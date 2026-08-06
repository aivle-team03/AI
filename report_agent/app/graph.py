from pathlib import Path
from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.agents import (
    risk_data_correction_agent,
    risk_data_correction_review_agent,
    risk_assessment_report_analyze_agent,
    risk_assessment_report_review_agent,
    risk_assessment_report_writer_agent,
    site_anomaly_analyze_agent,
    site_anomaly_review_agent,
    site_anomaly_writer_agent,
)
from app.common.Report_data import build_backend_source_data, has_backend_table_data
from app.risk_assessment_form import DEFAULT_FORM_PATH, DEFAULT_OUTPUT_PATH
from app.risk_assessment_form import fill_risk_assessment_form, resolved_xlsx_path_for
from app.risk_assessment_report_aggregation import aggregate_risk_assessment_report_data
from app.risk_data_correction import PROTECTED_FIELDS, enforce_history_table_invariants
from app.site_anomaly_aggregation import aggregate_site_anomaly_data
from app.schemas import (
    ReportSection,
    RiskAssessmentReportRequest,
    SectionCode,
    SiteAnomalyReportRequest,
)
from app.state import (
    RiskAssessmentFormState,
    RiskAssessmentReportState,
    SiteAnomalyReportState,
    UnifiedReportState,
)
from scripts.build_final_history_table_14 import build_final_history_table_14


def retry_node(state):
    return {"retry_count": state.get("retry_count", 0) + 1}


def risk_assessment_backend_data_fetch_node(state):
    request = state["request"]
    request_data = request.model_dump(mode="json")
    if has_backend_table_data(request_data):
        return {"backend_data": request_data}

    backend_data = build_backend_source_data()
    return {
        "request": request.model_copy(update=backend_data),
        "backend_data": backend_data,
    }


def route(state) -> Literal["finish", "retry"]:
    review_passed = state["review_result"].passed
    retry_limit_reached = state.get("retry_count", 0) >= state.get("max_retry_count", 2)
    return "finish" if review_passed or retry_limit_reached else "retry"


def site_anomaly_aggregate_node(state):
    return {"aggregated_data": aggregate_site_anomaly_data(state["request"])}


async def site_anomaly_analyze_node(state):
    return {
        "analysis_result": await site_anomaly_analyze_agent(state["aggregated_data"])
    }


async def site_anomaly_write_node(state):
    return {
        "generated_report": await site_anomaly_writer_agent(
            state["aggregated_data"],
            state["analysis_result"],
            state.get("generated_report"),
            state.get("review_result"),
        )
    }


async def site_anomaly_review_node(state):
    normalized_report = _normalize_management_review_order(
        state["generated_report"],
        state["aggregated_data"],
    )
    return {
        "generated_report": normalized_report,
        "review_result": await site_anomaly_review_agent(
            state["aggregated_data"],
            state["analysis_result"],
            normalized_report,
        )
    }


def risk_assessment_table_node(state):
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


