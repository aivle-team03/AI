from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.common.Report_data import get_action_history_detail

EXTERNAL_OUTPUT_ROOT = PROJECT_ROOT.parent / "output"
INSPECTION_DONE = "점검 완료"
APPROVED = "승인 완료"
TYPE_INSPECTION = "점검이력"
TYPE_DIRECT = "직접추가"
TYPE_BOARD = "게시판"
TYPE_EVENT = "이벤트"


def _index_by(items: list[dict[str, Any]], key: str) -> dict[Any, dict[str, Any]]:
    return {item.get(key): item for item in items}


def _risk(category: dict[str, Any] | None) -> Any:
    if not category:
        return None
    return category.get("risk_level") or category.get("risk") or category.get("level")


def _category_part(
    category_id: Any,
    category_by_id: dict[Any, dict[str, Any]],
) -> dict[str, Any]:
    category = category_by_id.get(category_id, {})
    return {
        "category": category.get("category"),
        "risk": _risk(category),
        "category_name": category.get("category_name"),
    }


def _inspection_part(history: dict[str, Any] | None) -> dict[str, Any]:
    if not history:
        return {
            "inspection_location": None,
            "inspection_date": None,
            "inspection_user_name": None,
            "inspection_content": None,
        }

    return {
        "inspection_location": history.get("location"),
        "inspection_date": history.get("date"),
        "inspection_user_name": history.get("user_name"),
        "inspection_content": history.get("content"),
    }


def _action_part(
    action: dict[str, Any] | None,
    row_type: str | None = None,
) -> dict[str, Any]:
    if not action:
        return {
            "action_name": None,
            "action_location": None,
            "completed_at": None,
            "handler_name": None,
            "content": None,
            "approver_name": None,
            "type": row_type,
        }

    return {
        "action_name": action.get("action_name"),
        "action_location": action.get("location"),
        "completed_at": action.get("completed_at"),
        "handler_name": action.get("handler_name"),
        "content": action.get("content"),
        "approver_name": action.get("approver_name"),
        "type": action.get("type") or action.get("source_type"),
    }


def _inspection_image_url_for_action(
    action: dict[str, Any] | None,
    board_by_id: dict[Any, dict[str, Any]],
    event_by_id: dict[Any, dict[str, Any]],
) -> str | None:
    if not action:
        return None

    source_type = str(action.get("type") or action.get("source_type") or "").strip()

    if source_type == TYPE_BOARD:
        board_id = action.get("board_id") or action.get("source_id")
        return board_by_id.get(board_id, {}).get("image_url")

    if source_type == TYPE_EVENT:
        event_id = action.get("event_id") or action.get("source_id")
        return event_by_id.get(event_id, {}).get("image_url")

    return None


def _image_url_for_action(action: dict[str, Any]) -> str | None:
    return action.get("image_url")


def _fill_action_content(rows: list[dict[str, Any]], action_history_ids: list[Any]) -> None:
    # action_history list rows don't carry a "content" field; fetch it per-row from the
    # detail endpoint as a final pass, once we know which rows have a real action.
    for row, action_history_id in zip(rows, action_history_ids):
        if action_history_id is None:
            continue
        detail = get_action_history_detail(action_history_id)
        content = detail.get("content")
        if content:
            row["content"] = content


def build_final_history_table_14(tables: dict[str, Any]) -> list[dict[str, Any]]:
    category_by_id = _index_by(tables.get("event_category", []), "category_id")
    inspection_by_id = _index_by(tables.get("inspection", []), "inspection_id")
    board_by_id = _index_by(tables.get("board", []), "board_id")
    event_by_id = _index_by(tables.get("event", []), "event_id")

    inspection_histories = tables.get("inspection_history", [])
    actions = tables.get("action_history", [])

    approved_actions = [
        action
        for action in actions
        if action.get("approval_status") == APPROVED
    ]

    approved_action_by_inspection_history_id: dict[Any, dict[str, Any]] = {}
    for action in approved_actions:
        source_type = str(action.get("type") or action.get("source_type") or "").strip()
        if source_type != TYPE_INSPECTION:
            continue

        inspection_history_id = (
            action.get("inspection_history_id")
            or action.get("source_id")
        )
        if inspection_history_id is not None:
            approved_action_by_inspection_history_id[inspection_history_id] = action

    rows: list[dict[str, Any]] = []
    action_history_ids: list[Any] = []

    for history in inspection_histories:
        if history.get("status") != INSPECTION_DONE:
            continue

        inspection = inspection_by_id.get(history.get("inspection_id"), {})
        category_id = history.get("category_id") or inspection.get("category_id")
        action = approved_action_by_inspection_history_id.get(
            history.get("inspection_history_id")
        )

        rows.append(
            {
                **_category_part(category_id, category_by_id),
                **_inspection_part(history),
                "image_url": _image_url_for_action(action) if action else None,
                "inspection_image_url": None,
                **_action_part(action),
            }
        )
        action_history_ids.append(action.get("action_history_id") if action else None)

    for action in approved_actions:
        source_type = str(action.get("type") or action.get("source_type") or "").strip()
        if source_type == TYPE_INSPECTION:
            continue
        if source_type not in {TYPE_DIRECT, TYPE_BOARD, TYPE_EVENT}:
            continue

        rows.append(
            {
                **_category_part(action.get("category_id"), category_by_id),
                **_inspection_part(None),
                "image_url": _image_url_for_action(action),
                "inspection_image_url": _inspection_image_url_for_action(
                    action, board_by_id, event_by_id
                ),
                **_action_part(action),
            }
        )
        action_history_ids.append(action.get("action_history_id"))

    _fill_action_content(rows, action_history_ids)

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a compact 14-column final history table.",
    )
    parser.add_argument(
        "--input",
        default=str(EXTERNAL_OUTPUT_ROOT / "risk_assessment_form" / "BackendData.json"),
        help="BackendData JSON path.",
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "output" / "final_history_table_14.json"),
        help="Compact final table JSON path.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.is_absolute():
        input_path = PROJECT_ROOT / input_path
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    with input_path.open("r", encoding="utf-8-sig") as file:
        tables = json.load(file)

    rows = build_final_history_table_14(tables)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig") as file:
        json.dump(rows, file, ensure_ascii=False, indent=2)
        file.write("\n")

    counts: dict[str, int] = {}
    for row in rows:
        row_type = row.get("type")
        counts[str(row_type)] = counts.get(str(row_type), 0) + 1

    print(f"wrote: {output_path}")
    print(f"total: {len(rows)}")
    for row_type in sorted(counts):
        print(f"{row_type}: {counts[row_type]}")


if __name__ == "__main__":
    main()

