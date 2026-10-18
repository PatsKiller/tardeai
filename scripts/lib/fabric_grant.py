"""Resolve and verify the guard grant a packet's --apply runs under (TRADEAI_FABRIC_GRANT).

Packets used to accept any non-empty TRADEAI_FABRIC_GRANT, so a free-text label passed as easily as a real grant.
This reads the guard ledger (read-only; it never consumes a use) and accepts the value only when it is the grant_id
(or an unambiguous prefix of at least 8 hex chars) of an ACTIVE grant of one of the allowed tiers.

  python3 scripts/lib/fabric_grant.py id <tier>                    -> prints the active grant_id, exit 1 if none
  python3 scripts/lib/fabric_grant.py verify <grant> <tier>[,...]  -> prints "tier grant_id", exit 1 when refused
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

MIN_PREFIX = 8


def ledger_path() -> Path:
    base = os.environ.get("GUARD_APPROVALS_DIR") or str(Path.home() / ".cursor" / "approvals")
    return Path(base) / "grants.json"


def active_grants(now: float | None = None) -> dict[str, dict]:
    now = time.time() if now is None else now
    try:
        doc = json.loads(ledger_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    grants = doc.get("grants", doc) if isinstance(doc, dict) else {}
    out = {}
    for tier, g in (grants or {}).items():
        if not isinstance(g, dict) or not g.get("grant_id"):
            continue
        uses = int(g.get("uses", 0))
        if float(g.get("expires", 0)) > now and (uses < 0 or uses > 0):
            out[tier] = g
    return out


def grant_id(tier: str) -> str | None:
    g = active_grants().get(tier)
    return str(g["grant_id"]) if g else None


def verify(value: str, tiers: list[str]) -> tuple[str, str] | None:
    value = (value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{%d,}" % MIN_PREFIX, value):
        return None
    hits = [(t, str(g["grant_id"])) for t, g in active_grants().items()
            if t in tiers and str(g["grant_id"]).lower().startswith(value)]
    return hits[0] if len(hits) == 1 else None


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "id":
        gid = grant_id(argv[1])
        if not gid:
            print(f"no active {argv[1]} grant", file=sys.stderr)
            return 1
        print(gid)
        return 0
    if len(argv) == 3 and argv[0] == "verify":
        hit = verify(argv[1], [t for t in argv[2].split(",") if t])
        if not hit:
            print(f"TRADEAI_FABRIC_GRANT is not the id of an active {argv[2]} grant "
                  f"(get it with: bin/guard id {argv[2].split(',')[0]})", file=sys.stderr)
            return 1
        print(f"{hit[0]} {hit[1]}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
