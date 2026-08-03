from datetime import date, datetime
from typing import Any, Iterable, Optional


OPERATION_LABELS = {
    "list_inspections": "점검 항목",
    "get_inspection": "점검 항목 상세",
    "list_inspection_histories": "점검 이력",
    "get_inspection_history": "점검 이력 상세",
    "list_action_histories": "조치 이력",
    "get_action_history": "조치 이력 상세",
    "list_education_courses": "교육 과정",
    "get_education_course": "교육 과정 상세",
    "list_education_summaries": "과정별 교육 현황",
    "list_course_attendees": "교육 대상자 현황",
    "list_user_education_statuses": "사용자별 교육 현황",
    "get_education_overview": "전체 교육 현황",
}


def _value(value: Any, empty: str = "없음") -> str:
    if value is None or value == "":
        return empty
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _category(item: dict[str, Any]) -> str:
    values = [item.get("category"), item.get("category_name")]
    return " / ".join(str(value) for value in values if value) or "없음"


def _numbered_items(items: Iterable[dict[str, Any]], formatter) -> list[str]:
    lines = []
    for index, item in enumerate(items, start=1):
        lines.extend(formatter(index, item))
    if not lines:
        lines.append("조회된 항목이 없습니다.")
    return lines


def _format_inspection_item(index: int, item: dict[str, Any]) -> list[str]:
    return [
        f"{index}. {_value(item.get('name'))}",
        f"   - 위치: {_value(item.get('location'))}",
        f"   - 분류: {_category(item)}",
        f"   - 점검 주기: {_value(item.get('cycle'))}",
        f"   - 담당자: {_value(item.get('user_name'), '미할당')}",
        f"   - 내용: {_value(item.get('content'))}",
    ]


def _format_inspection_history_item(
    index: int,
    item: dict[str, Any],
) -> list[str]:
    return [
        f"{index}. {_value(item.get('name'))}",
        f"   - 위치: {_value(item.get('location'))}",
        f"   - 분류: {_category(item)}",
        f"   - 점검 일시: {_value(item.get('date'))}",
        f"   - 점검 상태: {_value(item.get('status'))}",
        f"   - 조치 필요: {_value(item.get('is_action_required'))}",
        f"   - 점검자: {_value(item.get('user_name'))}",
        f"   - 내용: {_value(item.get('content'))}",
    ]


def _format_action_item(index: int, item: dict[str, Any]) -> list[str]:
    lines = [
        f"{index}. {_value(item.get('action_name'))}",
        f"   - 위치: {_value(item.get('location'))}",
        f"   - 분류: {_category(item)}",
        f"   - 위험도: {_value(item.get('category_level'))}",
        f"   - 조치 상태: {_value(item.get('action_status'))}",
        f"   - 승인 상태: {_value(item.get('approval_status'))}",
        f"   - 담당자: {_value(item.get('handler_name'), '미할당')}",
        f"   - 등록 일시: {_value(item.get('created_at'))}",
        f"   - 완료 일시: {_value(item.get('completed_at'))}",
        f"   - 내용: {_value(item.get('content'))}",
    ]
    if item.get("rejection_reason"):
        lines.append(f"   - 반려 사유: {_value(item.get('rejection_reason'))}")
    return lines


