"""Generate a small, deterministic UPI Sentinel transaction CSV."""

from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Any

import pandas as pd

from src.schema import (
    AMOUNT,
    LABEL,
    RECEIVER_ID,
    SCENARIO_ID,
    SENDER_ID,
    SOURCE_ROW,
    TIME,
    TRANSACTION_ID,
    TRANSACTION_TYPE,
)

DEFAULT_SEED = 20261012
DEFAULT_OUTPUT = Path("data/samples/synthetic_transactions.csv")


def generate_synthetic_transactions(seed: int = DEFAULT_SEED) -> pd.DataFrame:
    """Create deterministic valid and deliberately invalid scenario records.

    ``label`` is a toy evaluation reference for the designed scenario only:
    1 marks S2/S3 pattern-positive examples and 0 marks controls. It is not a
    fraud/mule ground truth and must never be used by analysis rules.
    S4 invalid rows include null and malformed values intentionally.
    """
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []

    def add(
        transaction_id: str,
        time: Any,
        sender_id: Any,
        receiver_id: Any,
        amount: Any,
        transaction_type: Any = "P2P",
        label: Any = 0,
        scenario_id: str = "",
    ) -> None:
        records.append(
            {
                TRANSACTION_ID: transaction_id,
                TIME: time,
                SENDER_ID: sender_id,
                RECEIVER_ID: receiver_id,
                AMOUNT: amount,
                TRANSACTION_TYPE: transaction_type,
                LABEL: label,
                SCENARIO_ID: scenario_id,
            }
        )

    # S1: normal peer-to-peer transfers, with deterministic varied amounts.
    for index in range(4):
        add(
            f"S1-T{index + 1}", 10 + index * 3, f"S1-U{index + 1}",
            f"S1-U{index + 5}", round(rng.uniform(12.0, 175.0), 2),
            label=0, scenario_id="S1",
        )

    # S2: intentionally rapid A -> B -> C sequence.
    add("S2-T1", 100, "S2-A", "S2-B", 500, label=1, scenario_id="S2")
    add("S2-T2", 101, "S2-B", "S2-C", 480, label=1, scenario_id="S2")

    # S3: multiple senders converge on a common intermediary that forwards.
    for index, sender in enumerate(("S3-A", "S3-B", "S3-C")):
        add(f"S3-IN-{index + 1}", 200 + index, sender, "S3-HUB", 300 + index * 25,
            label=1, scenario_id="S3")
    add("S3-OUT", 204, "S3-HUB", "S3-OUTSIDE", 950, label=1, scenario_id="S3")

    # S4: each record demonstrates a distinct invalid-data condition.
    add("S4-BLANK-SENDER", 300, "   ", "S4-R1", 10, scenario_id="S4")
    add("S4-MISSING-RECEIVER", 301, "S4-S2", None, 10, scenario_id="S4")
    add("S4-MISSING-AMOUNT", 302, "S4-S3", "S4-R3", None, scenario_id="S4")
    add("S4-NONNUMERIC-AMOUNT", 303, "S4-S4", "S4-R4", "not-a-number", scenario_id="S4")
    add("S4-NEGATIVE-AMOUNT", 304, "S4-S5", "S4-R5", -4.25, scenario_id="S4")
    add("S4-INVALID-TIME", "not-a-time", "S4-S6", "S4-R6", 5, scenario_id="S4")
    add("S4-MISSING-SENDER", 306, None, "S4-R7", 6, scenario_id="S4")
    add("S4-DUPLICATE", 307, "S4-S8", "S4-R8", 7, scenario_id="S4")
    add("S4-DUPLICATE", 308, "S4-S9", "S4-R9", 8, scenario_id="S4")

    # S5: high-volume legitimate merchant control; volume alone is not a rule.
    for index in range(18):
        add(
            f"S5-T{index + 1}", 400 + index, f"S5-CUSTOMER-{index + 1}",
            "S5-MERCHANT", round(rng.uniform(3.0, 90.0), 2),
            transaction_type="PAYMENT", label=0, scenario_id="S5",
        )

    # S6: ordinary split payment followed by a partial refund.
    add("S6-SPLIT-1", 500, "S6-CUSTOMER", "S6-SHOP", 60, label=0, scenario_id="S6")
    add("S6-SPLIT-2", 501, "S6-CUSTOMER", "S6-SHOP", 40, label=0, scenario_id="S6")
    add("S6-REFUND", 505, "S6-SHOP", "S6-CUSTOMER", 10, transaction_type="REFUND",
        label=0, scenario_id="S6")

    frame = pd.DataFrame.from_records(records)
    frame.insert(0, SOURCE_ROW, range(1, len(frame) + 1))
    return frame


def write_synthetic_csv(path: str | Path = DEFAULT_OUTPUT, seed: int = DEFAULT_SEED) -> Path:
    """Write generated scenarios to CSV and return the resolved output path."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generate_synthetic_transactions(seed=seed).to_csv(output_path, index=False)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    output_path = write_synthetic_csv(args.output, seed=args.seed)
    print(f"Wrote synthetic transactions to {output_path} (seed={args.seed})")


if __name__ == "__main__":
    main()
