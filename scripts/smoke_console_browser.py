#!/usr/bin/env python3
"""Browser acceptance for the console; uses disposable DB/raw and an owned server.

Run with a Python containing playwright 1.58 (optional [browser] extra).
The server runs using the repository's .venv. Nothing writes to the user library.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="evidplane-browser-") as tmp:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = os.environ.copy()
        env.update(
            EVIDPLANE_DB=f"{tmp}/test.db",
            EVIDPLANE_RAW_ROOT=f"{tmp}/raw",
            EVIDPLANE_RAW_BACKEND="local",
        )
        for name in ("NOTION_TOKEN", "NOTION_DATABASE_ID", "NOTION_PAGE_IDS"):
            env.pop(name, None)
        url = f"http://127.0.0.1:{port}"
        with open(f"{tmp}/server.log", "w") as log:
            process = subprocess.Popen(
                [
                    str(ROOT / ".venv/bin/python"),
                    "-m",
                    "console.server",
                    "--port",
                    str(port),
                ],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
            )
        try:
            for _ in range(80):
                try:
                    with urlopen(url + "/api/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    if process.poll() is not None:
                        raise RuntimeError(Path(f"{tmp}/server.log").read_text())
                    time.sleep(0.1)
            else:
                raise RuntimeError("Browser test server did not become ready")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1050})
                errors = []
                external = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "request",
                    lambda request: (
                        external.append(request.url)
                        if not request.url.startswith(url)
                        else None
                    ),
                )
                page.goto(url, wait_until="networkidle")
                page.get_by_text("从第一条证据开始").wait_for()
                assert page.locator("#stat-total").inner_text() == "0"
                page.locator('nav a[data-view="sources"]').click()
                page.locator("#note-title").fill("项目进展与下一步")
                page.locator("#note-text").fill(
                    "Milestone: 完成本机工作台。下一步：整理项目资料。<img src=x onerror=window.__xss=1>"
                )
                page.locator("#note-url").fill("https://example.com/project")
                page.get_by_role("button", name="保存到证据库").click()
                page.locator("#view-library").wait_for(state="visible")
                page.locator("#library-items .evidence-row").wait_for()
                page.locator("#search-query").fill("项目")
                page.locator("#search-source").select_option("manual")
                page.get_by_role("button", name="搜索", exact=True).click()
                page.wait_for_function(
                    "document.getElementById('search-summary').textContent === '共 1 条证据'"
                )
                page.locator("#library-items .evidence-row").click()
                page.locator("#detail-dialog").wait_for(state="visible")
                assert "Milestone" in page.locator(".detail-body").inner_text()
                assert page.locator(".detail-body img").count() == 0
                assert page.evaluate("window.__xss || null") is None
                page.keyboard.press("Escape")
                page.locator('nav a[data-view="pack"]').click()
                page.locator("#generate-pack").click()
                page.locator("#pack-text").wait_for(state="visible")
                assert "Milestone" in page.locator("#pack-text").inner_text()
                page.locator(".citation-button").click()
                page.locator("#detail-dialog").wait_for(state="visible")
                page.locator("#close-detail").click()
                page.locator('nav a[data-view="sources"]').click()
                page.locator('[data-tab="file"]').click()
                page.locator("#import-file").set_input_files(
                    str(ROOT / "connectors/calendar/demo_pull.json")
                )
                page.get_by_role("button", name="导入文件", exact=False).click()
                page.locator("#view-library").wait_for(state="visible")
                page.locator('nav a[data-view="sources"]').click()
                page.locator("#import-demo").click()
                page.locator("#view-library").wait_for(state="visible")
                page.locator('nav a[data-view="overview"]').click()
                page.locator("#demo-note").wait_for(state="visible")
                assert not page.evaluate(
                    "document.documentElement.scrollWidth > innerWidth"
                )
                if args.screenshots:
                    args.screenshots.mkdir(parents=True, exist_ok=True)
                    page.screenshot(
                        path=str(args.screenshots / "console-desktop.png"),
                        full_page=True,
                    )
                page.set_viewport_size({"width": 390, "height": 844})
                for view in ("overview", "library", "pack", "sources"):
                    page.locator(f'nav a[data-view="{view}"]').click()
                    page.locator(f"#view-{view}").wait_for(state="visible")
                    assert not page.evaluate(
                        "document.documentElement.scrollWidth > innerWidth"
                    ), view
                if args.screenshots:
                    page.screenshot(
                        path=str(args.screenshots / "console-mobile.png"),
                        full_page=True,
                    )
                assert not errors, errors
                assert not external, external
                saved_total = page.request.get(url + "/api/status").json()["total"]
                process.terminate()
                process.wait(timeout=10)
                with open(f"{tmp}/server.log", "a") as log:
                    process = subprocess.Popen(
                        [
                            str(ROOT / ".venv/bin/python"),
                            "-m",
                            "console.server",
                            "--port",
                            str(port),
                        ],
                        cwd=ROOT,
                        env=env,
                        stdout=log,
                        stderr=log,
                    )
                for _ in range(80):
                    try:
                        with urlopen(url + "/api/health", timeout=1):
                            break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Restarted server did not become ready")
                page.reload(wait_until="networkidle")
                assert (
                    page.request.get(url + "/api/status").json()["total"] == saved_total
                )
                browser.close()
                print(
                    json.dumps(
                        {
                            "result": "BROWSER SMOKE OK",
                            "checks": [
                                "empty state",
                                "manual import",
                                "CJK search + filter",
                                "detail + inert HTML",
                                "pack + cite roundtrip",
                                "file import",
                                "explicit demo",
                                "mobile four views",
                                "no external requests",
                                "no JS errors",
                                "process restart preserves evidence",
                            ],
                        },
                        ensure_ascii=False,
                    )
                )
        finally:
            process.terminate()
            process.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
