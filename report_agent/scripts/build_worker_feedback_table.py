from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.worker_feedback.table_builder import build_worker_feedback_table


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a worker feedback table from separated dummy tables.",
    )
    parser.add_argument(
        "--input",
        default="output/separated_history_dummy_tables.json",
        help="Separated table JSON path.",
    )
    parser.add_argument(
        "--output",
        default="output/worker_feedback_table_from_separated.json",
        help="Worker feedback table output JSON path.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    with input_path.open("r", encoding="utf-8-sig") as file:
        tables = json.load(file)

    rows = build_worker_feedback_table(tables)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(rows, file, ensure_ascii=False, indent=2)
        file.write("\n")

    print(f"wrote: {output_path}")
    print(f"total: {len(rows)}")


if __name__ == "__main__":
    main()
