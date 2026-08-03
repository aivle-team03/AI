import os

from dotenv import load_dotenv


load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000").rstrip("/")
BACKEND_TIMEOUT_SECONDS = float(os.getenv("BACKEND_TIMEOUT_SECONDS", "5"))
AGENT_READ_DATABASE_URL = os.getenv("AGENT_READ_DATABASE_URL", "").strip()
AGENT_READ_DB_SSL_CA = os.getenv("AGENT_READ_DB_SSL_CA", "").strip()
