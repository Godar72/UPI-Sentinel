"""LangGraph orchestration for the deterministic UPI Sentinel agents.

The graph coordinates ordinary Python components; it does not call an LLM or
external service. Detection stays label-independent, and evaluation runs only
after the pattern and explanation stages have completed.
"""

from __future__ import annotations

from typing import Any, Callable, TypedDict

import networkx as nx
import pandas as pd
from langgraph.graph import END, START, StateGraph

from src.rules import Finding, RuleConfig
from src.validation import ValidationResult
from src.graph_analysis import GraphSummary


class AnalysisState(TypedDict, total=False):
    """State values passed between ordered LangGraph nodes."""

    raw_dataframe: pd.DataFrame
    config: RuleConfig | None
    validation: ValidationResult
    graph: nx.MultiDiGraph
    graph_summary: GraphSummary
    findings: list[Finding]
    human_readable_summary: str
    evaluation: Any
    stage_trace: list[Any]


def build_analysis_graph(coordinator: Any):
    """Compile the workflow using the agents owned by ``coordinator``."""
    # Local imports avoid a module cycle: CoordinatorAgent calls this builder
    # after src.agents has finished defining the shared result types.
    from src.agents import WorkflowError, WorkflowStage

    def make_node(
        stage_name: str,
        action: Callable[[AnalysisState], tuple[dict[str, Any], str, str]],
    ) -> Callable[[AnalysisState], dict[str, Any]]:
        def node(state: AnalysisState) -> dict[str, Any]:
            trace = list(state.get("stage_trace", []))
            try:
                updates, status, message = action(state)
            except Exception as exc:
                trace.append(WorkflowStage(stage_name, "failed", str(exc)))
                raise WorkflowError(stage_name, str(exc), trace) from exc

            trace.append(WorkflowStage(stage_name, status, message))
            updates["stage_trace"] = trace
            return updates

        return node

    def validate(state: AnalysisState) -> tuple[dict[str, Any], str, str]:
        result = coordinator.validation_agent.run(state["raw_dataframe"])
        if result.schema_errors:
            return (
                {"validation": result},
                "completed_with_schema_errors",
                "; ".join(result.schema_errors),
            )
        if not result.rejected_rows.empty:
            return (
                {"validation": result},
                "completed_with_rejections",
                f"Accepted {len(result.valid_rows)} rows; rejected "
                f"{len(result.rejected_rows)} rows with reasons retained.",
            )
        return (
            {"validation": result},
            "completed",
            f"Accepted all {len(result.valid_rows)} input rows.",
        )

    def analyze_network(state: AnalysisState) -> tuple[dict[str, Any], str, str]:
        graph, summary = coordinator.network_agent.run(state["validation"])
        return (
            {"graph": graph, "graph_summary": summary},
            "completed",
            f"Built accepted-only graph: {summary.account_count} accounts, "
            f"{summary.transaction_count} transactions.",
        )

    def analyze_patterns(state: AnalysisState) -> tuple[dict[str, Any], str, str]:
        findings = coordinator.pattern_agent.run(state["graph"], state.get("config"))
        return (
            {"findings": findings},
            "completed",
            f"Generated {len(findings)} evidence-backed finding(s).",
        )

    def explain(state: AnalysisState) -> tuple[dict[str, Any], str, str]:
        summary = coordinator.explanation_agent.run(
            state["validation"], state["graph_summary"], state["findings"]
        )
        return (
            {"human_readable_summary": summary},
            "completed",
            "Prepared summary from validation, graph, and findings.",
        )

    def evaluate(state: AnalysisState) -> tuple[dict[str, Any], str, str]:
        # This is the first stage that receives reference labels. Findings and
        # graph outputs are already complete and are not modified here.
        result = coordinator.evaluation_agent.run(
            state["validation"].valid_rows, state["findings"]
        )
        if result.status == "unavailable":
            return {"evaluation": result}, "unavailable", result.reason
        return (
            {"evaluation": result},
            "completed",
            "Computed transaction-level comparison after pattern findings were generated.",
        )

    builder = StateGraph(AnalysisState)
    builder.add_node("data_validation", make_node("data_validation", validate))
    builder.add_node("network_analysis", make_node("network_analysis", analyze_network))
    builder.add_node("pattern_analysis", make_node("pattern_analysis", analyze_patterns))
    builder.add_node("explanation", make_node("explanation", explain))
    builder.add_node("evaluation", make_node("evaluation", evaluate))

    builder.add_edge(START, "data_validation")
    builder.add_edge("data_validation", "network_analysis")
    builder.add_edge("network_analysis", "pattern_analysis")
    builder.add_edge("pattern_analysis", "explanation")
    builder.add_edge("explanation", "evaluation")
    builder.add_edge("evaluation", END)
    return builder.compile()


def run_langgraph_workflow(
    coordinator: Any,
    raw_dataframe: pd.DataFrame,
    config: RuleConfig | None = None,
) -> AnalysisState:
    """Run the compiled graph and keep the coordinator's public stage trace."""
    from src.agents import WorkflowError

    workflow = build_analysis_graph(coordinator)
    initial_state: AnalysisState = {
        "raw_dataframe": raw_dataframe,
        "config": config,
        "stage_trace": [],
    }
    try:
        result = workflow.invoke(initial_state)
    except WorkflowError as exc:
        coordinator.stage_trace = list(exc.stage_trace)
        raise
    coordinator.stage_trace = list(result["stage_trace"])
    return result
