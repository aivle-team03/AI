import os

from dotenv import load_dotenv


load_dotenv()


def _parse_csv_env(name: str, default: str) -> tuple[str, ...]:
    raw_value = os.getenv(name, default)
    return tuple(
        value.strip().rstrip("/")
        for value in raw_value.split(",")
        if value.strip()
    )


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# 생성 산출물 경로. 백엔드의 static/ 아래가 아니라 이 서비스 전용 디렉터리를 쓴다.
# 업로드 원본은 OS 임시 디렉터리를 쓰므로 별도 설정이 없다.
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output/videos").rstrip("/")

BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000").rstrip("/")

FRONTEND_ORIGINS = _parse_csv_env(
    "FRONTEND_ORIGINS",
    "http://127.0.0.1:5173,http://localhost:5173",
)

# 생성된 영상을 올릴 S3 버킷. 백엔드의 이미지 버킷과 같은 것을 쓴다.
AWS_S3_MEDIA_BUCKET = os.getenv("AWS_S3_MEDIA_BUCKET")
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-2")

# 재생 URL 의 접두사(CloudFront 주소). 백엔드가 이 URL 을 education 테이블에
# 그대로 저장하므로 절대 주소여야 한다.
MEDIA_BASE_URL = os.getenv("MEDIA_BASE_URL", "").rstrip("/")
