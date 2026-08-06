"""Cloudinary media upload service module for uploading generated videos to cloud storage."""
import os
import asyncio
from typing import Optional

import cloudinary
import cloudinary.uploader


def _init_cloudinary():
    """Environment variable-based Cloudinary SDK initialization"""
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")
    cloudinary_url = os.getenv("CLOUDINARY_URL")

    if cloudinary_url:
        cloudinary.config(cloudinary_url=cloudinary_url, secure=True)
    elif cloud_name and api_key and api_secret:
        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True
        )


async def upload_video_to_cloudinary(
    file_path: str,
    folder: str = "safety_education_videos",
    public_id: Optional[str] = None
) -> Optional[str]:
    """
    로컬 MP4 동영상 파일을 Cloudinary에 업로드하고 보안 HTTPS URL(secure_url)을 반환한다.
    Cloudinary 설정 미비 또는 업로드 실패 시 None을 반환한다.
    """
    if not file_path or not os.path.exists(file_path):
        print(f"[Cloudinary] 업로드 대상 파일이 존재하지 않습니다: {file_path}")
        return None

    _init_cloudinary()

    try:
        def _sync_upload():
            upload_options = {
                "resource_type": "video",
                "folder": folder,
                "overwrite": True
            }
            if public_id:
                upload_options["public_id"] = public_id

            response = cloudinary.uploader.upload(file_path, **upload_options)
            return response.get("secure_url") or response.get("url")

        secure_url = await asyncio.to_thread(_sync_upload)
        if secure_url:
            print(f"[Cloudinary] SUCCESS: 동영상 Cloudinary 클라우드 업로드 완료 -> {secure_url}")
            return secure_url
    except Exception as e:
        print(f"[Cloudinary] WARNING: Cloudinary 동영상 업로드 예외 발생 (로컬 경로 사용): {e}")

    return None
