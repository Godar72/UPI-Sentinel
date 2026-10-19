"""Canonical transaction schema and column helpers."""

from __future__ import annotations

from typing import Final

import pandas as pd

TRANSACTION_ID: Final = "transaction_id"
TIME: Final = "time"
SENDER_ID: Final = "sender_id"
RECEIVER_ID: Final = "receiver_id"
AMOUNT: Final = "amount"
TRANSACTION_TYPE: Final = "transaction_type"
LABEL: Final = "label"
SOURCE_ROW: Final = "source_row"
SCENARIO_ID: Final = "scenario_id"

REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    TRANSACTION_ID,
    TIME,
    SENDER_ID,
    RECEIVER_ID,
    AMOUNT,
    TRANSACTION_TYPE,
)
CANONICAL_COLUMNS: Final[tuple[str, ...]] = (*REQUIRED_COLUMNS, LABEL)
ANALYSIS_COLUMNS: Final[tuple[str, ...]] = REQUIRED_COLUMNS
METADATA_COLUMNS: Final[tuple[str, ...]] = (SOURCE_ROW, SCENARIO_ID)


def analysis_view(frame: pd.DataFrame) -> pd.DataFrame:
    """Return only canonical analysis fields, excluding labels and metadata.

    This helper intentionally does not copy or transform values. Validation is
    responsible for producing a normalized accepted frame first.
    """
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    return frame.loc[:, list(ANALYSIS_COLUMNS)].copy()
