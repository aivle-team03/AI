from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.risk_assessment.agents import (
    risk_assessment_report_analyze_agent,
    risk_assessment_report_review_agent,
    risk_assessment_report_writer_agent,
)
from app.risk_assessment.aggregation import aggregate_risk_assessment_report_data
from app.risk_assessment.state import RiskAssessmentReportState
from app.risk_assessment.schemas import ReportSection, SectionCode
from scripts.build_final_history_table_14 import build_final_history_table_14


def retry_node(state):
    return {"retry_count": state.get("retry_count", 0) + 1}


def route(state) -> Literal["finish", "retry"]:
    review_passed = state["review_result"].passed
    retry_limit_reached = state.get("retry_count", 0) >= state.get("max_retry_count", 2)
    return "finish" if review_passed or retry_limit_reached else "retry"


def risk_assessment_report_aggregate_node(state):
    request = state["request"]
    if not request.final_history_rows:
        final_history_rows = build_final_history_table_14(request.model_dump(mode="json"))
        request = request.model_copy(update={"final_history_rows": final_history_rows})
        return {
            "request": request,
            "final_history_rows": final_history_rows,
            "aggregated_data": aggregate_risk_assessment_report_data(request),
        }

    return {
        "final_history_rows": [
            row.model_dump(mode="json") if hasattr(row, "model_dump") else row
            for row in request.final_history_rows
        ],
        "aggregated_data": aggregate_risk_assessment_report_data(request),
    }


async def risk_assessment_report_analyze_node(state):
    return {
        "analysis_result": await risk_assessment_report_analyze_agent(
            state["aggregated_data"]
        )
    }


async def risk_assessment_report_write_node(state):
    return {
        "generated_report": await risk_assessment_report_writer_agent(
            state["aggregated_data"],
            state["analysis_result"],
            state.get("generated_report"),
            state.get("review_result"),
        )
    }


def _risk_rate(value):
    return f"{value:.1f}%" if isinstance(value, float) else f"{value}%"


def _risk_summary_text(aggregated_data):
    kpi = aggregated_data.get("kpi") or {}
    total = kpi.get("assessment_records", 0)
    high_or_critical = kpi.get("high_or_critical_risk_records", 0)
    high_rate = _risk_rate(kpi.get("high_or_critical_risk_rate", 0))
    action_total = kpi.get("action_total", 0)
    action_rate = _risk_rate(kpi.get("action_completion_rate", 0))
    approval_rate = _risk_rate(kpi.get("approval_completion_rate", 0))
    risk_recurrence_rate = kpi.get("risk_recurrence_rate", 0)
    board_action_history_rate=kpi.get("board_action_history_rate",0)
    cctv_action_history_rate=kpi.get("cctv_action_history_rate",0)

    return (
        f"평가기간 동안 총 {total}건의 위험성평가가 수행됐다. "
        f"고위험 및 중대위험 항목은 {high_or_critical}건으로 전체의 {high_rate}이다. "
        f"조치가 연결된 평가 항목은 {action_total}건이며, 전체 평가 항목 기준 조치 완료율은 {action_rate}이다. "
        f"종사자가 신고하여 위험요인을 추가한 항목은 전체 중 {board_action_history_rate}% 이며, CCTV가 감지한 항목은 전체의 {cctv_action_history_rate}이다. "
        f"재발 항목률 {risk_recurrence_rate}% 이다."
    )


def _risk_management_status_text(aggregated_data):
    risk_counts = (aggregated_data.get("risk_distribution") or {}).get("risk_band_counts") or {}
    kpi = aggregated_data.get("kpi") or {}
    total = kpi.get("assessment_records", 0)
    high_or_critical = kpi.get("high_or_critical_risk_records", 0)
    high_rate = _risk_rate(kpi.get("high_or_critical_risk_rate", 0))
    action_total = kpi.get("action_total", 0)
    action_rate = _risk_rate(kpi.get("action_completion_rate", 0))
    approval_rate = _risk_rate(kpi.get("approval_completion_rate", 0))
    risk_recurrence_rate = kpi.get("risk_recurrence_rate", 0)
    return (
        "위험도 분포는 "
        f"중대위험 {risk_counts.get('CRITICAL', 0)}건, "
        f"고위험 {risk_counts.get('HIGH', 0)}건, "
        f"중간위험 {risk_counts.get('MEDIUM', 0)}건, "
        f"저위험 {risk_counts.get('LOW', 0)}건으로 확인됐다. "
        f"고위험 및 중대위험 항목은 총 {high_or_critical}건으로 전체 평가 항목 {total}건의 {high_rate}를 차지했다. "
        f"조치가 연결된 평가 항목은 {action_total}건이며, 승인 완료율은 {approval_rate}이다. "
        f"재발 항목률 {risk_recurrence_rate}% 이다."
    )


