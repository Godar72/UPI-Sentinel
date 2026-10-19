from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import networkx as nx
import pandas as pd
import pytest

import app
from app import load_bundled_fixture, parse_uploaded_csv
from src.agents import run_analysis
from src.visualization import create_network_figure


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_fixture_loader_reads_bundled_csv_file() -> None:
    actual_path = PROJECT_ROOT / "data" / "samples" / "synthetic_transactions.csv"
    expected = pd.read_csv(actual_path)
    loaded = load_bundled_fixture(actual_path)
    pd.testing.assert_frame_equal(loaded, expected)


def test_uploaded_csv_parser_uses_same_workflow_contract() -> None:
    source = load_bundled_fixture().drop(columns=["scenario_id"])
    uploaded = parse_uploaded_csv(source.to_csv(index=False).encode("utf-8"))
    assert list(uploaded.columns) == list(source.columns)
    result = run_analysis(uploaded)
    assert result.validation_counts["input_rows"] == len(uploaded)
    assert result.validation_counts["accepted_rows"] > 0


def test_empty_network_figure_is_safe() -> None:
    visual = create_network_figure(nx.MultiDiGraph())
    assert visual.total_accounts == 0
    assert visual.total_transactions == 0
    assert visual.displayed_accounts == 0
    assert visual.displayed_transactions == 0


def test_network_figure_reports_truncation_for_large_input() -> None:
    graph = nx.MultiDiGraph()
    graph.add_edge("A", "B", key="T1", transaction_id="T1", amount=1,
                   transaction_type="P2P", time=1)
    graph.add_edge("A", "C", key="T2", transaction_id="T2", amount=2,
                   transaction_type="P2P", time=2)
    graph.add_edge("B", "C", key="T3", transaction_id="T3", amount=3,
                   transaction_type="P2P", time=3)
    visual = create_network_figure(graph, max_nodes=2, max_edges=1)
    assert visual.total_accounts == 3
    assert visual.total_transactions == 3
    assert visual.displayed_accounts == 2
    assert visual.displayed_transactions == 1
    assert len(visual.figure.layout.annotations) == 1


def test_network_visualization_rejects_nonpositive_limits() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        create_network_figure(nx.MultiDiGraph(), max_nodes=0)


def test_network_visualization_highlights_selected_transaction_evidence() -> None:
    graph = nx.MultiDiGraph()
    graph.add_edge("A", "B", key="T1", transaction_id="T1", amount=1,
                   transaction_type="P2P", time=1)
    graph.add_edge("B", "C", key="T2", transaction_id="T2", amount=2,
                   transaction_type="P2P", time=2)
    visual = create_network_figure(
        graph, highlighted_transaction_ids=("T2",), highlighted_accounts=("A", "B")
    )
    selected = next(trace for trace in visual.figure.data if trace.name == "Selected evidence")
    assert len(selected.x) == 3
    account_trace = next(trace for trace in visual.figure.data if trace.name == "Accounts")
    assert "A" in account_trace.text and "B" in account_trace.text
    assert visual.total_transactions == 2


def test_inspect_evidence_uses_callback_to_change_navigation(monkeypatch) -> None:
    state = SimpleNamespace(page="Overview", selected_finding=None)
    finding = SimpleNamespace(
        involved_account_ids=("A", "B"),
        measurements={"elapsed_time": 1.0},
        finding_id="finding-1",
        rule_name="rapid_transfer_chain",
        supporting_transaction_ids=("T1", "T2"),
    )
    clicked = {}

    monkeypatch.setattr(app.st, "session_state", state)
    monkeypatch.setattr(app.st, "markdown", lambda *args, **kwargs: None)

    def fake_button(*args, **kwargs):
        clicked.update(kwargs)
        kwargs["on_click"](*kwargs.get("args", ()))
        return True

    monkeypatch.setattr(app.st, "button", fake_button)
    app._finding_card(finding, 0)

    assert clicked["on_click"] is app._navigate_to_finding
    assert state.page == "Investigations"
    assert state.selected_finding == "finding-1"


def test_methodology_time_units_follow_actual_time_representation() -> None:
    numeric = pd.DataFrame({"time": [100.0, 101.0]})
    dated = pd.DataFrame({"time": pd.to_datetime(["2026-01-01T00:00:00", "2026-01-01T01:00:00"])})

    assert app._time_unit_label(numeric) == "numeric time units"
    assert app._time_unit_label(dated) == "hours from datetime timestamps"
