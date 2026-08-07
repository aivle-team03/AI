from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.management.correction import (
    PROTECTED_FIELDS,
    enforce_history_table_invariants,
    management_data_correction_agent,
    management_data_correction_review_agent,
)
from app.management.agents import (
    management_review_analyze_agent,
    management_review_review_agent,
    management_review_writer_agent,
)
from app.management.aggregation import aggregate_management_review_order_data
from app.management.state import ManagementReviewOrderState
from app.management.schemas import ReportSection, SectionCode, SiteAnomalyReportRequest
from scripts.build_final_history_table_14 import build_final_history_table_14


def retry_node(state):
    return {"retry_count": state.get("retry_count", 0) + 1}


def preprocessing_retry_node(state):
    return {"preprocessing_retry_count": state.get("preprocessing_retry_count", 0) + 1}


def reset_report_retry_node(state):
    return {"retry_count": 0}


def route(state) -> Literal["finish", "retry"]:
    review_passed = state["review_result"].passed
    retry_limit_reached = state.get("retry_count", 0) >= state.get("max_retry_count", 2)
    return "finish" if review_passed or retry_limit_reached else "retry"


def route_after_correction_review(state) -> Literal["route_report", "retry_preprocessing", "finish"]:
    review = state["correction_review"]
    if review.approved:
        return "route_report"
    if state.get("preprocessing_retry_count", 0) < state.get("max_retry_count", 2):
        return "retry_preprocessing"
    return "finish"


def build_final_history_table_node(state):
    request = state["request"]
    if getattr(request, "final_history_rows", None):
        return {
            "final_history_rows": [
                row.model_dump(mode="json") if hasattr(row, "model_dump") else row
                for row in request.final_history_rows
            ]
        }

    source_data = request.model_dump(mode="json")
    return {"final_history_rows": build_final_history_table_14(source_data)}


async def data_correction_node(state):
    raw_result = await management_data_correction_agent(
        state["final_history_rows"],
        protected_fields=PROTECTED_FIELDS,
        previous_result=state.get("correction_result"),
        review_result=state.get("correction_review"),
    )
    safe_result = enforce_history_table_invariants(
        state["final_history_rows"],
        raw_result,
        PROTECTED_FIELDS,
    )
    return {"correction_result": safe_result}


async def data_correction_review_node(state):
    review = await management_data_correction_review_agent(
        state["final_history_rows"],
        state["correction_result"],
    )
    return {"correction_review": review}


def _request_with_final_history_rows(state, request_cls):
    data = state["request"].model_dump(mode="json")
    data["final_history_rows"] = [
        row.model_dump(mode="json") if hasattr(row, "model_dump") else row
        for row in state["correction_result"].corrected_rows
    ]
    return request_cls(**data)


def management_review_aggregate_node(state):
    request = _request_with_final_history_rows(state, SiteAnomalyReportRequest)
    return {"aggregated_data": aggregate_management_review_order_data(request)}


async def management_review_analyze_node(state):
    return {"analysis_result": await management_review_analyze_agent(state["aggregated_data"])}


async def management_review_write_node(state):
    return {
        "generated_report": await management_review_writer_agent(
            state["aggregated_data"],
            state["analysis_result"],
            state.get("generated_report"),
            state.get("review_result"),
        )
    }


async def management_review_review_node(state):
    normalized_report = _normalize_management_review_order(
        state["generated_report"],
        state["aggregated_data"],
    )
    return {
        "generated_report": normalized_report,
        "review_result": await management_review_review_agent(
            state["aggregated_data"],
            state["analysis_result"],
            normalized_report,
        ),
    }


def _management_risk_label(candidate):
    score = candidate.get("max_risk_score")
    if isinstance(score, int):
        if score >= 4:
            return "CRITICAL"
        if score >= 3:
            return "HIGH"
        if score >= 2:
            return "MEDIUM"
        if score >= 1:
            return "LOW"
    return str(candidate.get("severity") or "UNKNOWN")


def _management_judgment(candidate):
    parts = []
    severity = str(candidate.get("severity") or "").upper()
    if severity == "HIGH":
        parts.append("경영책임자 우선 검토 필요")
    elif severity == "MEDIUM":
        parts.append("관리 수준 점검 필요")
    else:
        parts.append("정기 모니터링 필요")
    if candidate.get("pending_source_ids"):
        parts.append("미조치 또는 승인 대기 현황 확인 필요")
    if candidate.get("recurrence_after_action_count"):
        parts.append("조치 이후 동일 유형 기록 재확인 필요")
    if candidate.get("count", 0) >= 3:
        parts.append("반복 발생 관리 기준 보완 필요")
    return ", ".join(parts)


def _management_review_table(aggregated_data):
    rows = [
        "| 구역 | 반복 위험 유형 | 위험도 | 경영책임자 판단 |",
        "|---|---|---|---|",
    ]
    candidates = aggregated_data.get("anomaly_candidates") or []
    if not candidates:
        rows.append("| - | - | - | 반복 위험 후보 없음 |")
        return "\n".join(rows)

    for candidate in candidates[:10]:
        rows.append(
            "| {location} | {risk_type} | {risk} | {judgment} |".format(
                location=str(candidate.get("location") or "-"),
                risk_type=str(candidate.get("risk_type") or "-"),
                risk=_management_risk_label(candidate),
                judgment=_management_judgment(candidate),
            )
        )
    return "\n".join(rows)


