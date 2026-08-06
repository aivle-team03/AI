import asyncio
import json
import os
import re
import urllib.request
from typing import Any, Dict, List, Optional

from app.ai.veo.client import _get_vertex_access_token


def _clean_and_parse_json_for_veo(raw_text: str, context: str = ""):
    """Veo 전용 JSON 안전 파서 (script_generator 독립, 이중 따옴표 자동 복구 포함)"""
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if match:
            candidate = match.group(0)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                # 문자열 안에 그대로 들어온 개행 복구
                repaired = candidate.replace('\n', '\\n').replace('\r', '\\r')
                try:
                    return json.loads(repaired)
                except Exception as e:
                    # 어느 호출에서 무엇을 받았는지 남긴다. 이 정보가 없으면 실패 지점을 추적할 수 없다.
                    where = f"[{context}] " if context else ""
                    print(f"[VeoGenerator] {where}JSON 파싱 실패: {e}")
                    print(f"[VeoGenerator] {where}응답 원문(앞 300자): {text[:300]!r}")
    return None


# 파이프라인별 LLM 토큰 집계용 글로벌 저장소
_ACCUMULATED_TOKEN_USAGE = {"input_tokens": 0, "output_tokens": 0}


def reset_token_usage():
    """토큰 집계 카운터 초기화"""
    _ACCUMULATED_TOKEN_USAGE["input_tokens"] = 0
    _ACCUMULATED_TOKEN_USAGE["output_tokens"] = 0


def get_token_usage() -> Dict[str, int]:
    """현재까지 누적된 LLM 토큰 사용량 리턴"""
    return dict(_ACCUMULATED_TOKEN_USAGE)


def _call_gemini_for_veo_sync(api_key: str, payload: dict, models: List[str]) -> Optional[str]:
    """[Track 2 전용] Veo 프롬프트 생성을 위한 독립 Gemini REST API 연동 함수"""
    access_token, project_id = _get_vertex_access_token()

    # JSON 강제 출력 옵션 주입
    if "generationConfig" not in payload:
        payload["generationConfig"] = {}
    payload["generationConfig"]["responseMimeType"] = "application/json"

    if access_token and project_id:
        location = os.getenv("GCP_LOCATION", "us-central1")
        # Vertex에 실제로 존재하는 모델만 나열한다. 존재하지 않는 이름은 404로 즉시 실패해 폴백이
        # 무력해지고, 그러면 호출 한도에 자주 걸리는 AI Studio로 곧장 넘어가 Fallback 대본을 쓰게 된다.
        # (2026-08-04 실측: 2.0-flash / 1.5-flash / flash-latest 는 이 프로젝트에서 모두 404)
        vertex_models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]
        for v_model in vertex_models:
            url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{location}/publishers/google/models/{v_model}:generateContent"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=40) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    text_out = res_data["candidates"][0]["content"]["parts"][0]["text"]
                    
                    # 토큰 메타데이터 집계
                    meta = res_data.get("usageMetadata", {})
                    in_tok = meta.get("promptTokenCount", 0)
                    out_tok = meta.get("candidatesTokenCount", 0)
                    _ACCUMULATED_TOKEN_USAGE["input_tokens"] += in_tok
                    _ACCUMULATED_TOKEN_USAGE["output_tokens"] += out_tok
                    
                    print(f"[VeoGenerator] SUCCESS: Vertex AI Gemini 프롬프트 생성 완료 ({v_model}, Input: {in_tok}t, Output: {out_tok}t)")
                    return text_out
            except Exception as ve:
                print(f"[VeoGenerator] Vertex AI {v_model} 시도 실패: {ve}")

    if api_key:
        for model_name in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            headers = {"Content-Type": "application/json"}
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=40) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    text_out = res_data["candidates"][0]["content"]["parts"][0]["text"]

                    # 토큰 메타데이터 집계
                    meta = res_data.get("usageMetadata", {})
                    in_tok = meta.get("promptTokenCount", 0)
                    out_tok = meta.get("candidatesTokenCount", 0)
                    _ACCUMULATED_TOKEN_USAGE["input_tokens"] += in_tok
                    _ACCUMULATED_TOKEN_USAGE["output_tokens"] += out_tok

                    print(f"[VeoGenerator] SUCCESS: AI Studio Gemini 프롬프트 생성 완료 ({model_name}, Input: {in_tok}t, Output: {out_tok}t)")
                    return text_out
            except Exception as e:
                print(f"[VeoGenerator] Gemini REST API {model_name} 대체: {e}")
    return None


