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
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output/videos").rstrip("/")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "output/uploads").rstrip("/")

BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000").rstrip("/")

FRONTEND_ORIGINS = _parse_csv_env(
    "FRONTEND_ORIGINS",
    "http://127.0.0.1:5173,http://localhost:5173",
)
