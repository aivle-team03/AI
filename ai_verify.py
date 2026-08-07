import os
import base64
import json
from pathlib import Path
from openai import OpenAI

# .env 파일의 OPENAI_API_KEY 자동 로드
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def encode_image_to_base64(image_path: str) -> str:
    """로컬 이미지 파일을 Base64 문자열로 변환"""
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"이미지 파일을 찾을 수 없습니다: {image_path}")
    
    with open(path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def verify_action_image(category_name: str, local_image_path: str) -> dict:
    """VLM(GPT-4o-mini)을 사용하여 조치 완료 여부 검사"""
    base64_image = encode_image_to_base64(local_image_path)

    prompt = f"""
    당신은 산업 현장 안전 관리자 AI입니다.
    원래 감지되었던 위험 요소 카테고리는 [{category_name}] 입니다.

    첨부된 [조치 등록 사진]을 보고 다음을 판단해 주세요:
    1. 사진 상에서 [{category_name}] 위험이 완전히 조치/해소되었는가?
    2. 판단 결과와 함께 판단 근거를 한국어 한 문장으로 작성하세요.

    반드시 아래 JSON 포맷으로만 응답하세요:
    {{
      "is_resolved": true,
      "result_text": "위험요소 해소",
      "confidence": 98.4,
      "analysis_summary": "정상 상태 복구 감지됨"
    }}
    (만약 해소되지 않았다면 is_resolved는 false, result_text는 "위험요소 미해소"로 응답)
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        },
                    },
                ],
            }
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )

    return json.loads(response.choices[0].message.content)