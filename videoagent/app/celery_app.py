from celery import Celery

from app.config import REDIS_URL


celery_app = Celery(
    "videoagent",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.pipeline"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Seoul",
    enable_utc=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
)
