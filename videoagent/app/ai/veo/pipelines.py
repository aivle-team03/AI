import asyncio
import os
import shutil
from typing import Dict, List

from app.config import OUTPUT_DIR
from app.ai.veo.client import generate_veo_video_clip
from app.ai.veo.constants import MAX_CLIP_SECONDS
from app.ai.veo.video_editor import _concat_video_clips_ffmpeg

VEO_MAX_CLIP_SECONDS = MAX_CLIP_SECONDS

# Veo 클립은 서로 의존하지 않으므로 병렬 생성한다. Vertex AI 동시 요청 할당량을 넘기지 않도록 제한한다.
MAX_CONCURRENT_CLIPS = 4


def _cleanup_temp_clips(clip_dir: str):
    """렌더링 및 품질 검수 완료 후 태스크 전용 임시 클립 디렉터리 자동 삭제 및 디스크 용량 정돈"""
    if not clip_dir or "veo_clips" not in clip_dir.replace("\\", "/"):
        return
    try:
        shutil.rmtree(clip_dir, ignore_errors=True)
        print(f"[VeoClipsCleanup] SUCCESS: 임시 veo_clips 렌더링 클립 디렉터리 삭제 완료! ({clip_dir})")
    except Exception as e:
        print(f"[VeoClipsCleanup] 임시 클립 디렉터리 삭제 중 예외 ({clip_dir}): {e}")


async def generate_veo_video_from_storyboard(
    storyboard: List[Dict], output_video_path: str, task_id: str
) -> Dict:
    """Render a pre-approved storyboard and merge its scene clips into one MP4."""
    # 동시 실행되는 다른 태스크와 클립 파일이 충돌하지 않도록 task_id 전용 디렉터리에 렌더링한다.
    clip_dir = f"{OUTPUT_DIR}/veo_clips/{task_id}"
    os.makedirs(clip_dir, exist_ok=True)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CLIPS)

    async def render_scene(index: int, scene: Dict) -> str:
        # 파일명은 스토리보드 배열 위치에서 뽑는다. scene 필드는 LLM 출력이라 중복되거나 배열 순서와
        # 어긋날 수 있는데, 병합 순서는 배열 위치를 따르므로 근거를 하나로 통일해야 한다.
        clip_path = f"{clip_dir}/scene_{index + 1}.mp4"
        # 클립 길이는 대사 길이에 맞춰 스토리보드 단계에서 정해진다 (4/6/8초).
        duration = scene.get("duration_seconds", VEO_MAX_CLIP_SECONDS)
        async with semaphore:
            # 대사는 veo_prompt에 포함되어 Veo가 직접 발화하므로 별도 TTS 합성을 하지 않는다.
            return await generate_veo_video_clip(
                scene.get("veo_prompt", ""), clip_path, duration_seconds=duration
            )

    print(f"[VeoRender] {len(storyboard)}개 장면을 최대 {MAX_CONCURRENT_CLIPS}개씩 병렬 생성 시작...")
    # gather는 입력 순서대로 결과를 반환하므로 병합 시 장면 순서가 유지된다.
    video_clips = list(await asyncio.gather(*[
        render_scene(i, sc) for i, sc in enumerate(storyboard)
    ]))

    os.makedirs(os.path.dirname(os.path.abspath(output_video_path)), exist_ok=True)
    merged_ok = await asyncio.to_thread(_concat_video_clips_ffmpeg, video_clips, output_video_path)
    if not merged_ok and video_clips and os.path.exists(video_clips[0]):
        shutil.copy(video_clips[0], output_video_path)

    # 임시 클립은 품질 검수가 파일 존재 여부를 확인한 뒤에 삭제해야 하므로 호출부에서 정리한다.
    return {
        "video_url": "/" + output_video_path.replace("\\", "/"),
        "video_clips": video_clips,
        "clip_dir": clip_dir,
        "merged": merged_ok,
    }
