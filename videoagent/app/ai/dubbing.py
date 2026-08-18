"""한국어 Veo 영상을 다른 언어로 더빙하기 위한 번역 에이전트.

Veo 로 언어판을 따로 생성하면 클립당 비용이 그대로 두 배가 된다. 영상은 한국어 하나만
만들고, 대본을 번역해 TTS 로 오디오만 갈아끼우면 추가 비용이 사실상 없다.

번역에서 가장 중요한 제약은 **길이**다. 클립은 4/6/8초로 이미 고정돼 있어서, 번역문이
길면 잘리고 짧으면 빈 구간이 생긴다. 그래서 장면마다 목표 글자 수를 정해 지시한다.
"""
import asyncio
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

from app.ai.education_video_pipeline import _SCRIPT_LENGTH_TO_CLIP_SECONDS
from app.ai.veo.prompt_builder import generate_json_response
from app.ai.veo.video_editor import _concat_video_clips_ffmpeg, _get_ffmpeg_executable


# 최대 클립(8초)에 담을 글자 수. _SCRIPT_LENGTH_TO_CLIP_SECONDS 는 4초·6초 경계만
# 담고 그 위는 전부 8초로 넘기므로, 8초 상한만 여기서 정한다.
_MAX_DUB_CHARS = {"en": 100}

_LANGUAGE_NAMES = {"en": "영어"}

# 번역 지침. 보는 사람이 원어민이 아니라 외국인 노동자라 쉬운 표현을 강제한다.
_TRANSLATION_GUIDES = {
    "en": """- 이 영상을 볼 사람은 **영어가 모국어가 아닌 외국인 노동자**입니다. 원어민용 표현이 아니라 쉬운 영어로 쓰세요.
- **전문용어와 복합명사를 피하고, 중학교 수준의 쉬운 단어로 풀어 쓰세요.**
  예: 'rear-view mirror' -> 'the mirror behind you' / 'braking system' -> 'the brakes'
- 명령문(imperative)으로 쓰세요. 'You should pull the pin' 이 아니라 'First, pull the safety pin' 처럼 씁니다.
- 축약형(don't, it's)보다 풀어 쓴 형태(do not, it is)가 TTS 발음이 또렷합니다.
- 원문의 순서 접속어('먼저', '다음은', '이어서')는 영어에서도 살리세요(First, Next, Then).""",
}


def _target_chars(duration_seconds: int, language: str) -> int:
    """클립 길이에 맞는 번역문 목표 글자 수.

    `_SCRIPT_LENGTH_TO_CLIP_SECONDS` 를 뒤집어 쓴다. 그 표가 '몇 자까지 몇 초'를 정하므로
    같은 숫자를 여기 다시 적으면 한쪽만 고쳤을 때 조용히 어긋난다.
    """
    thresholds = _SCRIPT_LENGTH_TO_CLIP_SECONDS.get(language)
    if thresholds:
        for max_chars, secs in thresholds:
            if secs == duration_seconds:
                return max_chars
    return _MAX_DUB_CHARS.get(language, 100)


def _build_instruction(scenes: List[Dict[str, Any]], language: str) -> str:
    lines = []
    for scene in scenes:
        no = scene.get("scene")
        script = (scene.get("script") or "").strip()
        limit = _target_chars(scene.get("duration_seconds", 8), language)
        lines.append(f'  {{"scene": {no}, "script_ko": "{script}", "max_chars": {limit}}}')
    scene_block = ",\n".join(lines)

    return f"""당신은 산업안전 교육 영상의 전문 번역가입니다.
아래 한국어 대본을 {_LANGUAGE_NAMES.get(language, language)}로 번역하세요.

[길이 제약 (가장 중요)]
- 각 장면에는 `max_chars` 가 있습니다. 번역문은 **공백 포함 그 글자 수를 넘기면 안 됩니다.**
- 영상 클립 길이가 이미 고정돼 있어서, 넘치면 대사가 잘리고 모자라면 빈 구간이 생깁니다.
- 의미를 다 담지 못하면 **문장을 줄이지 말고 더 쉬운 짧은 표현으로 바꾸세요.**
- max_chars 의 70% 이상은 채우세요. 너무 짧으면 클립 뒤가 빕니다.

[번역 지침]
{_TRANSLATION_GUIDES.get(language, "")}

[입력]
[
{scene_block}
]

[출력 형식]
아래 JSON 만 출력하세요. 설명·코드블록 표시를 붙이지 마세요.
{{"scenes": [{{"scene": 1, "script": "번역문"}}]}}
"""


