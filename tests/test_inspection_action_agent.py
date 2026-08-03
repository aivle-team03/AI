import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent_main import create_initial_state
from app.agents.inspection_action_management import (
    inspection_action_management_agent_node,
)
from app.agents.router import auth_node
from app.schemas.inspection_action import InspectionActionQuery
from app.server import app
from app.tools.inspection_action_tools import execute_inspection_action_query


class AgentApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_query_requires_bearer_token(self):
        response = self.client.post(
            "/api/agent/query",
            json={"user_message": "점검 이력을 보여줘"},
        )
        self.assertEqual(response.status_code, 401)

    @patch("app.server.run_agent")
    def test_query_passes_token_without_client_supplied_role(self, run_agent):
        run_agent.return_value = {
            "final_answer": "확인했습니다.",
            "next_step": "end",
            "context": {},
        }
        response = self.client.post(
            "/api/agent/query",
            headers={"Authorization": "Bearer signed-token"},
            json={"user_message": "점검 이력을 보여줘"},
        )

        self.assertEqual(response.status_code, 200)
        run_agent.assert_called_once_with(
            access_token="signed-token",
            user_message="점검 이력을 보여줘",
        )


class AgentAuthAndToolTest(unittest.TestCase):
    @patch("app.agents.router.get_agent_session")
    def test_auth_uses_trusted_backend_session(self, get_agent_session):
        get_agent_session.return_value = {"uid": 9, "role": "안전관리자"}
        state = create_initial_state("signed-token", "조치 대기 내역")

        result = auth_node(state)

        self.assertEqual(result["next_step"], "router")
        self.assertEqual(result["uid"], 9)
        self.assertEqual(result["role"], "안전관리자")
        self.assertNotIn("access_token", result["context"])

    @patch("app.tools.inspection_action_tools.get_backend_json")
    def test_tool_uses_allowlisted_path_and_parameters(self, get_backend_json):
        get_backend_json.return_value = {"items": [], "total_items": 0}
        query = InspectionActionQuery(
            operation="list_action_histories",
            source_type="점검이력",
            action_status="조치 대기",
            limit=10,
        )

        execute_inspection_action_query(query, access_token="signed-token")

        self.assertEqual(
            get_backend_json.call_args.args[0],
            "/api/agent-data/inspection-action/action-histories",
        )
        self.assertEqual(
            get_backend_json.call_args.kwargs["params"],
            {
                "source_type": "점검이력",
                "action_status": "조치 대기",
                "offset": 0,
                "limit": 10,
            },
        )

    @patch(
        "app.agents.inspection_action_management.execute_inspection_action_query"
    )
    @patch("app.agents.inspection_action_management._get_openai_client")
    def test_specialist_executes_only_validated_query_plan(
        self,
        get_openai_client,
        execute_query,
    ):
        message = type(
            "Message",
            (),
            {
                "content": (
                    '{"queries":[{"operation":"list_inspection_histories",'
                    '"status_filter":"점검 완료","limit":5}]}'
                )
            },
        )()
        choice = type("Choice", (), {"message": message})()
        response = type("Response", (), {"choices": [choice]})()
        completions = type(
            "Completions",
            (),
            {"create": lambda self, **kwargs: response},
        )()
        get_openai_client.return_value = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": completions})()},
        )()
        execute_query.return_value = {
            "items": [],
            "total_items": 0,
            "summary": {"completed_count": 0},
        }
        state = create_initial_state("signed-token", "완료된 점검 이력을 보여줘")
        state["uid"] = 9
        state["role"] = "안전관리자"

        result = inspection_action_management_agent_node(state)

        self.assertEqual(result["next_step"], "answer_agent")
        self.assertEqual(result["context"]["inspection_action_query_count"], 1)
        planned_query = execute_query.call_args.args[0]
        self.assertEqual(planned_query.operation, "list_inspection_histories")
        self.assertEqual(planned_query.status_filter, "점검 완료")


if __name__ == "__main__":
    unittest.main()
