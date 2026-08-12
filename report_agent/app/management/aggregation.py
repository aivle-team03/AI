from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from app.management.schemas import SiteAnomalyReportRequest

RISK_SCORE = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "상": 3,
    "중": 2,
    "하": 1,
}


def _row_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "model_dump"):
        return row.model_dump(mode="json")
    return dict(row or {})


def _rows(req: SiteAnomalyReportRequest) -> list[dict[str, Any]]:
    return [_row_dict(row) for row in req.final_history_rows]


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


def _period(rows: list[dict[str, Any]]) -> dict[str, str]:
    dates = sorted(
        _date_key(row.get("inspection_date") or row.get("completed_at"))
        for row in rows
    )
    dates = [date for date in dates if date != "-"]
    if not dates:
        return {"start_date": "-", "end_date": "-"}
    return {"start_date": dates[0], "end_date": dates[-1]}


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


def _has_action(row: dict[str, Any]) -> bool:
    return bool(row.get("action_name") or row.get("completed_at") or row.get("content"))


def _action_completed(row: dict[str, Any]) -> bool:
    return _has_action(row) and bool(row.get("completed_at") or row.get("content"))


def _approval_completed(row: dict[str, Any]) -> bool:
    return bool(row.get("approver_name"))


def _source_id(row: dict[str, Any]) -> str:
    parts = [
        row.get("inspection_date") or row.get("completed_at") or "-",
        row.get("inspection_location") or row.get("action_location") or "-",
        row.get("category_name") or row.get("category") or "-",
    ]
    return "|".join(str(part) for part in parts)


def _record_context(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": _source_id(row),
        "type": row.get("type"),
        "date": _date_text(row.get("inspection_date") or row.get("completed_at")),
        "location": row.get("inspection_location") or row.get("action_location") or "-",
        "risk_type": row.get("category_name") or "-",
        "risk": row.get("risk"),
        "risk_band": _risk_band(row.get("risk")),
        "inspection_name": row.get("category"),
        "inspection_content": row.get("inspection_content"),
        "action_name": row.get("action_name"),
        "action_content": row.get("content"),
        "action_completed": _action_completed(row),
        "approval_completed": _approval_completed(row),
        "approval_name": row.get("approver_name"),
        "before_image_url": row.get("image_url"),
    }


def _pending_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if not _has_action(row) or not _approval_completed(row)
    ]


def _severity_for_group(
    count: int,
    max_score: int,
    pending_count: int,
    recurrence_after_action_count: int,
) -> str:
    if max_score >= 4 or (max_score >= 3 and pending_count > 0):
        return "HIGH"
    if recurrence_after_action_count > 0 or count >= 3 or max_score >= 3:
        return "MEDIUM"
    return "LOW"


def aggregate_site_anomaly_data(req: SiteAnomalyReportRequest) -> dict[str, Any]:
    rows = _rows(req)
    inspection_rows = [
        row for row in rows
        if row.get("inspection_content")
    ]
    review_rows = [
        row for row in rows
        if row.get("inspection_content")
        or row.get("action_name")
        or row.get("completed_at")
        or row.get("content")
    ]
    contexts = [_record_context(row) for row in review_rows]

    grouped_records: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for context in contexts:
        grouped_records[(context["location"], context["risk_type"])].append(context)

    anomaly_candidates = []
    for (location, risk_type), records in grouped_records.items():
        if len(records) < 2:
            continue

        pending_items = [
            record for record in records
            if not record["action_completed"] or not record["approval_completed"]
        ]
        completed_action_dates = [
            _parse_datetime(record.get("date"))
            for record in records
            if record["action_completed"]
        ]
        completed_action_dates = [date for date in completed_action_dates if date]
        latest_completed_at = max(completed_action_dates) if completed_action_dates else None
        recurrence_after_action_count = 0
        if latest_completed_at:
            recurrence_after_action_count = sum(
                1
                for record in records
                if (_parse_datetime(record["date"]) or datetime.min) > latest_completed_at
            )

        max_score = max(_risk_score(record.get("risk")) for record in records)
        latest_record = max(
            records,
            key=lambda record: _parse_datetime(record["date"]) or datetime.min,
        )
        severity = _severity_for_group(
            len(records),
            max_score,
            len(pending_items),
            recurrence_after_action_count,
        )

        reasons = [f"same location and same risk type repeated {len(records)} times"]
        if max_score >= 4:
            reasons.append("critical risk included")
        elif max_score >= 3:
            reasons.append("high risk included")
        if pending_items:
            reasons.append(f"{len(pending_items)} items require action or approval follow-up")
        if recurrence_after_action_count:
            reasons.append("similar pattern appears after previous action date")

        anomaly_candidates.append(
            {
                "pattern_type": "REPEATED_LOCATION_CATEGORY",
                "location": location,
                "risk_type": risk_type,
                "count": len(records),
                "severity": severity,
                "max_risk_score": max_score,
                "source_ids": [record["source_id"] for record in records],
                "latest_record_date": latest_record["date"],
                "pending_source_ids": [record["source_id"] for record in pending_items],
                "recurrence_after_action_count": recurrence_after_action_count,
                "why_flagged": "; ".join(reasons),
                "field_check_points": [
                    "동일 장소에서 동일 위험요인이 반복되는지 확인한다.",
                    "기존 조치 이후 재발 방지 효과가 있었는지 확인한다.",
                    "지연된 조치 또는 승인 대기 항목이 있는지 확인한다.",
                    "같은 항목에 대해서 조치가 여러 번 있는지 확인한다."
                ],
            }
        )

    anomaly_candidates = sorted(
        anomaly_candidates,
        key=lambda item: (
            {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(item["severity"], 0),
            item["count"],
            item["max_risk_score"],
        ),
        reverse=True,
    )

    pending_items = _pending_records(review_rows)
    high_records = [
        row for row in review_rows
        if _risk_band(row.get("risk")) in {"CRITICAL", "HIGH"}
    ]
    event_counts_by_day = Counter(
        _date_key(row.get("inspection_date") or row.get("completed_at"))
        for row in review_rows
    )
    risk_type_counts = Counter(str(row.get("category_name") or "-") for row in review_rows)
    location_counts = Counter(
        str(row.get("inspection_location") or row.get("action_location") or "-")
        for row in review_rows
    )

    return {
        "site_context": {
            "company": req.company or {},
            "period": _period(inspection_rows),
            "audience": "MANAGEMENT_RESPONSIBLE",
            "report_type": "MANAGEMENT_REVIEW_ORDER",
            "data_source": "preprocessed_final_history_rows.final_history_rows",
        },
        "summary_counts": {
            "total_records": len(rows),
            "inspection_records": len(inspection_rows),
            "review_records": len(review_rows),
            "high_risk_records": len(high_records),
            "pending_or_unapproved_records": len(pending_items),
            "repeated_risk_groups": len(anomaly_candidates),
        },
        "anomaly_candidates": anomaly_candidates,
        "action_context": [_record_context(row) for row in pending_items],
        "recent_records": sorted(
            contexts,
            key=lambda record: _parse_datetime(record["date"]) or datetime.min,
            reverse=True,
        )[:10],
        "distributions": {
            "record_counts_by_day": dict(sorted(event_counts_by_day.items())),
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
            "record_source_ids": [
                _source_id(row) for row in review_rows
            ],
        },
        "constraints": {
            "do_not_infer_root_cause": True,
            "recommend_management_level_directives": True,
            "require_source_id_basis": True,
        },
    }


def aggregate_management_review_order_data(request: SiteAnomalyReportRequest) -> dict[str, Any]:
    return aggregate_site_anomaly_data(request)
