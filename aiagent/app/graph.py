from langgraph.graph import END, START, StateGraph

from app.agents.answer import answer_agent_node
from app.agents.education_management import education_management_agent_node
from app.agents.inspection_action_management import (
    inspection_action_management_agent_node,
)
from app.agents.law_manual import law_manual_agent_node
from app.agents.conversation_memory import (
    load_conversation_memory_node,
    save_conversation_memory_node,
)
from app.agents.router import auth_node, router_node
from app.state import AgentState


def select_next_step(state: AgentState) -> str:
    return state.get("next_step", "answer_agent")


def build_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("auth", auth_node)
    graph.add_node("load_conversation_memory", load_conversation_memory_node)
    graph.add_node("router", router_node)
    graph.add_node(
        "inspection_action_management_agent",
        inspection_action_management_agent_node,
    )
    graph.add_node("education_management_agent", education_management_agent_node)
    graph.add_node("law_manual_agent", law_manual_agent_node)
    graph.add_node("answer_agent", answer_agent_node)
    graph.add_node("save_conversation_memory", save_conversation_memory_node)

    graph.add_edge(START, "auth")
    graph.add_conditional_edges(
        "auth",
        select_next_step,
        {
            "router": "load_conversation_memory",
            "answer_agent": "answer_agent",
        },
    )
    graph.add_edge("load_conversation_memory", "router")

    graph.add_conditional_edges(
        "router",
        select_next_step,
        {
            "inspection_action_management_agent": (
                "inspection_action_management_agent"
            ),
            "education_management_agent": "education_management_agent",
            "law_manual_agent": "law_manual_agent",
            "answer_agent": "answer_agent",
        },
    )

    graph.add_edge("inspection_action_management_agent", "answer_agent")
    graph.add_edge("education_management_agent", "answer_agent")
    graph.add_edge("law_manual_agent", "answer_agent")
    graph.add_edge("answer_agent", "save_conversation_memory")
    graph.add_edge("save_conversation_memory", END)

    return graph.compile()


agent_graph = build_agent_graph()
