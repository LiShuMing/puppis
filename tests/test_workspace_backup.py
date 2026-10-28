import json
from pathlib import Path

import pytest

from console.service import Service
from lake.query import get
from lake.raw_store import LocalRawStore
from scripts import workspace


def test_backup_restore_remaps_raw_and_preserves_queryability(tmp_path, monkeypatch):
    service = Service(
        tmp_path / "original.db", LocalRawStore(tmp_path / "original-raw")
    )
    created = service.import_text("备份验收", "backup evidence")
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {"backend": "local", "db": service.db_path, "raw": str(service.store.root)}
        )
    )
    monkeypatch.setattr(workspace, "STATE", state)
    backup = tmp_path / "backup"
    workspace.backup(backup)
    restored = tmp_path / "restored"
    workspace.restore(backup, restored)
    item = get(created["item_id"], db_path=str(restored / "evidplane.db"))
    assert item["text"] == "backup evidence"
    assert item["raw_uri"].startswith((restored / "raw").as_uri())
    assert Path(item["raw_uri"].removeprefix("file://")).read_bytes()
    workspace.verify_snapshot(restored, restored / "raw")
    with pytest.raises(ValueError, match="尚不存在"):
        workspace.restore(backup, restored)


def test_backup_refuses_to_report_success_with_corrupt_raw(tmp_path, monkeypatch):
    service = Service(tmp_path / "original.db", LocalRawStore(tmp_path / "raw"))
    created = service.import_text("Corrupt", "test")
    item = service.get(created["item_id"])
    Path(item["raw_uri"].removeprefix("file://")).write_bytes(b"corrupted")
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {"backend": "local", "db": service.db_path, "raw": str(service.store.root)}
        )
    )
    monkeypatch.setattr(workspace, "STATE", state)
    with pytest.raises(RuntimeError, match="hash"):
        workspace.backup(tmp_path / "backup")
    assert not (tmp_path / "backup").exists()
