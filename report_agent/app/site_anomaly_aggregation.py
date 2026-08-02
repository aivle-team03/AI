from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from app.schemas import SiteAnomalyReportRequest


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _date_text(value: Any) -> str:
    parsed = _parse_datetime(value)
    return parsed.isoformat() if parsed else str(value or "-")


def _date_key(value: Any) -> str:
    parsed = _parse_datetime(value)
    return parsed.date().isoformat() if parsed else "-"


def _normalized_text(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("_", "")


def _is_action_completed(value: Any) -> bool:
    normalized = _normalized_text(value)
    return normalized in {"조치완료", "완료", "completed", "complete", "done", "approved"}


def _is_approval_completed(value: Any) -> bool:
    normalized = _normalized_text(value)
    return normalized in {"승인완료", "승인", "approved", "complete", "completed"}


def _risk_band(level: int) -> str:
    if level >= 8:
        return "HIGH"
    if level >= 5:
        return "MEDIUM"
    return "LOW"


def _period(events: list[dict[str, Any]]) -> dict[str, str]:
    dates = sorted(_date_key(event.get("date")) for event in events)
    dates = [date for date in dates if date != "-"]
    if not dates:
        return {"start_date": "-", "end_date": "-"}
    return {"start_date": dates[0], "end_date": dates[-1]}


def _group_by(items: list[dict[str, Any]], key: str) -> dict[Any, list[dict[str, Any]]]:
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(item.get(key), []).append(item)
    return grouped


def _recent_events(
    events: list[dict[str, Any]],
    category_by_id: dict[Any, dict[str, Any]],
    cctv_by_id: dict[Any, dict[str, Any]],
    limit: int = 10,
) -> list[dict[str, Any]]:
    sorted_events = sorted(
        events,
        key=lambda event: _parse_datetime(event.get("date")) or datetime.min,
        reverse=True,
    )
    return [
        _event_context(event, category_by_id, cctv_by_id)
        for event in sorted_events[:limit]
    ]


def _event_context(
    event: dict[str, Any],
    category_by_id: dict[Any, dict[str, Any]],
    cctv_by_id: dict[Any, dict[str, Any]],
) -> dict[str, Any]:
    category = category_by_id.get(event.get("category_id"), {})
    cctv = cctv_by_id.get(event.get("cctv_id"), {})
    level = int(category.get("level") or 0)
    return {
        "event_id": event.get("event_id"),
        "date": _date_text(event.get("date")),
        "location": cctv.get("location", "-"),
        "cctv_name": cctv.get("cctv_name", "-"),
        "risk_type": category.get("category_name", "-"),
        "risk_category": category.get("category", "-"),
        "risk_level": level,
        "risk_band": _risk_band(level),
        "image_url": event.get("image_url"),
    }


def _pending_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        action
        for action in actions
        if not _is_action_completed(action.get("action_status"))
        or not _is_approval_completed(action.get("approval_status"))
    ]


def _action_context(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    context = []
    for action in actions:
        context.append(
            {
                "action_history_id": action.get("action_history_id"),
                "event_id": action.get("event_id"),
                "action_name": action.get("action_name"),
                "action_status": action.get("action_status"),
                "approval_status": action.get("approval_status"),
                "handler_name": action.get("handler_name"),
                "approver_name": action.get("approver_name"),
                "created_at": _date_text(action.get("created_at")),
                "completed_at": _date_text(action.get("completed_at")),
                "approval_date": _date_text(action.get("approval_date")),
                "content": action.get("content"),
                "image_url": action.get("image_url"),
            }
        )
    return context


def _checklist_context(checklists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "checklist_id": item.get("checklist_id"),
            "event_id": item.get("event_id"),
            "date": _date_text(item.get("date")),
            "status": item.get("status"),
            "content": item.get("content"),
            "type": item.get("type"),
            "image_url": item.get("image_url"),
        }
        for item in checklists
    ]


def _severity_for_group(
    count: int,
    max_level: int,
    pending_count: int,
    recurrence_after_action_count: int,
) -> str:
    if max_level >= 8 and (count >= 3 or pending_count > 0):
        return "HIGH"
    if recurrence_after_action_count > 0 or count >= 3 or max_level >= 8:
        return "MEDIUM"
    return "LOW"


