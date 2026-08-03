from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from agent_main import run_agent


app = FastAPI(title="BP3 AI Agent API")
bearer_scheme = HTTPBearer(auto_error=False)


class HealthResponse(BaseModel):
    status: str


class AgentQueryRequest(BaseModel):
    user_message: str = Field(..., min_length=1)


class AgentQueryResponse(BaseModel):
    final_answer: str
    next_step: str
    context: Dict[str, Any]


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/api/agent/query", response_model=AgentQueryResponse)
def query_agent(
    request: AgentQueryRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> AgentQueryResponse:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 토큰이 필요합니다.",
        )
    try:
        result = run_agent(
            access_token=credentials.credentials,
            user_message=request.user_message,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="AI agent execution failed.",
        ) from exc

    return AgentQueryResponse(
        final_answer=result.get("final_answer", ""),
        next_step=result.get("next_step", ""),
        context=result.get("context", {}),
    )
