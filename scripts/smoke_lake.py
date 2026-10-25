#!/usr/bin/env python3
"""Smoke: seed → search / get / pack against the local SQLite lake."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from lake.api import get, pack, search
from lake.db import default_db_path
from lake.seed import seed_fake


def main() -> int:
    db = default_db_path()
    seed_info = seed_fake(db, force=True)
    print("=== seed ===")
    print(json.dumps(seed_info, ensure_ascii=False, indent=2))

    print("\n=== search(q='pack') ===")
    s = search(q="pack", since_days=14, limit=5)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    assert s["count"] >= 1, "expected FTS hit for 'pack'"

    print("\n=== search(source='notion', since_days=7) ===")
    s2 = search(source="notion", since_days=7, limit=10)
    print(json.dumps({"count": s2["count"], "ids": [i["item_id"] for i in s2["items"]]}, indent=2))
    assert s2["count"] >= 1

    first_id = s["items"][0]["item_id"]
    print(f"\n=== get({first_id}) ===")
    g = get(first_id)
    print(json.dumps({k: g[k] for k in ("item_id", "title", "url", "provenance") if k in g}, indent=2))
    print("text excerpt:", (g.get("text") or "")[:160])
    assert "error" not in g

    print("\n=== pack(work) ===")
    p = pack(template="work", budget_tokens=2000, since_days=7)
    print(
        json.dumps(
            {
                "item_count": p["item_count"],
                "token_estimate": p["token_estimate"],
                "cites": p["cites"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("\n--- pack text (first 800 chars) ---\n")
    print(p["text"][:800])
    assert p["item_count"] >= 1
    assert p["token_estimate"] > 0
    assert all(c.get("item_id") for c in p["cites"])

    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
