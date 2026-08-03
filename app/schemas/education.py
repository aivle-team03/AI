from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


EducationOperation = Literal[
    "list_education_courses",
    "get_education_course",
    "list_education_summaries",
    "list_course_attendees",
    "list_user_education_statuses",
    "get_education_overview",
]


class EducationQuery(BaseModel):
    operation: EducationOperation
    education_id: Optional[int] = Field(default=None, gt=0)
    uid: Optional[int] = Field(default=None, gt=0)
    user_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    keyword: Optional[str] = Field(default=None, max_length=100)
    category: Optional[str] = Field(default=None, max_length=100)
    education_type: Optional[str] = Field(default=None, max_length=50)
    status_filter: Optional[Literal["미이수", "진행중", "이수"]] = None
    due_state: Optional[Literal["this_week", "overdue", "no_due_date"]] = None
    due_from: Optional[date] = None
    due_to: Optional[date] = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="after")
    def validate_operation_requirements(self):
        if self.operation in {"get_education_course", "list_course_attendees"}:
            if self.education_id is None:
                raise ValueError("과정 조회 operation에는 education_id가 필요합니다.")
        if self.operation == "list_user_education_statuses":
            if self.uid is None and not self.user_name:
                raise ValueError("사용자 조회에는 uid 또는 user_name이 필요합니다.")
            if self.uid is not None and self.user_name:
                raise ValueError("uid와 user_name은 동시에 사용할 수 없습니다.")
        if self.due_from and self.due_to and self.due_from > self.due_to:
            raise ValueError("due_from은 due_to보다 늦을 수 없습니다.")
        return self


class EducationPlan(BaseModel):
    queries: List[EducationQuery] = Field(min_length=1, max_length=3)
