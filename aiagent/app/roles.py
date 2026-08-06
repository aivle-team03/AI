from typing import Optional


ADMIN_ROLE = "안전관리자"


def normalize_role(role: Optional[str]) -> str:
    return (role or "").strip()


def is_admin(role: Optional[str]) -> bool:
    return normalize_role(role) == ADMIN_ROLE
