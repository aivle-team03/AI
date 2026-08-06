import asyncio
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Optional

from tenacity import retry, retry_if_exception_type, wait_exponential, stop_after_attempt

from app.ai.veo.constants import MAX_CLIP_SECONDS, TEXT_TO_VIDEO_DURATIONS


def _get_vertex_access_token() -> tuple[Optional[str], Optional[str]]:
    """GCP Service Account 키(video_create.json 등)로 Vertex AI OAuth2 Bearer 토큰 생성"""
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests

        key_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or "video_create.json"
        project_id = os.getenv("GCP_PROJECT_ID")

        if os.path.exists(key_file):
            creds = service_account.Credentials.from_service_account_file(
                key_file,
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            req = google.auth.transport.requests.Request()
            creds.refresh(req)
            if not project_id and hasattr(creds, "project_id"):
                project_id = creds.project_id
            return creds.token, project_id
    except Exception as e:
        print(f"[VeoGenerator] OAuth2 Token Issue: {e}")

    return None, None


def _extract_video_from_veo_response(res_data) -> tuple[Optional[str], Optional[str]]:
    """
    Vertex AI Veo LRO 완료 응답에서 영상 데이터를 추출하는 범용 파서.
    모델/API 버전에 따라 스키마가 다를 수 있어 모두 지원:
      - {"predictions": [{"bytesBase64Encoded": ...}]}
      - {"videos": [{"bytesBase64Encoded": ...}]}
      - {"generatedVideos": [{"video": {"bytesBase64Encoded": ...}}]}
      - {"video": {"bytesBase64Encoded": ...}}
      - gcsUri/uri 형태의 GCS 저장 결과
    """
    if not isinstance(res_data, dict):
        return None, None

    candidate_lists = []
    for key in ("predictions", "videos", "generatedVideos", "generated_videos", "samples"):
        val = res_data.get(key)
        if isinstance(val, list) and val:
            candidate_lists.append(val)

    if isinstance(res_data.get("video"), dict):
        candidate_lists.append([res_data["video"]])

    for item_list in candidate_lists:
        for item in item_list:
            if not isinstance(item, dict):
                continue
            inner = item.get("video") if isinstance(item.get("video"), dict) else item
            b64 = inner.get("bytesBase64Encoded") or item.get("bytesBase64Encoded")
            if b64:
                return b64, None
            uri = inner.get("gcsUri") or inner.get("uri") or item.get("gcsUri") or item.get("uri")
            if uri:
                return None, uri

    b64 = res_data.get("bytesBase64Encoded")
    if b64:
        return b64, None
    uri = res_data.get("gcsUri") or res_data.get("uri")
    if uri:
        return None, uri

    return None, None


def _clamp_veo_duration(requested_seconds: int, supported: tuple = TEXT_TO_VIDEO_DURATIONS) -> int:
    """요청된 영상 길이를 Veo가 지원하는 값 중 가장 가까운 값으로 보정한다."""
    if requested_seconds in supported:
        return requested_seconds
    closest = min(supported, key=lambda d: (abs(d - requested_seconds), -d))
    print(f"[VeoGenerator] INFO: 요청된 영상 길이 {requested_seconds}초는 미지원 값이라 {closest}초로 자동 보정합니다. (지원 값: {supported})")
    return closest


def _sanitize_veo_prompt(raw_prompt: str) -> str:
    """Veo AI 모델에 전달하기 전 화면 텍스트 금지 지시를 보강하고 공백을 정돈한다.

    대사(saying: "...")는 Veo가 그대로 발화하므로 제거하지 않는다. 화면에 한글이 렌더링되는 문제는
    대사 삭제가 아니라 no on-screen text 계열 네거티브 지시로 막는다.
    """
    if not raw_prompt:
        return (
            "Cinematic medium shot of an industrial workplace, realistic lighting, "
            "photorealistic 8k video, 24fps, no on-screen text, no captions, "
            "no subtitles, no readable signage or labels of any kind"
        )

    clean_p = raw_prompt.strip()

    text_suffix = ", no on-screen text, no captions, no subtitles, no readable signage or labels of any kind"
    if "no on-screen text" not in clean_p.lower():
        clean_p = clean_p.rstrip(" .,") + text_suffix

    clean_p = re.sub(r'\s*,\s*', ', ', clean_p)
    clean_p = re.sub(r'\s+', ' ', clean_p).strip()
    return clean_p


class VeoRequestError(RuntimeError):
    """LRO 생성 이전 단계에서 발생한 실패. 재시도해도 중복 과금이 발생하지 않는다."""


class VeoJobError(RuntimeError):
    """LRO가 이미 생성된 뒤 발생한 실패. 재시도하면 과금 작업이 하나 더 생기므로 재시도하지 않는다."""


# 재시도는 VeoRequestError(=LRO 생성 전 실패)에만 적용한다.
# 예전에는 함수 전체를 감싸고 있어, 폴링이 실패하면 이미 과금된 작업을 두고 새 LRO를 또 만들었다.
# 최악의 경우 한 클립에 3회 과금되고 30분이 소요된다.
@retry(
    wait=wait_exponential(multiplier=2, min=4, max=20),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(VeoRequestError),
)
def generate_veo_video_clip_sync(
    prompt: str,
    output_path: str,
    duration_seconds: int = MAX_CLIP_SECONDS,
    aspect_ratio: str = "16:9",
    model_name: str = "veo-3.1-lite-generate-001"
) -> str:
    """Google Vertex AI Veo REST API 1회 단일 호출 함수"""
    access_token, project_id = _get_vertex_access_token()

    if not access_token or not project_id:
        print("[VeoGenerator] ERROR: GCP 인증 정보가 유효하지 않습니다.")
        raise VeoRequestError("GCP 인증 정보 누락으로 비디오 생성을 중단합니다.")

    target_model = os.getenv("VEO_MODEL_NAME", model_name)
    location = os.getenv("GCP_LOCATION", "us-central1")
    duration_seconds = _clamp_veo_duration(duration_seconds)
    sanitized_prompt = _sanitize_veo_prompt(prompt)

    url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{location}/publishers/google/models/{target_model}:predictLongRunning"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "instances": [{"prompt": sanitized_prompt}],
        "parameters": {
            "aspectRatio": aspect_ratio,
            "durationSeconds": duration_seconds,
            "sampleCount": 1,
            "generateAudio": True
        }
    }

    # 1) LRO 생성 요청. 이 단계의 실패는 과금 작업이 만들어지지 않았으므로 재시도해도 안전하다.
    try:
        print(f"[VeoGenerator] Vertex AI Veo API 1회 호출 발송... (Model: {target_model})")
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=120) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as he:
        try:
            err_body = he.read().decode("utf-8")
        except Exception:
            err_body = str(he)
        print(f"[VeoGenerator] Veo API ({target_model}) HTTP {he.code} 상세 오류 본문: {err_body}")
        raise VeoRequestError(f"Veo API HTTP {he.code}: {err_body[:200]}") from he
    except Exception as e:
        print(f"[VeoGenerator] Veo API ({target_model}) 호출 예외: {e}")
        raise VeoRequestError(f"Veo API 호출 중 예외 발생: {e}") from e

    # 2) 여기서부터는 과금 작업이 이미 생성된 상태다. 무슨 일이 있어도 재시도하지 않는다.
    if "name" in res_data:
        operation_name = res_data["name"]
        print(f"[VeoGenerator] LRO 비디오 생성 작업 등록 완료 ({operation_name})")
        res_data = _poll_lro_operation(operation_name, access_token, location)

    try:
        debug_keys = list(res_data.keys()) if isinstance(res_data, dict) else type(res_data)
        print(f"[VeoGenerator] DEBUG: LRO 최종 응답 최상위 키: {debug_keys}")
        print(f"[VeoGenerator] DEBUG: LRO 최종 응답 원문(앞 1500자): {json.dumps(res_data, ensure_ascii=False)[:1500]}")
    except Exception:
        pass

    if isinstance(res_data, dict) and res_data.get("error"):
        err = res_data["error"]
        err_msg = err.get("message") if isinstance(err, dict) else err
        print(f"[VeoGenerator] ERROR: Veo API가 LRO를 오류로 종료함 -> {err_msg}")
        raise VeoJobError(f"Veo LRO가 오류로 종료됨: {err_msg}")

    video_bytes_b64, gcs_uri = _extract_video_from_veo_response(res_data)
    if video_bytes_b64:
        video_bytes = base64.b64decode(video_bytes_b64)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(video_bytes)
        print(f"[VeoGenerator] SUCCESS: Veo 비디오 생성 완료 ({output_path})")
        return output_path
    if gcs_uri:
        print(f"[VeoGenerator] SUCCESS: GCS 비디오 URI 수신 ({gcs_uri})")
        return gcs_uri

    print("[VeoGenerator] WARNING: LRO는 완료됐지만 응답에서 영상 데이터를 찾지 못함.")
    raise VeoJobError("Veo LRO 작업이 완료되었으나 영상 데이터를 얻지 못했습니다.")


