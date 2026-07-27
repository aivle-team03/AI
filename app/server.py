from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent_main import run_agent


app = FastAPI(title="BP3 AI Agent API")


class HealthResponse(BaseModel):
    status: str


class AgentQueryRequest(BaseModel):
    company_code: str = Field(..., min_length=1)
    role: str = Field(..., min_length=1)
    user_message: str = Field(..., min_length=1)


class AgentQueryResponse(BaseModel):
    final_answer: str
    next_step: str
    context: Dict[str, Any]


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/api/agent/query", response_model=AgentQueryResponse)
def query_agent(request: AgentQueryRequest) -> AgentQueryResponse:
    try:
        result = run_agent(
            company_code=request.company_code,
            role=request.role,
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
