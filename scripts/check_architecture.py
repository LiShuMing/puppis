#!/usr/bin/env python3
"""Check static package boundaries, including relative and function-local imports."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYERS = {"connectors", "lake", "serve", "console"}
NETWORK = {
    "http",
    "httpx",
    "httpx2",
    "requests",
    "urllib",
    "socket",
    "aiohttp",
    "notion_client",
    "googleapiclient",
    "google",
    "google_auth_oauthlib",
    "boto3",
    "botocore",
    "opendal",
}


def violations(source: str, path: str) -> list[str]:
    """Return violations for a repository-relative Python path."""
    file = Path(path)
    layer = file.parts[0]
    package = ".".join(file.parent.parts)
    errors = []
    for node in ast.walk(ast.parse(source, filename=path)):
        imports: list[str] = []
        if isinstance(node, ast.Import):
            imports = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            try:
                module = (
                    resolve_name("." * node.level + (node.module or ""), package)
                    if node.level
                    else (node.module or "")
                )
            except (ImportError, ValueError):
                errors.append(f"{path}:{node.lineno}: invalid relative import")
                continue
            # Resolve package imports such as `from lake import db` too.
            if module in LAYERS:
                imports = [f"{module}.{alias.name}" for alias in node.names]
            else:
                imports = [module]
        for module in imports:
            top = module.split(".")[0]
            allowed = True
            if layer == "connectors" and top in LAYERS:
                own = (
                    ".".join(file.parts[:2])
                    if len(file.parts) > 2
                    else "connectors.base"
                )
                allowed = (
                    module == "connectors.base"
                    or module == own
                    or module.startswith(own + ".")
                )
            elif layer == "lake" and top in LAYERS:
                allowed = top == "lake" or (
                    path == "lake/ingest.py" and module == "connectors.base"
                )
            elif layer == "serve" and top in LAYERS:
                allowed = top == "serve" or module == "lake.query"
            elif layer == "console" and top in LAYERS:
                if path == "console/service.py":
                    allowed = top in {"console", "connectors", "lake"}
                else:
                    allowed = top == "console"
            if (
                top in NETWORK
                and module != "urllib.parse"
                and layer in {"lake", "serve", "console"}
            ):
                allowed = path == "lake/raw_store.py" and top == "opendal"
            if path == "connectors/base.py" and top in NETWORK:
                allowed = False
            if not allowed:
                errors.append(f"{path}:{node.lineno}: forbidden dependency {module}")
    return errors


def main() -> int:
    errors = []
    count = 0
    for layer in sorted(LAYERS):
        for file in sorted((ROOT / layer).rglob("*.py")):
            count += 1
            path = file.relative_to(ROOT).as_posix()
            try:
                errors.extend(violations(file.read_text(encoding="utf-8"), path))
            except SyntaxError as exc:
                errors.append(f"{path}:{exc.lineno}: {exc.msg}")
    if errors:
        print("\n".join(errors))
        return 1
    print(f"Architecture OK ({count} Python files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
