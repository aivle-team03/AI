from pathlib import Path
from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.agents import (
    headquarters_analyze_agent,
    headquarters_review_agent,
    headquarters_writer_agent,
    risk_data_correction_agent,
    risk_data_correction_review_agent,
    site_anomaly_analyze_agent,
    site_anomaly_review_agent,
    site_anomaly_writer_agent,
    worker_feedback_correction_agent,
    worker_feedback_correction_review_agent,
)
from app.build_worker_feedback_table import build_worker_feedback_table
from app.headquarters_aggregation import aggregate_headquarters_data
from app.risk_assessment_form import DEFAULT_FORM_PATH, DEFAULT_OUTPUT_PATH
from app.risk_assessment_form import fill_risk_assessment_form
from app.risk_data_correction import PROTECTED_FIELDS, enforce_history_table_invariants
from app.site_anomaly_aggregation import aggregate_site_anomaly_data
from app.state import (
    HeadquartersReportState,
    RiskAssessmentFormState,
    SiteAnomalyReportState,
    WorkerFeedbackImprovementReportState,
)
from app.worker_feedback_correction import (
    PROTECTED_FIELDS as WORKER_FEEDBACK_PROTECTED_FIELDS,
)
from app.worker_feedback_correction import enforce_worker_feedback_invariants
from app.worker_feedback_excel import (
    DEFAULT_OUTPUT_DIR as WORKER_FEEDBACK_EXCEL_OUTPUT_DIR,
)
from app.worker_feedback_excel import (
    DEFAULT_TEMPLATE_PATH as WORKER_FEEDBACK_EXCEL_TEMPLATE_PATH,
)
from app.worker_feedback_excel import fill_worker_feedback_excel_reports
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
    return {"csv_output_path": csv_output_path}


def worker_feedback_table_node(state):
    source_data = state["request"].model_dump(mode="json")
    return {"worker_feedback_rows": build_worker_feedback_table(source_data)}


async def worker_feedback_correction_node(state):
    raw_result = await worker_feedback_correction_agent(
        state["worker_feedback_rows"],
        protected_fields=WORKER_FEEDBACK_PROTECTED_FIELDS,
        previous_result=state.get("correction_result"),
        review_result=state.get("correction_review"),
    )
    safe_result = enforce_worker_feedback_invariants(
        state["worker_feedback_rows"],
        raw_result,
        WORKER_FEEDBACK_PROTECTED_FIELDS,
    )
    return {"correction_result": safe_result}


async def worker_feedback_correction_review_node(state):
    review = await worker_feedback_correction_review_agent(
        state["worker_feedback_rows"],
        state["correction_result"],
        protected_fields=WORKER_FEEDBACK_PROTECTED_FIELDS,
    )
    return {"correction_review": review}


def route_after_worker_feedback_review(
    state,
) -> Literal["fill_excel", "retry", "finish"]:
    review = state["correction_review"]
    if review.approved:
        return "fill_excel"
    if state.get("retry_count", 0) < state.get("max_retry_count", 2):
        return "retry"
    return "finish"


def worker_feedback_excel_node(state):
    request = state["request"]
    template_path = (
        Path(request.excel_template_path)
        if request.excel_template_path
        else WORKER_FEEDBACK_EXCEL_TEMPLATE_PATH
    )
    output_dir = (
        Path(request.excel_output_dir)
        if request.excel_output_dir
        else WORKER_FEEDBACK_EXCEL_OUTPUT_DIR
    )
    output_paths = fill_worker_feedback_excel_reports(
        state["correction_result"].corrected_rows,
        template_path=template_path,
        output_dir=output_dir,
    )
    return {"excel_output_paths": output_paths}


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


def build_worker_feedback_improvement_graph():
    graph = StateGraph(WorkerFeedbackImprovementReportState)
    graph.add_node("build_worker_feedback_table", worker_feedback_table_node)
    graph.add_node("worker_feedback_correction_agent", worker_feedback_correction_node)
    graph.add_node(
        "worker_feedback_correction_review_agent",
        worker_feedback_correction_review_node,
    )
    graph.add_node("retry", retry_node)
    graph.add_node("fill_worker_feedback_excel", worker_feedback_excel_node)

    graph.add_edge(START, "build_worker_feedback_table")
    graph.add_edge("build_worker_feedback_table", "worker_feedback_correction_agent")
    graph.add_edge(
        "worker_feedback_correction_agent",
        "worker_feedback_correction_review_agent",
    )
    graph.add_conditional_edges(
        "worker_feedback_correction_review_agent",
        route_after_worker_feedback_review,
        {
            "fill_excel": "fill_worker_feedback_excel",
            "retry": "retry",
            "finish": END,
        },
    )
    graph.add_edge("retry", "worker_feedback_correction_agent")
    graph.add_edge("fill_worker_feedback_excel", END)
    return graph.compile()


headquarters_full_graph = build_headquarters_full()
site_anomaly_full_graph = build_site_anomaly_full()
risk_assessment_form_graph = build_risk_assessment_form_graph()
worker_feedback_improvement_graph = build_worker_feedback_improvement_graph()
