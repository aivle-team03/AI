import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import create_llm
from app.worker_feedback.prompts import (
    WORKER_FEEDBACK_CORRECTION_PROMPT,
    WORKER_FEEDBACK_CORRECTION_REVIEW_PROMPT,
)
from app.worker_feedback.schemas import (
    WorkerFeedbackCorrectionResult,
    WorkerFeedbackCorrectionReviewResult,
)


async def worker_feedback_correction_agent(
    rows,
    protected_fields=None,
    previous_result=None,
    review_result=None,
):
    llm = create_llm().with_structured_output(WorkerFeedbackCorrectionResult)
    payload = {
        "rows": rows,
        "protected_fields": protected_fields or [],
        "previous_result": (
            previous_result.model_dump(mode="json") if previous_result else None
        ),
        "review_result": (
            review_result.model_dump(mode="json") if review_result else None
        ),
    }
    return await llm.ainvoke(
        [
            SystemMessage(content=WORKER_FEEDBACK_CORRECTION_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )


async def worker_feedback_correction_review_agent(
    original_rows,
    correction_result,
    protected_fields=None,
):
    llm = create_llm().with_structured_output(WorkerFeedbackCorrectionReviewResult)
    payload = {
        "original_rows": original_rows,
        "correction_result": correction_result.model_dump(mode="json"),
        "protected_fields": protected_fields or [],
    }
    return await llm.ainvoke(
        [
            SystemMessage(content=WORKER_FEEDBACK_CORRECTION_REVIEW_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )
