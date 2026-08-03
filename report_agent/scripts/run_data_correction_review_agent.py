from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.agents import risk_data_correction_review_agent
from app.schemas import RiskDataCorrectionResult


async def run(original_path: Path, corrected_path: Path, output_path: Path) -> None:
    with original_path.open("r", encoding="utf-8-sig") as file:
        original_rows = json.load(file)

    with corrected_path.open("r", encoding="utf-8-sig") as file:
        correction_result = RiskDataCorrectionResult.model_validate(json.load(file))

    review = await risk_data_correction_review_agent(original_rows, correction_result)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(review.model_dump(mode="json"), file, ensure_ascii=False, indent=2)
        file.write("\n")

    print(f"wrote: {output_path}")
    print(f"approved: {review.approved}")
    print(f"final_decision: {review.final_decision}")
    print(f"score: {review.score}")
    print(f"issues: {len(review.issues)}")
    print(f"items_requiring_revision: {len(review.items_requiring_revision)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the risk data correction review agent."
    )
    parser.add_argument(
        "--original",
        default="output/final_history_table_from_separated.json",
        help="Original final history table JSON path.",
    )
    parser.add_argument(
        "--corrected",
        default="output/final_history_table_corrected.json",
        help="Corrected data JSON path.",
    )
    parser.add_argument(
        "--output",
        default="output/final_history_table_correction_review.json",
        help="Review output JSON path.",
    )
    args = parser.parse_args()
    asyncio.run(run(Path(args.original), Path(args.corrected), Path(args.output)))


if __name__ == "__main__":
    main()
