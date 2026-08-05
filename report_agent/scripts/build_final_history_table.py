from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.common.Report_data import _get_json


def _index_by(items: list[dict[str, Any]], key: str) -> dict[Any, dict[str, Any]]:
    return {item.get(key): item for item in items}


def _risk(category: dict[str, Any] | None) -> str | None:
    if not category:
        return None
    return category.get("risk_level") or category.get("level")


def _inspection_part(
    inspection_history: dict[str, Any] | None,
    inspection_by_id: dict[Any, dict[str, Any]],
    category_by_id: dict[Any, dict[str, Any]],
) -> dict[str, Any]:
    if not inspection_history:
        return {
            "inspection_history_id": None,
            "inspection_id": None,
            "inspection_name": None,
            "category_id": None,
            "category_name": None,
            "risk": None,
            "inspection_location": None,
            "inspection_date": None,
            "inspection_user_id": None,
            "inspection_user_name": None,
            "inspection_content": None,
        }

    inspection = inspection_by_id.get(inspection_history.get("inspection_id"), {})
    category_id = (
        inspection_history.get("category_id")
        or inspection.get("category_id")
    )
    category = category_by_id.get(category_id, {})

    return {
        "inspection_history_id": inspection_history.get("inspection_history_id"),
        "inspection_id": inspection_history.get("inspection_id"),
        "inspection_name": inspection.get("name") or inspection_history.get("name"),
        "category_id": category_id,
        "category_name": (
            category.get("category_name")
            or inspection_history.get("category_name")
        ),
        "risk": _risk(category),
        "inspection_location": inspection_history.get("location"),
        "inspection_date": inspection_history.get("date"),
        "inspection_user_id": inspection_history.get("uid"),
        "inspection_user_name": inspection_history.get("user_name"),
        "inspection_content": inspection_history.get("content"),
    }


def _empty_action_part() -> dict[str, Any]:
    return {
        "action_history_id": None,
        "action_name": None,
        "action_location": None,
        "action_date": None,
        "action_user_id": None,
        "action_user_name": None,
        "action_content": None,
        "action_status": None,
        "approval_status": None,
        "approval_name": None,
    }


def _unwrap_item(data: Any) -> dict[str, Any]:
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    if isinstance(data, dict):
        return data
    return {}


def _action_detail(action_history_id: int) -> dict[str, Any]:
    return _unwrap_item(_get_json(f"/api/action-histories/{action_history_id}"))


def _merge_approved_action_detail(action: dict[str, Any]) -> dict[str, Any]:
    if action.get("approval_status") != "승인 완료":
        return action

    action_history_id = action.get("action_history_id")
    if action_history_id is None:
        return action

    detail = _action_detail(int(action_history_id))
    return {**action, **detail}


def _action_part(action: dict[str, Any]) -> dict[str, Any]:
    action = _merge_approved_action_detail(action)

    return {
        "action_history_id": action.get("action_history_id"),
        "action_name": action.get("action_name"),
        "action_location": action.get("location"),
        "action_date": action.get("created_at"),
        "action_user_id": action.get("handler_uid"),
        "action_user_name": action.get("handler_name"),
        "action_content": action.get("content"),
        "action_status": action.get("action_status"),
        "approval_status": action.get("approval_status"),
        "approval_name": action.get("approver_name"),
    }


def _image_url_for_action(
    action: dict[str, Any],
    event_by_id: dict[Any, dict[str, Any]],
    board_by_id: dict[Any, dict[str, Any]],
) -> str | None:
    source_type = str(action.get("source_type") or "").strip()
    if source_type == "게시판":
        event = event_by_id.get(action.get("event_id"))
        board = board_by_id.get(action.get("board_id"))
        return (
            (event or {}).get("image_url")
            or (board or {}).get("image_url")
            or action.get("image_url")
        )
    if source_type == "이벤트":
        event = event_by_id.get(action.get("event_id"))
        return (event or {}).get("image_url") or action.get("image_url")
    return action.get("image_url")


