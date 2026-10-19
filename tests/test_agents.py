from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import pytest

from src.agents import (
    CoordinatorAgent,
    EvaluationAgent,
    NetworkAnalysisAgent,
    PatternAnalysisAgent,
    WorkflowError,
    run_analysis,
)
from src.generate_synthetic import generate_synthetic_transactions
from src.langgraph_workflow import build_analysis_graph


def test_end_to_end_workflow_on_synthetic_fixture() -> None:
    fixture = generate_synthetic_transactions()
    result = run_analysis(fixture)

    assert result.status == "completed"
    assert result.validation_counts == {
        "input_rows": 40,
        "accepted_rows": 31,
        "rejected_rows": 9,
        "schema_errors": [],
    }
    assert result.graph_summary.account_count == result.graph.number_of_nodes()
    assert result.graph_summary.transaction_count == 31
    assert len(result.rejected_rows) == 9
    assert result.rejected_rows["source_row"].notna().all()
    assert result.evaluation.status == "available"
    assert result.evaluation.unit == "transaction"


def test_fixture_s2_s3_have_leads_and_s1_s5_s6_do_not() -> None:
    fixture = generate_synthetic_transactions()
    results = {
        scenario: run_analysis(fixture.loc[fixture.scenario_id == scenario])
        for scenario in ("S1", "S2", "S3", "S5", "S6")
    }
    assert any(f.rule_name == "rapid_transfer_chain" for f in results["S2"].findings)
    assert any(f.rule_name == "shared_intermediary" for f in results["S3"].findings)
    assert all(not results[s].findings for s in ("S1", "S5", "S6"))


def test_empty_input_and_missing_columns_complete_with_clear_status() -> None:
    empty = run_analysis(pd.DataFrame(columns=[
        "transaction_id", "time", "sender_id", "receiver_id", "amount", "transaction_type"
    ]))
    assert empty.status == "completed"
    assert empty.validation_counts["input_rows"] == 0
    assert empty.graph_summary.account_count == 0
    assert not empty.findings
    assert empty.evaluation.status == "unavailable"

    malformed_schema = run_analysis(pd.DataFrame({"transaction_id": ["r1"]}))
    assert malformed_schema.status == "completed"
    assert malformed_schema.validation_counts["accepted_rows"] == 0
    assert malformed_schema.validation_counts["rejected_rows"] == 1
    assert malformed_schema.validation_counts["schema_errors"]
    assert malformed_schema.stage_trace[0].status == "completed_with_schema_errors"
    assert malformed_schema.graph.number_of_edges() == 0


def test_all_rejected_data_is_retained_and_evaluation_unavailable() -> None:
    fixture = generate_synthetic_transactions()
    invalid = fixture.loc[fixture.scenario_id == "S4"]
    result = run_analysis(invalid)
    assert result.validation_counts["accepted_rows"] == 0
    assert result.validation_counts["rejected_rows"] == 9
    assert result.rejected_rows["rejection_reasons"].map(bool).all()
    assert result.graph.number_of_edges() == 0
    assert result.findings == []
    assert result.evaluation.status == "unavailable"


def test_missing_labels_return_explicit_unavailable_evaluation() -> None:
    fixture = generate_synthetic_transactions().drop(columns=["label"])
    result = run_analysis(fixture)
    assert result.evaluation.status == "unavailable"
    assert result.evaluation.metrics is None
    assert "No evaluation label column" in result.evaluation.reason


def test_labels_do_not_change_graph_or_findings() -> None:
    fixture = generate_synthetic_transactions()
    original = run_analysis(fixture)
    changed = fixture.copy()
    changed["label"] = ["not-a-binary-label"] * len(changed)
    altered = run_analysis(changed)

    assert list(original.graph.edges(keys=True, data=True)) == list(
        altered.graph.edges(keys=True, data=True)
    )
    assert asdict(original.graph_summary) == asdict(altered.graph_summary)
    assert [f.to_dict() for f in original.findings] == [f.to_dict() for f in altered.findings]
    assert altered.evaluation.status == "unavailable"


def test_evaluation_agent_runs_after_pattern_detection() -> None:
    order: list[str] = []

    class OrderedPatternAgent(PatternAnalysisAgent):
        def run(self, graph, config=None):
            findings = super().run(graph, config)
            assert findings
            order.append("pattern_complete")
            return findings

    class OrderedEvaluationAgent(EvaluationAgent):
        def run(self, accepted_rows, findings):
            assert order == ["pattern_complete"]
            order.append("evaluation")
            return super().run(accepted_rows, findings)

    generated = generate_synthetic_transactions()
    fixture = generated.loc[generated.scenario_id == "S2"]
    coordinator = CoordinatorAgent(
        pattern_agent=OrderedPatternAgent(), evaluation_agent=OrderedEvaluationAgent()
    )
    result = coordinator.run(fixture)
    assert order == ["pattern_complete", "evaluation"]
    assert [stage.stage for stage in result.stage_trace] == [
        "data_validation", "network_analysis", "pattern_analysis", "explanation", "evaluation"
    ]


