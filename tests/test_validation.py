from __future__ import annotations

import pandas as pd
import pytest

from src.generate_synthetic import generate_synthetic_transactions
from src.schema import (
    ANALYSIS_COLUMNS,
    LABEL,
    REQUIRED_COLUMNS,
    SOURCE_ROW,
    analysis_view,
)
from src.validation import validate_transactions


def valid_frame(**overrides) -> pd.DataFrame:
    row = {
        "transaction_id": "TX-1",
        "time": 12,
        "sender_id": "A",
        "receiver_id": "B",
        "amount": 25.5,
        "transaction_type": "P2P",
        "label": 0,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_valid_row_is_accepted_and_source_row_added() -> None:
    result = validate_transactions(valid_frame())
    assert len(result.valid_rows) == 1
    assert result.rejected_rows.empty
    assert result.valid_rows.loc[0, SOURCE_ROW] == 1
    assert result.valid_rows.loc[0, "amount"] == 25.5
    assert result.valid_rows.loc[0, "time"] == 12


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("transaction_id", "  ", "missing_transaction_id"),
        ("sender_id", "", "missing_sender_id"),
        ("sender_id", None, "missing_sender_id"),
        ("receiver_id", None, "missing_receiver_id"),
        ("time", "yesterday-ish", "invalid_time"),
        ("time", None, "missing_time"),
        ("amount", "twenty", "nonnumeric_amount"),
        ("amount", float("inf"), "non_finite_amount"),
        ("amount", float("nan"), "missing_amount"),
        ("amount", -0.01, "negative_amount"),
        ("amount", None, "missing_amount"),
        ("transaction_type", "", "missing_transaction_type"),
    ],
)
def test_invalid_values_are_rejected_with_reason(field, value, reason) -> None:
    result = validate_transactions(valid_frame(**{field: value}))
    assert result.valid_rows.empty
    assert len(result.rejected_rows) == 1
    assert reason in result.rejected_rows.iloc[0]["rejection_reasons"]
    raw_value = result.rejected_rows.iloc[0][field]
    if isinstance(value, float) and pd.isna(value):
        assert pd.isna(raw_value)
    else:
        assert raw_value == value


def test_missing_required_columns_rejects_rows_and_reports_schema_error() -> None:
    frame = valid_frame().drop(columns=["receiver_id", "amount"])
    result = validate_transactions(frame)
    assert result.valid_rows.empty
    assert len(result.rejected_rows) == 1
    assert result.schema_errors == [
        "missing_required_column:receiver_id",
        "missing_required_column:amount",
    ]
    assert result.rejected_rows.iloc[0][SOURCE_ROW] == 1


def test_duplicate_policy_rejects_every_row_with_same_id() -> None:
    frame = pd.concat(
        [valid_frame(), valid_frame(sender_id="C")], ignore_index=True
    )
    result = validate_transactions(frame)
    assert result.valid_rows.empty
    assert len(result.rejected_rows) == 2
    assert all(
        "duplicate_transaction_id" in reasons
        for reasons in result.rejected_rows["rejection_reasons"]
    )
    assert result.rejected_rows[SOURCE_ROW].tolist() == [1, 2]


def test_existing_source_row_is_preserved() -> None:
    frame = valid_frame()
    frame[SOURCE_ROW] = ["external-row-91"]
    result = validate_transactions(frame)
    assert result.valid_rows.iloc[0][SOURCE_ROW] == "external-row-91"


def test_label_is_not_in_analysis_view() -> None:
    result = validate_transactions(valid_frame())
    view = analysis_view(result.valid_rows)
    assert tuple(view.columns) == ANALYSIS_COLUMNS
    assert LABEL not in view.columns
    assert tuple(REQUIRED_COLUMNS) == ANALYSIS_COLUMNS


def test_generator_is_reproducible_and_contains_all_scenarios() -> None:
    first = generate_synthetic_transactions(seed=123)
    second = generate_synthetic_transactions(seed=123)
    pd.testing.assert_frame_equal(first, second)
    assert {"S1", "S2", "S3", "S4", "S5", "S6"}.issubset(
        set(first["scenario_id"])
    )
    assert first[SOURCE_ROW].tolist() == list(range(1, len(first) + 1))


def test_synthetic_invalid_rows_are_retained_with_reasons() -> None:
    frame = generate_synthetic_transactions()
    result = validate_transactions(frame)
    assert not result.valid_rows.empty
    assert len(result.rejected_rows) >= 8
    assert result.rejected_rows[SOURCE_ROW].notna().all()
    assert result.rejected_rows["rejection_reasons"].map(bool).all()
