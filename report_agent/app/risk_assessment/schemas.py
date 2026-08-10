from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Audience(str, Enum):
    RISK_ASSESSMENT_REPORT = "RISK_ASSESSMENT_REPORT"


class SectionCode(str, Enum):
    EXECUTIVE_SUMMARY = "EXECUTIVE_SUMMARY"
    RISK_DISTRIBUTION = "RISK_DISTRIBUTION"
    HIGH_RISK_ITEMS = "HIGH_RISK_ITEMS"


class AnalysisFinding(BaseModel):
    finding_type: Literal[
        "KPI",
        "TREND",
        "RISK_ASSESSMENT",
        "UNRESOLVED",
        "PRIORITY",
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


class RiskAssessmentReportRequest(EvidenceContentRequest):
    final_history_rows: list[FinalHistoryRow] = Field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None


class RiskAssessmentReportResponse(BaseModel):
    status: Literal["COMPLETED", "FAILED"]
    retry_count: int
    aggregated_data: dict[str, Any]
    analysis_result: AnalysisResult
    report: GeneratedReport
    review: ReviewResult
