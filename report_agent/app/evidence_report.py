from collections import Counter
from typing import Any

from app.schemas import EvidenceContentRequest, EvidenceContentResponse


def _value(data: dict[str, Any] | None, key: str, default: str = "-") -> Any:
    if not data:
        return default
    value = data.get(key)
    return default if value is None or value == "" else value


def _date_text(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value).replace("T", " ")


def _ids(items: list[dict[str, Any]], key: str) -> list[Any]:
    return [item[key] for item in items if item.get(key) is not None]


def _group_by(items: list[dict[str, Any]], key: str) -> dict[Any, list[dict[str, Any]]]:
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(item.get(key), []).append(item)
    return grouped


def _count_by(items: list[dict[str, Any]], key: str) -> str:
    counts = Counter(str(item.get(key)) for item in items if item.get(key))
    if not counts:
        return "-"
    return ", ".join(f"{name} {count}건" for name, count in counts.items())


def _event_location_counts(
    events: list[dict[str, Any]],
    cctv_by_id: dict[Any, dict[str, Any]],
) -> str:
    locations = []
    for event in events:
        cctv = cctv_by_id.get(event.get("cctv_id"), {})
        locations.append(str(_value(cctv, "location", str(event.get("cctv_id", "-")))))

    counts = Counter(location for location in locations if location != "-")
    if not counts:
        return "-"
    return ", ".join(f"{location} {count}건" for location, count in counts.items())


def _period(req: EvidenceContentRequest) -> str:
    dates = []
    for item in [*req.event, *req.checklist, *req.inspection_history]:
        value = item.get("date") or item.get("created_at")
        if value:
            dates.append(str(value)[:10])
    if not dates:
        return "-"
    return f"{min(dates)} ~ {max(dates)}"


def _writer_name(req: EvidenceContentRequest) -> str:
    writer = _value(req.report, "writer", "")
    if writer:
        return writer

    report_uid = _value(req.report, "uid", None)
    for item in req.user:
        if report_uid is not None and item.get("uid") == report_uid:
            return str(_value(item, "name"))
    return str(_value(req.user[0] if req.user else None, "name"))


def build_evidence_content(req: EvidenceContentRequest) -> EvidenceContentResponse:
    company_name = _value(req.company, "company_name")
    writer_name = _writer_name(req)
    period = _period(req)
    summary = f"{company_name} {period} 위험성 평가보고서"

    category_by_id = {item.get("category_id"): item for item in req.event_category}
    cctv_by_id = {item.get("cctv_id"): item for item in req.cctv}
    checklists_by_event = _group_by(req.checklist, "event_id")
    actions_by_event = _group_by(req.action_history, "event_id")

    content: list[str] = [
        "# 위험성 평가보고서",
        "",
        f"- 회사: {company_name}",
        f"- 작성자: {writer_name}",
        f"- 보고 기간: {period}",
        "",
        "## 요약",
        f"- 이벤트 수: {len(req.event)}건",
        f"- 체크리스트 수: {len(req.checklist)}건",
        f"- 조치 이력 수: {len(req.action_history)}건",
        f"- 점검 이력 수: {len(req.inspection_history)}건",
        f"- 교육 이수 상태 수: {len(req.education_status)}건",
        f"- 구역별 이벤트: {_event_location_counts(req.event, cctv_by_id)}",
        f"- 체크리스트 상태: {_count_by(req.checklist, 'status')}",
        f"- 조치 상태: {_count_by(req.action_history, 'action_status')}",
        f"- 승인 상태: {_count_by(req.action_history, 'approval_status')}",
        "",
        "## 이벤트 상세",
    ]

    for index, event in enumerate(req.event, start=1):
        category = category_by_id.get(event.get("category_id"), {})
        cctv = cctv_by_id.get(event.get("cctv_id"), {})
        event_id = event.get("event_id")

        content.extend(
            [
                "",
                f"### {index}. 이벤트 {_value(event, 'event_id')}",
                f"- 감지 일시: {_date_text(event.get('date'))}",
                f"- 카테고리: {_value(category, 'category_name')}",
                f"- 위험 강도: {_value(category, 'level')}",
                f"- CCTV: {_value(cctv, 'cctv_name')}",
                f"- CCTV 위치: {_value(cctv, 'location')}",
                f"- 감지 이미지: {_value(event, 'image_url')}",
                "",
                "#### 위험요인",
                f"- 위험요인: {_value(category, 'category_name')}",
                f"- 발생 위치: {_value(cctv, 'location')}",
                f"- 확인 근거: {_value(event, 'image_url')}",
                "",
                "#### 위험도",
                f"- 위험도: {_value(category, 'level')}",
                f"- 위험 분류: {_value(category, 'category')}",
                "",
                "#### 조치 내용",
            ]
        )

        _append_actions(content, actions_by_event.get(event_id, []))
        _append_checklists(content, checklists_by_event.get(event_id, []))

    _append_inspection_history(content, req.inspection_history)
    _append_education_status(content, req.education, req.education_status)
    _append_board(content, req.board)
    _append_report_maps(content, req)

    return EvidenceContentResponse(
        content="\n".join(content),
        summary=summary,
        event_ids=[str(value) for value in _ids(req.event, "event_id")],
        checklist_ids=[int(value) for value in _ids(req.checklist, "checklist_id")],
        inspection_history_ids=[
            int(value) for value in _ids(req.inspection_history, "inspection_history_id")
        ],
        action_history_ids=[
            int(value) for value in _ids(req.action_history, "action_history_id")
        ],
    )


