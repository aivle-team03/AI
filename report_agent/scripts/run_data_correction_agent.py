from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.agents import risk_data_correction_agent
from app.risk_data_correction import PROTECTED_FIELDS, enforce_history_table_invariants


async def run(input_path: Path, output_path: Path) -> None:
    with input_path.open("r", encoding="utf-8-sig") as file:
        rows = json.load(file)

    result = await risk_data_correction_agent(rows, protected_fields=PROTECTED_FIELDS)
    safe_result = enforce_history_table_invariants(rows, result, PROTECTED_FIELDS)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(safe_result.model_dump(mode="json"), file, ensure_ascii=False, indent=2)
        file.write("\n")

    print(f"wrote: {output_path}")
    print(f"rows: {len(safe_result.corrected_rows)}")
    print(f"corrections: {len(safe_result.correction_notes)}")
    print(f"unresolved: {len(safe_result.unresolved_notes)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the risk data correction agent.")
    parser.add_argument(
        "--input",
        default="output/final_history_table_from_separated.json",
        help="Final history table JSON path.",
    )
    parser.add_argument(
        "--output",
        default="output/final_history_table_corrected.json",
        help="Corrected data output JSON path.",
    )
    args = parser.parse_args()
    asyncio.run(run(Path(args.input), Path(args.output)))


if __name__ == "__main__":
    main()