def _find_section(report, code):
    for section in report.sections:
        if section.section_code == code or section.section_code.value == code.value:
            return section
    return None


def _clean_management_text(text):
    replacements = {
        "책임 소재 명확화": "관리 기준 보완 필요",
        "책임소재 명확화": "관리 기준 보완 필요",
        "책임 소재": "관리 기준",
        "원인 분석": "발생 경위 확인 필요",
        "원인분석": "발생 경위 확인 필요",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _normalize_management_review_order(report, aggregated_data):
    review_content = _find_section(report, SectionCode.MANAGEMENT_REVIEW_CONTENT)
    directives = _find_section(report, SectionCode.MANAGEMENT_DIRECTIVES)
    opinion = _find_section(report, SectionCode.OVERALL_OPINION)
    signoff = _find_section(report, SectionCode.APPROVAL_SIGNOFF)

    if review_content is None:
        review_content = ReportSection(
            section_code=SectionCode.MANAGEMENT_REVIEW_CONTENT,
            heading="경영책임자 검토내용",
            content="",
        )
    if directives is None:
        directives = ReportSection(
            section_code=SectionCode.MANAGEMENT_DIRECTIVES,
            heading="경영책임자 지시사항",
            content="",
        )
    if opinion is None:
        opinion = ReportSection(
            section_code=SectionCode.OVERALL_OPINION,
            heading="종합의견",
            content=report.conclusion or "검토 결과를 종합하여 후속 관리가 필요하다.",
        )
    if signoff is None:
        signoff = ReportSection(
            section_code=SectionCode.APPROVAL_SIGNOFF,
            heading="결재",
            content="",
        )

    summary_counts = aggregated_data.get("summary_counts") or {}
    detail = (
        "\n\n위 표는 동일 구역과 동일 위험 유형이 반복 기록된 후보를 기준으로 정리한 것이다. "
        f"반복 위험 그룹은 {summary_counts.get('repeated_risk_groups', 0)}건, "
        f"고위험 기록은 {summary_counts.get('high_risk_records', 0)}건, "
        f"미조치 또는 승인 대기 기록은 {summary_counts.get('pending_or_unapproved_records', 0)}건이다."
    )
    review_content.heading = "경영책임자 검토내용"
    review_content.content = _management_review_table(aggregated_data) + detail

    directives.heading = "경영책임자 지시사항"
    directives.content = _clean_management_text(directives.content or "")
    opinion.heading = "종합의견"
    opinion.content = _clean_management_text(opinion.content or report.conclusion or "")
    signoff.heading = "결재"
    signoff.content = "경영책임자: ______________________ / 검토일: ______________________ / 서명: ______________________"

    report.sections = [review_content, directives, opinion, signoff]
    report.summary = _clean_management_text(report.summary).replace("해야 한다", "할 것").replace("필요하다", "필요")
    report.conclusion = opinion.content
    report.title = "경영책임자 검토지시서"
    return report


def build_management_review_order_graph():
    graph = StateGraph(ManagementReviewOrderState)
    graph.add_node("build_final_history_table_14", build_final_history_table_node)
    graph.add_node("data_correction_agent", data_correction_node)
    graph.add_node("data_correction_review_agent", data_correction_review_node)
    graph.add_node("preprocessing_retry", preprocessing_retry_node)
    graph.add_node("reset_report_retry", reset_report_retry_node)
    graph.add_node("management_review_aggregation", management_review_aggregate_node)
    graph.add_node("management_review_analysis", management_review_analyze_node)
    graph.add_node("management_review_order_writer", management_review_write_node)
    graph.add_node("management_review_order_review", management_review_review_node)
    graph.add_node("management_review_retry", retry_node)

    graph.add_edge(START, "build_final_history_table_14")
    graph.add_edge("build_final_history_table_14", "data_correction_agent")
    graph.add_edge("data_correction_agent", "data_correction_review_agent")
    graph.add_conditional_edges(
        "data_correction_review_agent",
        route_after_correction_review,
        {
            "route_report": "reset_report_retry",
            "retry_preprocessing": "preprocessing_retry",
            "finish": END,
        },
    )
    graph.add_edge("preprocessing_retry", "data_correction_agent")
    graph.add_edge("reset_report_retry", "management_review_aggregation")
    graph.add_edge("management_review_aggregation", "management_review_analysis")
    graph.add_edge("management_review_analysis", "management_review_order_writer")
    graph.add_edge("management_review_order_writer", "management_review_order_review")
    graph.add_conditional_edges(
        "management_review_order_review",
        route,
        {"finish": END, "retry": "management_review_retry"},
    )
    graph.add_edge("management_review_retry", "management_review_order_writer")
    return graph.compile()


management_review_order_graph = build_management_review_order_graph()
