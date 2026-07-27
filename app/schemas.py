from typing import Any, Literal, Optional, TypedDict


RouteStep = Literal[
    "inspection_action_agent",
    "education_agent",
    "history_agent",
    "answer_agent",
]

EducationProgressStatus = Literal["미이수", "진행중", "이수"]
HistoryRecordType = Literal["event", "checklist", "report", "education"]

class RiskEventItem(TypedDict):
    event_id: int
    occurred_at: str
    category: str
    category_name: str
    camera_id: Optional[int]
    camera_name: str
    location: str
    current_status: str
    image_url: Optional[str]
    description: str


class ActionItem(TypedDict):
    checklist_id: int
    event_id: Optional[int]
    camera_id: Optional[int]
    assigned_uid: Optional[int]
    status: str
    requested_at: str
    completed_at: str
    location: str
    content: str
    image_url: Optional[str]


class InspectionActionResult(TypedDict):
    summary: str
    total_risk_count: int
    pending_action_count: int
    in_progress_count: int
    completed_count: int
    risk_events: list[RiskEventItem]
    pending_actions: list[ActionItem]
    in_progress_actions: list[ActionItem]
    completed_actions: list[ActionItem]
    source: str


class EducationItem(TypedDict):
    education_id: int
    title: str
    role: str
    category: str
    education_type: str
    due_date: str
    status: EducationProgressStatus
    completed_date: str


class RoleCompletionStat(TypedDict):
    role: str
    completion_rate: float
    target_count: int
    completed_count: int


class EducationResult(TypedDict):
    summary: str
    total_count: int
    due_this_week_count: int
    incomplete_count: int
    in_progress_count: int
    completed_count: int
    essential_rate: float
    regular_rate: float
    total_completion_rate: float
    educations: list[EducationItem]
    role_completion_stats: list[RoleCompletionStat]
    source: str

class HistoryRecordItem(TypedDict):
    record_type: HistoryRecordType
    record_id: int
    title: str
    occurred_at: str
    status: str
    location: str
    related_event_id: Optional[int]
    related_checklist_id: Optional[int]
    content: str
    summary: str

class HistoryResult(TypedDict):
    summary: str
    total_count: int
    period_start: str
    period_end: str
    filters: dict[str, Any]
    records: list[HistoryRecordItem]
    source: str
