import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.common.s3_upload import (
    upload_docx_files_to_s3_if_missing,
    upload_docx_to_s3,
)
from app.config import MAX_RETRY_COUNT

from app.management.graph import management_review_order_no_preprocessing_graph
from app.management.schemas import SiteAnomalyReportRequest, SiteAnomalyReportResponse
from app.risk_assessment.graph import risk_assessment_report_graph
from app.risk_assessment.fill_risk_assessment_report_docx import (
    DEFAULT_TEMPLATE_PATH as RISK_ASSESSMENT_REPORT_TEMPLATE_PATH,
    fill_docx_template as fill_risk_assessment_report_docx,
)
from app.risk_assessment.schemas import (
    RiskAssessmentReportRequest,
    RiskAssessmentReportResponse,
)
from app.risk_assessment_form_graph.daily_outputs import (
    DEFAULT_OUTPUT_DIR as RISK_ASSESSMENT_FORM_OUTPUT_DIR,
    write_daily_outputs,
)
from app.risk_assessment_form_graph.graph import (
    risk_assessment_form_graph as risk_assessment_form_docx_graph,
)
from app.risk_assessment_form_graph.schemas import (
    RiskAssessmentFormRequest,
    RiskAssessmentFormResponse,
)
from app.worker_feedback.graph import worker_feedback_improvement_graph
from app.worker_feedback.schemas import (
    WorkerFeedbackImprovementReportRequest,
    WorkerFeedbackImprovementReportResponse,
)

from scripts.fill_management_review_order_docx import (
    DEFAULT_TEMPLATE_PATH as MANAGEMENT_REVIEW_ORDER_TEMPLATE_PATH,
    fill_docx_template as fill_management_review_order_docx,
)

MANAGEMENT_REVIEW_ORDER_OUTPUT_DIR = Path("output") / "management_reports"
MANAGEMENT_REVIEW_ORDER_S3_PREFIX = "report/management-review-order/"
RISK_ASSESSMENT_REPORT_OUTPUT_DIR = Path("output") / "risk_assessment_reports"
RISK_ASSESSMENT_REPORT_S3_PREFIX = "report/risk-assessment-report/"
WORKER_FEEDBACK_S3_PREFIX = "report/worker-feedback/"
RISK_ASSESSMENT_FORM_S3_PREFIX = "report/risk-assessment-form/"
RISK_ASSESSMENT_FORM_RESPONSE_PATH = (
    RISK_ASSESSMENT_FORM_OUTPUT_DIR / "risk_assessment_form_graph_response.json"
)


def _date_for_filename(value: str | None) -> str:
    return str(value or "unknown").replace("-", "_")


def _management_review_order_period(
    req: SiteAnomalyReportRequest,
    response_payload: dict,
) -> tuple[str | None, str | None]:
    period = (
        response_payload.get("aggregated_data", {})
        .get("site_context", {})
        .get("period", {})
    )
    start = req.start_date or period.get("start_date")
    end = req.end_date or period.get("end_date")
    return start, end


def _management_review_order_period_text(start: str | None, end: str | None) -> str:
    return f"{start or '-'} ~ {end or '-'}"


def _management_review_order_filename(start_date: str | None, end_date: str | None) -> str:
    start = _date_for_filename(start_date)
    end = _date_for_filename(end_date)
    return f"경영책임자검토지시서_{start}_{end}.docx"


def _risk_assessment_report_period(
    req: RiskAssessmentReportRequest,
    response_payload: dict,
) -> tuple[str | None, str | None]:
    period = (
        response_payload.get("aggregated_data", {})
        .get("report_context", {})
        .get("period", {})
    )
    start = req.start_date or period.get("start_date")
    end = req.end_date or period.get("end_date")
    return start, end


def _risk_assessment_report_filename(start_date: str | None, end_date: str | None) -> str:
    start = _date_for_filename(start_date)
    end = _date_for_filename(end_date)
    return f"위험성평가보고서_{start}_{end}.docx"


app = FastAPI(title="Warehouse Safety AI Report API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


#위험성평가표 + json 파일
@app.post(
    "/api/report/risk-assessment/form/generate",
    response_model=RiskAssessmentFormResponse,
    tags=["report-generation"],
)
async def generate_risk_assessment_form(req: RiskAssessmentFormRequest):
    print(
        f"[risk-assessment-form] rows={len(req.final_history_rows)} "
        f"batch_size={req.correction_batch_size}",
        flush=True,
    )
    try:
        result = await risk_assessment_form_docx_graph.ainvoke(
            {
                "request": req,
                "final_history_rows": [
                    row.model_dump(mode="json") if hasattr(row, "model_dump") else row
                    for row in req.final_history_rows
                ],
                "retry_count": 0,
                "max_retry_count": MAX_RETRY_COUNT,
                "errors": [],
            }
        )
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
            s3_output_path=None,
        )
        response.daily_uploads = write_daily_outputs(response, req.model_dump(mode="json"))

        RISK_ASSESSMENT_FORM_RESPONSE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with RISK_ASSESSMENT_FORM_RESPONSE_PATH.open("w", encoding="utf-8-sig") as file:
            json.dump(response.model_dump(mode="json"), file, ensure_ascii=False, indent=2)

        return response
    except Exception as exc:
        raise HTTPException(
            500,
            f"Failed to generate risk assessment form: {exc}",
        ) from exc


