from datetime import date
from typing import Any

from app.schemas.inspection_action import InspectionActionQuery
from app.tools.backend_client import get_backend_json


LIST_PATHS = {
    "list_inspections": "/api/agent-data/inspection-action/inspections",
    "list_inspection_histories": (
        "/api/agent-data/inspection-action/inspection-histories"
    ),
    "list_action_histories": (
        "/api/agent-data/inspection-action/action-histories"
    ),
}


def _query_params(query: InspectionActionQuery) -> dict[str, Any]:
    allowed_fields = {
        "list_inspections": {
            "keyword",
            "category_id",
            "uid",
            "offset",
            "limit",
        },
        "list_inspection_histories": {
            "inspection_id",
            "keyword",
            "status_filter",
            "is_action_required",
            "date_from",
            "date_to",
            "offset",
            "limit",
        },
        "list_action_histories": {
            "keyword",
            "source_type",
            "category_id",
            "action_status",
            "approval_status",
            "handler_uid",
            "unassigned",
            "created_from",
            "created_to",
            "completed_from",
            "completed_to",
            "offset",
            "limit",
        },
    }
    fields = allowed_fields[query.operation]
    params = query.model_dump(exclude_none=True, include=fields)
    return {
        key: value.isoformat() if isinstance(value, date) else value
        for key, value in params.items()
    }


def execute_inspection_action_query(
    query: InspectionActionQuery,
    *,
    access_token: str,
) -> dict[str, Any]:
    if query.operation in LIST_PATHS:
        return get_backend_json(
            LIST_PATHS[query.operation],
            access_token=access_token,
            params=_query_params(query),
        )

    detail_paths = {
        "get_inspection": (
            "/api/agent-data/inspection-action/inspections/"
            f"{query.inspection_id}"
        ),
        "get_inspection_history": (
            "/api/agent-data/inspection-action/inspection-histories/"
            f"{query.inspection_history_id}"
        ),
        "get_action_history": (
            "/api/agent-data/inspection-action/action-histories/"
            f"{query.action_history_id}"
        ),
    }
    return get_backend_json(
        detail_paths[query.operation],
        access_token=access_token,
    )
