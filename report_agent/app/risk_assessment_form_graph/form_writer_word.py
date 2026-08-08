from __future__ import annotations

import copy
from datetime import date
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table, _Cell

from app.risk_assessment_form_graph.schemas import FinalHistoryRow, RiskDataCorrectionResult

DEFAULT_FORM_PATH = Path(r"C:\Users\User\Desktop\KT에이블\빅프로젝트\AI\위험성평가표.docx")
DEFAULT_OUTPUT_PATH = Path("output/risk_assessment_form/risk_assessment_form_filled.docx")

# Template layout (0-based table.rows indices), confirmed by inspecting the docx table:
# rows 0-1: title (vertically merged)
# row 2: 사업장명 / company name / 생성 일자 / date
# row 3: 평가 목적 (static, left untouched)
# row 4: spacer
# rows 5-6: header (vertically merged)
# rows 7+: data rows, each logical row spans a "restart" + "continue" <w:tr> pair
META_ROW_INDEX = 2
COMPANY_NAME_TC_INDEX = 1
GENERATED_DATE_TC_INDEX = 3
DATA_START_ROW_INDEX = 7
DATA_COLUMN_COUNT = 16


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
    # Order matches the template header: 카테고리/위험도/점검이름/구역/점검일시/담당자/내용/
    # 조치 전 사진/조치이름/구역/조치 일시/담당자/조치 내용/조치 후 사진/승인자/타입
    return [
        _value(data.get("category_name")),
        _value(data.get("risk")),
        _value(data.get("category")),
        _value(data.get("inspection_location")),
        _date_text(data.get("inspection_date")),
        _value(data.get("inspection_user_name")),
        _value(data.get("inspection_content")),
        _value(data.get("inspection_image_url")),
        _value(data.get("action_name")),
        _value(data.get("action_location")),
        _date_text(data.get("completed_at")),
        _value(data.get("handler_name")),
        _value(data.get("content")),
        _value(data.get("image_url")),
        _value(data.get("approver_name")),
        _value(data.get("type")),
    ]


def _row_tcs(table: Table, row_index: int):
    return table.rows[row_index]._tr.findall(qn("w:tc"))


def _set_tc_text(tc, table: Table, value: str) -> None:
    # Write through the first existing run so template formatting (font/color) survives;
    # cell.text = value would replace the paragraph and drop that formatting.
    cell = _Cell(tc, table)
    paragraphs = cell.paragraphs
    if not paragraphs:
        cell.text = value
        return

    first_paragraph = paragraphs[0]
    runs = first_paragraph.runs
    if runs:
        runs[0].text = value
        for extra_run in runs[1:]:
            extra_run.text = ""
    else:
        first_paragraph.add_run(value)

    for extra_paragraph in paragraphs[1:]:
        for run in extra_paragraph.runs:
            run.text = ""


def _ensure_row_pair(table: Table, pair_index: int) -> int:
    # Each data row is a vertically merged "restart" + "continue" <w:tr> pair. The
    # template pre-builds a handful of blank pairs; clone the last one for overflow.
    restart_index = DATA_START_ROW_INDEX + pair_index * 2
    while len(table.rows) <= restart_index + 1:
        last_restart = table.rows[-2]._tr
        last_continue = table.rows[-1]._tr
        table._tbl.append(copy.deepcopy(last_restart))
        table._tbl.append(copy.deepcopy(last_continue))
    return restart_index


def _write_data_row(table: Table, restart_index: int, values: list[str]) -> None:
    tcs = _row_tcs(table, restart_index)
    for column_index, value in enumerate(values[:DATA_COLUMN_COUNT]):
        if column_index < len(tcs):
            _set_tc_text(tcs[column_index], table, value)


def fill_risk_assessment_form_docx(
    source_data: dict[str, Any],
    correction_result: RiskDataCorrectionResult,
    form_path: Path | str = DEFAULT_FORM_PATH,
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
) -> str:
    form_path = Path(form_path)
    output_path = Path(output_path)

    document = Document(str(form_path))
    table = document.tables[0]

    info = _company_info(source_data)
    meta_tcs = _row_tcs(table, META_ROW_INDEX)
    company_name = _first_non_empty(info.get("company_name"))
    if company_name and COMPANY_NAME_TC_INDEX < len(meta_tcs):
        _set_tc_text(meta_tcs[COMPANY_NAME_TC_INDEX], table, company_name)
    if GENERATED_DATE_TC_INDEX < len(meta_tcs):
        _set_tc_text(meta_tcs[GENERATED_DATE_TC_INDEX], table, date.today().isoformat())

    for pair_index, row in enumerate(correction_result.corrected_rows):
        restart_index = _ensure_row_pair(table, pair_index)
        _write_data_row(table, restart_index, _form_row(row))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        document.save(str(output_path))
        return str(output_path)
    except PermissionError:
        fallback_path = output_path.with_name(f"{output_path.stem}_new{output_path.suffix}")
        document.save(str(fallback_path))
        return str(fallback_path)
