from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from app.schemas import HeadquartersReportRequest


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _date_key(value: Any) -> str:
    parsed = _parse_datetime(value)
    return parsed.date().isoformat() if parsed else "-"


def _week_key(value: Any) -> str:
    parsed = _parse_datetime(value)
    if not parsed:
        return "-"
    year, week, _ = parsed.isocalendar()
    return f"{year}-W{week:02d}"


def _round_rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 1) if denominator else 0.0


def _normalized_text(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("_", "")


def _is_action_completed(value: Any) -> bool:
    normalized = _normalized_text(value)
    return normalized in {"조치완료", "완료", "completed", "complete", "done", "approved"}


def _is_approval_completed(value: Any) -> bool:
    normalized = _normalized_text(value)
    return normalized in {"승인완료", "승인", "approved", "complete", "completed"}


def _is_approval_waiting(value: Any) -> bool:
    normalized = _normalized_text(value)
    return normalized in {"승인대기", "대기", "waiting", "pending"}


def _is_approval_rejected(value: Any) -> bool:
    normalized = _normalized_text(value)
    return normalized in {"반려", "거절", "rejected", "reject", "denied"}


def _is_education_completed(value: Any) -> bool:
    normalized = _normalized_text(value)
    return normalized in {"이수", "완료", "completed", "complete", "done"}


def _top_counts(counter: Counter, limit: int = 5) -> list[dict[str, Any]]:
    return [
        {"name": name, "count": count}
        for name, count in counter.most_common(limit)
    ]


def _period(dates: list[str]) -> dict[str, str]:
    valid_dates = sorted(date for date in dates if date != "-")
    if not valid_dates:
        return {"start_date": "-", "end_date": "-"}
    return {"start_date": valid_dates[0], "end_date": valid_dates[-1]}


def _trend_delta(series: dict[str, int]) -> dict[str, Any]:
    values = [value for key, value in sorted(series.items()) if key != "-"]
    if len(values) < 2:
        return {
            "first_value": values[0] if values else 0,
            "last_value": values[-1] if values else 0,
            "delta": 0,
            "delta_rate": 0.0,
            "direction": "FLAT",
        }

    first_value = values[0]
    last_value = values[-1]
    delta = last_value - first_value
    if delta > 0:
        direction = "UP"
    elif delta < 0:
        direction = "DOWN"
    else:
        direction = "FLAT"

    return {
        "first_value": first_value,
        "last_value": last_value,
        "delta": delta,
        "delta_rate": round(delta / first_value * 100, 1) if first_value else None,
        "direction": direction,
    }


def _status_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(Counter(str(item.get(key) or "-") for item in items))


def aggregate_headquarters_data(req: HeadquartersReportRequest) -> dict[str, Any]:
    category_by_id = {item.get("category_id"): item for item in req.event_category}
    cctv_by_id = {item.get("cctv_id"): item for item in req.cctv}
    actions_by_event = _group_by(req.action_history, "event_id")

    event_dates = [_date_key(event.get("date")) for event in req.event]
    period = _period(event_dates)

    high_events = []
    medium_events = []
    low_events = []
    category_counts: Counter = Counter()
    location_counts: Counter = Counter()
    daily_counts: Counter = Counter()
    weekly_counts: Counter = Counter()
    daily_high_counts: Counter = Counter()
    category_daily_counts: dict[str, Counter] = defaultdict(Counter)
    location_daily_counts: dict[str, Counter] = defaultdict(Counter)
    repeated_groups: dict[tuple[str, str], list[str]] = defaultdict(list)

    for event in req.event:
        category = category_by_id.get(event.get("category_id"), {})
        cctv = cctv_by_id.get(event.get("cctv_id"), {})
        event_id = str(event.get("event_id"))
        category_name = str(category.get("category_name", "-"))
        location = str(cctv.get("location", "-"))
        level = int(category.get("level") or 0)
        day = _date_key(event.get("date"))

        category_counts[category_name] += 1
        location_counts[location] += 1
        daily_counts[day] += 1
        weekly_counts[_week_key(event.get("date"))] += 1
        category_daily_counts[category_name][day] += 1
        location_daily_counts[location][day] += 1
        repeated_groups[(location, category_name)].append(event_id)

        if level >= 8:
            high_events.append(event)
            daily_high_counts[day] += 1
        elif level >= 5:
            medium_events.append(event)
        else:
            low_events.append(event)

    completed_actions = [
        action for action in req.action_history
        if _is_action_completed(action.get("action_status"))
    ]
    pending_actions = [
        action for action in req.action_history
        if not _is_action_completed(action.get("action_status"))
    ]
    approved_actions = [
        action for action in req.action_history
        if _is_approval_completed(action.get("approval_status"))
    ]
    approval_waiting_actions = [
        action for action in req.action_history
        if _is_approval_waiting(action.get("approval_status"))
    ]
    rejected_actions = [
        action for action in req.action_history
        if _is_approval_rejected(action.get("approval_status"))
    ]

    action_minutes = []
    for action in completed_actions:
        created_at = _parse_datetime(action.get("created_at"))
        completed_at = _parse_datetime(action.get("completed_at"))
        if created_at and completed_at and completed_at >= created_at:
            action_minutes.append((completed_at - created_at).total_seconds() / 60)

    high_event_ids = {event.get("event_id") for event in high_events}
    unresolved_high_risk_events = [
        str(action.get("event_id"))
        for action in pending_actions
        if action.get("event_id") in high_event_ids
    ]

    repeated_risks = [
        {
            "location": location,
            "category_name": category_name,
            "count": len(event_ids),
            "event_ids": event_ids,
        }
        for (location, category_name), event_ids in repeated_groups.items()
        if len(event_ids) >= 2
    ]

    education_completed = [
        item for item in req.education_status
        if _is_education_completed(item.get("status"))
    ]

    daily_counts_dict = dict(sorted(daily_counts.items()))
    weekly_counts_dict = dict(sorted(weekly_counts.items()))
    daily_high_counts_dict = dict(sorted(daily_high_counts.items()))

    return {
        "company": req.company or {},
        "period": period,
        "kpi": {
            "total_events": len(req.event),
            "high_risk_events": len(high_events),
            "medium_risk_events": len(medium_events),
            "low_risk_events": len(low_events),
            "action_total": len(req.action_history),
            "action_completed": len(completed_actions),
            "action_waiting": len(pending_actions),
            "action_completion_rate": _round_rate(
                len(completed_actions),
                len(req.action_history),
            ),
            "approval_completed": len(approved_actions),
            "approval_waiting": len(approval_waiting_actions),
            "approval_rejected": len(rejected_actions),
            "average_action_minutes": (
                round(sum(action_minutes) / len(action_minutes), 1)
                if action_minutes
                else None
            ),
            "education_target_count": len(req.education_status),
            "education_completed_count": len(education_completed),
            "education_completion_rate": _round_rate(
                len(education_completed),
                len(req.education_status),
            ),
            "high_risk_ratio": _round_rate(len(high_events), len(req.event)),
            "pending_action_rate": _round_rate(
                len(pending_actions),
                len(req.action_history),
            ),
            "approval_completion_rate": _round_rate(
                len(approved_actions),
                len(req.action_history),
            ),
        },
        "trend": {
            "daily_event_counts": daily_counts_dict,
            "weekly_event_counts": weekly_counts_dict,
            "daily_high_risk_counts": daily_high_counts_dict,
            "event_trend_delta": _trend_delta(daily_counts_dict),
            "weekly_trend_delta": _trend_delta(weekly_counts_dict),
            "high_risk_trend_delta": _trend_delta(daily_high_counts_dict),
            "category_daily_counts": {
                key: dict(sorted(value.items()))
                for key, value in category_daily_counts.items()
            },
            "location_daily_counts": {
                key: dict(sorted(value.items()))
                for key, value in location_daily_counts.items()
            },
        },
        "status_distribution": {
            "action_status_counts": _status_counts(req.action_history, "action_status"),
            "approval_status_counts": _status_counts(
                req.action_history,
                "approval_status",
            ),
            "education_status_counts": _status_counts(req.education_status, "status"),
            "checklist_status_counts": _status_counts(req.checklist, "status"),
        },
        "rankings": {
            "top_categories": _top_counts(category_counts),
            "top_locations": _top_counts(location_counts),
            "top_delayed_actions": _top_delayed_actions(req.action_history),
        },
        "risk_flags": {
            "repeated_risks": repeated_risks,
            "unresolved_high_risk_event_ids": unresolved_high_risk_events,
            "pending_action_ids": [
                action.get("action_history_id") for action in pending_actions
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
        "source_samples": {
            "high_risk_events": _event_samples(high_events, category_by_id, cctv_by_id),
            "pending_actions": pending_actions[:10],
        },
    }


def _group_by(items: list[dict[str, Any]], key: str) -> dict[Any, list[dict[str, Any]]]:
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(item.get(key), []).append(item)
    return grouped


def _top_delayed_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    delayed = []
    for action in actions:
        created_at = _parse_datetime(action.get("created_at"))
        completed_at = _parse_datetime(action.get("completed_at"))
        if not created_at or not completed_at or completed_at < created_at:
            continue

        delayed.append(
            {
                "action_history_id": action.get("action_history_id"),
                "event_id": action.get("event_id"),
                "action_name": action.get("action_name"),
                "handler_name": action.get("handler_name"),
                "minutes": round((completed_at - created_at).total_seconds() / 60, 1),
            }
        )

    return sorted(delayed, key=lambda item: item["minutes"], reverse=True)[:5]


def _event_samples(
    events: list[dict[str, Any]],
    category_by_id: dict[Any, dict[str, Any]],
    cctv_by_id: dict[Any, dict[str, Any]],
) -> list[dict[str, Any]]:
    samples = []
    for event in events[:10]:
        category = category_by_id.get(event.get("category_id"), {})
        cctv = cctv_by_id.get(event.get("cctv_id"), {})
        samples.append(
            {
                "event_id": event.get("event_id"),
                "date": event.get("date"),
                "category_name": category.get("category_name"),
                "level": category.get("level"),
                "location": cctv.get("location"),
                "image_url": event.get("image_url"),
            }
        )
    return samples
