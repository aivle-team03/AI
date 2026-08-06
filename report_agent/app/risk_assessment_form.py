from __future__ import annotations

import csv
import html
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

from app.schemas import FinalHistoryRow, RiskDataCorrectionResult

HEADER_ROW_INDEX = 7
DATA_START_ROW_INDEX = 8
COLUMN_COUNT = 25
DEFAULT_FORM_PATH = Path(r"C:\Users\User\Downloads\위험성평가표 - 시트1.csv")
DEFAULT_XLSX_TEMPLATE_PATH = Path(r"C:\Users\User\Downloads\위험성평가표_양식.xlsx")
DEFAULT_OUTPUT_PATH = Path("output/risk_assessment_form/risk_assessment_form_filled.csv")

COLUMN_WIDTHS = {
    1: 18,
    2: 12,
    3: 24,
    5: 20,
    6: 22,
    8: 14,
    9: 56,
    11: 28,
    13: 24,
    15: 20,
    16: 22,
    18: 14,
    20: 56,
    22: 28,
    24: 14,
    25: 14,
}
WRAP_COLUMNS = {9, 20}
DATE_COLUMNS = {6, 16}
NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
ET.register_namespace("", NS["main"])
ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
ET.register_namespace("mc", "http://schemas.openxmlformats.org/markup-compatibility/2006")
ET.register_namespace("x14ac", "http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac")
ET.register_namespace("xr", "http://schemas.microsoft.com/office/spreadsheetml/2014/revision")
ET.register_namespace("xr2", "http://schemas.microsoft.com/office/spreadsheetml/2015/revision2")
ET.register_namespace("xr3", "http://schemas.microsoft.com/office/spreadsheetml/2016/revision3")


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
    output[2] = _value(data.get("category"))
    output[4] = _value(data.get("inspection_location"))
    output[5] = _date_text(data.get("inspection_date"))
    output[7] = _value(data.get("inspection_user_name"))
    output[8] = _value(data.get("inspection_content"))
    output[10] = _value(data.get("image_url"))
    output[12] = _value(data.get("action_name"))
    output[14] = _value(data.get("action_location"))
    output[15] = _date_text(data.get("completed_at"))
    output[17] = _value(data.get("handler_name"))
    output[19] = _value(data.get("content"))
    output[21] = _value(data.get("image_url"))
    output[23] = _value(data.get("approver_name"))
    output[24] = _value(data.get("type"))
    return output


