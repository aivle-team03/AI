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
    before_img: UploadFile | None = File(None),
    category_name: str = Form("안전 위험 요인"),
    action_content: str = Form(""),
):
    """조치 사진(after_img)을 받아 OpenAI VLM으로 해소 여부 판독"""
    try:
        after_bytes = await after_img.read()
        after_b64 = base64.b64encode(after_bytes).decode("utf-8")
        after_mime = after_img.content_type or "image/jpeg"
        
        before_b64 = None
        before_mime = "image/jpeg"
        if before_img:
            before_bytes = await before_img.read()
            if before_bytes:
                before_b64 = base64.b64encode(before_bytes).decode("utf-8")
                before_mime = before_img.content_type or "image/jpeg"

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
           
        [판단 규칙 2]
        1. '조치 전 사진'이 함께 제공된 경우:
        - 조치 전 사진의 위험 상태(방치물, 불씨, 안전장비 미비 등)가 '조치 후 사진'에서 깔끔하게 해결/정리되었는지 비교 검증하세요.
        2. '조치 후 사진'만 제공된 경우:
        - 해당 사진 내에서 [{category_name}] 위험이 해소되었는지 단독 판단하세요.
        3. 작업자가 작성한 [조치 내용]이 실제 조치 후 사진 속 모습과 모순되지 않아야 승인(is_resolved: true)합니다.

        [주의사항]
        - 제공된 **[{category_name}]** 이외의 다른 현장 상태나 위험 요소는 판단에 반영하지 마세요.

        [출력 규칙]
        1. 지정 카테고리가 안전하게 조치되었고 조치 내용과 사진이 일치하면 is_resolved를 true, 미조치 상태면 false로 지정하세요.
        2. result_text는 조치 완료 시 "위험요소 해소", 미해소 시 "위험요소 미해소"로 작성하세요.
        3. confidence에는 제공된 이미지의 화질, 위험요소 해소 여부의 선명도, 조치 내용과의 일치성을 스스로 종합 평가하여 본인의 확신 정도를 0.0 ~ 1.0 사이의 실수로 자유롭게 부여하세요.
        4. analysis_summary에는 **[{category_name}]** 관점 및 작성된 조치 내용과의 부합 여부를 포함하여 판단 근거를 한 문장의 한국어로 작성하세요.

        응답은 반드시 아래 json 구조로 작성하세요:
        {{
          "is_resolved": boolean,
          "result_text": string,
          "confidence": float,
          "analysis_summary": string
        }}
        """
        user_content = [{"type": "text", "text": prompt}]

        if before_b64:
            user_content.append({"type": "text", "text": "[조치 전 위험 사진]"})
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{before_mime};base64,{before_b64}",
                    "detail": "high"
                }
            })
            
        user_content.append({"type": "text", "text": "[조치 후 사진]"})
        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{after_mime};base64,{after_b64}",
                "detail": "high"
            }
        })
        
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": user_content,
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