from typing import Any, Literal, Optional, TypedDict


RouteStep = Literal[
    "inspection_action_management_agent",
    "education_management_agent",
    "law_manual_agent",
    "answer_agent",
]


class AgentState(TypedDict):
    access_token: str
    uid: Optional[int]
    company_id: Optional[int]
    role: str
    user_message: str

    context: dict[str, Any]
    next_step: str

    inspection_action_result: Optional[dict[str, Any]]
    education_result: Optional[dict[str, Any]]
    law_manual_result: Optional[dict[str, Any]]

    final_answer: str
    error_message: str
