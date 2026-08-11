from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


S3_BUCKET = "aivle-team3-boss-bucket"
DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
JSON_CONTENT_TYPE = "application/json"


def upload_docx_to_s3(local_path: str | Path, prefix: str) -> str:
    return upload_file_to_s3(local_path, prefix, DOCX_CONTENT_TYPE)


def upload_docx_to_s3_if_missing(local_path: str | Path, prefix: str) -> str:
    return upload_file_to_s3(local_path, prefix, DOCX_CONTENT_TYPE, skip_existing=True)


def upload_json_to_s3(local_path: str | Path, prefix: str) -> str:
    return upload_file_to_s3(local_path, prefix, JSON_CONTENT_TYPE)


def upload_file_to_s3(
    local_path: str | Path,
    prefix: str,
    content_type: str,
    skip_existing: bool = False,
) -> str:
    path = Path(local_path)
    key = f"{prefix.rstrip('/')}/{path.name}"
    s3_uri = f"s3://{S3_BUCKET}/{key}"

    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client("s3")
    if skip_existing:
        try:
            client.head_object(Bucket=S3_BUCKET, Key=key)
            print(f"[S3] skip existing file: {s3_uri}", flush=True)
            return s3_uri
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code"))
            if error_code not in {"404", "NoSuchKey", "NotFound"}:
                raise

    print(f"[S3] upload file: {path} -> {s3_uri}", flush=True)
    client.upload_file(
        str(path),
        S3_BUCKET,
        key,
        ExtraArgs={"ContentType": content_type},
    )
    return s3_uri


def upload_docx_files_to_s3(local_paths: list[str | Path], prefix: str) -> list[str]:
    return [upload_docx_to_s3(path, prefix) for path in local_paths if path]


def upload_docx_files_to_s3_if_missing(
    local_paths: list[str | Path],
    prefix: str,
) -> list[str]:
    return [upload_docx_to_s3_if_missing(path, prefix) for path in local_paths if path]


def load_json_objects_from_s3(prefix: str) -> list[dict]:
    import boto3

    client = boto3.client("s3")
    paginator = client.get_paginator("list_objects_v2")
    payloads = []
    normalized_prefix = prefix.rstrip("/") + "/"
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=normalized_prefix):
        for item in page.get("Contents", []):
            key = item.get("Key", "")
            if not key.endswith(".json"):
                continue
            relative_key = key.removeprefix(normalized_prefix)
            if not re.match(r"\d{4}-\d{2}-\d{2}/", relative_key):
                continue
            body = client.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
            payloads.append(json.loads(body.decode("utf-8-sig")))
    return payloads


def _date_key(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date().isoformat()
    except ValueError:
        text = str(value)
        return text[:10] if len(text) >= 10 else None


def _row_date(row: dict) -> str | None:
    return _date_key(row.get("completed_at")) or _date_key(row.get("inspection_date"))


def _rows_from_payload(payload: dict) -> list[dict]:
    if isinstance(payload.get("final_history_rows"), list):
        return payload["final_history_rows"]
    correction_result = payload.get("correction_result") or {}
    if isinstance(correction_result.get("corrected_rows"), list):
        return correction_result["corrected_rows"]
    return []


def load_final_history_rows_from_s3_period(
    start_date: str,
    end_date: str,
    prefix: str = "report/daily-json/",
) -> list[dict]:
    rows = []
    for payload in load_json_objects_from_s3(prefix):
        for row in _rows_from_payload(payload):
            day = _row_date(row)
            if day and start_date <= day <= end_date:
                rows.append(row)
    return rows