async def translate_scripts(
    storyboard: List[Dict[str, Any]], language: str = "en"
) -> Optional[List[str]]:
    """스토리보드 대본을 번역해 장면 순서대로 돌려준다.

    한 번의 호출로 전체 장면을 함께 번역한다. 장면별로 나눠 부르면 앞뒤 문맥이 끊겨
    순서 접속어('먼저', '다음은')가 어긋나고 호출 수만 늘어난다.

    실패하면 None 을 돌려준다. 호출부는 더빙을 건너뛰고 한국어판만 저장해야 한다.
    """
    if not storyboard:
        return None

    parsed = await generate_json_response(_build_instruction(storyboard, language))
    if not isinstance(parsed, dict):
        print(f"[Dubbing] 번역 응답을 파싱하지 못했습니다 (language={language})")
        return None

    by_scene = {}
    for item in parsed.get("scenes") or []:
        if isinstance(item, dict) and item.get("script"):
            by_scene[item.get("scene")] = str(item["script"]).strip()

    translated = []
    for index, scene in enumerate(storyboard):
        text = by_scene.get(scene.get("scene")) or by_scene.get(index + 1)
        if not text:
            print(f"[Dubbing] 장면 {scene.get('scene')} 번역문이 없어 더빙을 중단합니다.")
            return None
        translated.append(text)

    _log_length_report(storyboard, translated, language)
    return translated


def _log_length_report(
    storyboard: List[Dict[str, Any]], translated: List[str], language: str
) -> None:
    """목표 글자 수를 넘긴 장면을 남긴다. TTS 단계에서 속도로 보정할 대상이다."""
    over = []
    for scene, text in zip(storyboard, translated):
        limit = _target_chars(scene.get("duration_seconds", 8), language)
        if len(text) > limit:
            over.append((scene.get("scene"), len(text), limit))

    if over:
        detail = ", ".join(f"장면{no} {length}/{limit}자" for no, length, limit in over)
        print(f"[Dubbing] 목표 길이를 넘긴 장면이 있습니다 (TTS 속도로 보정): {detail}")
    else:
        print(f"[Dubbing] 전체 장면이 목표 길이 안에 번역되었습니다 ({len(translated)}개)")


# ── TTS ──────────────────────────────────────────────────────────────

# Veo 프롬프트가 남성 안전관리자/내레이터를 지정하므로 목소리도 남성으로 맞춘다.
_TTS_VOICES = {"en": ("en-US", "en-US-Neural2-D")}

# 클립 앞 0.5초는 도입 침묵으로 비워 둔다. Veo 대본 규칙과 같은 기준이라
# 장면이 이어질 때 말이 앞 장면에 붙어 들리지 않는다.
_LEAD_IN_SECONDS = 0.5

# 말을 빠르게 해서 맞출 수 있는 한계. 이보다 올리면 알아듣기 어려워진다.
_MAX_SPEAKING_RATE = 1.25


