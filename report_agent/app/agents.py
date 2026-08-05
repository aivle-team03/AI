import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import create_llm
from app.prompts import (
    HEADQUARTERS_DATA_ANALYSIS_PROMPT,
    HEADQUARTERS_REPORT_REVIEW_PROMPT,
    HEADQUARTERS_REPORT_WRITER_PROMPT,
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


async def headquarters_analyze_agent(aggregated_data):
    llm = create_llm().with_structured_output(AnalysisResult)
    payload = {
        "audience": Audience.HEADQUARTERS.value,
        "aggregated_data": aggregated_data,
    }
    return await llm.ainvoke(
        [
            SystemMessage(content=HEADQUARTERS_DATA_ANALYSIS_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )


async def headquarters_writer_agent(aggregated_data, analysis, previous=None, review=None):
    llm = create_llm().with_structured_output(GeneratedReport)
    payload = {
        "audience": Audience.HEADQUARTERS.value,
        "aggregated_data": aggregated_data,
        "analysis_result": analysis.model_dump(mode="json"),
        "previous_report": previous.model_dump(mode="json") if previous else None,
        "review_result": review.model_dump(mode="json") if review else None,
    }
    return await llm.ainvoke(
        [
            SystemMessage(content=HEADQUARTERS_REPORT_WRITER_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )


async def headquarters_review_agent(aggregated_data, analysis, report):
    llm = create_llm().with_structured_output(ReviewResult)
    payload = {
        "audience": Audience.HEADQUARTERS.value,
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
            SystemMessage(content=HEADQUARTERS_REPORT_REVIEW_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )


async def site_anomaly_analyze_agent(aggregated_data):
    llm = create_llm().with_structured_output(AnalysisResult)
    payload = {
        "audience": Audience.SITE_MANAGER.value,
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
        "audience": Audience.SITE_MANAGER.value,
        "aggregated_data": aggregated_data,
        "analysis_result": analysis.model_dump(mode="json"),
        "previous_report": previous.model_dump(mode="json") if previous else None,
        "review_result": review.model_dump(mode="json") if review else None,
    }
    return await llm.ainvoke(
        [
            SystemMessage(content=SITE_ANOMALY_REPORT_WRITER_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )


async def site_anomaly_review_agent(aggregated_data, analysis, report):
    llm = create_llm().with_structured_output(ReviewResult)
    payload = {
        "audience": Audience.SITE_MANAGER.value,
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
        "valid_inspection_history_ids": aggregated_data.get("source_ids", {}).get(
            "inspection_history_ids",
            [],
        ),
        "valid_checklist_ids": aggregated_data.get("source_ids", {}).get(
            "checklist_ids",
            [],
        ),
    }
    return await llm.ainvoke(
        [
            SystemMessage(content=SITE_ANOMALY_REPORT_REVIEW_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )


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
            SystemMessage(content=RISK_ASSESSMENT_REPORT_WRITER_PROMPT),
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
            SystemMessage(content=RISK_ASSESSMENT_REPORT_REVIEW_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )
