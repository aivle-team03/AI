from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import MAX_RETRY_COUNT
from app.evidence_report import build_evidence_content
from app.graph import (
    risk_assessment_report_graph,
)
from app.management.graph import management_review_order_no_preprocessing_graph
from app.risk_assessment_form_graph.daily_outputs import write_daily_outputs
from app.risk_assessment_form_graph.graph import (
    risk_assessment_form_graph as risk_assessment_form_docx_graph,
)
from app.risk_assessment_form_graph.schemas import (
    RiskAssessmentFormRequest,
    RiskAssessmentFormResponse,
)
from app.schemas import (
    EvidenceContentRequest,
    EvidenceContentResponse,
    RiskAssessmentReportRequest,
    RiskAssessmentReportResponse,
    SiteAnomalyReportRequest,
    SiteAnomalyReportResponse,
)

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


@app.post(
    "/api/reports/evidence-content",
    response_model=EvidenceContentResponse,
    tags=["report-generation"],
)
async def generate_evidence_content(req: EvidenceContentRequest):
    try:
        return build_evidence_content(req)
    except Exception as exc:
        raise HTTPException(
            500,
            f"Failed to build evidence report content: {exc}",
        ) from exc


@app.post(
    "/api/reports/management-report/generate",
    response_model=SiteAnomalyReportResponse,
    tags=["report-generation"],
)
async def generate_management_report(req: SiteAnomalyReportRequest):
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
        return SiteAnomalyReportResponse(
            status="COMPLETED" if review_result.passed else "FAILED",
            retry_count=result.get("retry_count", 0),
            aggregated_data=result["aggregated_data"],
            analysis_result=result["analysis_result"],
            report=result["generated_report"],
            review=review_result,
        )
    except Exception as exc:
        raise HTTPException(
            500,
            f"Failed to generate management report: {exc}",
        ) from exc


@app.post(
    "/api/reports/risk-assessment/form/generate",
    response_model=RiskAssessmentFormResponse,
    tags=["report-generation"],
)
async def generate_risk_assessment_form(req: RiskAssessmentFormRequest):
    try:
        result = await risk_assessment_form_docx_graph.ainvoke(
            {
                "request": req,
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
        )
        response.daily_uploads = write_daily_outputs(
            response,
            result.get("backend_data") or req.model_dump(mode="json"),
        )
        return response
    except Exception as exc:
        raise HTTPException(
            500,
            f"Failed to generate risk assessment form: {exc}",
        ) from exc



@app.post(
    "/api/reports/risk-assessment/report/generate",
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
        return RiskAssessmentReportResponse(
            status="COMPLETED" if review_result.passed else "FAILED",
            retry_count=result.get("retry_count", 0),
            aggregated_data=result["aggregated_data"],
            analysis_result=result["analysis_result"],
            report=result["generated_report"],
            review=review_result,
        )
    except Exception as exc:
        raise HTTPException(
            500,
            f"Failed to generate risk assessment report: {exc}",
        ) from exc




