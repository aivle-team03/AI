from langgraph.graph import END, START, StateGraph

from app.nodes import (
    answer_agent_node,
    auth_node,
    education_agent_node,
    history_agent_node,
    inspection_action_agent_node,
    router_node,
)
from app.state import AgentState

def select_next_step(state: AgentState) -> str:
    return state.get("next_step", "answer_agent")

def build_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("auth", auth_node)
    graph.add_node("router", router_node)
    graph.add_node("inspection_action_agent", inspection_action_agent_node)
    graph.add_node("education_agent", education_agent_node)
    graph.add_node("history_agent", history_agent_node)
    graph.add_node("answer_agent", answer_agent_node)

    graph.add_edge(START, "auth")
    graph.add_conditional_edges("auth",select_next_step,
        {"router": "router","answer_agent": "answer_agent"}
    )

    graph.add_conditional_edges("router",select_next_step,
        {"inspection_action_agent": "inspection_action_agent","education_agent": "education_agent","history_agent": "history_agent","answer_agent": "answer_agent"}
    )

    graph.add_edge("inspection_action_agent", "answer_agent")
    graph.add_edge("education_agent", "answer_agent")
    graph.add_edge("history_agent", "answer_agent")
    graph.add_edge("answer_agent", END)

    return graph.compile()


agent_graph = build_agent_graph()
