from typing import TypedDict

from app.risk_assessment_form_graph.schemas import (
    RiskAssessmentFormRequest,
    RiskDataCorrectionResult,
    RiskDataCorrectionReviewResult,
)


class RiskAssessmentFormState(TypedDict, total=False):
    request: RiskAssessmentFormRequest
    backend_data: dict
    final_history_rows: list[dict]
    correction_result: RiskDataCorrectionResult
    correction_review: RiskDataCorrectionReviewResult
    correction_batch_size: int
    correction_batch_count: int
    csv_output_path: str
    xlsx_output_path: str
    retry_count: int
    max_retry_count: int
    errors: list[str]
