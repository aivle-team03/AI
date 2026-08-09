from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import EvidenceContentRequest


class WorkerFeedbackRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    board_id: int | str | None = Field(default=None, alias="게시글 ID")
    category: str | None = Field(default=None, alias="카테고리")
    risk: str | int | None = Field(default=None, alias="위험도")
    category_name: str | None = Field(default=None, alias="이름")
    user: str | None = Field(default=None, alias="근로자 성명")
    board_writer: str | None = Field(default=None, alias="게시글 작성자")
    board_created_at: str | None = Field(default=None, alias="신고일시")
    board_contents: str | None = Field(default=None, alias="신고 내용")
    status: str | None = Field(default=None, alias="상태")
    board_image_url: str | None = Field(default=None, alias="신고 이미지")
    action_name: str | None = Field(default=None, alias="조치이름")
    location: str | None = Field(default=None, alias="구역")
    completed_at: str | None = Field(default=None, alias="조치일시")
    action_status: str | None = Field(default=None, alias="조치상태")
    handler_name: str | None = Field(default=None, alias="담당자")
    content: str | None = Field(default=None, alias="내용")
    image_url: str | None = Field(default=None, alias="조치 후 사진")
    approver_name: str | None = Field(default=None, alias="승인자")
    source_type: str | None = Field(default=None, alias="타입")


class WorkerFeedbackCorrectionNote(BaseModel):
    row_index: int
    field: str
    original_text: str
    corrected_text: str
    reason: str


class WorkerFeedbackCorrectionResult(BaseModel):
    corrected_rows: list[WorkerFeedbackRow] = Field(default_factory=list)
    correction_notes: list[WorkerFeedbackCorrectionNote] = Field(default_factory=list)
    unresolved_notes: list[str] = Field(default_factory=list)


class WorkerFeedbackCorrectionReviewIssue(BaseModel):
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


class WorkerFeedbackCorrectionReviewResult(BaseModel):
    approved: bool
    final_decision: Literal["APPROVED", "REVISION_REQUIRED"]
    score: int = Field(ge=0, le=100)
    issues: list[WorkerFeedbackCorrectionReviewIssue] = Field(default_factory=list)
    items_requiring_revision: list[str] = Field(default_factory=list)


class WorkerFeedbackImprovementReportRequest(EvidenceContentRequest):
    word_template_path: str | None = None
    word_output_dir: str | None = None


class WorkerFeedbackImprovementReportResponse(BaseModel):
    status: Literal["COMPLETED", "FAILED"]
    retry_count: int
    worker_feedback_rows: list[WorkerFeedbackRow] = Field(default_factory=list)
    correction_result: WorkerFeedbackCorrectionResult
    correction_review: WorkerFeedbackCorrectionReviewResult
    word_output_paths: list[str] = Field(default_factory=list)
    s3_output_paths: list[str] = Field(default_factory=list)
