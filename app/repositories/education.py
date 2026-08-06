from datetime import date, timedelta
from typing import Optional

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.models.agent_read import (
    agent_education_read,
    agent_education_status_read,
    agent_education_user_read,
)


INCOMPLETE = "미이수"
IN_PROGRESS = "진행중"
COMPLETED = "이수"
ALL_EMPLOYEE_CATEGORY = "공통"


def _week_end(today: date) -> date:
    return today + timedelta(days=6 - today.weekday())


def _course_conditions(
    *,
    company_id: int,
    education_id: Optional[int] = None,
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    education_type: Optional[str] = None,
    due_from: Optional[date] = None,
    due_to: Optional[date] = None,
    due_state: Optional[str] = None,
) -> list:
    course = agent_education_read
    conditions = [course.c.company_id == company_id]
    if education_id is not None:
        conditions.append(course.c.education_id == education_id)
    if keyword and keyword.strip():
        conditions.append(course.c.title.ilike(f"%{keyword.strip()}%"))
    if category:
        conditions.append(course.c.category == category)
    if education_type:
        conditions.append(course.c.education_type == education_type)
    if due_from:
        conditions.append(course.c.due_date >= due_from)
    if due_to:
        conditions.append(course.c.due_date <= due_to)

    today = date.today()
    if due_state == "this_week":
        conditions.extend(
            [course.c.due_date >= today, course.c.due_date <= _week_end(today)]
        )
    elif due_state == "overdue":
        conditions.append(course.c.due_date < today)
    elif due_state == "no_due_date":
        conditions.append(course.c.due_date.is_(None))
    return conditions


def _course_columns():
    course = agent_education_read
    return [
        course.c.education_id,
        course.c.title,
        course.c.video_url,
        course.c.category,
        course.c.education_type,
        course.c.due_date,
    ]


def get_courses(
    db: Session,
    *,
    company_id: int,
    offset: int,
    limit: int,
    education_id: Optional[int] = None,
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    education_type: Optional[str] = None,
    due_from: Optional[date] = None,
    due_to: Optional[date] = None,
    due_state: Optional[str] = None,
) -> dict:
    course = agent_education_read
    conditions = _course_conditions(
        company_id=company_id,
        education_id=education_id,
        keyword=keyword,
        category=category,
        education_type=education_type,
        due_from=due_from,
        due_to=due_to,
        due_state=due_state,
    )
    total = db.execute(
        select(func.count()).select_from(course).where(*conditions)
    ).scalar_one()
    rows = db.execute(
        select(*_course_columns())
        .where(*conditions)
        .order_by(course.c.education_id.asc())
        .offset(offset)
        .limit(limit)
    ).mappings()
    return {
        "items": [dict(row) for row in rows],
        "total_items": int(total),
        "offset": offset,
        "limit": limit,
    }


def _target_source():
    course = agent_education_read
    user = agent_education_user_read
    status = agent_education_status_read
    target_condition = and_(
        user.c.company_id == course.c.company_id,
        or_(
            course.c.category == ALL_EMPLOYEE_CATEGORY,
            user.c.category == course.c.category,
        ),
    )
    status_condition = and_(
        status.c.company_id == course.c.company_id,
        status.c.education_id == course.c.education_id,
        status.c.uid == user.c.uid,
    )
    return course.outerjoin(user, target_condition).outerjoin(status, status_condition)


