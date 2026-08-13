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
