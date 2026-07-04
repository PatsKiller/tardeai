#!/usr/bin/env python3
"""holdings_change_trigger.py — re-queue CIO synthesis when a symbol's held-state changes.

Why: the CIO synthesis narrative embeds a PORTFOLIO POSITION ground-truth block read at run
time. When a position appears/disappears between synthesis runs (e.g. SMCI bought in Fidelity,
first visible in the 2026-07-03 12:33 SnapTrade sync while the narrative still said "zero
position" from the night before), the card shows a stale contradiction until the next scheduled
pass happens to touch the symbol. This trigger closes the loop at the source: after every
holdings.json write, diff per-symbol share totals against the last-seen state and enqueue a
full_chain re-synthesis job for watchlist symbols whose held-state materially changed.

Called from schwab_position_sync.protected_holdings_write (the single gate both the Schwab
position sync and the SnapTrade merge write through), always non-fatally. Also runnable as a CLI:

    python3 scripts/holdings_change_trigger.py            # dry run — print the diff
    python3 scripts/holdings_change_trigger.py --apply    # enqueue jobs + update state
    python3 scripts/holdings_change_trigger.py --baseline # write state only, enqueue nothing

Advisory-only: queues research jobs for the always-on watchlist workers. Never touches orders.
First run (no state file) is an automatic baseline — no job storm.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Imports resolve next to this file; the data root is env-overridable (TRADE_AI_ROOT) for tests.
sys.path.insert(0, str(Path(__file__).resolve().parent))
PROJECT_ROOT = Path(os.environ.get("TRADE_AI_ROOT") or Path(__file__).resolve().parents[1])

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
HOLDINGS_PATH = STATE_DIR / "holdings.json"
TRIGGER_STATE_PATH = STATE_DIR / "holdings_symbol_state.json"

# Material change = held-state flip, or share count moving by at least this fraction.
SHARE_DELTA_PCT = 0.10


def _current_shares() -> dict[str, float]:
    """Per-symbol total shares from canonical holdings.json (non-cash positions only)."""
    if not HOLDINGS_PATH.exists():
        return {}
    data = json.loads(HOLDINGS_PATH.read_text())
    totals: dict[str, float] = {}
    for h in data.get("holdings", []):
        if h.get("is_cash"):
            continue
        sym = str(h.get("symbol") or "").upper().strip()
        shares = float(h.get("shares") or 0)
        if not sym or shares <= 0:
            continue
        totals[sym] = totals.get(sym, 0.0) + shares
    return totals


def _load_state() -> dict | None:
    if not TRIGGER_STATE_PATH.exists():
        return None
    try:
        return json.loads(TRIGGER_STATE_PATH.read_text())
    except Exception:
        return None


def _save_state(symbols: dict[str, float]) -> None:
    TRIGGER_STATE_PATH.write_text(json.dumps({
        "symbols": symbols,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))


def _diff(prev: dict[str, float], cur: dict[str, float]) -> list[dict]:
    """Symbols whose held-state or share count changed materially."""
    changes = []
    for sym in sorted(set(prev) | set(cur)):
        old = float(prev.get(sym, 0.0))
        new = float(cur.get(sym, 0.0))
        if old == new:
            continue
        flipped = (old == 0) != (new == 0)
        rel = abs(new - old) / max(old, new) if max(old, new) > 0 else 0
        if flipped or rel >= SHARE_DELTA_PCT:
            changes.append({"symbol": sym, "old_shares": old, "new_shares": new,
                            "kind": "opened" if old == 0 else "closed" if new == 0 else "resized"})
    return changes


def _in_watchlist(symbols: list[str]) -> set[str]:
    """Filter to symbols the watchlist pipeline actually tracks — skips SPAXX-style noise."""
    if not symbols:
        return set()
    from db_adapter import _execute
    rows = _execute(
        "SELECT symbol FROM watchlist_symbol_master WHERE symbol = ANY(%s)",
        (symbols,), fetch="all") or []
    return {r["symbol"] if isinstance(r, dict) else r[0] for r in rows}


def _enqueue(sym: str, note: str) -> str:
    """Queue a full_chain re-synthesis job; skip if one is already queued/running."""
    from db_adapter import _execute
    dup = _execute("""SELECT 1 FROM watchlist_agent_jobs WHERE symbol=%s AND requested_agent='full_chain'
                      AND status IN ('queued','running') LIMIT 1""", (sym,), fetch="one")
    if dup:
        return "already queued"
    job_id = f"holdchg-{sym}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    _execute("""INSERT INTO watchlist_agent_jobs
                (id, symbol, requested_agent, request_type, note, priority, status, submitted_from, payload, created_at)
                VALUES (%s,%s,'full_chain','holdings_change',%s,1,'queued','holdings_change_trigger','{}',NOW())
                ON CONFLICT (id) DO NOTHING""", (job_id, sym, note), fetch=None)
    # Re-open the synthesis gate: run_synthesis skips symbols whose maturity says 'completed',
    # so re-run agents never re-synthesized (SMCI 2026-07-03 — agents finished, final row stale).
    _execute("""UPDATE watchlist_analysis_maturity SET final_synthesis_status='pending', updated_at=now()
                WHERE symbol=%s AND final_synthesis_status='completed'""", (sym,), fetch=None)
    return "enqueued"


def check_and_enqueue(apply: bool = False, baseline: bool = False) -> dict:
    """Diff holdings vs last-seen state; enqueue re-synthesis for changed watchlist symbols.

    Returns {changed, enqueued, skipped, summary}. Never raises for callers that print-and-continue.
    """
    cur = _current_shares()
    state = _load_state()

    if state is None or baseline:
        if apply or baseline:
            _save_state(cur)
        return {"changed": [], "enqueued": [], "skipped": [],
                "summary": f"baseline written ({len(cur)} symbols)" if (apply or baseline)
                else f"baseline pending ({len(cur)} symbols) — run with --apply"}

    prev = {k.upper(): float(v) for k, v in (state.get("symbols") or {}).items()}
    changes = _diff(prev, cur)
    if not changes:
        if apply:
            _save_state(cur)
        return {"changed": [], "enqueued": [], "skipped": [], "summary": "no held-state changes"}

    tracked = _in_watchlist([c["symbol"] for c in changes])
    enqueued, skipped = [], []
    for c in changes:
        sym = c["symbol"]
        note = (f"held-state {c['kind']}: {c['old_shares']:.1f} → {c['new_shares']:.1f} sh — "
                f"re-synthesize with live PORTFOLIO POSITION block")
        if sym not in tracked:
            skipped.append(f"{sym} (not in watchlist master)")
            continue
        if not apply:
            enqueued.append(f"{sym} (dry-run)")
            continue
        try:
            outcome = _enqueue(sym, note)
            (enqueued if outcome == "enqueued" else skipped).append(f"{sym} ({outcome})")
        except Exception as e:  # DB hiccup — report, keep the rest going
            skipped.append(f"{sym} (error: {str(e)[:60]})")
    if apply:
        _save_state(cur)
        # Cross-surface refresh (2026-07-03 tier-2): a position change also stales the per-holding
        # LLM health assessment and the protective-stop advisory. Health: spawn a detached refresh
        # (cap 3 — LLM work, never block the sync). Stops: alert-only — stop machinery is
        # order-adjacent and stays untouched; the operator/stop-advisory cron acts on the alert.
        try:
            import subprocess
            py = str(PROJECT_ROOT / ".venv" / "bin" / "python")
            for c in changes[:3]:
                if c["new_shares"] > 0:
                    subprocess.Popen([py, str(Path(__file__).resolve().parent / "holdings_llm_refresh.py"),
                                      "--run", "--symbol", c["symbol"]],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
        except Exception:
            pass
        try:
            from alert_event_writer import save_alert_event
            for c in changes:
                save_alert_event(alert_type="system_health", severity="info",
                                 source_script="holdings_change_trigger.py",
                                 raw_text=(f"[holdings-change] {c['symbol']} {c['kind']} "
                                           f"{c['old_shares']:.0f}→{c['new_shares']:.0f} sh — "
                                           f"protective-stop band recheck recommended"),
                                 parsed_payload={"kind": "stop_band_recheck", "symbol": c["symbol"],
                                                 "change": c["kind"]})
        except Exception:
            pass

    summary = (f"{len(changes)} change(s): "
               + "; ".join(f"{c['symbol']} {c['kind']} {c['old_shares']:.0f}→{c['new_shares']:.0f}" for c in changes)
               + (f" | enqueued: {', '.join(enqueued)}" if enqueued else "")
               + (f" | skipped: {', '.join(skipped)}" if skipped else ""))
    return {"changed": changes, "enqueued": enqueued, "skipped": skipped, "summary": summary}


def main() -> int:
    ap = argparse.ArgumentParser(description="Enqueue CIO re-synthesis on held-state changes.")
    ap.add_argument("--apply", action="store_true", help="enqueue jobs + update state (default: dry-run diff)")
    ap.add_argument("--baseline", action="store_true", help="write current state only; enqueue nothing")
    args = ap.parse_args()
    res = check_and_enqueue(apply=args.apply, baseline=args.baseline)
    print(json.dumps(res, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
