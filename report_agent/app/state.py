from typing import TypedDict

from app.schemas import (
    AnalysisResult,
    GeneratedReport,
    HeadquartersReportRequest,
    ReviewResult,
    RiskAssessmentFormRequest,
    RiskDataCorrectionResult,
    RiskDataCorrectionReviewResult,
    SiteAnomalyReportRequest,
)


class HeadquartersReportState(TypedDict, total=False):
    request: HeadquartersReportRequest
    aggregated_data: dict
    analysis_result: AnalysisResult
    generated_report: GeneratedReport
    review_result: ReviewResult
    retry_count: int
    max_retry_count: int
    errors: list[str]


class SiteAnomalyReportState(TypedDict, total=False):
    request: SiteAnomalyReportRequest
    aggregated_data: dict
    analysis_result: AnalysisResult
    generated_report: GeneratedReport
    review_result: ReviewResult
    retry_count: int
    max_retry_count: int
    errors: list[str]
class RiskAssessmentFormState(TypedDict, total=False):
    request: RiskAssessmentFormRequest
    final_history_rows: list[dict]
    correction_result: RiskDataCorrectionResult
    correction_review: RiskDataCorrectionReviewResult
    csv_output_path: str
    retry_count: int
    max_retry_count: int
    errors: list[str]


