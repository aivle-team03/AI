from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from app.risk_assessment.schemas import RiskAssessmentReportRequest

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


def _rows(req: RiskAssessmentReportRequest) -> list[dict[str, Any]]:
    return [_row_dict(row) for row in req.final_history_rows]


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


def _period(rows: list[dict[str, Any]]) -> dict[str, str]:
    dates = sorted(
        _date_key(row.get("inspection_date") or row.get("action_date"))
        for row in rows
    )
    dates = [date for date in dates if date != "-"]
    if not dates:
        return {"start_date": "-", "end_date": "-"}
    return {"start_date": dates[0], "end_date": dates[-1]}


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


def _has_action(row: dict[str, Any]) -> bool:
    return bool(row.get("action_name") or row.get("completed_at") or row.get("content"))


def _board_action_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if _has_action(row)
        and str(row.get("source_type") or row.get("type") or "").strip() == "게시판"
    ]

def _cctv_action_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if _has_action(row)
        and str(row.get("source_type") or row.get("type") or "").strip() == "이벤트"
    ]


def _inspection_action_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if _has_action(row) and str(row.get("type") or "").strip() == "점검이력"
    ]

def _recurrence_rows(inspection_rows):
    return [
        row
        for row in inspection_rows
        if _has_action(row)
    ]

def _action_completed(row: dict[str, Any]) -> bool:
    return _has_action(row) and bool(row.get("completed_at") or row.get("content"))


def _approval_completed(row: dict[str, Any]) -> bool:
    return bool(row.get("approver_name"))


def _source_id(row: dict[str, Any]) -> str:
    return str(
        row.get("event_id")
        or row.get("inspection_history_id")
        or row.get("action_history_id")
        or row.get("case")
        or row.get("inspection_date")
        or row.get("completed_at")
        or "-"
    )


def _high_risk_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": _source_id(row),
        "inspection_history_id": row.get("inspection_history_id"),
        "action_history_id": row.get("action_history_id"),
        "category_name": row.get("category_name"),
        "risk": row.get("risk"),
        "risk_band": _risk_band(row.get("risk")),
        "location": row.get("inspection_location") or row.get("action_location"),
        "inspection_date": row.get("inspection_date"),
        "inspection_name": row.get("category"),
        "inspection_content": row.get("inspection_content"),
        "action_name": row.get("action_name"),
        "action_date": row.get("completed_at"),
        "action_content": row.get("content"),
        "action_completed": _action_completed(row),
        "approval_completed": _approval_completed(row),
        "approval_name": row.get("approver_name"),
        "date" : row.get("inspection_date") or row.get("completed_at"),
        "handler" :  row.get("handler_name") or row.get("inspection_user_name"),
    }


