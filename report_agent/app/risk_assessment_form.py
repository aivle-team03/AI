from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any

from app.schemas import FinalHistoryRow, RiskDataCorrectionResult

HEADER_ROW_INDEX = 7
DATA_START_ROW_INDEX = 8
COLUMN_COUNT = 25
DEFAULT_FORM_PATH = Path(r"C:\Users\User\Downloads\위험성평가표 - 시트1.csv")
DEFAULT_OUTPUT_PATH = Path("output/risk_assessment_form_filled.csv")
DEFAULT_EXCEL_OUTPUT_PATH = Path("output/risk_assessment_form_filled_excel.csv")


def _value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _date_text(value: Any) -> str:
    text = _value(value)
    return text.replace("T", " ") if "T" in text else text


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = _value(value).strip()
        if text:
            return text
    return ""


def _row_to_dict(row: FinalHistoryRow | dict[str, Any]) -> dict[str, Any]:
    if hasattr(row, "model_dump"):
        return row.model_dump(mode="json")
    return dict(row or {})


def _company_info(source_data: dict[str, Any]) -> dict[str, str]:
    company = source_data.get("company") or {}
    users = source_data.get("user") or []
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


def _form_row(row: FinalHistoryRow | dict[str, Any]) -> list[str]:
    data = _row_to_dict(row)
    output = [""] * COLUMN_COUNT
    output[0] = _value(data.get("category_name"))
    output[1] = _value(data.get("risk"))
    output[2] = _value(data.get("inspection_name"))
    output[4] = _value(data.get("inspection_location"))
    output[5] = _date_text(data.get("inspection_date"))
    output[7] = _value(data.get("inspection_user_name"))
    output[8] = _value(data.get("inspection_content"))
    output[10] = _value(data.get("before_image_url"))
    output[12] = _value(data.get("action_name"))
    output[14] = _value(data.get("action_location"))
    output[15] = _date_text(data.get("action_date"))
    output[17] = _value(data.get("action_user_name"))
    output[19] = _value(data.get("action_content"))
    output[21] = ""
    output[23] = _value(data.get("approval_name"))
    output[24] = _value(data.get("type"))
    return output


def _write_csv(path: Path, rows: list[list[str]], encoding: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=encoding, newline="") as file:
        writer = csv.writer(file)
        writer.writerows(rows)


def fill_risk_assessment_form(
    source_data: dict[str, Any],
    correction_result: RiskDataCorrectionResult,
    form_path: Path | str = DEFAULT_FORM_PATH,
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
) -> str:
    form_path = Path(form_path)
    output_path = Path(output_path)

    with form_path.open("r", encoding="utf-8-sig", newline="") as file:
        form_rows = list(csv.reader(file))

    while len(form_rows) <= DATA_START_ROW_INDEX:
        form_rows.append([""] * COLUMN_COUNT)

    output_rows = []
    for row in form_rows[:DATA_START_ROW_INDEX]:
        normalized = list(row[:COLUMN_COUNT])
        normalized.extend([""] * (COLUMN_COUNT - len(normalized)))
        output_rows.append(normalized)

    info = _company_info(source_data)
    output_rows[0][1] = _first_non_empty(info.get("company_name"), output_rows[0][1])
    output_rows[0][11] = _first_non_empty(info.get("safety_manager"), output_rows[0][11])
    output_rows[2][1] = date.today().isoformat()

    output_rows.extend(_form_row(row) for row in correction_result.corrected_rows)

    _write_csv(output_path, output_rows, "utf-8-sig")

    excel_output_path = output_path.with_name(f"{output_path.stem}_excel{output_path.suffix}")
    _write_csv(excel_output_path, output_rows, "cp949")

    return str(output_path)
