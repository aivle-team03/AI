from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any


HEADER_ROW_INDEX = 7
DATA_START_ROW_INDEX = 8
COLUMN_COUNT = 25


def _value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _date_only(value: Any) -> str:
    text = _value(value)
    if "T" in text:
        return text.replace("T", " ")
    return text


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = _value(value).strip()
        if text:
            return text
    return ""


def _load_company_info(sample_request_path: Path | None) -> dict[str, str]:
    if not sample_request_path or not sample_request_path.exists():
        return {}
    with sample_request_path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)

    company = data.get("company") or {}
    users = data.get("user") or []
    safety_manager = ""
    for user in users:
        role = str(user.get("role") or "")
        category = str(user.get("category") or "")
        if "안전" in role or "안전" in category:
            safety_manager = str(user.get("name") or "")
            break

    return {
        "company_name": str(company.get("company_name") or ""),
        "safety_manager": safety_manager,
    }


def _row_from_history(row: dict[str, Any]) -> list[str]:
    output = [""] * COLUMN_COUNT
    output[0] = _value(row.get("category_name"))
    output[1] = _value(row.get("risk"))
    output[2] = _value(row.get("inspection_name"))
    output[4] = _value(row.get("inspection_location"))
    output[5] = _date_only(row.get("inspection_date"))
    output[7] = _value(row.get("inspection_user_name"))
    output[8] = _value(row.get("inspection_content"))
    output[10] = _value(row.get("before_image_url"))
    output[12] = _value(row.get("action_name"))
    output[14] = _value(row.get("action_location"))
    output[15] = _date_only(row.get("action_date"))
    output[17] = _value(row.get("action_user_name"))
    output[19] = _value(row.get("action_content"))
    output[21] = ""
    output[23] = _value(row.get("approval_name"))
    output[24] = _value(row.get("type"))
    return output


def fill_form(
    form_path: Path,
    corrected_path: Path,
    output_path: Path,
    sample_request_path: Path | None = None,
) -> None:
    with form_path.open("r", encoding="utf-8-sig", newline="") as file:
        form_rows = list(csv.reader(file))

    with corrected_path.open("r", encoding="utf-8-sig") as file:
        correction_result = json.load(file)

    corrected_rows = correction_result.get("corrected_rows", [])
    company_info = _load_company_info(sample_request_path)

    while len(form_rows) <= DATA_START_ROW_INDEX:
        form_rows.append([""] * COLUMN_COUNT)

    normalized_rows = []
    for row in form_rows[:DATA_START_ROW_INDEX]:
        normalized = list(row[:COLUMN_COUNT])
        normalized.extend([""] * (COLUMN_COUNT - len(normalized)))
        normalized_rows.append(normalized)

    normalized_rows[0][1] = _first_non_empty(company_info.get("company_name"), normalized_rows[0][1])
    normalized_rows[2][1] = date.today().isoformat()
    normalized_rows[0][11] = _first_non_empty(
        company_info.get("safety_manager"),
        normalized_rows[0][11],
    )

    data_rows = [_row_from_history(row) for row in corrected_rows]
    output_rows = normalized_rows + data_rows

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerows(output_rows)

    print(f"wrote: {output_path}")
    print(f"rows_written: {len(data_rows)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fill risk assessment CSV form with reviewed/corrected data."
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
        default="output/risk_assessment_form_filled.csv",
        help="Filled CSV output path.",
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