def _write_csv(path: Path, rows: list[list[str]], encoding: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w", encoding=encoding, newline="") as file:
            writer = csv.writer(file)
            writer.writerows(rows)
        return path
    except PermissionError:
        fallback_path = path.with_name(f"{path.stem}_new{path.suffix}")
        with fallback_path.open("w", encoding=encoding, newline="") as file:
            writer = csv.writer(file)
            writer.writerows(rows)
        return fallback_path


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _column_index(cell_ref: str) -> int:
    letters = re.sub(r"\d", "", cell_ref)
    result = 0
    for char in letters:
        result = result * 26 + ord(char.upper()) - 64
    return result


def _cell_xml(row_index: int, column_index: int, value: str, style_id: int) -> str:
    ref = f"{_column_name(column_index)}{row_index}"
    escaped = html.escape(value, quote=False)
    return (
        f'<c r="{ref}" t="inlineStr" s="{style_id}">'
        f'<is><t xml:space="preserve">{escaped}</t></is></c>'
    )


def _sheet_xml(rows: list[list[str]]) -> str:
    cols = []
    for column_index in range(1, COLUMN_COUNT + 1):
        width = COLUMN_WIDTHS.get(column_index, 10)
        cols.append(
            f'<col min="{column_index}" max="{column_index}" '
            f'width="{width}" customWidth="1"/>'
        )

    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        height = 18
        if row_index >= DATA_START_ROW_INDEX + 1:
            height = 48
        elif row_index == HEADER_ROW_INDEX + 1:
            height = 24

        cells = []
        for column_index in range(1, COLUMN_COUNT + 1):
            value = _value(row[column_index - 1] if column_index - 1 < len(row) else "")
            if column_index in WRAP_COLUMNS:
                style_id = 2
            elif row_index == HEADER_ROW_INDEX + 1:
                style_id = 1
            elif column_index in DATE_COLUMNS:
                style_id = 3
            else:
                style_id = 0
            cells.append(_cell_xml(row_index, column_index, value, style_id))
        sheet_rows.append(
            f'<row r="{row_index}" ht="{height}" customHeight="1">'
            f'{"".join(cells)}</row>'
        )

    dimension = f"A1:{_column_name(COLUMN_COUNT)}{len(rows)}"
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <dimension ref="{dimension}"/>
  <sheetViews><sheetView workbookViewId="0"><pane ySplit="8" topLeftCell="A9" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
  <cols>{''.join(cols)}</cols>
  <sheetData>{''.join(sheet_rows)}</sheetData>
</worksheet>'''


def _inline_cell(ref: str, value: str, style_id: str | None) -> ET.Element:
    cell = ET.Element(f"{{{NS['main']}}}c", {"r": ref, "t": "inlineStr"})
    if style_id is not None:
        cell.set("s", style_id)
    inline_string = ET.SubElement(cell, f"{{{NS['main']}}}is")
    text = ET.SubElement(inline_string, f"{{{NS['main']}}}t")
    text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text.text = value
    return cell


def _replace_cell_value(sheet_data: ET.Element, ref: str, value: str) -> None:
    row_number = int(re.sub(r"\D", "", ref))
    row = sheet_data.find(f"main:row[@r='{row_number}']", NS)
    if row is None:
        return
    old_cell = row.find(f"main:c[@r='{ref}']", NS)
    style_id = old_cell.get("s") if old_cell is not None else None
    new_cell = _inline_cell(ref, value, style_id)
    if old_cell is not None:
        row.remove(old_cell)
    row.append(new_cell)
    row[:] = sorted(row, key=lambda cell: _column_index(cell.get("r", "A1")))


def _style_by_column(template_row: ET.Element | None) -> dict[int, str]:
    styles: dict[int, str] = {}
    if template_row is None:
        return styles
    for cell in template_row.findall("main:c", NS):
        ref = cell.get("r", "")
        style_id = cell.get("s")
        if ref and style_id is not None:
            styles[_column_index(ref)] = style_id
    return styles


def _data_row_xml(row_index: int, row: list[str], styles: dict[int, str]) -> ET.Element:
    attrs = {
        "r": str(row_index),
        "spans": f"1:{COLUMN_COUNT}",
        "ht": "48",
        "customHeight": "1",
    }
    row_element = ET.Element(f"{{{NS['main']}}}row", attrs)
    for column_index in range(1, COLUMN_COUNT + 1):
        value = _value(row[column_index - 1] if column_index - 1 < len(row) else "")
        ref = f"{_column_name(column_index)}{row_index}"
        row_element.append(_inline_cell(ref, value, styles.get(column_index)))
    return row_element


def _keep_merge(ref: str) -> bool:
    rows = [int(value) for value in re.findall(r"\d+", ref)]
    return all(row < DATA_START_ROW_INDEX + 1 for row in rows)


def _write_xlsx_from_template(path: Path, template_path: Path, rows: list[list[str]], source_data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        with zipfile.ZipFile(template_path, "r") as archive:
            archive.extractall(temp_path)

        sheet_path = temp_path / "xl" / "worksheets" / "sheet1.xml"
        tree = ET.parse(sheet_path)
        root = tree.getroot()
        sheet_data = root.find("main:sheetData", NS)
        if sheet_data is None:
            raise ValueError("Template sheetData not found")

        info = _company_info(source_data)
        if info.get("company_name"):
            _replace_cell_value(sheet_data, "B3", info["company_name"])
        _replace_cell_value(sheet_data, "K3", date.today().isoformat())

        template_row = sheet_data.find(f"main:row[@r='{DATA_START_ROW_INDEX + 1}']", NS)
        styles = _style_by_column(template_row)

        for row in list(sheet_data.findall("main:row", NS)):
            row_number = int(row.get("r", "0"))
            if row_number >= DATA_START_ROW_INDEX + 1:
                sheet_data.remove(row)

        for offset, row in enumerate(rows[DATA_START_ROW_INDEX:], start=0):
            sheet_data.append(_data_row_xml(DATA_START_ROW_INDEX + 1 + offset, row, styles))

        dimension = root.find("main:dimension", NS)
        if dimension is not None:
            dimension.set("ref", f"A1:{_column_name(COLUMN_COUNT)}{len(rows)}")

        merge_cells = root.find("main:mergeCells", NS)
        if merge_cells is not None:
            for merge_cell in list(merge_cells.findall("main:mergeCell", NS)):
                if not _keep_merge(merge_cell.get("ref", "")):
                    merge_cells.remove(merge_cell)
            merge_cells.set("count", str(len(merge_cells.findall("main:mergeCell", NS))))

        tree.write(sheet_path, encoding="utf-8", xml_declaration=True)
        sheet_text = sheet_path.read_text(encoding="utf-8")
        sheet_text = sheet_text.replace('mc:Ignorable="x14ac xr xr2 xr3"', 'mc:Ignorable="x14ac xr"')
        sheet_path.write_text(sheet_text, encoding="utf-8")

        try:
            shutil.make_archive(str(path.with_suffix("")), "zip", temp_path)
            zip_path = path.with_suffix(".zip")
            if path.exists():
                path.unlink()
            zip_path.replace(path)
        except PermissionError:
            fallback_path = path.with_name(f"{path.stem}_new{path.suffix}")
            shutil.make_archive(str(fallback_path.with_suffix("")), "zip", temp_path)
            zip_path = fallback_path.with_suffix(".zip")
            if fallback_path.exists():
                fallback_path.unlink()
            zip_path.replace(fallback_path)


def _write_xlsx(path: Path, rows: list[list[str]], source_data: dict[str, Any] | None = None) -> None:
    source_data = source_data or {}
    if DEFAULT_XLSX_TEMPLATE_PATH.exists():
        _write_xlsx_from_template(path, DEFAULT_XLSX_TEMPLATE_PATH, rows, source_data)
        return

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>''')
        archive.writestr("_rels/.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>''')
        archive.writestr("xl/workbook.xml", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="위험성평가표" sheetId="1" r:id="rId1"/></sheets></workbook>''')
        archive.writestr("xl/_rels/workbook.xml.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>''')
        archive.writestr("xl/worksheets/sheet1.xml", _sheet_xml(rows))


def xlsx_path_for(output_path: Path | str) -> Path:
    output_path = Path(output_path)
    return output_path.with_suffix(".xlsx")




def resolved_xlsx_path_for(output_path: Path | str) -> Path:
    base_path = xlsx_path_for(output_path)
    fallback_path = base_path.with_name(f"{base_path.stem}_new{base_path.suffix}")
    if fallback_path.exists() and (
        not base_path.exists()
        or fallback_path.stat().st_mtime >= base_path.stat().st_mtime
    ):
        return fallback_path
    return base_path

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

    csv_output_path = _write_csv(output_path, output_rows, "utf-8-sig")
    _write_xlsx(xlsx_path_for(csv_output_path), output_rows, source_data)

    return str(csv_output_path)


