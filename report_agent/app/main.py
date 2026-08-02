from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import MAX_RETRY_COUNT
from app.evidence_report import build_evidence_content
from app.graph import headquarters_full_graph, site_anomaly_full_graph
from app.schemas import (
    EvidenceContentRequest,
    EvidenceContentResponse,
    HeadquartersReportRequest,
    HeadquartersReportResponse,
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
    "/api/reports/headquarters/generate",
    response_model=HeadquartersReportResponse,
    tags=["report-generation"],
)
async def generate_headquarters_report(req: HeadquartersReportRequest):
    try:
        result = await headquarters_full_graph.ainvoke(
            {
                "request": req,
                "retry_count": 0,
                "max_retry_count": MAX_RETRY_COUNT,
                "errors": [],
            }
        )
        review_result = result["review_result"]
        return HeadquartersReportResponse(
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
            f"Failed to generate headquarters report: {exc}",
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
