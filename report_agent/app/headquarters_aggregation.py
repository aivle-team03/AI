from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from app.schemas import HeadquartersReportRequest

RISK_SCORE = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
}


def _row_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "model_dump"):
        return row.model_dump(mode="json")
    return dict(row or {})


def _rows(req: HeadquartersReportRequest) -> list[dict[str, Any]]:
    return [_row_dict(row) for row in req.corrected_rows]


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


def _risk_score(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = str(value or "").strip().upper()
    if text.isdigit():
        return int(text)
    return RISK_SCORE.get(text, 0)


def _risk_band(value: Any) -> str:
    score = _risk_score(value)
    if score >= 4:
        return "CRITICAL"
    if score >= 3:
        return "HIGH"
    if score >= 2:
        return "MEDIUM"
    if score >= 1:
        return "LOW"
    return "UNKNOWN"


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


def _top_counts(counter: Counter, limit: int = 5) -> list[dict[str, Any]]:
    return [
        {"name": name, "count": count}
        for name, count in counter.most_common(limit)
    ]


def _has_action(row: dict[str, Any]) -> bool:
    return bool(row.get("action_history_id"))


def _is_action_completed(row: dict[str, Any]) -> bool:
    return _has_action(row) and bool(row.get("action_date") or row.get("action_content"))


def _is_approval_completed(row: dict[str, Any]) -> bool:
    return bool(row.get("approval_name"))


def _source_id(row: dict[str, Any]) -> str:
    return str(
        row.get("event_id")
        or row.get("inspection_history_id")
        or row.get("action_history_id")
        or row.get("case")
        or "-"
    )


def aggregate_headquarters_data(req: HeadquartersReportRequest) -> dict[str, Any]:
    rows = _rows(req)
    inspection_rows = [row for row in rows if row.get("inspection_history_id")]
    action_rows = [row for row in rows if _has_action(row)]
    completed_action_rows = [row for row in action_rows if _is_action_completed(row)]
    pending_action_rows = [row for row in action_rows if not _is_action_completed(row)]
    unaddressed_inspection_rows = [row for row in inspection_rows if not _has_action(row)]
    approved_rows = [row for row in action_rows if _is_approval_completed(row)]

    date_values = [_date_key(row.get("inspection_date") or row.get("action_date")) for row in rows]
    period = _period(date_values)

    category_counts: Counter = Counter()
    location_counts: Counter = Counter()
    daily_counts: Counter = Counter()
    weekly_counts: Counter = Counter()
    daily_high_counts: Counter = Counter()
    risk_band_counts: Counter = Counter()
    category_daily_counts: dict[str, Counter] = defaultdict(Counter)
    location_daily_counts: dict[str, Counter] = defaultdict(Counter)
    repeated_groups: dict[tuple[str, str], list[str]] = defaultdict(list)

    for row in inspection_rows:
        category_name = str(row.get("category_name") or "-")
        location = str(row.get("inspection_location") or row.get("action_location") or "-")
        day = _date_key(row.get("inspection_date") or row.get("action_date"))
        band = _risk_band(row.get("risk"))
        source_id = _source_id(row)

        category_counts[category_name] += 1
        location_counts[location] += 1
        daily_counts[day] += 1
        weekly_counts[_week_key(row.get("inspection_date") or row.get("action_date"))] += 1
        category_daily_counts[category_name][day] += 1
        location_daily_counts[location][day] += 1
        risk_band_counts[band] += 1
        repeated_groups[(location, category_name)].append(source_id)
        if band in {"CRITICAL", "HIGH"}:
            daily_high_counts[day] += 1

    repeated_risks = [
        {
            "location": location,
            "category_name": category_name,
            "count": len(source_ids),
            "source_ids": source_ids,
        }
        for (location, category_name), source_ids in repeated_groups.items()
        if len(source_ids) >= 2
    ]

    unresolved_high_risk_ids = [
        _source_id(row)
        for row in inspection_rows
        if _risk_band(row.get("risk")) in {"CRITICAL", "HIGH"} and not _has_action(row)
    ]

    daily_counts_dict = dict(sorted(daily_counts.items()))
    weekly_counts_dict = dict(sorted(weekly_counts.items()))
    daily_high_counts_dict = dict(sorted(daily_high_counts.items()))

    return {
        "company": req.company or {},
        "data_source": {
            "name": "final_history_table_corrected.corrected_rows",
            "row_count": len(rows),
            "input_shape": "corrected_final_history_table",
        },
        "period": period,
        "kpi": {
            "total_records": len(rows),
            "inspection_records": len(inspection_rows),
            "critical_risk_records": risk_band_counts.get("CRITICAL", 0),
            "high_risk_records": risk_band_counts.get("HIGH", 0),
            "medium_risk_records": risk_band_counts.get("MEDIUM", 0),
            "low_risk_records": risk_band_counts.get("LOW", 0),
            "action_total": len(action_rows),
            "action_completed": len(completed_action_rows),
            "action_waiting": len(pending_action_rows),
            "action_completion_rate": _round_rate(len(completed_action_rows), len(action_rows)),
            "approval_completed": len(approved_rows),
            "approval_waiting": len(action_rows) - len(approved_rows),
            "approval_completion_rate": _round_rate(len(approved_rows), len(action_rows)),
            "high_risk_ratio": _round_rate(
                risk_band_counts.get("CRITICAL", 0) + risk_band_counts.get("HIGH", 0),
                len(inspection_rows),
            ),
            "pending_action_rate": _round_rate(len(pending_action_rows), len(action_rows)),
        },
        "trend": {
            "daily_record_counts": daily_counts_dict,
            "weekly_record_counts": weekly_counts_dict,
            "daily_high_risk_counts": daily_high_counts_dict,
            "record_trend_delta": _trend_delta(daily_counts_dict),
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
            "risk_band_counts": dict(risk_band_counts),
            "action_status_counts": {
                "completed": len(completed_action_rows),
                "waiting": len(pending_action_rows),
                "unaddressed_inspections": len(unaddressed_inspection_rows),
            },
            "approval_status_counts": {
                "approved": len(approved_rows),
                "waiting": len(action_rows) - len(approved_rows),
            },
            "type_counts": dict(Counter(str(row.get("type") or "-") for row in rows)),
        },
        "rankings": {
            "top_categories": _top_counts(category_counts),
            "top_locations": _top_counts(location_counts),
            "top_repeated_risks": sorted(
                repeated_risks,
                key=lambda item: item["count"],
                reverse=True,
            )[:5],
        },
        "risk_flags": {
            "repeated_risks": repeated_risks,
            "unresolved_high_risk_source_ids": unresolved_high_risk_ids,
            "pending_action_ids": [
                row.get("action_history_id") for row in pending_action_rows
            ],
            "unaddressed_inspection_history_ids": [
                row.get("inspection_history_id") for row in unaddressed_inspection_rows
            ],
        },
        "source_ids": {
            "inspection_history_ids": [
                row.get("inspection_history_id") for row in inspection_rows
            ],
            "action_history_ids": [
                row.get("action_history_id") for row in action_rows
            ],
            "event_ids": [row.get("event_id") for row in rows if row.get("event_id")],
        },
        "source_samples": {
            "high_risk_records": [
                row for row in inspection_rows
                if _risk_band(row.get("risk")) in {"CRITICAL", "HIGH"}
            ][:10],
            "pending_action_records": pending_action_rows[:10],
            "unaddressed_inspection_records": unaddressed_inspection_rows[:10],
        },
    }

