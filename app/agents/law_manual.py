from app.state import AgentState


def law_manual_agent_node(state: AgentState) -> AgentState:
    return {
        **state,
        "context": {
            **state["context"],
            "executed_agent": "law_manual_agent",
        },
        "next_step": "answer_agent",
    }
