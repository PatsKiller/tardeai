#!/usr/bin/env python3
"""Sunday-evening "plan for the next session" brief (PKG-SELLOFF-INTEL-20261106 A).

One advisory message that puts the weekend's facts in one place before the next open:

  1. the market-risk tier line (what the engine computed, never a tier it did not);
  2. the deep brief: what usually happens next after days like this, with the matched base rates and the
     analog dates (``cio_context.deep_brief_on_demand`` — stored brief, else built from the read-only DB);
  3. the calendar (almanac) facts that apply to the coming session, each with its ``reproduced`` flag;
  4. the re-entry watch cards: status and the conditions met, "not evaluated" when the engine sent none;
  5. the stressed and weak groups with their 5-day and drawdown numbers (members: package E);
  6. the top five rows of the opportunity board by conviction.

Every section that cannot be read says so by name ("unavailable: <reason>"); nothing is flattened to zero.

MBI_BEHAVIOR = 0. The brief names no order, size, stop or weight. The finished text goes through the same
sizing/stop guard the re-entry cards use, and a guard hit refuses the send (exit 2).

Read-only: the market-risk snapshot file, the opportunity projection file, the calendar-fact sources and the
deep-brief reader (read-only DB). It makes no HTTP request and no broker call. ``--dry-run`` prints the brief
and sends nothing; without it the brief goes through the Telegram chokepoint (``telegram_alert.send_telegram``,
priority P2), the same sender the morning brief uses. Scheduling is an n8n lane (house rule), not cron.

Usage:
    python scripts/monday_plan_brief.py --dry-run
    python scripts/monday_plan_brief.py --dry-run --data-root /path/to/checkout --state-root /path/to/state
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = timezone(timedelta(hours=-5))

DEFAULT_STATE_ROOT = Path(os.path.expanduser("~/trade-ai-releases/persistent-state"))
FOOTER = "Advisory only: this brief names no order, size, stop or weight."
#: Calendar facts worth a line in a November-April brief; the rest are listed only when their month applies.
_SEASONAL_BY_MONTH: dict[int, tuple[str, ...]] = {
    1: ("january_barometer", "best_six_months", "halloween_nov_apr", "turn_of_month"),
    9: ("september_weakness", "worst_six_months_may_oct", "turn_of_month"),
    11: ("best_six_months", "halloween_nov_apr", "turn_of_month", "pre_holiday"),
    12: ("santa_claus_rally", "best_six_months", "halloween_nov_apr", "turn_of_month", "pre_holiday"),
}
_DISCLAIMER = re.compile(r"^advisory\b.*\bno order, size or stop( level)? is implied", re.I)
#: Symbols brief_guard.clean would drop silently ("VIX 27.0 >= 25.0" would read "VIX 27.0  25.0").
_FOLD = str.maketrans({"\u2192": "->", "\u2265": ">=", "\u2264": "<="})
#: Sanity bounds for a GROUP or ETF move. A sector/industry ETF moving more than this is far likelier a bad bar (an
#: unadjusted split: SOXX "-79% off its 52w high", Semis "-42.8% in 5 days" on 2026-11-06) than a real move, so
#: the brief says "data check failed" instead of printing the number. March 2020 stays inside every bound
#: (semis ETF worst 5d about -24%, worst 20d drawdown about -40%).
GROUP_MAX_ABS_5D_PCT = 30.0
GROUP_MIN_DD20_PCT = -45.0
ETF_MIN_OFF_52W_HIGH_PCT = -60.0
_OFF_52W = re.compile(r"(\b[A-Z][A-Z0-9.]{0,9}) (-\d+(?:\.\d+)?)% off 52w high")
_STOP_DISTANCE = re.compile(r"\s*\(stop [^)]*\)", re.I)
_CYCLE_FACTS = ("midterm_year_pattern", "post_election_year", "presidential_4yr_cycle", "midterm_bottom_picker")


# ── helpers ────────────────────────────────────────────────────────────────


def _unavailable(what: str, exc: Any) -> list[str]:
    return [f"{what}: unavailable ({str(exc)[:160]})"]


def _pct(v: Any) -> str:
    return f"{float(v):+.1f}%" if isinstance(v, (int, float)) else "n/a"


def next_session(today: date) -> date:
    """The next trading session strictly after ``today`` (holiday-aware through the market calendar)."""
    from scripts.lib.market_risk import sessions

    return sessions._next_trading_day(today)  # noqa: SLF001 — the engine's own holiday calendar


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# ── sections ───────────────────────────────────────────────────────────────


def section_tier(data_root: Path) -> list[str]:
    try:
        from scripts.lib.cio_market_context_state import load_market_risk_projection
        from scripts.lib.market_risk.cio_context import tier_line

        return [tier_line(load_market_risk_projection(project_root=data_root))]
    except Exception as exc:  # noqa: BLE001 -- a failed section is reported by name, never crashes the brief
        return _unavailable("Market risk", exc)


def section_deep_brief(loader: Optional[Callable[[], dict[str, Any]]] = None) -> list[str]:
    try:
        if loader is None:
            from scripts.lib.market_risk.cio_context import deep_brief_on_demand as loader  # type: ignore[no-redef] -- the default loader rebinds the optional parameter
        db = loader() or {}
    except Exception as exc:  # noqa: BLE001 -- a failed section is reported by name, never crashes the brief
        return _unavailable("Deep brief", exc)
    if db.get("source") == "unavailable" or not (db.get("text") or db.get("facts")):
        return [f"Deep brief: unavailable ({db.get('reason') or 'no brief and none could be built'})"]
    out: list[str] = []
    nxt = [f for f in (db.get("facts") or []) if isinstance(f, dict) and f.get("section") == "next"]
    if nxt:
        out.append("What usually happens next (matched past days, 2016-2025; 2026 held out):")
        out += [f"- {f.get('text')}" for f in nxt if f.get("text")]
    else:
        out.append("What usually happens next: no matched base-rate facts in this brief.")
    text = _deep_brief_body(str(db.get("text") or ""))
    if text:
        out.append("")
        out.append(f"Deep brief ({db.get('source')}):")
        out.append(text)
    return out


def _deep_brief_body(text: str) -> str:
    """The deep brief text, minus what this brief already carries or must not carry.

    - its "What usually happens next" block (shown above, once);
    - its closing advisory disclaimer (one footer covers every section, and its words "stop level" are exactly
      what the stop-instruction guard refuses);
    - any "(stop N% away)" distance on an exposure line: the brief names no stop level (MBI_BEHAVIOR = 0).
    """
    out: list[str] = []
    skipping = False
    for ln in text.translate(_FOLD).strip().splitlines():
        s = ln.strip()
        if s.lower() == "what usually happens next":
            skipping = True
            continue
        if skipping:
            if s.startswith("- "):
                continue
            skipping = False
        if _DISCLAIMER.match(s):
            continue
        out.append(_OFF_52W.sub(_check_52w, _STOP_DISTANCE.sub("", ln)))
    return "\n".join(out).strip()


def _check_52w(mt: "re.Match[str]") -> str:
    if float(mt.group(2)) < ETF_MIN_OFF_52W_HIGH_PCT:
        return f"{mt.group(1)} distance from 52w high: data check failed"
    return mt.group(0)


def _group_sane(g: dict[str, Any]) -> bool:
    for key in ("r5", "rs5"):
        v = g.get(key)
        if isinstance(v, (int, float)) and abs(v) > GROUP_MAX_ABS_5D_PCT:
            return False
    dd = g.get("dd20")
    return not (isinstance(dd, (int, float)) and dd < GROUP_MIN_DD20_PCT)


def section_almanac(session: date, rows: Optional[list[dict[str, Any]]] = None) -> list[str]:
    try:
        if rows is None:
            from scripts.lib.cio_calendar_facts import build_calendar_facts

            rows = build_calendar_facts()
    except Exception as exc:  # noqa: BLE001 -- a failed section is reported by name, never crashes the brief
        return _unavailable("Calendar facts", exc)
    wanted = _SEASONAL_BY_MONTH.get(session.month, ("turn_of_month",)) + _CYCLE_FACTS
    by_id = {str(r.get("fact_id")): r for r in rows or [] if isinstance(r, dict)}
    out = [f"Calendar facts for {session:%B} (reproduced = re-measured on 1926+ data here; not = a claim only):"]
    for fid in wanted:
        r = by_id.get(fid)
        if not r:
            continue
        rep = "reproduced" if r.get("reproduced") else "NOT reproduced"
        grade = r.get("evidence_grade") or "ungraded"
        note = str(r.get("notes") or "").strip().split("\n")[0][:180]
        out.append(f"- {r.get('title') or fid}: {rep}, evidence {grade}" + (f" — {note}" if note else ""))
    if len(out) == 1:
        out.append("- none of the tracked calendar facts applies")
    return out


def _reentry_line(sym: str, rec: dict[str, Any]) -> list[str]:
    conds = [c for c in (rec.get("conditions") or []) if isinstance(c, dict)]
    met = sum(1 for c in conds if c.get("met") is True)
    if not conds:
        state = "conditions not evaluated"
    elif met == len(conds):
        state = f"all {len(conds)} conditions met"
    else:
        state = f"{met} of {len(conds)} conditions met"
    # Counts only. The engine's stage label (reentry_stages.evaluate) is a different rule: "Confirmed" when any one
    # stage-2 price check passes, regardless of these five conditions, so printing both reads as a contradiction
    # ("Confirmed" at 2 of 5). The label returns once the two agree (selloff package B).
    lines = [f"- {sym}: {state} · as of {rec.get('as_of') or 'unknown'}"]
    lines += [f"    {'met' if c.get('met') is True else 'not met'}: {c.get('text')}" for c in conds]
    br = rec.get("base_rate") or {}
    if br.get("n") and isinstance(br.get("rate"), (int, float)):
        lines.append(
            f"    base rate: re-entering on trend repair beat waiting {br.get('horizon_sessions')} sessions in "
            f"{br.get('beat_waiting')} of {br['n']} past setups ({round(100 * br['rate'])}%)"
        )
    return lines


def section_reentry(snapshot: Optional[dict[str, Any]]) -> list[str]:
    if snapshot is None:
        return ["Re-entry watch: unavailable (no market-risk snapshot)"]
    rw = snapshot.get("reentry_watch")
    if not isinstance(rw, dict):
        return ["Re-entry watch: not evaluated (the snapshot carries no re-entry watch)"]
    syms = sorted(k for k, v in rw.items() if not str(k).startswith("_") and isinstance(v, dict))
    if not syms:
        return ["Re-entry watch: no names on the watch"]
    out = ["Re-entry watch (status only):"]
    for s in syms:
        out += _reentry_line(s, rw[s])
    return out


def section_stressed(snapshot: Optional[dict[str, Any]]) -> list[str]:
    if snapshot is None:
        return ["Stressed groups: unavailable (no market-risk snapshot)"]
    sec = snapshot.get("sectors")
    if not isinstance(sec, dict):
        return ["Stressed groups: not evaluated (the snapshot carries no sector read)"]
    groups = [g for g in (sec.get("groups") or []) if isinstance(g, dict) and g.get("state") in ("STRESS", "WEAK")]
    bench = sec.get("benchmark") or {}
    out = [f"Stressed and weak groups (vs {bench.get('symbol') or 'SPY'} {_pct(bench.get('r5'))} 5d), biggest 20d drawdown first:"]
    if not groups:
        out.append("- none flagged")
    failed = [g for g in groups if not _group_sane(g)]
    sane = [g for g in groups if _group_sane(g)]
    for g in sorted(sane, key=lambda g: g.get("dd20") if isinstance(g.get("dd20"), (int, float)) else 0):
        syms = ",".join(g.get("symbols") or [])
        out.append(
            f"- {g.get('label')} ({syms}) {str(g.get('state')).lower()}: 5d {_pct(g.get('r5'))}, "
            f"vs benchmark {_pct(g.get('rs5'))}, off 20d high {_pct(g.get('dd20'))}"
        )
    for g in failed:
        out.append(
            f"- {g.get('label')} ({','.join(g.get('symbols') or [])}) {str(g.get('state')).lower()}: data check failed "
            "(a move beyond the sanity bound, likely a bad price bar; numbers withheld until the source is verified)"
        )
    out.append("  Member names by drawdown: not in this brief yet (selloff package E).")
    return out


def section_opportunities(data_root: Path, items: Optional[list[dict[str, Any]]] = None, n: int = 5) -> list[str]:
    try:
        from scripts.lib.data_broker import opportunity as op

        if items is None:
            from scripts.lib.cio_opportunity_store import CIOOpportunityStore

            proj = CIOOpportunityStore(
                event_path=data_root / "data" / "cio" / "cio_opportunity_assessments.jsonl",
                projection_path=data_root / "data" / "cio" / "cio_opportunity_projection.json",
            ).read_projection()
            items = list((proj.get("items") or {}).values())
        ranked = op.sort_items([a for a in items if isinstance(a, dict)], "conviction")[:n]
    except Exception as exc:  # noqa: BLE001 -- a failed section is reported by name, never crashes the brief
        return _unavailable("Opportunities", exc)
    if not ranked:
        return ["Top opportunities: unavailable (the opportunity board is empty or unreadable)"]
    out = [f"Top {len(ranked)} on the opportunity board by conviction:"]
    for a in ranked:
        up = a.get("upside_pct")
        out.append(
            f"- {a.get('symbol')} ({a.get('sector') or 'sector n/a'}): conviction {a.get('conviction')}, "
            f"stance {a.get('stance') or 'n/a'}, upside {_pct(up) if isinstance(up, (int, float)) else 'n/a'}"
        )
    return out


# ── assembly ───────────────────────────────────────────────────────────────


def guard(text: str) -> str:
    """Fold typography and refuse sizing/stop/order wording (the re-entry card guard). Raises ValueError."""
    from scripts.lib.market_risk import brief_guard
    from scripts.lib.market_risk.reentry_watch import _guard

    cleaned, _bad = brief_guard.clean(text)
    _guard(cleaned)
    return cleaned


def build(
    *,
    now: datetime,
    data_root: Path,
    state_root: Path,
    deep_brief_loader: Optional[Callable[[], dict[str, Any]]] = None,
    calendar_rows: Optional[list[dict[str, Any]]] = None,
    opportunity_items: Optional[list[dict[str, Any]]] = None,
) -> str:
    today = now.astimezone(ET).date()
    try:
        session = next_session(today)
        session_line = f"Plan for the next session: {session:%A %Y-%m-%d}"
    except Exception as exc:  # noqa: BLE001 -- an unreadable market calendar is printed as unknown, never crashes the brief
        session = today + timedelta(days=1)
        session_line = f"Plan for the next session: unknown (market calendar unavailable: {str(exc)[:80]})"
    try:
        snapshot: Optional[dict[str, Any]] = _read_json(state_root / "data" / "runtime" / "market_risk" / "latest.json")
    except Exception:  # noqa: BLE001 — every section that needs it says so
        snapshot = None
    parts = [
        [f"NEXT-SESSION PLAN BRIEF · written {now.astimezone(ET):%a %Y-%m-%d %H:%M} ET", session_line],
        section_tier(data_root),
        section_deep_brief(deep_brief_loader),
        section_almanac(session, calendar_rows),
        section_reentry(snapshot),
        section_stressed(snapshot),
        section_opportunities(data_root, opportunity_items),
        [FOOTER],
    ]
    return guard("\n\n".join("\n".join(p) for p in parts))


def send(text: str) -> bool:
    from telegram_alert import send_telegram  # the operator-alert chokepoint (same as send_morning_brief)

    return bool(send_telegram(text, priority="P2", producer="monday_plan_brief"))


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print the brief; send nothing")
    ap.add_argument("--data-root", type=Path, default=Path(os.environ.get("TRADEAI_DATA_ROOT") or PROJECT_ROOT),
                    help="checkout whose data/ holds the opportunity projection (default: this checkout)")
    ap.add_argument("--state-root", type=Path,
                    default=Path(os.environ.get("TRADEAI_STATE_ROOT") or DEFAULT_STATE_ROOT),
                    help="persistent-state root holding data/runtime/market_risk/latest.json")
    args = ap.parse_args(argv)
    try:
        text = build(now=datetime.now(timezone.utc), data_root=args.data_root, state_root=args.state_root)
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(text)
        return 0
    ok = send(text)
    print(json.dumps({"producer": "monday_plan_brief", "accepted": ok, "chars": len(text)}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
