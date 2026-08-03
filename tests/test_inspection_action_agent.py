import unittest
from contextlib import contextmanager
from datetime import date, datetime, time
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from agent_main import create_initial_state
from app.agents.inspection_action_management import (
    _prepare_plan_for_request,
    _requests_summary,
    inspection_action_management_agent_node,
)
from app.agents.router import (
    _requests_other_company,
    auth_node,
    router_node,
)
from app.db.read_db import AgentReadDatabaseError
from app.schemas.inspection_action import InspectionActionPlan, InspectionActionQuery
from app.server import app
from app.tools.backend_client import BackendClientError
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

    def test_cors_allows_configured_frontend_with_authorization_header(self):
        response = self.client.options(
            "/api/agent/query",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "http://127.0.0.1:5173",
        )
        self.assertIn(
            "Authorization",
            response.headers.get("access-control-allow-headers", ""),
        )

    @patch("app.server.run_agent")
    def test_query_passes_token_without_client_supplied_role(self, run_agent):
        conversation_id = "6de30f1d-9c3f-4a67-a65f-d98614c77745"
        run_agent.return_value = {
            "final_answer": "확인했습니다.",
            "next_step": "end",
            "context": {},
            "conversation_id": conversation_id,
        }
        response = self.client.post(
            "/api/agent/query",
            headers={"Authorization": "Bearer signed-token"},
            json={
                "conversation_id": conversation_id,
                "user_message": "점검 이력을 보여줘",
            },
        )

        self.assertEqual(response.status_code, 200)
        run_agent.assert_called_once_with(
            access_token="signed-token",
            user_message="점검 이력을 보여줘",
            conversation_id=conversation_id,
        )
        self.assertEqual(response.json()["conversation_id"], conversation_id)

    @patch("app.server.run_agent")
    def test_query_returns_unauthorized_for_expired_backend_session(self, run_agent):
        run_agent.return_value = {
            "final_answer": "인증이 만료되었거나 유효하지 않습니다.",
            "next_step": "end",
            "context": {"auth_status_code": 401},
        }

        response = self.client.post(
            "/api/agent/query",
            headers={"Authorization": "Bearer expired-token"},
            json={"user_message": "교육 현황을 알려줘"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn("만료", response.json()["detail"])


class AgentAuthAndToolTest(unittest.TestCase):
    def test_count_and_summary_phrases_request_summary_mode(self):
        for message in (
            "반려된 건 수가 몇개야?",
            "조치 완료 건수를 알려줘",
            "현재 조치 상황을 요약해줘",
        ):
            with self.subTest(message=message):
                self.assertTrue(_requests_summary(message))

        self.assertFalse(_requests_summary("반려된 조치 이력을 보여줘"))

    def test_schema_repairs_approval_status_in_action_status_field(self):
        for value in ("반려", "반려된", "거절된", "반송"):
            with self.subTest(value=value):
                query = InspectionActionQuery(
                    operation="list_action_histories",
                    action_status=value,
                )

                self.assertIsNone(query.action_status)
                self.assertEqual(query.approval_status, "반려")

    def test_combined_action_status_counts_are_merged_into_one_query(self):
        plan = InspectionActionPlan(
            queries=[
                InspectionActionQuery(
                    operation="list_action_histories",
                    action_status="조치 대기",
                ),
                InspectionActionQuery(
                    operation="list_action_histories",
                    action_status="조치 완료",
                ),
            ]
        )

        prepared = _prepare_plan_for_request(
            plan,
            "현재 조치 대기와 조치 완료 건수를 알려줘",
        )

        self.assertEqual(len(prepared.queries), 1)
        query = prepared.queries[0]
        self.assertIsNone(query.action_status)
        self.assertEqual(query.response_mode, "summary")
        self.assertEqual(query.summary_scope, "action_status")
        self.assertEqual(query.limit, 1)

    def test_follow_up_inherits_previous_action_filters(self):
        history = [
            {
                "executed_agent": "inspection_action_management_agent",
                "queries": [
                    {
                        "operation": "list_action_histories",
                        "action_status": "조치 대기",
                        "response_mode": "summary",
                    }
                ],
                "referenced_items": [],
            }
        ]
        plan = InspectionActionPlan(
            queries=[
                InspectionActionQuery(
                    operation="list_action_histories",
                    approval_status="반려",
                )
            ]
        )

        prepared = _prepare_plan_for_request(
            plan,
            "그중에서 반려된 건 몇개야?",
            history,
        )

        query = prepared.queries[0]
        self.assertEqual(query.action_status, "조치 대기")
        self.assertEqual(query.approval_status, "반려")
        self.assertEqual(query.response_mode, "summary")

    def test_rejection_reason_question_forces_reason_mode(self):
        plan = InspectionActionPlan(
            queries=[
                InspectionActionQuery(
                    operation="list_action_histories",
                    keyword="불법 적치물 치우기",
                    action_status="조치 대기",
                    approval_status="반려",
                )
            ]
        )

        prepared = _prepare_plan_for_request(
            plan,
            "불법 적치물 치우기 조치는 왜 반려됐어?",
        )

        query = prepared.queries[0]
        self.assertEqual(query.response_mode, "reason")
        self.assertEqual(query.limit, 5)

    @patch("app.agents.router.get_current_user_profile")
    def test_auth_uses_trusted_backend_profile(self, get_current_user_profile):
        get_current_user_profile.return_value = {
            "uid": 9,
            "company_id": 41,
            "role": "안전관리자",
        }
        state = create_initial_state("signed-token", "조치 대기 내역")

        result = auth_node(state)

        self.assertEqual(result["next_step"], "router")
        self.assertEqual(result["uid"], 9)
        self.assertEqual(result["company_id"], 41)
        self.assertEqual(result["role"], "안전관리자")
        self.assertNotIn("access_token", result["context"])

    @patch("app.agents.router.get_current_user_profile")
    def test_auth_rejects_profile_without_company_id(self, get_current_user_profile):
        get_current_user_profile.return_value = {
            "uid": 9,
            "role": "안전관리자",
        }

        result = auth_node(create_initial_state("signed-token", "점검 내역"))

        self.assertEqual(result["next_step"], "answer_agent")
        self.assertIn("회사", result["error_message"])

    @patch("app.agents.router.get_current_user_profile")
    def test_auth_rejects_non_admin_role(self, get_current_user_profile):
        get_current_user_profile.return_value = {
            "uid": 10,
            "company_id": 41,
            "role": "일반유저",
        }

        result = auth_node(create_initial_state("signed-token", "교육 현황"))

        self.assertEqual(result["next_step"], "answer_agent")
        self.assertIn("안전관리자", result["error_message"])
        self.assertEqual(result["context"]["auth_status_code"], 403)

    @patch("app.agents.router.get_current_user_profile")
    def test_auth_preserves_backend_unauthorized_status(self, get_current_user_profile):
        get_current_user_profile.side_effect = BackendClientError(
            "인증이 만료되었거나 유효하지 않습니다.",
            401,
        )

        result = auth_node(create_initial_state("expired-token", "교육 현황"))

        self.assertEqual(result["next_step"], "answer_agent")
        self.assertEqual(result["context"]["auth_status_code"], 401)

    @patch("app.agents.router._get_openai_client")
    def test_router_rejects_other_company_before_openai(self, get_openai_client):
        state = create_initial_state("signed-token", "회사 2의 점검 이력을 알려줘")
        state["company_id"] = 41
        state["role"] = "안전관리자"

        result = router_node(state)

        self.assertEqual(result["next_step"], "answer_agent")
        self.assertTrue(result["context"]["company_scope_violation"])
        self.assertIn("다른 회사", result["error_message"])
        get_openai_client.assert_not_called()

    def test_company_scope_parser_ignores_period_and_count_expressions(self):
        allowed_messages = (
            "우리 회사 2분기 점검 이력을 알려줘",
            "회사 8월 교육 현황을 알려줘",
            "회사 3개 과정의 이수율을 알려줘",
        )

        for message in allowed_messages:
            with self.subTest(message=message):
                self.assertFalse(_requests_other_company(message, company_id=41))

    @patch("app.agents.router._get_openai_client")
    def test_router_allows_authenticated_company_reference(self, get_openai_client):
        message = type(
            "Message",
            (),
            {
                "content": (
                    '{"next_step":"inspection_action_management_agent",'
                    '"reason":"점검 이력 요청"}'
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
        state = create_initial_state("signed-token", "회사 41의 점검 이력을 알려줘")
        state["company_id"] = 41
        state["role"] = "안전관리자"

        result = router_node(state)

        self.assertEqual(
            result["next_step"],
            "inspection_action_management_agent",
        )
        self.assertNotIn("company_scope_violation", result["context"])
        get_openai_client.assert_called_once()

    @patch("app.agents.router._get_openai_client")
    def test_router_uses_previous_agent_for_follow_up_reference(
        self,
        get_openai_client,
    ):
        state = create_initial_state(
            "signed-token",
            "그중에서 반려된 건 몇개야?",
        )
        state["company_id"] = 41
        state["role"] = "안전관리자"
        state["conversation_history"] = [
            {
                "executed_agent": "inspection_action_management_agent",
                "queries": [],
            }
        ]

        result = router_node(state)

        self.assertEqual(
            result["next_step"],
            "inspection_action_management_agent",
        )
        self.assertEqual(result["context"]["routing_source"], "conversation_memory")
        get_openai_client.assert_not_called()

    @patch("app.tools.inspection_action_tools.repository.get_action_histories")
    @patch("app.tools.inspection_action_tools.get_read_session")
    def test_tool_forces_company_scope_and_allowlisted_filters(
        self,
        get_read_session,
        get_action_histories,
    ):
        session = object()
        context = MagicMock()
        context.__enter__.return_value = session
        get_read_session.return_value = context
        get_action_histories.return_value = {"items": [], "total_items": 0}
        query = InspectionActionQuery(
            operation="list_action_histories",
            source_type="점검이력",
            action_status="조치 대기",
            limit=10,
        )

        execute_inspection_action_query(query, company_id=41)

        self.assertIs(get_action_histories.call_args.args[0], session)
        kwargs = get_action_histories.call_args.kwargs
        self.assertEqual(kwargs["company_id"], 41)
        self.assertEqual(kwargs["source_type"], "점검이력")
        self.assertEqual(kwargs["action_status"], "조치 대기")
        self.assertEqual(kwargs["offset"], 0)
        self.assertEqual(kwargs["limit"], 10)

    @patch("app.tools.inspection_action_tools.repository.get_inspection_histories")
    @patch("app.tools.inspection_action_tools.get_read_session")
    def test_detail_query_preserves_item_shape_and_full_day_filter(
        self,
        get_read_session,
        get_inspection_histories,
    ):
        context = MagicMock()
        context.__enter__.return_value = object()
        get_read_session.return_value = context
        item = {"inspection_history_id": 11, "status": "점검 완료"}
        get_inspection_histories.return_value = {
            "items": [item],
            "total_items": 1,
        }
        query = InspectionActionQuery(
            operation="get_inspection_history",
            inspection_history_id=11,
            date_from=date(2026, 8, 3),
            date_to=date(2026, 8, 3),
        )

        result = execute_inspection_action_query(query, company_id=41)

        self.assertEqual(result, item)
        kwargs = get_inspection_histories.call_args.kwargs
        self.assertEqual(kwargs["date_from"], datetime.combine(query.date_from, time.min))
        self.assertEqual(kwargs["date_to"], datetime.combine(query.date_to, time.max))

    @patch("app.tools.inspection_action_tools.get_read_session")
    def test_tool_fails_closed_without_read_database(self, get_read_session):
        @contextmanager
        def unavailable_session():
            raise AgentReadDatabaseError("설정되지 않았습니다.")
            yield

        get_read_session.side_effect = unavailable_session
        query = InspectionActionQuery(operation="list_inspections")

        with self.assertRaises(AgentReadDatabaseError):
            execute_inspection_action_query(query, company_id=41)

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
        state["company_id"] = 41
        state["role"] = "안전관리자"

        result = inspection_action_management_agent_node(state)

        self.assertEqual(result["next_step"], "answer_agent")
        self.assertEqual(result["context"]["inspection_action_query_count"], 1)
        planned_query = execute_query.call_args.args[0]
        self.assertEqual(planned_query.operation, "list_inspection_histories")
        self.assertEqual(planned_query.status_filter, "점검 완료")
        self.assertEqual(execute_query.call_args.kwargs["company_id"], 41)

    @patch(
        "app.agents.inspection_action_management.execute_inspection_action_query"
    )
    @patch("app.agents.inspection_action_management._get_openai_client")
    def test_rejected_count_query_is_repaired_and_uses_summary_mode(
        self,
        get_openai_client,
        execute_query,
    ):
        message = type(
            "Message",
            (),
            {
                "content": (
                    '{"queries":[{"operation":"list_action_histories",'
                    '"action_status":"반려된","limit":20}]}'
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
            "total_items": 3,
            "summary": {"total_count": 3},
        }
        state = create_initial_state(
            "signed-token",
            "조치이력 중에 반려된 건 수가 몇개야?",
        )
        state["uid"] = 9
        state["company_id"] = 41
        state["role"] = "안전관리자"

        result = inspection_action_management_agent_node(state)

        self.assertEqual(result["error_message"], "")
        query = execute_query.call_args.args[0]
        self.assertIsNone(query.action_status)
        self.assertEqual(query.approval_status, "반려")
        self.assertEqual(query.response_mode, "summary")
        self.assertEqual(query.limit, 1)


if __name__ == "__main__":
    unittest.main()
