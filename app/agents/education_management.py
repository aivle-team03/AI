from app.state import AgentState


def education_management_agent_node(state: AgentState) -> AgentState:
    return {
        **state,
        "context": {
            **state["context"],
            "executed_agent": "education_management_agent",
        },
        "next_step": "answer_agent",
    }