async def generate_veo_prompts_from_parsed_text(
    parsed_text: str,
    request: Optional[str] = None,
    file_path: Optional[str] = None,
    target_scenes: Optional[int] = None
) -> List[Dict]:
    """
    [Track 2 - Scene 분할 모드] parser.py에서 추출된 원문 텍스트(parsed_text)를 직접 입력받아,
    Google Veo 전용 카메라 무빙/인물 모션 프롬프트(veo_prompt) 및 장면 대본(script)을 직접 일괄 생성하는 함수
    """
    from app.ai.parser import parse_document_content

    gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]

    extracted_text = parsed_text or ""
    visual_parts = []

    if file_path and os.path.exists(file_path):
        p_text, p_visual_parts = await asyncio.to_thread(parse_document_content, file_path)
        if p_text:
            extracted_text = p_text
        visual_parts = p_visual_parts

    if target_scenes is None:
        char_count = len(extracted_text.strip())
        if char_count < 300:
            target_scenes = 3   # 24초 (단문/요약 문서)
        elif char_count < 600:
            target_scenes = 4   # 32초 (일반 1페이지)
        elif char_count < 900:
            target_scenes = 5   # 40초
        elif char_count < 1200:
            target_scenes = 6   # 48초
        elif char_count < 1500:
            target_scenes = 8   # 64초
        else:
            target_scenes = 10  # 80초 (대용량 매뉴얼/표준 작업 지침서)
    else:
        target_scenes = max(1, target_scenes)

    user_prompt = f"""
당신은 베테랑 영상 시나리오 작가이자 안전 교육 총괄 디렉터입니다.
전달받은 파싱 원문 텍스트를 정밀 분석하여, 전체 영상을 **처음부터 끝까지 하나의 완벽하게 연결된 강연 스토리(시나리오)**로 기획하고 총 {target_scenes}개의 장면(Veo 모션 프롬프트 및 대본)으로 구성하세요.

[대사 길이 규칙 (핵심)]
- 각 장면의 script는 **공백 포함 12~34자**로 쓰되, **가능한 한 짧게** 쓰세요. 34자는 절대 넘기지 마세요.
- 한 장면에 한 가지만 말하세요. 두 가지를 한 문장에 담지 말고 장면을 나누세요.
  예: "안전핀을 뽑고 손잡이를 눌러 불에 뿌리세요"(X, 두 동작) -> "먼저 안전핀을 뽑으세요"(O) + "손잡이를 눌러 뿌리세요"(O)
- 12~20자로 충분히 전달되는 내용을 굳이 늘리지 마세요. 짧은 문장이 발음도 정확하고 전달력도 좋습니다.
  전체 장면 중 **최소 절반은 24자 이하**가 되도록 구성하세요.
- 영상 클립 길이는 시스템이 대사 길이에 맞춰 4초·6초·8초 중에서 자동으로 고릅니다.
  따라서 짧은 대사를 억지로 늘릴 필요가 없습니다. 남는 시간이 생기지 않도록 시스템이 클립을 짧게 잡습니다.
  (기준: 16자 이하 4초 / 24자 이하 6초 / 그 외 8초. 도입부 0.5초를 뺀 뒤 초당 약 4자 기준의 실측값입니다.)
- 모든 veo_prompt 안에는 그 장면의 script 원문을 그대로 큰따옴표로 넣으세요. 형식: saying exactly and only this one line: "실제 대사"
- veo_prompt에는 "he says nothing else and does not improvise any additional words"를 반드시 포함해, Veo가 대사 외의 말을 지어내지 않게 하세요.
- veo_prompt에는 "begins after a very short half-second pause, then speaks slowly and deliberately, delivering the line clearly from the very first syllable and pacing it so the speech continues all the way to the end of the eight-second clip, never rushing or finishing early"를 반드시 포함하세요.
  클립 첫 프레임부터 곧바로 말하게 하면 첫 음절이 잘린 채 시작되어 장면 전환 지점에서 소리가 끊겨 들립니다.
  반대로 끝까지 채우라는 지시가 없으면 Veo가 대사를 급하게 읽어치우고 뒤를 비워 둡니다. 이때 발음도 같이 뭉개집니다. (실측: 초당 7자로 읽은 클립이 유사도 0.857)
  도입부 침묵은 앞 장면 끝의 침묵과 이어져 체감이 두 배가 되므로 0.5초를 넘기지 않게 하고, 끝부분 여유는 1초 이내로 유지하세요.
  veo_prompt에는 일단 "eight-second"로 쓰세요. 시스템이 대사 길이에 맞춰 four/six/eight 중 실제 값으로 자동 치환합니다.

[한국어 발음 오독 방지 지침 (필수)]
- Veo는 한자어 복합명사와 전문용어를 특히 심하게 오독합니다. 실측 사례: '구내속도' -> '군내 속도', '후사경' -> '후사견', '계획 수립' -> '개운 수리'.
- **한자어 복합명사와 전문용어를 쓰지 말고, 초등학생도 알아듣는 쉬운 구어체로 풀어 쓰세요.**
  예: '후사경' -> '뒷거울' / '구내속도' -> '작업장 안 속도' / '제동장치' -> '브레이크' / '적재 용량 준수' -> '짐을 너무 많이 싣지 마세요' / '주지시키고' -> '알려 주고'
- 한 문장을 통째로 쓰지 말고, 쉼표로 2~3개의 짧은 절로 끊어 쓰세요. 끊어 읽을 지점이 있어야 또박또박 발화됩니다.
- 띄어쓰기를 표준에 맞춰 명확히 구분하세요.

[내용 연결성 및 스토리텔링 지침]
1. 단편 수칙 개별 나열 금지: 파싱 문서 항목들을 단순 분할하여 따로 놀게 하지 마세요.
2. **대사는 "따라 할 수 있는 동작 지시"로 쓰세요.** 개념 설명이나 당위("중요합니다", "필수입니다")가 아니라
   무엇을 어떻게 하라는 구체적 행동이어야 합니다. 그래야 화면에 보여줄 동작이 생깁니다.
   나쁜 예: "소화기는 정말 중요합니다" / 좋은 예: "먼저 안전핀을 힘껏 잡아당겨 뽑으세요"
3. 짧은 접속어 문맥 연결: 각 장면 대사(script) 시작 부분에 짧은 연결어('먼저, ...', '다음은, ...', '이어서, ...', '그다음, ...', '끝으로, ...')를 사용하여 순서가 드러나게 하세요.
4. 손과 배경의 일관성: 모든 동작 장면은 동일한 작업 장갑과 동일한 작업 환경에서 촬영된 것처럼 묘사하세요.
5. 명확한 발화 지침 (한국어 강제 튜닝): 구글 Veo가 외국어나 외계어를 발음하지 않도록 모든 veo_prompt 내에 "speaks fluent Korean with authentic native pronunciation, perfectly clear Korean speech articulation, distinct Korean phonemes" 지침을 반드시 포함하세요. 인물이 나오는 장면에는 "natural Korean lip-sync"도 추가하세요.
6. 화면 텍스트 금지: 모든 veo_prompt 끝에 "no on-screen text, no captions, no subtitles, no readable signage or labels of any kind"를 반드시 포함하세요.

[동작 시연 중심 구성 (가장 중요)]
이 영상의 목적은 **말로 설명하는 것이 아니라 행동을 보여주는 것**입니다.
문서 주제가 무엇이든(소화기, 지게차, 보호구, 사다리, 기계 조작, 화학물질 취급 등) 그 **대상 물체와 손동작이
화면에 실제로 보여야** 학습자가 따라 할 수 있습니다. 말하는 얼굴만 나오는 영상은 실패입니다.

1. 각 장면의 veo_prompt는 그 장면 script가 지시하는 **동작을 실제로 수행하는 장면**을 묘사하세요.
   대상 물체가 화면의 큰 부분을 차지하고 손의 움직임이 명확히 보여야 합니다.
   예: script "안전핀을 뽑으세요"     -> 장갑 낀 손가락이 안전핀 고리에 걸려 곧게 당겨 뽑는 클로즈업
       script "레버를 아래로 내리세요" -> 손이 레버를 잡고 아래로 끝까지 내리는 클로즈업
       script "안전벨트를 매세요"      -> 버클을 잠금쇠에 밀어 넣어 딸깍 채우는 클로즈업

2. **정지된 포즈와 "~하는 척" 금지.** 물건을 들고만 있는 장면, 그리고 실제로는 일어나지 않는 가상의
   상황을 흉내 내는 묘사는 시연이 아닙니다. 아래 표현을 veo_prompt에 절대 쓰지 마세요.
   금지: as if, imagined, simulating, pretending, mock, "demonstrating the action"
   나쁜 예: "aiming at the base of an imagined fire" -> 불이 화면에 나오지 않습니다
   좋은 예: "aiming the nozzle at real orange flames burning in a metal training tray"

3. **동작의 대상과 결과가 프레임 안에 함께 보여야 합니다.** 손동작만 있고 그 동작이 향하는 대상이나
   결과가 없으면 무엇을 하는 장면인지 알 수 없습니다. 배경을 무조건 흐리게 하지 말고, 대상과 결과가
   보이도록 프레이밍하세요.
   "불을 향해 분사"  -> 손 + 소화기 + 실제 타오르는 불꽃 + 뿜어져 나오는 흰 분말 + 불이 잦아드는 변화
   "볼트를 조인다"   -> 손 + 렌치 + 실제 볼트와 조여지는 결합부
   "포크를 들어 올린다" -> 손 + 레버 + 실제로 올라가는 포크와 그 위의 화물

4. 동작 장면에는 **사람의 얼굴과 머리가 보이지 않게** 하세요. 손과 팔, 대상 물체, 동작의 결과가 함께
   담기면 됩니다. 형식:
   "Cinematic close-up of gloved hands ...(구체적 동작)..., ...(대상과 결과 묘사)..., no face and no person's head visible in the frame"
   음성은 "a male Korean narrator voice-over" 로 지정하세요. 화자가 화면에 없어도 한국어 음성이 정상 생성됩니다. (실측 확인)

5. 인물이 화면에 나오는 장면은 **첫 장면(인사)과 마지막 장면(마무리)만** 허용합니다. 이때 형식:
   "Cinematic medium close-up shot framing an Asian male safety manager from the chest up, plain unmarked navy work uniform with no logos or lettering, plain solid yellow hardhat with no markings, shallow depth of field with the background heavily blurred"

6. 문서에 등장하는 실제 장비·도구 이름을 영어로 구체적으로 묘사하세요. 두루뭉술한 "safety equipment"가 아니라
   "red fire extinguisher", "forklift control lever", "safety harness buckle" 처럼 특정해야 화면에 제대로 나옵니다.
   동작이 벌어지는 장소도 구체적으로 적으세요. 예: "outdoor fire safety training ground", "warehouse loading bay"

7. **장비를 어떻게 잡고 어떤 자세로 조작하는지 반드시 명시하세요.** 이것을 빼면 화면상 목표(예: 노즐이 불을
   향함)만 만족시키려고 장비를 잘못 잡거나 기울인 그림이 나옵니다. 잘못된 사용법을 가르치는 영상이 됩니다.
   - 부품 간 연결 관계를 적으세요. 예: 소화기는 손잡이에서 나온 **유연한 호스 끝에 노즐**이 달려 있습니다.
     "a flexible black hose extends from the extinguisher valve, one gloved hand holds the nozzle at the end
      of the hose and aims it, while the other hand keeps the red cylinder upright and vertical"
   - 유지해야 할 자세를 적으세요. 예: "the cylinder stays upright and vertical at all times"
   - 문서에 사용 자세·파지법·순서가 적혀 있으면 그대로 반영하세요.
   (실측 사례: 자세 지시를 빼자 Veo가 노즐을 손잡이에 직접 붙여 만들고 몸통을 기울여 겨누는,
    실제로는 분말이 나오지 않는 잘못된 사용법 영상을 생성했습니다.)

반드시 아래 JSON 배열 형식으로만 응답하세요.
첫 장면은 인물 등장(인사), 중간 장면들은 전부 손동작 클로즈업, 마지막 장면만 다시 인물 등장(마무리)입니다:
[
  {{"scene": 1, "script": "오늘은 소화기 쓰는 방법을 함께 익혀 보겠습니다.", "veo_prompt": "Cinematic medium close-up shot framing an Asian male safety manager from the chest up, plain unmarked navy work uniform with no logos or lettering, plain solid yellow hardhat with no markings, shallow depth of field with the background heavily blurred, the manager speaks fluent Korean with authentic native pronunciation, perfectly clear Korean speech articulation, distinct Korean phonemes, natural Korean lip-sync, saying exactly and only this one line: \\"오늘은 소화기 쓰는 방법을 함께 익혀 보겠습니다.\\", begins after a very short half-second pause, then speaks slowly and deliberately, delivering the line clearly from the very first syllable and pacing it so the speech continues all the way to the end of the eight-second clip, never rushing or finishing early, he says nothing else and does not improvise any additional words, no on-screen text, no captions, no subtitles, no readable signage or labels of any kind"}},
  {{"scene": 2, "script": "먼저 안전핀을 힘껏 잡아당겨 뽑으세요.", "veo_prompt": "Cinematic close-up of gloved hands gripping a red fire extinguisher at an outdoor fire safety training ground, one hand holds the body steady while the other hooks a finger through the metal safety pin and pulls it straight out of the handle in one deliberate motion, the loose pin clearly visible in the hand, no face and no person's head visible in the frame, a male Korean narrator voice-over speaks fluent Korean with authentic native pronunciation, perfectly clear Korean speech articulation, distinct Korean phonemes, saying exactly and only this one line: \\"먼저 안전핀을 힘껏 잡아당겨 뽑으세요.\\", begins after a very short half-second pause, then speaks slowly and deliberately, delivering the line clearly from the very first syllable and pacing it so the speech continues all the way to the end of the eight-second clip, never rushing or finishing early, nothing else is said and no additional words are improvised, no on-screen text, no captions, no subtitles, no readable signage or labels of any kind"}},
  {{"scene": 3, "script": "불을 쓸듯이 좌우로 뿌려 진화하세요.", "veo_prompt": "Cinematic medium close-up of a red fire extinguisher held upright and vertical in one gloved hand, a flexible black hose extends from the extinguisher valve and the other gloved hand holds the nozzle at the end of the hose, sweeping that nozzle steadily from side to side while the cylinder stays upright, a thick white cloud of extinguishing powder bursts continuously from the nozzle and sweeps across real orange flames burning in a metal tray on the ground, the flames shrink and die down under the white powder, outdoor fire safety training ground, no face and no person's head visible in the frame, a male Korean narrator voice-over speaks fluent Korean with authentic native pronunciation, perfectly clear Korean speech articulation, distinct Korean phonemes, saying exactly and only this one line: \\"불을 쓸듯이 좌우로 뿌려 진화하세요.\\", begins after a very short half-second pause, then speaks slowly and deliberately, delivering the line clearly from the very first syllable and pacing it so the speech continues all the way to the end of the eight-second clip, never rushing or finishing early, nothing else is said and no additional words are improvised, no on-screen text, no captions, no subtitles, no readable signage or labels of any kind"}},
  ...
]

파싱 문서 원문:
{extracted_text[:4000]}
"""
    if request:
        user_prompt += f"사용자 추가 요청: {request}\n"

    prompt_parts = [{"text": user_prompt}] + visual_parts
    payload = {"contents": [{"role": "user", "parts": prompt_parts}]}

    try:
        raw_resp = await asyncio.to_thread(_call_gemini_for_veo_sync, gemini_api_key, payload, models_to_try)
        if raw_resp:
            results = _clean_and_parse_json_for_veo(raw_resp, context="스토리보드 장면 생성")
            if results:
                print(f"[VeoGenerator] SUCCESS: parser 원문에서 직접 Veo 전용 프롬프트 {len(results)}개 생성 완료")
                return results
    except Exception as e:
        print(f"[VeoGenerator] parser 원문 기준 Veo 프롬프트 생성 중 예외: {e}")

    print(f"[VeoGenerator] WARNING: Gemini API 호출 실패/응답 파싱 불가로 {target_scenes}개 Fallback 장면 프롬프트를 사용합니다.")
    # 대사는 내용에 맞는 자연스러운 길이(12~34자). 클립 길이는 create_storyboard가 대사 길이로 정한다.
    # 구도는 클로즈업 + 배경 흐림으로 화면 속 깨진 한글이 나타날 표면을 줄인다.
    fallback_pairs = [
        (
            "안녕하세요, 오늘은 안전 수칙을 알아봅니다.",
            "Cinematic medium close-up shot framing an Asian male safety manager from the chest up"
        ),
        (
            "일을 시작하기 전에 안전모를 꼭 써 주세요.",
            "Medium close-up of the same safety manager from the chest up, putting on his hardhat"
        ),
        (
            "걸을 때는 정해진 길로만 다니세요.",
            "Medium close-up of the same safety manager from the chest up, gesturing toward the floor"
        ),
        (
            "위험한 일이 생기면, 바로 비상벨을 누르고 밖으로 나가세요.",
            "Medium close-up of the same safety manager from the chest up, pointing to one side"
        ),
        (
            "안전 수칙을 늘 지켜 주세요.",
            "Warm medium close-up of the same safety manager from the chest up, nodding to camera"
        ),
    ]
    fallback_scenes = []
    for i in range(target_scenes):
        script, visual = fallback_pairs[i % len(fallback_pairs)]
        fallback_scenes.append({
            "scene": i + 1,
            "script": script,
            # Fallback은 문서 내용이 반영되지 않은 고정 대본이라 어차피 저장 전에 실패 처리된다.
            # 동작 시연 구성은 문서에서 대상 장비를 알아야 가능하므로 여기서는 인물 발화로만 둔다.
            # 문서 내용이 전혀 반영되지 않은 고정 대본임을 상위에 알린다. 호출부가 이 플래그를 보고
            # 작업을 실패 처리해야 문서와 무관한 영상이 정상 결과로 저장되는 것을 막을 수 있다.
            "is_fallback": True,
            "veo_prompt": (
                f"{visual}, plain unmarked navy work uniform with no logos, patches, or lettering, "
                "plain solid yellow hardhat with no markings, "
                "shallow depth of field with the background heavily blurred and out of focus, "
                "the person speaks fluent Korean with authentic native pronunciation, perfectly clear Korean speech articulation, distinct Korean phonemes, natural Korean lip-sync, "
                f'saying exactly and only this one line: "{script}", '
                "begins after a very short half-second pause, then speaks slowly and deliberately, "
                "delivering the line clearly from the very first syllable and pacing it so the speech "
                "continues all the way to the end of the eight-second clip, never rushing or finishing early, "
                "he says nothing else and does not improvise any additional words, "
                "cinematic lighting, photorealistic 8k video, 24fps, no background music, "
                "no on-screen text, no captions, no subtitles, no readable signage or labels of any kind"
            )
        })
    return fallback_scenes


async def generate_json_response(instruction: str) -> Optional[Dict[str, Any]]:
    """Generate and safely parse a JSON-only Gemini response."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    payload = {"contents": [{"role": "user", "parts": [{"text": instruction}]}]}
    raw = await asyncio.to_thread(
        _call_gemini_for_veo_sync,
        api_key,
        payload,
        ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"],
    )
    parsed = _clean_and_parse_json_for_veo(raw, context="문서분석/학습목표 JSON 생성") if raw else None
    return parsed if isinstance(parsed, dict) else None


async def generate_storyboard_scenes(
    planning_context: str, request: Optional[str], target_scenes: Optional[int]
) -> List[Dict[str, Any]]:
    return await generate_veo_prompts_from_parsed_text(
        planning_context, request, target_scenes=target_scenes
    )
