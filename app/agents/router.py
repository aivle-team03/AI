import json
import re

from openai import OpenAI

from app.config import OPENAI_API_KEY, OPENAI_MODEL
from app.roles import is_admin
from app.state import AgentState
from app.tools.backend_client import BackendClientError, get_current_user_profile


ROUTER_NEXT_STEPS = {
    "inspection_action_management_agent",
    "education_management_agent",
    "law_manual_agent",
    "answer_agent",
}

OTHER_COMPANY_TERMS = (
    "다른 회사",
    "타 회사",
    "타회사",
    "타사",
)
COMPANY_ID_PATTERNS = (
    re.compile(r"company[_\s-]*id\s*[:=#]?\s*(\d+)", re.IGNORECASE),
    re.compile(
        r"회사\s*(?:id|아이디)?\s*[:=#]?\s*(\d+)"
        r"(?!\d|분기|월|년|일|주|차|개)",
        re.IGNORECASE,
    ),
    re.compile(r"(\d+)\s*번\s*회사"),
)


def _get_openai_client():
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다.")
    return OpenAI(api_key=OPENAI_API_KEY)


def _requests_other_company(user_message: str, company_id: int) -> bool:
    normalized_message = " ".join(user_message.split())
    if any(term in normalized_message for term in OTHER_COMPANY_TERMS):
        return True

    for pattern in COMPANY_ID_PATTERNS:
        for match in pattern.finditer(normalized_message):
            if int(match.group(1)) != company_id:
                return True
    return False


def auth_node(state: AgentState) -> AgentState:
    if not state["access_token"].strip():
        return {
            **state,
            "error_message": "인증 토큰이 없어 AI 비서 요청을 처리할 수 없습니다.",
            "next_step": "answer_agent",
        }

    try:
        session = get_current_user_profile(state["access_token"])
    except BackendClientError as exc:
        return {
            **state,
            "error_message": str(exc),
            "next_step": "answer_agent",
        }

    role = str(session.get("role", "")).strip()
    uid = session.get("uid")
    company_id = session.get("company_id")
    if (
        not is_admin(role)
        or not isinstance(uid, int)
        or not isinstance(company_id, int)
    ):
        return {
            **state,
            "error_message": "안전관리자 권한과 회사 범위를 확인할 수 없습니다.",
            "next_step": "answer_agent",
        }

    return {
        **state,
        "uid": uid,
        "company_id": company_id,
        "role": role,
        "context": {
            **state["context"],
            "authenticated": True,
            "role": role,
        },
        "next_step": "router",
    }


def router_node(state: AgentState) -> AgentState:
    company_id = state.get("company_id")
    if isinstance(company_id, int) and _requests_other_company(
        state["user_message"],
        company_id,
    ):
        return {
            **state,
            "context": {
                **state["context"],
                "routing_source": "company_scope_policy",
                "routing_target": "answer_agent",
                "company_scope_violation": True,
            },
            "error_message": "다른 회사의 데이터에는 접근할 수 없습니다.",
            "next_step": "answer_agent",
        }

    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 시설안전관리 AI 비서의 라우터입니다. "
                        "사용자의 한국어 메시지를 분석해서 next_step을 정확히 하나만 선택하세요. "
                        "허용되는 next_step 값은 inspection_action_management_agent, "
                        "education_management_agent, law_manual_agent, answer_agent입니다. "
                        "inspection_action_management_agent는 점검 목록, 점검 이력, "
                        "점검 결과, 조치 대기, 조치 완료, 조치 이력, "
                        "위험 이벤트와 연결된 조치 현황 요청을 처리합니다. "
                        "education_management_agent는 안전교육, 교육 이수, 미이수, "
                        "진행중, 이수율, 교육관리 요청을 처리합니다. "
                        "law_manual_agent는 소방법, 산업안전보건법, 사내 매뉴얼, "
                        "안전 수칙, 법률/매뉴얼 Q&A 요청을 처리합니다. "
                        "answer_agent는 인사말, 지원하지 않는 요청, 의도가 불명확한 요청을 처리합니다. "
                        "반드시 next_step과 reason 키를 가진 JSON만 반환하세요."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"role: {state['role']}\n"
                        f"user_message: {state['user_message']}"
                    ),
                },
            ],
        )

        raw_content = response.choices[0].message.content or "{}"
        routing_result = json.loads(raw_content)
        next_step = routing_result.get("next_step", "answer_agent")
        reason = routing_result.get("reason", "")

        if next_step not in ROUTER_NEXT_STEPS:
            next_step = "answer_agent"
            reason = "OpenAI router가 허용되지 않은 next_step을 반환해 일반 답변으로 보냈습니다."

        return {
            **state,
            "context": {
                **state["context"],
                "routing_reason": reason,
                "routing_source": "openai",
                "routing_model": OPENAI_MODEL,
                "routing_target": next_step,
            },
            "next_step": next_step,
        }
    except Exception as exc:
        return {
            **state,
            "context": {
                **state["context"],
                "routing_source": "openai",
                "routing_error": f"{type(exc).__name__}: {exc}",
            },
            "error_message": "라우팅 중 오류가 발생했습니다. OpenAI API 설정 또는 네트워크 상태를 확인해주세요.",
            "next_step": "answer_agent",
        }
