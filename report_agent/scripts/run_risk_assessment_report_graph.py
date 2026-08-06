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
from app.risk_assessment.graph import risk_assessment_report_graph
from app.schemas import RiskAssessmentReportRequest, RiskAssessmentReportResponse
from scripts.fill_risk_assessment_report_docx import DEFAULT_TEMPLATE_PATH, fill_docx_template

INPUT_PATH = PROJECT_ROOT / "output" / "BackendData.json"
OUTPUT_DIR = PROJECT_ROOT / "output" / "risk_assessment_reports"
RESPONSE_PATH = OUTPUT_DIR / "risk_assessment_report_response.json"
REPORT_PATH = OUTPUT_DIR / "risk_assessment_report.md"
DOCX_REPORT_PATH = OUTPUT_DIR / "risk_assessment_report.docx"


def _dedupe_repeated_sentences(text: str) -> str:
    sentences = []
    seen = set()
    for sentence in text.split(". "):
        normalized = " ".join(sentence.strip().split())
        key = normalized.replace(".", "")
        if "안정적인 추세" in key or "안정적" in key:
            if key in seen:
                continue
            seen.add(key)
        sentences.append(sentence)
    return ". ".join(sentences)


def _markdown(response: RiskAssessmentReportResponse) -> str:
    report = response.report
    lines = [
        f"# {report.title}",
        "",
        f"- 기간: {report.period}",
        "",
    ]
    for section in report.sections:
        lines.extend([
            f"## {section.heading}",
            _dedupe_repeated_sentences(section.content),
            "",
        ])
    has_conclusion_section = any(section.heading.strip() == "결론" for section in report.sections)
    if not has_conclusion_section:
        lines.extend([
            "## 결론",
            _dedupe_repeated_sentences(report.conclusion),
            "",
        ])
    if report.limitations:
        lines.append("## 한계")
        lines.extend(f"- {item}" for item in report.limitations)
        lines.append("")
    return "\n".join(lines)


async def main() -> None:
    with INPUT_PATH.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    request = RiskAssessmentReportRequest(**payload)
    result = await risk_assessment_report_graph.ainvoke(
        {
            "request": request,
            "retry_count": 0,
            "max_retry_count": MAX_RETRY_COUNT,
            "errors": [],
        }
    )
    review_result = result["review_result"]
    response = RiskAssessmentReportResponse(
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
    docx_report_path = fill_docx_template(
        response.model_dump(mode="json"),
        DEFAULT_TEMPLATE_PATH,
        DOCX_REPORT_PATH,
    )

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

