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


def _parse_positive_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer.")
    return value

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000").rstrip("/")
BACKEND_TIMEOUT_SECONDS = float(os.getenv("BACKEND_TIMEOUT_SECONDS", "5"))
AGENT_READ_DATABASE_URL = os.getenv("AGENT_READ_DATABASE_URL", "").strip()
AGENT_READ_DB_SSL_CA = os.getenv("AGENT_READ_DB_SSL_CA", "").strip()
FRONTEND_ORIGINS = _parse_csv_env(
    "FRONTEND_ORIGINS",
    "http://127.0.0.1:5173,http://localhost:5173",
)
CONVERSATION_MAX_TURNS = _parse_positive_int_env("CONVERSATION_MAX_TURNS", 10)
CONVERSATION_TTL_SECONDS = _parse_positive_int_env(
    "CONVERSATION_TTL_SECONDS",
    3600,
)
CONVERSATION_MAX_SESSIONS = _parse_positive_int_env(
    "CONVERSATION_MAX_SESSIONS",
    1000,
)
