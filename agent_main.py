import argparse
import json
import os
from typing import Any

from app.graph import agent_graph
from app.state import AgentState


def create_initial_state(
    access_token: str,
    user_message: str,
) -> AgentState:
    normalized_user_message = user_message.strip()

    return {
        "access_token": access_token.strip(),
        "uid": None,
        "company_id": None,
        "role": "",
        "user_message": normalized_user_message,
        "context": {},
        "next_step": "",
        "inspection_action_result": None,
        "education_result": None,
        "law_manual_result": None,
        "final_answer": "",
        "error_message": "",
    }


def run_agent(
    access_token: str,
    user_message: str,
) -> dict[str, Any]:
    initial_state = create_initial_state(
        access_token=access_token,
        user_message=user_message,
    )
    result_state = agent_graph.invoke(initial_state)

    return {
        "final_answer": result_state.get("final_answer", ""),
        "next_step": result_state.get("next_step", ""),
        "context": result_state.get("context", {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("user_message")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    access_token = os.getenv("BP3_ACCESS_TOKEN", "").strip()
    if not access_token:
        parser.error("BP3_ACCESS_TOKEN environment variable is required")

    result = run_agent(
        access_token=access_token,
        user_message=args.user_message,
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
        )
    )


if __name__ == "__main__":
    main()
