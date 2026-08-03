from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


InspectionActionOperation = Literal[
    "list_inspections",
    "get_inspection",
    "list_inspection_histories",
    "get_inspection_history",
    "list_action_histories",
    "get_action_history",
]


class InspectionActionQuery(BaseModel):
    operation: InspectionActionOperation
    inspection_id: Optional[int] = Field(default=None, gt=0)
    inspection_history_id: Optional[int] = Field(default=None, gt=0)
    action_history_id: Optional[int] = Field(default=None, gt=0)
    keyword: Optional[str] = Field(default=None, max_length=100)
    category_id: Optional[int] = Field(default=None, gt=0)
    uid: Optional[int] = Field(default=None, gt=0)
    handler_uid: Optional[int] = Field(default=None, gt=0)
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
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="after")
    def validate_detail_identifier(self):
        required_id = {
            "get_inspection": self.inspection_id,
            "get_inspection_history": self.inspection_history_id,
            "get_action_history": self.action_history_id,
        }.get(self.operation)
        if self.operation.startswith("get_") and required_id is None:
            raise ValueError("상세 조회 operation에는 대응하는 ID가 필요합니다.")
        return self


class InspectionActionPlan(BaseModel):
    queries: List[InspectionActionQuery] = Field(min_length=1, max_length=3)
