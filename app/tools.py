from app.schemas import EducationResult, HistoryResult, InspectionActionResult


UNCONNECTED_SOURCE = "unconnected"


def get_inspection_action_data(company_code: str) -> InspectionActionResult:
    return {
        "summary": "점검/조치 데이터 소스가 아직 연결되지 않았습니다.",
        "total_risk_count": 0,
        "pending_action_count": 0,
        "in_progress_count": 0,
        "completed_count": 0,
        "risk_events": [],
        "pending_actions": [],
        "in_progress_actions": [],
        "completed_actions": [],
        "source": UNCONNECTED_SOURCE,
    }


def get_education_data(company_code: str) -> EducationResult:
    return {
        "summary": "교육관리 데이터 소스가 아직 연결되지 않았습니다.",
        "total_count": 0,
        "due_this_week_count": 0,
        "incomplete_count": 0,
        "in_progress_count": 0,
        "completed_count": 0,
        "essential_rate": 0.0,
        "regular_rate": 0.0,
        "total_completion_rate": 0.0,
        "educations": [],
        "role_completion_stats": [],
        "source": UNCONNECTED_SOURCE,
    }


def get_history_data(company_code: str) -> HistoryResult:
    return {
        "summary": "이력관리 데이터 소스가 아직 연결되지 않았습니다.",
        "total_count": 0,
        "period_start": "",
        "period_end": "",
        "filters": {
            "company_code": company_code,
        },
        "records": [],
        "source": UNCONNECTED_SOURCE,
    }
