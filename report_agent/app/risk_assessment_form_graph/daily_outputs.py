from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from app.common.s3_upload import upload_docx_to_s3, upload_json_to_s3
from app.risk_assessment_form_graph.form_writer_word import (
    DEFAULT_FORM_PATH,
    fill_risk_assessment_form_docx,
)
from app.risk_assessment_form_graph.schemas import RiskAssessmentFormResponse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output" / "risk_assessment_form"
DAILY_DOCX_S3_PREFIX = "report/risk-assessment-form/"
DAILY_JSON_S3_PREFIX = "report/daily-json/"


def _date_key(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date().isoformat()
    except ValueError:
        text = str(value)
        return text[:10] if len(text) >= 10 else None


def _row_date(row) -> str:
    data = row.model_dump(mode="json") if hasattr(row, "model_dump") else dict(row or {})
    return _date_key(data.get("completed_at")) or _date_key(data.get("inspection_date")) or "unknown"


def _daily_response_payload(response: RiskAssessmentFormResponse, rows) -> dict:
    payload = response.model_dump(mode="json")
    payload["final_history_rows"] = [
        row.model_dump(mode="json") if hasattr(row, "model_dump") else row
        for row in rows
    ]
    correction_result = payload.get("correction_result") or {}
    correction_result["corrected_rows"] = payload["final_history_rows"]
    correction_result["correction_notes"] = []
    correction_result["unresolved_notes"] = []
    payload["correction_result"] = correction_result
    return payload


def write_daily_outputs(
    response: RiskAssessmentFormResponse,
    source_data: dict,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> list[dict]:
    rows_by_date = defaultdict(list)
    for row in response.correction_result.corrected_rows:
        rows_by_date[_row_date(row)].append(row)

    uploads = []
    for day, rows in sorted(rows_by_date.items()):
        daily_payload = _daily_response_payload(response, rows)
        json_path = output_dir / day / f"risk_assessment_form_graph_response_{day}.json"
        docx_path = output_dir / day / f"risk_assessment_form_filled_{day}.docx"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with json_path.open("w", encoding="utf-8-sig") as file:
            json.dump(daily_payload, file, ensure_ascii=False, indent=2)

        daily_correction_result = response.correction_result.model_copy(
            update={
                "corrected_rows": rows,
                "correction_notes": [],
                "unresolved_notes": [],
            }
        )
        fill_risk_assessment_form_docx(
            source_data,
            daily_correction_result,
            form_path=DEFAULT_FORM_PATH,
            output_path=docx_path,
        )
        uploads.append(
            {
                "date": day,
                "rows": len(rows),
                "s3_docx_output_path": upload_docx_to_s3(
                    docx_path,
                    f"{DAILY_DOCX_S3_PREFIX}{day}/",
                ),
                "s3_json_output_path": upload_json_to_s3(
                    json_path,
                    f"{DAILY_JSON_S3_PREFIX}{day}/",
                ),
            }
        )
    return uploads