def _source_context_for_action(
    action: dict[str, Any],
    category_by_id: dict[Any, dict[str, Any]],
    event_by_id: dict[Any, dict[str, Any]],
    board_by_id: dict[Any, dict[str, Any]],
) -> dict[str, Any]:
    category = category_by_id.get(action.get("category_id"), {})
    source_type = str(action.get("source_type") or "").strip()
    event = event_by_id.get(action.get("event_id"), {})
    board = board_by_id.get(action.get("board_id"), {})

    return {
        "category_id": action.get("category_id"),
        "category_name": category.get("category_name") or action.get("category_name"),
        "risk": _risk(category),
        "before_image_url": _image_url_for_action(action, event_by_id, board_by_id),
        "board_id": board.get("board_id"),
        "event_id": event.get("event_id") or action.get("event_id"),
        "source_type": source_type or None,
        "source_id": action.get("source_id"),
    }


def build_final_history_table(tables: dict[str, Any]) -> list[dict[str, Any]]:
    category_by_id = _index_by(tables.get("event_category", []), "category_id")
    inspection_by_id = _index_by(tables.get("inspection", []), "inspection_id")
    inspection_history_by_id = _index_by(
        tables.get("inspection_history", []),
        "inspection_history_id",
    )
    event_by_id = _index_by(tables.get("event", []), "event_id")
    board_by_id = _index_by(tables.get("board", []), "board_id")

    actions = tables.get("action_history", [])
    actions_by_inspection_history_id = {
        action.get("inspection_history_id")
        for action in actions
        if action.get("inspection_history_id") is not None
    }

    rows: list[dict[str, Any]] = []

    for inspection_history in tables.get("inspection_history", []):
        inspection_history_id = inspection_history.get("inspection_history_id")
        if inspection_history_id in actions_by_inspection_history_id:
            continue

        rows.append(
            {
                "type": "inspection",
                **_inspection_part(
                    inspection_history,
                    inspection_by_id,
                    category_by_id,
                ),
                "before_image_url": None,
                **_empty_action_part(),
            }
        )

    for action in actions:
        source_type = str(action.get("source_type") or "").strip()

        if action.get("inspection_history_id") is not None:
            inspection_history = inspection_history_by_id.get(
                action.get("inspection_history_id")
            )
            rows.append(
                {
                    "type": "조치이력",
                    **_inspection_part(
                        inspection_history,
                        inspection_by_id,
                        category_by_id,
                    ),
                    "before_image_url": None,
                    "source_type": source_type or None,
                    "source_id": action.get("source_id"),
                    **_action_part(action),
                }
            )
            continue

        source = _source_context_for_action(
            action,
            category_by_id,
            event_by_id,
            board_by_id,
        )
        case_name = "Case 3" if source_type == "게시판" else "Case 4"
        row_type = "board" if source_type == "게시판" else "event"

        rows.append(
            {
                "type": row_type,
                "source_type": source["source_type"],
                "source_id": source["source_id"],
                **_inspection_part(None, inspection_by_id, category_by_id),
                "category_id": source["category_id"],
                "category_name": source["category_name"],
                "risk": source["risk"],
                "before_image_url": source["before_image_url"],
                "board_id": source["board_id"],
                "event_id": source["event_id"],
                **_action_part(action),
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row.get("type") or "",
            row.get("inspection_date") or row.get("action_date") or "",
            row.get("action_history_id") or 0,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a final combined history table from separated dummy tables.",
    )
    parser.add_argument(
        "--input",
        default="output/separated_history_dummy_tables.json",
        help="Separated table JSON path.",
    )
    parser.add_argument(
        "--output",
        default="output/final_history_table_from_separated.json",
        help="Combined final table JSON path.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    with input_path.open("r", encoding="utf-8-sig") as file:
        tables = json.load(file)

    rows = build_final_history_table(tables)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(rows, file, ensure_ascii=False, indent=2)
        file.write("\n")

    counts: dict[str, int] = {}
    for row in rows:
        row_type = row.get("type") or "-"
        counts[row_type] = counts.get(row_type, 0) + 1

    print(f"wrote: {output_path}")
    print(f"total: {len(rows)}")
    for row_type in sorted(counts):
        print(f"{row_type}: {counts[row_type]}")


if __name__ == "__main__":
    main()