def _audio_duration_seconds(path: str) -> Optional[float]:
    """ffmpeg 로 오디오 길이를 잰다. imageio-ffmpeg 에 ffprobe 는 없어서 stderr 를 읽는다."""
    try:
        # -nostdin 과 stdin 차단이 둘 다 필요하다. ffmpeg 는 기본적으로 stdin 을 대화형으로
        # 읽어서, 워커처럼 stdin 이 닫히지 않는 환경에서는 출력 파일 없이 -i 만 줘도 대기한다.
        result = subprocess.run(
            [_get_ffmpeg_executable(), "-nostdin", "-i", path],
            capture_output=True, text=True, errors="ignore",
            stdin=subprocess.DEVNULL, timeout=15,
        )
    except Exception:
        return None

    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", result.stderr or "")
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _tts_client():
    """Veo 와 같은 서비스 계정 키로 TTS 클라이언트를 만든다.

    기본 ADC 를 쓰면 이 서버에서는 자격 증명을 찾지 못한다(Veo 는 키 파일을 직접 지정해
    동작 중이다). veo/client.py 와 같은 경로 규칙을 따라 인증을 일치시킨다.

    transport 는 REST 로 고정한다. 기본값인 gRPC 는 Celery prefork 워커에서 fork 이후
    데드락에 빠져 예외도 로그도 없이 멈추는 사례가 있다. 호출량이 영상당 몇 회뿐이라
    gRPC 의 성능 이점보다 fork 안전성이 중요하다.
    """
    from google.cloud import texttospeech
    from google.oauth2 import service_account

    key_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or "video_create.json"
    if not os.path.exists(key_file):
        raise FileNotFoundError(f"서비스 계정 키를 찾을 수 없습니다: {key_file}")

    credentials = service_account.Credentials.from_service_account_file(
        key_file, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    return texttospeech.TextToSpeechClient(credentials=credentials, transport="rest")


def _synthesize_sync(text: str, language: str, speaking_rate: float, out_path: str) -> bool:
    try:
        from google.cloud import texttospeech
    except ImportError:
        print("[Dubbing] google-cloud-texttospeech 가 설치되지 않아 더빙을 건너뜁니다.")
        return False

    language_code, voice_name = _TTS_VOICES.get(language, _TTS_VOICES["en"])
    try:
        client = _tts_client()
        response = client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=text),
            voice=texttospeech.VoiceSelectionParams(
                language_code=language_code, name=voice_name
            ),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=speaking_rate,
            ),
            # 값이 없으면 무한정 기다린다. 더빙은 부가 기능이라 막히면 포기하는 편이 낫다.
            timeout=30,
        )
    except Exception as error:
        print(f"[Dubbing] TTS 합성 실패: {error}")
        return False

    with open(out_path, "wb") as audio_file:
        audio_file.write(response.audio_content)
    return True


async def synthesize_scene_audio(
    text: str, language: str, clip_seconds: int, out_path: str
) -> bool:
    """장면 대사를 TTS 로 만들고, 클립 안에 들어가도록 속도를 한 번 보정한다.

    짧은 것은 그냥 둔다. 뒤가 조용해질 뿐이고 mux 단계에서 무음으로 채운다.
    Veo 네이티브 오디오와 달리 TTS 는 빈 구간을 옹알이로 채우지 않는다.
    긴 것만 문제라서 그때만 다시 합성한다.
    """
    if not await asyncio.to_thread(_synthesize_sync, text, language, 1.0, out_path):
        return False

    available = clip_seconds - _LEAD_IN_SECONDS
    duration = await asyncio.to_thread(_audio_duration_seconds, out_path)
    if not duration or duration <= available:
        return True

    rate = min(duration / available, _MAX_SPEAKING_RATE)
    print(
        f"[Dubbing] 대사가 {duration:.1f}초로 {available:.1f}초를 넘어 "
        f"속도를 {rate:.2f}배로 다시 합성합니다."
    )
    return await asyncio.to_thread(_synthesize_sync, text, language, rate, out_path)


# ── 오디오 교체 ───────────────────────────────────────────────────────

