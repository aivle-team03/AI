from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import MAX_RETRY_COUNT
from app.evidence_report import build_evidence_content
from app.graph import (
    risk_assessment_form_graph,
    risk_assessment_report_graph,
    site_anomaly_full_graph,
)
from app.schemas import (
    EvidenceContentRequest,
    EvidenceContentResponse,
    RiskAssessmentFormRequest,
    RiskAssessmentReportRequest,
    RiskAssessmentFormResponse,
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
    "/api/reports/site-anomaly/generate",
    response_model=SiteAnomalyReportResponse,
    tags=["report-generation"],
)
async def generate_site_anomaly_report(req: SiteAnomalyReportRequest):
    try:
        result = await site_anomaly_full_graph.ainvoke(
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
            f"Failed to generate site anomaly report: {exc}",
        ) from exc


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
        csv_output_path = result.get("csv_output_path")
        return RiskAssessmentFormResponse(
            status="COMPLETED" if review_result.approved and csv_output_path else "FAILED",
            retry_count=result.get("retry_count", 0),
            final_history_rows=result.get("final_history_rows", []),
            correction_result=result["correction_result"],
            correction_review=review_result,
            csv_output_path=csv_output_path,
            xlsx_output_path=result.get("xlsx_output_path"),
        )
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




