import asyncio
import json
from pathlib import Path

from app.config import MAX_RETRY_COUNT
from app.graph import risk_assessment_form_graph
from app.schemas import RiskAssessmentFormRequest, RiskAssessmentFormResponse

INPUT_PATH = Path("output/separated_history_dummy_tables.json")
DEFAULT_RESPONSE_PATH = Path("output/risk_assessment_form_graph_response.json")
DEFAULT_CSV_PATH = Path("output/risk_assessment_form_filled.csv")


async def main():
    with INPUT_PATH.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    request = RiskAssessmentFormRequest(
        **payload,
        output_path=str(DEFAULT_CSV_PATH),
    )
    result = await risk_assessment_form_graph.ainvoke(
        {
            "request": request,
            "retry_count": 0,
            "max_retry_count": MAX_RETRY_COUNT,
            "errors": [],
        }
    )

    review_result = result["correction_review"]
    csv_output_path = result.get("csv_output_path")
    response = RiskAssessmentFormResponse(
        status="COMPLETED" if review_result.approved and csv_output_path else "FAILED",
        retry_count=result.get("retry_count", 0),
        final_history_rows=result.get("final_history_rows", []),
        correction_result=result["correction_result"],
        correction_review=review_result,
        csv_output_path=csv_output_path,
    )

    DEFAULT_RESPONSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DEFAULT_RESPONSE_PATH.open("w", encoding="utf-8-sig") as file:
        json.dump(response.model_dump(mode="json"), file, ensure_ascii=False, indent=2)

    print(json.dumps({
        "status": response.status,
        "retry_count": response.retry_count,
        "rows": len(response.correction_result.corrected_rows),
        "corrections": len(response.correction_result.correction_notes),
        "review_approved": response.correction_review.approved,
        "review_score": response.correction_review.score,
        "csv_output_path": response.csv_output_path,
        "response_path": str(DEFAULT_RESPONSE_PATH),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
