from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.risk_assessment_form import fill_risk_assessment_form, resolved_xlsx_path_for
from app.schemas import RiskDataCorrectionResult


def fill_form(
    form_path: Path,
    corrected_path: Path,
    output_path: Path,
    sample_request_path: Path | None = None,
) -> None:
    source_data = {}
    if sample_request_path and sample_request_path.exists():
        with sample_request_path.open("r", encoding="utf-8-sig") as file:
            source_data = json.load(file)

    with corrected_path.open("r", encoding="utf-8-sig") as file:
        correction_result = RiskDataCorrectionResult.model_validate(json.load(file))

    csv_output_path = fill_risk_assessment_form(
        source_data,
        correction_result,
        form_path=form_path,
        output_path=output_path,
    )
    csv_output = Path(csv_output_path)
    xlsx_output = resolved_xlsx_path_for(csv_output)

    print(f"wrote: {csv_output}")
    print(f"wrote_xlsx: {xlsx_output}")
    print(f"rows_written: {len(correction_result.corrected_rows)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fill risk assessment form with reviewed/corrected data."
    )
    parser.add_argument(
        "--form",
        default=r"C:\Users\User\Downloads\위험성평가표 - 시트1.csv",
        help="Risk assessment CSV form path.",
    )
    parser.add_argument(
        "--corrected",
        default="output/final_history_table_corrected.json",
        help="Reviewed/corrected final history table JSON path.",
    )
    parser.add_argument(
        "--sample-request",
        default="sample_request.json",
        help="Optional source request JSON for company metadata.",
    )
    parser.add_argument(
        "--output",
        default="output/risk_assessment_form/risk_assessment_form_filled.csv",
        help="Filled CSV output path. XLSX is generated beside this path.",
    )
    args = parser.parse_args()
    fill_form(
        Path(args.form),
        Path(args.corrected),
        Path(args.output),
        Path(args.sample_request) if args.sample_request else None,
    )


if __name__ == "__main__":
    main()


