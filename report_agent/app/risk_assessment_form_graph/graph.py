from pathlib import Path
import json
import time
from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.common.Report_data import has_backend_table_data, save_backend_data
from app.risk_assessment_form_graph.correction import (
    PROTECTED_FIELDS,
    enforce_history_table_invariants,
    risk_form_data_correction_agent,
    risk_form_data_correction_review_agent,
)
from app.risk_assessment_form_graph.form_writer_word import (
    DEFAULT_FORM_PATH,
    DEFAULT_OUTPUT_PATH,
    fill_risk_assessment_form_docx,
)
from app.risk_assessment_form_graph.state import RiskAssessmentFormState
from app.risk_assessment_form_graph.schemas import (
    RiskDataCorrectionResult,
    RiskDataCorrectionReviewResult,
)
from scripts.build_final_history_table_14 import build_final_history_table_14

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DATA_OUTPUT_PATH = PROJECT_ROOT.parent / "output" / "risk_assessment_form" / "BackendData.json"


def _write_backend_data_snapshot(data):
    BACKEND_DATA_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with BACKEND_DATA_OUTPUT_PATH.open("w", encoding="utf-8-sig") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def retry_node(state):
    return {"retry_count": state.get("retry_count", 0) + 1}


def risk_assessment_backend_data_fetch_node(state):
    request = state["request"]
    request_data = request.model_dump(mode="json")
    if has_backend_table_data(request_data):
        _write_backend_data_snapshot(request_data)
        return {"backend_data": request_data}

    backend_data = save_backend_data(BACKEND_DATA_OUTPUT_PATH)
    return {
        "request": request.model_copy(update=backend_data),
        "backend_data": backend_data,
    }


def route_after_correction_review(state) -> Literal["finish", "retry"]:
    review_approved = state["correction_review"].approved
    retry_limit_reached = state.get("retry_count", 0) >= state.get("max_retry_count", 2)
    return "finish" if review_approved or retry_limit_reached else "retry"


def build_final_history_table_node(state):
    request = state["request"]
    if request.final_history_rows:
        return {
            "final_history_rows": [
                row.model_dump(mode="json") if hasattr(row, "model_dump") else row
                for row in request.final_history_rows
            ]
        }

    source_data = request.model_dump(mode="json")
    return {"final_history_rows": build_final_history_table_14(source_data)}


def _batch_rows(rows, batch_size):
    for start in range(0, len(rows), batch_size):
        yield start, rows[start:start + batch_size]


async def data_correction_node(state):
    rows = state["final_history_rows"]
    batch_size = state["request"].correction_batch_size
    total_batches = (len(rows) + batch_size - 1) // batch_size if rows else 0
    corrected_rows = []
    correction_notes = []
    unresolved_notes = []
    batch_count = 0

    for start, batch in _batch_rows(rows, batch_size):
        batch_count += 1
        print(
            f"[2/4] 데이터 수정 agent batch {batch_count}/{total_batches} 실행 중 "
            f"({start + 1}-{start + len(batch)}행)",
            flush=True,
        )
        batch_started_at = time.perf_counter()
        raw_result = await risk_form_data_correction_agent(
            batch,
            protected_fields=PROTECTED_FIELDS,
            previous_result=None,
            review_result=None,
        )
        print(
            f"[2/4] batch {batch_count}/{total_batches} LLM 호출 소요시간: "
            f"{time.perf_counter() - batch_started_at:.1f}초",
            flush=True,
        )
        safe_result = enforce_history_table_invariants(
            batch,
            raw_result,
            PROTECTED_FIELDS,
        )
        corrected_rows.extend(safe_result.corrected_rows)
        for note in safe_result.correction_notes:
            note.row_index += start
            correction_notes.append(note)
        unresolved_notes.extend(safe_result.unresolved_notes)

    return {
        "correction_result": RiskDataCorrectionResult(
            corrected_rows=corrected_rows,
            correction_notes=correction_notes,
            unresolved_notes=unresolved_notes,
        ),
        "correction_batch_size": batch_size,
        "correction_batch_count": batch_count,
    }


