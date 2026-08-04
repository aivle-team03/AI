from pathlib import Path
from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.agents import (
    headquarters_analyze_agent,
    headquarters_review_agent,
    headquarters_writer_agent,
    risk_data_correction_agent,
    risk_data_correction_review_agent,
    risk_assessment_report_analyze_agent,
    risk_assessment_report_review_agent,
    risk_assessment_report_writer_agent,
    site_anomaly_analyze_agent,
    site_anomaly_review_agent,
    site_anomaly_writer_agent,
)
from app.headquarters_aggregation import aggregate_headquarters_data
from app.risk_assessment_form import DEFAULT_FORM_PATH, DEFAULT_OUTPUT_PATH
from app.risk_assessment_form import fill_risk_assessment_form, resolved_xlsx_path_for
from app.risk_assessment_report_aggregation import aggregate_risk_assessment_report_data
from app.risk_data_correction import PROTECTED_FIELDS, enforce_history_table_invariants
from app.site_anomaly_aggregation import aggregate_site_anomaly_data
from app.state import (
    HeadquartersReportState,
    RiskAssessmentFormState,
    RiskAssessmentReportState,
    SiteAnomalyReportState,
)
from scripts.build_final_history_table import build_final_history_table


def retry_node(state):
    return {"retry_count": state.get("retry_count", 0) + 1}


def route(state) -> Literal["finish", "retry"]:
    review_passed = state["review_result"].passed
    retry_limit_reached = state.get("retry_count", 0) >= state.get("max_retry_count", 2)
    return "finish" if review_passed or retry_limit_reached else "retry"


def headquarters_aggregate_node(state):
    return {"aggregated_data": aggregate_headquarters_data(state["request"])}


async def headquarters_analyze_node(state):
    return {
        "analysis_result": await headquarters_analyze_agent(state["aggregated_data"])
    }


async def headquarters_write_node(state):
    return {
        "generated_report": await headquarters_writer_agent(
            state["aggregated_data"],
            state["analysis_result"],
            state.get("generated_report"),
            state.get("review_result"),
        )
    }


async def headquarters_review_node(state):
    return {
        "review_result": await headquarters_review_agent(
            state["aggregated_data"],
            state["analysis_result"],
            state["generated_report"],
        )
    }


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
    return {
        "review_result": await site_anomaly_review_agent(
            state["aggregated_data"],
            state["analysis_result"],
            state["generated_report"],
        )
    }


def risk_assessment_table_node(state):
    source_data = state["request"].model_dump(mode="json")
    return {"final_history_rows": build_final_history_table(source_data)}


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
    return {"aggregated_data": aggregate_risk_assessment_report_data(state["request"])}


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


def _normalize_risk_assessment_report(report):
    allowed = [
        ("EXECUTIVE_SUMMARY", "요약"),
        ("RISK_DISTRIBUTION", "위험도 분포 및 평가 추세"),
        ("HIGH_RISK_ITEMS", "주요 고위험 항목"),
    ]
    allowed_codes = {code for code, _ in allowed}
    section_by_code = {section.section_code.value: section for section in report.sections}

    summary_parts = []
    kpi_section = section_by_code.get("KPI")
    executive_section = section_by_code.get("EXECUTIVE_SUMMARY")
    if executive_section:
        summary_parts.append(executive_section.content)
    if kpi_section:
        summary_parts.append(kpi_section.content)

    normalized_sections = []
    seen_stability_sentences: set[str] = set()
    for code, heading in allowed:
        section = section_by_code.get(code)
        if not section:
            continue
        if code == "EXECUTIVE_SUMMARY" and summary_parts:
            section.content = "\n\n".join(summary_parts)
        section.heading = heading
        section.content = _dedupe_stability_text(section.content, seen_stability_sentences)
        normalized_sections.append(section)

    report.conclusion = _dedupe_stability_text(report.conclusion, seen_stability_sentences)
    report.sections = [
        section for section in normalized_sections
        if section.section_code.value in allowed_codes
    ]
    return report

async def risk_assessment_report_review_node(state):
    normalized_report = _normalize_risk_assessment_report(state["generated_report"])
    review_result = await risk_assessment_report_review_agent(
        state["aggregated_data"],
        state["analysis_result"],
        normalized_report,
    )
    return {
        "generated_report": normalized_report,
        "review_result": review_result,
    }

def build_headquarters_full():
    graph = StateGraph(HeadquartersReportState)
    graph.add_node("headquarters_aggregation", headquarters_aggregate_node)
    graph.add_node("data_analysis_agent", headquarters_analyze_node)
    graph.add_node("report_writer_agent", headquarters_write_node)
    graph.add_node("report_review_agent", headquarters_review_node)
    graph.add_node("retry", retry_node)

    graph.add_edge(START, "headquarters_aggregation")
    graph.add_edge("headquarters_aggregation", "data_analysis_agent")
    graph.add_edge("data_analysis_agent", "report_writer_agent")
    graph.add_edge("report_writer_agent", "report_review_agent")
    graph.add_conditional_edges(
        "report_review_agent",
        route,
        {"finish": END, "retry": "retry"},
    )
    graph.add_edge("retry", "report_writer_agent")
    return graph.compile()


def build_site_anomaly_full():
    graph = StateGraph(SiteAnomalyReportState)
    graph.add_node("site_anomaly_aggregation", site_anomaly_aggregate_node)
    graph.add_node("anomaly_analysis_agent", site_anomaly_analyze_node)
    graph.add_node("improvement_writer_agent", site_anomaly_write_node)
    graph.add_node("site_manager_review_agent", site_anomaly_review_node)
    graph.add_node("retry", retry_node)

    graph.add_edge(START, "site_anomaly_aggregation")
    graph.add_edge("site_anomaly_aggregation", "anomaly_analysis_agent")
    graph.add_edge("anomaly_analysis_agent", "improvement_writer_agent")
    graph.add_edge("improvement_writer_agent", "site_manager_review_agent")
    graph.add_conditional_edges(
        "site_manager_review_agent",
        route,
        {"finish": END, "retry": "retry"},
    )
    graph.add_edge("retry", "improvement_writer_agent")
    return graph.compile()


def build_risk_assessment_form_graph():
    graph = StateGraph(RiskAssessmentFormState)
    graph.add_node("build_final_history_table", risk_assessment_table_node)
    graph.add_node("data_correction_agent", risk_data_correction_node)
    graph.add_node("data_correction_review_agent", risk_data_correction_review_node)
    graph.add_node("retry", retry_node)
    graph.add_node("fill_csv_form", risk_assessment_form_node)

    graph.add_edge(START, "build_final_history_table")
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

headquarters_full_graph = build_headquarters_full()
site_anomaly_full_graph = build_site_anomaly_full()
risk_assessment_form_graph = build_risk_assessment_form_graph()
risk_assessment_report_graph = build_risk_assessment_report_graph()






