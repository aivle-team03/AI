import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.agent_read import (
    agent_action_history_read,
    agent_event_category_read,
    agent_inspection_history_read,
    agent_inspection_read,
    agent_read_metadata,
    agent_user_display_read,
)
from app.repositories import inspection_action as repository


class InspectionActionRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        agent_read_metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.execute(
            agent_event_category_read.insert(),
            [
                {
                    "category_id": 10,
                    "company_id": 1,
                    "category": "점검",
                    "category_name": "전기 안전",
                    "level": 3,
                },
                {
                    "category_id": 20,
                    "company_id": 2,
                    "category": "점검",
                    "category_name": "타사 점검",
                    "level": 1,
                },
            ],
        )
        self.db.execute(
            agent_user_display_read.insert(),
            [
                {"uid": 100, "company_id": 1, "name": "담당자", "role": "현장관리자"},
                {"uid": 200, "company_id": 2, "name": "타사", "role": "현장관리자"},
            ],
        )
        self.db.execute(
            agent_inspection_read.insert(),
            [
                {
                    "inspection_id": 1,
                    "company_id": 1,
                    "category_id": 10,
                    "uid": 100,
                    "name": "배전반 점검",
                    "location": "A동",
                    "cycle": "매일",
                    "content": "온도 확인",
                },
                {
                    "inspection_id": 2,
                    "company_id": 2,
                    "category_id": 20,
                    "uid": 200,
                    "name": "타사 점검",
                    "location": "B동",
                    "cycle": "매주",
                    "content": None,
                },
            ],
        )
        self.db.execute(
            agent_inspection_history_read.insert(),
            {
                "inspection_history_id": 11,
                "company_id": 1,
                "inspection_id": 1,
                "uid": 100,
                "user_name": "이전 담당자명",
                "name": "배전반 점검",
                "location": "A동",
                "date": datetime(2026, 8, 3, 9, 0),
                "status": "점검 완료",
                "is_action_required": True,
                "content": "과열 확인",
            },
        )
        self.db.execute(
            agent_action_history_read.insert(),
            {
                "action_history_id": 21,
                "company_id": 1,
                "inspection_history_id": 11,
                "category_id": 10,
                "handler_uid": 100,
                "handler_name": "담당자",
                "approver_uid": None,
                "approver_name": None,
                "action_name": "배전반 냉각",
                "source_type": "점검이력",
                "source_id": 11,
                "location": "A동",
                "created_at": datetime(2026, 8, 3, 10, 0),
                "completed_at": None,
                "action_status": "조치 대기",
                "content": "냉각팬 교체",
                "approval_status": None,
                "approval_date": None,
                "rejection_reason": None,
            },
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_queries_preserve_relations_summaries_and_company_scope(self):
        inspections = repository.get_inspections(
            self.db, company_id=1, offset=0, limit=20
        )
        histories = repository.get_inspection_histories(
            self.db, company_id=1, offset=0, limit=20
        )
        actions = repository.get_action_histories(
            self.db, company_id=1, offset=0, limit=20
        )

        self.assertEqual(inspections["total_items"], 1)
        self.assertEqual(inspections["items"][0]["user_name"], "담당자")
        self.assertEqual(histories["summary"]["action_required_count"], 1)
        self.assertEqual(actions["summary"]["waiting_count"], 1)
        self.assertEqual(actions["items"][0]["source_id"], 11)
        self.assertNotIn("company_id", actions["items"][0])
        self.assertNotIn("board_id", actions["items"][0])
        self.assertNotIn("event_id", actions["items"][0])

    def test_other_company_detail_is_not_visible(self):
        result = repository.get_inspections(
            self.db,
            company_id=1,
            inspection_id=2,
            offset=0,
            limit=1,
        )

        self.assertEqual(result["total_items"], 0)
        self.assertEqual(result["items"], [])

    def test_metadata_contains_only_allowlisted_views(self):
        self.assertEqual(
            set(agent_read_metadata.tables),
            {
                "ai_inspection_read",
                "ai_inspection_history_read",
                "ai_action_history_read",
                "ai_event_category_read",
                "ai_user_display_read",
                "ai_education_read",
                "ai_education_status_read",
                "ai_education_user_read",
            },
        )


if __name__ == "__main__":
    unittest.main()
