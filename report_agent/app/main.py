from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.common.s3_upload import upload_docx_to_s3
from app.config import MAX_RETRY_COUNT
from app.evidence_report import build_evidence_content
# from app.graph import (
#     risk_assessment_report_graph,
#     site_anomaly_full_graph,
# )
from app.management.graph import management_review_order_no_preprocessing_graph
from app.management.schemas import (
    SiteAnomalyReportRequest,
    SiteAnomalyReportResponse,
)
from app.risk_assessment_form_graph.graph import risk_assessment_form_graph
from app.risk_assessment_form_graph.schemas import (
    RiskAssessmentFormRequest,
    RiskAssessmentFormResponse,
)

from scripts.fill_management_review_order_docx import (
    DEFAULT_TEMPLATE_PATH as MANAGEMENT_REVIEW_ORDER_TEMPLATE_PATH,
    fill_docx_template as fill_management_review_order_docx,
)

MANAGEMENT_REVIEW_ORDER_OUTPUT_DIR = Path("output") / "management_reports"
MANAGEMENT_REVIEW_ORDER_S3_PREFIX = "report/management-review-order/"

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


# @app.post(
#     "/api/reports/site-anomaly/generate",
#     response_model=SiteAnomalyReportResponse,
#     tags=["report-generation"],
# )
# async def generate_site_anomaly_report(req: SiteAnomalyReportRequest):
#     try:
#         result = await site_anomaly_full_graph.ainvoke(
#             {
#                 "request": req,
#                 "retry_count": 0,
#  

@app.post(
    "/api/reports/risk-assessment/form/generate",
    response_model=RiskAssessmentFormResponse,
    tags=["report-generation"],
)
async def generate_risk_assessment_form(req: RiskAssessmentFormRequest):
    try:
        result = await risk_assessment_form_graph.ainvoke(
            {
                "request": req,
                "retry_count": 0,
                "max_retry_count": MAX_RETRY_COUNT,
                "errors": [],
            }
        )
        review_result = result["correction_review"]
        docx_output_path = result.get("docx_output_path")
        return RiskAssessmentFormResponse(
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
    except Exception as exc:
        raise HTTPException(
            500,
            f"Failed to generate risk assessment form: {exc}",
        ) from exc



# @app.post(
#     "/api/reports/risk-assessment/report/generate",
#     response_model=RiskAssessmentReportResponse,
#     tags=["report-generation"],
# )
# async def generate_risk_assessment_report(req: RiskAssessmentReportRequest):
#     try:
#         result = await risk_assessment_report_graph.ainvoke(
#             {
#                 "request": req,
#                 "retry_count": 0,
#                 "max_retry_count": MAX_RETRY_COUNT,
#                 "errors": [],
#             }
#         )
#         review_result = result["review_result"]
#         return RiskAssessmentReportResponse(
#             status="COMPLETED" if review_result.passed else "FAILED",
#             retry_count=result.get("retry_count", 0),
#             aggregated_data=result["aggregated_data"],
#             analysis_result=result["analysis_result"],
#             report=result["generated_report"],
#             review=review_result,
#         )
#     except Exception as exc:
#         raise HTTPException(
#             500,
#             f"Failed to generate risk assessment report: {exc}",
#         ) from exc


@app.post(
    "/api/reports/management-review-order/generate",
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

        MANAGEMENT_REVIEW_ORDER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        docx_report_path = fill_management_review_order_docx(
            response_payload,
            MANAGEMENT_REVIEW_ORDER_TEMPLATE_PATH,
            MANAGEMENT_REVIEW_ORDER_OUTPUT_DIR / "management_review_order.docx",
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




