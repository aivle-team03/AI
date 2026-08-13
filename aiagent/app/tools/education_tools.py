from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.db.read_db import AgentReadDatabaseError, get_read_session
from app.repositories import education as repository
from app.schemas.education import EducationQuery


def _first_or_error(result: dict[str, Any]) -> dict[str, Any]:
    if not result["items"]:
        raise AgentReadDatabaseError("요청한 교육 과정을 찾을 수 없습니다.")
    return result["items"][0]


def execute_education_query(
    query: EducationQuery,
    *,
    company_id: int,
) -> dict[str, Any]:
    if company_id <= 0:
        raise AgentReadDatabaseError("인증된 회사 정보를 확인할 수 없습니다.")

    try:
        with get_read_session() as db:
            if query.operation in {
                "list_education_courses",
                "get_education_course",
            }:
                result = repository.get_courses(
                    db,
                    company_id=company_id,
                    education_id=(
                        query.education_id
                        if query.operation == "get_education_course"
                        else None
                    ),
                    keyword=query.keyword,
                    category=query.category,
                    education_type=query.education_type,
                    due_from=query.due_from,
                    due_to=query.due_to,
                    due_state=query.due_state,
                    offset=query.offset,
                    limit=(
                        1
                        if query.operation == "get_education_course"
                        else query.limit
                    ),
                )
                return (
                    _first_or_error(result)
                    if query.operation == "get_education_course"
                    else result
                )

            if query.operation == "list_education_summaries":
                return repository.get_course_summaries(
                    db,
                    company_id=company_id,
                    education_id=query.education_id,
                    keyword=query.keyword,
                    category=query.category,
                    education_type=query.education_type,
                    status_filter=query.status_filter,
                    due_from=query.due_from,
                    due_to=query.due_to,
                    due_state=query.due_state,
                    target_state=query.target_state,
                    order_by=query.order_by,
                    offset=query.offset,
                    limit=query.limit,
                )

            if query.operation == "list_course_attendees":
                result = repository.get_course_attendees(
                    db,
                    company_id=company_id,
                    education_id=query.education_id,
                    status_filter=query.status_filter,
                    offset=query.offset,
                    limit=query.limit,
                )
                if result is None:
                    raise AgentReadDatabaseError(
                        "요청한 교육 과정을 찾을 수 없습니다."
                    )
                return result

            if query.operation == "list_user_education_statuses":
                if query.user_name:
                    return repository.search_user_statuses(
                        db,
                        company_id=company_id,
                        user_name=query.user_name,
                        status_filter=query.status_filter,
                        category=query.category,
                        education_type=query.education_type,
                        due_state=query.due_state,
                        user_limit=10,
                        course_limit=query.limit,
                    )
                result = repository.get_user_statuses(
                    db,
                    company_id=company_id,
                    uid=query.uid,
                    status_filter=query.status_filter,
                    category=query.category,
                    education_type=query.education_type,
                    due_state=query.due_state,
                    offset=query.offset,
                    limit=query.limit,
                )
                if result is None:
                    raise AgentReadDatabaseError(
                        "요청한 사용자를 찾을 수 없습니다."
                    )
                return result

            return repository.get_overview(db, company_id=company_id)
    except AgentReadDatabaseError:
        raise
    except SQLAlchemyError as exc:
        raise AgentReadDatabaseError(
            "교육 읽기 전용 데이터베이스 조회에 실패했습니다."
        ) from exc
