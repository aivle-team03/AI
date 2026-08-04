from __future__ import annotations

from typing import Any


def _index_by(items: list[dict[str, Any]], key: str) -> dict[Any, dict[str, Any]]:
    return {item.get(key): item for item in items}


def _risk(category: dict[str, Any] | None) -> str | int | None:
    if not category:
        return None
    return category.get("risk_level") or category.get("risk") or category.get("level")


def build_worker_feedback_table(tables: dict[str, Any]) -> list[dict[str, Any]]:
    category_by_id = _index_by(tables.get("event_category", []), "category_id")
    board_by_id = _index_by(tables.get("board", []), "board_id")

    rows: list[dict[str, Any]] = []

    for action in tables.get("action_history", []):
        source_type = str(action.get("source_type") or "").strip()
        if source_type != "게시판":
            continue

        board = board_by_id.get(action.get("board_id"), {})
        category = category_by_id.get(action.get("category_id"), {})

        rows.append(
            {
                "category": category.get("category"),
                "risk": _risk(category),
                "category_name": category.get("category_name"),
                "board_created_at": board.get("created_at"),
                "board_contents": board.get("board_contents"),
                "status": board.get("status"),
                "board_image_url": board.get("image_url"),
                "action_name": action.get("action_name"),
                "location": action.get("location"),
                "completed_at": action.get("completed_at"),
                "handler_name": action.get("handler_name"),
                "content": action.get("content"),
                "image_url": action.get("image_url"),
                "approver_name": action.get("approver_name"),
                "source_type": source_type,
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row.get("board_created_at") or "",
            row.get("completed_at") or "",
            row.get("category") or "",
            row.get("category_name") or "",
        ),
    )
