from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.common.Report_data import BACKEND_AUTH_TOKEN, BACKEND_BASE_URL

def _index_by(items: list[dict[str, Any]], key: str) -> dict[Any, dict[str, Any]]:
    return {item.get(key): item for item in items}


def _risk(category: dict[str, Any] | None) -> str | int | None:
    if not category:
        return None
    return category.get("risk_level") or category.get("risk") or category.get("level")


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).replace("T", " ")


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if BACKEND_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {BACKEND_AUTH_TOKEN}"
    return headers


def _unwrap_item(data: Any) -> dict[str, Any]:
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    if isinstance(data, dict):
        return data
    return {}


def _get_action_history_detail(action_history_id: int) -> dict[str, Any]:
    url = (
        f"{BACKEND_BASE_URL.rstrip('/')}"
        f"/api/action-histories/{action_history_id}"
    )
    request = Request(url, headers=_headers(), method="GET")

    try:
        with urlopen(request, timeout=30) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return _unwrap_item(json.loads(response.read().decode(charset)))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {url} failed: {exc.code} {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"GET {url} failed: {exc.reason}") from exc


def _merge_action_detail(action: dict[str, Any]) -> dict[str, Any]:
    action_history_id = action.get("action_history_id")
    if action_history_id is None:
        return action

    detail = _get_action_history_detail(int(action_history_id))
    return {**action, **detail}


def build_worker_feedback_table(tables: dict[str, Any]) -> list[dict[str, Any]]:
    category_by_id = _index_by(tables.get("event_category", []), "category_id")
    board_by_id = _index_by(tables.get("board", []), "board_id")

    rows: list[dict[str, Any]] = []

    for action in tables.get("action_history", []):
        source_type = str(action.get("source_type") or "").strip()
        if source_type != "게시판":
            continue
        if action.get("approval_status") != "승인 완료":
            continue

        action = _merge_action_detail(action)

        board_id = action.get("board_id") or action.get("source_id")
        board = board_by_id.get(board_id, {})
        category = category_by_id.get(action.get("category_id"), {})

        rows.append(
            {
                "category": category.get("category"),
                "risk": _risk(category),
                "category_name": category.get("category_name"),
                "user": board.get("writer"),
                "board_writer": board.get("writer"),
                "board_created_at": _date_text(board.get("created_at")),
                "board_contents": board.get("board_contents"),
                "status": board.get("status"),
                "board_image_url": board.get("image_url"),
                "action_name": action.get("action_name"),
                "location": action.get("location"),
                "completed_at": _date_text(action.get("completed_at")),
                "action_status": action.get("action_status"),
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
