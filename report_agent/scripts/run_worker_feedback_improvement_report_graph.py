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
from app.worker_feedback.graph import worker_feedback_improvement_graph
from app.worker_feedback.schemas import (
    WorkerFeedbackImprovementReportRequest,
    WorkerFeedbackImprovementReportResponse,
)

INPUT_PATH = PROJECT_ROOT / "output" / "BackendData.json"
RESPONSE_PATH = PROJECT_ROOT / "output" / "worker_feedback_improvement_report_response.json"


async def run_graph(request):
    state = {
        "request": request,
        "retry_count": 0,
        "max_retry_count": MAX_RETRY_COUNT,
        "errors": [],
    }

    print("[1/4] 종사자 의견청취 테이블 생성 시작", flush=True)
    async for event in worker_feedback_improvement_graph.astream(
        state,
        stream_mode="updates",
    ):
        for node_name, update in event.items():
            if isinstance(update, dict):
                state.update(update)

            if node_name == "build_worker_feedback_table":
                print("[1/4] 종사자 의견청취 테이블 생성 완료", flush=True)
                print("[2/4] 데이터 수정 agent 실행 중", flush=True)
            elif node_name == "worker_feedback_correction_agent":
                print("[2/4] 데이터 수정 agent 완료", flush=True)
                print("[3/4] 데이터 검토 agent 실행 중", flush=True)
            elif node_name == "worker_feedback_correction_review_agent":
                print("[3/4] 데이터 검토 agent 완료", flush=True)
                print("[4/4] 워드 보고서 생성 중", flush=True)
            elif node_name == "retry":
                print("검토 결과 수정 필요: 데이터 수정 agent 재실행", flush=True)
            elif node_name == "fill_worker_feedback_word":
                print("[4/4] 워드 보고서 생성 완료", flush=True)

    return state


async def main() -> None:
    print(f"프로젝트 경로: {PROJECT_ROOT}", flush=True)
    print(f"입력 데이터: {INPUT_PATH}", flush=True)

    with INPUT_PATH.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    request = WorkerFeedbackImprovementReportRequest(**payload)
    result = await run_graph(request)

    review_result = result["correction_review"]
    word_output_paths = result.get("word_output_paths", [])
    response = WorkerFeedbackImprovementReportResponse(
        status="COMPLETED" if review_result.approved and word_output_paths else "FAILED",
        retry_count=result.get("retry_count", 0),
        worker_feedback_rows=result.get("worker_feedback_rows", []),
        correction_result=result["correction_result"],
        correction_review=review_result,
        word_output_paths=word_output_paths,
    )

    RESPONSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESPONSE_PATH.open("w", encoding="utf-8-sig") as file:
        json.dump(response.model_dump(mode="json"), file, ensure_ascii=False, indent=2)

    print(
        json.dumps(
            {
                "status": response.status,
                "retry_count": response.retry_count,
                "rows": len(response.correction_result.corrected_rows),
                "corrections": len(response.correction_result.correction_notes),
                "review_approved": response.correction_review.approved,
                "review_score": response.correction_review.score,
                "word_output_paths": response.word_output_paths,
                "response_path": str(RESPONSE_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