async def risk_data_correction_node(state):
    raw_result = await risk_data_correction_agent(
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


async def risk_data_correction_review_node(state):
    review = await risk_data_correction_review_agent(
        state["final_history_rows"],
        state["correction_result"],
    )
    return {"correction_review": review}


def route_after_correction_review(
    state,
) -> Literal["fill_form", "retry", "finish"]:
    review = state["correction_review"]
    if review.approved:
        return "fill_form"
    if state.get("retry_count", 0) < state.get("max_retry_count", 2):
        return "retry"
    return "finish"


def risk_assessment_form_node(state):
    request = state["request"]
    source_data = request.model_dump(mode="json")
    form_path = Path(request.form_path) if request.form_path else DEFAULT_FORM_PATH
    output_path = Path(request.output_path) if request.output_path else DEFAULT_OUTPUT_PATH
    csv_output_path = fill_risk_assessment_form(
        source_data,
        state["correction_result"],
        form_path=form_path,
        output_path=output_path,
    )
    return {"csv_output_path": csv_output_path, "xlsx_output_path": str(resolved_xlsx_path_for(csv_output_path))}




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




def _dedupe_stability_text(text: str, seen: set[str] | None = None) -> str:
    seen = seen if seen is not None else set()
    sentences = []
    for sentence in text.split(". "):
        normalized = " ".join(sentence.strip().split()).rstrip(".")
        if not normalized:
            continue
        is_stability_sentence = (
            "안정적인 추세" in normalized
            or "안정적" in normalized
            or "일별 및 주별" in normalized
            or "일별, 주별" in normalized
        )
        if is_stability_sentence:
            if normalized in seen:
                continue
            seen.add(normalized)
        sentences.append(sentence)
    return ". ".join(sentences)


def _risk_rate(value):
    return f"{value:.1f}%" if isinstance(value, float) else f"{value}%"


def _risk_summary_text(aggregated_data):
    kpi = aggregated_data.get("kpi") or {}
    total = kpi.get("assessment_records", 0)
    high_or_critical = kpi.get("high_or_critical_risk_records", 0)
    high_rate = _risk_rate(kpi.get("high_or_critical_risk_rate", 0))
    action_total = kpi.get("action_total", 0)
    action_rate = _risk_rate(kpi.get("action_completion_rate", 0))
    approval_completed = kpi.get("approval_completed", 0)
    approval_rate = _risk_rate(kpi.get("approval_completion_rate", 0))
    unaddressed = kpi.get("unaddressed_assessment_records", 0)
    unaddressed_high = kpi.get("unaddressed_high_risk_records", 0)
    return (
        f"평가기간 동안 총 {total}건의 위험성평가가 수행됐다. "
        f"고위험 및 중대위험 항목은 {high_or_critical}건으로 전체의 {high_rate}이다. "
        f"조치가 연결된 평가 항목은 {action_total}건이며, 전체 평가 항목 기준 조치 완료율은 {action_rate}이다. "
        f"승인 완료 평가 항목은 {approval_completed}건이며, 전체 평가 항목 기준 승인 완료율은 {approval_rate}이다. "
        f"미조치 평가 항목은 {unaddressed}건이고, 이 중 고위험 또는 중대위험 미조치 항목은 {unaddressed_high}건이다."
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
    unaddressed = kpi.get("unaddressed_assessment_records", 0)
    unaddressed_high = kpi.get("unaddressed_high_risk_records", 0)
    return (
        "위험도 분포는 "
        f"중대위험 {risk_counts.get('CRITICAL', 0)}건, "
        f"고위험 {risk_counts.get('HIGH', 0)}건, "
        f"중간위험 {risk_counts.get('MEDIUM', 0)}건, "
        f"저위험 {risk_counts.get('LOW', 0)}건으로 확인됐다. "
        f"고위험 및 중대위험 항목은 총 {high_or_critical}건으로 전체 평가 항목 {total}건의 {high_rate}를 차지했다. "
        f"조치가 연결된 평가 항목은 {action_total}건이며, 전체 평가 항목 기준 조치 완료율은 {action_rate}, 승인 완료율은 {approval_rate}이다. "
        f"미조치 평가 항목은 {unaddressed}건이고, 이 중 고위험 또는 중대위험 미조치 항목은 {unaddressed_high}건으로 확인됐다."
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
        f"조치가 연결된 평가 항목은 {kpi.get('action_total', 0)}건이며, "
        f"미조치 평가 항목은 {kpi.get('unaddressed_assessment_records', 0)}건으로 확인됐다. "
        f"특히 고위험 또는 중대위험 미조치 항목 {kpi.get('unaddressed_high_risk_records', 0)}건은 우선 관리 대상으로 분류된다. "
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
        f"미조치 또는 승인 대기 기록은 {summary_counts.get('pending_or_unapproved_records', 0)}건이다. "
       
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
async def risk_assessment_report_review_node(state):
    normalized_report = _normalize_risk_assessment_report(state["generated_report"], state["aggregated_data"])
    review_result = await risk_assessment_report_review_agent(
        state["aggregated_data"],
        state["analysis_result"],
        normalized_report,
    )
    return {
        "generated_report": normalized_report,
        "review_result": review_result,
    }

def build_site_anomaly_full():
    graph = StateGraph(SiteAnomalyReportState)
    graph.add_node("site_anomaly_aggregation", site_anomaly_aggregate_node)
    graph.add_node("detailed_anomaly_analysis_agent", site_anomaly_analyze_node)
    graph.add_node("management_review_order_writer_agent", site_anomaly_write_node)
    graph.add_node("management_order_review_agent", site_anomaly_review_node)
    graph.add_node("retry", retry_node)

    graph.add_edge(START, "site_anomaly_aggregation")
    graph.add_edge("site_anomaly_aggregation", "detailed_anomaly_analysis_agent")
    graph.add_edge("detailed_anomaly_analysis_agent", "management_review_order_writer_agent")
    graph.add_edge("management_review_order_writer_agent", "management_order_review_agent")
    graph.add_conditional_edges(
        "management_order_review_agent",
        route,
        {"finish": END, "retry": "retry"},
    )
    graph.add_edge("retry", "management_review_order_writer_agent")
    return graph.compile()


def build_risk_assessment_form_graph():
    graph = StateGraph(RiskAssessmentFormState)
    graph.add_node("fetch_backend_data", risk_assessment_backend_data_fetch_node)
    graph.add_node("build_final_history_table", risk_assessment_table_node)
    graph.add_node("data_correction_agent", risk_data_correction_node)
    graph.add_node("data_correction_review_agent", risk_data_correction_review_node)
    graph.add_node("retry", retry_node)
    graph.add_node("fill_csv_form", risk_assessment_form_node)

    graph.add_edge(START, "fetch_backend_data")
    graph.add_edge("fetch_backend_data", "build_final_history_table")
    graph.add_edge("build_final_history_table", "data_correction_agent")
    graph.add_edge("data_correction_agent", "data_correction_review_agent")
    graph.add_conditional_edges(
        "data_correction_review_agent",
        route_after_correction_review,
        {
            "fill_form": "fill_csv_form",
            "retry": "retry",
            "finish": END,
        },
    )
    graph.add_edge("retry", "data_correction_agent")
    graph.add_edge("fill_csv_form", END)
    return graph.compile()




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



def unified_preprocessing_retry_node(state):
    return {"preprocessing_retry_count": state.get("preprocessing_retry_count", 0) + 1}


def reset_report_retry_node(state):
    return {"retry_count": 0}


def route_after_unified_correction_review(
    state,
) -> Literal["route_report", "retry_preprocessing", "finish"]:
    review = state["correction_review"]
    if review.approved:
        return "route_report"
    if state.get("preprocessing_retry_count", 0) < state.get("max_retry_count", 2):
        return "retry_preprocessing"
    return "finish"


def route_unified_report_type(
    state,
) -> Literal[
    "risk_assessment_form",
    "risk_assessment_report",
    "site_anomaly_improvement",
    "management_review_order",
]:
    report_type = state["request"].report_type
    if report_type == "site_anomaly_improvement":
        return "management_review_order"
    return report_type


def unified_report_router_node(state):
    return {}


def _request_with_corrected_rows(state, request_cls):
    data = state["request"].model_dump(mode="json")
    data["corrected_rows"] = [
        row.model_dump(mode="json") if hasattr(row, "model_dump") else row
        for row in state["correction_result"].corrected_rows
    ]
    return request_cls(**data)


def _request_with_final_history_rows(state, request_cls):
    data = state["request"].model_dump(mode="json")
    data["final_history_rows"] = [
        row.model_dump(mode="json") if hasattr(row, "model_dump") else row
        for row in state["correction_result"].corrected_rows
    ]
    return request_cls(**data)


def unified_risk_assessment_form_node(state):
    request = state["request"]
    source_data = request.model_dump(mode="json")
    form_path = Path(request.form_path) if request.form_path else DEFAULT_FORM_PATH
    output_path = Path(request.output_path) if request.output_path else DEFAULT_OUTPUT_PATH
    csv_output_path = fill_risk_assessment_form(
        source_data,
        state["correction_result"],
        form_path=form_path,
        output_path=output_path,
    )
    return {
        "csv_output_path": csv_output_path,
        "xlsx_output_path": str(resolved_xlsx_path_for(csv_output_path)),
    }


def unified_risk_assessment_report_aggregate_node(state):
    request = _request_with_final_history_rows(state, RiskAssessmentReportRequest)
    return {"aggregated_data": aggregate_risk_assessment_report_data(request)}


def unified_site_anomaly_aggregate_node(state):
    request = _request_with_final_history_rows(state, SiteAnomalyReportRequest)
    return {"aggregated_data": aggregate_site_anomaly_data(request)}


async def unified_site_anomaly_analyze_node(state):
    return {"analysis_result": await site_anomaly_analyze_agent(state["aggregated_data"])}


async def unified_site_anomaly_write_node(state):
    return {
        "generated_report": await site_anomaly_writer_agent(
            state["aggregated_data"],
            state["analysis_result"],
            state.get("generated_report"),
            state.get("review_result"),
        )
    }


async def unified_site_anomaly_review_node(state):
    normalized_report = _normalize_management_review_order(
        state["generated_report"],
        state["aggregated_data"],
    )
    return {
        "generated_report": normalized_report,
        "review_result": await site_anomaly_review_agent(
            state["aggregated_data"],
            state["analysis_result"],
            normalized_report,
        )
    }


async def unified_risk_assessment_report_analyze_node(state):
    return {
        "analysis_result": await risk_assessment_report_analyze_agent(
            state["aggregated_data"]
        )
    }


async def unified_risk_assessment_report_write_node(state):
    return {
        "generated_report": await risk_assessment_report_writer_agent(
            state["aggregated_data"],
            state["analysis_result"],
            state.get("generated_report"),
            state.get("review_result"),
        )
    }


async def unified_risk_assessment_report_review_node(state):
    normalized_report = _normalize_risk_assessment_report(state["generated_report"], state["aggregated_data"])
    review_result = await risk_assessment_report_review_agent(
        state["aggregated_data"],
        state["analysis_result"],
        normalized_report,
    )
    return {
        "generated_report": normalized_report,
        "review_result": review_result,
    }


def build_unified_report_graph():
    graph = StateGraph(UnifiedReportState)
    graph.add_node("build_final_history_table", risk_assessment_table_node)
    graph.add_node("data_correction_agent", risk_data_correction_node)
    graph.add_node("data_correction_review_agent", risk_data_correction_review_node)
    graph.add_node("preprocessing_retry", unified_preprocessing_retry_node)
    graph.add_node("reset_report_retry", reset_report_retry_node)
    graph.add_node("report_router", unified_report_router_node)

    graph.add_node("risk_assessment_form", unified_risk_assessment_form_node)

    graph.add_node("risk_assessment_report_aggregation", unified_risk_assessment_report_aggregate_node)
    graph.add_node("risk_assessment_report_analysis", unified_risk_assessment_report_analyze_node)
    graph.add_node("risk_assessment_report_writer", unified_risk_assessment_report_write_node)
    graph.add_node("risk_assessment_report_review", unified_risk_assessment_report_review_node)
    graph.add_node("risk_assessment_report_retry", retry_node)

    graph.add_node("site_anomaly_aggregation", unified_site_anomaly_aggregate_node)
    graph.add_node("management_anomaly_analysis", unified_site_anomaly_analyze_node)
    graph.add_node("management_review_order_writer", unified_site_anomaly_write_node)
    graph.add_node("management_review_order_review", unified_site_anomaly_review_node)
    graph.add_node("site_anomaly_retry", retry_node)

    graph.add_edge(START, "build_final_history_table")
    graph.add_edge("build_final_history_table", "data_correction_agent")
    graph.add_edge("data_correction_agent", "data_correction_review_agent")
    graph.add_conditional_edges(
        "data_correction_review_agent",
        route_after_unified_correction_review,
        {
            "route_report": "reset_report_retry",
            "retry_preprocessing": "preprocessing_retry",
            "finish": END,
        },
    )
    graph.add_edge("preprocessing_retry", "data_correction_agent")
    graph.add_edge("reset_report_retry", "report_router")
    graph.add_conditional_edges(
        "report_router",
        route_unified_report_type,
        {
            "risk_assessment_form": "risk_assessment_form",
            "risk_assessment_report": "risk_assessment_report_aggregation",
            "site_anomaly_improvement": "site_anomaly_aggregation",
            "management_review_order": "site_anomaly_aggregation",
        },
    )

    graph.add_edge("risk_assessment_form", END)

    graph.add_edge("risk_assessment_report_aggregation", "risk_assessment_report_analysis")
    graph.add_edge("risk_assessment_report_analysis", "risk_assessment_report_writer")
    graph.add_edge("risk_assessment_report_writer", "risk_assessment_report_review")
    graph.add_conditional_edges(
        "risk_assessment_report_review",
        route,
        {"finish": END, "retry": "risk_assessment_report_retry"},
    )
    graph.add_edge("risk_assessment_report_retry", "risk_assessment_report_writer")

    graph.add_edge("site_anomaly_aggregation", "management_anomaly_analysis")
    graph.add_edge("management_anomaly_analysis", "management_review_order_writer")
    graph.add_edge("management_review_order_writer", "management_review_order_review")
    graph.add_conditional_edges(
        "management_review_order_review",
        route,
        {"finish": END, "retry": "site_anomaly_retry"},
    )
    graph.add_edge("site_anomaly_retry", "management_review_order_writer")

    return graph.compile()

site_anomaly_full_graph = build_site_anomaly_full()
risk_assessment_form_graph = build_risk_assessment_form_graph()
risk_assessment_report_graph = build_risk_assessment_report_graph()
unified_report_graph = build_unified_report_graph()























