from __future__ import annotations

import argparse
import asyncio
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=Warning, module="langgraph")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import MAX_RETRY_COUNT
from app.graph import unified_report_graph
from app.schemas import UnifiedReportRequest, UnifiedReportResponse
from scripts.fill_risk_assessment_report_docx import DEFAULT_TEMPLATE_PATH as RISK_REPORT_TEMPLATE_PATH, fill_docx_template as fill_risk_report_docx_template
from scripts.fill_management_review_order_docx import DEFAULT_TEMPLATE_PATH as MANAGEMENT_ORDER_TEMPLATE_PATH, fill_docx_template as fill_management_order_docx_template

DEFAULT_INPUT_PATH = PROJECT_ROOT / "output" / "separated_history_dummy_tables.json"
OUTPUT_NAME_BY_TYPE = {
    "risk_assessment_form": "risk_assessment_form_unified_response.json",
    "risk_assessment_report": "risk_assessment_report_unified_response.json",
    "site_anomaly_improvement": "management_review_order_unified_response.json",
    "management_review_order": "management_review_order_unified_response.json",
}
MARKDOWN_NAME_BY_TYPE = {
    "risk_assessment_report": "risk_assessment_report_unified.md",
    "site_anomaly_improvement": "management_review_order_unified.md",
    "management_review_order": "management_review_order_unified.md",
}


def _markdown(response: UnifiedReportResponse) -> str:
    report = response.report
    if not report:
        return ""
    lines = [
        f"# {report.title}",
        "",
        f"- 기간: {report.period}",
        "",
    ]
    for section in report.sections:
        lines.extend([
            f"## {section.heading}",
            section.content,
            "",
        ])
    has_conclusion_section = any(
        section.heading.strip() == "결론" for section in report.sections
    )
    is_management_order = response.report_type in {"management_review_order", "site_anomaly_improvement"}
    if not has_conclusion_section and not is_management_order:
        lines.extend([
            "## 결론",
            report.conclusion,
            "",
        ])
    if report.limitations and not is_management_order:
        lines.append("## 한계")
        lines.extend(f"- {item}" for item in report.limitations)
        lines.append("")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run preprocessing, then route to one report generation graph."
    )
    parser.add_argument(
        "--report-type",
        choices=list(OUTPUT_NAME_BY_TYPE),
        required=True,
        help="Report type to generate after preprocessing.",
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT_PATH),
        help="Raw separated table JSON path.",
    )
    parser.add_argument(
        "--output-path",
        default=None,
        help="Optional output path for risk_assessment_form CSV.",
    )
    parser.add_argument(
        "--form-path",
        default=None,
        help="Optional template/form path for risk_assessment_form.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    with input_path.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    request = UnifiedReportRequest(
        **payload,
        report_type=args.report_type,
        output_path=args.output_path,
        form_path=args.form_path,
    )
    result = await unified_report_graph.ainvoke(
        {
            "request": request,
            "retry_count": 0,
            "preprocessing_retry_count": 0,
            "max_retry_count": MAX_RETRY_COUNT,
            "errors": [],
        }
    )

    correction_review = result["correction_review"]
    review_result = result.get("review_result")
    is_form = args.report_type == "risk_assessment_form"
    report_passed = True if is_form else bool(review_result and review_result.passed)
    response = UnifiedReportResponse(
        status="COMPLETED" if correction_review.approved and report_passed else "FAILED",
        report_type=args.report_type,
        retry_count=result.get("retry_count", 0),
        preprocessing_retry_count=result.get("preprocessing_retry_count", 0),
        final_history_rows=result.get("final_history_rows", []),
        correction_result=result["correction_result"],
        correction_review=correction_review,
        aggregated_data=result.get("aggregated_data"),
        analysis_result=result.get("analysis_result"),
        report=result.get("generated_report"),
        review=review_result,
        csv_output_path=result.get("csv_output_path"),
        xlsx_output_path=result.get("xlsx_output_path"),
    )

    response_path = PROJECT_ROOT / "output" / OUTPUT_NAME_BY_TYPE[args.report_type]
    response_path.parent.mkdir(parents=True, exist_ok=True)
    with response_path.open("w", encoding="utf-8-sig") as file:
        json.dump(response.model_dump(mode="json"), file, ensure_ascii=False, indent=2)

    markdown_path = None
    docx_report_path = None
    if args.report_type in MARKDOWN_NAME_BY_TYPE and response.report:
        markdown_path = PROJECT_ROOT / "output" / MARKDOWN_NAME_BY_TYPE[args.report_type]
        markdown_path.write_text(_markdown(response), encoding="utf-8-sig")
        if args.report_type == "risk_assessment_report":
            docx_report_path = fill_risk_report_docx_template(
                response.model_dump(mode="json"),
                RISK_REPORT_TEMPLATE_PATH,
                PROJECT_ROOT / "output" / "risk_assessment_report_unified.docx",
            )
        elif args.report_type in {"management_review_order", "site_anomaly_improvement"}:
            docx_report_path = fill_management_order_docx_template(
                response.model_dump(mode="json"),
                MANAGEMENT_ORDER_TEMPLATE_PATH,
                PROJECT_ROOT / "output" / "management_review_order_unified.docx",
            )

    print(json.dumps({
        "status": response.status,
        "report_type": response.report_type,
        "preprocessing_retry_count": response.preprocessing_retry_count,
        "retry_count": response.retry_count,
        "correction_approved": response.correction_review.approved,
        "review_passed": response.review.passed if response.review else None,
        "review_score": response.review.score if response.review else None,
        "response_path": str(response_path),
        "markdown_path": str(markdown_path) if markdown_path else None,
        "docx_report_path": str(docx_report_path) if docx_report_path else None,
        "csv_output_path": response.csv_output_path,
        "xlsx_output_path": response.xlsx_output_path,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())



