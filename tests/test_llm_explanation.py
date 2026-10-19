from __future__ import annotations

import json
import socket
from typing import Any
from urllib.error import URLError

import pytest

from src.agents import run_analysis
from src.generate_synthetic import generate_synthetic_transactions
from src.llm_explanation import (
    OLLAMA_CHAT_URL,
    OLLAMA_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    TIMEOUT_ENV_VAR,
    deterministic_fallback,
    explain_finding_with_ollama,
    finding_evidence_payload,
)
from src.rules import DISCLAIMER


@pytest.fixture
def finding():
    result = run_analysis(generate_synthetic_transactions())
    return result.findings[0]


class FakeResponse:
    def __init__(self, value: Any):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.value).encode("utf-8")


def test_success_uses_local_api_and_only_selected_finding_evidence(monkeypatch, finding) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({
            "model": OLLAMA_MODEL,
            "created_at": "2026-10-19T00:00:00Z",
            "message": {"role": "assistant", "content": "The listed transfers form a rapid sequence."},
            "done": True,
        })

    monkeypatch.setattr("src.llm_explanation.urlopen", fake_urlopen)
    result = explain_finding_with_ollama(finding)

    assert captured["url"] == OLLAMA_CHAT_URL
    assert captured["body"]["model"] == OLLAMA_MODEL
    assert captured["timeout"] == DEFAULT_TIMEOUT_SECONDS
    assert captured["body"]["stream"] is False
    sent = json.loads(captured["body"]["messages"][1]["content"])
    assert sent == finding_evidence_payload(finding)
    assert "source_row" not in json.dumps(sent)
    assert "label" not in json.dumps(sent)
    assert result.status == "generated"
    assert result.text == "The listed transfers form a rapid sequence."


def test_timeout_can_be_configured_for_local_ollama(monkeypatch, finding) -> None:
    monkeypatch.setenv(TIMEOUT_ENV_VAR, "42")
    observed = {}

    def fake_urlopen(request, timeout):
        observed["timeout"] = timeout
        return FakeResponse({"message": {"content": "The listed transfers form a rapid sequence."}})

    monkeypatch.setattr("src.llm_explanation.urlopen", fake_urlopen)
    result = explain_finding_with_ollama(finding)
    assert result.status == "generated"
    assert observed["timeout"] == 42.0


def test_generated_explanation_formats_amounts_and_numeric_time_units(monkeypatch, finding) -> None:
    monkeypatch.setattr(
        "src.llm_explanation.urlopen",
        lambda *args, **kwargs: FakeResponse({
            "message": {
                "content": "Transfers of 500.0and480.0 occurred within 1 hour"
            }
        }),
    )

    result = explain_finding_with_ollama(finding)

    assert result.status == "generated"
    assert result.text == "Transfers of 500 and 480 occurred within 1 time unit."


@pytest.mark.parametrize(
    "failure",
    [URLError("server unavailable"), socket.timeout("timed out")],
)
def test_api_failure_and_timeout_return_deterministic_fallback(monkeypatch, finding, failure) -> None:
    monkeypatch.setattr("src.llm_explanation.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(failure))
    result = explain_finding_with_ollama(finding)
    assert result.status == "fallback"
    assert result.text == deterministic_fallback(finding)
    assert DISCLAIMER in result.text
    assert result.detail and "unavailable" in result.detail


def test_empty_model_output_returns_fallback(monkeypatch, finding) -> None:
    monkeypatch.setattr(
        "src.llm_explanation.urlopen",
        lambda *args, **kwargs: FakeResponse({"message": {"content": "  "}}),
    )
    result = explain_finding_with_ollama(finding)
    assert result.status == "fallback"
    assert result.text == deterministic_fallback(finding)


def test_timeout_while_reading_response_returns_fallback(monkeypatch, finding) -> None:
    class TimeoutResponse(FakeResponse):
        def read(self) -> bytes:
            raise socket.timeout("response generation timed out")

    monkeypatch.setattr(
        "src.llm_explanation.urlopen",
        lambda *args, **kwargs: TimeoutResponse({}),
    )
    result = explain_finding_with_ollama(finding)
    assert result.status == "fallback"
    assert result.text == deterministic_fallback(finding)
    assert result.detail and "timed out" in result.detail


def test_malformed_response_returns_fallback(monkeypatch, finding) -> None:
    monkeypatch.setattr("src.llm_explanation.urlopen", lambda *args, **kwargs: FakeResponse({"message": {}}))
    result = explain_finding_with_ollama(finding)
    assert result.status == "fallback"
    assert result.text == deterministic_fallback(finding)


def test_prohibited_fraud_claim_returns_fallback(monkeypatch, finding) -> None:
    monkeypatch.setattr(
        "src.llm_explanation.urlopen",
        lambda *args, **kwargs: FakeResponse({"message": {"content": "This proves fraud."}}),
    )
    result = explain_finding_with_ollama(finding)
    assert result.status == "fallback"
    assert result.text == deterministic_fallback(finding)