def get_course_summaries(
    db: Session,
    *,
    company_id: int,
    offset: int,
    limit: int,
    education_id: Optional[int] = None,
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    education_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    due_from: Optional[date] = None,
    due_to: Optional[date] = None,
    due_state: Optional[str] = None,
    target_state: Optional[str] = None,
    order_by: Optional[str] = None,
) -> dict:
    user = agent_education_user_read
    status = agent_education_status_read
    effective_status = func.coalesce(status.c.status, INCOMPLETE)
    has_target = user.c.uid.is_not(None)
    conditions = _course_conditions(
        company_id=company_id,
        education_id=education_id,
        keyword=keyword,
        category=category,
        education_type=education_type,
        due_from=due_from,
        due_to=due_to,
        due_state=due_state,
    )
    rows = db.execute(
        select(
            *_course_columns(),
            func.count(user.c.uid).label("target_count"),
            func.coalesce(
                func.sum(
                    case(
                        (and_(has_target, effective_status == INCOMPLETE), 1),
                        else_=0,
                    )
                ),
                0,
            ).label("incomplete_count"),
            func.coalesce(
                func.sum(
                    case(
                        (and_(has_target, effective_status == IN_PROGRESS), 1),
                        else_=0,
                    )
                ),
                0,
            ).label("in_progress_count"),
            func.coalesce(
                func.sum(
                    case(
                        (and_(has_target, effective_status == COMPLETED), 1),
                        else_=0,
                    )
                ),
                0,
            ).label("completed_count"),
        )
        .select_from(_target_source())
        .where(*conditions)
        .group_by(*_course_columns())
        .order_by(agent_education_read.c.education_id.asc())
    ).mappings()

    items = []
    for row in rows:
        item = dict(row)
        target_count = int(item["target_count"])
        item["target_count"] = target_count
        for key in ("incomplete_count", "in_progress_count", "completed_count"):
            item[key] = int(item[key])
        item["completion_rate"] = (
            round(item["completed_count"] / target_count * 100, 1)
            if target_count
            else 0.0
        )
        count_by_status = {
            INCOMPLETE: item["incomplete_count"],
            IN_PROGRESS: item["in_progress_count"],
            COMPLETED: item["completed_count"],
        }
        if status_filter and count_by_status[status_filter] == 0:
            continue
        if due_state in {"this_week", "overdue"} and (
            item["incomplete_count"] + item["in_progress_count"] == 0
        ):
            continue
        if target_state == "with_targets" and target_count == 0:
            continue
        if target_state == "without_targets" and target_count != 0:
            continue
        items.append(item)

    if order_by == "completion_rate_asc":
        items.sort(key=lambda item: (item["completion_rate"], item["education_id"]))
    elif order_by == "completion_rate_desc":
        items.sort(
            key=lambda item: (-item["completion_rate"], item["education_id"])
        )

    target_assignment_count = sum(item["target_count"] for item in items)
    completed_count = sum(item["completed_count"] for item in items)
    summary = {
        "course_count": len(items),
        "target_assignment_count": target_assignment_count,
        "incomplete_count": sum(item["incomplete_count"] for item in items),
        "in_progress_count": sum(item["in_progress_count"] for item in items),
        "completed_count": completed_count,
        "completion_rate": (
            round(completed_count / target_assignment_count * 100, 1)
            if target_assignment_count
            else 0.0
        ),
    }

    return {
        "items": items[offset : offset + limit],
        "total_items": len(items),
        "offset": offset,
        "limit": limit,
        "summary": summary,
    }


def get_course_attendees(
    db: Session,
    *,
    company_id: int,
    education_id: int,
    offset: int,
    limit: int,
    status_filter: Optional[str] = None,
) -> Optional[dict]:
    course_result = get_courses(
        db,
        company_id=company_id,
        education_id=education_id,
        offset=0,
        limit=1,
    )
    if not course_result["items"]:
        return None

    course = agent_education_read
    user = agent_education_user_read
    status = agent_education_status_read
    effective_status = func.coalesce(status.c.status, INCOMPLETE)
    source = course.join(
        user,
        and_(
            user.c.company_id == course.c.company_id,
            or_(
                course.c.category == ALL_EMPLOYEE_CATEGORY,
                user.c.category == course.c.category,
            ),
        ),
    ).outerjoin(
        status,
        and_(
            status.c.company_id == course.c.company_id,
            status.c.education_id == course.c.education_id,
            status.c.uid == user.c.uid,
        ),
    )
    rows = db.execute(
        select(
            user.c.name,
            user.c.category,
            user.c.role,
            effective_status.label("status"),
            status.c.completed_date,
        )
        .select_from(source)
        .where(
            course.c.company_id == company_id,
            course.c.education_id == education_id,
        )
        .order_by(user.c.name.asc())
    ).mappings()
    all_items = [dict(row) for row in rows]
    summary = {
        "target_count": len(all_items),
        "incomplete_count": sum(item["status"] == INCOMPLETE for item in all_items),
        "in_progress_count": sum(item["status"] == IN_PROGRESS for item in all_items),
        "completed_count": sum(item["status"] == COMPLETED for item in all_items),
    }
    filtered = (
        [item for item in all_items if item["status"] == status_filter]
        if status_filter
        else all_items
    )
    return {
        "course": course_result["items"][0],
        "items": filtered[offset : offset + limit],
        "total_items": len(filtered),
        "offset": offset,
        "limit": limit,
        "summary": summary,
    }