def _merge_review_results(results):
    issues = []
    items_requiring_revision = []
    for result in results:
        issues.extend(result.issues)
        items_requiring_revision.extend(result.items_requiring_revision)

    approved = all(result.approved for result in results)
    score = min((result.score for result in results), default=100)
    return RiskDataCorrectionReviewResult(
        approved=approved,
        final_decision="APPROVED" if approved else "REVISION_REQUIRED",
        score=score,
        issues=issues,
        items_requiring_revision=items_requiring_revision,
    )


async def data_correction_review_node(state):
    rows = state["final_history_rows"]
    corrected_rows = state["correction_result"].corrected_rows
    batch_size = state.get("correction_batch_size") or state["request"].correction_batch_size
    total_batches = (len(rows) + batch_size - 1) // batch_size if rows else 0
    review_results = []

    for batch_index, (start, batch) in enumerate(_batch_rows(rows, batch_size), start=1):
        print(
            f"[3/4] 데이터 검토 agent batch {batch_index}/{total_batches} 실행 중 "
            f"({start + 1}-{start + len(batch)}행)",
            flush=True,
        )
        corrected_batch = corrected_rows[start:start + len(batch)]
        correction_result = RiskDataCorrectionResult(
            corrected_rows=corrected_batch,
            correction_notes=[
                note.model_copy(update={"row_index": note.row_index - start})
                for note in state["correction_result"].correction_notes
                if note.row_index is not None and start <= note.row_index < start + len(batch)
            ],
            unresolved_notes=state["correction_result"].unresolved_notes,
        )
        batch_started_at = time.perf_counter()
        review = await risk_form_data_correction_review_agent(batch, correction_result)
        print(
            f"[3/4] batch {batch_index}/{total_batches} LLM 호출 소요시간: "
            f"{time.perf_counter() - batch_started_at:.1f}초",
            flush=True,
        )
        for issue in review.issues:
            if issue.row_index is not None:
                issue.row_index += start
        review.items_requiring_revision = [
            f"batch_start={start}: {item}" for item in review.items_requiring_revision
        ]
        review_results.append(review)

    review = _merge_review_results(review_results)
    return {"correction_review": review}


def risk_assessment_form_node(state):
    if state.get("skip_overall_docx"):
        return {"docx_output_path": None}

    request = state["request"]
    source_data = request.model_dump(mode="json")
    form_path = Path(request.form_path) if request.form_path else DEFAULT_FORM_PATH
    output_path = Path(request.output_path) if request.output_path else DEFAULT_OUTPUT_PATH
    docx_output_path = fill_risk_assessment_form_docx(
        source_data,
        state["correction_result"],
        form_path=form_path,
        output_path=output_path,
    )
    return {
        "docx_output_path": docx_output_path,
    }


def build_risk_assessment_form_graph():
    graph = StateGraph(RiskAssessmentFormState)
    graph.add_node("fetch_backend_data", risk_assessment_backend_data_fetch_node)
    graph.add_node("build_final_history_table_14", build_final_history_table_node)
    graph.add_node("data_correction_agent", data_correction_node)
    graph.add_node("data_correction_review_agent", data_correction_review_node)
    graph.add_node("retry", retry_node)
    graph.add_node("fill_csv_form", risk_assessment_form_node)

    graph.add_edge(START, "data_correction_agent")
    graph.add_edge("fetch_backend_data", "build_final_history_table_14")
    graph.add_edge("build_final_history_table_14", "data_correction_agent")
    graph.add_edge("data_correction_agent", "data_correction_review_agent")
    graph.add_conditional_edges(
        "data_correction_review_agent",
        route_after_correction_review,
        {"finish": "fill_csv_form", "retry": "retry"},
    )
    graph.add_edge("retry", "data_correction_agent")
    graph.add_edge("fill_csv_form", END)
    return graph.compile()


risk_assessment_form_graph = build_risk_assessment_form_graph()


