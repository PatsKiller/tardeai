#!/usr/bin/env python3
"""register_analyst_sources.py — promote the public analyst-aggregator domains to first-class,
active `analyst` sources in the maturity ladder (idempotent).

Hermes already surfaces analyst commentary opportunistically (MarketBeat, GuruFocus, simplywall.st are
top trade-converting sources). This registers the high-value public analyst aggregators that were only
incidental web hits — TipRanks, Zacks, Morningstar, WallStreetZen, StockAnalysis — as recognized,
credibility-seeded `analyst` sources so they're weighted and yield-tracked by the source-maturity ladder
(daily 05:45) instead of decaying as anonymous low-cred discoveries.

Anchored on Yahoo consensus (authoritative); these add public analyst *commentary/ratings* breadth.
Idempotent: upserts by source_url. Re-runnable from cron to keep them pinned active.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# (name, url, specialty, seed_credibility) — seeded high since these are known-good analyst aggregators
ANALYST_SOURCES = [
    ("TipRanks",       "tipranks.com",      "analyst ratings + price targets + smart score", 150),
    ("Zacks",          "zacks.com",         "analyst rank + estimate revisions",             150),
    ("Morningstar",    "morningstar.com",   "analyst fair-value + moat ratings",             150),
    ("WallStreetZen",  "wallstreetzen.com", "analyst rating aggregation",                    120),
    ("StockAnalysis",  "stockanalysis.com", "analyst targets + fundamentals",                120),
]


def register(apply: bool) -> dict:
    from db_adapter import _execute
    added = updated = 0
    for name, url, specialty, cred in ANALYST_SOURCES:
        existing = _execute("SELECT id, active FROM research_sources WHERE source_url=%s OR source_name=%s",
                            (url, name), fetch="one")
        if not apply:
            print(f"  would {'update' if existing else 'add'}: {name:14s} {url:20s} cred={cred} [{specialty}]")
            continue
        if existing:
            _execute("""UPDATE research_sources SET source_type='analyst', active=true,
                        credibility_score=GREATEST(COALESCE(credibility_score,0), %s),
                        specialty=%s, notes='analyst aggregator (register_analyst_sources)'
                        WHERE id=%s""", (cred, [specialty], dict(existing)["id"]), fetch=None)
            updated += 1
        else:
            _execute("""INSERT INTO research_sources
                        (source_type, source_name, source_url, credibility_score, specialty, active, notes, created_at)
                        VALUES ('analyst', %s, %s, %s, %s, true, 'analyst aggregator (register_analyst_sources)', NOW())""",
                     (name, url, cred, [specialty]), fetch=None)
            added += 1
        print(f"  {'updated' if existing else 'added'}: {name} ({url})")
    return {"added": added, "updated": updated}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write to research_sources (default dry-run)")
    a = ap.parse_args()
    print(f"[analyst-sources] registering {len(ANALYST_SOURCES)} analyst aggregators (apply={a.apply})")
    res = register(a.apply)
    print(f"[analyst-sources] {'APPLIED' if a.apply else 'DRY'} — {res}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