def get_user_statuses(
    db: Session,
    *,
    company_id: int,
    uid: int,
    offset: int,
    limit: int,
    status_filter: Optional[str] = None,
    category: Optional[str] = None,
    education_type: Optional[str] = None,
    due_state: Optional[str] = None,
) -> Optional[dict]:
    course = agent_education_read
    user = agent_education_user_read
    status = agent_education_status_read
    user_row = db.execute(
        select(user.c.name, user.c.category).where(
            user.c.company_id == company_id,
            user.c.uid == uid,
        )
    ).mappings().first()
    if not user_row:
        return None

    source = user.join(
        course,
        and_(
            course.c.company_id == user.c.company_id,
            or_(
                course.c.category == ALL_EMPLOYEE_CATEGORY,
                course.c.category == user.c.category,
            ),
        ),
    ).outerjoin(
        status,
        and_(
            status.c.company_id == course.c.company_id,
            status.c.education_id == course.c.education_id,
            status.c.uid == user.c.uid,
        ),
    )
    conditions = _course_conditions(
        company_id=company_id,
        category=category,
        education_type=education_type,
        due_state=due_state,
    )
    conditions.append(user.c.uid == uid)
    effective_status = func.coalesce(status.c.status, INCOMPLETE)
    if status_filter:
        conditions.append(effective_status == status_filter)
    rows = db.execute(
        select(
            *_course_columns(),
            effective_status.label("status"),
            status.c.completed_date,
        )
        .select_from(source)
        .where(*conditions)
        .order_by(course.c.education_id.asc())
    ).mappings()
    items = [dict(row) for row in rows]
    return {
        "user_name": user_row["name"],
        "user_category": user_row["category"],
        "items": items[offset : offset + limit],
        "total_items": len(items),
        "offset": offset,
        "limit": limit,
        "summary": {
            "target_count": len(items),
            "incomplete_count": sum(item["status"] == INCOMPLETE for item in items),
            "in_progress_count": sum(item["status"] == IN_PROGRESS for item in items),
            "completed_count": sum(item["status"] == COMPLETED for item in items),
        },
    }


def search_user_statuses(
    db: Session,
    *,
    company_id: int,
    user_name: str,
    status_filter: Optional[str] = None,
    category: Optional[str] = None,
    education_type: Optional[str] = None,
    due_state: Optional[str] = None,
    user_limit: int = 10,
    course_limit: int = 50,
) -> dict:
    user = agent_education_user_read
    user_ids = db.execute(
        select(user.c.uid)
        .where(
            user.c.company_id == company_id,
            user.c.name.ilike(f"%{user_name.strip()}%"),
        )
        .order_by(user.c.name.asc(), user.c.uid.asc())
        .limit(user_limit)
    ).scalars().all()
    results = []
    for uid in user_ids:
        result = get_user_statuses(
            db,
            company_id=company_id,
            uid=uid,
            status_filter=status_filter,
            category=category,
            education_type=education_type,
            due_state=due_state,
            offset=0,
            limit=course_limit,
        )
        if result is not None:
            results.append(result)
    return {"users": results, "total_users": len(results)}


def get_overview(db: Session, *, company_id: int) -> dict:
    summaries = get_course_summaries(
        db,
        company_id=company_id,
        offset=0,
        limit=100000,
    )["items"]
    today = date.today()
    week_end = _week_end(today)
    target_count = sum(item["target_count"] for item in summaries)
    completed_count = sum(item["completed_count"] for item in summaries)
    category_totals = {}
    for item in summaries:
        bucket = category_totals.setdefault(
            item["category"], {"target_count": 0, "completed_count": 0}
        )
        bucket["target_count"] += item["target_count"]
        bucket["completed_count"] += item["completed_count"]

    categories = []
    for category, counts in sorted(category_totals.items()):
        category_target = counts["target_count"]
        categories.append(
            {
                "category": category,
                **counts,
                "completion_rate": (
                    round(counts["completed_count"] / category_target * 100, 1)
                    if category_target
                    else 0.0
                ),
            }
        )
    return {
        "course_count": len(summaries),
        "target_assignment_count": target_count,
        "incomplete_count": sum(item["incomplete_count"] for item in summaries),
        "in_progress_count": sum(item["in_progress_count"] for item in summaries),
        "completed_count": completed_count,
        "completion_rate": (
            round(completed_count / target_count * 100, 1)
            if target_count
            else 0.0
        ),
        "due_this_week_course_count": sum(
            item["due_date"] is not None
            and today <= item["due_date"] <= week_end
            and item["incomplete_count"] + item["in_progress_count"] > 0
            for item in summaries
        ),
        "overdue_course_count": sum(
            item["due_date"] is not None
            and item["due_date"] < today
            and item["incomplete_count"] + item["in_progress_count"] > 0
            for item in summaries
        ),
        "no_due_date_course_count": sum(
            item["due_date"] is None for item in summaries
        ),
        "categories": categories,
    }
