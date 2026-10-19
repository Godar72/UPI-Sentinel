"""Deterministic multi-agent orchestration for UPI Sentinel.

These are ordinary Python components with bounded responsibilities, not
autonomous LLM agents. All analysis is deterministic and runs locally.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import Any

import networkx as nx
import pandas as pd

from src.graph_analysis import GraphSummary, build_account_graph, summarize_graph
from src.rules import Finding, RuleConfig, detect_patterns
from src.schema import LABEL, TRANSACTION_ID
from src.validation import ValidationResult, validate_transactions


@dataclass
class WorkflowStage:
    stage: str
    status: str
    message: str


@dataclass
class EvaluationResult:
    status: str
    reason: str
    unit: str = "transaction"
    positive_label: int = 1
    predicted_positive_definition: str = (
        "A transaction is predicted positive if its transaction ID appears in "
        "the evidence of at least one generated finding."
    )
    metrics: dict[str, Any] | None = None


@dataclass
class WorkflowResult:
    status: str
    validation_counts: dict[str, Any]
    accepted_rows: pd.DataFrame
    rejected_rows: pd.DataFrame
    graph: nx.MultiDiGraph
    graph_summary: GraphSummary
    findings: list[Finding]
    human_readable_summary: str
    evaluation: EvaluationResult
    stage_trace: list[WorkflowStage]


class WorkflowError(RuntimeError):
    """A workflow stage failed; includes stage name and completed trace."""

    def __init__(self, stage: str, message: str, stage_trace: list[WorkflowStage]):
        self.stage = stage
        self.stage_trace = list(stage_trace)
        super().__init__(f"Workflow stage '{stage}' failed: {message}")


class DataValidationAgent:
    """Runs the existing canonical schema validator and returns row details."""

    name = "data_validation"

    def run(self, raw_dataframe: pd.DataFrame) -> ValidationResult:
        return validate_transactions(raw_dataframe)


class NetworkAnalysisAgent:
    """Builds the accepted-only directed account graph and graph summary."""

    name = "network_analysis"

    def run(self, validation: ValidationResult) -> tuple[nx.MultiDiGraph, GraphSummary]:
        graph = build_account_graph(validation.valid_rows)
        # Preserve validation-agent rejection provenance in the shared graph result.
        graph.graph["rejected_row_count"] = len(validation.rejected_rows)
        graph.graph["rejected_source_rows"] = (
            validation.rejected_rows["source_row"].tolist()
            if "source_row" in validation.rejected_rows.columns
            else []
        )
        return graph, summarize_graph(graph)


class PatternAnalysisAgent:
    """Runs the existing deterministic, label-independent graph rules."""

    name = "pattern_analysis"

    def run(self, graph: nx.MultiDiGraph, config: RuleConfig | None = None) -> list[Finding]:
        return detect_patterns(graph, config)


class ExplanationAgent:
    """Summarizes observed counts and findings without adding classifications."""

    name = "explanation"

    def run(
        self,
        validation: ValidationResult,
        graph_summary: GraphSummary,
        findings: list[Finding],
    ) -> str:
        total = len(validation.valid_rows) + len(validation.rejected_rows)
        parts = [
            f"Input review: {len(validation.valid_rows)} of {total} rows accepted; "
            f"{len(validation.rejected_rows)} rejected."
        ]
        if validation.schema_errors:
            parts.append("Schema issues: " + ", ".join(validation.schema_errors) + ".")
        parts.append(
            f"Accepted network: {graph_summary.account_count} accounts and "
            f"{graph_summary.transaction_count} transactions."
        )
        if findings:
            counts: dict[str, int] = {}
            for finding in findings:
                counts[finding.rule_name] = counts.get(finding.rule_name, 0) + 1
            rule_summary = ", ".join(
                f"{rule} ({count})" for rule, count in sorted(counts.items())
            )
            parts.append(
                f"Generated {len(findings)} investigation lead(s): {rule_summary}. "
                "Review the linked transaction evidence and thresholds."
            )
        else:
            parts.append(
                "No configured patterns matched the accepted transactions; this does not "
                "establish that activity is safe."
            )
        parts.append(
            "Findings are investigation leads for human review, not proof of fraud or mule activity."
        )
        return " ".join(parts)


class EvaluationAgent:
    """Compares completed transaction findings with suitable binary labels.

    Evaluation is post-detection only. Rejected records are excluded. The
    reference label is interpreted as a transaction-level positive class (1),
    never as an account-level mule label.
    """

    name = "evaluation"

    def run(
        self, accepted_rows: pd.DataFrame, findings: list[Finding]
    ) -> EvaluationResult:
        if LABEL not in accepted_rows.columns:
            return self._unavailable("No evaluation label column was supplied.")
        if accepted_rows.empty:
            return self._unavailable("No accepted transactions are available to evaluate.")

        normalized_labels: list[int] = []
        for value in accepted_rows[LABEL].tolist():
            if value is None or pd.isna(value):
                return self._unavailable("At least one accepted transaction has a missing label.")
            if isinstance(value, bool):
                normalized_labels.append(int(value))
            elif isinstance(value, Real) and math.isfinite(float(value)) and value in (0, 1):
                normalized_labels.append(int(value))
            else:
                return self._unavailable(
                    "Labels must be numeric/bool 0 or 1 for this demo evaluation."
                )

        if set(normalized_labels) != {0, 1}:
            return self._unavailable(
                "Both reference classes (0 and 1) are required for the reported demo metrics."
            )

        alerted_ids = {
            transaction_id
            for finding in findings
            for transaction_id in finding.supporting_transaction_ids
        }
        predicted = [
            transaction_id in alerted_ids
            for transaction_id in accepted_rows[TRANSACTION_ID].tolist()
        ]
        tp = sum(pred and label == 1 for pred, label in zip(predicted, normalized_labels))
        fp = sum(pred and label == 0 for pred, label in zip(predicted, normalized_labels))
        tn = sum((not pred) and label == 0 for pred, label in zip(predicted, normalized_labels))
        fn = sum((not pred) and label == 1 for pred, label in zip(predicted, normalized_labels))
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        specificity = tn / (tn + fp) if tn + fp else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall
            else 0.0
        )
        accuracy = (tp + tn) / len(normalized_labels)
        return EvaluationResult(
            status="available",
            reason=(
                "Transaction-level rule-evidence comparison completed. This is a demo metric, "
                "not an account-level mule assessment or production performance estimate."
            ),
            metrics={
                "reference_positive_label": 1,
                "transaction_count": len(normalized_labels),
                "confusion_counts": {"true_positive": tp, "false_positive": fp,
                                     "true_negative": tn, "false_negative": fn},
                "precision": precision,
                "recall": recall,
                "specificity": specificity,
                "f1": f1,
                "accuracy": accuracy,
            },
        )

    @staticmethod
    def _unavailable(reason: str) -> EvaluationResult:
        return EvaluationResult(status="unavailable", reason=reason, metrics=None)


class CoordinatorAgent:
    """Runs the deterministic stages through a compiled LangGraph workflow."""

    def __init__(
        self,
        validation_agent: DataValidationAgent | None = None,
        network_agent: NetworkAnalysisAgent | None = None,
        pattern_agent: PatternAnalysisAgent | None = None,
        explanation_agent: ExplanationAgent | None = None,
        evaluation_agent: EvaluationAgent | None = None,
    ) -> None:
        self.validation_agent = validation_agent or DataValidationAgent()
        self.network_agent = network_agent or NetworkAnalysisAgent()
        self.pattern_agent = pattern_agent or PatternAnalysisAgent()
        self.explanation_agent = explanation_agent or ExplanationAgent()
        self.evaluation_agent = evaluation_agent or EvaluationAgent()
        self.stage_trace: list[WorkflowStage] = []

    def run(self, raw_dataframe: pd.DataFrame, config: RuleConfig | None = None) -> WorkflowResult:
        self.stage_trace = []
        from src.langgraph_workflow import run_langgraph_workflow

        state = run_langgraph_workflow(self, raw_dataframe, config)
        validation = state["validation"]
        graph = state["graph"]
        graph_summary = state["graph_summary"]
        findings = state["findings"]
        summary = state["human_readable_summary"]
        evaluation = state["evaluation"]

        return WorkflowResult(
            status="completed",
            validation_counts={
                "input_rows": len(validation.valid_rows) + len(validation.rejected_rows),
                "accepted_rows": len(validation.valid_rows),
                "rejected_rows": len(validation.rejected_rows),
                "schema_errors": list(validation.schema_errors),
            },
            accepted_rows=validation.valid_rows.copy(),
            rejected_rows=validation.rejected_rows.copy(),
            graph=graph,
            graph_summary=graph_summary,
            findings=findings,
            human_readable_summary=summary,
            evaluation=evaluation,
            stage_trace=list(self.stage_trace),
        )


def run_analysis(
    raw_dataframe: pd.DataFrame, config: RuleConfig | None = None
) -> WorkflowResult:
    """Public deterministic workflow entry point for callers such as Streamlit."""
    return CoordinatorAgent().run(raw_dataframe, config)
