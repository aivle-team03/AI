"""생성된 교육 영상을 AWS S3에 올린다.

백엔드가 게시판·조치이력 이미지에 쓰는 것과 같은 규칙을 따른다.
  S3 키   media/videos/2026/08/11/{task_id}.mp4
  재생 URL {MEDIA_BASE_URL}/media/videos/2026/08/11/{task_id}.mp4

백엔드는 videoagent 가 돌려준 video_url 을 그대로 education 테이블에
저장하므로, 여기서 재생 가능한 절대 URL 을 만들어 돌려줘야 한다.
"""
import asyncio
import os
from datetime import datetime

import boto3
from botocore.config import Config

from app.config import AWS_S3_MEDIA_BUCKET, AWS_REGION, MEDIA_BASE_URL


MEDIA_S3_PREFIX = "media/"

# addressing_style 을 명시하지 않으면 리전 없는 글로벌 엔드포인트로 서명되어
# 서울 리전 버킷에서 리다이렉트나 AuthorizationHeaderMalformed 를 유발한다.
_S3_CONFIG = Config(s3={"addressing_style": "virtual"})


def _create_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=AWS_REGION,
        config=_S3_CONFIG,
    )


async def upload_video_to_s3(file_path: str, task_id: str) -> str:
    """영상을 S3에 올리고 재생 가능한 절대 URL을 돌려준다.

    설정이 없거나 업로드에 실패하면 예외를 던진다. 실패를 삼키고 로컬 경로를
    돌려주면 재생 불가 링크가 교육 자료로 등록되므로 작업을 실패시켜야 한다.
    """
    if not file_path or not os.path.exists(file_path):
        raise FileNotFoundError(f"업로드할 영상 파일이 없습니다: {file_path}")

    if not AWS_S3_MEDIA_BUCKET:
        raise RuntimeError(
            "AWS_S3_MEDIA_BUCKET 이 설정되지 않아 영상을 업로드할 수 없습니다."
        )
    if not MEDIA_BASE_URL:
        raise RuntimeError(
            "MEDIA_BASE_URL 이 설정되지 않아 재생 URL 을 만들 수 없습니다."
        )

    relative_path = f"videos/{datetime.now():%Y/%m/%d}/{task_id}.mp4"
    key = f"{MEDIA_S3_PREFIX}{relative_path}"

    def _upload() -> None:
        _create_s3_client().upload_file(
            file_path,
            AWS_S3_MEDIA_BUCKET,
            key,
            ExtraArgs={"ContentType": "video/mp4"},
        )

    await asyncio.to_thread(_upload)
    print(f"[S3Upload] SUCCESS: s3://{AWS_S3_MEDIA_BUCKET}/{key}")
    return f"{MEDIA_BASE_URL}/media/{relative_path}"