def _format_inspection_action_execution(
    query: dict[str, Any],
    result: dict[str, Any],
) -> list[str]:
    operation = query.get("operation", "")
    is_detail = operation.startswith("get_")
    items = [result] if is_detail else result.get("items", [])
    lines = []

    if operation in {"list_inspection_histories", "get_inspection_history"}:
        summary = result.get("summary", {}) if not is_detail else {}
        if summary and query.get("response_mode") == "ratio":
            total_count = int(summary.get("total_count") or 0)
            action_required_count = int(
                summary.get("action_required_count") or 0
            )
            ratio = (
                round(action_required_count / total_count * 100, 1)
                if total_count
                else 0.0
            )
            return [
                "점검 완료 건 중 조치 필요 비율입니다.",
                f"- 점검 완료: {total_count}건",
                f"- 조치 필요: {action_required_count}건",
                f"- 비율: {ratio}%",
            ]
        if summary and query.get("response_mode") == "summary":
            total_count = _value(summary.get("total_count"), "0")
            status_filter = query.get("status_filter")
            if status_filter:
                return [f"{status_filter} 건수는 {total_count}건입니다."]
            return [
                "현재 점검 이력 현황입니다.",
                f"- 점검 대기: {_value(summary.get('waiting_count'), '0')}건",
                f"- 점검 완료: {_value(summary.get('completed_count'), '0')}건",
                f"- 조치 필요: {_value(summary.get('action_required_count'), '0')}건",
            ]
        if summary:
            lines.append("요약")
            lines.append(f"- 총 조회 건수: {_value(summary.get('total_count'), '0')}건")
            status_filter = query.get("status_filter")
            if status_filter:
                lines.append(
                    f"- {status_filter}: {_value(summary.get('total_count'), '0')}건"
                )
            else:
                lines.append(f"- 점검 대기: {_value(summary.get('waiting_count'), '0')}건")
                lines.append(f"- 점검 완료: {_value(summary.get('completed_count'), '0')}건")
            lines.append(
                f"- 조치 필요: {_value(summary.get('action_required_count'), '0')}건"
            )
            lines.append("")
        lines.append("점검 이력")
        lines.extend(_numbered_items(items, _format_inspection_history_item))
        return lines

    if operation in {"list_action_histories", "get_action_history"}:
        summary = result.get("summary", {}) if not is_detail else {}
        if query.get("response_mode") == "reason":
            if not items:
                return ["조건에 맞는 반려 조치 이력을 찾지 못했습니다."]
            if len(items) == 1:
                item = items[0]
                action_name = _value(item.get("action_name"))
                rejection_reason = item.get("rejection_reason")
                if rejection_reason:
                    return [
                        f"'{action_name}' 조치의 반려 사유는 다음과 같습니다.",
                        f"- {_value(rejection_reason)}",
                    ]
                return [
                    f"'{action_name}' 조치에는 확인 가능한 반려 사유가 없습니다."
                ]

            reason_lines = ["조회된 조치별 반려 사유입니다."]
            for item in items:
                action_name = _value(item.get("action_name"))
                rejection_reason = item.get("rejection_reason")
                if rejection_reason:
                    reason_lines.append(
                        f"- '{action_name}': {_value(rejection_reason)}"
                    )
                else:
                    reason_lines.append(
                        f"- '{action_name}': 확인 가능한 반려 사유가 없습니다."
                    )
            return reason_lines
        if summary and query.get("response_mode") == "summary":
            total_count = _value(summary.get("total_count"), "0")
            approval_status = query.get("approval_status")
            if approval_status:
                status_label = {
                    "승인 대기": "승인 대기 중인",
                    "승인 완료": "승인 완료된",
                    "반려": "반려된",
                }.get(approval_status, approval_status)
                return [f"{status_label} 조치 이력은 {total_count}건입니다."]
            action_status = query.get("action_status")
            if action_status:
                return [f"{action_status} 건수는 {total_count}건입니다."]
            if query.get("summary_scope") == "action_status":
                return [
                    "현재 조치 현황입니다.",
                    f"- 조치 대기: {_value(summary.get('waiting_count'), '0')}건",
                    f"- 조치 완료: {_value(summary.get('completed_count'), '0')}건",
                ]
            return [
                "현재 조치 이력 현황입니다.",
                f"- 조치 대기: {_value(summary.get('waiting_count'), '0')}건",
                f"- 조치 완료: {_value(summary.get('completed_count'), '0')}건",
                f"- 승인 대기: {_value(summary.get('pending_approval_count'), '0')}건",
                f"- 미할당: {_value(summary.get('unassigned_count'), '0')}건",
            ]
        if summary:
            lines.append("요약")
            lines.append(f"- 총 조회 건수: {_value(summary.get('total_count'), '0')}건")
            approval_status = query.get("approval_status")
            action_status = query.get("action_status")
            if approval_status:
                lines.append(
                    f"- {approval_status}: {_value(summary.get('total_count'), '0')}건"
                )
            elif action_status:
                lines.append(
                    f"- {action_status}: {_value(summary.get('total_count'), '0')}건"
                )
            else:
                lines.append(f"- 조치 대기: {_value(summary.get('waiting_count'), '0')}건")
                lines.append(f"- 조치 완료: {_value(summary.get('completed_count'), '0')}건")
            if approval_status != "승인 대기":
                lines.append(
                    f"- 승인 대기: {_value(summary.get('pending_approval_count'), '0')}건"
                )
            lines.append(f"- 미할당: {_value(summary.get('unassigned_count'), '0')}건")
            lines.append("")
        lines.append("조치 내역")
        lines.extend(_numbered_items(items, _format_action_item))
        return lines

    lines.append("점검 항목")
    if not is_detail:
        lines.append(f"- 총 조회 건수: {_value(result.get('total_items'), '0')}건")
        lines.append("")
    lines.extend(_numbered_items(items, _format_inspection_item))
    return lines


