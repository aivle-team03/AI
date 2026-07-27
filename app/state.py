from typing import Any, TypedDict

from app.schemas import EducationResult, HistoryResult, InspectionActionResult


class AgentState(TypedDict):
    company_code: str
    role: str
    user_message: str

    context: dict[str, Any]
    next_step: str

    inspection_action_result: InspectionActionResult
    education_result: EducationResult
    history_result: HistoryResult

    final_answer: str
    error_message: str
