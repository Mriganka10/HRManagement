"""File storage for resumes, receipts and generated documents.

``HRM_STORAGE_BACKEND=local`` (default) keeps files under ``data/files``;
``HRM_STORAGE_BACKEND=s3`` stores them in ``HRM_S3_BUCKET`` (private, SSE-S3 encrypted)
using the ECS task role — no access keys in the app. Callers only ever see a *storage key*
like ``resumes/<uuid>/resume.pdf``; the backend decides where the bytes live.
"""
from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path

from .settings import get_settings

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def new_key(folder: str, filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()[:10]
    stem = _SAFE.sub("_", Path(filename or "file").stem)[:60] or "file"
    return f"{folder.strip('/')}/{uuid.uuid4().hex}/{stem}{suffix}"


def _local_path(key: str) -> Path:
    root = get_settings().files_dir.resolve()
    path = (root / key).resolve()
    if root not in path.parents:
        raise ValueError("Invalid storage key.")
    return path


def _s3():
    import boto3  # installed with the "aws" extra

    return boto3.client("s3", region_name=get_settings().aws_region)


def _s3_key(key: str) -> str:
    prefix = get_settings().s3_prefix
    return f"{prefix}/{key}" if prefix else key


def put(key: str, data: bytes, content_type: str = "") -> str:
    cfg = get_settings()
    content_type = content_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
    if cfg.storage_backend == "s3":
        _s3().put_object(Bucket=cfg.s3_bucket, Key=_s3_key(key), Body=data, ContentType=content_type,
                         ServerSideEncryption="AES256")
    else:
        path = _local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return key


def get(key: str) -> bytes:
    cfg = get_settings()
    # v1 stored absolute local paths for resumes; keep reading them.
    if Path(key).is_absolute():
        return Path(key).read_bytes()
    if cfg.storage_backend == "s3":
        return _s3().get_object(Bucket=cfg.s3_bucket, Key=_s3_key(key))["Body"].read()
    return _local_path(key).read_bytes()


def local_copy(key: str, suffix: str = "") -> Path:
    """A local file path for engines that need one (resume parser). Caller deletes temp copies."""
    if Path(key).is_absolute():
        return Path(key)
    cfg = get_settings()
    if cfg.storage_backend != "s3":
        return _local_path(key)
    import tempfile

    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix or Path(key).suffix)
    handle.write(get(key))
    handle.close()
    return Path(handle.name)


def delete(key: str) -> None:
    cfg = get_settings()
    try:
        if cfg.storage_backend == "s3":
            _s3().delete_object(Bucket=cfg.s3_bucket, Key=_s3_key(key))
        else:
            _local_path(key).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 - best effort cleanup
        pass


def content_type(key: str) -> str:
    return mimetypes.guess_type(key)[0] or "application/octet-stream"
