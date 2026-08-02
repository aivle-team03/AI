from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.agents import (
    headquarters_analyze_agent,
    headquarters_review_agent,
    headquarters_writer_agent,
    site_anomaly_analyze_agent,
    site_anomaly_review_agent,
    site_anomaly_writer_agent,
)
from app.headquarters_aggregation import aggregate_headquarters_data
from app.site_anomaly_aggregation import aggregate_site_anomaly_data
from app.state import HeadquartersReportState, SiteAnomalyReportState


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


headquarters_full_graph = build_headquarters_full()
site_anomaly_full_graph = build_site_anomaly_full()
