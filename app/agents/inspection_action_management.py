import json
from datetime import date

from pydantic import ValidationError

from app.agents.router import _get_openai_client
from app.config import OPENAI_MODEL
from app.db.read_db import AgentReadDatabaseError
from app.schemas.inspection_action import InspectionActionPlan
from app.state import AgentState
from app.tools.inspection_action_tools import execute_inspection_action_query


def inspection_action_management_agent_node(state: AgentState) -> AgentState:
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
                        "당신은 점검 및 조치 이력 조회 계획을 만드는 도구 라우터입니다. "
                        f"오늘은 {date.today().isoformat()}입니다. "
                        "사용자 질문에 필요한 조회를 queries 배열에 1개 이상 3개 이하로 반환하세요. "
                        "queries의 각 항목은 문자열이 아니라 operation 필드가 있는 JSON 객체입니다. "
                        "예: 완료된 점검 이력 요청은 "
                        "{\"queries\":[{\"operation\":\"list_inspection_histories\","
                        "\"status_filter\":\"점검 완료\",\"offset\":0,\"limit\":20}]} 입니다. "
                        "허용 operation은 list_inspections, get_inspection, "
                        "list_inspection_histories, get_inspection_history, "
                        "list_action_histories, get_action_history뿐입니다. "
                        "상세 operation에는 각각 inspection_id, inspection_history_id, "
                        "action_history_id가 필요합니다. 날짜는 YYYY-MM-DD 형식입니다. "
                        "점검 대기 또는 점검 완료 요청은 list_inspection_histories의 "
                        "status_filter에 해당 상태를 반드시 설정하세요. "
                        "조치 대기 또는 조치 완료 요청은 list_action_histories의 "
                        "action_status에 해당 상태를 반드시 설정하세요. "
                        "점검에서 발생한 조치만 필요하면 source_type을 점검이력으로 설정하세요. "
                        "사용자가 요청하지 않은 개인정보 필터나 넓은 조회를 추가하지 마세요. "
                        "각 목록의 limit은 기본 20, 최대 50입니다. JSON 객체만 반환하세요."
                    ),
                },
                {"role": "user", "content": state["user_message"]},
            ],
        )
        raw_content = response.choices[0].message.content or "{}"
        plan = InspectionActionPlan.model_validate(json.loads(raw_content))

        executions = []
        company_id = state.get("company_id")
        if not isinstance(company_id, int):
            raise AgentReadDatabaseError("인증된 회사 정보를 확인할 수 없습니다.")
        for query in plan.queries:
            result = execute_inspection_action_query(
                query,
                company_id=company_id,
            )
            executions.append(
                {
                    "query": query.model_dump(mode="json", exclude_none=True),
                    "result": result,
                }
            )

        return {
            **state,
            "context": {
                **state["context"],
                "executed_agent": "inspection_action_management_agent",
                "inspection_action_query_count": len(executions),
            },
            "inspection_action_result": {"executions": executions},
            "next_step": "answer_agent",
        }
    except AgentReadDatabaseError as exc:
        return {
            **state,
            "context": {
                **state["context"],
                "executed_agent": "inspection_action_management_agent",
            },
            "error_message": str(exc),
            "next_step": "answer_agent",
        }
    except (json.JSONDecodeError, ValidationError) as exc:
        return {
            **state,
            "context": {
                **state["context"],
                "executed_agent": "inspection_action_management_agent",
                "planning_error": type(exc).__name__,
            },
            "error_message": "점검·조치 조회 조건을 해석하지 못했습니다.",
            "next_step": "answer_agent",
        }
    except Exception as exc:
        return {
            **state,
            "context": {
                **state["context"],
                "executed_agent": "inspection_action_management_agent",
                "planning_error": type(exc).__name__,
            },
            "error_message": "점검·조치 이력을 조회하는 중 오류가 발생했습니다.",
            "next_step": "answer_agent",
        }
