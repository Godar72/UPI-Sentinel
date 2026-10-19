"""Directed account-network construction and deterministic graph summaries."""

from __future__ import annotations

from dataclasses import dataclass
import networkx as nx
import pandas as pd

from src.schema import (
    AMOUNT,
    REQUIRED_COLUMNS,
    RECEIVER_ID,
    SENDER_ID,
    SOURCE_ROW,
    TIME,
    TRANSACTION_ID,
    TRANSACTION_TYPE,
    analysis_view,
)
from src.validation import ValidationResult, validate_transactions
from src.rules import Finding, RuleConfig, detect_patterns


@dataclass
class AccountActivity:
    account_id: str
    incoming_transactions: int
    outgoing_transactions: int
    incoming_amount: float
    outgoing_amount: float


@dataclass
class GraphSummary:
    account_count: int
    transaction_count: int
    account_activity: dict[str, AccountActivity]


@dataclass
class AnalysisResult:
    validation: ValidationResult
    graph: nx.MultiDiGraph
    findings: list[Finding]


def _graph_from_validated(transactions: pd.DataFrame) -> nx.MultiDiGraph:
    """Construct the graph from accepted, normalized rows only."""
    graph = nx.MultiDiGraph()
    graph.graph["rejected_row_count"] = 0
    graph.graph["label_used_for_analysis"] = False
    if transactions.empty:
        return graph

    fields = [TRANSACTION_ID, TIME, SENDER_ID, RECEIVER_ID, AMOUNT, TRANSACTION_TYPE]
    if SOURCE_ROW in transactions.columns:
        fields.append(SOURCE_ROW)
    evidence_frame = transactions.loc[:, fields]
    for row in evidence_frame.to_dict(orient="records"):
        sender = row[SENDER_ID]
        receiver = row[RECEIVER_ID]
        graph.add_node(sender)
        graph.add_node(receiver)
        graph.add_edge(
            sender,
            receiver,
            key=row[TRANSACTION_ID],
            transaction_id=row[TRANSACTION_ID],
            amount=row[AMOUNT],
            transaction_type=row[TRANSACTION_TYPE],
            time=row[TIME],
            **({SOURCE_ROW: row[SOURCE_ROW]} if SOURCE_ROW in row else {}),
        )
    return graph


def build_account_graph(transactions: pd.DataFrame) -> nx.MultiDiGraph:
    """Validate input and build a directed multigraph from accepted rows.

    Nodes are account IDs. Each directed edge is one transaction, with the
    transaction ID as its multiedge key and amount/type/time/source row stored
    as edge attributes. Invalid and duplicate-ID records never enter the graph.
    Rejected-row count and source-row IDs are retained in graph metadata.
    """
    validation = validate_transactions(transactions)
    graph = _graph_from_validated(validation.valid_rows)
    graph.graph["rejected_row_count"] = len(validation.rejected_rows)
    if SOURCE_ROW in validation.rejected_rows.columns:
        graph.graph["rejected_source_rows"] = validation.rejected_rows[SOURCE_ROW].tolist()
    else:
        graph.graph["rejected_source_rows"] = []
    return graph


def summarize_graph(graph: nx.MultiDiGraph) -> GraphSummary:
    """Return account/transaction counts and per-account in/out activity."""
    activity: dict[str, AccountActivity] = {}
    for account in sorted(graph.nodes, key=str):
        incoming = list(graph.in_edges(account, keys=True, data=True))
        outgoing = list(graph.out_edges(account, keys=True, data=True))
        activity[account] = AccountActivity(
            account_id=account,
            incoming_transactions=len(incoming),
            outgoing_transactions=len(outgoing),
            incoming_amount=sum(float(edge[3]["amount"]) for edge in incoming),
            outgoing_amount=sum(float(edge[3]["amount"]) for edge in outgoing),
        )
    return GraphSummary(
        account_count=graph.number_of_nodes(),
        transaction_count=graph.number_of_edges(),
        account_activity=activity,
    )


def analyze_transactions(
    transactions: pd.DataFrame, config: RuleConfig | None = None
) -> AnalysisResult:
    """Validate once, build an accepted-only graph, and run deterministic rules."""
    validation = validate_transactions(transactions)
    if validation.schema_errors:
        accepted = pd.DataFrame(columns=[*REQUIRED_COLUMNS, SOURCE_ROW])
    else:
        accepted_analysis = analysis_view(validation.valid_rows)
        # Keep trace metadata on accepted records while remaining label-independent.
        accepted = validation.valid_rows.loc[:, list(accepted_analysis.columns) + (
            [SOURCE_ROW] if SOURCE_ROW in validation.valid_rows.columns else []
        )]
    graph = _graph_from_validated(accepted)
    graph.graph["rejected_row_count"] = len(validation.rejected_rows)
    graph.graph["rejected_source_rows"] = (
        validation.rejected_rows[SOURCE_ROW].tolist()
        if SOURCE_ROW in validation.rejected_rows.columns
        else []
    )
    findings = detect_patterns(graph, config or RuleConfig())
    return AnalysisResult(validation=validation, graph=graph, findings=findings)