def _format_course_item(index: int, item: dict[str, Any]) -> list[str]:
    lines = [
        f"{index}. {_value(item.get('title'))}",
        f"   - 교육 ID: {_value(item.get('education_id'))}",
        f"   - 대상 분류: {_value(item.get('category'))}",
        f"   - 교육 유형: {_value(item.get('education_type'))}",
        f"   - 마감일: {_value(item.get('due_date'))}",
    ]
    if "target_count" in item:
        lines.extend(
            [
                f"   - 대상: {_value(item.get('target_count'), '0')}명",
                f"   - 미이수: {_value(item.get('incomplete_count'), '0')}명",
                f"   - 진행중: {_value(item.get('in_progress_count'), '0')}명",
                f"   - 이수: {_value(item.get('completed_count'), '0')}명",
                f"   - 이수율: {_value(item.get('completion_rate'), '0')}%",
            ]
        )
    if "status" in item:
        lines.extend(
            [
                f"   - 교육 상태: {_value(item.get('status'))}",
                f"   - 이수일: {_value(item.get('completed_date'))}",
            ]
        )
    return lines


def _format_education_overview(result: dict[str, Any]) -> list[str]:
    lines = [
        "요약",
        f"- 교육 과정: {_value(result.get('course_count'), '0')}개",
        f"- 대상 배정: {_value(result.get('target_assignment_count'), '0')}건",
        f"- 미이수: {_value(result.get('incomplete_count'), '0')}건",
        f"- 진행중: {_value(result.get('in_progress_count'), '0')}건",
        f"- 이수: {_value(result.get('completed_count'), '0')}건",
        f"- 전체 이수율: {_value(result.get('completion_rate'), '0')}%",
        f"- 이번 주 마감 과정: {_value(result.get('due_this_week_course_count'), '0')}개",
        f"- 기한 초과 과정: {_value(result.get('overdue_course_count'), '0')}개",
        f"- 마감일 없는 과정: {_value(result.get('no_due_date_course_count'), '0')}개",
    ]
    categories = result.get("categories", [])
    if categories:
        lines.extend(["", "분류별 현황"])
        for index, item in enumerate(categories, start=1):
            lines.extend(
                [
                    f"{index}. {_value(item.get('category'))}",
                    f"   - 대상: {_value(item.get('target_count'), '0')}건",
                    f"   - 이수: {_value(item.get('completed_count'), '0')}건",
                    f"   - 이수율: {_value(item.get('completion_rate'), '0')}%",
                ]
            )
    return lines


def _format_attendee_item(index: int, item: dict[str, Any]) -> list[str]:
    return [
        f"{index}. {_value(item.get('name'))}",
        f"   - 분류: {_value(item.get('category'))}",
        f"   - 역할: {_value(item.get('role'))}",
        f"   - 교육 상태: {_value(item.get('status'))}",
        f"   - 이수일: {_value(item.get('completed_date'))}",
    ]


def _format_user_status(result: dict[str, Any]) -> list[str]:
    lines = [
        f"사용자: {_value(result.get('user_name'))}",
        f"사용자 분류: {_value(result.get('user_category'))}",
    ]
    summary = result.get("summary", {})
    if summary:
        lines.extend(
            [
                f"- 대상 과정: {_value(summary.get('target_count'), '0')}개",
                f"- 미이수: {_value(summary.get('incomplete_count'), '0')}개",
                f"- 진행중: {_value(summary.get('in_progress_count'), '0')}개",
                f"- 이수: {_value(summary.get('completed_count'), '0')}개",
            ]
        )
    lines.extend(["", "교육 과정"])
    lines.extend(_numbered_items(result.get("items", []), _format_course_item))
    return lines


