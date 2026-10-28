#!/usr/bin/env python3
"""Start, stop, inspect and back up the local Evidplane workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "data" / "platform"
STATE = RUNTIME / "server.json"


def read_state():
    return json.loads(STATE.read_text()) if STATE.exists() else None


def owned(state):
    if not state:
        return False
    try:
        cmd = Path(f"/proc/{int(state['pid'])}/cmdline").read_bytes().split(b"\0")
        return (
            b"console.server" in cmd
            and Path(f"/proc/{state['pid']}/cwd").resolve() == ROOT
        )
    except (OSError, ValueError):
        return False


def health(state):
    if not owned(state):
        return False
    try:
        with urlopen(state["url"] + "/api/health", timeout=2) as response:
            return json.load(response).get("status") == "ok"
    except OSError:
        return False


def start(port):
    state = read_state()
    if owned(state):
        if health(state):
            print(f"Evidplane 已运行：{state['url']}")
            return
        raise RuntimeError("已存在本平台进程但健康检查失败，请先 stop 并检查日志")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault(
        "EVIDPLANE_DB", env.get("PUPPIS_DB") or str(ROOT / "data" / "puppis.db")
    )
    env.setdefault("EVIDPLANE_RAW_ROOT", str(RUNTIME / "raw"))
    env.setdefault("EVIDPLANE_RAW_BACKEND", "local")
    for key in ("EVIDPLANE_DB", "EVIDPLANE_RAW_ROOT"):
        env[key] = str(Path(env[key]).expanduser().resolve())
    python = ROOT / ".venv" / "bin" / "python"
    if not python.exists():
        raise RuntimeError("请先创建 .venv 并安装依赖，见 docs/LOCAL_PLATFORM.md")
    with (RUNTIME / "server.log").open("a") as log:
        process = subprocess.Popen(
            [str(python), "-m", "console.server", "--port", str(port)],
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    state = {
        "pid": process.pid,
        "url": f"http://127.0.0.1:{port}",
        "db": str(Path(env["EVIDPLANE_DB"]).expanduser().resolve()),
        "raw": str(Path(env["EVIDPLANE_RAW_ROOT"]).expanduser().resolve()),
        "backend": env["EVIDPLANE_RAW_BACKEND"],
    }
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    for _ in range(50):
        if process.poll() is not None:
            STATE.unlink(missing_ok=True)
            raise RuntimeError(
                "启动失败，请检查 data/platform/server.log（端口可能已被占用）"
            )
        if health(state):
            print(f"Evidplane 已启动：{state['url']}\n日志：{RUNTIME / 'server.log'}")
            return
        time.sleep(0.1)
    process.terminate()
    process.wait(timeout=5)
    STATE.unlink(missing_ok=True)
    raise RuntimeError("启动超时，请检查日志后重试")


def stop():
    state = read_state()
    if owned(state):
        os.kill(state["pid"], signal.SIGTERM)
        for _ in range(50):
            if not owned(state):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("进程尚未退出，保留状态文件，请检查后重试")
    STATE.unlink(missing_ok=True)
    print("Evidplane 已停止")


def backup(output):
    state = read_state()
    if not state or state["backend"] != "local":
        raise RuntimeError(
            "此命令需要已启动/有运行记录的 local 存储；S3 请单独备份 bucket"
        )
    destination = Path(output).expanduser().resolve()
    raw = Path(state["raw"])
    if destination == raw or destination.is_relative_to(raw):
        raise RuntimeError("备份位置不能在原始资料目录内")
    destination.mkdir(parents=True, exist_ok=False)
    try:
        with (
            sqlite3.connect(f"file:{state['db']}?mode=ro", uri=True) as source,
            sqlite3.connect(destination / "evidplane.db") as target,
        ):
            source.backup(target)
        # Snapshot DB first, then immutable raw versions referenced by it.
        if raw.exists():
            shutil.copytree(
                raw, destination / "raw", ignore=shutil.ignore_patterns("tmp*")
            )
        else:
            (destination / "raw").mkdir()
        verify_snapshot(destination, raw)
        (destination / "manifest.json").write_text(
            json.dumps(
                {
                    "format": 1,
                    "created_at": datetime.now(UTC).isoformat(),
                    "database": "evidplane.db",
                    "raw": "raw",
                    "original_raw_root": str(raw),
                    "note": "DB + raw backup; workspace restore remaps file:// references. Not a raw-only replay archive.",
                },
                indent=2,
            )
            + "\n"
        )
    except Exception:
        shutil.rmtree(destination)
        raise
    print(f"备份已完成：{destination}")


def verify_snapshot(directory: Path, original_root: Path):
    with sqlite3.connect(
        f"file:{directory / 'evidplane.db'}?mode=ro", uri=True
    ) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("备份数据库完整性检查失败")
        rows = conn.execute("SELECT content_hash, uri FROM raw_objects").fetchall()
    for digest, uri in rows:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            raise RuntimeError("备份包含非本地 raw 引用，需单独迁移其存储")
        try:
            relative = Path(unquote(parsed.path)).relative_to(original_root)
            content = (directory / "raw" / relative).read_bytes()
        except (ValueError, OSError) as exc:
            raise RuntimeError(
                "备份缺少引用的 raw 文件；历史演示/其他 raw 目录需先整理"
            ) from exc
        if hashlib.sha256(content).hexdigest() != digest:
            raise RuntimeError("raw hash 校验失败；备份未标记成功")


def restore(backup_path, output):
    source = Path(backup_path).expanduser().resolve()
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest.get("format") != 1:
        raise ValueError("不支持的备份格式")
    old_root = Path(manifest["original_raw_root"])
    verify_snapshot(source, old_root)
    destination = Path(output).expanduser().resolve()
    if destination.exists():
        raise ValueError("恢复目标必须是尚不存在的目录，不覆盖当前数据")
    shutil.copytree(source, destination)
    try:
        with sqlite3.connect(destination / "evidplane.db") as conn:
            rows = conn.execute("SELECT raw_id, uri FROM raw_objects").fetchall()
            for raw_id, uri in rows:
                relative = Path(unquote(urlparse(uri).path)).relative_to(old_root)
                new_uri = (destination / "raw" / relative).as_uri()
                conn.execute(
                    "UPDATE raw_objects SET uri=? WHERE raw_id=?", (new_uri, raw_id)
                )
                conn.execute(
                    "UPDATE items SET raw_uri=? WHERE raw_uri=?", (new_uri, uri)
                )
        verify_snapshot(destination, destination / "raw")
        manifest["original_raw_root"] = str(destination / "raw")
        (destination / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )
    except Exception:
        shutil.rmtree(destination)
        raise
    print(
        f"恢复已完成：{destination}\n启动时设置 EVIDPLANE_DB={destination / 'evidplane.db'} EVIDPLANE_RAW_ROOT={destination / 'raw'}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["start", "stop", "status", "backup", "restore"]
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output", help="New backup directory")
    parser.add_argument("--backup", help="Backup directory to restore")
    args = parser.parse_args()
    try:
        if args.command == "start":
            if not 1 <= args.port <= 65535:
                raise ValueError("端口必须为 1–65535")
            start(args.port)
        elif args.command == "stop":
            stop()
        elif args.command == "status":
            state = read_state()
            if not health(state):
                print("Evidplane 未运行")
                return 1
            print(f"Evidplane 运行正常：{state['url']}")
        elif args.command == "restore" and args.backup and args.output:
            restore(args.backup, args.output)
        elif args.command == "backup" and args.output:
            backup(args.output)
        else:
            parser.error(
                "backup requires --output; restore requires --backup and --output"
            )
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
