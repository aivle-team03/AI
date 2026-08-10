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
from app.common.s3_upload import load_final_history_rows_from_s3_period, upload_docx_to_s3
from app.management.graph import management_review_order_no_preprocessing_graph
from app.management.schemas import SiteAnomalyReportRequest, SiteAnomalyReportResponse
from scripts.fill_management_review_order_docx import DEFAULT_TEMPLATE_PATH, fill_docx_template


INPUT_PATH = PROJECT_ROOT / "output" /"risk_assessment_form"/ "risk_assessment_form_graph_response.json"
OUTPUT_DIR = PROJECT_ROOT / "output" / "management_reports"
RESPONSE_PATH = OUTPUT_DIR / "management_review_order_no_preprocessing_response.json"
REPORT_PATH = OUTPUT_DIR / "management_review_order_no_preprocessing.md"
S3_PREFIX = "report/management-review-order/"
DAILY_JSON_S3_PREFIX = "report/daily-json/"


def _load_final_history_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if isinstance(payload.get("final_history_rows"), list):
            return payload["final_history_rows"]
        correction_result = payload.get("correction_result") or {}
        if isinstance(correction_result.get("corrected_rows"), list):
            return correction_result["corrected_rows"]
        result = payload.get("result") or {}
        if isinstance(result.get("corrected_rows"), list):
            return result["corrected_rows"]

    raise ValueError(f"Unsupported final history JSON format: {path}")


def _load_final_history_rows_for_period(start_date: str | None, end_date: str | None) -> tuple[list[dict], str]:
    if not start_date or not end_date:
        return _load_final_history_rows(INPUT_PATH), str(INPUT_PATH)

    rows = load_final_history_rows_from_s3_period(
        start_date,
        end_date,
        DAILY_JSON_S3_PREFIX,
    )
    return rows, f"s3://aivle-team3-boss-bucket/{DAILY_JSON_S3_PREFIX}{start_date}..{end_date}"


def _date_key(value):
    if not value:
        return None
    text = str(value)
    return text[:10] if len(text) >= 10 else None


def _row_date(row: dict) -> str | None:
    return _date_key(row.get("completed_at")) or _date_key(row.get("inspection_date"))


def _period_suffix(start_date: str | None, end_date: str | None, rows: list[dict]) -> str:
    if start_date and end_date:
        return f"{start_date.replace('-', '_')}_{end_date.replace('-', '_')}"

    dates = sorted(day for row in rows if (day := _row_date(row)))
    if not dates:
        return "unknown"
    return f"{dates[0].replace('-', '_')}_{dates[-1].replace('-', '_')}"


def _markdown(response: SiteAnomalyReportResponse) -> str:
    report = response.report
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    args = parser.parse_args()

    final_history_rows, input_source = _load_final_history_rows_for_period(
        args.start_date,
        args.end_date,
    )
    request = SiteAnomalyReportRequest(
        final_history_rows=final_history_rows,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    result = await management_review_order_no_preprocessing_graph.ainvoke(
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

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    response_payload = response.model_dump(mode="json")
    with RESPONSE_PATH.open("w", encoding="utf-8-sig") as file:
        json.dump(response_payload, file, ensure_ascii=False, indent=2)
    REPORT_PATH.write_text(_markdown(response), encoding="utf-8-sig")
    docx_output_path = OUTPUT_DIR / f"경영책임자검토지시서_{_period_suffix(args.start_date, args.end_date, final_history_rows)}.docx"
    docx_report_path = fill_docx_template(response_payload, DEFAULT_TEMPLATE_PATH, docx_output_path)
    s3_output_path = upload_docx_to_s3(docx_report_path, S3_PREFIX)
    response_payload["s3_output_path"] = s3_output_path
    with RESPONSE_PATH.open("w", encoding="utf-8-sig") as file:
        json.dump(response_payload, file, ensure_ascii=False, indent=2)

    print(json.dumps({
        "status": response.status,
        "report_type": "management_review_order",
        "preprocessing": False,
        "input_path": input_source,
        "final_history_rows": len(final_history_rows),
        "retry_count": response.retry_count,
        "review_passed": response.review.passed if response.review else None,
        "review_score": response.review.score if response.review else None,
        "response_path": str(RESPONSE_PATH),
        "report_path": str(REPORT_PATH),
        "docx_report_path": str(docx_report_path),
        "s3_output_path": s3_output_path,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

