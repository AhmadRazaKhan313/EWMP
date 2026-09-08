"""
File storage abstraction.

Two backends, selected via settings.STORAGE_BACKEND:
  - "local": writes to disk under STORAGE_LOCAL_DIR. Good for dev — no
    external service required. Files are NOT web-accessible directly;
    they're only ever read back through an authenticated API endpoint
    (see api/v1/hrms/employee_documents.py), so sensitive documents
    (CNIC, contracts) are never exposed via a public static URL.
  - "s3" / "r2" / "minio": all three are S3-compatible, so one boto3
    client handles them — R2/MinIO just set S3_ENDPOINT_URL.

Usage:
    storage = get_storage()
    key = await storage.save(key="employees/<id>/<uuid>_file.pdf", content=raw_bytes)
    data = await storage.read(key)
    await storage.delete(key)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from app.core.config import settings
from app.core.exceptions import StorageError


class StorageBackend(Protocol):
    async def save(self, key: str, content: bytes) -> str: ...
    async def read(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


class LocalStorageBackend:
    """Writes files under a local directory. Default for development."""

    def __init__(self, root_dir: str) -> None:
        self.root = Path(root_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        # Prevent path traversal — keys must stay inside root.
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents and path != self.root.resolve():
            raise StorageError("Invalid storage key")
        return path

    async def save(self, key: str, content: bytes) -> str:
        path = self._resolve(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        try:
            await asyncio.to_thread(_write)
        except OSError as exc:
            raise StorageError(f"Failed to save file: {exc}") from exc
        return key

    async def read(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.exists():
            raise StorageError("File not found in storage")
        try:
            return await asyncio.to_thread(path.read_bytes)
        except OSError as exc:
            raise StorageError(f"Failed to read file: {exc}") from exc

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        try:
            await asyncio.to_thread(path.unlink, True)  # missing_ok=True
        except OSError as exc:
            raise StorageError(f"Failed to delete file: {exc}") from exc


class S3StorageBackend:
    """
    S3-compatible backend. Works for AWS S3, Cloudflare R2, and MinIO —
    all three speak the same S3 API; only the endpoint URL differs.
    """

    def __init__(self) -> None:
        import boto3

        client_kwargs: dict = {
            "region_name": settings.AWS_REGION,
        }
        if settings.AWS_ACCESS_KEY_ID:
            client_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
            client_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
        if settings.S3_ENDPOINT_URL:
            client_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL

        self._client = boto3.client("s3", **client_kwargs)
        self._bucket = settings.S3_BUCKET_NAME

    async def save(self, key: str, content: bytes) -> str:
        try:
            await asyncio.to_thread(
                self._client.put_object, Bucket=self._bucket, Key=key, Body=content
            )
        except Exception as exc:  # noqa: BLE001 — boto3 raises many exception types
            raise StorageError(f"Failed to upload file: {exc}") from exc
        return key

    async def read(self, key: str) -> bytes:
        try:
            obj = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
            return await asyncio.to_thread(obj["Body"].read)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Failed to download file: {exc}") from exc

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(
                self._client.delete_object, Bucket=self._bucket, Key=key
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Failed to delete file: {exc}") from exc


_storage_instance: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Return the configured storage backend (cached singleton)."""
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance

    if settings.STORAGE_BACKEND == "local":
        _storage_instance = LocalStorageBackend(settings.STORAGE_LOCAL_DIR)
    else:
        _storage_instance = S3StorageBackend()
    return _storage_instance
