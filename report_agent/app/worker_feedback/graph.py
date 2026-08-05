from pathlib import Path
from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.worker_feedback.agents import (
    worker_feedback_correction_agent,
    worker_feedback_correction_review_agent,
)
from app.worker_feedback.correction import (
    PROTECTED_FIELDS as WORKER_FEEDBACK_PROTECTED_FIELDS,
)
from app.worker_feedback.correction import enforce_worker_feedback_invariants
from app.worker_feedback.state import WorkerFeedbackImprovementReportState
from app.worker_feedback.table_builder import build_worker_feedback_table
from app.worker_feedback.word_writer import (
    DEFAULT_OUTPUT_DIR as WORKER_FEEDBACK_WORD_OUTPUT_DIR,
)
from app.worker_feedback.word_writer import (
    DEFAULT_TEMPLATE_PATH as WORKER_FEEDBACK_WORD_TEMPLATE_PATH,
)
from app.worker_feedback.word_writer import fill_worker_feedback_word_reports


def retry_node(state):
    return {"retry_count": state.get("retry_count", 0) + 1}


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
) -> Literal["fill_word", "retry", "finish"]:
    review = state["correction_review"]
    if review.approved:
        return "fill_word"
    if state.get("retry_count", 0) < state.get("max_retry_count", 2):
        return "retry"
    return "finish"


def worker_feedback_word_node(state):
    request = state["request"]
    template_path = (
        Path(request.word_template_path)
        if request.word_template_path
        else WORKER_FEEDBACK_WORD_TEMPLATE_PATH
    )
    output_dir = (
        Path(request.word_output_dir)
        if request.word_output_dir
        else WORKER_FEEDBACK_WORD_OUTPUT_DIR
    )
    output_paths = fill_worker_feedback_word_reports(
        state["correction_result"].corrected_rows,
        template_path=template_path,
        output_dir=output_dir,
    )
    return {"word_output_paths": output_paths}


def build_worker_feedback_improvement_graph():
    graph = StateGraph(WorkerFeedbackImprovementReportState)
    graph.add_node("build_worker_feedback_table", worker_feedback_table_node)
    graph.add_node("worker_feedback_correction_agent", worker_feedback_correction_node)
    graph.add_node(
        "worker_feedback_correction_review_agent",
        worker_feedback_correction_review_node,
    )
    graph.add_node("retry", retry_node)
    graph.add_node("fill_worker_feedback_word", worker_feedback_word_node)

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
            "fill_word": "fill_worker_feedback_word",
            "retry": "retry",
            "finish": END,
        },
    )
    graph.add_edge("retry", "worker_feedback_correction_agent")
    graph.add_edge("fill_worker_feedback_word", END)
    return graph.compile()


worker_feedback_improvement_graph = build_worker_feedback_improvement_graph()
