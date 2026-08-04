import asyncio
import json
import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=Warning, module="langgraph")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import MAX_RETRY_COUNT
from app.graph import risk_assessment_form_graph
from app.schemas import RiskAssessmentFormRequest, RiskAssessmentFormResponse

INPUT_PATH = PROJECT_ROOT / "output" / "separated_history_dummy_tables.json"
DEFAULT_RESPONSE_PATH = PROJECT_ROOT / "output" / "risk_assessment_form_graph_response.json"
DEFAULT_CSV_PATH = PROJECT_ROOT / "output" / "risk_assessment_form_filled.csv"
TIMEOUT_SECONDS = 180


async def run_graph(request):
    state = {
        "request": request,
        "retry_count": 0,
        "max_retry_count": MAX_RETRY_COUNT,
        "errors": [],
    }

    print("[1/4] 최종 이력 테이블 생성 시작", flush=True)
    async for event in risk_assessment_form_graph.astream(state, stream_mode="updates"):
        for node_name, update in event.items():
            if isinstance(update, dict):
                state.update(update)

            if node_name == "build_final_history_table":
                print("[1/4] 최종 이력 테이블 생성 완료", flush=True)
                print("[2/4] 데이터 수정 agent 실행 중", flush=True)
            elif node_name == "data_correction_agent":
                print("[2/4] 데이터 수정 agent 완료", flush=True)
                print("[3/4] 데이터 검토 agent 실행 중", flush=True)
            elif node_name == "data_correction_review_agent":
                print("[3/4] 데이터 검토 agent 완료", flush=True)
                print("[4/4] 위험성평가표 CSV 생성 중", flush=True)
            elif node_name == "retry":
                print("검토 결과 수정 필요: 데이터 수정 agent 재실행", flush=True)
            elif node_name == "fill_csv_form":
                print("[4/4] 위험성평가표 CSV 생성 완료", flush=True)

    return state


async def main():
    print(f"프로젝트 경로: {PROJECT_ROOT}", flush=True)
    print(f"입력 데이터: {INPUT_PATH}", flush=True)

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY 환경변수를 확인합니다.", flush=True)

    with INPUT_PATH.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    request = RiskAssessmentFormRequest(
        **payload,
        output_path=str(DEFAULT_CSV_PATH),
    )

    try:
        result = await asyncio.wait_for(run_graph(request), timeout=TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(
            f"{TIMEOUT_SECONDS}초 동안 응답이 없어 실행을 중단했습니다. "
            "네트워크, OPENAI_API_KEY, 모델 설정을 확인하세요."
        ) from exc

    review_result = result["correction_review"]
    csv_output_path = result.get("csv_output_path")
    response = RiskAssessmentFormResponse(
        status="COMPLETED" if review_result.approved and csv_output_path else "FAILED",
        retry_count=result.get("retry_count", 0),
        final_history_rows=result.get("final_history_rows", []),
        correction_result=result["correction_result"],
        correction_review=review_result,
        csv_output_path=csv_output_path,
        xlsx_output_path=result.get("xlsx_output_path"),
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
        "xlsx_output_path": response.xlsx_output_path,
        "response_path": str(DEFAULT_RESPONSE_PATH),
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())


