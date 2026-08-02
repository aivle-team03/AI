from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


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


class HeadquartersReportRequest(EvidenceContentRequest):
    pass


class SiteAnomalyReportRequest(EvidenceContentRequest):
    pass


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
