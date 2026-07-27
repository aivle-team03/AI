import json

from openai import OpenAI

from app.config import OPENAI_API_KEY, OPENAI_MODEL
from app.roles import is_admin
from app.state import AgentState
from app.tools import (
    get_education_data,
    get_history_data,
    get_inspection_action_data,
)


ROUTER_NEXT_STEPS = {
    "inspection_action_agent",
    "education_agent",
    "history_agent",
    "answer_agent",
}


def _get_openai_client():
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다.")
    return OpenAI(api_key=OPENAI_API_KEY)


def auth_node(state: AgentState) -> AgentState:
    if not state["company_code"].strip():
        return {
            **state,
            "error_message": "회사 코드가 없어 AI 비서 요청을 처리할 수 없습니다.",
            "next_step": "answer_agent",
        }

    if not is_admin(state["role"]):
        return {
            **state,
            "error_message": "AI 비서 기능은 관리자 권한이 필요합니다.",
            "next_step": "answer_agent",
        }

    return {
        **state,
        "next_step": "router",
    }


def router_node(state: AgentState) -> AgentState:
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
                        "허용되는 next_step 값은 inspection_action_agent, education_agent, "
                        "history_agent, answer_agent입니다. "
                        "inspection_action_agent는 위험상황, CCTV, 감지, 점검, "
                        "조치중 상태, 조치완료 상태를 처리합니다. "
                        "education_agent는 안전교육, 교육 이수, 미이수, 수강, "
                        "훈련, 교육관리 요청을 처리합니다. "
                        "history_agent는 과거 조치 이력, 보고서, 기록, "
                        "아카이브 조회 요청을 처리합니다. "
                        "answer_agent는 인사말, 지원하지 않는 요청, 의도가 불명확한 요청을 처리합니다. "
                        "반드시 next_step과 reason 키를 가진 JSON만 반환하세요."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"company_code: {state['company_code']}\n"
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


def inspection_action_agent_node(state: AgentState) -> AgentState:
    try:
        result = get_inspection_action_data(state["company_code"])
        return {
            **state,
            "context": {
                **state["context"],
                "executed_agent": "inspection_action_agent",
                "inspection_action_source": result.get("source", ""),
            },
            "inspection_action_result": result,
            "next_step": "answer_agent",
        }
    except Exception as exc:
        return {
            **state,
            "context": {
                **state["context"],
                "inspection_action_error": f"{type(exc).__name__}: {exc}",
            },
            "error_message": "점검/조치 데이터 조회 중 오류가 발생했습니다.",
            "next_step": "answer_agent",
        }


def education_agent_node(state: AgentState) -> AgentState:
    try:
        result = get_education_data(state["company_code"])
        return {
            **state,
            "context": {
                **state["context"],
                "executed_agent": "education_agent",
                "education_source": result.get("source", ""),
            },
            "education_result": result,
            "next_step": "answer_agent",
        }
    except Exception as exc:
        return {
            **state,
            "context": {
                **state["context"],
                "education_error": f"{type(exc).__name__}: {exc}",
            },
            "error_message": "교육관리 데이터 조회 중 오류가 발생했습니다.",
            "next_step": "answer_agent",
        }


def history_agent_node(state: AgentState) -> AgentState:
    try:
        result = get_history_data(state["company_code"])
        return {
            **state,
            "context": {
                **state["context"],
                "executed_agent": "history_agent",
                "history_source": result.get("source", ""),
            },
            "history_result": result,
            "next_step": "answer_agent",
        }
    except Exception as exc:
        return {
            **state,
            "context": {
                **state["context"],
                "history_error": f"{type(exc).__name__}: {exc}",
            },
            "error_message": "이력관리 데이터 조회 중 오류가 발생했습니다.",
            "next_step": "answer_agent",
        }


def answer_agent_node(state: AgentState) -> AgentState:
    if state["error_message"]:
        return {
            **state,
            "final_answer": state["error_message"],
            "next_step": "end",
        }

    executed_agent = state["context"].get("executed_agent", "")
    answer_payload = {
        "user_message": state["user_message"],
        "executed_agent": executed_agent,
    }
    if executed_agent == "inspection_action_agent":
        answer_payload["inspection_action_result"] = state[
            "inspection_action_result"
        ]
    elif executed_agent == "education_agent":
        answer_payload["education_result"] = state["education_result"]
    elif executed_agent == "history_agent":
        answer_payload["history_result"] = state["history_result"]

    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 시설안전관리 서비스의 AI 비서입니다. "
                        f"현재 사용자의 권한은 {state['role']}입니다. "
                        "사용자 질문과 실행된 전문 agent 결과만 근거로 한국어 답변을 작성하세요. "
                        "payload에 포함되지 않은 agent 영역은 답변에 포함하지 마세요. "
                        "agent 결과에 없는 사실은 임의로 만들지 마세요. "
                        "데이터가 비어 있으면 확인된 정보가 없다고 말하세요. "
                        "위험상황, 조치중, 조치완료, 교육, 이력처럼 구분이 필요한 내용은 "
                        "짧은 섹션으로 나누어 보고하세요."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        answer_payload,
                        ensure_ascii=False,
                        default=str,
                        indent=2,
                    ),
                },
            ],
        )

        final_answer = response.choices[0].message.content or ""
        if not final_answer.strip():
            final_answer = "답변 생성 결과가 비어 있습니다."

        return {
            **state,
            "context": {
                **state["context"],
                "answer_source": "openai",
                "answer_model": OPENAI_MODEL,
            },
            "final_answer": final_answer.strip(),
            "next_step": "end",
        }
    except Exception as exc:
        return {
            **state,
            "context": {
                **state["context"],
                "answer_source": "openai",
                "answer_error": f"{type(exc).__name__}: {exc}",
            },
            "final_answer": "답변 생성 중 오류가 발생했습니다. OpenAI API 설정 또는 네트워크 상태를 확인해주세요.",
            "next_step": "end",
        }
