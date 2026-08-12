import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import create_llm
from app.management.prompts import (
    COMMON_REPORT_STYLE_GUIDE,
    MANAGEMENT_REVIEW_ANALYSIS_PROMPT,
    MANAGEMENT_REVIEW_REVIEW_PROMPT,
    MANAGEMENT_REVIEW_WRITER_PROMPT,
)
from app.management.schemas import AnalysisResult, Audience, GeneratedReport, ReviewResult


INTERNAL_ID_TERMS = (
    "source_id",
    "pending_source_ids",
    "inspection_history_id",
    "action_history_id",
    "event_id",
)


def _strip_internal_ids(value):
    if isinstance(value, list):
        return [_strip_internal_ids(item) for item in value]
    if isinstance(value, dict):
        blocked_keys = {
            "source_ids",
            "source_id",
            "inspection_history_ids",
            "inspection_history_id",
            "action_history_ids",
            "action_history_id",
            "event_ids",
            "event_id",
            "checklist_ids",
            "checklist_id",
            "pending_source_ids",
        }
        return {
            key: _strip_internal_ids(item)
            for key, item in value.items()
            if key not in blocked_keys
        }
    return value


def _report_visible_text(report) -> str:
    data = report.model_dump(mode="json") if hasattr(report, "model_dump") else dict(report or {})
    parts = [
        data.get("title") or "",
        data.get("period") or "",
        data.get("summary") or "",
        data.get("conclusion") or "",
    ]
    for section in data.get("sections") or []:
        parts.append(section.get("heading") or "")
        parts.append(section.get("content") or "")
    return "\n".join(str(part) for part in parts if part)


def _drop_false_internal_id_issues(review: ReviewResult, report) -> ReviewResult:
    visible_text = _report_visible_text(report)
    if any(term in visible_text for term in INTERNAL_ID_TERMS):
        return review

    filtered = []
    for issue in review.issues:
        text = " ".join([
            str(issue.category or ""),
            str(issue.message or ""),
            str(issue.recommendation if hasattr(issue, "recommendation") else ""),
        ])
        if any(term in text for term in INTERNAL_ID_TERMS):
            continue
        filtered.append(issue)

    review.issues = filtered
    review.revision_instructions = [
        instruction for instruction in review.revision_instructions
        if not any(term in instruction for term in INTERNAL_ID_TERMS)
    ]
    if not review.issues:
        review.passed = True
        review.score = max(review.score, 95)
    return review


async def management_review_analyze_agent(aggregated_data):
    llm = create_llm().with_structured_output(AnalysisResult)
    payload = {
        "audience": Audience.MANAGEMENT_RESPONSIBLE.value,
        "aggregated_data": _strip_internal_ids(aggregated_data),
    }
    return await llm.ainvoke(
        [
            SystemMessage(content=MANAGEMENT_REVIEW_ANALYSIS_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )


async def management_review_writer_agent(
    aggregated_data,
    analysis,
    previous=None,
    review=None,
):
    llm = create_llm().with_structured_output(GeneratedReport)
    payload = {
        "audience": Audience.MANAGEMENT_RESPONSIBLE.value,
        "aggregated_data": _strip_internal_ids(aggregated_data),
        "analysis_result": analysis.model_dump(mode="json"),
        "previous_report": previous.model_dump(mode="json") if previous else None,
        "review_result": review.model_dump(mode="json") if review else None,
    }
    return await llm.ainvoke(
        [
            SystemMessage(content=COMMON_REPORT_STYLE_GUIDE + "\n\n" + MANAGEMENT_REVIEW_WRITER_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )


async def management_review_review_agent(aggregated_data, analysis, report):
    llm = create_llm().with_structured_output(ReviewResult)
    payload = {
        "audience": Audience.MANAGEMENT_RESPONSIBLE.value,
        "aggregated_data": _strip_internal_ids(aggregated_data),
        "analysis_result": analysis.model_dump(mode="json"),
        "report": report.model_dump(mode="json"),
    }
    review = await llm.ainvoke(
        [
            SystemMessage(content=COMMON_REPORT_STYLE_GUIDE + "\n\n" + MANAGEMENT_REVIEW_REVIEW_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )
    return _drop_false_internal_id_issues(review, report)