def aggregate_risk_assessment_report_data(req: RiskAssessmentReportRequest) -> dict[str, Any]:
    rows = _rows(req)
    inspection_rows = [row for row in rows if row.get("inspection_content")]
    # 위험성평가보고서는 평가 항목 기준으로 KPI를 계산한다.
    # board/event 조치 이력 행을 섞으면 평가 10건보다 조치 건수가 커지는 모순이 생긴다.
    action_rows = [row for row in inspection_rows if _has_action(row)]
    completed_action_rows = [row for row in inspection_rows if _action_completed(row)]
    approved_action_rows = [row for row in inspection_rows if _approval_completed(row)]


    daily_counts: Counter = Counter()
    weekly_counts: Counter = Counter()
    daily_high_counts: Counter = Counter()
    risk_band_counts: Counter = Counter()
    category_counts: Counter = Counter()
    location_counts: Counter = Counter()
    category_risk_counts: dict[str, Counter] = defaultdict(Counter)

    for row in inspection_rows:
        day = _date_key(row.get("inspection_date") or row.get("action_date"))
        week = _week_key(row.get("inspection_date") or row.get("action_date"))
        band = _risk_band(row.get("risk"))
        category_name = str(row.get("category_name") or "-")
        location = str(row.get("inspection_location") or row.get("action_location") or "-")

        daily_counts[day] += 1
        weekly_counts[week] += 1
        risk_band_counts[band] += 1
        category_counts[category_name] += 1
        location_counts[location] += 1
        category_risk_counts[category_name][band] += 1
        if band in {"CRITICAL", "HIGH"}:
            daily_high_counts[day] += 1

    high_risk_rows = [
        row for row in inspection_rows
        if _risk_band(row.get("risk")) in {"CRITICAL", "HIGH"}
    ]

    daily_counts_dict = dict(sorted(daily_counts.items()))
    weekly_counts_dict = dict(sorted(weekly_counts.items()))
    daily_high_counts_dict = dict(sorted(daily_high_counts.items()))

    high_risk_items = sorted(
        [_high_risk_item(row) for row in high_risk_rows],
        key=lambda item: (
            RISK_SCORE.get(str(item.get("risk_band") or "").upper(), 0),
            item.get("inspection_date") or "",
        ),
        reverse=True,
    )

    return {
        "report_context": {
            "company": req.company or {},
            "period": _period(inspection_rows),
            "audience": "RISK_ASSESSMENT_REPORT",
            "report_type": "RISK_ASSESSMENT_REPORT",
            "data_source": "preprocessed_final_history_rows.vfinal_history_rows",
            "excluded_scope": [
                "anomaly_pattern_analysis",
                "improvement_recommendation_report",
            ],
        },
        "kpi": {
            "total_records": len(rows),
            "assessment_records": len(inspection_rows),
            "critical_risk_records": risk_band_counts.get("CRITICAL", 0),
            "high_risk_records": risk_band_counts.get("HIGH", 0),
            "medium_risk_records": risk_band_counts.get("MEDIUM", 0),
            "low_risk_records": risk_band_counts.get("LOW", 0),
            "high_or_critical_risk_records": len(high_risk_rows),
            "high_or_critical_risk_rate":  _round_rate(len(high_risk_rows),len(inspection_rows)),
            "board_action_history_rate": _round_rate(len(_board_action_rows(rows)), len(rows)),     # 종사가가 추가한 조치항목
            "cctv_action_history_rate":  _round_rate(len(_cctv_action_rows(rows)), len(rows)),      # CCTV가 추가한 조치항목
            "risk_recurrence_rate": _round_rate( len (_recurrence_rows(inspection_rows)), len(inspection_rows)),
            "action_total": len(action_rows),
            "action_completed": len(completed_action_rows),
            "action_completion_rate": _round_rate(len(completed_action_rows), len(inspection_rows)),
            "approval_completed": len(approved_action_rows),
            "approval_completion_rate": _round_rate(len(_inspection_action_rows(action_rows)), len(inspection_rows)),


        },
        "trend": {
            "daily_assessment_counts": daily_counts_dict,
            "weekly_assessment_counts": weekly_counts_dict,
            "daily_high_risk_counts": daily_high_counts_dict,
            "assessment_trend_delta": _trend_delta(daily_counts_dict),
            "weekly_trend_delta": _trend_delta(weekly_counts_dict),
            "high_risk_trend_delta": _trend_delta(daily_high_counts_dict),
        },
        "risk_distribution": {
            "risk_band_counts": dict(risk_band_counts),
            "category_counts": dict(category_counts),
            "location_counts": dict(location_counts),
            "category_risk_counts": {
                category: dict(counts) for category, counts in category_risk_counts.items()
            },
        },
        "high_risk_items": high_risk_items[:20],
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
            "high_risk_items": high_risk_items[:10],
        },
        "constraints": {
            "do_not_include_anomaly_patterns": True,
            "do_not_include_improvement_recommendations": True,
            "use_only_corrected_rows": True,
            "do_not_infer_root_cause": True,
        },
    }

