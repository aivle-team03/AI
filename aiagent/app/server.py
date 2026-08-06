from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from agent_main import run_agent
from app.config import FRONTEND_ORIGINS


app = FastAPI(title="BP3 AI Agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(FRONTEND_ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
bearer_scheme = HTTPBearer(auto_error=False)


class HealthResponse(BaseModel):
    status: str


class AgentQueryRequest(BaseModel):
    user_message: str = Field(..., min_length=1)
    conversation_id: UUID = Field(default_factory=uuid4)


class AgentQueryResponse(BaseModel):
    final_answer: str
    next_step: str
    context: Dict[str, Any]
    conversation_id: UUID


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
            conversation_id=str(request.conversation_id),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="AI agent execution failed.",
        ) from exc

    result_context = result.get("context", {})
    auth_status_code = result_context.get("auth_status_code")
    if auth_status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN):
        raise HTTPException(
            status_code=auth_status_code,
            detail=result.get("final_answer") or "AI 요청 권한을 확인할 수 없습니다.",
        )

    return AgentQueryResponse(
        final_answer=result.get("final_answer", ""),
        next_step=result.get("next_step", ""),
        context=result_context,
        conversation_id=UUID(result.get("conversation_id", str(request.conversation_id))),
    )
