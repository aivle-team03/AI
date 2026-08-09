from __future__ import annotations

from pathlib import Path


S3_BUCKET = "aivle-team3-boss-bucket"
DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def upload_docx_to_s3(local_path: str | Path, prefix: str) -> str:
    path = Path(local_path)
    key = f"{prefix.rstrip('/')}/{path.name}"

    import boto3

    boto3.client("s3").upload_file(
        str(path),
        S3_BUCKET,
        key,
        ExtraArgs={"ContentType": DOCX_CONTENT_TYPE},
    )
    return f"s3://{S3_BUCKET}/{key}"


def upload_docx_files_to_s3(local_paths: list[str | Path], prefix: str) -> list[str]:
    return [upload_docx_to_s3(path, prefix) for path in local_paths if path]
