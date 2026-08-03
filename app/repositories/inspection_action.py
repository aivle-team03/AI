from datetime import datetime
from typing import Optional

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.models.agent_read import (
    agent_action_history_read,
    agent_event_category_read,
    agent_inspection_history_read,
    agent_inspection_read,
    agent_user_display_read,
)


def _contains(column, keyword: str):
    return column.ilike(f"%{keyword.strip()}%")


def get_inspections(
    db: Session,
    *,
    company_id: int,
    offset: int,
    limit: int,
    inspection_id: Optional[int] = None,
    keyword: Optional[str] = None,
    category_id: Optional[int] = None,
    uid: Optional[int] = None,
) -> dict:
    inspection = agent_inspection_read
    category = agent_event_category_read
    user = agent_user_display_read
    source = inspection.outerjoin(
        category,
        and_(
            category.c.category_id == inspection.c.category_id,
            category.c.company_id == inspection.c.company_id,
        ),
    ).outerjoin(
        user,
        and_(
            user.c.uid == inspection.c.uid,
            user.c.company_id == inspection.c.company_id,
        ),
    )
    conditions = [inspection.c.company_id == company_id]
    if inspection_id is not None:
        conditions.append(inspection.c.inspection_id == inspection_id)
    if keyword and keyword.strip():
        conditions.append(
            or_(
                _contains(inspection.c.name, keyword),
                _contains(inspection.c.location, keyword),
                _contains(inspection.c.content, keyword),
            )
        )
    if category_id is not None:
        conditions.append(inspection.c.category_id == category_id)
    if uid is not None:
        conditions.append(inspection.c.uid == uid)

    columns = [
        inspection.c.inspection_id,
        inspection.c.category_id,
        category.c.category,
        category.c.category_name,
        category.c.level.label("category_level"),
        inspection.c.uid,
        user.c.name.label("user_name"),
        inspection.c.name,
        inspection.c.location,
        inspection.c.cycle,
        inspection.c.content,
    ]
    total = db.execute(
        select(func.count()).select_from(source).where(*conditions)
    ).scalar_one()
    rows = db.execute(
        select(*columns)
        .select_from(source)
        .where(*conditions)
        .order_by(inspection.c.inspection_id.desc())
        .offset(offset)
        .limit(limit)
    ).mappings()
    return {
        "items": [dict(row) for row in rows],
        "total_items": int(total),
        "offset": offset,
        "limit": limit,
    }


