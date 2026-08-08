import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import create_llm
from app.risk_assessment.prompts import (
    COMMON_REPORT_STYLE_GUIDE,
    RISK_ASSESSMENT_REPORT_ANALYSIS_PROMPT,
    RISK_ASSESSMENT_REPORT_REVIEW_PROMPT,
    RISK_ASSESSMENT_REPORT_WRITER_PROMPT,
)
from app.risk_assessment.schemas import AnalysisResult, Audience, GeneratedReport, ReviewResult


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
