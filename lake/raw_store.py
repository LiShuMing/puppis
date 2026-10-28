"""Raw object store: local file:// (default) or S3-compatible (Aliyun OSS)."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
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
    return hashlib.sha256(item_id.encode("utf-8")).hexdigest()


def _safe_component(value: str) -> str:
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in value):
        raise ValueError("invalid storage component")
    return value


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
    """Publish content-addressed raw JSON without replacing existing versions."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root).expanduser().resolve() if root else default_raw_root()

    def path_for(
        self,
        connector_id: str,
        item_id: str,
        *,
        when: datetime | None = None,
        digest: str,
    ) -> Path:
        yyyy, mm, _when = _yyyy_mm(when)
        return (
            self.root
            / "sources"
            / _safe_component(connector_id)
            / "raw"
            / yyyy
            / mm
            / _safe_item_id(item_id)
            / f"{digest}.json"
        )

    def write(
        self,
        connector_id: str,
        item_id: str,
        payload: dict[str, Any] | bytes | str,
        *,
        when: datetime | None = None,
    ) -> tuple[str, str]:
        """Atomically publish complete bytes, never replace an existing version."""
        data = _serialize_payload(payload)
        digest = hashlib.sha256(data).hexdigest()
        path = self.path_for(connector_id, item_id, when=when, digest=digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
            temp_path = Path(temp.name)
            try:
                temp.write(data)
                temp.flush()
                os.fsync(temp.fileno())
            except BaseException:
                temp_path.unlink(missing_ok=True)
                raise
        try:
            try:
                os.link(temp_path, path)
            except FileExistsError:
                if path.read_bytes() != data:
                    raise ValueError("existing raw object failed content verification")
        finally:
            temp_path.unlink(missing_ok=True)
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
            / _safe_component(connector_id)
            / "errors"
            / yyyy
            / mm
            / f"{_safe_component(name)}.json"
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
    """S3-compatible raw store (Aliyun OSS / MinIO) via Apache OpenDAL. Lazy-imports opendal."""

    def __init__(
        self,
        *,
        bucket: str | None = None,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str | None = None,
        prefix: str | None = None,
        operator: Any | None = None,
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
        self._operator = operator

    def _get_operator(self) -> Any:
        if self._operator is not None:
            return self._operator
        import opendal  # lazy: local storage does not require OpenDAL at import

        # OSS requires virtual-hosted addressing. OpenDAL does not send CRC32
        # trailers by default, so no checksum override is needed for OSS.
        kwargs: dict[str, str] = {
            "bucket": self.bucket,
            "region": self.region,
            "root": "/",
            "enable_virtual_host_style": "true",
        }
        if self.endpoint_url:
            kwargs["endpoint"] = self.endpoint_url
        if self.access_key and self.secret_key:
            kwargs.update(
                access_key_id=self.access_key,
                secret_access_key=self.secret_key,
                disable_config_load="true",
                disable_ec2_metadata="true",
            )
        self._operator = opendal.Operator("s3", **kwargs)
        return self._operator

    def _key_for(
        self,
        connector_id: str,
        item_id: str,
        *,
        when: datetime | None = None,
        kind: str = "raw",
        digest: str | None = None,
    ) -> str:
        yyyy, mm, _when = _yyyy_mm(when)
        safe = f"{_safe_item_id(item_id)}/{digest}" if kind == "raw" else _safe_component(item_id)
        return f"{self.prefix}/sources/{_safe_component(connector_id)}/{kind}/{yyyy}/{mm}/{safe}.json"

    def _uri_for(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

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
        key = self._key_for(connector_id, item_id, when=when, kind="raw", digest=digest)
        uri = self._uri_for(key)
        operator = self._get_operator()
        from opendal.exceptions import AlreadyExists, ConditionNotMatch

        try:
            operator.write(
                key, data, content_type="application/json",
                user_metadata={"sha256": digest}, if_not_exists=True,
            )
        except (AlreadyExists, ConditionNotMatch):
            if operator.read(key) != data:
                raise ValueError("existing raw object failed content verification")
        # Unsupported conditional writes fail closed; no overwrite fallback.
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
        operator = self._get_operator()
        operator.write(
            key, data, content_type="application/json",
            user_metadata={"sha256": hashlib.sha256(data).hexdigest()},
        )
        return self._uri_for(key)


OpenDalRawStore = S3RawStore


def open_raw_store(root: Path | str | None = None) -> LocalRawStore | S3RawStore:
    """Factory: local by default; S3 when EVIDPLANE_RAW_BACKEND=s3."""
    backend = (os.environ.get("EVIDPLANE_RAW_BACKEND") or "local").strip().lower()
    if backend in ("s3", "oss", "minio"):
        return S3RawStore()
    return LocalRawStore(root)


get_raw_store = open_raw_store