def _append_checklists(content: list[str], checklists: list[dict[str, Any]]) -> None:
    content.append("- 체크리스트:")
    if not checklists:
        content.append("  - 없음")
        return

    for item in checklists:
        content.append(
            "  - "
            f"[{_value(item, 'checklist_id')}] "
            f"{_date_text(item.get('date'))} / "
            f"상태: {_value(item, 'status')} / "
            f"담당자 UID: {_value(item, 'uid')} / "
            f"내용: {_value(item, 'content')} / "
            f"이미지: {_value(item, 'image_url')} / "
            f"구분: {_value(item, 'type')}"
        )


def _append_actions(content: list[str], actions: list[dict[str, Any]]) -> None:
    content.append("- 조치 이력:")
    if not actions:
        content.append("  - 없음")
        return

    for item in actions:
        content.append(
            "  - "
            f"[{_value(item, 'action_history_id')}] "
            f"{_value(item, 'action_name')} / "
            f"담당자: {_value(item, 'handler_name')} / "
            f"승인자: {_value(item, 'approver_name')} / "
            f"상태: {_value(item, 'action_status')} / "
            f"완료일: {_date_text(item.get('completed_at'))} / "
            f"승인 상태: {_value(item, 'approval_status')} / "
            f"승인일: {_date_text(item.get('approval_date'))} / "
            f"반려 사유: {_value(item, 'rejection_reason')} / "
            f"내용: {_value(item, 'content')} / "
            f"이미지: {_value(item, 'image_url')}"
        )


def _append_inspection_history(
    content: list[str],
    inspection_history: list[dict[str, Any]],
) -> None:
    content.extend(["", "## 점검 이력"])
    if not inspection_history:
        content.append("- 없음")
        content.append("")
        return

    for item in inspection_history:
        content.append(
            "- "
            f"[{_value(item, 'inspection_history_id')}] "
            f"{_value(item, 'name')} / "
            f"수행자: {_value(item, 'user_name')} / "
            f"위치: {_value(item, 'location')} / "
            f"일시: {_date_text(item.get('date'))} / "
            f"상태: {_value(item, 'status')} / "
            f"조치 필요: {_value(item, 'is_action_required')} / "
            f"내용: {_value(item, 'content')}"
        )
    content.append("")


def _append_education_status(
    content: list[str],
    education: list[dict[str, Any]],
    education_status: list[dict[str, Any]],
) -> None:
    if not education and not education_status:
        return

    education_by_id = {item.get("education_id"): item for item in education}
    content.extend(["## 교육 이수 상태"])
    for item in education_status:
        course = education_by_id.get(item.get("education_id"), {})
        content.append(
            "- "
            f"{_value(item, 'user_name')} / "
            f"교육: {_value(course, 'title')} / "
            f"상태: {_value(item, 'status')} / "
            f"완료일: {_date_text(item.get('completed_date'))}"
        )
    content.append("")


def _append_board(content: list[str], board: list[dict[str, Any]]) -> None:
    if not board:
        return

    content.extend(["## 게시글"])
    for item in board:
        content.append(
            "- "
            f"[{_value(item, 'board_id')}] "
            f"{_value(item, 'title')} / "
            f"상태: {_value(item, 'status')} / "
            f"위치: {_value(item, 'location')} / "
            f"이미지: {_value(item, 'image_url')}"
        )
    content.append("")


def _append_report_maps(content: list[str], req: EvidenceContentRequest) -> None:
    content.extend(
        [
            "## 저장 매핑 대상",
            f"- report_event_map: "
            f"{', '.join(map(str, _ids(req.report_event_map, 'event_id'))) or '-'}",
            f"- report_checklist_map: "
            f"{', '.join(map(str, _ids(req.report_checklist_map, 'checklist_id'))) or '-'}",
            f"- report_inspection_map: "
            f"{', '.join(map(str, _ids(req.report_inspection_map, 'inspection_history_id'))) or '-'}",
            f"- report_action_map: "
            f"{', '.join(map(str, _ids(req.report_action_map, 'action_history_id'))) or '-'}",
            "",
        ]
    )
