from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.graph import _management_judgment, _management_risk_label

DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "output" / "management_review_order_form.docx"
DEFAULT_RESPONSE_PATH = PROJECT_ROOT / "output" / "management_review_order_response.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "output" / "management_review_order.docx"

ANOMALY_PREFIX = "aggregated_data.anomaly_candidates."
DIRECTIVE_PREFIX = "report.sections.MANAGEMENT_DIRECTIVES.items."


def _section(report: dict, code: str) -> dict:
    for section in report.get("sections") or []:
        if section.get("section_code") == code:
            return section
    return {}


def _section_content(report: dict, code: str) -> str:
    return _section(report, code).get("content") or ""


def _review_detail(report: dict) -> str:
    content = _section_content(report, "MANAGEMENT_REVIEW_CONTENT")
    if "\n\n" in content:
        return content.split("\n\n", 1)[1].strip()
    return content.strip()


def _directive_items(report: dict) -> list[dict[str, str]]:
    content = _section_content(report, "MANAGEMENT_DIRECTIVES")
    content = re.sub(r"\s+", " ", content).strip()
    if not content:
        return []

    numbered = list(re.finditer(r"(?:^|\s)(\d+)\.\s+", content))
    items = []
    if numbered:
        for index, match in enumerate(numbered):
            start = match.end()
            end = numbered[index + 1].start() if index + 1 < len(numbered) else len(content)
            directive = content[start:end].strip()
            if directive:
                items.append({"no": match.group(1), "directive": directive})
        return items

    sentences = [part.strip() for part in re.split(r"(?<=다\.)\s+|(?<=것\.)\s+", content) if part.strip()]
    return [
        {"no": str(index), "directive": directive}
        for index, directive in enumerate(sentences, start=1)
    ]


def _period_text(context: dict) -> str:
    period = context.get("period") or {}
    start = period.get("start_date") or "-"
    end = period.get("end_date") or "-"
    return f"{start} ~ {end}" if start != "-" or end != "-" else "-"


def _value_map(response: dict) -> dict[str, str]:
    report = response.get("report") or {}
    aggregated = response.get("aggregated_data") or {}
    context = aggregated.get("site_context") or {}
    company = context.get("company") or {}
    signoff = _section_content(report, "APPROVAL_SIGNOFF")
    return {
        "report.title": report.get("title") or "경영책임자 검토지시서",
        "report.period": report.get("period") or _period_text(context),
        "generated_date": datetime.now().strftime("%Y-%m-%d"),
        "report.summary": report.get("summary") or "-",
        "report.conclusion": report.get("conclusion") or "-",
        "aggregated_data.site_context.company.company_name": company.get("company_name") or company.get("name") or "-",
        "aggregated_data.site_context.company.department_name": company.get("department_name") or "-",
        "aggregated_data.site_context.company.management_responsible_name": company.get("management_responsible_name") or "-",
        "report.sections.MANAGEMENT_REVIEW_CONTENT.content": _section_content(report, "MANAGEMENT_REVIEW_CONTENT") or "-",
        "report.sections.MANAGEMENT_REVIEW_CONTENT.detail": _review_detail(report) or "-",
        "report.sections.MANAGEMENT_DIRECTIVES.content": _section_content(report, "MANAGEMENT_DIRECTIVES") or "-",
        "report.sections.OVERALL_OPINION.content": _section_content(report, "OVERALL_OPINION") or "-",
        "report.sections.APPROVAL_SIGNOFF.content": signoff or "-",
        "report.sections.APPROVAL_SIGNOFF.preparer_signature": "",
        "report.sections.APPROVAL_SIGNOFF.reviewer_signature": "",
        "report.sections.APPROVAL_SIGNOFF.management_signature": "",
    }


def _xml_text(value: str) -> str:
    return escape(str(value)).replace("\n", "</w:t><w:br/><w:t>")

def _plain_xml_text(xml: str) -> str:
    return re.sub(r"<[^>]+>", "", xml)


def _normalize_split_placeholders(document_xml: str) -> str:
    def replace(match: re.Match) -> str:
        key = _plain_xml_text(match.group(0)).replace("{{", "").replace("}}", "")
        key = re.sub(r"\s+", "", key)
        return "{{" + key + "}}"

    return re.sub(r"\{\{[\s\S]*?\}\}", replace, document_xml)


def _anomaly_value(item: dict, key: str) -> str:
    if key == "severity":
        return _management_risk_label(item)
    if key == "management_judgment":
        return _management_judgment(item)
    value = item.get(key)
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value if value not in (None, "") else "-")


def _directive_value(item: dict, key: str) -> str:
    return str(item.get(key) if item.get(key) not in (None, "") else "-")


def _replace_repeated_placeholders(row_xml: str, item: dict, prefix: str, value_func) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(1).strip()
        if key.startswith(prefix):
            return _xml_text(value_func(item, key.removeprefix(prefix)))
        return match.group(0)
    return re.sub(r"\{\{\s*([^{}]+?)\s*\}\}", replace, row_xml)


def _expand_repeated_rows(document_xml: str, response: dict) -> str:
    aggregated = response.get("aggregated_data") or {}
    anomaly_items = aggregated.get("anomaly_candidates") or []
    directive_items = _directive_items(response.get("report") or {})
    row_pattern = re.compile(r"<w:tr[\s\S]*?</w:tr>")

    def replace_row(match: re.Match) -> str:
        row_xml = match.group(0)
        if "{{" + ANOMALY_PREFIX in row_xml:
            return "".join(
                _replace_repeated_placeholders(row_xml, item, ANOMALY_PREFIX, _anomaly_value)
                for item in (anomaly_items or [{}])
            )
        if "{{" + DIRECTIVE_PREFIX in row_xml:
            return "".join(
                _replace_repeated_placeholders(row_xml, item, DIRECTIVE_PREFIX, _directive_value)
                for item in (directive_items or [{}])
            )
        return row_xml

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
                text = _normalize_split_placeholders(text)
                if item.filename == "word/document.xml":
                    text = _expand_repeated_rows(text, response)

                def replace(match: re.Match) -> str:
                    key = match.group(1).strip()
                    return _xml_text(values.get(key, "-"))

                text = pattern.sub(replace, text)
                data = text.encode("utf-8")
            zout.writestr(copy.copy(item), data)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill management review order DOCX template.")
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