def aggregate_site_anomaly_data(req: SiteAnomalyReportRequest) -> dict[str, Any]:
    category_by_id = {item.get("category_id"): item for item in req.event_category}
    cctv_by_id = {item.get("cctv_id"): item for item in req.cctv}
    actions_by_event = _group_by(req.action_history, "event_id")
    checklists_by_event = _group_by(req.checklist, "event_id")

    enriched_events = [
        _event_context(event, category_by_id, cctv_by_id)
        for event in req.event
    ]
    events_by_id = {event["event_id"]: event for event in enriched_events}

    grouped_events: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in enriched_events:
        grouped_events[(event["location"], event["risk_type"])].append(event)

    anomaly_candidates = []
    for (location, risk_type), events in grouped_events.items():
        if len(events) < 2:
            continue

        event_ids = [event["event_id"] for event in events]
        related_actions = [
            action
            for event_id in event_ids
            for action in actions_by_event.get(event_id, [])
        ]
        pending_actions = _pending_actions(related_actions)
        related_checklists = [
            checklist
            for event_id in event_ids
            for checklist in checklists_by_event.get(event_id, [])
        ]
        completed_action_dates = [
            _parse_datetime(action.get("completed_at"))
            for action in related_actions
            if _is_action_completed(action.get("action_status"))
        ]
        completed_action_dates = [date for date in completed_action_dates if date]
        latest_completed_at = max(completed_action_dates) if completed_action_dates else None
        recurrence_after_action_count = 0
        if latest_completed_at:
            recurrence_after_action_count = sum(
                1
                for event in events
                if (_parse_datetime(event["date"]) or datetime.min) > latest_completed_at
            )

        max_level = max(int(event["risk_level"] or 0) for event in events)
        latest_event = max(
            events,
            key=lambda event: _parse_datetime(event["date"]) or datetime.min,
        )
        pending_action_ids = [
            action.get("action_history_id")
            for action in pending_actions
            if action.get("action_history_id") is not None
        ]
        severity = _severity_for_group(
            len(events),
            max_level,
            len(pending_actions),
            recurrence_after_action_count,
        )

        reasons = [f"동일 구역/동일 위험유형이 {len(events)}회 반복"]
        if max_level >= 8:
            reasons.append(f"고위험 등급(level {max_level}) 포함")
        if pending_action_ids:
            reasons.append(f"미완료 또는 승인 대기 조치 {len(pending_action_ids)}건 존재")
        if recurrence_after_action_count:
            reasons.append("조치 완료 이후 동일 패턴 재발 가능성 존재")

        anomaly_candidates.append(
            {
                "pattern_type": "REPEATED_LOCATION_CATEGORY",
                "location": location,
                "risk_type": risk_type,
                "count": len(events),
                "severity": severity,
                "max_risk_level": max_level,
                "event_ids": event_ids,
                "latest_event_date": latest_event["date"],
                "pending_action_ids": pending_action_ids,
                "related_checklist_ids": [
                    checklist.get("checklist_id")
                    for checklist in related_checklists
                    if checklist.get("checklist_id") is not None
                ],
                "recurrence_after_action_count": recurrence_after_action_count,
                "why_flagged": "; ".join(reasons),
                "field_check_points": [
                    "동일 위치에 위험요인이 남아 있는지 현장 확인",
                    "기존 조치가 실제 재발 방지로 이어졌는지 확인",
                    "미완료/승인 대기 조치의 처리 지연 사유 확인",
                ],
            }
        )

    anomaly_candidates = sorted(
        anomaly_candidates,
        key=lambda item: (
            {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(item["severity"], 0),
            item["count"],
            item["max_risk_level"],
        ),
        reverse=True,
    )

    pending_action_items = _pending_actions(req.action_history)
    event_counts_by_day = Counter(event["date"][:10] for event in enriched_events)
    risk_type_counts = Counter(event["risk_type"] for event in enriched_events)
    location_counts = Counter(event["location"] for event in enriched_events)
    high_events = [event for event in enriched_events if event["risk_band"] == "HIGH"]

    return {
        "site_context": {
            "company": req.company or {},
            "period": _period(req.event),
            "audience": "SITE_MANAGER",
            "report_type": "ANOMALY_IMPROVEMENT_RECOMMENDATION",
        },
        "summary_counts": {
            "total_events": len(req.event),
            "high_risk_events": len(high_events),
            "pending_actions": len(pending_action_items),
            "repeated_risk_groups": len(anomaly_candidates),
            "checklist_items": len(req.checklist),
        },
        "anomaly_candidates": anomaly_candidates,
        "action_context": _action_context(pending_action_items),
        "recent_events": _recent_events(req.event, category_by_id, cctv_by_id),
        "checklist_context": _checklist_context(
            [
                checklist
                for checklist in req.checklist
                if checklist.get("event_id") in events_by_id
            ]
        ),
        "distributions": {
            "event_counts_by_day": dict(sorted(event_counts_by_day.items())),
            "top_risk_types": [
                {"name": name, "count": count}
                for name, count in risk_type_counts.most_common(5)
            ],
            "top_locations": [
                {"name": name, "count": count}
                for name, count in location_counts.most_common(5)
            ],
        },
        "source_ids": {
            "event_ids": [event.get("event_id") for event in req.event],
            "action_history_ids": [
                action.get("action_history_id") for action in req.action_history
            ],
            "checklist_ids": [
                checklist.get("checklist_id") for checklist in req.checklist
            ],
        },
        "constraints": {
            "do_not_infer_root_cause": True,
            "recommend_only_site_level_actions": True,
            "require_event_id_basis": True,
        },
    }
