from typing import Any, Optional

from app.conversation_memory import ConversationKey, conversation_store
from app.state import AgentState


REFERENCE_ITEM_FIELDS = (
    "action_history_id",
    "action_name",
    "inspection_history_id",
    "inspection_id",
    "education_id",
    "title",
    "category",
    "education_type",
    "due_date",
    "location",
    "action_status",
    "approval_status",
    "status",
    "law_id",
    "law_name",
    "law_type",
    "article_number",
    "article_branch",
    "article_label",
    "article_title",
    "effective_date",
    "source_url",
    "delegation_targets",
)


def _conversation_key(state: AgentState) -> Optional[ConversationKey]:
    uid = state.get("uid")
    company_id = state.get("company_id")
    conversation_id = state.get("conversation_id", "").strip()
    if not isinstance(uid, int) or not isinstance(company_id, int) or not conversation_id:
        return None
    return uid, company_id, conversation_id


def _query_context(state: AgentState) -> list[dict[str, Any]]:
    executed_agent = state.get("context", {}).get("executed_agent", "")
    result_key = {
        "inspection_action_management_agent": "inspection_action_result",
        "education_management_agent": "education_result",
        "law_manual_agent": "law_manual_result",
    }.get(executed_agent)
    result = state.get(result_key) if result_key else None
    if not isinstance(result, dict):
        return []
    return [
        execution.get("query", {})
        for execution in result.get("executions", [])
        if isinstance(execution, dict) and isinstance(execution.get("query"), dict)
    ]


def _referenced_items(state: AgentState) -> list[dict[str, Any]]:
    executed_agent = state.get("context", {}).get("executed_agent", "")
    result_key = {
        "inspection_action_management_agent": "inspection_action_result",
        "education_management_agent": "education_result",
        "law_manual_agent": "law_manual_result",
    }.get(executed_agent)
    result = state.get(result_key) if result_key else None
    if not isinstance(result, dict):
        return []

    references = []
    for execution in result.get("executions", []):
        if not isinstance(execution, dict):
            continue
        query = execution.get("query", {})
        if query.get("response_mode") == "summary":
            continue
        query_result = execution.get("result", {})
        items = query_result.get("items", []) if isinstance(query_result, dict) else []
        if query.get("operation", "").startswith("get_") and isinstance(query_result, dict):
            items = [query_result]
        for item in items[:10]:
            if not isinstance(item, dict):
                continue
            reference = {
                field: item[field]
                for field in REFERENCE_ITEM_FIELDS
                if item.get(field) is not None
            }
            if reference:
                references.append(reference)
    return references[:10]


def load_conversation_memory_node(state: AgentState) -> AgentState:
    key = _conversation_key(state)
    history = conversation_store.get(key) if key else []
    return {
        **state,
        "conversation_history": history,
        "context": {
            **state["context"],
            "conversation_turn_count": len(history),
        },
        "next_step": "router",
    }


def save_conversation_memory_node(state: AgentState) -> AgentState:
    key = _conversation_key(state)
    if key and state.get("user_message") and state.get("final_answer"):
        conversation_store.append(
            key,
            {
                "user_message": state["user_message"][:1000],
                "final_answer": state["final_answer"][:2000],
                "executed_agent": state.get("context", {}).get(
                    "executed_agent",
                    "",
                ),
                "queries": _query_context(state),
                "referenced_items": _referenced_items(state),
            },
        )
    return {
        **state,
        "next_step": "end",
    }
