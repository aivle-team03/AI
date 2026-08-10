from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.common.Report_data import save_backend_data
from app.config import MAX_RETRY_COUNT
from app.risk_assessment_form_graph.daily_outputs import write_daily_outputs
from app.risk_assessment_form_graph.graph import risk_assessment_form_graph
from app.risk_assessment_form_graph.schemas import (
    FinalHistoryRow,
    RiskAssessmentFormRequest,
    RiskAssessmentFormResponse,
)
from scripts.build_final_history_table_14 import build_final_history_table_14

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output" / "risk_assessment_form"
DEFAULT_RESPONSE_PATH = OUTPUT_DIR / "risk_assessment_form_graph_response.json"
DEFAULT_DOCX_PATH = OUTPUT_DIR / "risk_assessment_form_filled.docx"

SCHEDULER_TIMEZONE = os.getenv("DAILY_REPORT_TIMEZONE", "Asia/Seoul")
SCHEDULER_ENABLED = os.getenv("DAILY_REPORT_SCHEDULER_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CORRECTION_BATCH_SIZE = int(os.getenv("RISK_FORM_CORRECTION_BATCH_SIZE", "10"))
TIMEOUT_SECONDS = int(os.getenv("RISK_FORM_TIMEOUT_SECONDS", "1200"))

_scheduler: AsyncIOScheduler | None = None
_job_lock = asyncio.Lock()


def _date_key(value) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date().isoformat()
    except ValueError:
        text = str(value)
        return text[:10] if len(text) >= 10 else None


def _row_date(row: dict) -> str | None:
    return _date_key(row.get("completed_at")) or _date_key(row.get("inspection_date"))


def _yesterday() -> date:
    return datetime.now(ZoneInfo(SCHEDULER_TIMEZONE)).date() - timedelta(days=1)


async def _invoke_graph(request: RiskAssessmentFormRequest) -> dict:
    return await risk_assessment_form_graph.ainvoke(
        {
            "request": request,
            "retry_count": 0,
            "max_retry_count": MAX_RETRY_COUNT,
            "errors": [],
        }
    )


async def generate_daily_risk_assessment_form(target_date: date | None = None) -> dict:
    target_date = target_date or _yesterday()
    day = target_date.isoformat()

    if _job_lock.locked():
        logger.warning("Daily risk assessment form job skipped because previous job is still running.")
        return {"status": "SKIPPED", "reason": "previous job still running", "date": day}

    async with _job_lock:
        logger.info("Daily risk assessment form job started for %s", day)
        backend_data = save_backend_data()
        rows = [
            row
            for row in build_final_history_table_14(backend_data)
            if _row_date(row) == day
        ]

        request = RiskAssessmentFormRequest(
            **backend_data,
            final_history_rows=[FinalHistoryRow(**row) for row in rows],
            correction_batch_size=CORRECTION_BATCH_SIZE,
            output_path=str(DEFAULT_DOCX_PATH),
        )
        result = await asyncio.wait_for(_invoke_graph(request), timeout=TIMEOUT_SECONDS)

        review_result = result["correction_review"]
        docx_output_path = result.get("docx_output_path")
        response = RiskAssessmentFormResponse(
            status="COMPLETED" if review_result.approved and docx_output_path else "FAILED",
            retry_count=result.get("retry_count", 0),
            correction_batch_size=result.get("correction_batch_size"),
            correction_batch_count=result.get("correction_batch_count"),
            final_history_rows=result.get("final_history_rows", []),
            correction_result=result["correction_result"],
            correction_review=review_result,
            docx_output_path=docx_output_path,
            s3_output_path=result.get("s3_output_path"),
        )

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        response_payload = response.model_dump(mode="json")
        with DEFAULT_RESPONSE_PATH.open("w", encoding="utf-8-sig") as file:
            json.dump(response_payload, file, ensure_ascii=False, indent=2)
            file.write("\n")

        daily_uploads = write_daily_outputs(response, backend_data, target_date=day)
        payload = {
            "status": response.status,
            "date": day,
            "rows": len(response.correction_result.corrected_rows),
            "review_approved": response.correction_review.approved,
            "review_score": response.correction_review.score,
            "docx_output_path": response.docx_output_path,
            "daily_uploads": daily_uploads,
            "response_path": str(DEFAULT_RESPONSE_PATH),
        }
        logger.info("Daily risk assessment form job finished: %s", payload)
        return payload


def start_daily_report_scheduler() -> AsyncIOScheduler | None:
    global _scheduler
    if not SCHEDULER_ENABLED:
        logger.info("Daily report scheduler is disabled by DAILY_REPORT_SCHEDULER_ENABLED.")
        return None
    if _scheduler and _scheduler.running:
        return _scheduler

    timezone = ZoneInfo(SCHEDULER_TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=timezone)
    scheduler.add_job(
        generate_daily_risk_assessment_form,
        CronTrigger(hour=0, minute=0, second=5, timezone=timezone),
        id="daily_risk_assessment_form",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("Daily report scheduler started. It runs every day at 00:00:05 (%s).", SCHEDULER_TIMEZONE)
    return scheduler


def shutdown_daily_report_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Daily report scheduler stopped.")
    _scheduler = None
