#!/usr/bin/env python3
"""Smoke: init + seed + print pack(work) without an MCP client."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from lake.db import default_db_path
from lake.query import pack_work, search
from lake.seed import seed_fake


def main() -> int:
    db = default_db_path()
    seed_info = seed_fake(db, force=True)
    print("=== seed ===")
    print(json.dumps(seed_info, ensure_ascii=False, indent=2))

    print("\n=== search(q='PR') ===")
    s = search(q="PR", since_days=14, limit=5)
    print(json.dumps({"count": s["count"], "titles": [i["title"] for i in s["items"]]}, ensure_ascii=False, indent=2))

    print("\n=== pack_work(budget_tokens=3000) ===")
    p = pack_work(budget_tokens=3000, since_days=14)
    print(
        json.dumps(
            {
                "item_count": p["item_count"],
                "token_estimate": p["token_estimate"],
                "budget_tokens": p["budget_tokens"],
                "cite_count": len(p["cites"]),
                "titles": [c["title"] for c in p["cites"]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("\n--- pack text ---\n")
    print(p["text"])
    assert p["item_count"] >= 1, "expected at least one pack item"
    assert p["cites"], "expected cites"
    assert all(c.get("item_id") for c in p["cites"])
    assert p["token_estimate"] <= p["budget_tokens"], (
        f"pack must hard-cap estimate at budget: {p['token_estimate']} > {p['budget_tokens']}"
    )
    print("\nSMOKE_PACK OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
