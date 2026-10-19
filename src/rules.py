"""Explainable deterministic transaction-network investigation rules."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import networkx as nx


DISCLAIMER = "Investigation lead for human review; this pattern is not proof of fraud or mule activity."


@dataclass(frozen=True)
class RuleConfig:
    """Rule thresholds; numeric times use index units, datetimes use hours."""

    rapid_chain_window: float = 2.0
    shared_intermediary_window: float = 3.0
    shared_intermediary_min_senders: int = 2
    onward_window: float = 3.0
    onward_min_received_proportion: float = 0.80

    def __post_init__(self) -> None:
        for name in (
            "rapid_chain_window",
            "shared_intermediary_window",
            "onward_window",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")
        if self.shared_intermediary_min_senders < 2:
            raise ValueError("shared_intermediary_min_senders must be at least 2")
        if not 0 < self.onward_min_received_proportion <= 1:
            raise ValueError("onward_min_received_proportion must be in (0, 1]")


@dataclass
class Finding:
    finding_id: str
    rule_name: str
    involved_account_ids: tuple[str, ...]
    supporting_transaction_ids: tuple[str, ...]
    evidence: tuple[dict[str, Any], ...]
    relevant_times: tuple[Any, ...]
    configured_thresholds: dict[str, Any]
    measurements: dict[str, float]
    explanation: str
    status: str = DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _time_delta_hours_or_units(earlier: Any, later: Any) -> float | None:
    """Return positive elapsed time; same-time, reversed, or mixed values skip."""
    if isinstance(earlier, datetime) and isinstance(later, datetime):
        try:
            seconds = (later - earlier).total_seconds()
        except (TypeError, ValueError):
            return None
        return seconds / 3600.0 if seconds > 0 else None
    if isinstance(earlier, (int, float)) and not isinstance(earlier, bool) and isinstance(
        later, (int, float)
    ) and not isinstance(later, bool):
        delta = float(later) - float(earlier)
        return delta if delta > 0 else None
    return None


def _edge_records(graph: nx.MultiDiGraph) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for sender, receiver, _, data in graph.edges(keys=True, data=True):
        records.append(
            {
                "transaction_id": data["transaction_id"],
                "sender_id": sender,
                "receiver_id": receiver,
                "amount": float(data["amount"]),
                "transaction_type": data["transaction_type"],
                "time": data["time"],
                **({"source_row": data["source_row"]} if "source_row" in data else {}),
            }
        )
    return sorted(records, key=lambda item: (str(item["time"]), item["transaction_id"]))


def _make_finding(
    rule_name: str,
    records: list[dict[str, Any]],
    thresholds: dict[str, Any],
    explanation: str,
    measurements: dict[str, float] | None = None,
) -> Finding:
    transaction_ids = tuple(record["transaction_id"] for record in records)
    digest_source = "|".join((rule_name, *transaction_ids))
    digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:12]
    accounts = tuple(
        dict.fromkeys(
            account
            for record in records
            for account in (record["sender_id"], record["receiver_id"])
        )
    )
    return Finding(
        finding_id=f"{rule_name}-{digest}",
        rule_name=rule_name,
        involved_account_ids=accounts,
        supporting_transaction_ids=transaction_ids,
        evidence=tuple(records),
        relevant_times=tuple(record["time"] for record in records),
        configured_thresholds=thresholds,
        measurements=measurements or {},
        explanation=explanation,
    )


def _rapid_chain_findings(records: list[dict[str, Any]], config: RuleConfig) -> list[Finding]:
    findings: list[Finding] = []
    for incoming in records:
        for outgoing in records:
            if incoming["transaction_id"] == outgoing["transaction_id"]:
                continue
            if incoming["receiver_id"] != outgoing["sender_id"]:
                continue
            elapsed = _time_delta_hours_or_units(incoming["time"], outgoing["time"])
            if elapsed is None or elapsed > config.rapid_chain_window:
                continue
            findings.append(
                _make_finding(
                    "rapid_transfer_chain",
                    [incoming, outgoing],
                    {"max_elapsed_time_units_or_hours": config.rapid_chain_window},
                    (
                        f"Account {incoming['receiver_id']} received {incoming['amount']:g} "
                        f"in {incoming['transaction_id']} and sent {outgoing['amount']:g} "
                        f"in {outgoing['transaction_id']} after {elapsed:g} time units/hours."
                    ),
                    measurements={"elapsed_time_units_or_hours": elapsed},
                )
            )
    return findings


def _shared_intermediary_findings(
    records: list[dict[str, Any]], config: RuleConfig
) -> list[Finding]:
    findings: list[Finding] = []
    accounts = sorted({record["receiver_id"] for record in records})
    for intermediary in accounts:
        incoming = [record for record in records if record["receiver_id"] == intermediary]
        onward_records = [record for record in records if record["sender_id"] == intermediary]
        for onward in onward_records:
            recent_incoming = [
                record
                for record in incoming
                if record["transaction_id"] != onward["transaction_id"]
                and (elapsed := _time_delta_hours_or_units(record["time"], onward["time"]))
                is not None
                and elapsed <= config.shared_intermediary_window
            ]
            distinct_senders = {record["sender_id"] for record in recent_incoming}
            if len(distinct_senders) < config.shared_intermediary_min_senders:
                continue
            elapsed_values = [
                _time_delta_hours_or_units(record["time"], onward["time"])
                for record in recent_incoming
            ]
            ordered = sorted(recent_incoming, key=lambda r: (str(r["time"]), r["transaction_id"]))
            evidence = [*ordered, onward]
            sender_names = ", ".join(sorted(distinct_senders))
            findings.append(
                _make_finding(
                    "shared_intermediary",
                    evidence,
                    {
                        "min_distinct_senders": config.shared_intermediary_min_senders,
                        "max_incoming_to_onward_elapsed_time_units_or_hours": (
                            config.shared_intermediary_window
                        ),
                    },
                    (
                        f"{intermediary} received recent transfers from {len(distinct_senders)} "
                        f"distinct senders ({sender_names}) and then transferred onward."
                    ),
                    measurements={
                        "distinct_recent_senders": float(len(distinct_senders)),
                        "max_incoming_to_onward_elapsed_time_units_or_hours": max(
                            value for value in elapsed_values if value is not None
                        ),
                    },
                )
            )
    return findings


def _onward_transfer_findings(records: list[dict[str, Any]], config: RuleConfig) -> list[Finding]:
    findings: list[Finding] = []
    accounts = sorted({record["sender_id"] for record in records})
    for account in accounts:
        incoming = [record for record in records if record["receiver_id"] == account]
        outgoing = [record for record in records if record["sender_id"] == account]
        for onward in outgoing:
            recent_incoming = [
                record
                for record in incoming
                if record["transaction_id"] != onward["transaction_id"]
                and (elapsed := _time_delta_hours_or_units(record["time"], onward["time"]))
                is not None
                and elapsed <= config.onward_window
            ]
            received_total = sum(record["amount"] for record in recent_incoming)
            if received_total <= 0:
                continue
            proportion = onward["amount"] / received_total
            if proportion < config.onward_min_received_proportion:
                continue
            ordered = sorted(recent_incoming, key=lambda r: (str(r["time"]), r["transaction_id"]))
            findings.append(
                _make_finding(
                    "substantial_onward_transfer",
                    [*ordered, onward],
                    {
                        "window_units_or_hours": config.onward_window,
                        "min_outgoing_to_recent_incoming_ratio": (
                            config.onward_min_received_proportion
                        ),
                    },
                    (
                        f"{account} sent {onward['amount']:g} after receiving an aggregate "
                        f"{received_total:g} in the configured recent window; the amount ratio "
                        f"is {proportion:.1%}. This aggregate comparison does not establish that "
                        "the same funds were transferred onward."
                    ),
                    measurements={
                        "recent_incoming_total": received_total,
                        "outgoing_amount": onward["amount"],
                        "outgoing_to_incoming_ratio": proportion,
                    },
                )
            )
    return findings


def detect_patterns(graph: nx.MultiDiGraph, config: RuleConfig | None = None) -> list[Finding]:
    """Run deterministic rules on a validated account multigraph.

    Evaluation labels are never read: only graph nodes and transaction edge
    evidence are used. Findings are returned in stable rule/ID order.
    """
    if not isinstance(graph, nx.MultiDiGraph):
        raise TypeError("detect_patterns requires a NetworkX MultiDiGraph")
    active_config = config or RuleConfig()
    records = _edge_records(graph)
    findings = [
        *_rapid_chain_findings(records, active_config),
        *_shared_intermediary_findings(records, active_config),
        *_onward_transfer_findings(records, active_config),
    ]
    return sorted(findings, key=lambda finding: (finding.rule_name, finding.finding_id))
