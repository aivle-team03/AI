import argparse
import json
from typing import Any

from app.graph import agent_graph
from app.state import AgentState
from app.tools import (
    get_education_data,
    get_history_data,
    get_inspection_action_data,
)


def create_initial_state(
    company_code: str,
    role: str,
    user_message: str,
) -> AgentState:
    normalized_company_code = company_code.strip()
    normalized_role = role.strip()
    normalized_user_message = user_message.strip()

    return {
        "company_code": normalized_company_code,
        "role": normalized_role,
        "user_message": normalized_user_message,
        "context": {
            "company_code": normalized_company_code,
            "role": normalized_role,
        },
        "next_step": "",
        "inspection_action_result": get_inspection_action_data(
            normalized_company_code
        ),
        "education_result": get_education_data(normalized_company_code),
        "history_result": get_history_data(normalized_company_code),
        "final_answer": "",
        "error_message": "",
    }


def run_agent(
    company_code: str,
    role: str,
    user_message: str,
) -> dict[str, Any]:
    initial_state = create_initial_state(
        company_code=company_code,
        role=role,
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
    parser.add_argument("company_code")
    parser.add_argument("role")
    parser.add_argument("user_message")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    result = run_agent(
        company_code=args.company_code,
        role=args.role,
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
