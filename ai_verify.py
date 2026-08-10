import base64
import json
import os
from openai import OpenAI
from dotenv import load_dotenv
from fastapi import UploadFile, File, Form, HTTPException, FastAPI

load_dotenv()

app = FastAPI(title="AI Verification Server")

api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    raise ValueError("🚨 OPENAI_API_KEY가 .env 파일에 설정되지 않았거나 읽을 수 없습니다.")

openai_client = OpenAI(api_key=api_key)

@app.post("/api/ai/verify-action")
async def verify_action_endpoint(
    after_img: UploadFile = File(...),
    category_name: str = Form("안전 위험 요인"),
    action_content: str = Form(""),
):
    """조치 사진(after_img)을 받아 OpenAI VLM으로 해소 여부 판독"""
    try:
        image_bytes = await after_img.read()
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        mime_type = after_img.content_type or "image/jpeg"

        prompt = f"""
        당신은 산업현장 AI 안전 검사관입니다.
        다른 카테고리나 위험 요소는 절대 고려하지 말고, 오직 지정된 **[{category_name}]** 카테고리와 작업자가 제출한 [조치 내용]을 종합하여 판단하세요.

        [검사 정보]
        - 카테고리: [{category_name}]
        - 작업자가 입력한 조치 내용: "{action_content if action_content.strip() else '내용 없음'}"

        [판단 규칙]
        1. 지정 카테고리가 '화재/불꽃/연기'인 경우:
           - 사진에 불이나 연기가 없거나, **[{category_name}]**에 대한 대응 조치(소화기 배치, 소화전 비치, 불씨 제거 등)가 확인되면 -> (is_resolved: true)
           - 여전히 화재 위험이 남아있으면 -> (is_resolved: false)

        2. 지정 카테고리가 '소화기/소화전/피난구' 등 안전장비인 경우:
           - 해당 장비가 정상 비치/설치되어 있으면 -> (is_resolved: true)
           - 장비가 없거나 파손되었으면 -> (is_resolved: false)

        3. 그 외 제공된 지정 카테고리인 경우:
           - 해당 위험이 정리/해소되었으면 -> (is_resolved: true)
           - 위험이 그대로 남아있으면 -> (is_resolved: false)

        4. [조치 내용 검증]
           - 작성된 [조치 내용]이 사진 속 실제 조치 상태와 일치해야 합니다.

        [주의사항]
        - 제공된 **[{category_name}]** 이외의 다른 현장 상태나 위험 요소는 판단에 반영하지 마세요.

        [출력 규칙]
        1. 지정 카테고리가 안전하게 조치되었고 조치 내용과 사진이 일치하면 is_resolved를 true, 미조치 상태면 false로 지정하세요.
        2. result_text는 조치 완료 시 "위험요소 해소", 미해소 시 "위험요소 미해소"로 작성하세요.
        3. analysis_summary에는 **[{category_name}]** 관점 및 작성된 조치 내용과의 부합 여부를 포함하여 판단 근거를 한 문장의 한국어로 작성하세요.

        응답은 반드시 아래 json 구조로 작성하세요:
        {{
          "is_resolved": boolean,
          "result_text": string,
          "confidence": float,
          "analysis_summary": string
        }}
        """
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_image}",
                                "detail": "high"
                            },
                        },
                    ],
                }
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=250,
            timeout=15.0,
        )

        content = response.choices[0].message.content
        return json.loads(content)

    except Exception as e:
        print(f"🚨 [AI 서버 VLM 에러]: {e}", flush=True)
        return {
            "is_resolved": False,
            "result_text": "AI 분석 실패",
            "confidence": 0.0,
            "analysis_summary": f"VLM 분석 중 오류 발생: {str(e)}",
        }