#위험성평가 보고서
@app.post(
    "/api/report/risk-assessment/report/generate",
    response_model=RiskAssessmentReportResponse,
    tags=["report-generation"],
)
async def generate_risk_assessment_report(req: RiskAssessmentReportRequest):
    try:
        result = await risk_assessment_report_graph.ainvoke(
            {
                "request": req,
                "retry_count": 0,
                "max_retry_count": MAX_RETRY_COUNT,
                "errors": [],
            }
        )
        review_result = result["review_result"]
        response = RiskAssessmentReportResponse(
            status="COMPLETED" if review_result.passed else "FAILED",
            retry_count=result.get("retry_count", 0),
            aggregated_data=result["aggregated_data"],
            analysis_result=result["analysis_result"],
            report=result["generated_report"],
            review=review_result,
        )
        response_payload = response.model_dump(mode="json")
        start_date, end_date = _risk_assessment_report_period(req, response_payload)
        response_payload["report"]["period"] = _management_review_order_period_text(
            start_date,
            end_date,
        )

        RISK_ASSESSMENT_REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        docx_report_path = fill_risk_assessment_report_docx(
            response_payload,
            RISK_ASSESSMENT_REPORT_TEMPLATE_PATH,
            RISK_ASSESSMENT_REPORT_OUTPUT_DIR
            / _risk_assessment_report_filename(start_date, end_date),
        )
        s3_output_path = upload_docx_to_s3(
            docx_report_path,
            RISK_ASSESSMENT_REPORT_S3_PREFIX,
        )
        response_payload["docx_output_path"] = str(docx_report_path)
        response_payload["s3_output_path"] = s3_output_path
        return response_payload
    except Exception as exc:
        raise HTTPException(
            500,
            f"Failed to generate risk assessment report: {exc}",
        ) from exc

#경영책임자 검토 지시서
@app.post(
    "/api/report/management-review-order/generate",
    tags=["report-generation"],
)
async def generate_management_review_order(req: SiteAnomalyReportRequest):
    try:
        result = await management_review_order_no_preprocessing_graph.ainvoke(
            {
                "request": req,
                "retry_count": 0,
                "max_retry_count": MAX_RETRY_COUNT,
                "errors": [],
            }
        )
        review_result = result["review_result"]
        response = SiteAnomalyReportResponse(
            status="COMPLETED" if review_result.passed else "FAILED",
            retry_count=result.get("retry_count", 0),
            aggregated_data=result["aggregated_data"],
            analysis_result=result["analysis_result"],
            report=result["generated_report"],
            review=review_result,
        )
        response_payload = response.model_dump(mode="json")
        start_date, end_date = _management_review_order_period(req, response_payload)
        response_payload["report"]["period"] = _management_review_order_period_text(
            start_date,
            end_date,
        )

        MANAGEMENT_REVIEW_ORDER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        docx_report_path = fill_management_review_order_docx(
            response_payload,
            MANAGEMENT_REVIEW_ORDER_TEMPLATE_PATH,
            MANAGEMENT_REVIEW_ORDER_OUTPUT_DIR
            / _management_review_order_filename(start_date, end_date),
        )
        s3_output_path = upload_docx_to_s3(docx_report_path, MANAGEMENT_REVIEW_ORDER_S3_PREFIX)
        response_payload["docx_output_path"] = str(docx_report_path)
        response_payload["s3_output_path"] = s3_output_path
        return response_payload
    except Exception as exc:
        raise HTTPException(
            500,
            f"Failed to generate management review order: {exc}",
        ) from exc


#종사자 의견청취 개선 보고서
@app.post(
    "/api/report/worker-feedback/generate",
    response_model=WorkerFeedbackImprovementReportResponse,
    tags=["report-generation"],
)
async def generate_worker_feedback_improvement_report(req: WorkerFeedbackImprovementReportRequest):
    try:
        result = await worker_feedback_improvement_graph.ainvoke(
            {
                "request": req,
                "retry_count": 0,
                "max_retry_count": MAX_RETRY_COUNT,
                "errors": [],
            }
        )
        review_result = result["correction_review"]
        word_output_paths = result.get("word_output_paths", [])
        print(
            f"[worker-feedback] word_output_paths={len(word_output_paths)}",
            flush=True,
        )
        s3_output_paths = upload_docx_files_to_s3_if_missing(
            word_output_paths,
            WORKER_FEEDBACK_S3_PREFIX,
        )
        print(
            f"[worker-feedback] s3_output_paths={len(s3_output_paths)}",
            flush=True,
        )
        has_rows = bool(result["correction_result"].corrected_rows)
        return WorkerFeedbackImprovementReportResponse(
            status="COMPLETED" if review_result.approved and has_rows else "FAILED",
            retry_count=result.get("retry_count", 0),
            worker_feedback_rows=result.get("worker_feedback_rows", []),
            correction_result=result["correction_result"],
            correction_review=review_result,
            word_output_paths=word_output_paths,
            s3_output_paths=s3_output_paths,
        )
    except Exception as exc:
        raise HTTPException(
            500,
            f"Failed to generate worker feedback improvement report: {exc}",
        ) from exc