def _risk_high_items_text(aggregated_data):
    items = aggregated_data.get("high_risk_items") or []
    if not items:
        return "주요 고위험 항목은 확인되지 않았다."
    lines = []
    for idx, item in enumerate(items[:10], start=1):
        action_state = "조치 완료" if item.get("action_completed") else "미조치"
        approval_state = "승인 완료" if item.get("approval_completed") else "승인 미완료"
        lines.append(
            f"{idx}. 위치: {item.get('location') or '-'}, "
            f"위험유형: {item.get('category_name') or '-'}, "
            f"위험도: {item.get('risk_band') or item.get('risk') or '-'}, "
            f"조치 상태: {action_state}, 승인 상태: {approval_state}\n"
            f"- 점검 내용: {item.get('inspection_content') or '-'}\n"
            f"- 조치 내용: {item.get('action_content') or '-'}"
        )
    return "\n\n".join(lines)


def _risk_conclusion_text(aggregated_data):
    kpi = aggregated_data.get("kpi") or {}
    return (
        f"위험성평가 결과 총 {kpi.get('assessment_records', 0)}건 중 "
        f"{kpi.get('high_or_critical_risk_records', 0)}건이 고위험 또는 중대위험으로 분류됐다. "
        f"조치가 연결된 평가 항목은 {kpi.get('action_total', 0)}건이다. "
        f"특히 동일 항목에 대한 재현율은 {kpi.get('risk_recurrence_rate', 0)}%로 해당 항목은 우선 관리 대상으로 분류된다. "
        "본 보고서는 위험도 분포, 관리 현황, 주요 고위험 항목을 기준으로 사업장 위험성평가 결과를 종합한 것이다."
    )


def _normalize_risk_assessment_report(report, aggregated_data):
    section_by_code = {section.section_code.value: section for section in report.sections}

    summary_section = section_by_code.get("EXECUTIVE_SUMMARY") or ReportSection(
        section_code=SectionCode.EXECUTIVE_SUMMARY,
        heading="요약",
        content="",
    )
    distribution_section = section_by_code.get("RISK_DISTRIBUTION") or ReportSection(
        section_code=SectionCode.RISK_DISTRIBUTION,
        heading="위험도 분포 및 관리 현황",
        content="",
    )
    high_items_section = section_by_code.get("HIGH_RISK_ITEMS") or ReportSection(
        section_code=SectionCode.HIGH_RISK_ITEMS,
        heading="주요 고위험 항목",
        content="",
    )

    report.summary = _risk_summary_text(aggregated_data)
    summary_section.heading = "요약"
    summary_section.content = report.summary
    distribution_section.heading = "위험도 분포 및 관리 현황"
    distribution_section.content = _risk_management_status_text(aggregated_data)
    high_items_section.heading = "주요 고위험 항목"
    high_items_section.content = _risk_high_items_text(aggregated_data)
    report.conclusion = _risk_conclusion_text(aggregated_data)
    report.sections = [summary_section, distribution_section, high_items_section]
    return report


async def risk_assessment_report_review_node(state):
    normalized_report = _normalize_risk_assessment_report(
        state["generated_report"],
        state["aggregated_data"],
    )
    review_result = await risk_assessment_report_review_agent(
        state["aggregated_data"],
        state["analysis_result"],
        normalized_report,
    )
    return {
        "generated_report": normalized_report,
        "review_result": review_result,
    }


def build_risk_assessment_report_graph():
    graph = StateGraph(RiskAssessmentReportState)
    graph.add_node("risk_assessment_report_aggregation", risk_assessment_report_aggregate_node)
    graph.add_node("risk_kpi_trend_analysis_agent", risk_assessment_report_analyze_node)
    graph.add_node("risk_assessment_report_writer_agent", risk_assessment_report_write_node)
    graph.add_node("risk_assessment_report_review_agent", risk_assessment_report_review_node)
    graph.add_node("retry", retry_node)

    graph.add_edge(START, "risk_assessment_report_aggregation")
    graph.add_edge("risk_assessment_report_aggregation", "risk_kpi_trend_analysis_agent")
    graph.add_edge("risk_kpi_trend_analysis_agent", "risk_assessment_report_writer_agent")
    graph.add_edge("risk_assessment_report_writer_agent", "risk_assessment_report_review_agent")
    graph.add_conditional_edges(
        "risk_assessment_report_review_agent",
        route,
        {"finish": END, "retry": "retry"},
    )
    graph.add_edge("retry", "risk_assessment_report_writer_agent")
    return graph.compile()


risk_assessment_report_graph = build_risk_assessment_report_graph()
