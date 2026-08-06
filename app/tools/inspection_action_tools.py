from datetime import date, datetime, time
from typing import Any, Optional

from sqlalchemy.exc import SQLAlchemyError

from app.db.read_db import AgentReadDatabaseError, get_read_session
from app.repositories import inspection_action as repository
from app.schemas.inspection_action import InspectionActionQuery


def _start_of_day(value: Optional[date]) -> Optional[datetime]:
    return datetime.combine(value, time.min) if value else None


def _end_of_day(value: Optional[date]) -> Optional[datetime]:
    return datetime.combine(value, time.max) if value else None


def _first_or_error(result: dict[str, Any]) -> dict[str, Any]:
    if not result["items"]:
        raise AgentReadDatabaseError("요청한 데이터를 찾을 수 없습니다.")
    return result["items"][0]


def execute_inspection_action_query(
    query: InspectionActionQuery,
    *,
    company_id: int,
) -> dict[str, Any]:
    if company_id <= 0:
        raise AgentReadDatabaseError("인증된 회사 정보를 확인할 수 없습니다.")

    try:
        with get_read_session() as db:
            if query.operation in {"list_inspections", "get_inspection"}:
                result = repository.get_inspections(
                    db,
                    company_id=company_id,
                    inspection_id=(
                        query.inspection_id
                        if query.operation == "get_inspection"
                        else None
                    ),
                    keyword=query.keyword,
                    category_id=query.category_id,
                    category_value=query.category,
                    category_name=query.category_name,
                    uid=query.uid,
                    offset=query.offset,
                    limit=1 if query.operation == "get_inspection" else query.limit,
                )
                return (
                    _first_or_error(result)
                    if query.operation == "get_inspection"
                    else result
                )

            if query.operation in {
                "list_inspection_histories",
                "get_inspection_history",
            }:
                result = repository.get_inspection_histories(
                    db,
                    company_id=company_id,
                    inspection_history_id=(
                        query.inspection_history_id
                        if query.operation == "get_inspection_history"
                        else None
                    ),
                    inspection_id=query.inspection_id,
                    keyword=query.keyword,
                    category_value=query.category,
                    category_name=query.category_name,
                    status=query.status_filter,
                    is_action_required=query.is_action_required,
                    date_from=_start_of_day(query.date_from),
                    date_to=_end_of_day(query.date_to),
                    offset=query.offset,
                    limit=(
                        1
                        if query.operation == "get_inspection_history"
                        else query.limit
                    ),
                )
                return (
                    _first_or_error(result)
                    if query.operation == "get_inspection_history"
                    else result
                )

            result = repository.get_action_histories(
                db,
                company_id=company_id,
                action_history_id=(
                    query.action_history_id
                    if query.operation == "get_action_history"
                    else None
                ),
                keyword=query.keyword,
                source_type=query.source_type,
                category_id=query.category_id,
                category_value=query.category,
                category_name=query.category_name,
                action_status=query.action_status,
                approval_status=query.approval_status,
                handler_uid=query.handler_uid,
                inspection_history_ids=query.inspection_history_ids,
                unassigned=query.unassigned,
                created_from=_start_of_day(query.created_from),
                created_to=_end_of_day(query.created_to),
                completed_from=_start_of_day(query.completed_from),
                completed_to=_end_of_day(query.completed_to),
                sort_by=query.sort_by,
                offset=query.offset,
                limit=1 if query.operation == "get_action_history" else query.limit,
            )
            return (
                _first_or_error(result)
                if query.operation == "get_action_history"
                else result
            )
    except AgentReadDatabaseError:
        raise
    except SQLAlchemyError as exc:
        raise AgentReadDatabaseError(
            "점검·조치 읽기 전용 데이터베이스 조회에 실패했습니다."
        ) from exc
