#!/usr/bin/env python3
"""Premarket cadence comparison -- old 5-minute throttled heads-up vs new 1-minute threaded lifecycle, per symbol.

Operator 2026-10-23: switch active_trader_premarket.cadence_mode to live only after seeing, for a session, when the
old path alerted and when the new one would have. This reads three stores (read-only) and prints, per symbol:

- old: the first PREMARKET_WATCH ALERT in the Active Trader journal (data/active_trader/momentum_alerts.jsonl), how
  many old alerts there were and how many were sent;
- new: the 1-minute path's threaded messages (unified ledger data/runtime/unified_momentum_alerts.jsonl, origin
  ``active_trader_premarket``): first message time and state, every state change, capped / deduped counts;
- latency gained = old first alert minus new first message, in minutes (positive = the new path was earlier);
- focus: when the name entered / left the focus list and why (data/runtime/scalp_focus_events.jsonl).

  python3 scripts/premarket_cadence_compare.py --day 2026-10-23            # text table
  python3 scripts/premarket_cadence_compare.py --day 2026-10-23 --json     # machine-readable

AUTHORITY: READ_ONLY_ADVISORY. No broker, no send, no model call, no write. MBI_BEHAVIOR=0.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

ET = ZoneInfo("America/New_York")
SCHEMA = "PremarketCadenceComparison@v1"
ORIGIN_1M = "active_trader_premarket"
NEW_EMITTED = ("SHADOW_LOGGED", "SENT", "ACCEPTED_NOT_DELIVERED")
# check_dark_contracts: the report schema has no importer by design -- the operator runs this CLI before flipping
# cadence_mode to live.
NO_CONSUMER_REASON = "operator CLI: old vs new premarket alert timing for the cadence_mode live decision"


def _hm(ts: Optional[float]) -> Optional[str]:
    return None if ts is None else datetime.fromtimestamp(float(ts), ET).strftime("%H:%M")


def _jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def compare(day: str, *, journal: Path, ledger: Path, focus_events: Path) -> dict:
    old: dict[str, dict] = {}
    for r in _jsonl(journal):
        c = r.get("candidate") or {}
        if r.get("kind") != "PREMARKET_WATCH" or c.get("session_date") != day or r.get("verdict") != "ALERT":
            continue
        sym = str(c.get("symbol") or "").upper()
        o = old.setdefault(sym, {"first": None, "alerts": 0, "sent": 0, "times": []})
        ts = float(r.get("ts_epoch") or 0)
        o["alerts"] += 1
        o["sent"] += 1 if r.get("sent") else 0
        o["times"].append(_hm(ts))
        o["first"] = ts if o["first"] is None else min(o["first"], ts)
    new: dict[str, dict] = {}
    for r in _jsonl(ledger):
        if r.get("day") != day or r.get("origin") != ORIGIN_1M:
            continue
        sym = str(r.get("symbol") or "").upper()
        n = new.setdefault(sym, {"first": None, "first_state": None, "messages": 0, "capped": 0, "deduped": 0,
                                 "timeline": [], "mode": r.get("mode")})
        act = r.get("action")
        ts = float(r.get("ts_epoch") or 0)
        if act in NEW_EMITTED:
            n["messages"] += 1
            n["timeline"].append(f"{_hm(ts)} {r.get('state')}")
            if n["first"] is None or ts < n["first"]:
                n["first"], n["first_state"] = ts, r.get("state")
        elif act == "CAPPED_PER_HOUR":
            n["capped"] += 1
        elif act == "DEDUPED_SAME_STATE":
            n["deduped"] += 1
    focus: dict[str, list[str]] = {}
    for e in _jsonl(focus_events):
        if e.get("day") == day:
            focus.setdefault(str(e.get("symbol") or "").upper(), []).append(
                f"{_hm(e.get('ts_epoch'))} {e.get('reason')}")
    rows = []
    for sym in sorted(set(old) | set(new)):
        o, n = old.get(sym) or {}, new.get(sym) or {}
        gained = None
        if o.get("first") is not None and n.get("first") is not None:
            gained = round((o["first"] - n["first"]) / 60.0, 1)
        rows.append({"symbol": sym, "old_first": _hm(o.get("first")), "old_alerts": o.get("alerts", 0),
                     "old_sent": o.get("sent", 0), "new_first": _hm(n.get("first")),
                     "new_first_state": n.get("first_state"), "new_messages": n.get("messages", 0),
                     "new_capped": n.get("capped", 0), "new_deduped": n.get("deduped", 0),
                     "latency_gained_min": gained, "new_timeline": n.get("timeline", []),
                     "old_times": o.get("times", []), "focus": focus.get(sym, [])})
    both = [r["latency_gained_min"] for r in rows if r["latency_gained_min"] is not None]
    return {"schema": SCHEMA, "day": day, "symbols": len(rows),
            "only_old": [r["symbol"] for r in rows if r["old_first"] and not r["new_first"]],
            "only_new": [r["symbol"] for r in rows if r["new_first"] and not r["old_first"]],
            "median_latency_gained_min": sorted(both)[len(both) // 2] if both else None,
            "old_messages": sum(r["old_alerts"] for r in rows), "new_messages": sum(r["new_messages"] for r in rows),
            "rows": rows, "authority": "READ_ONLY_ADVISORY"}


def render(rep: dict) -> str:
    lines = [f"Premarket cadence comparison {rep['day']} -- old 5-min throttled vs new 1-min threaded",
             f"{'symbol':7}{'old first':>10}{'#old':>6}{'new first':>11}{'state':>13}{'#new':>6}{'gained':>9}"]
    for r in rep["rows"]:
        g = "—" if r["latency_gained_min"] is None else f"{r['latency_gained_min']:+.1f}m"
        lines.append(f"{r['symbol']:7}{r['old_first'] or '—':>10}{r['old_alerts']:>6}{r['new_first'] or '—':>11}"
                     f"{r['new_first_state'] or '—':>13}{r['new_messages']:>6}{g:>9}")
        if r["new_timeline"]:
            lines.append("        new: " + " → ".join(r["new_timeline"]))
        if r["focus"]:
            lines.append("        focus: " + " | ".join(r["focus"][:4]))
    lines.append(f"median latency gained: {rep['median_latency_gained_min']} min · old messages "
                 f"{rep['old_messages']} · new messages {rep['new_messages']} · only old {rep['only_old']} · "
                 f"only new {rep['only_new']}")
    return "\n".join(lines)


def _defaults() -> tuple[Path, Path, Path]:
    from lib import scalp_focus as sf
    from lib import unified_momentum_alert as um

    return um.at_journal_path(), um.ledger_path(), sf.events_path()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--day", default=datetime.now(ET).strftime("%Y-%m-%d"))
    ap.add_argument("--journal", type=Path)
    ap.add_argument("--ledger", type=Path)
    ap.add_argument("--focus-events", type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not (a.journal and a.ledger and a.focus_events):
        j, ledger, fe = _defaults()
        a.journal, a.ledger, a.focus_events = a.journal or j, a.ledger or ledger, a.focus_events or fe
    rep = compare(a.day, journal=a.journal, ledger=a.ledger, focus_events=a.focus_events)
    print(json.dumps(rep, indent=1) if a.json else render(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
