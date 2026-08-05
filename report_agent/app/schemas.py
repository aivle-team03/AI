from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Audience(str, Enum):
    HEADQUARTERS = "HEADQUARTERS"
    SITE_MANAGER = "SITE_MANAGER"
    EVIDENCE = "EVIDENCE"


class SectionCode(str, Enum):
    KPI = "KPI"
    TREND_ANALYSIS = "TREND_ANALYSIS"
    RISK_DISTRIBUTION = "RISK_DISTRIBUTION"
    EXECUTIVE_SUMMARY = "EXECUTIVE_SUMMARY"
    ANOMALY_PATTERNS = "ANOMALY_PATTERNS"
    REPEATED_RISKS = "REPEATED_RISKS"
    UNRESOLVED_ITEMS = "UNRESOLVED_ITEMS"
    PRIORITY_ACTIONS = "PRIORITY_ACTIONS"
    RECOMMENDATIONS = "RECOMMENDATIONS"
    EVENT_HISTORY = "EVENT_HISTORY"
    ACTION_HISTORY = "ACTION_HISTORY"
    EVIDENCE_LIST = "EVIDENCE_LIST"
    APPROVAL_RECORDS = "APPROVAL_RECORDS"


class AnalysisFinding(BaseModel):
    finding_type: Literal[
        "KPI",
        "TREND",
        "ANOMALY",
        "REPEATED_RISK",
        "UNRESOLVED",
        "PRIORITY",
        "EVIDENCE",
    ]
    title: str
    description: str
    related_event_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    severity: Literal["HIGH", "MEDIUM", "LOW", "INFO"]


class AnalysisResult(BaseModel):
    executive_insights: list[str] = Field(default_factory=list)
    findings: list[AnalysisFinding] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    data_limitations: list[str] = Field(default_factory=list)


class ReportSection(BaseModel):
    section_code: SectionCode
    heading: str
    content: str
    related_event_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class GeneratedReport(BaseModel):
    title: str
    audience: Audience
    period: str
    summary: str
    sections: list[ReportSection]
    conclusion: str
    limitations: list[str] = Field(default_factory=list)


class ReviewIssue(BaseModel):
    severity: Literal["ERROR", "WARNING"]
    category: str
    message: str
    section_code: SectionCode | None = None


class ReviewResult(BaseModel):
    passed: bool
    score: int = Field(ge=0, le=100)
    issues: list[ReviewIssue] = Field(default_factory=list)
    revision_instructions: list[str] = Field(default_factory=list)


class FinalHistoryRow(BaseModel):
    type: str | None = None
    source_type: str | None = None
    source_id: int | str | None = None
    inspection_history_id: int | None = None
    inspection_id: int | None = None
    inspection_name: str | None = None
    category_id: int | None = None
    category_name: str | None = None
    risk: str | int | None = None
    inspection_location: str | None = None
    inspection_date: str | None = None
    inspection_user_id: int | None = None
    inspection_user_name: str | None = None
    inspection_content: str | None = None
    before_image_url: str | None = None
    action_history_id: int | None = None
    action_name: str | None = None
    action_location: str | None = None
    action_date: str | None = None
    action_user_id: int | None = None
    action_user_name: str | None = None
    action_content: str | None = None
    action_status: str | None = None
    approval_status: str | None = None
    approval_name: str | None = None
    board_id: int | None = None
    event_id: str | int | None = None

class DataCorrectionNote(BaseModel):
    row_index: int
    field: str
    original_text: str
    corrected_text: str
    reason: str


class RiskDataCorrectionRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    protected_fields: list[str] = Field(default_factory=list)


class RiskDataCorrectionResult(BaseModel):
    corrected_rows: list[FinalHistoryRow] = Field(default_factory=list)
    correction_notes: list[DataCorrectionNote] = Field(default_factory=list)
    unresolved_notes: list[str] = Field(default_factory=list)


class RiskDataCorrectionResponse(BaseModel):
    status: Literal["COMPLETED", "FAILED"]
    result: RiskDataCorrectionResult

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


class EvidenceContentRequest(BaseModel):
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
    signup_code: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceContentResponse(BaseModel):
    content: str
    summary: str
    event_ids: list[str] = Field(default_factory=list)
    checklist_ids: list[int] = Field(default_factory=list)
    inspection_history_ids: list[int] = Field(default_factory=list)
    action_history_ids: list[int] = Field(default_factory=list)


class RiskAssessmentFormRequest(EvidenceContentRequest):
    form_path: str | None = None
    output_path: str | None = None


class RiskAssessmentFormResponse(BaseModel):
    status: Literal["COMPLETED", "FAILED"]
    retry_count: int
    final_history_rows: list[FinalHistoryRow] = Field(default_factory=list)
    correction_result: RiskDataCorrectionResult
    correction_review: RiskDataCorrectionReviewResult
    csv_output_path: str | None = None

class HeadquartersReportRequest(EvidenceContentRequest):
    corrected_rows: list[FinalHistoryRow] = Field(default_factory=list)


class SiteAnomalyReportRequest(EvidenceContentRequest):
    corrected_rows: list[FinalHistoryRow] = Field(default_factory=list)


class HeadquartersReportResponse(BaseModel):
    status: Literal["COMPLETED", "FAILED"]
    retry_count: int
    aggregated_data: dict[str, Any]
    analysis_result: AnalysisResult
    report: GeneratedReport
    review: ReviewResult


class SiteAnomalyReportResponse(BaseModel):
    status: Literal["COMPLETED", "FAILED"]
    retry_count: int
    aggregated_data: dict[str, Any]
    analysis_result: AnalysisResult
    report: GeneratedReport
    review: ReviewResult


class WorkerFeedbackRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

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









