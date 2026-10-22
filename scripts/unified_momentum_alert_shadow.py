#!/usr/bin/env python3
"""Unified momentum alert -- Active Trader shadow replay (Gate 4, 2026-10-22). ADVISORY ONLY; never sends.

Reads one session day of the Active Trader alert journal (``data/active_trader/momentum_alerts.jsonl``,
contract active-trader-momentum-alert-v1, read-only) and, for every alert the operator was actually sent
(``sent: true``), builds the unified threaded message in SHADOW mode into the same ledger the social scalp
scanner's shadow hook writes (``data/runtime/unified_momentum_alerts.jsonl``). The result is the side-by-side
the operator reviews before switching ``unified_momentum_alert.mode`` to live: one thread per symbol/event/day,
scan and Active Trader states interleaved, with what each old alert said beside it.

Why a replay and not a live hook: the Active Trader sender (scripts/active_trader/momentum_alerts.py) is in the
broker execution file set (AGENTS.md §0 rule 2, config/agents_guard_hook_rules.json broker.execution_code_edit);
hooking it needs an operator execution-engineering grant. This reads its journal, a store, and nothing else.

Idempotent: an AT row already in the ledger (same origin_ref) is skipped, so re-running a day adds nothing.

Usage:
  python scripts/unified_momentum_alert_shadow.py --day 2026-10-22 --dry-run   # print, write nothing
  python scripts/unified_momentum_alert_shadow.py --day 2026-10-22             # append shadow rows

AUTHORITY: READ_ONLY_ADVISORY. No broker, no order, no Telegram, no model call. MBI_BEHAVIOR=0.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import unified_momentum_alert as U  # noqa: E402


def replay(day: str, *, journal: Path | None = None, ledger: "U.Ledger", include_unsent: bool = False,
           catalyst_lookup=None) -> dict:
    rows = U.at_rows(day, path=journal)
    picked = [r for r in rows if include_unsent or r.get("sent") is True]
    picked.sort(key=lambda r: float(r.get("ts_epoch") or 0))
    actions: Counter = Counter()
    for r in picked:
        ev = U.event_from_at_row(r)
        if ev is None:
            actions["UNMAPPED_KIND"] += 1
            continue
        U.enrich_catalyst(ev, catalyst_lookup)
        title = ((r.get("message") or {}).get("title") or "").splitlines()
        res = U.emit(ev, mode="shadow", ledger=ledger,
                     legacy_alert=("active_trader: " + title[-1].strip()) if title else "active_trader")
        actions[res.get("action")] += 1
    return {"schema": "UnifiedMomentumAlertShadowReplay@v1", "day": day, "journal_rows": len(rows),
            "replayed": len(picked), "actions": dict(sorted(actions.items())),
            "threads": len({r.get("thread_key") for r in ledger.rows(day) if r.get("mode") == "shadow"})}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--day", default=datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d"))
    ap.add_argument("--journal", type=Path, default=None, help="AT journal (default: the data-broker store root)")
    ap.add_argument("--ledger", type=Path, default=None, help="unified ledger (default: state root)")
    ap.add_argument("--include-unsent", action="store_true", help="also replay vetoed / unsent decisions")
    ap.add_argument("--dry-run", action="store_true", help="build in memory, print, write nothing")
    ap.add_argument("--show", type=int, default=0, help="print the first N built messages")
    a = ap.parse_args(argv)
    path = a.ledger or U.ledger_path()
    ledger = U.MemoryLedger(seed=path if Path(path).exists() else None) if a.dry_run else U.Ledger(path)
    out = replay(a.day, journal=a.journal, ledger=ledger, include_unsent=a.include_unsent)
    out["dry_run"] = bool(a.dry_run)
    out["ledger"] = str(path)
    print(json.dumps(out, indent=1, sort_keys=True))
    if a.show:
        built = ledger.appended if a.dry_run else [r for r in ledger.rows(a.day) if r.get("mode") == "shadow"]
        for r in built[: a.show]:
            print("\n---", r.get("thread_key"), r.get("state"), "reply_to:", r.get("would_reply_to"))
            print(r.get("text"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
