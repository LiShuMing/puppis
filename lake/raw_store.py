"""Raw object store: local file:// (default) or S3-compatible (Aliyun OSS)."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


def default_raw_root() -> Path:
    override = os.environ.get("EVIDPLANE_RAW_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".evidplane").resolve()


def _serialize_payload(payload: dict[str, Any] | bytes | str) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode(
        "utf-8"
    )


def _safe_item_id(item_id: str) -> str:
    return item_id.replace("/", "_")


def _yyyy_mm(when: datetime | None) -> tuple[str, str, datetime]:
    when = when or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return f"{when.year:04d}", f"{when.month:02d}", when


@runtime_checkable
class RawStore(Protocol):
    """Minimal write surface used by lake.ingest."""

    root: str | Path

    def write(
        self,
        connector_id: str,
        item_id: str,
        payload: dict[str, Any] | bytes | str,
        *,
        when: datetime | None = None,
    ) -> tuple[str, str]:
        """Return (content_sha256, uri)."""
        ...

    def write_error(
        self,
        connector_id: str,
        name: str,
        payload: dict[str, Any],
        *,
        when: datetime | None = None,
    ) -> str:
        ...


class LocalRawStore:
    """Write immutable raw JSON under sources/<connector>/raw/yyyy/mm/<item_id>.json."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root else default_raw_root()

    def path_for(
        self,
        connector_id: str,
        item_id: str,
        *,
        when: datetime | None = None,
    ) -> Path:
        yyyy, mm, _when = _yyyy_mm(when)
        return (
            self.root
            / "sources"
            / connector_id
            / "raw"
            / yyyy
            / mm
            / f"{_safe_item_id(item_id)}.json"
        )

    def write(
        self,
        connector_id: str,
        item_id: str,
        payload: dict[str, Any] | bytes | str,
        *,
        when: datetime | None = None,
    ) -> tuple[str, str]:
        """Serialize payload, write once, return (content_sha256, file:// uri)."""
        data = _serialize_payload(payload)
        digest = hashlib.sha256(data).hexdigest()
        path = self.path_for(connector_id, item_id, when=when)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            existing = path.read_bytes()
            if hashlib.sha256(existing).hexdigest() == digest:
                return digest, path.as_uri()
        path.write_bytes(data)
        return digest, path.as_uri()

    def write_error(
        self,
        connector_id: str,
        name: str,
        payload: dict[str, Any],
        *,
        when: datetime | None = None,
    ) -> str:
        yyyy, mm, _when = _yyyy_mm(when)
        path = (
            self.root
            / "sources"
            / connector_id
            / "errors"
            / yyyy
            / mm
            / f"{name}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path.as_uri()


def _env_first(*names: str) -> str | None:
    for name in names:
        val = os.environ.get(name)
        if val is not None and str(val).strip() != "":
            return str(val).strip()
    return None


class S3RawStore:
    """S3-compatible raw store (Aliyun OSS / MinIO) via boto3. Lazy-imports boto3."""

    def __init__(
        self,
        *,
        bucket: str | None = None,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str | None = None,
        prefix: str | None = None,
    ) -> None:
        self.bucket = bucket or _env_first("EVIDPLANE_S3_BUCKET", "AWS_S3_BUCKET")
        if not self.bucket:
            raise RuntimeError(
                "S3RawStore requires EVIDPLANE_S3_BUCKET (or AWS_S3_BUCKET)"
            )
        self.endpoint_url = endpoint_url or _env_first(
            "EVIDPLANE_S3_ENDPOINT", "AWS_ENDPOINT_URL"
        )
        self.access_key = access_key or _env_first(
            "EVIDPLANE_S3_ACCESS_KEY", "AWS_ACCESS_KEY_ID"
        )
        self.secret_key = secret_key or _env_first(
            "EVIDPLANE_S3_SECRET_KEY", "AWS_SECRET_ACCESS_KEY"
        )
        self.region = (
            region
            or _env_first("EVIDPLANE_S3_REGION", "AWS_DEFAULT_REGION")
            or "cn-hangzhou"
        )
        raw_prefix = (
            prefix if prefix is not None else _env_first("EVIDPLANE_S3_PREFIX")
        )
        self.prefix = (raw_prefix or "evidplane").strip().strip("/")
        self.root = f"s3://{self.bucket}/{self.prefix}"
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        import boto3  # lazy: local smoke must not require boto3 at import

        kwargs: dict[str, Any] = {"region_name": self.region}
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        if self.access_key and self.secret_key:
            kwargs["aws_access_key_id"] = self.access_key
            kwargs["aws_secret_access_key"] = self.secret_key
        self._client = boto3.client("s3", **kwargs)
        return self._client

    def _key_for(
        self,
        connector_id: str,
        item_id: str,
        *,
        when: datetime | None = None,
        kind: str = "raw",
    ) -> str:
        yyyy, mm, _when = _yyyy_mm(when)
        safe = _safe_item_id(item_id) if kind == "raw" else item_id
        return f"{self.prefix}/sources/{connector_id}/{kind}/{yyyy}/{mm}/{safe}.json"

    def _uri_for(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def _existing_sha256(self, client: Any, key: str) -> str | None:
        """Return Metadata sha256 if object exists; None if missing."""
        try:
            head = client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:  # botocore ClientError
            resp = getattr(exc, "response", None) or {}
            http = (resp.get("ResponseMetadata") or {}).get("HTTPStatusCode")
            code = (resp.get("Error") or {}).get("Code")
            # 403: some OSS policies deny HeadObject on missing keys — treat as miss (dedupe may no-op).
            if http in (403, 404) or code in ("404", "NoSuchKey", "NotFound"):
                return None
            raise
        meta = head.get("Metadata") or {}
        return meta.get("sha256") or meta.get("content_sha256")

    def write(
        self,
        connector_id: str,
        item_id: str,
        payload: dict[str, Any] | bytes | str,
        *,
        when: datetime | None = None,
    ) -> tuple[str, str]:
        data = _serialize_payload(payload)
        digest = hashlib.sha256(data).hexdigest()
        key = self._key_for(connector_id, item_id, when=when, kind="raw")
        uri = self._uri_for(key)
        client = self._get_client()
        if self._existing_sha256(client, key) == digest:
            return digest, uri
        client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType="application/json",
            Metadata={"sha256": digest},
        )
        return digest, uri

    def write_error(
        self,
        connector_id: str,
        name: str,
        payload: dict[str, Any],
        *,
        when: datetime | None = None,
    ) -> str:
        data = _serialize_payload(payload)
        key = self._key_for(connector_id, name, when=when, kind="errors")
        client = self._get_client()
        client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType="application/json",
        )
        return self._uri_for(key)


def open_raw_store(root: Path | str | None = None) -> LocalRawStore | S3RawStore:
    """Factory: local by default; S3 when EVIDPLANE_RAW_BACKEND=s3."""
    backend = (os.environ.get("EVIDPLANE_RAW_BACKEND") or "local").strip().lower()
    if backend in ("s3", "oss", "minio"):
        return S3RawStore()
    return LocalRawStore(root)


get_raw_store = open_raw_store
