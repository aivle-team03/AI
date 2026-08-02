from typing import TypedDict

from app.schemas import (
    AnalysisResult,
    GeneratedReport,
    HeadquartersReportRequest,
    ReviewResult,
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
