import asyncio
import os
from typing import Any, Dict, Optional

from app.config import OUTPUT_DIR
from app.task_store import create_task, get_task, update_task
from app.utils.cloudinary_utils import upload_video_to_cloudinary

from app.ai.veo.constants import MAX_CLIP_SECONDS
from app.ai.veo.pipelines import _cleanup_temp_clips, generate_veo_video_from_storyboard
from app.ai.parser import parse_document_content
from app.ai.veo.prompt_builder import get_token_usage, reset_token_usage
from app.ai.education_video_pipeline import (
    analyze_document,
    extract_learning_objectives,
    create_storyboard,
    inspect_video_quality_async,
)


def calculate_veo_usage_and_cost(
    task_id: str,
    clip_count: int,
    total_seconds: int,
    llm_input_tokens: int,
    llm_output_tokens: int
) -> Dict[str, Any]:
    """영상 제작에 소모된 LLM 토큰 수, Veo 비디오 생성 초 수 및 추정 단가를 집계하여 출력한다."""
    # Gemini 2.5 Flash 단가 (Input $0.075 / 1M, Output $0.30 / 1M)
    llm_in_cost = (llm_input_tokens / 1_000_000) * 0.075
    llm_out_cost = (llm_output_tokens / 1_000_000) * 0.30
    llm_total_cost = llm_in_cost + llm_out_cost

    # Veo 3.1 Lite 단가 (초당 $0.06 USD 추정)
    veo_cost_per_sec = 0.06
    veo_total_cost = total_seconds * veo_cost_per_sec

    total_usd = llm_total_cost + veo_total_cost
    total_krw = total_usd * 1350  # 환율 1,350원 기준

    summary = {
        "llm_model": "gemini-2.5-flash",
        "llm_input_tokens": llm_input_tokens,
        "llm_output_tokens": llm_output_tokens,
        "llm_total_tokens": llm_input_tokens + llm_output_tokens,
        "llm_cost_usd": round(llm_total_cost, 6),
        "veo_model": "veo-3.1-lite-generate-001",
        "video_clips_count": clip_count,
        "total_video_seconds": total_seconds,
        "veo_cost_usd": round(veo_total_cost, 4),
        "total_cost_usd": round(total_usd, 4),
        "total_cost_krw": round(total_krw, 1)
    }

    print("\n" + "=" * 64)
    print("💰 [Veo AI 영상 제작 총 토큰 & API 비용 집계 리포트]")
    print(f"  - 태스크 ID: {task_id}")
    print(f"  - 🤖 LLM 토큰 사용량 (Gemini 2.5 Flash):")
    print(f"    • 입력 토큰 (Input Tokens)  : {llm_input_tokens:,} tokens")
    print(f"    • 출력 토큰 (Output Tokens) : {llm_output_tokens:,} tokens")
    print(f"    • 총 사용 토큰 (Total Tokens): {llm_input_tokens + llm_output_tokens:,} tokens")
    print(f"    • 추정 LLM 비용: ${llm_total_cost:.6f} USD (약 ₩{llm_total_cost * 1350:.2f} 원)")
    print(f"  - 🎬 Veo 비디오 생성 사용량 (Veo 3.1 Lite):")
    print(f"    • 생성 클립 개수: {clip_count}개 클립")
    print(f"    • 총 영상 재생 시간: {total_seconds}초")
    print(f"    • 추정 Veo API 비용: ${veo_total_cost:.4f} USD (약 ₩{veo_total_cost * 1350:,.0f} 원)")
    print("-" * 64)
    print(f"  💵 최종 추정 제작 비용: ${total_usd:.4f} USD (약 ₩{total_krw:,.0f} 원)")
    print("=" * 64 + "\n")

    return summary


def create_veo_task_record() -> str:
    """새로운 Veo 비동기 동영상 제작 태스크 생성 및 ID 반환"""
    return create_task(task_type="VEO")


def get_veo_task_status(task_id: str) -> Optional[Dict]:
    """Veo 태스크 처리 상태 및 결과 반환"""
    return get_task(task_id)


