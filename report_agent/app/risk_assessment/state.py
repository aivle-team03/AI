from typing import TypedDict

from app.schemas import (
    AnalysisResult,
    GeneratedReport,
    ReviewResult,
    RiskAssessmentReportRequest,
)


class RiskAssessmentReportState(TypedDict, total=False):
    request: RiskAssessmentReportRequest
    final_history_rows: list[dict]
    aggregated_data: dict
    analysis_result: AnalysisResult
    generated_report: GeneratedReport
    review_result: ReviewResult
    retry_count: int
    max_retry_count: int
    errors: list[str]
