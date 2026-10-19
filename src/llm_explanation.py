"""Optional Ollama explanation for one already-detected finding.

This module is deliberately outside the deterministic analysis workflow. It
uses only Python's standard library and never returns or mutates findings.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.rules import DISCLAIMER, Finding


OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen2.5:3b"
DEFAULT_TIMEOUT_SECONDS = 60
TIMEOUT_ENV_VAR = "UPI_SENTINEL_OLLAMA_TIMEOUT_SECONDS"
MAX_EXPLANATION_LENGTH = 1200

_EVIDENCE_FIELDS = (
    "transaction_id",
    "sender_id",
    "receiver_id",
    "amount",
    "transaction_type",
    "time",
)
_PROHIBITED_CLAIMS = re.compile(
    r"\b(?:proves?\s+(?:fraud|money laundering|mule)|"
    r"(?:is|are|was|were|definitely|confirmed(?:ly)?)\s+(?:fraudulent|fraud|a mule|mule accounts?)|"
    r"confirmed fraud)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExplanationResponse:
    text: str
    status: str  # "generated" or "fallback"
    detail: str | None = None


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def finding_evidence_payload(finding: Finding) -> dict[str, Any]:
    """Return a whitelist containing only this finding's minimal evidence."""
    records = [
        {field: _json_safe(record[field]) for field in _EVIDENCE_FIELDS if field in record}
        for record in finding.evidence
    ]
    return {
        "finding_id": finding.finding_id,
        "rule_name": finding.rule_name,
        "involved_account_ids": list(finding.involved_account_ids),
        "supporting_transaction_ids": list(finding.supporting_transaction_ids),
        "evidence": records,
        "relevant_times": _json_safe(finding.relevant_times),
        "configured_thresholds": _json_safe(finding.configured_thresholds),
        "measurements": _json_safe(finding.measurements),
    }


def deterministic_fallback(finding: Finding) -> str:
    """Explain a finding using only its recorded evidence and thresholds."""
    payload = finding_evidence_payload(finding)
    entries = []
    for record in payload["evidence"]:
        entries.append(
            f"{record.get('transaction_id', 'unknown transaction')}: "
            f"{record.get('sender_id', '?')} → {record.get('receiver_id', '?')}, "
            f"amount {record.get('amount', 'not recorded')}, "
            f"type {record.get('transaction_type', 'not recorded')}, "
            f"time {record.get('time', 'not recorded')}"
        )
    evidence_text = "; ".join(entries) if entries else "no transaction evidence was recorded"
    thresholds = json.dumps(payload["configured_thresholds"], sort_keys=True, ensure_ascii=False)
    return (
        f"The {finding.rule_name.replace('_', ' ')} rule matched finding {finding.finding_id}. "
        f"Recorded evidence: {evidence_text}. Configured thresholds: {thresholds}. "
        f"{DISCLAIMER}"
    )


def _validate_model_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Ollama response content was not text.")
    text = value.strip()
    if not text:
        raise ValueError("Ollama returned an empty explanation.")
    if len(text) > MAX_EXPLANATION_LENGTH:
        raise ValueError("Ollama explanation exceeded the length limit.")
    if _PROHIBITED_CLAIMS.search(text):
        raise ValueError("Ollama explanation made a prohibited fraud or mule claim.")
    return text


def _format_amount(value: Any) -> str | None:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite():
        return None
    formatted = f"{amount:,.12f}".rstrip("0").rstrip(".")
    return formatted


def _format_generated_explanation(value: str, finding: Finding) -> str:
    """Tidy prose and ground amount/time wording in this finding's evidence."""
    text = re.sub(r"\s+([,.!?;:])", r"\1", value.strip())
    # Repair common token glue such as "500.0and480.0" from generated prose.
    text = re.sub(
        r"(?P<left>\d+(?:\.\d+)?)(?P<link>and|or)(?P<right>\d+(?:\.\d+)?)",
        r"\g<left> \g<link> \g<right>",
        text,
        flags=re.IGNORECASE,
    )

    numeric_times = {
        Decimal(str(record["time"]))
        for record in finding.evidence
        if isinstance(record.get("time"), (int, float))
        and not isinstance(record.get("time"), bool)
    }
    has_datetime_evidence = any(
        isinstance(record.get("time"), (datetime, date))
        for record in finding.evidence
    )
    if numeric_times and not has_datetime_evidence:
        def replace_hour(match: re.Match[str]) -> str:
            quantity = match.group("quantity")
            try:
                singular = Decimal(quantity) == 1
            except InvalidOperation:
                singular = False
            return f"{quantity} time {'unit' if singular else 'units'}"

        text = re.sub(
            r"(?P<quantity>\d+(?:\.\d+)?)\s+hours?\b",
            replace_hour,
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\ban hour\b", "a time unit", text, flags=re.IGNORECASE)

    # Format only amounts present in this finding. Skip values that are also
    # numeric timestamps, where the same literal could refer to either field.
    for record in finding.evidence:
        amount_text = _format_amount(record.get("amount"))
        if amount_text is None:
            continue
        try:
            amount_value = Decimal(str(record.get("amount")))
        except InvalidOperation:
            continue
        if amount_value in numeric_times:
            continue
        raw = str(record.get("amount"))
        variants = sorted({raw, amount_text}, key=len, reverse=True)
        alternatives = "|".join(re.escape(item) for item in variants)
        text = re.sub(
            rf"(?<![\w.,-])(?:{alternatives})(?![\w.,-])",
            amount_text,
            text,
        )

    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _resolve_timeout(timeout: float | None) -> float:
    """Resolve an explicit timeout or the environment-configured local default."""
    if timeout is None:
        configured = os.getenv(TIMEOUT_ENV_VAR)
        timeout = DEFAULT_TIMEOUT_SECONDS if configured is None else float(configured)
    resolved = float(timeout)
    if not math.isfinite(resolved) or resolved <= 0:
        raise ValueError(f"Ollama timeout must be a positive finite number of seconds ({TIMEOUT_ENV_VAR}).")
    return resolved


def explain_finding_with_ollama(
    finding: Finding,
    *,
    timeout: float | None = None,
) -> ExplanationResponse:
    """Ask local Ollama to explain one finding; safely fall back on any failure."""
    fallback = deterministic_fallback(finding)
    payload = finding_evidence_payload(finding)
    system_prompt = (
        "You explain one existing deterministic transaction-pattern finding for a human reviewer. "
        "Use only the JSON evidence provided by the user. Never invent transactions, account behavior, "
        "amounts, times, motives, or facts. Do not create or alter findings, severity, or classifications. "
        "Never state or imply that fraud or mule-account activity is proven. Describe only the observed "
        "pattern and its evidence, in at most three concise sentences. Use readable spacing and punctuation. "
        "Format amounts with thousands separators and omit unnecessary trailing zeros. Preserve numeric "
        "time values and call their unit 'time unit(s)', not hours; use hours only when timestamps are datetimes. "
        "If the evidence is insufficient, say so."
    )
    request_body = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    }
    request = Request(
        OLLAMA_CHAT_URL,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        request_timeout = _resolve_timeout(timeout)
        with urlopen(request, timeout=request_timeout) as response:
            response_data = json.loads(response.read().decode("utf-8"))
        model_text = response_data["message"]["content"]
        explanation = _format_generated_explanation(_validate_model_text(model_text), finding)
        return ExplanationResponse(text=explanation, status="generated")
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError,
            KeyError, TypeError, ValueError) as error:
        return ExplanationResponse(
            text=fallback,
            status="fallback",
            detail=f"Local Ollama explanation unavailable: {error}",
        )
