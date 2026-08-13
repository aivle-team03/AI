"""Korea Standard Time (KST, UTC+9) timezone helper module."""
from datetime import datetime
from zoneinfo import ZoneInfo

# 대한민국 표준시 시간대 (Asia/Seoul, UTC+9)
KST = ZoneInfo("Asia/Seoul")


def get_kst_now() -> datetime:
    """대한민국 표준시(KST, UTC+9) 현재 시각 반환 (naive datetime, DB 저장용)"""
    return datetime.now(KST).replace(tzinfo=None)


def get_kst_now_iso() -> str:
    """KST 현재 시각 ISO 8601 포맷 문자열 반환 (예: '2026-07-31T15:40:00+09:00')"""
    return datetime.now(KST).isoformat()


def get_kst_now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """KST 현재 시각 포맷 문자열 반환"""
    return datetime.now(KST).strftime(fmt)
