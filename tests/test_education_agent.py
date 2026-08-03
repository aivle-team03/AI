import unittest
from unittest.mock import MagicMock, patch

from agent_main import create_initial_state
from app.agents.education_management import (
    _prepare_education_plan,
    _repair_education_plan_payload,
    education_management_agent_node,
)
from app.schemas.education import EducationPlan, EducationQuery
from app.tools.education_tools import execute_education_query


class EducationSchemaAndToolTest(unittest.TestCase):
    def test_detail_operations_require_identifiers(self):
        with self.assertRaises(ValueError):
            EducationQuery(operation="get_education_course")
        with self.assertRaises(ValueError):
            EducationQuery(operation="list_user_education_statuses")

    @patch("app.tools.education_tools.repository.get_course_summaries")
    @patch("app.tools.education_tools.get_read_session")
    def test_summary_tool_forces_company_scope_and_filters(
        self,
        get_read_session,
        get_course_summaries,
    ):
        session = object()
        context = MagicMock()
        context.__enter__.return_value = session
        get_read_session.return_value = context
        get_course_summaries.return_value = {"items": [], "total_items": 0}
        query = EducationQuery(
            operation="list_education_summaries",
            category="지게차",
            status_filter="미이수",
            due_state="overdue",
            limit=10,
        )

        execute_education_query(query, company_id=41)

        self.assertIs(get_course_summaries.call_args.args[0], session)
        kwargs = get_course_summaries.call_args.kwargs
        self.assertEqual(kwargs["company_id"], 41)
        self.assertEqual(kwargs["category"], "지게차")
        self.assertEqual(kwargs["status_filter"], "미이수")
        self.assertEqual(kwargs["due_state"], "overdue")
        self.assertEqual(kwargs["offset"], 0)
        self.assertEqual(kwargs["limit"], 10)

    @patch("app.tools.education_tools.repository.search_user_statuses")
    @patch("app.tools.education_tools.get_read_session")
    def test_user_name_query_uses_allowlisted_repository_operation(
        self,
        get_read_session,
        search_user_statuses,
    ):
        context = MagicMock()
        context.__enter__.return_value = object()
        get_read_session.return_value = context
        search_user_statuses.return_value = {"users": [], "total_users": 0}
        query = EducationQuery(
            operation="list_user_education_statuses",
            user_name="홍길동",
            limit=5,
        )

        execute_education_query(query, company_id=41)

        kwargs = search_user_statuses.call_args.kwargs
        self.assertEqual(kwargs["company_id"], 41)
        self.assertEqual(kwargs["user_name"], "홍길동")
        self.assertEqual(kwargs["course_limit"], 5)


class EducationAgentTest(unittest.TestCase):
    def test_follow_up_inherits_previous_education_filters(self):
        history = [
            {
                "executed_agent": "education_management_agent",
                "queries": [
                    {
                        "operation": "list_education_summaries",
                        "category": "지게차",
                        "due_state": "this_week",
                    }
                ],
                "referenced_items": [
                    {
                        "education_id": 2,
                        "title": "비상구 실무 가이드",
                        "category": "지게차",
                    },
                    {
                        "education_id": 3,
                        "title": "신규 근로자 기본 수칙",
                        "category": "화물트럭",
                    },
                ],
            }
        ]
        plan = EducationPlan(
            queries=[
                EducationQuery(
                    operation="list_education_summaries",
                    status_filter="미이수",
                )
            ]
        )

        prepared = _prepare_education_plan(
            plan,
            "그중에서 미이수 과정만 알려줘",
            history,
        )

        query = prepared.queries[0]
        self.assertEqual(query.category, "지게차")
        self.assertEqual(query.due_state, "this_week")
        self.assertEqual(query.status_filter, "미이수")

    def test_follow_up_matches_category_from_previous_results(self):
        history = [
            {
                "executed_agent": "education_management_agent",
                "queries": [
                    {
                        "operation": "list_education_summaries",
                        "due_state": "no_due_date",
                    }
                ],
                "referenced_items": [
                    {"education_id": 2, "category": "지게차"},
                    {"education_id": 3, "category": "화물트럭"},
                ],
            }
        ]
        plan = EducationPlan(
            queries=[EducationQuery(operation="list_education_summaries")]
        )

        prepared = _prepare_education_plan(
            plan,
            "그중에서 지게차 교육만 알려줘",
            history,
        )

        query = prepared.queries[0]
        self.assertEqual(query.category, "지게차")
        self.assertEqual(query.due_state, "no_due_date")

    def test_follow_up_applies_explicit_status_over_previous_filters(self):
        history = [
            {
                "executed_agent": "education_management_agent",
                "queries": [
                    {
                        "operation": "list_education_summaries",
                        "category": "지게차",
                        "due_state": "no_due_date",
                    }
                ],
                "referenced_items": [],
            }
        ]
        plan = EducationPlan(
            queries=[EducationQuery(operation="list_education_summaries")]
        )

        prepared = _prepare_education_plan(
            plan,
            "그중에서 진행중인 대상자가 있는 과정만 알려줘",
            history,
        )

        query = prepared.queries[0]
        self.assertEqual(query.category, "지게차")
        self.assertEqual(query.due_state, "no_due_date")
        self.assertEqual(query.status_filter, "진행중")

    def test_follow_up_repairs_ambiguous_detail_operation(self):
        history = [
            {
                "executed_agent": "education_management_agent",
                "referenced_items": [
                    {"education_id": 2},
                    {"education_id": 3},
                ],
            }
        ]

        repaired = _repair_education_plan_payload(
            {
                "queries": [
                    {"operation": "list_course_attendees"},
                ]
            },
            "그중에서 지게차 교육만 알려줘",
            history,
        )

        self.assertEqual(
            repaired["queries"][0]["operation"],
            "list_education_summaries",
        )

    @patch("app.agents.education_management.execute_education_query")
    @patch("app.agents.education_management._get_openai_client")
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
                    '{"queries":[{"operation":"list_education_summaries",'
                    '"status_filter":"미이수","due_state":"this_week","limit":5}]}'
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
        execute_query.return_value = {"items": [], "total_items": 0}
        state = create_initial_state("signed-token", "이번 주 미이수 교육 현황")
        state["uid"] = 9
        state["company_id"] = 41
        state["role"] = "안전관리자"

        result = education_management_agent_node(state)

        self.assertEqual(result["next_step"], "answer_agent")
        self.assertEqual(result["context"]["education_query_count"], 1)
        self.assertNotIn("access_token", result["context"])
        self.assertIn("definitions", result["education_result"])
        planned_query = execute_query.call_args.args[0]
        self.assertEqual(planned_query.operation, "list_education_summaries")
        self.assertEqual(planned_query.due_state, "this_week")
        self.assertEqual(planned_query.status_filter, "미이수")
        self.assertEqual(execute_query.call_args.kwargs["company_id"], 41)


if __name__ == "__main__":
    unittest.main()
