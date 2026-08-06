from typing import TypedDict

from app.schemas import (
    AnalysisResult,
    GeneratedReport,
    ReviewResult,
    RiskAssessmentFormRequest,
    RiskAssessmentReportRequest,
    RiskDataCorrectionResult,
    RiskDataCorrectionReviewResult,
    SiteAnomalyReportRequest,
    UnifiedReportRequest,
)




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
    backend_data: dict
    final_history_rows: list[dict]
    correction_result: RiskDataCorrectionResult
    correction_review: RiskDataCorrectionReviewResult
    csv_output_path: str
    xlsx_output_path: str
    retry_count: int
    max_retry_count: int
    errors: list[str]




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


class UnifiedReportState(TypedDict, total=False):
    request: UnifiedReportRequest
    final_history_rows: list[dict]
    correction_result: RiskDataCorrectionResult
    correction_review: RiskDataCorrectionReviewResult
    preprocessing_retry_count: int
    aggregated_data: dict
    analysis_result: AnalysisResult
    generated_report: GeneratedReport
    review_result: ReviewResult
    csv_output_path: str
    xlsx_output_path: str
    retry_count: int
    max_retry_count: int
    errors: list[str]