def get_inspection_histories(
    db: Session,
    *,
    company_id: int,
    offset: int,
    limit: int,
    inspection_history_id: Optional[int] = None,
    inspection_id: Optional[int] = None,
    keyword: Optional[str] = None,
    status: Optional[str] = None,
    is_action_required: Optional[bool] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> dict:
    history = agent_inspection_history_read
    inspection = agent_inspection_read
    category = agent_event_category_read
    user = agent_user_display_read
    source = (
        history.outerjoin(
            inspection,
            and_(
                inspection.c.inspection_id == history.c.inspection_id,
                inspection.c.company_id == history.c.company_id,
            ),
        )
        .outerjoin(
            category,
            and_(
                category.c.category_id == inspection.c.category_id,
                category.c.company_id == history.c.company_id,
            ),
        )
        .outerjoin(
            user,
            and_(
                user.c.uid == history.c.uid,
                user.c.company_id == history.c.company_id,
            ),
        )
    )
    conditions = [history.c.company_id == company_id]
    if inspection_history_id is not None:
        conditions.append(
            history.c.inspection_history_id == inspection_history_id
        )
    if inspection_id is not None:
        conditions.append(history.c.inspection_id == inspection_id)
    if keyword and keyword.strip():
        conditions.append(
            or_(
                _contains(history.c.name, keyword),
                _contains(history.c.location, keyword),
                _contains(history.c.content, keyword),
            )
        )
    if status:
        conditions.append(history.c.status == status)
    if is_action_required is not None:
        conditions.append(history.c.is_action_required == is_action_required)
    if date_from:
        conditions.append(history.c.date >= date_from)
    if date_to:
        conditions.append(history.c.date <= date_to)

    columns = [
        history.c.inspection_history_id,
        history.c.inspection_id,
        inspection.c.category_id,
        category.c.category,
        category.c.category_name,
        category.c.level.label("category_level"),
        history.c.uid,
        func.coalesce(user.c.name, history.c.user_name).label("user_name"),
        history.c.name,
        history.c.location,
        history.c.date,
        history.c.status,
        history.c.is_action_required,
        history.c.content,
    ]
    summary_row = db.execute(
        select(
            func.count().label("total"),
            func.coalesce(
                func.sum(case((history.c.status == "점검 대기", 1), else_=0)),
                0,
            ).label("waiting"),
            func.coalesce(
                func.sum(case((history.c.status == "점검 완료", 1), else_=0)),
                0,
            ).label("completed"),
            func.coalesce(
                func.sum(
                    case((history.c.is_action_required.is_(True), 1), else_=0)
                ),
                0,
            ).label("action_required"),
        )
        .select_from(source)
        .where(*conditions)
    ).mappings().one()
    rows = db.execute(
        select(*columns)
        .select_from(source)
        .where(*conditions)
        .order_by(history.c.date.desc(), history.c.inspection_history_id.desc())
        .offset(offset)
        .limit(limit)
    ).mappings()
    total = int(summary_row["total"])
    return {
        "items": [dict(row) for row in rows],
        "total_items": total,
        "offset": offset,
        "limit": limit,
        "summary": {
            "total_count": total,
            "waiting_count": int(summary_row["waiting"]),
            "completed_count": int(summary_row["completed"]),
            "action_required_count": int(summary_row["action_required"]),
        },
    }


def get_action_histories(
    db: Session,
    *,
    company_id: int,
    offset: int,
    limit: int,
    action_history_id: Optional[int] = None,
    keyword: Optional[str] = None,
    source_type: Optional[str] = None,
    category_id: Optional[int] = None,
    action_status: Optional[str] = None,
    approval_status: Optional[str] = None,
    handler_uid: Optional[int] = None,
    unassigned: Optional[bool] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    completed_from: Optional[datetime] = None,
    completed_to: Optional[datetime] = None,
) -> dict:
    action = agent_action_history_read
    category = agent_event_category_read
    handler = agent_user_display_read.alias("handler")
    approver = agent_user_display_read.alias("approver")
    source = (
        action.outerjoin(
            category,
            and_(
                category.c.category_id == action.c.category_id,
                category.c.company_id == action.c.company_id,
            ),
        )
        .outerjoin(
            handler,
            and_(
                handler.c.uid == action.c.handler_uid,
                handler.c.company_id == action.c.company_id,
            ),
        )
        .outerjoin(
            approver,
            and_(
                approver.c.uid == action.c.approver_uid,
                approver.c.company_id == action.c.company_id,
            ),
        )
    )
    conditions = [action.c.company_id == company_id]
    if action_history_id is not None:
        conditions.append(action.c.action_history_id == action_history_id)
    if keyword and keyword.strip():
        conditions.append(
            or_(
                _contains(action.c.action_name, keyword),
                _contains(action.c.location, keyword),
                _contains(action.c.content, keyword),
            )
        )
    if source_type:
        conditions.append(action.c.source_type == source_type)
    if category_id is not None:
        conditions.append(action.c.category_id == category_id)
    if action_status:
        conditions.append(action.c.action_status == action_status)
    if approval_status:
        conditions.append(action.c.approval_status == approval_status)
    if handler_uid is not None:
        conditions.append(action.c.handler_uid == handler_uid)
    if unassigned is True:
        conditions.append(action.c.handler_uid.is_(None))
    elif unassigned is False:
        conditions.append(action.c.handler_uid.is_not(None))
    if created_from:
        conditions.append(action.c.created_at >= created_from)
    if created_to:
        conditions.append(action.c.created_at <= created_to)
    if completed_from:
        conditions.append(action.c.completed_at >= completed_from)
    if completed_to:
        conditions.append(action.c.completed_at <= completed_to)

    columns = [
        action.c.action_history_id,
        action.c.inspection_history_id,
        action.c.category_id,
        category.c.category,
        category.c.category_name,
        category.c.level.label("category_level"),
        action.c.handler_uid,
        func.coalesce(handler.c.name, action.c.handler_name).label("handler_name"),
        action.c.approver_uid,
        func.coalesce(approver.c.name, action.c.approver_name).label("approver_name"),
        action.c.action_name,
        action.c.source_type,
        action.c.source_id,
        action.c.location,
        action.c.created_at,
        action.c.completed_at,
        action.c.action_status,
        action.c.content,
        action.c.approval_status,
        action.c.approval_date,
        action.c.rejection_reason,
    ]
    summary_row = db.execute(
        select(
            func.count().label("total"),
            func.coalesce(
                func.sum(case((action.c.action_status == "조치 대기", 1), else_=0)),
                0,
            ).label("waiting"),
            func.coalesce(
                func.sum(case((action.c.action_status == "조치 완료", 1), else_=0)),
                0,
            ).label("completed"),
            func.coalesce(
                func.sum(
                    case((action.c.approval_status == "승인 대기", 1), else_=0)
                ),
                0,
            ).label("pending_approval"),
            func.coalesce(
                func.sum(case((action.c.handler_uid.is_(None), 1), else_=0)),
                0,
            ).label("unassigned"),
        )
        .select_from(source)
        .where(*conditions)
    ).mappings().one()
    rows = db.execute(
        select(*columns)
        .select_from(source)
        .where(*conditions)
        .order_by(action.c.created_at.desc(), action.c.action_history_id.desc())
        .offset(offset)
        .limit(limit)
    ).mappings()
    total = int(summary_row["total"])
    return {
        "items": [dict(row) for row in rows],
        "total_items": total,
        "offset": offset,
        "limit": limit,
        "summary": {
            "total_count": total,
            "waiting_count": int(summary_row["waiting"]),
            "completed_count": int(summary_row["completed"]),
            "pending_approval_count": int(summary_row["pending_approval"]),
            "unassigned_count": int(summary_row["unassigned"]),
        },
    }
