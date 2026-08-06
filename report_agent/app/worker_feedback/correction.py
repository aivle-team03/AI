from typing import Any

from app.worker_feedback.schemas import (
    WorkerFeedbackCorrectionNote,
    WorkerFeedbackCorrectionResult,
    WorkerFeedbackRow,
)

PROTECTED_FIELDS = [
    "category",
    "risk",
    "category_name",
    "user",
    "board_writer",
    "board_created_at",
    "status",
    "board_image_url",
    "location",
    "completed_at",
    "action_status",
    "handler_name",
    "image_url",
    "approver_name",
    "source_type",
]

TEXT_FIELDS = [
    "board_contents",
    "action_name",
    "content",
]


def _row_to_dict(row: WorkerFeedbackRow | dict[str, Any]) -> dict[str, Any]:
    if hasattr(row, "model_dump"):
        return row.model_dump(mode="json")
    return dict(row or {})


def _build_notes(
    original_rows: list[dict[str, Any]],
    corrected_rows: list[WorkerFeedbackRow],
) -> list[WorkerFeedbackCorrectionNote]:
    notes: list[WorkerFeedbackCorrectionNote] = []
    for index, (original, corrected_model) in enumerate(
        zip(original_rows, corrected_rows)
    ):
        corrected = corrected_model.model_dump(mode="json")
        for field in TEXT_FIELDS:
            original_text = original.get(field)
            corrected_text = corrected.get(field)
            if original_text is None or corrected_text is None:
                continue
            if original_text != corrected_text:
                notes.append(
                    WorkerFeedbackCorrectionNote(
                        row_index=index,
                        field=field,
                        original_text=str(original_text),
                        corrected_text=str(corrected_text),
                        reason="보고서 문체, 띄어쓰기 또는 문장 종결 표현을 정리함.",
                    )
                )
    return notes


def enforce_worker_feedback_invariants(
    original_rows: list[dict[str, Any]],
    result: WorkerFeedbackCorrectionResult,
    protected_fields: list[str] | None = None,
) -> WorkerFeedbackCorrectionResult:
    protected = set(protected_fields or PROTECTED_FIELDS)
    corrected_rows = result.corrected_rows
    unresolved_notes = list(result.unresolved_notes)

    if len(corrected_rows) != len(original_rows):
        unresolved_notes.append(
            "Correction result row count differed from source; original rows were restored."
        )
        safe_rows = [WorkerFeedbackRow(**row) for row in original_rows]
        return WorkerFeedbackCorrectionResult(
            corrected_rows=safe_rows,
            correction_notes=[],
            unresolved_notes=unresolved_notes,
        )

    safe_rows: list[WorkerFeedbackRow] = []
    for index, original in enumerate(original_rows):
        candidate = _row_to_dict(corrected_rows[index])
        safe_row = dict(original)

        for field in TEXT_FIELDS:
            if field in original and field not in protected:
                safe_row[field] = candidate.get(field, original.get(field))

        for field in protected:
            if field in original and candidate.get(field) != original.get(field):
                unresolved_notes.append(
                    f"Row {index} protected field '{field}' was restored to original value."
                )
                safe_row[field] = original.get(field)

        safe_rows.append(WorkerFeedbackRow(**safe_row))

    return WorkerFeedbackCorrectionResult(
        corrected_rows=safe_rows,
        correction_notes=_build_notes(original_rows, safe_rows),
        unresolved_notes=unresolved_notes,
    )
