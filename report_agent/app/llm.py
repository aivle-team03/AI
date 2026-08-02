from langchain_openai import ChatOpenAI

from app.config import MAX_RETRY_COUNT, OPENAI_API_KEY, OPENAI_MODEL


def create_llm():
    if not OPENAI_API_KEY:
        raise RuntimeError("Set OPENAI_API_KEY in .env or environment variables.")
    return ChatOpenAI(
        api_key=OPENAI_API_KEY,
        model=OPENAI_MODEL,
        temperature=0,
        timeout=90,
        max_retries=MAX_RETRY_COUNT,
    )
