import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import create_llm
from app.prompts import (
    COMMON_REPORT_STYLE_GUIDE,
    SITE_ANOMALY_DATA_ANALYSIS_PROMPT,
    SITE_ANOMALY_REPORT_REVIEW_PROMPT,
    SITE_ANOMALY_REPORT_WRITER_PROMPT,
    RISK_DATA_CORRECTION_PROMPT,
    RISK_DATA_CORRECTION_REVIEW_PROMPT,
    RISK_ASSESSMENT_REPORT_ANALYSIS_PROMPT,
    RISK_ASSESSMENT_REPORT_REVIEW_PROMPT,
    RISK_ASSESSMENT_REPORT_WRITER_PROMPT,
)
from app.schemas import (
    AnalysisResult,
    Audience,
    GeneratedReport,
    ReviewResult,
    RiskDataCorrectionResult,
    RiskDataCorrectionReviewResult,
)


async def site_anomaly_analyze_agent(aggregated_data):
    llm = create_llm().with_structured_output(AnalysisResult)
    payload = {
        "audience": Audience.MANAGEMENT_RESPONSIBLE.value,
        "aggregated_data": aggregated_data,
    }
    return await llm.ainvoke(
        [
            SystemMessage(content=SITE_ANOMALY_DATA_ANALYSIS_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )


async def site_anomaly_writer_agent(
    aggregated_data,
    analysis,
    previous=None,
    review=None,
):
    llm = create_llm().with_structured_output(GeneratedReport)
    payload = {
        "audience": Audience.MANAGEMENT_RESPONSIBLE.value,
        "aggregated_data": aggregated_data,
        "analysis_result": analysis.model_dump(mode="json"),
        "previous_report": previous.model_dump(mode="json") if previous else None,
        "review_result": review.model_dump(mode="json") if review else None,
    }
    return await llm.ainvoke(
        [
            SystemMessage(content=COMMON_REPORT_STYLE_GUIDE + "\n\n" + SITE_ANOMALY_REPORT_WRITER_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )



INTERNAL_ID_TERMS = (
    "source_id",
    "pending_source_ids",
    "inspection_history_id",
    "action_history_id",
    "event_id",
)


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
async def site_anomaly_review_agent(aggregated_data, analysis, report):
    llm = create_llm().with_structured_output(ReviewResult)
    payload = {
        "audience": Audience.MANAGEMENT_RESPONSIBLE.value,
        "aggregated_data": _strip_internal_ids(aggregated_data),
        "analysis_result": analysis.model_dump(mode="json"),
        "report": report.model_dump(mode="json"),
        "valid_event_ids": aggregated_data.get("source_ids", {}).get("event_ids", []),
        "valid_inspection_history_ids": aggregated_data.get("source_ids", {}).get(
            "inspection_history_ids",
            [],
        ),
        "valid_action_history_ids": aggregated_data.get("source_ids", {}).get(
            "action_history_ids",
            [],
        ),
        "valid_inspection_history_ids": aggregated_data.get("source_ids", {}).get(
            "inspection_history_ids",
            [],
        ),
        "valid_checklist_ids": aggregated_data.get("source_ids", {}).get(
            "checklist_ids",
            [],
        ),
    }
    review = await llm.ainvoke(
        [
            SystemMessage(content=COMMON_REPORT_STYLE_GUIDE + "\n\n" + SITE_ANOMALY_REPORT_REVIEW_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )
    return _drop_false_internal_id_issues(review, report)


async def risk_data_correction_agent(
    rows,
    protected_fields=None,
    previous_result=None,
    review_result=None,
):
    llm = create_llm().with_structured_output(RiskDataCorrectionResult)
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
            SystemMessage(content=RISK_DATA_CORRECTION_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )

async def risk_data_correction_review_agent(original_rows, correction_result):
    llm = create_llm().with_structured_output(RiskDataCorrectionReviewResult)
    payload = {
        "original_rows": original_rows,
        "correction_result": correction_result.model_dump(mode="json"),
    }
    return await llm.ainvoke(
        [
            SystemMessage(content=RISK_DATA_CORRECTION_REVIEW_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )

async def risk_assessment_report_analyze_agent(aggregated_data):
    llm = create_llm().with_structured_output(AnalysisResult)
    payload = {
        "audience": Audience.RISK_ASSESSMENT_REPORT.value,
        "aggregated_data": aggregated_data,
    }
    return await llm.ainvoke(
        [
            SystemMessage(content=RISK_ASSESSMENT_REPORT_ANALYSIS_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )


async def risk_assessment_report_writer_agent(
    aggregated_data,
    analysis,
    previous=None,
    review=None,
):
    llm = create_llm().with_structured_output(GeneratedReport)
    payload = {
        "audience": Audience.RISK_ASSESSMENT_REPORT.value,
        "aggregated_data": aggregated_data,
        "analysis_result": analysis.model_dump(mode="json"),
        "previous_report": previous.model_dump(mode="json") if previous else None,
        "review_result": review.model_dump(mode="json") if review else None,
    }
    return await llm.ainvoke(
        [
            SystemMessage(content=COMMON_REPORT_STYLE_GUIDE + "\n\n" + RISK_ASSESSMENT_REPORT_WRITER_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )


async def risk_assessment_report_review_agent(aggregated_data, analysis, report):
    llm = create_llm().with_structured_output(ReviewResult)
    payload = {
        "audience": Audience.RISK_ASSESSMENT_REPORT.value,
        "aggregated_data": aggregated_data,
        "analysis_result": analysis.model_dump(mode="json"),
        "report": report.model_dump(mode="json"),
        "valid_event_ids": aggregated_data.get("source_ids", {}).get("event_ids", []),
        "valid_inspection_history_ids": aggregated_data.get("source_ids", {}).get(
            "inspection_history_ids",
            [],
        ),
        "valid_action_history_ids": aggregated_data.get("source_ids", {}).get(
            "action_history_ids",
            [],
        ),
    }
    return await llm.ainvoke(
        [
            SystemMessage(content=COMMON_REPORT_STYLE_GUIDE + "\n\n" + RISK_ASSESSMENT_REPORT_REVIEW_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )










