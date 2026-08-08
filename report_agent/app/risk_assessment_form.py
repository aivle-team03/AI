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
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.schemas import FinalHistoryRow, RiskDataCorrectionResult

HEADER_ROW_INDEX = 7
DATA_START_ROW_INDEX = 8
COLUMN_COUNT = 25
DEFAULT_FORM_PATH = Path(r"C:\Users\User\Downloads\위험성평가표 - 시트1.csv")
DEFAULT_XLSX_TEMPLATE_PATH = Path(r"C:\Users\User\Downloads\위험성평가표_양식.xlsx")
DEFAULT_OUTPUT_PATH = Path("output/risk_assessment_form/risk_assessment_form_filled.csv")

# 1-based column indices that hold image URLs (output[10]=inspection_image_url, output[21]=image_url).
IMAGE_COLUMNS = {11, 22}
IMAGE_WIDTH_EMU = 1143000
IMAGE_HEIGHT_EMU = 762000

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


def _download_image(url: str | None) -> bytes | None:
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=15) as response:
            return response.read()
    except (HTTPError, URLError, ValueError, TimeoutError):
        return None


def _guess_image_ext(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG"):
        return "png"
    if image_bytes.startswith(b"\xff\xd8"):
        return "jpeg"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if image_bytes.startswith(b"BM"):
        return "bmp"
    return "png"


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
    output[10] = _value(data.get("inspection_image_url"))
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


# CT_Worksheet child element order (ECMA-376), used to insert <drawing> in a schema-valid position.
_CT_WORKSHEET_ORDER = [
    "sheetPr", "dimension", "sheetViews", "sheetFormatPr", "cols", "sheetData",
    "sheetCalcPr", "sheetProtection", "protectedRanges", "scenarios", "autoFilter",
    "sortState", "dataConsolidate", "customSheetViews", "mergeCells", "phoneticPr",
    "conditionalFormatting", "dataValidations", "hyperlinks", "printOptions",
    "pageMargins", "pageSetup", "headerFooter", "rowBreaks", "colBreaks",
    "customProperties", "cellWatches", "ignoredErrors", "smartTags", "drawing",
    "drawingHF", "picture", "oleObjects", "controls", "webPublishItems",
    "tableParts", "extLst",
]


def _insert_in_schema_order(root: ET.Element, new_element: ET.Element, tag: str) -> None:
    target_index = _CT_WORKSHEET_ORDER.index(tag)
    insert_at = len(list(root))
    for index, child in enumerate(root):
        local_name = child.tag.split("}")[-1]
        if local_name in _CT_WORKSHEET_ORDER and _CT_WORKSHEET_ORDER.index(local_name) > target_index:
            insert_at = index
            break
    root.insert(insert_at, new_element)


def _drawing_rels_xml(image_files: list[tuple[str, str]]) -> str:
    relationships = "".join(
        f'<Relationship Id="{rid}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        f'Target="../media/{filename}"/>'
        for rid, filename in image_files
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{relationships}</Relationships>'
    )


def _drawing_xml(anchors: list[tuple[int, int, str]]) -> str:
    entries = []
    for anchor_id, (row0, col0, rid) in enumerate(anchors, start=1):
        entries.append(
            "<xdr:oneCellAnchor>"
            f"<xdr:from><xdr:col>{col0}</xdr:col><xdr:colOff>0</xdr:colOff>"
            f"<xdr:row>{row0}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>"
            f'<xdr:ext cx="{IMAGE_WIDTH_EMU}" cy="{IMAGE_HEIGHT_EMU}"/>'
            "<xdr:pic>"
            "<xdr:nvPicPr>"
            f'<xdr:cNvPr id="{anchor_id + 1}" name="Picture {anchor_id}"/>'
            "<xdr:cNvPicPr><a:picLocks noChangeAspect=\"1\"/></xdr:cNvPicPr>"
            "</xdr:nvPicPr>"
            f'<xdr:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>'
            "<xdr:spPr>"
            f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{IMAGE_WIDTH_EMU}" cy="{IMAGE_HEIGHT_EMU}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            "</xdr:spPr>"
            "</xdr:pic>"
            "<xdr:clientData/>"
            "</xdr:oneCellAnchor>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        "<xdr:wsDr "
        'xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'{"".join(entries)}</xdr:wsDr>'
    )


def _ensure_content_type_default(content_types_text: str, extension: str, content_type: str) -> str:
    if f'Extension="{extension}"' in content_types_text:
        return content_types_text
    insertion = f'<Default Extension="{extension}" ContentType="{content_type}"/>'
    return content_types_text.replace("</Types>", f"{insertion}</Types>")


def _ensure_content_type_override(content_types_text: str, part_name: str, content_type: str) -> str:
    if f'PartName="{part_name}"' in content_types_text:
        return content_types_text
    insertion = f'<Override PartName="{part_name}" ContentType="{content_type}"/>'
    return content_types_text.replace("</Types>", f"{insertion}</Types>")


def _embed_images_in_xlsx(xlsx_path: Path, rows: list[list[str]]) -> None:
    if not xlsx_path.exists():
        return

    downloads: list[tuple[int, int, bytes]] = []
    for row_offset, row in enumerate(rows):
        if row_offset < DATA_START_ROW_INDEX:
            continue
        for column_index in IMAGE_COLUMNS:
            url = row[column_index - 1] if column_index - 1 < len(row) else ""
            image_bytes = _download_image(url)
            if image_bytes:
                downloads.append((row_offset, column_index, image_bytes))

    if not downloads:
        return

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        with zipfile.ZipFile(xlsx_path, "r") as archive:
            archive.extractall(temp_path)

        sheet_path = temp_path / "xl" / "worksheets" / "sheet1.xml"
        tree = ET.parse(sheet_path)
        root = tree.getroot()
        sheet_data = root.find("main:sheetData", NS)

        media_dir = temp_path / "xl" / "media"
        media_dir.mkdir(parents=True, exist_ok=True)

        image_files: list[tuple[str, str]] = []
        anchors: list[tuple[int, int, str]] = []
        for index, (row0, column_index, image_bytes) in enumerate(downloads, start=1):
            ext = _guess_image_ext(image_bytes)
            filename = f"image{index}.{ext}"
            (media_dir / filename).write_bytes(image_bytes)
            rid = f"rId{index}"
            image_files.append((rid, filename))
            anchors.append((row0, column_index - 1, rid))

            if sheet_data is not None:
                ref = f"{_column_name(column_index)}{row0 + 1}"
                _replace_cell_value(sheet_data, ref, "")

        # CT_Worksheet allows only one <drawing> element. If the template already has
        # one (e.g. a placeholder/logo drawing), reuse its relationship id and target
        # path instead of appending a second <drawing>, which Excel treats as corrupt.
        r_id_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        sheet_rels_path = temp_path / "xl" / "worksheets" / "_rels" / "sheet1.xml.rels"
        sheet_rels_path.parent.mkdir(parents=True, exist_ok=True)
        rels_text = (
            sheet_rels_path.read_text(encoding="utf-8")
            if sheet_rels_path.exists()
            else (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                "</Relationships>"
            )
        )

        existing_drawing = root.find("main:drawing", NS)
        drawing_target = "../drawings/drawing1.xml"
        if existing_drawing is not None:
            existing_rid = existing_drawing.get(r_id_attr)
            match = re.search(
                rf'<Relationship Id="{re.escape(existing_rid)}"[^>]*Target="([^"]+)"', rels_text
            )
            if match:
                drawing_target = match.group(1)
        else:
            drawing_relationship_id = "rIdDrawing1"
            existing_ids = set(re.findall(r'Id="([^"]+)"', rels_text))
            suffix = 1
            while drawing_relationship_id in existing_ids:
                suffix += 1
                drawing_relationship_id = f"rIdDrawing{suffix}"
            relationship = (
                f'<Relationship Id="{drawing_relationship_id}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" '
                f'Target="{drawing_target}"/>'
            )
            rels_text = rels_text.replace("</Relationships>", f"{relationship}</Relationships>")
            sheet_rels_path.write_text(rels_text, encoding="utf-8")

            drawing_element = ET.Element(f"{{{NS['main']}}}drawing")
            drawing_element.set(r_id_attr, drawing_relationship_id)
            _insert_in_schema_order(root, drawing_element, "drawing")
            tree.write(sheet_path, encoding="utf-8", xml_declaration=True)

        drawing_path = (temp_path / "xl" / "worksheets" / drawing_target).resolve()
        drawing_path.parent.mkdir(parents=True, exist_ok=True)
        drawing_path.write_text(_drawing_xml(anchors), encoding="utf-8")
        drawing_rels_dir = drawing_path.parent / "_rels"
        drawing_rels_dir.mkdir(parents=True, exist_ok=True)
        (drawing_rels_dir / f"{drawing_path.name}.rels").write_text(
            _drawing_rels_xml(image_files), encoding="utf-8"
        )

        content_types_path = temp_path / "[Content_Types].xml"
        content_types_text = content_types_path.read_text(encoding="utf-8")
        for _, filename in image_files:
            ext = filename.rsplit(".", 1)[-1]
            content_type = f"image/{ext}"
            content_types_text = _ensure_content_type_default(content_types_text, ext, content_type)
        content_types_text = _ensure_content_type_override(
            content_types_text,
            "/xl/drawings/drawing1.xml",
            "application/vnd.openxmlformats-officedocument.drawing+xml",
        )
        content_types_path.write_text(content_types_text, encoding="utf-8")

        try:
            shutil.make_archive(str(xlsx_path.with_suffix("")), "zip", temp_path)
            zip_path = xlsx_path.with_suffix(".zip")
            xlsx_path.unlink()
            zip_path.replace(xlsx_path)
        except PermissionError:
            fallback_path = xlsx_path.with_name(f"{xlsx_path.stem}_new{xlsx_path.suffix}")
            shutil.make_archive(str(fallback_path.with_suffix("")), "zip", temp_path)
            zip_path = fallback_path.with_suffix(".zip")
            if fallback_path.exists():
                fallback_path.unlink()
            zip_path.replace(fallback_path)


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
        archive.writestr("xl/styles.xml", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy-mm-dd hh:mm"/></numFmts><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1"/></xf><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>''')
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
    _embed_images_in_xlsx(resolved_xlsx_path_for(csv_output_path), output_rows)

    return str(csv_output_path)


