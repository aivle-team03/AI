import asyncio
import json
import os
import sys
import warnings
from collections import defaultdict
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore", category=Warning, module="langgraph")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import MAX_RETRY_COUNT
from app.common.s3_upload import upload_docx_to_s3, upload_json_to_s3
from app.risk_assessment_form_graph.graph import risk_assessment_form_graph
from app.risk_assessment_form_graph.form_writer_word import (
    DEFAULT_FORM_PATH,
    fill_risk_assessment_form_docx,
)
from app.risk_assessment_form_graph.schemas import (
    RiskAssessmentFormRequest,
    RiskAssessmentFormResponse,
)

OUTPUT_DIR = PROJECT_ROOT / "output" / "risk_assessment_form"
DEFAULT_RESPONSE_PATH = OUTPUT_DIR / "risk_assessment_form_graph_response.json"
DEFAULT_DOCX_PATH = OUTPUT_DIR / "risk_assessment_form_filled.docx"
DAILY_DOCX_S3_PREFIX = "report/risk-assessment-form/"
DAILY_JSON_S3_PREFIX = "report/daily-json/"
TIMEOUT_SECONDS = int(os.getenv("RISK_FORM_TIMEOUT_SECONDS", "1200"))
CORRECTION_BATCH_SIZE = int(os.getenv("RISK_FORM_CORRECTION_BATCH_SIZE", "10"))


def _date_key(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date().isoformat()
    except ValueError:
        text = str(value)
        return text[:10] if len(text) >= 10 else None


def _row_date(row) -> str:
    data = row.model_dump(mode="json") if hasattr(row, "model_dump") else dict(row or {})
    return _date_key(data.get("completed_at")) or _date_key(data.get("inspection_date")) or "unknown"


def _file_date(day: str) -> str:
    return day.replace("-", "_")


def _daily_response_payload(response: RiskAssessmentFormResponse, rows) -> dict:
    payload = response.model_dump(mode="json")
    payload["final_history_rows"] = [
        row.model_dump(mode="json") if hasattr(row, "model_dump") else row
        for row in rows
    ]
    correction_result = payload.get("correction_result") or {}
    correction_result["corrected_rows"] = payload["final_history_rows"]
    correction_result["correction_notes"] = []
    correction_result["unresolved_notes"] = []
    payload["correction_result"] = correction_result
    return payload


def _write_daily_outputs(response: RiskAssessmentFormResponse, source_data: dict) -> list[dict]:
    rows_by_date = defaultdict(list)
    for row in response.correction_result.corrected_rows:
        rows_by_date[_row_date(row)].append(row)

    uploads = []
    for day, rows in sorted(rows_by_date.items()):
        daily_payload = _daily_response_payload(response, rows)
        json_path = OUTPUT_DIR / day / f"risk_assessment_form_graph_response_{day}.json"
        docx_path = OUTPUT_DIR / day / f"위험성평가표_{_file_date(day)}.docx"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with json_path.open("w", encoding="utf-8-sig") as file:
            json.dump(daily_payload, file, ensure_ascii=False, indent=2)

        daily_correction_result = response.correction_result.model_copy(
            update={
                "corrected_rows": rows,
                "correction_notes": [],
                "unresolved_notes": [],
            }
        )
        fill_risk_assessment_form_docx(
            source_data,
            daily_correction_result,
            form_path=DEFAULT_FORM_PATH,
            output_path=docx_path,
        )
        uploads.append(
            {
                "date": day,
                "rows": len(rows),
                "s3_docx_output_path": upload_docx_to_s3(
                    docx_path,
                    f"{DAILY_DOCX_S3_PREFIX}{day}/",
                ),
                "s3_json_output_path": upload_json_to_s3(
                    json_path,
                    f"{DAILY_JSON_S3_PREFIX}{day}/",
                ),
            }
        )
    return uploads


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

            if node_name == "build_final_history_table_14":
                print("[1/4] 최종 이력 테이블 생성 완료", flush=True)
                print("[2/4] 데이터 수정 agent 실행 중", flush=True)
            elif node_name == "data_correction_agent":
                print("[2/4] 데이터 수정 agent 완료", flush=True)
                print("[3/4] 데이터 검토 agent 실행 중", flush=True)
            elif node_name == "data_correction_review_agent":
                print("[3/4] 데이터 검토 agent 완료", flush=True)
                print("[4/4] 위험성평가표 문서 생성 중", flush=True)
            elif node_name == "retry":
                print("검토 결과 수정 필요: 데이터 수정 agent 재실행", flush=True)
            elif node_name == "fill_csv_form":
                print("[4/4] 위험성평가표 문서 생성 완료", flush=True)

    return state


async def main():
    print(f"프로젝트 경로: {PROJECT_ROOT}", flush=True)

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY 환경변수를 확인합니다.", flush=True)

    request = RiskAssessmentFormRequest(
        correction_batch_size=CORRECTION_BATCH_SIZE,
        output_path=str(DEFAULT_DOCX_PATH),
    )

    try:
        result = await asyncio.wait_for(run_graph(request), timeout=TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(
            f"{TIMEOUT_SECONDS}초 동안 응답이 없어 실행을 중단했습니다. "
            "네트워크, OPENAI_API_KEY, 모델 설정을 확인하세요."
        ) from exc

    review_result = result["correction_review"]
    docx_output_path = result.get("docx_output_path")
    response = RiskAssessmentFormResponse(
        status="COMPLETED" if review_result.approved and docx_output_path else "FAILED",
        retry_count=result.get("retry_count", 0),
        correction_batch_size=result.get("correction_batch_size"),
        correction_batch_count=result.get("correction_batch_count"),
        final_history_rows=result.get("final_history_rows", []),
        correction_result=result["correction_result"],
        correction_review=review_result,
        docx_output_path=docx_output_path,
        s3_output_path=result.get("s3_output_path"),
    )

    DEFAULT_RESPONSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    response_payload = response.model_dump(mode="json")
    with DEFAULT_RESPONSE_PATH.open("w", encoding="utf-8-sig") as file:
        json.dump(response_payload, file, ensure_ascii=False, indent=2)
    daily_uploads = _write_daily_outputs(response, result.get("backend_data") or {})

    print(json.dumps({
        "status": response.status,
        "retry_count": response.retry_count,
        "correction_batch_size": response.correction_batch_size,
        "correction_batch_count": response.correction_batch_count,
        "rows": len(response.correction_result.corrected_rows),
        "corrections": len(response.correction_result.correction_notes),
        "review_approved": response.correction_review.approved,
        "review_score": response.correction_review.score,
        "docx_output_path": response.docx_output_path,
        "s3_output_path": response.s3_output_path,
        "daily_uploads": daily_uploads,
        "response_path": str(DEFAULT_RESPONSE_PATH),
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())



