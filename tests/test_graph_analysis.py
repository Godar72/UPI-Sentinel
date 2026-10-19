from __future__ import annotations

from datetime import datetime

import networkx as nx
import pandas as pd

from src.generate_synthetic import generate_synthetic_transactions
from src.graph_analysis import analyze_transactions, build_account_graph, summarize_graph
from src.rules import DISCLAIMER, RuleConfig


def tx(txid, time, sender, receiver, amount, label=0, kind="P2P"):
    return {
        "transaction_id": txid,
        "time": time,
        "sender_id": sender,
        "receiver_id": receiver,
        "amount": amount,
        "transaction_type": kind,
        "label": label,
    }


def frame(*rows) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_graph_preserves_parallel_transaction_evidence_and_summary() -> None:
    transactions = frame(
        tx("T1", 1, "A", "B", 10),
        tx("T2", 2, "A", "B", 12, kind="REFUND"),
        tx("T3", 3, "B", "C", 5),
    )
    graph = build_account_graph(transactions)
    assert isinstance(graph, nx.MultiDiGraph)
    assert graph.number_of_edges("A", "B") == 2
    assert graph["A"]["B"]["T1"]["amount"] == 10
    assert graph["A"]["B"]["T2"]["transaction_type"] == "REFUND"
    assert graph["A"]["B"]["T2"]["time"] == 2
    summary = summarize_graph(graph)
    assert (summary.account_count, summary.transaction_count) == (3, 3)
    assert summary.account_activity["A"].outgoing_transactions == 2
    assert summary.account_activity["A"].outgoing_amount == 22
    assert summary.account_activity["B"].incoming_transactions == 2


def test_rapid_chain_rule_returns_complete_evidence() -> None:
    result = analyze_transactions(
        frame(tx("CHAIN-1", 10, "A", "B", 100), tx("CHAIN-2", 11, "B", "C", 90))
    )
    findings = [f for f in result.findings if f.rule_name == "rapid_transfer_chain"]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.supporting_transaction_ids == ("CHAIN-1", "CHAIN-2")
    assert finding.involved_account_ids == ("A", "B", "C")
    assert tuple(record["amount"] for record in finding.evidence) == (100, 90)
    assert finding.relevant_times == (10, 11)
    assert finding.configured_thresholds["max_elapsed_time_units_or_hours"] == 2
    assert finding.measurements["elapsed_time_units_or_hours"] == 1
    assert "1 time units/hours" in finding.explanation
    assert finding.status == DISCLAIMER


def test_shared_intermediary_requires_multiple_senders_and_onward_transfer() -> None:
    result = analyze_transactions(
        frame(
            tx("IN-A", 10, "A", "HUB", 30),
            tx("IN-B", 11, "B", "HUB", 40),
            tx("OUT", 12, "HUB", "C", 50),
        )
    )
    findings = [f for f in result.findings if f.rule_name == "shared_intermediary"]
    assert len(findings) == 1
    finding = findings[0]
    assert set(finding.supporting_transaction_ids) == {"IN-A", "IN-B", "OUT"}
    assert "HUB" in finding.involved_account_ids
    assert finding.configured_thresholds["min_distinct_senders"] == 2


def test_onward_rule_uses_aggregate_window_ratio_and_disclaims_tracing() -> None:
    result = analyze_transactions(
        frame(
            tx("IN-1", 1, "A", "B", 100),
            tx("IN-2", 2, "C", "B", 50),
            tx("OUT", 3, "B", "D", 120),
        )
    )
    findings = [f for f in result.findings if f.rule_name == "substantial_onward_transfer"]
    assert len(findings) == 1
    finding = findings[0]
    assert set(finding.supporting_transaction_ids) == {"IN-1", "IN-2", "OUT"}
    assert finding.configured_thresholds["min_outgoing_to_recent_incoming_ratio"] == 0.8
    assert finding.measurements["recent_incoming_total"] == 150
    assert finding.measurements["outgoing_to_incoming_ratio"] == 0.8
    assert "80.0%" in finding.explanation
    assert "does not establish that the same funds" in finding.explanation


def test_synthetic_normal_and_high_volume_merchant_controls_do_not_flag() -> None:
    generated = generate_synthetic_transactions()
    for scenario in ("S1", "S5"):
        result = analyze_transactions(generated.loc[generated.scenario_id == scenario])
        assert result.findings == []
        assert len(result.validation.rejected_rows) == 0


