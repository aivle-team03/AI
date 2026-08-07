from __future__ import annotations

import argparse
import copy
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "output" / "risk_assessment_report_template.docx"
DEFAULT_RESPONSE_PATH = PROJECT_ROOT / "output" / "risk_assessment_reports" / "risk_assessment_report_response.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "output" / "risk_assessment_reports" / "risk_assessment_report.docx"


def _section_content(report: dict, section_code: str) -> str:
    for section in report.get("sections") or []:
        if section.get("section_code") == section_code:
            return section.get("content") or ""
    return ""


def _fmt_count_map(values: dict | None) -> str:
    values = values or {}
    if not values:
        return "-"
    return " / ".join(f"{key}: {value}건" for key, value in values.items())


def _fmt_items(items: list[dict], key: str, default: str = "-") -> str:
    values = []
    for idx, item in enumerate(items, start=1):
        if key == "no":
            values.append(str(idx))
        else:
            value = item.get(key)
            if isinstance(value, bool):
                value = "완료" if value else "미완료"
            values.append(str(value if value not in (None, "") else default))
    return "\n".join(values) if values else default


def _value_map(response: dict) -> dict[str, str]:
    report = response.get("report") or {}
    aggregated = response.get("aggregated_data") or {}
    context = aggregated.get("report_context") or {}
    company = context.get("company") or {}
    kpi = aggregated.get("kpi") or {}
    trend = aggregated.get("trend") or {}
    risk_distribution = aggregated.get("risk_distribution") or {}
    high_risk_items = aggregated.get("high_risk_items") or []

    return {
        "report.title": report.get("title") or "위험성평가보고서",
        "report.period": report.get("period") or _period_text(context.get("period")),
        "generated_date": datetime.now().strftime("%Y-%m-%d"),
        "aggregated_data.report_context.company.name": company.get("name") or company.get("company_name") or "-",
        "report.summary": report.get("summary") or "-",
        "report.conclusion": report.get("conclusion") or "-",
        "report.sections.RISK_DISTRIBUTION.content": _section_content(report, "RISK_DISTRIBUTION") or "-",
        "aggregated_data.kpi.assessment_records": str(kpi.get("assessment_records", 0)),
        "aggregated_data.kpi.critical_risk_records": str(kpi.get("critical_risk_records", 0)),
        "aggregated_data.kpi.high_risk_records": str(kpi.get("high_risk_records", 0)),
        "aggregated_data.kpi.medium_risk_records": str(kpi.get("medium_risk_records", 0)),
        "aggregated_data.kpi.low_risk_records": str(kpi.get("low_risk_records", 0)),
        "aggregated_data.kpi.high_or_critical_risk_records": str(kpi.get("high_or_critical_risk_records", 0)),
        "aggregated_data.kpi.action_total": str(kpi.get("action_total", 0)),
        "aggregated_data.kpi.action_completion_rate": f"{kpi.get('action_completion_rate', 0)}%",
        "aggregated_data.kpi.approval_completion_rate": f"{kpi.get('approval_completion_rate', 0)}%",
        "aggregated_data.kpi.board_action_history_rate": f"{kpi.get('board_action_history_rate', 0)}%",
        "aggregated_data.kpi.risk_recurrence_rate": f"{kpi.get('risk_recurrence_rate', 0)}%",
        "aggregated_data.kpi.unaddressed_assessment_records": str(kpi.get("unaddressed_assessment_records", 0)),
        "aggregated_data.kpi.unaddressed_high_risk_records": str(kpi.get("unaddressed_high_risk_records", 0)),
        "aggregated_data.risk_distribution.risk_band_counts": _fmt_count_map(risk_distribution.get("risk_band_counts")),
        "aggregated_data.trend.daily_assessment_counts": _section_content(report, "RISK_DISTRIBUTION") or "-",
        "aggregated_data.high_risk_items.no": _fmt_items(high_risk_items, "no"),
        "aggregated_data.high_risk_items.location": _fmt_items(high_risk_items, "location"),
        "aggregated_data.high_risk_items.category_name": _fmt_items(high_risk_items, "category_name"),
        "aggregated_data.high_risk_items.risk_band": _fmt_items(high_risk_items, "risk_band"),
        "aggregated_data.high_risk_items.inspection_content": _fmt_items(high_risk_items, "inspection_content"),
        "aggregated_data.high_risk_items.action_name": _fmt_items(high_risk_items, "action_name"),
        "aggregated_data.high_risk_items.action_content": _fmt_items(high_risk_items, "action_content"),
        "aggregated_data.high_risk_items.approval_name": _fmt_items(high_risk_items, "approval_name"),
    }


