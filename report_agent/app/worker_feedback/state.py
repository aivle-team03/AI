from typing import TypedDict

from app.worker_feedback.schemas import (
    WorkerFeedbackCorrectionResult,
    WorkerFeedbackCorrectionReviewResult,
    WorkerFeedbackImprovementReportRequest,
)


class WorkerFeedbackImprovementReportState(TypedDict, total=False):
    request: WorkerFeedbackImprovementReportRequest
    backend_data: dict
    worker_feedback_rows: list[dict]
    correction_result: WorkerFeedbackCorrectionResult
    correction_review: WorkerFeedbackCorrectionReviewResult
    word_output_paths: list[str]
    retry_count: int
    max_retry_count: int
    errors: list[str]
