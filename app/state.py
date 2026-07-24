from typing import Any, TypedDict


class AgentState(TypedDict):
    company_code: str
    role: str
    user_message: str

    context: dict[str, Any]
    next_step: str

    inspection_action_result: dict[str, Any]
    education_result: dict[str, Any]
    history_result: dict[str, Any]

    final_answer: str
    error_message: str
