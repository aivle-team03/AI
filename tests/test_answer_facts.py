import unittest
from unittest.mock import MagicMock, patch

from agent_main import create_initial_state
from app.agents.answer import answer_agent_node
from app.answer_facts import build_authoritative_answer


class AuthoritativeAnswerTest(unittest.TestCase):
    def test_rejection_reason_answer_uses_exact_database_reason(self):
        agent_result = {
            "executions": [
                {
                    "query": {
                        "operation": "list_action_histories",
                        "keyword": "불법 적치물 치우기",
                        "approval_status": "반려",
                        "response_mode": "reason",
                    },
                    "result": {
                        "items": [
                            {
                                "action_name": "불법 적치물 치우기",
                                "rejection_reason": (
                                    "조치 전/후 비교 사진이 누락되었습니다. 다시 첨부 바랍니다."
                                ),
                            }
                        ],
                        "summary": {"total_count": 1},
                    },
                }
            ]
        }

        answer = build_authoritative_answer(
            "inspection_action_management_agent",
            agent_result,
        )

        self.assertEqual(
            answer,
            "'불법 적치물 치우기' 조치의 반려 사유는 다음과 같습니다.\n"
            "- 조치 전/후 비교 사진이 누락되었습니다. 다시 첨부 바랍니다.",
        )

    def test_rejected_count_summary_omits_action_details(self):
        agent_result = {
            "executions": [
                {
                    "query": {
                        "operation": "list_action_histories",
                        "approval_status": "반려",
                        "response_mode": "summary",
                    },
                    "result": {
                        "items": [{"action_name": "출력되면 안 되는 항목"}],
                        "total_items": 3,
                        "summary": {
                            "total_count": 3,
                            "waiting_count": 2,
                            "completed_count": 1,
                            "pending_approval_count": 0,
                            "unassigned_count": 0,
                        },
                    },
                }
            ]
        }

        answer = build_authoritative_answer(
            "inspection_action_management_agent",
            agent_result,
        )

        self.assertEqual(answer, "반려된 조치 이력은 3건입니다.")
        self.assertNotIn("조치 내역", answer)
        self.assertNotIn("출력되면 안 되는 항목", answer)

    def test_combined_action_status_summary_uses_one_compact_section(self):
        agent_result = {
            "executions": [
                {
                    "query": {
                        "operation": "list_action_histories",
                        "response_mode": "summary",
                        "summary_scope": "action_status",
                    },
                    "result": {
                        "items": [],
                        "total_items": 14,
                        "summary": {
                            "total_count": 14,
                            "waiting_count": 8,
                            "completed_count": 6,
                            "pending_approval_count": 4,
                            "unassigned_count": 3,
                        },
                    },
                }
            ]
        }

        answer = build_authoritative_answer(
            "inspection_action_management_agent",
            agent_result,
        )

        self.assertEqual(
            answer,
            "현재 조치 현황입니다.\n- 조치 대기: 8건\n- 조치 완료: 6건",
        )
        self.assertNotIn("조회 1", answer)
        self.assertNotIn("승인 대기", answer)

    def test_pending_action_answer_preserves_names_and_filter_scope(self):
        agent_result = {
            "executions": [
                {
                    "query": {
                        "operation": "list_action_histories",
                        "action_status": "조치 대기",
                    },
                    "result": {
                        "items": [
                            {
                                "action_name": "2개씩 뜨는지 테스트",
                                "location": "기석님 집",
                                "category": "소방안전",
                                "category_name": "화재 감지",
                                "action_status": "조치 대기",
                                "approval_status": "반려",
                                "handler_name": None,
                                "content": "Action is required for this inspection.",
                                "rejection_reason": "사진이 누락되었습니다.",
                            }
                        ],
                        "total_items": 1,
                        "summary": {
                            "total_count": 1,
                            "waiting_count": 1,
                            "completed_count": 0,
                            "pending_approval_count": 0,
                            "unassigned_count": 1,
                        },
                    },
                }
            ]
        }

        answer = build_authoritative_answer(
            "inspection_action_management_agent",
            agent_result,
        )

        self.assertIn("1. 2개씩 뜨는지 테스트", answer)
        self.assertIn("분류: 소방안전 / 화재 감지", answer)
        self.assertIn("승인 상태: 반려", answer)
        self.assertIn("반려 사유: 사진이 누락되었습니다.", answer)
        self.assertIn("내용: Action is required for this inspection.", answer)
        self.assertIn("조치 대기: 1건", answer)
        self.assertNotIn("조치 완료: 0건", answer)

    def test_education_overview_uses_exact_counts(self):
        agent_result = {
            "executions": [
                {
                    "query": {"operation": "get_education_overview"},
                    "result": {
                        "course_count": 4,
                        "target_assignment_count": 79,
                        "incomplete_count": 36,
                        "in_progress_count": 11,
                        "completed_count": 32,
                        "completion_rate": 40.5,
                        "due_this_week_course_count": 0,
                        "overdue_course_count": 0,
                        "no_due_date_course_count": 4,
                        "categories": [],
                    },
                }
            ]
        }

        answer = build_authoritative_answer(
            "education_management_agent",
            agent_result,
        )

        self.assertIn("교육 과정: 4개", answer)
        self.assertIn("대상 배정: 79건", answer)
        self.assertIn("전체 이수율: 40.5%", answer)

    @patch("app.agents.answer._get_openai_client")
    def test_specialist_facts_skip_openai_answer_generation(self, get_client):
        state = create_initial_state("signed-token", "조치 대기 상황을 요약해줘")
        state["role"] = "안전관리자"
        state["context"] = {
            "executed_agent": "inspection_action_management_agent"
        }
        state["inspection_action_result"] = {
            "executions": [
                {
                    "query": {"operation": "list_action_histories"},
                    "result": {"items": [], "total_items": 0, "summary": {}},
                }
            ]
        }

        result = answer_agent_node(state)

        self.assertEqual(result["context"]["answer_source"], "deterministic_formatter")
        self.assertIn("조회된 항목이 없습니다.", result["final_answer"])
        get_client.assert_not_called()

    @patch("app.agents.answer._get_openai_client")
    def test_general_answer_generation_uses_zero_temperature(self, get_client):
        response = MagicMock()
        response.choices[0].message.content = "안녕하세요."
        get_client.return_value.chat.completions.create.return_value = response
        state = create_initial_state("signed-token", "안녕하세요")
        state["role"] = "안전관리자"

        result = answer_agent_node(state)

        self.assertEqual(result["final_answer"], "안녕하세요.")
        kwargs = get_client.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["temperature"], 0)


if __name__ == "__main__":
    unittest.main()
