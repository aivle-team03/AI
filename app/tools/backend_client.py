from typing import Any, Optional

import httpx

from app.config import BACKEND_API_URL, BACKEND_TIMEOUT_SECONDS


class BackendClientError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def get_backend_json(
    path: str,
    *,
    access_token: str,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    try:
        response = httpx.get(
            f"{BACKEND_API_URL}{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            timeout=BACKEND_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        raise BackendClientError("백엔드 조회 시간이 초과되었습니다.") from exc
    except httpx.HTTPError as exc:
        raise BackendClientError("백엔드에 연결할 수 없습니다.") from exc

    if response.status_code == 401:
        raise BackendClientError("인증이 만료되었거나 유효하지 않습니다.", 401)
    if response.status_code == 403:
        raise BackendClientError("안전관리자 권한이 필요합니다.", 403)
    if response.status_code == 404:
        raise BackendClientError("요청한 데이터를 찾을 수 없습니다.", 404)
    if response.status_code >= 400:
        raise BackendClientError("백엔드 데이터 조회에 실패했습니다.", response.status_code)

    try:
        payload = response.json()
    except ValueError as exc:
        raise BackendClientError("백엔드 응답 형식이 올바르지 않습니다.") from exc
    if not isinstance(payload, dict):
        raise BackendClientError("백엔드 응답 형식이 올바르지 않습니다.")
    return payload


def get_agent_session(access_token: str) -> dict[str, Any]:
    return get_backend_json(
        "/api/agent-data/inspection-action/session",
        access_token=access_token,
    )