def test_existing_synthetic_chain_and_common_intermediary_scenarios_match() -> None:
    generated = generate_synthetic_transactions()
    rapid = analyze_transactions(generated.loc[generated.scenario_id == "S2"])
    shared = analyze_transactions(generated.loc[generated.scenario_id == "S3"])
    assert any(f.rule_name == "rapid_transfer_chain" for f in rapid.findings)
    assert any(f.rule_name == "shared_intermediary" for f in shared.findings)


def test_invalid_rows_and_duplicate_ids_are_excluded_from_graph() -> None:
    transactions = frame(
        tx("GOOD", 1, "A", "B", 10),
        tx("BAD-AMOUNT", 2, "B", "C", "oops"),
        tx("DUP", 3, "B", "D", 5),
        tx("DUP", 4, "B", "E", 5),
    )
    result = analyze_transactions(transactions)
    assert result.graph.number_of_edges() == 1
    assert result.graph.has_edge("A", "B")
    assert not result.graph.has_node("C")
    assert result.graph.graph["rejected_row_count"] == 3
    assert result.validation.rejected_rows["source_row"].tolist() == [2, 3, 4]


def test_missing_columns_and_empty_input_are_safe() -> None:
    missing_columns = analyze_transactions(pd.DataFrame({"transaction_id": ["x"]}))
    assert missing_columns.graph.number_of_nodes() == 0
    assert missing_columns.graph.number_of_edges() == 0
    assert missing_columns.findings == []
    assert missing_columns.validation.schema_errors

    empty = analyze_transactions(pd.DataFrame(columns=[
        "transaction_id", "time", "sender_id", "receiver_id", "amount", "transaction_type"
    ]))
    assert empty.graph.number_of_nodes() == 0
    assert empty.findings == []


def test_same_time_and_out_of_order_transfers_do_not_form_chain() -> None:
    for pair in (
        (tx("T1", 5, "A", "B", 10), tx("T2", 5, "B", "C", 10)),
        (tx("T1", 6, "A", "B", 10), tx("T2", 5, "B", "C", 10)),
    ):
        result = analyze_transactions(frame(*pair))
        assert not [f for f in result.findings if f.rule_name == "rapid_transfer_chain"]


def test_datetime_window_uses_hours_and_low_activity_graph_is_safe() -> None:
    result = analyze_transactions(
        frame(
            tx("T1", datetime.fromisoformat("2026-01-01T00:00:00"), "A", "B", 100),
            tx("T2", datetime.fromisoformat("2026-01-01T01:00:00"), "B", "C", 90),
        )
    )
    assert any(f.rule_name == "rapid_transfer_chain" for f in result.findings)
    result.graph.add_node("ISOLATED")
    summary = summarize_graph(result.graph)
    assert summary.account_activity["ISOLATED"].incoming_transactions == 0
    assert summary.account_activity["ISOLATED"].outgoing_transactions == 0


def test_findings_have_unique_ids_and_traceable_evidence() -> None:
    result = analyze_transactions(
        frame(
            tx("A-IN", 1, "A", "HUB", 30),
            tx("B-IN", 2, "B", "HUB", 40),
            tx("H-OUT", 3, "HUB", "C", 60),
        )
    )
    ids = [finding.finding_id for finding in result.findings]
    assert len(ids) == len(set(ids))
    for finding in result.findings:
        assert all(txid in {e["transaction_id"] for e in finding.evidence}
                   for txid in finding.supporting_transaction_ids)
        assert all(e["source_row"] for e in finding.evidence)
        assert finding.status == DISCLAIMER


def test_changing_evaluation_labels_does_not_change_findings() -> None:
    data = frame(tx("T1", 1, "A", "B", 100, label=0), tx("T2", 2, "B", "C", 90, label=0))
    changed_labels = data.copy()
    changed_labels["label"] = ["arbitrary", 999]
    first = analyze_transactions(data).findings
    second = analyze_transactions(changed_labels).findings
    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]


def test_duplicate_ids_cannot_form_a_chain_even_if_account_edges_look_linked() -> None:
    result = analyze_transactions(
        frame(tx("REUSED", 1, "A", "B", 100), tx("REUSED", 2, "B", "C", 90))
    )
    assert result.graph.number_of_edges() == 0
    assert result.findings == []


def test_rule_config_rejects_invalid_thresholds() -> None:
    import pytest

    with pytest.raises(ValueError):
        RuleConfig(rapid_chain_window=0)
