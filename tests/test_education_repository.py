import unittest
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.agent_read import (
    agent_education_read,
    agent_education_status_read,
    agent_education_user_read,
    agent_read_metadata,
)
from app.repositories import education as repository


class EducationRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        agent_read_metadata.create_all(self.engine)
        self.db = Session(self.engine)
        today = date.today()
        this_week = today + timedelta(days=6 - today.weekday())
        self.db.execute(
            agent_education_user_read.insert(),
            [
                {"uid": 1, "company_id": 1, "name": "공통이수", "role": "근로자", "category": "지게차"},
                {"uid": 2, "company_id": 1, "name": "지게차진행", "role": "근로자", "category": "지게차"},
                {"uid": 3, "company_id": 1, "name": "화물미이수", "role": "근로자", "category": "화물트럭"},
                {"uid": 4, "company_id": 2, "name": "타사사용자", "role": "근로자", "category": "지게차"},
            ],
        )
        self.db.execute(
            agent_education_read.insert(),
            [
                {
                    "education_id": 10,
                    "company_id": 1,
                    "title": "공통 안전교육",
                    "video_url": "https://example.com/common",
                    "category": "공통",
                    "education_type": "필수",
                    "due_date": this_week,
                },
                {
                    "education_id": 11,
                    "company_id": 1,
                    "title": "지게차 교육",
                    "video_url": "https://example.com/forklift",
                    "category": "지게차",
                    "education_type": "정기",
                    "due_date": today - timedelta(days=1),
                },
                {
                    "education_id": 12,
                    "company_id": 1,
                    "title": "마감일 없는 교육",
                    "video_url": "https://example.com/no-due",
                    "category": "화물트럭",
                    "education_type": "필수",
                    "due_date": None,
                },
                {
                    "education_id": 20,
                    "company_id": 2,
                    "title": "타사 교육",
                    "video_url": "https://example.com/other",
                    "category": "공통",
                    "education_type": "필수",
                    "due_date": this_week,
                },
            ],
        )
        self.db.execute(
            agent_education_status_read.insert(),
            [
                {
                    "uid": 1,
                    "education_id": 10,
                    "company_id": 1,
                    "user_name": "공통이수",
                    "status": "이수",
                    "completed_date": today,
                },
                {
                    "uid": 1,
                    "education_id": 11,
                    "company_id": 1,
                    "user_name": "공통이수",
                    "status": "이수",
                    "completed_date": today,
                },
                {
                    "uid": 2,
                    "education_id": 11,
                    "company_id": 1,
                    "user_name": "지게차진행",
                    "status": "진행중",
                    "completed_date": None,
                },
                {
                    "uid": 4,
                    "education_id": 20,
                    "company_id": 2,
                    "user_name": "타사사용자",
                    "status": "이수",
                    "completed_date": today,
                },
            ],
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_target_rule_missing_status_and_company_scope(self):
        result = repository.get_course_summaries(
            self.db, company_id=1, offset=0, limit=20
        )

        by_id = {item["education_id"]: item for item in result["items"]}
        self.assertEqual(set(by_id), {10, 11, 12})
        self.assertEqual(by_id[10]["target_count"], 3)
        self.assertEqual(by_id[10]["completed_count"], 1)
        self.assertEqual(by_id[10]["incomplete_count"], 2)
        self.assertEqual(by_id[11]["target_count"], 2)
        self.assertEqual(by_id[11]["in_progress_count"], 1)
        self.assertEqual(by_id[12]["target_count"], 1)
        self.assertEqual(by_id[12]["incomplete_count"], 1)

    def test_composite_status_supports_multiple_courses_per_user(self):
        result = repository.get_user_statuses(
            self.db, company_id=1, uid=1, offset=0, limit=20
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["total_items"], 2)
        self.assertEqual(
            {item["education_id"] for item in result["items"]}, {10, 11}
        )

    def test_due_filters_and_unfinished_semantics(self):
        this_week = repository.get_course_summaries(
            self.db,
            company_id=1,
            due_state="this_week",
            offset=0,
            limit=20,
        )
        overdue = repository.get_course_summaries(
            self.db,
            company_id=1,
            due_state="overdue",
            offset=0,
            limit=20,
        )
        no_due_date = repository.get_courses(
            self.db,
            company_id=1,
            due_state="no_due_date",
            offset=0,
            limit=20,
        )

        self.assertEqual([item["education_id"] for item in this_week["items"]], [10])
        self.assertEqual([item["education_id"] for item in overdue["items"]], [11])
        self.assertEqual([item["education_id"] for item in no_due_date["items"]], [12])

    def test_names_are_limited_to_person_level_queries(self):
        summaries = repository.get_course_summaries(
            self.db, company_id=1, offset=0, limit=20
        )
        attendees = repository.get_course_attendees(
            self.db, company_id=1, education_id=10, offset=0, limit=20
        )

        self.assertNotIn("name", summaries["items"][0])
        self.assertEqual(
            {item["name"] for item in attendees["items"]},
            {"공통이수", "지게차진행", "화물미이수"},
        )


if __name__ == "__main__":
    unittest.main()
