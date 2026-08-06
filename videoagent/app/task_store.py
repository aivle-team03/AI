import os
import json
import uuid
import redis
from typing import Dict, Any, Optional
from app.utils.datetime_utils import get_kst_now_str

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# 만료 시간(TTL) 기본 24시간
TASK_TTL = 86400 

def create_task(task_type: str = "STANDARD") -> str:
    prefix = "veo_task" if task_type == "VEO" else "task"
    task_id = f"{prefix}_{uuid.uuid4().hex[:12]}"
    
    task_data = {
        "task_id": task_id,
        "status": "PENDING",
        "progress_percent": 0,
        "task_type": task_type,
        "video_url": "",
        "education_id": "",
        "error_message": "",
        "created_at": get_kst_now_str()
    }
    
    # HSET으로 딕셔너리 저장
    redis_client.hset(task_id, mapping=task_data)
    redis_client.expire(task_id, TASK_TTL)
    
    return task_id

def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    data = redis_client.hgetall(task_id)
    if not data:
        return None

    # Redis 해시는 문자열만 저장하므로 update_task가 None을 ""로 기록한다. 읽을 때 None으로 되돌린다.
    data = {k: (None if v == "" else v) for k, v in data.items()}

    # 타입 캐스팅
    if data.get("progress_percent") is not None:
        data["progress_percent"] = int(data["progress_percent"])
    if data.get("education_id") is not None:
        data["education_id"] = int(data["education_id"])


    # JSON 직렬화된 부가 데이터 처리 (quality_report 등)
    for k, v in data.items():
        if isinstance(v, str) and (v.startswith("{") or v.startswith("[")):
            try:
                data[k] = json.loads(v)
            except Exception:
                pass
                
    return data

def update_task(task_id: str, **kwargs):
    if not redis_client.exists(task_id):
        return
        
    mapping = {}
    for k, v in kwargs.items():
        if isinstance(v, (dict, list)):
            mapping[k] = json.dumps(v, ensure_ascii=False)
        elif v is None:
            mapping[k] = ""
        else:
            mapping[k] = str(v)
            
    if mapping:
        redis_client.hset(task_id, mapping=mapping)
        redis_client.expire(task_id, TASK_TTL)
