from typing import Any, Literal

from pydantic import BaseModel, Field


class FinalHistoryRow(BaseModel):
    category: str | None = None
    risk: str | int | None = None
    category_name: str | None = None
    inspection_location: str | None = None
    inspection_date: str | None = None
    inspection_user_name: str | None = None
    inspection_content: str | None = None
    image_url: str | None = None
    inspection_image_url: str | None = None
    action_name: str | None = None
    action_location: str | None = None
    completed_at: str | None = None
    handler_name: str | None = None
    content: str | None = None
    approver_name: str | None = None
    type: str | None = None


class DataCorrectionNote(BaseModel):
    row_index: int
    field: str
    original_text: str
    corrected_text: str
    reason: str


class RiskDataCorrectionResult(BaseModel):
    corrected_rows: list[FinalHistoryRow] = Field(default_factory=list)
    correction_notes: list[DataCorrectionNote] = Field(default_factory=list)
    unresolved_notes: list[str] = Field(default_factory=list)


class DataCorrectionReviewIssue(BaseModel):
    row_index: int | None = None
    field: str | None = None
    severity: Literal["ERROR", "WARNING"]
    category: Literal[
        "MEANING_CHANGED",
        "FABRICATED_FACT",
        "REPORT_STYLE",
        "UNNECESSARY_EDIT",
        "MISSED_CORRECTION",
        "PROTECTED_FIELD",
    ]
    original_text: str | None = None
    corrected_text: str | None = None
    message: str
    recommendation: str


class RiskDataCorrectionReviewResult(BaseModel):
    approved: bool
    final_decision: Literal["APPROVED", "REVISION_REQUIRED"]
    score: int = Field(ge=0, le=100)
    issues: list[DataCorrectionReviewIssue] = Field(default_factory=list)
    items_requiring_revision: list[str] = Field(default_factory=list)


class RiskAssessmentFormRequest(BaseModel):
    company: dict[str, Any] | None = None
    user: list[dict[str, Any]] = Field(default_factory=list)
    cctv: list[dict[str, Any]] = Field(default_factory=list)
    event_category: list[dict[str, Any]] = Field(default_factory=list)
    event: list[dict[str, Any]] = Field(default_factory=list)
    checklist: list[dict[str, Any]] = Field(default_factory=list)
    action_history: list[dict[str, Any]] = Field(default_factory=list)
    inspection: list[dict[str, Any]] = Field(default_factory=list)
    inspection_history: list[dict[str, Any]] = Field(default_factory=list)
    education: list[dict[str, Any]] = Field(default_factory=list)
    education_status: list[dict[str, Any]] = Field(default_factory=list)
    board: list[dict[str, Any]] = Field(default_factory=list)
    report: dict[str, Any] | None = None
    report_event_map: list[dict[str, Any]] = Field(default_factory=list)
    report_checklist_map: list[dict[str, Any]] = Field(default_factory=list)
    report_inspection_map: list[dict[str, Any]] = Field(default_factory=list)
    report_action_map: list[dict[str, Any]] = Field(default_factory=list)
    final_history_rows: list[FinalHistoryRow] = Field(default_factory=list)
    correction_batch_size: int = Field(default=10, ge=1)
    form_path: str | None = None
    output_path: str | None = None


class RiskAssessmentFormResponse(BaseModel):
    status: Literal["COMPLETED", "FAILED"]
    retry_count: int
    correction_batch_size: int | None = None
    correction_batch_count: int | None = None
    final_history_rows: list[FinalHistoryRow] = Field(default_factory=list)
    correction_result: RiskDataCorrectionResult
    correction_review: RiskDataCorrectionReviewResult
    csv_output_path: str | None = None
    xlsx_output_path: str | None = None