def _replace_audio_sync(clip_path: str, audio_path: str, out_path: str) -> bool:
    """클립의 Veo 오디오를 TTS 로 갈아끼운다.

    apad 로 오디오 뒤를 무음 연장한다. 이게 없으면 TTS 가 짧을 때 영상까지 같이 잘려
    장면이 사라진다. 대신 apad 는 인자가 없으면 **무한히** 패딩하므로 반드시 끊어야 한다.

    끊는 수단은 -t 다. -shortest 는 filter_complex 출력에는 걸리지 않아서, apad 가
    만드는 무한 스트림을 멈추지 못하고 ffmpeg 이 CPU 를 태우며 영영 돌아간다.
    """
    duration = _audio_duration_seconds(clip_path)

    command = [
        _get_ffmpeg_executable(), "-y", "-nostdin",
        "-i", clip_path,
        "-i", audio_path,
        "-filter_complex", f"[1:a]adelay={int(_LEAD_IN_SECONDS * 1000)}:all=1,apad[a]",
        "-map", "0:v:0", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac",
    ]
    if duration:
        # 원본 영상 길이에 정확히 맞춘다. 더빙판과 한국어판의 길이가 같아야
        # 시청 진도(last_position_seconds)가 두 언어에서 같은 장면을 가리킨다.
        command += ["-t", f"{duration:.3f}"]
    else:
        # 길이를 못 쟀을 때의 차선책. 무한 패딩만은 막는다.
        command += ["-shortest"]
    command.append(out_path)
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, errors="ignore",
            stdin=subprocess.DEVNULL, timeout=120,
        )
    except Exception as error:
        print(f"[Dubbing] 오디오 교체 실행 실패: {error}")
        return False

    if result.returncode != 0:
        print(f"[Dubbing] 오디오 교체 실패: {(result.stderr or '')[-400:]}")
        return False
    return os.path.exists(out_path) and os.path.getsize(out_path) > 0


async def replace_clip_audio(clip_path: str, audio_path: str, out_path: str) -> bool:
    return await asyncio.to_thread(_replace_audio_sync, clip_path, audio_path, out_path)


# ── 전체 흐름 ─────────────────────────────────────────────────────────

async def build_dubbed_video(
    storyboard: List[Dict[str, Any]],
    clip_paths: List[str],
    output_path: str,
    language: str = "en",
) -> Optional[str]:
    """한국어 클립을 그대로 쓰고 오디오만 번역·합성해 더빙판을 만든다.

    실패하면 None 을 돌려준다. 더빙은 부가 기능이라 여기서 실패해도 한국어판 저장까지
    같이 실패시키면 안 된다. 호출부는 None 을 받으면 조용히 건너뛴다.
    """
    if not storyboard or not clip_paths:
        return None

    usable = min(len(storyboard), len(clip_paths))
    if usable < len(storyboard):
        print(f"[Dubbing] 클립 수가 장면 수보다 적습니다 ({len(clip_paths)}/{len(storyboard)}). 더빙을 건너뜁니다.")
        return None

    translated = await translate_scripts(storyboard, language)
    if not translated:
        return None

    work_dir = os.path.join(os.path.dirname(os.path.abspath(clip_paths[0])), f"dub_{language}")
    os.makedirs(work_dir, exist_ok=True)

    dubbed_clips = []
    for index, (scene, clip_path, text) in enumerate(zip(storyboard, clip_paths, translated)):
        if not clip_path or not os.path.exists(clip_path):
            print(f"[Dubbing] 장면 {index + 1} 클립이 없어 더빙을 중단합니다.")
            return None

        audio_path = os.path.join(work_dir, f"scene_{index + 1}.mp3")
        clip_seconds = scene.get("duration_seconds") or 8
        if not await synthesize_scene_audio(text, language, clip_seconds, audio_path):
            return None

        dubbed_path = os.path.join(work_dir, f"scene_{index + 1}.mp4")
        if not await replace_clip_audio(clip_path, audio_path, dubbed_path):
            return None
        dubbed_clips.append(dubbed_path)

    merged = await asyncio.to_thread(_concat_video_clips_ffmpeg, dubbed_clips, output_path)
    if not merged:
        print("[Dubbing] 더빙 클립 병합에 실패했습니다.")
        return None

    print(f"[Dubbing] {language} 더빙판 생성 완료 ({len(dubbed_clips)}개 장면)")
    return output_path
