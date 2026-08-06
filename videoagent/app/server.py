import os
import shutil
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from app.config import FRONTEND_ORIGINS, UPLOAD_DIR
from app.pipeline import (
    create_veo_task_record,
    get_veo_task_status,
    process_veo_summary_video_pipeline,
)
from app.schemas import VideoGenerateResponse, VideoStatusResponse


app = FastAPI(
    title="Video Agent",
    description="Google Veo 기반 안전 교육 영상 생성 에이전트",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(FRONTEND_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post(
    "/video/generate",
    response_model=VideoGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_video(
    background_tasks: BackgroundTasks,
    company_id: int = Form(...),
    file: Optional[UploadFile] = File(None),
    text_content: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    category: Optional[str] = Form("공통"),
    type: Optional[str] = Form("필수"),
    request: Optional[str] = Form(None),
):
    """문서(PDF/PPTX/TXT) 또는 텍스트로 Veo 안전 교육 영상 생성을 시작하고 task_id를 반환한다."""
    if not file and not text_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="문서 파일(file) 또는 텍스트 내용(text_content) 중 하나는 필수입니다."
        )

    task_id = create_veo_task_record()
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    if file:
        file_path = os.path.join(UPLOAD_DIR, f"{task_id}_{os.path.basename(file.filename or 'upload')}")
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    else:
        file_path = os.path.join(UPLOAD_DIR, f"{task_id}_text.txt")
        with open(file_path, "wb") as buffer:
            buffer.write(text_content.encode("utf-8"))

    background_tasks.add_task(
        process_veo_summary_video_pipeline,
        task_id=task_id,
        file_path=file_path,
        company_id=company_id,
        title=title,
        category=category,
        type=type,
        request=request,
    )

    return {
        "task_id": task_id,
        "status": "PENDING",
        "message": "Veo 동영상 생성 작업이 시작되었습니다. task_id로 진행 상태를 조회하세요."
    }


@app.get("/video/generate/{task_id}/status", response_model=VideoStatusResponse)
def read_video_status(task_id: str):
    """생성 작업 진행 상태 및 완료 시 video_url, 품질 검수 결과를 반환한다."""
    status_info = get_veo_task_status(task_id)
    if not status_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 작업(task_id)을 찾을 수 없습니다."
        )
    return status_info