def test_evaluation_metric_definition_and_unavailable_reasons() -> None:
    fixture = generate_synthetic_transactions()
    result = run_analysis(fixture)
    metrics = result.evaluation.metrics
    assert metrics is not None
    assert set(metrics["confusion_counts"]) == {
        "true_positive", "false_positive", "true_negative", "false_negative"
    }
    assert metrics["transaction_count"] == 31
    assert "account-level mule" in result.evaluation.reason

    single_class = fixture.loc[fixture.scenario_id == "S1"]
    unavailable = run_analysis(single_class)
    assert unavailable.evaluation.status == "unavailable"
    assert "Both reference classes" in unavailable.evaluation.reason


def test_explanation_uses_actual_counts_and_findings() -> None:
    fixture = generate_synthetic_transactions()
    result = run_analysis(fixture)
    assert "31 of 40 rows accepted; 9 rejected" in result.human_readable_summary
    assert f"{result.graph_summary.account_count} accounts" in result.human_readable_summary
    assert f"{len(result.findings)} investigation lead(s)" in result.human_readable_summary
    assert "not proof of fraud" in result.human_readable_summary

    empty = run_analysis(fixture.loc[fixture.scenario_id == "S1"])
    assert "No configured patterns matched" in empty.human_readable_summary


def test_stage_trace_records_rejections_and_evaluation_unavailability() -> None:
    fixture = generate_synthetic_transactions()
    result = run_analysis(fixture)
    assert [stage.stage for stage in result.stage_trace] == [
        "data_validation", "network_analysis", "pattern_analysis", "explanation", "evaluation"
    ]
    assert result.stage_trace[0].status == "completed_with_rejections"
    assert result.stage_trace[1].status == "completed"
    assert "37 accounts" in result.stage_trace[1].message
    assert "5 evidence-backed finding(s)" in result.stage_trace[2].message
    assert result.stage_trace[-1].status == "completed"

    no_label = run_analysis(fixture.drop(columns=["label"]))
    assert no_label.stage_trace[-1].status == "unavailable"


def test_stage_failure_is_reported_with_trace_and_cause() -> None:
    class BrokenNetworkAgent(NetworkAnalysisAgent):
        def run(self, validation):
            raise ValueError("deliberate graph-stage failure")

    coordinator = CoordinatorAgent(network_agent=BrokenNetworkAgent())
    with pytest.raises(WorkflowError, match="network_analysis.*deliberate graph-stage failure") as error:
        coordinator.run(generate_synthetic_transactions())
    assert error.value.stage == "network_analysis"
    assert [stage.status for stage in error.value.stage_trace] == ["completed_with_rejections", "failed"]
    assert isinstance(error.value.__cause__, ValueError)


def test_identical_input_and_configuration_are_reproducible() -> None:
    fixture = generate_synthetic_transactions()
    first = run_analysis(fixture)
    second = run_analysis(fixture.copy())
    assert first.validation_counts == second.validation_counts
    assert asdict(first.graph_summary) == asdict(second.graph_summary)
    assert [finding.to_dict() for finding in first.findings] == [
        finding.to_dict() for finding in second.findings
    ]
    assert first.human_readable_summary == second.human_readable_summary
    assert first.evaluation.metrics == second.evaluation.metrics


def test_langgraph_compiles_the_ordered_agent_stages() -> None:
    workflow = build_analysis_graph(CoordinatorAgent())
    graph = workflow.get_graph()

    assert set(graph.nodes) == {
        "__start__",
        "data_validation",
        "network_analysis",
        "pattern_analysis",
        "explanation",
        "evaluation",
        "__end__",
    }
    assert {(edge.source, edge.target) for edge in graph.edges} == {
        ("__start__", "data_validation"),
        ("data_validation", "network_analysis"),
        ("network_analysis", "pattern_analysis"),
        ("pattern_analysis", "explanation"),
        ("explanation", "evaluation"),
        ("evaluation", "__end__"),
    }


def test_public_analysis_entrypoint_runs_through_langgraph(monkeypatch) -> None:
    import src.langgraph_workflow as orchestration

    real_runner = orchestration.run_langgraph_workflow
    calls: list[str] = []

    def observed_runner(coordinator, raw_dataframe, config=None):
        calls.append("langgraph")
        return real_runner(coordinator, raw_dataframe, config)

    monkeypatch.setattr(orchestration, "run_langgraph_workflow", observed_runner)
    result = run_analysis(generate_synthetic_transactions())

    assert calls == ["langgraph"]
    assert result.status == "completed"
    assert [stage.stage for stage in result.stage_trace] == [
        "data_validation",
        "network_analysis",
        "pattern_analysis",
        "explanation",
        "evaluation",
    ]