def _period_text(period: dict | None) -> str:
    period = period or {}
    start = period.get("start_date") or "-"
    end = period.get("end_date") or "-"
    return f"{start} ~ {end}" if start != "-" or end != "-" else "-"


STYLE_REPLACEMENTS = {
    "증명합니다": "증명한다",
    "양식입니다": "양식이다",
    "구성합니다": "구성한다",
    "요약합니다": "요약한다",
    "정리합니다": "정리한다",
    "제시합니다": "제시한다",
    "차지합니다": "차지한다",
    "나타났습니다": "나타났다",
    "필요합니다": "필요하다",
    "상황입니다": "상황이다",
    "수행되었습니다": "수행됐다",
    "확인되었습니다": "확인됐다",
    "되었습니다": "됐다",
    "합니다": "한다",
    "입니다": "이다",
}


def _normalize_report_style(value: str) -> str:
    text = str(value)
    for before, after in STYLE_REPLACEMENTS.items():
        text = text.replace(before, after)
    return text


def _xml_text(value: str) -> str:
    escaped = escape(_normalize_report_style(str(value)))
    return escaped.replace("\n", "</w:t><w:br/><w:t>")



HIGH_RISK_PREFIX = "aggregated_data.high_risk_items."


def _item_state(value: bool, done_text: str, pending_text: str) -> str:
    return done_text if value else pending_text


def _high_risk_item_value(item: dict, index: int, key: str) -> str:
    if key == "no":
        return str(index)
    if key == "action_name":
        return _item_state(bool(item.get("action_completed")), "조치 완료", "미조치")
    if key == "approval_name":
        return _item_state(bool(item.get("approval_completed")), "승인 완료", "승인 미완료")
    value = item.get(key)
    if isinstance(value, bool):
        return "완료" if value else "미완료"
    return str(value if value not in (None, "") else "-")


def _replace_high_risk_placeholders(row_xml: str, item: dict, index: int) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(1).strip()
        if key.startswith(HIGH_RISK_PREFIX):
            item_key = key.removeprefix(HIGH_RISK_PREFIX)
            return _xml_text(_high_risk_item_value(item, index, item_key))
        return match.group(0)

    return re.sub(r"\{\{\s*([^{}]+?)\s*\}\}", replace, row_xml)


def _expand_high_risk_item_rows(document_xml: str, response: dict) -> str:
    items = ((response.get("aggregated_data") or {}).get("high_risk_items") or [])
    row_pattern = re.compile(r"<w:tr[\s\S]*?</w:tr>")

    def replace_row(match: re.Match) -> str:
        row_xml = match.group(0)
        if "{{aggregated_data.high_risk_items." not in row_xml:
            return row_xml
        source_items = items or [{}]
        return "".join(
            _replace_high_risk_placeholders(row_xml, item, index)
            for index, item in enumerate(source_items, start=1)
        )

    return row_pattern.sub(replace_row, document_xml)
def fill_docx_template(response: dict, template_path: Path, output_path: Path) -> Path:
    values = _value_map(response)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")

    with zipfile.ZipFile(template_path, "r") as zin, zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.startswith("word/") and item.filename.endswith(".xml"):
                text = data.decode("utf-8", errors="ignore")
                if item.filename == "word/document.xml":
                    text = _expand_high_risk_item_rows(text, response)

                def replace(match: re.Match) -> str:
                    key = match.group(1).strip()
                    return _xml_text(values.get(key, "-"))

                text = pattern.sub(replace, text)
                text = text.replace("위험도 분포 및 평가 추세", "위험도 분포 및 관리 현황")
                text = text.replace("평가 추세", "관리 현황")
                text = _normalize_report_style(text)
                data = text.encode("utf-8")
            copied = copy.copy(item)
            zout.writestr(copied, data)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill risk assessment report DOCX template.")
    parser.add_argument("--response", default=str(DEFAULT_RESPONSE_PATH))
    parser.add_argument("--template", default=str(DEFAULT_TEMPLATE_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    args = parser.parse_args()

    with Path(args.response).open("r", encoding="utf-8-sig") as file:
        response = json.load(file)
    out = fill_docx_template(response, Path(args.template), Path(args.output))
    print(out.resolve())


if __name__ == "__main__":
    main()





