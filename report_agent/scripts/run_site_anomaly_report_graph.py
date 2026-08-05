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
from app.graph import site_anomaly_full_graph
from scripts.fill_management_review_order_docx import DEFAULT_TEMPLATE_PATH, fill_docx_template
from app.schemas import SiteAnomalyReportRequest, SiteAnomalyReportResponse

INPUT_PATH = PROJECT_ROOT / "output" / "final_history_table_corrected.json"
RESPONSE_PATH = PROJECT_ROOT / "output" / "management_review_order_response.json"
REPORT_PATH = PROJECT_ROOT / "output" / "management_review_order.md"
DOCX_REPORT_PATH = PROJECT_ROOT / "output" / "management_review_order.docx"


def _markdown(response: SiteAnomalyReportResponse) -> str:
    report = response.report
    lines = [
        f"# {report.title}",
        "",
        f"- 상태: {response.status}",
        f"- 기간: {report.period}",
        f"- 검토 점수: {response.review.score}",
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

    request = SiteAnomalyReportRequest(**payload)
    result = await site_anomaly_full_graph.ainvoke(
        {
            "request": request,
            "retry_count": 0,
            "max_retry_count": MAX_RETRY_COUNT,
            "errors": [],
        }
    )
    review_result = result["review_result"]
    response = SiteAnomalyReportResponse(
        status="COMPLETED" if review_result.passed else "FAILED",
        retry_count=result.get("retry_count", 0),
        aggregated_data=result["aggregated_data"],
        analysis_result=result["analysis_result"],
        report=result["generated_report"],
        review=review_result,
    )

    RESPONSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESPONSE_PATH.open("w", encoding="utf-8-sig") as file:
        json.dump(response.model_dump(mode="json"), file, ensure_ascii=False, indent=2)
    REPORT_PATH.write_text(_markdown(response), encoding="utf-8-sig")
    docx_report_path = fill_docx_template(response.model_dump(mode="json"), DEFAULT_TEMPLATE_PATH, DOCX_REPORT_PATH)

    print(json.dumps({
        "status": response.status,
        "retry_count": response.retry_count,
        "review_passed": response.review.passed,
        "review_score": response.review.score,
        "response_path": str(RESPONSE_PATH),
        "report_path": str(REPORT_PATH),
        "docx_report_path": str(docx_report_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())