def _poll_lro_operation(operation_name: str, access_token: str, location: str, max_retries: int = 60) -> dict:
    """Vertex AI Veo LRO 작업 상태 전용 폴링 함수"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    model_path = re.sub(r"/operations/[^/]+$", "", operation_name)
    fetch_url = f"https://{location}-aiplatform.googleapis.com/v1/{model_path}:fetchPredictOperation"
    fetch_payload = json.dumps({"operationName": operation_name}).encode("utf-8")
    get_url = f"https://{location}-aiplatform.googleapis.com/v1/{operation_name}"

    for attempt in range(max_retries):
        time.sleep(10)
        
        try:
            req = urllib.request.Request(fetch_url, data=fetch_payload, headers=headers)
            with urllib.request.urlopen(req, timeout=35) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                if res.get("done"):
                    print(f"[VeoGenerator] SUCCESS: Veo LRO 비디오 생성 완료! (Attempt: {attempt + 1})")
                    if "predictions" in res:
                        return res
                    elif "response" in res and isinstance(res["response"], dict):
                        return res["response"]
                    elif "result" in res and isinstance(res["result"], dict):
                        return res["result"]
                    return res

                meta_state = res.get("metadata", {}).get("state", "RUNNING")
                print(f"[VeoGenerator] Veo 렌더링 진행 중... (상태: {meta_state}, {attempt + 1}/{max_retries})")
                continue
        except Exception:
            pass

        try:
            req = urllib.request.Request(get_url, headers=headers)
            with urllib.request.urlopen(req, timeout=35) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                if res.get("done"):
                    print(f"[VeoGenerator] SUCCESS: Veo LRO 비디오 생성 완료! (Attempt: {attempt + 1})")
                    if "predictions" in res:
                        return res
                    elif "response" in res and isinstance(res["response"], dict):
                        return res["response"]
                    elif "result" in res and isinstance(res["result"], dict):
                        return res["result"]
                    return res

                meta_state = res.get("metadata", {}).get("state", "RUNNING")
                print(f"[VeoGenerator] Veo 렌더링 진행 중... (상태: {meta_state}, {attempt + 1}/{max_retries})")
        except Exception:
            pass

    return {}


async def generate_veo_video_clip(
    prompt: str,
    output_path: str,
    duration_seconds: int = MAX_CLIP_SECONDS,
    aspect_ratio: str = "16:9"
) -> str:
    """Veo 비디오 생성을 위한 비동기 Wrapper 함수"""
    return await asyncio.to_thread(
        generate_veo_video_clip_sync,
        prompt,
        output_path,
        duration_seconds,
        aspect_ratio
    )
