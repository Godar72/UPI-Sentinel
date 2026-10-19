"""Strict transaction input validation with row-level rejection reporting."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from numbers import Real
from typing import Any

import pandas as pd

from src.schema import (
    AMOUNT,
    REQUIRED_COLUMNS,
    SENDER_ID,
    RECEIVER_ID,
    SOURCE_ROW,
    TIME,
    TRANSACTION_ID,
    TRANSACTION_TYPE,
)

REJECTION_REASONS_COLUMN = "rejection_reasons"


@dataclass
class ValidationResult:
    """Accepted rows, rejected source rows, and structural schema errors."""

    valid_rows: pd.DataFrame
    rejected_rows: pd.DataFrame
    schema_errors: list[str]


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        result = pd.isna(value)
        return bool(result) if not hasattr(result, "__len__") else False
    except (TypeError, ValueError):
        return False


def _is_blank_string(value: Any) -> bool:
    return isinstance(value, str) and not value.strip()


def _parse_amount(value: Any) -> tuple[float | int | None, str | None]:
    if _is_missing(value) or _is_blank_string(value):
        return None, "missing_amount"
    if isinstance(value, bool):
        return None, "nonnumeric_amount"
    if isinstance(value, Real):
        parsed: float | int = value
    elif isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None, "nonnumeric_amount"
    else:
        return None, "nonnumeric_amount"
    if not math.isfinite(float(parsed)):
        return None, "non_finite_amount"
    if parsed < 0:
        return None, "negative_amount"
    return parsed, None


def _parse_time(value: Any) -> tuple[Any, str | None]:
    if _is_missing(value) or _is_blank_string(value):
        return None, "missing_time"
    if isinstance(value, bool):
        return None, "invalid_time"
    if isinstance(value, Real):
        return (value, None) if math.isfinite(float(value)) else (None, "invalid_time")
    if isinstance(value, datetime):
        return value, None
    if isinstance(value, str):
        raw = value.strip()
        try:
            # CSV readers commonly return integer/decimal time indices as text.
            numeric = float(raw)
            if math.isfinite(numeric):
                return (int(numeric) if numeric.is_integer() else numeric), None
            return None, "invalid_time"
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")), None
        except ValueError:
            return None, "invalid_time"
    return None, "invalid_time"


def _account_error(value: Any, field: str) -> str | None:
    if _is_missing(value) or _is_blank_string(value):
        return f"missing_{field}"
    if not isinstance(value, str):
        return f"invalid_{field}_type"
    return None


def validate_transactions(frame: pd.DataFrame) -> ValidationResult:
    """Validate records while retaining every rejected input row.

    Duplicate policy: if a nonblank string transaction ID appears more than
    once, reject *all* rows carrying that ID. This avoids order-dependent
    first-wins/last-wins behavior and preserves every source row for review.
    Existing ``source_row`` values are retained; otherwise one-based data-row
    positions are assigned (the first record is source row 1).
    """
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")

    source = frame.copy(deep=True)
    if SOURCE_ROW not in source.columns:
        source.insert(0, SOURCE_ROW, range(1, len(source) + 1))
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in source.columns]
    schema_errors = [f"missing_required_column:{column}" for column in missing_columns]
    if missing_columns:
        rejected = source.copy()
        rejected[REJECTION_REASONS_COLUMN] = [
            tuple(schema_errors) for _ in range(len(rejected))
        ]
        return ValidationResult(
            valid_rows=source.iloc[0:0].copy(),
            rejected_rows=rejected,
            schema_errors=schema_errors,
        )

    parsed_amounts: list[float | int | None] = []
    parsed_times: list[Any] = []
    reason_sets: list[list[str]] = []
    for _, row in source.iterrows():
        reasons: list[str] = []
        for field in (TRANSACTION_ID,):
            error = _account_error(row[field], "transaction_id")
            if error:
                reasons.append(error)
        for field in (SENDER_ID, RECEIVER_ID):
            error = _account_error(row[field], field)
            if error:
                reasons.append(error)
        transaction_type = row[TRANSACTION_TYPE]
        if _is_missing(transaction_type) or _is_blank_string(transaction_type):
            reasons.append("missing_transaction_type")
        elif not isinstance(transaction_type, str):
            reasons.append("invalid_transaction_type")

        parsed_time, time_error = _parse_time(row[TIME])
        parsed_times.append(parsed_time)
        if time_error:
            reasons.append(time_error)
        parsed_amount, amount_error = _parse_amount(row[AMOUNT])
        parsed_amounts.append(parsed_amount)
        if amount_error:
            reasons.append(amount_error)
        reason_sets.append(reasons)

    counts = Counter(
        value for value in source[TRANSACTION_ID].tolist()
        if isinstance(value, str) and value.strip()
    )
    for position, value in enumerate(source[TRANSACTION_ID].tolist()):
        if isinstance(value, str) and value.strip() and counts[value] > 1:
            reason_sets[position].append("duplicate_transaction_id")

    normalized = source.copy(deep=True)
    normalized[TIME] = parsed_times
    normalized[AMOUNT] = parsed_amounts
    normalized[REJECTION_REASONS_COLUMN] = [tuple(reasons) for reasons in reason_sets]
    rejected_mask = normalized[REJECTION_REASONS_COLUMN].map(bool)
    valid_rows = normalized.loc[~rejected_mask].drop(columns=[REJECTION_REASONS_COLUMN]).copy()
    # Rejections preserve the exact submitted values; normalized placeholders
    # are used only to determine acceptance and are never substituted here.
    rejected_rows = source.loc[rejected_mask].copy()
    rejected_rows[REJECTION_REASONS_COLUMN] = normalized.loc[
        rejected_mask, REJECTION_REASONS_COLUMN
    ].tolist()
    return ValidationResult(valid_rows, rejected_rows, schema_errors=[])