async def process_veo_summary_video_pipeline(
    task_id: str,
    file_path: str,
    company_id: int,
    title: Optional[str] = None,
    category: Optional[str] = "공통",
    type: Optional[str] = "필수",
    request: Optional[str] = None,
    target_duration_seconds: Optional[int] = None
):
    """
    [Veo 동영상 생성 파이프라인]
    1. parser 문서 원문 정밀 추출
    2. 장면별 Veo 8초 전용 비디오 모션 프롬프트 및 대본 생성
    3. Vertex AI Veo 8초 동영상 생성 ➔ FFmpeg 자동 병합
    4. 품질 검수 후 Cloudinary 업로드 및 작업 상태 기록

    DB 영속화(Education 테이블 적재)는 이 서비스가 하지 않는다.
    백엔드가 상태를 폴링해 결과를 저장한다.
    """
    try:
        record = get_task(task_id)
        if not record:
            return

        # 이미 시작된 적 있는 태스크(PENDING이 아닌 상태)가 다시 들어오면 중복 실행이므로 건너뛴다.
        # 그대로 두면 같은 요청이 두 번 과금된다.
        if record.get("status") != "PENDING":
            print(f"[VideoAgent] 이미 시작된 태스크가 재전달되어 실행을 건너뜁니다 (status={record.get('status')}, task_id={task_id})")
            return

        update_task(task_id, status="PROCESSING", progress_percent=15, company_id=company_id)
        reset_token_usage()

        # 파일명·public_id는 task_id를 쓴다. 제목 기반 이름은 동일 제목 재요청 시 서로 덮어쓰고,
        # 정규식으로 모든 문자가 걸러지면 빈 이름이 된다.
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        output_video_path = f"{OUTPUT_DIR}/{task_id}.mp4"

        update_task(task_id, progress_percent=30)

        # Structured education-video pipeline: parse -> analyze -> objectives -> storyboard -> render -> inspect.
        parsed_text, _ = await asyncio.to_thread(parse_document_content, file_path)
        update_task(task_id, progress_percent=25)
        analysis = await analyze_document(parsed_text)
        update_task(task_id, document_analysis=analysis, progress_percent=35)
        objectives = await extract_learning_objectives(analysis)
        update_task(task_id, learning_objectives=objectives, progress_percent=45)
        storyboard = await create_storyboard(
            parsed_text, analysis, objectives, request, target_duration_seconds
        )
        # Gemini 호출 실패로 고정 Fallback 대본이 쓰이면 문서 내용이 전혀 반영되지 않은 영상이 나온다.
        # 제목·카테고리는 사용자 입력 그대로라 결과만 보고는 구분할 수 없으므로 저장하지 않고 실패 처리한다.
        if any(s.get("is_fallback") for s in storyboard):
            raise RuntimeError(
                "문서 기반 대본 생성에 실패했습니다 (Gemini API 호출 실패 또는 호출 한도 초과). "
                "잠시 후 다시 시도해 주세요."
            )

        update_task(task_id, storyboard=storyboard, progress_percent=55)
        render_result = await generate_veo_video_from_storyboard(storyboard, output_video_path, task_id)
        quality_report = await inspect_video_quality_async(
            storyboard, render_result["video_clips"], output_video_path
        )
        update_task(task_id, quality_report=quality_report)

        # 품질 검수가 개별 클립 파일 존재 여부를 확인한 뒤에 임시 클립을 정리한다.
        _cleanup_temp_clips(render_result["clip_dir"])

        # 집계 및 비용 계산
        tokens = get_token_usage()
        total_sec = sum(s.get("duration_seconds", MAX_CLIP_SECONDS) for s in storyboard)
        usage_summary = calculate_veo_usage_and_cost(
            task_id, len(storyboard), total_sec, tokens["input_tokens"], tokens["output_tokens"]
        )
        update_task(task_id, usage_summary=usage_summary)

        update_task(task_id, progress_percent=80)

        # Cloudinary 클라우드 스토리지 동영상 업로드
        local_video_url = render_result.get("video_url", f"/{output_video_path}")
        cloudinary_url = await upload_video_to_cloudinary(output_video_path, folder="veo_safety_videos", public_id=task_id)
        video_url = cloudinary_url if cloudinary_url else local_video_url

        # 휴지통 비우기: 업로드 성공 시 로컬 비디오 파일 삭제
        if cloudinary_url and os.path.exists(output_video_path):
            try:
                os.remove(output_video_path)
            except OSError:
                pass

        update_task(
            task_id,
            status="COMPLETED",
            progress_percent=100,
            video_url=video_url,
            title=title,
            category=category,
            type=type,
        )
        print(f"[VideoAgent] SUCCESS: Veo 동영상 생성 완료 (task_id={task_id})")

    except Exception as e:
        print(f"[VideoAgent] Veo 파이프라인 실행 중 오류: {e}")
        update_task(task_id, status="FAILED", error_message=str(e))

    finally:
        # 성공·실패·조기 반환 어느 경로에서도 업로드 원본이 디스크에 남지 않도록 한다.
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
