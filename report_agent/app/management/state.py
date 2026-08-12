from typing import TypedDict

from app.management.schemas import (
    AnalysisResult,
    GeneratedReport,
    ReviewResult,
    RiskDataCorrectionResult,
    RiskDataCorrectionReviewResult,
    UnifiedReportRequest,
)


class ManagementReviewOrderState(TypedDict, total=False):
    request: UnifiedReportRequest
    final_history_rows: list[dict]
    correction_result: RiskDataCorrectionResult
    correction_review: RiskDataCorrectionReviewResult
    preprocessing_retry_count: int
    aggregated_data: dict
    analysis_result: AnalysisResult
    generated_report: GeneratedReport
    review_result: ReviewResult
    retry_count: int
    max_retry_count: int
    errors: list[str]
