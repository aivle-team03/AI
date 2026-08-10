from __future__ import annotations

import json
import re
from pathlib import Path


S3_BUCKET = "aivle-team3-boss-bucket"
DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
JSON_CONTENT_TYPE = "application/json"


def upload_docx_to_s3(local_path: str | Path, prefix: str) -> str:
    return upload_file_to_s3(local_path, prefix, DOCX_CONTENT_TYPE)


def upload_json_to_s3(local_path: str | Path, prefix: str) -> str:
    return upload_file_to_s3(local_path, prefix, JSON_CONTENT_TYPE)


def upload_file_to_s3(local_path: str | Path, prefix: str, content_type: str) -> str:
    path = Path(local_path)
    key = f"{prefix.rstrip('/')}/{path.name}"

    import boto3

    boto3.client("s3").upload_file(
        str(path),
        S3_BUCKET,
        key,
        ExtraArgs={"ContentType": content_type},
    )
    return f"s3://{S3_BUCKET}/{key}"


def upload_docx_files_to_s3(local_paths: list[str | Path], prefix: str) -> list[str]:
    return [upload_docx_to_s3(path, prefix) for path in local_paths if path]


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
