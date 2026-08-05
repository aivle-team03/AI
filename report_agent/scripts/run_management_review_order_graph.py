from __future__ import annotations

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
from scripts.fill_management_review_order_docx import DEFAULT_TEMPLATE_PATH, fill_docx_template
from app.schemas import UnifiedReportRequest, UnifiedReportResponse

INPUT_PATH = PROJECT_ROOT / "output" / "separated_history_dummy_tables.json"
RESPONSE_PATH = PROJECT_ROOT / "output" / "management_review_order_response.json"
REPORT_PATH = PROJECT_ROOT / "output" / "management_review_order.md"
DOCX_REPORT_PATH = PROJECT_ROOT / "output" / "management_review_order.docx"


def _markdown(response: UnifiedReportResponse) -> str:
    report = response.report
    if not report:
        return ""
    lines = [
        f"# {report.title}",
        "",
        f"- 상태: {response.status}",
        f"- 기간: {report.period}",
        f"- 검토 점수: {response.review.score if response.review else '-'}",
        "",
        "## 요약",
        report.summary,
        "",
    ]
    for section in report.sections:
        lines.extend([
            f"## {section.heading}",
            section.content,
            "",
        ])
    return "\n".join(lines)


async def main() -> None:
    with INPUT_PATH.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    request = UnifiedReportRequest(**payload, report_type="management_review_order")
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
    report_passed = bool(review_result and review_result.passed)
    response = UnifiedReportResponse(
        status="COMPLETED" if correction_review.approved and report_passed else "FAILED",
        report_type="management_review_order",
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

    RESPONSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESPONSE_PATH.open("w", encoding="utf-8-sig") as file:
        json.dump(response.model_dump(mode="json"), file, ensure_ascii=False, indent=2)
    REPORT_PATH.write_text(_markdown(response), encoding="utf-8-sig")
    docx_report_path = fill_docx_template(response.model_dump(mode="json"), DEFAULT_TEMPLATE_PATH, DOCX_REPORT_PATH)

    print(json.dumps({
        "status": response.status,
        "report_type": response.report_type,
        "preprocessing_retry_count": response.preprocessing_retry_count,
        "retry_count": response.retry_count,
        "correction_approved": response.correction_review.approved,
        "review_passed": response.review.passed if response.review else None,
        "review_score": response.review.score if response.review else None,
        "response_path": str(RESPONSE_PATH),
        "report_path": str(REPORT_PATH),
        "docx_report_path": str(docx_report_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())


