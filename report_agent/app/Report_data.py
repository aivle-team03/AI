from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL")
BACKEND_AUTH_TOKEN = os.getenv("BACKEND_AUTH_TOKEN")


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if BACKEND_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {BACKEND_AUTH_TOKEN}"
    return headers


def _get_json(path: str) -> Any:
    url = f"{BACKEND_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    request = Request(url, headers=_headers(), method="GET")

    try:
        with urlopen(request, timeout=30) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {url} failed: {exc.code} {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"GET {url} failed: {exc.reason}") from exc


def _items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    if isinstance(data, list):
        return data
    return []


def get_boards() -> Any:
    return _items(_get_json("/api/boards?size=100"))


def get_action_history() -> Any:
    return _items(_get_json("/api/action-histories?size=100"))


def get_event_categories() -> Any:
    return _items(_get_json("/api/risk/list"))


def build_worker_feedback_source_data() -> dict[str, Any]:
    return {
        "board": get_boards(),
        "action_history": get_action_history(),
        "event_category": get_event_categories(),
    }


def save_backend_data(
    output_path: str | Path = "output/BackendData.json",
) -> dict[str, Any]:
    output_path = Path(output_path)
    data = build_worker_feedback_source_data()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")

    return data


def main() -> int:
    try:
        data = save_backend_data()
    except RuntimeError as exc:
        print(f"[ERROR] Backend GET failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[ERROR] Failed to save backend data: {exc}", file=sys.stderr)
        return 1

    print("[OK] BackendData.json saved")
    print(json.dumps({key: len(value) for key, value in data.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
