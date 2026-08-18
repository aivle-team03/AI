from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class VideoGenerateResponse(BaseModel):
    task_id: str
    status: str
    message: str


class VideoStatusResponse(BaseModel):
    task_id: str
    status: str
    progress_percent: int
    video_url: Optional[str] = None
    video_url_en: Optional[str] = None   # 영어 더빙판. 더빙을 못 만들었으면 비어 있다
    company_id: Optional[int] = None
    title: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    error_message: Optional[str] = None
    document_analysis: Optional[Dict[str, Any]] = None
    learning_objectives: Optional[List[str]] = None
    storyboard: Optional[List[Dict[str, Any]]] = None
    quality_report: Optional[Dict[str, Any]] = None
    usage_summary: Optional[Dict[str, Any]] = None
