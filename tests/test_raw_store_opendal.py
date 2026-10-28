import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

import opendal
import pytest

from lake.raw_store import OpenDalRawStore, S3RawStore

WHEN = datetime(2026, 3, 4, tzinfo=timezone.utc)


class FakeOperator:
    def __init__(self, missing=opendal.exceptions.NotFound):
        self.objects = {}
        self.writes = []
        self.missing = missing

    def stat(self, key):
        if key not in self.objects:
            raise self.missing("missing object")
        return SimpleNamespace(user_metadata=self.objects[key][1]["user_metadata"])

    def write(self, key, data, **kwargs):
        if kwargs.get("if_not_exists") and key in self.objects:
            raise opendal.exceptions.ConditionNotMatch("exists")
        self.writes.append((key, data, kwargs))
        self.objects[key] = (data, kwargs)

    def read(self, key):
        return self.objects[key][0]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    import os

    for name in os.environ:
        if name.startswith(("EVIDPLANE_S3_", "AWS_")):
            monkeypatch.delenv(name)


def test_key_uri_and_idempotency():
    operator = FakeOperator()
    store = S3RawStore(bucket="bucket", prefix="/custom/", operator=operator)
    digest, uri = store.write("notion", "a/b", b'{"a":1}', when=WHEN)
    key = f"custom/sources/notion/raw/2026/03/{hashlib.sha256(b'a/b').hexdigest()}/{digest}.json"
    assert uri == f"s3://bucket/{key}"
    assert digest == hashlib.sha256(b'{"a":1}').hexdigest()
    assert operator.writes == [
        (key, b'{"a":1}', {"content_type": "application/json", "user_metadata": {"sha256": digest}, "if_not_exists": True})
    ]
    assert store.write("notion", "a/b", b'{"a":1}', when=WHEN) == (digest, uri)
    assert len(operator.writes) == 1
    changed_digest, changed_uri = store.write("notion", "a/b", b'{"a":2}', when=WHEN)
    assert changed_digest != digest
    assert changed_uri != uri
    assert len(operator.writes) == 2
    assert operator.writes[-1][2]["user_metadata"] == {"sha256": changed_digest}
    assert operator.read(key) == b'{"a":1}'


def test_error_key():
    operator = FakeOperator()
    store = S3RawStore(bucket="bucket", operator=operator)
    assert store.write_error("notion", "failed", {"error": "bad"}, when=WHEN) == (
        "s3://bucket/evidplane/sources/notion/errors/2026/03/failed.json"
    )
    key, data, options = operator.writes[0]
    assert key == "evidplane/sources/notion/errors/2026/03/failed.json"
    assert options == {
        "content_type": "application/json",
        "user_metadata": {"sha256": hashlib.sha256(data).hexdigest()},
    }


def test_corrupt_object_is_not_overwritten():
    operator = FakeOperator()
    store = S3RawStore(bucket="bucket", operator=operator)
    _, uri = store.write("test", "id", b"original", when=WHEN)
    key = uri.removeprefix("s3://bucket/")
    operator.objects[key] = (b"corrupted", {})
    with pytest.raises(ValueError, match="verification"):
        store.write("test", "id", b"original", when=WHEN)
    assert operator.read(key) == b"corrupted"


@pytest.mark.parametrize("error", [opendal.exceptions.PermissionDenied, opendal.exceptions.Unsupported])
def test_failed_conditional_write_does_not_fall_back(error):
    class FailingOperator(FakeOperator):
        def write(self, key, data, **kwargs):
            raise error("conditional write failed")

    operator = FailingOperator()
    with pytest.raises(error):
        S3RawStore(bucket="bucket", operator=operator).write("test", "id", {})
    assert not operator.objects


def test_env_fallback(monkeypatch):
    values = {
        "AWS_S3_BUCKET": "fallback-bucket",
        "AWS_ENDPOINT_URL": "https://oss-cn-hangzhou.aliyuncs.com",
        "AWS_ACCESS_KEY_ID": "dummy-access",
        "AWS_SECRET_ACCESS_KEY": "dummy-secret",
        "AWS_DEFAULT_REGION": "fallback-region",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    store = S3RawStore()
    assert (store.bucket, store.endpoint_url, store.access_key, store.secret_key, store.region) == tuple(values.values())
    assert store.prefix == "evidplane"
    for suffix, value in [
        ("BUCKET", "preferred"), ("ENDPOINT", "https://preferred"),
        ("ACCESS_KEY", "preferred-access"), ("SECRET_KEY", "preferred-secret"),
        ("REGION", "preferred-region"), ("PREFIX", "/preferred-prefix/"),
    ]:
        monkeypatch.setenv(f"EVIDPLANE_S3_{suffix}", value)
    store = S3RawStore()
    assert (store.bucket, store.endpoint_url, store.access_key, store.secret_key, store.region, store.prefix) == (
        "preferred", "https://preferred", "preferred-access", "preferred-secret",
        "preferred-region", "preferred-prefix",
    )


def test_real_operator_construction():
    assert OpenDalRawStore is S3RawStore
    store = S3RawStore(
        bucket="dummy-bucket", endpoint_url="https://oss-cn-hangzhou.aliyuncs.com",
        access_key="dummy-access", secret_key="dummy-secret",
    )
    assert store.region == "cn-hangzhou"
    assert store._operator is None
    operator = store._get_operator()
    assert isinstance(operator, opendal.Operator)
    assert store._get_operator() is operator


def test_operator_configuration(monkeypatch):
    calls = []
    sentinel = object()

    def construct(scheme, **kwargs):
        calls.append((scheme, kwargs))
        return sentinel

    monkeypatch.setattr(opendal, "Operator", construct)
    store = S3RawStore(bucket="bucket", endpoint_url="https://example.com",
                       access_key="access", secret_key="secret")
    assert store._get_operator() is sentinel
    assert calls == [("s3", {
        "bucket": "bucket", "endpoint": "https://example.com",
        "region": "cn-hangzhou", "access_key_id": "access",
        "secret_access_key": "secret", "root": "/",
        "enable_virtual_host_style": "true", "disable_config_load": "true",
        "disable_ec2_metadata": "true",
    })]
