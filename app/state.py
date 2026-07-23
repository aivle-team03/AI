from typing import Any, NotRequired, TypedDict


class AgentState(TypedDict):
    company_code: str
    role: str
    user_message: str

    context: NotRequired[dict[str, Any]]
    next_step: NotRequired[str]

    tool_results: NotRequired[dict[str, Any]]
    agent_results: NotRequired[dict[str, Any]]

    final_answer: NotRequired[str]
    error_message: NotRequired[str]