def _format_education_execution(
    query: dict[str, Any],
    result: dict[str, Any],
) -> list[str]:
    operation = query.get("operation", "")
    if operation == "get_education_overview":
        return _format_education_overview(result)

    if operation == "list_course_attendees":
        course = result.get("course", {})
        summary = result.get("summary", {})
        lines = [
            f"교육 과정: {_value(course.get('title'))}",
            f"- 대상: {_value(summary.get('target_count'), '0')}명",
            f"- 미이수: {_value(summary.get('incomplete_count'), '0')}명",
            f"- 진행중: {_value(summary.get('in_progress_count'), '0')}명",
            f"- 이수: {_value(summary.get('completed_count'), '0')}명",
            f"- 표시된 대상자: {_value(result.get('total_items'), '0')}명",
            "",
            "대상자",
        ]
        lines.extend(_numbered_items(result.get("items", []), _format_attendee_item))
        return lines

    if operation == "list_user_education_statuses":
        if "users" in result:
            users = result.get("users", [])
            lines = [f"조회된 사용자: {_value(result.get('total_users'), '0')}명"]
            for index, user_result in enumerate(users, start=1):
                lines.extend(["", f"사용자 {index}"])
                lines.extend(_format_user_status(user_result))
            return lines
        return _format_user_status(result)

    if (
        operation == "list_education_summaries"
        and query.get("response_mode") == "summary"
    ):
        summary = result.get("summary", {})
        category = query.get("category")
        heading = (
            f"{category} 교육 과정 집계입니다."
            if category
            else "교육 과정 집계입니다."
        )
        return [
            heading,
            f"- 교육 과정: {_value(summary.get('course_count'), '0')}개",
            f"- 대상 배정: {_value(summary.get('target_assignment_count'), '0')}건",
            f"- 미이수: {_value(summary.get('incomplete_count'), '0')}건",
            f"- 진행중: {_value(summary.get('in_progress_count'), '0')}건",
            f"- 이수: {_value(summary.get('completed_count'), '0')}건",
            f"- 대상 배정 기준 통합 이수율: {_value(summary.get('completion_rate'), '0')}%",
        ]

    is_detail = operation == "get_education_course"
    items = [result] if is_detail else result.get("items", [])
    lines = []
    if not is_detail:
        if query.get("order_by") in {
            "completion_rate_asc",
            "completion_rate_desc",
        }:
            criterion = (
                "이수율이 가장 낮은 과정"
                if query.get("order_by") == "completion_rate_asc"
                else "이수율이 가장 높은 과정"
            )
            lines.extend(
                [
                    f"- 비교 대상 교육 과정: {_value(result.get('total_items'), '0')}개",
                    f"- 표시 기준: {criterion}",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    f"- 조회된 교육 과정: {_value(result.get('total_items'), '0')}개",
                    "",
                ]
            )
    lines.extend(_numbered_items(items, _format_course_item))
    return lines


def build_authoritative_answer(
    executed_agent: str,
    agent_result: Optional[dict[str, Any]],
) -> str:
    if not agent_result or executed_agent not in {
        "inspection_action_management_agent",
        "education_management_agent",
    }:
        return ""

    executions = agent_result.get("executions", [])
    sections = []
    for index, execution in enumerate(executions, start=1):
        query = execution.get("query", {})
        result = execution.get("result", {})
        operation = query.get("operation", "")
        label = OPERATION_LABELS.get(operation, "조회 결과")
        lines = (
            _format_inspection_action_execution(query, result)
            if executed_agent == "inspection_action_management_agent"
            else _format_education_execution(query, result)
        )
        if len(executions) == 1 and query.get("response_mode") in {
            "summary",
            "reason",
            "ratio",
        }:
            sections.append("\n".join(lines).strip())
        else:
            heading = label if len(executions) == 1 else f"조회 {index}: {label}"
            sections.append("\n".join([heading, "", *lines]).strip())

    return "\n\n".join(sections)
