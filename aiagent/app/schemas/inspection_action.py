from datetime import date
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


InspectionActionOperation = Literal[
    "list_inspections",
    "get_inspection",
    "list_inspection_histories",
    "get_inspection_history",
    "list_action_histories",
    "get_action_history",
]

ACTION_STATUS_ALIASES = {
    "대기": "조치 대기",
    "대기중": "조치 대기",
    "조치대기": "조치 대기",
    "조치 대기중": "조치 대기",
    "미조치": "조치 대기",
    "완료": "조치 완료",
    "처리 완료": "조치 완료",
    "처리완료": "조치 완료",
    "조치완료": "조치 완료",
}

APPROVAL_STATUS_ALIASES = {
    "승인대기": "승인 대기",
    "승인 대기중": "승인 대기",
    "승인대기중": "승인 대기",
    "승인완료": "승인 완료",
    "승인됨": "승인 완료",
    "반려된": "반려",
    "반려됨": "반려",
    "거절": "반려",
    "거절된": "반려",
    "거절됨": "반려",
    "반송": "반려",
    "반송된": "반려",
    "반송됨": "반려",
}


def _canonical_status(value: Any, aliases: dict[str, str]) -> Any:
    if not isinstance(value, str):
        return value
    normalized = " ".join(value.strip().split())
    return aliases.get(normalized, normalized)


class InspectionActionQuery(BaseModel):
    operation: InspectionActionOperation
    inspection_id: Optional[int] = Field(default=None, gt=0)
    inspection_history_id: Optional[int] = Field(default=None, gt=0)
    action_history_id: Optional[int] = Field(default=None, gt=0)
    keyword: Optional[str] = Field(default=None, max_length=100)
    category_id: Optional[int] = Field(default=None, gt=0)
    category: Optional[str] = Field(default=None, min_length=1, max_length=50)
    category_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    uid: Optional[int] = Field(default=None, gt=0)
    handler_uid: Optional[int] = Field(default=None, gt=0)
    inspection_history_ids: Optional[List[int]] = Field(
        default=None,
        max_length=50,
    )
    unassigned: Optional[bool] = None
    status_filter: Optional[Literal["점검 대기", "점검 완료"]] = None
    is_action_required: Optional[bool] = None
    source_type: Optional[
        Literal["게시판", "이벤트", "점검이력", "직접추가"]
    ] = None
    action_status: Optional[Literal["조치 대기", "조치 완료"]] = None
    approval_status: Optional[
        Literal["승인 대기", "승인 완료", "반려"]
    ] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    created_from: Optional[date] = None
    created_to: Optional[date] = None
    completed_from: Optional[date] = None
    completed_to: Optional[date] = None
    response_mode: Literal["summary", "list", "reason", "ratio"] = "list"
    summary_scope: Optional[
        Literal["inspection_status", "action_status", "approval_status"]
    ] = None
    sort_by: Optional[Literal["risk_desc"]] = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="before")
    @classmethod
    def normalize_status_fields(cls, value: Any):
        if not isinstance(value, dict):
            return value

        data = dict(value)
        action_status = _canonical_status(
            data.get("action_status"),
            ACTION_STATUS_ALIASES,
        )
        approval_status = _canonical_status(
            data.get("approval_status"),
            APPROVAL_STATUS_ALIASES,
        )

        # Repair a common planner error: approval states placed in action_status.
        action_as_approval = _canonical_status(
            action_status,
            APPROVAL_STATUS_ALIASES,
        )
        if action_as_approval in {"승인 대기", "승인 완료", "반려"}:
            if approval_status is None:
                approval_status = action_as_approval
            action_status = None

        if action_status is None:
            data.pop("action_status", None)
        else:
            data["action_status"] = action_status
        if approval_status is not None:
            data["approval_status"] = approval_status
        return data

    @model_validator(mode="after")
    def validate_detail_identifier(self):
        required_id = {
            "get_inspection": self.inspection_id,
            "get_inspection_history": self.inspection_history_id,
            "get_action_history": self.action_history_id,
        }.get(self.operation)
        if self.operation.startswith("get_") and required_id is None:
            raise ValueError("상세 조회 operation에는 대응하는 ID가 필요합니다.")
        if self.inspection_history_ids is not None:
            if not self.inspection_history_ids:
                raise ValueError("inspection_history_ids는 비어 있을 수 없습니다.")
            if any(value <= 0 for value in self.inspection_history_ids):
                raise ValueError("inspection_history_ids는 양수여야 합니다.")
        return self


class InspectionActionPlan(BaseModel):
    queries: List[InspectionActionQuery] = Field(min_length=1, max_length=3)
