#!/usr/bin/env python3
"""Dip list with valuation (PKG-SELLOFF-INTEL-20261106 E): print it, read-only.

Reads the market-risk snapshot's sectors block (which groups are STRESS or WEAK), the CIO opportunity projection
(sector, industry, conviction), the daily closes, and the Yahoo analyst history through the engine's read-only PgReader. Prints the
ranked list as text (default) or JSON. ``--out PATH`` also writes the JSON to PATH; nothing else is ever written, nothing
is sent, nothing is scheduled. Advisory only: no size, weight, price level, order or stop (``MBI_BEHAVIOR = 0``).

  python3 scripts/market_risk_dip_list.py [--json] [--out PATH] [--days 45] [--limit 30]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib.market_risk import dip_list  # noqa: E402
from scripts.lib.market_risk.policy import load_policy  # noqa: E402

ET = ZoneInfo("America/New_York")


def state_root() -> Path:
    env = os.environ.get("TRADEAI_STATE_ROOT") or os.environ.get("TRADEAI_PERSISTENT_STATE_ROOT")
    return Path(env or Path.home() / "trade-ai-releases" / "persistent-state")


def _json(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def candidates(root: Path) -> list[dict]:
    doc = _json(root / "data" / "cio" / "cio_opportunity_projection.json")
    items = doc.get("items") or {}
    rows = items.values() if isinstance(items, dict) else items
    return [
        {k: it.get(k) for k in ("symbol", "sector", "industry", "conviction", "type")}
        for it in rows
        if isinstance(it, dict) and it.get("symbol")
    ]


def collect(now: datetime, reader, policy: dict, root: Path, *, days: int) -> dict:
    from scripts.lib.market_risk_projection import SNAPSHOT_REL

    snapshot = _json(root / SNAPSHOT_REL)
    sectors = snapshot.get("sectors") if isinstance(snapshot.get("sectors"), dict) else None
    cands = candidates(root)
    stressed = {g["key"] for g in dip_list.stressed_groups(sectors)}
    groups = {g["key"]: g for g in (policy.get("sectors") or {}).get("groups") or []}
    wanted = sorted({x["symbol"].upper() for x in cands if dip_list.membership(x, groups, stressed)})
    rows = reader.analyst_history(start=now - timedelta(days=days), end=now, symbols=wanted) if wanted else []
    bars: dict[str, list[dict]] = {}
    for bar in (
        reader.daily_bars(wanted, sessions=dip_list.DEFAULT_FILTER["high_sessions"] + 5, end=now) if wanted else []
    ):
        bars.setdefault(str(bar["symbol"]).upper(), []).append(bar)
    earn = {
        r["symbol"]: r["date"]
        for r in sorted(
            reader.earnings_calendar(start=now, end=now + timedelta(days=60), now=now),
            key=lambda r: r["date"],
            reverse=True,
        )
        if r.get("kind") == "next"
    }
    return dip_list.build(
        sectors_block=sectors,
        policy_groups=groups.values(),
        candidates=cands,
        analyst_rows=rows,
        bars=bars,
        today=now.astimezone(ET).date(),
        earnings=earn,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="print the JSON payload instead of the text")
    ap.add_argument("--out", type=Path, help="also write the JSON payload to this path")
    ap.add_argument("--days", type=int, default=45, help="analyst history to read, calendar days (default 45)")
    ap.add_argument("--limit", type=int, default=30, help="rows shown in the text (default 30)")
    a = ap.parse_args(argv)
    from scripts.lib.market_risk.reader import PgReader

    reader = PgReader()
    try:
        payload = collect(datetime.now(timezone.utc), reader, load_policy(), state_root(), days=a.days)
    finally:
        reader.close()
    print(json.dumps(payload, indent=2, default=str) if a.json else dip_list.render(payload, limit=a.limit))
    if a.out:
        a.out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"wrote {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
