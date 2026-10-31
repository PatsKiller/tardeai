"""Index options-flow alert — the first Market Risk Engine alert path (DSN-20261031-market-risk-engine P0-T6).

Single-source rule (AGENTS.md §4, operator 2026-10-05): an alert producer never fetches its own market data.
This module reads ONLY `option_chain_snapshots` rows — the trailing history through the cursor it is given,
and today's values as the rows the snapshot writer has just committed to that same table. It holds no
provider client. The writer (scripts/options_chain_snapshot.py) calls `emit` after its INSERT.

`emit` evaluates the policy thresholds (lib.market_risk.options_flow) and sends at most ONE intent through
telegram_alert.send_telegram. A dry run evaluates and prints the card; it sends nothing. Errors are returned
on the result, never swallowed. No sizing, ordering or stop value exists here (MBI_BEHAVIOR = 0).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone


def history(cur, symbol: str, lookback: int) -> list:
    """Trailing sessions for one index symbol from option_chain_snapshots (store read, no provider)."""
    cur.execute(
        """SELECT as_of, pc_oi_ratio, pc_vol_ratio, underlying_price FROM option_chain_snapshots
                   WHERE symbol=%s AND as_of < CURRENT_DATE ORDER BY as_of DESC LIMIT %s""",
        (symbol, lookback),
    )
    return [
        {"as_of": r[0], "pc_oi_ratio": r[1], "pc_vol_ratio": r[2], "underlying_price": r[3]} for r in cur.fetchall()
    ]


def emit(cur, rows: dict, *, dry_run: bool, now=None) -> dict:
    """Evaluate index put/call flow against policy and send ONE intent when it crosses a threshold.

    `rows` are today's option_chain_snapshots rows (symbol -> row dict) as committed by the writer.
    Returns what the dashboard needs: findings, the priority chosen, whether it was accepted, any error.
    """
    from lib.market_risk import options_flow as of
    from lib.market_risk.policy import load_policy

    try:
        cfg = load_policy()["options_flow"]
    except Exception as e:  # noqa: BLE001 — a missing policy is a finding on the snapshot, not a crash of the radar
        print(f"[flow] policy unavailable: {type(e).__name__}: {e}")
        return {"findings": [], "priority": None, "accepted": None, "error": f"policy: {e}"}
    today = {
        s: dict(rows[s], as_of=datetime.now(timezone.utc).date().isoformat()) for s in cfg["index_symbols"] if s in rows
    }
    hist = {s: history(cur, s, int(cfg["lookback_sessions"])) for s in today}
    findings = of.evaluate(today, hist, cfg)
    try:
        from market_session import current_market_session

        session = current_market_session(now)
    except Exception:  # noqa: BLE001
        session = "unknown"
    priority = of.priority_for(findings, session, cfg)
    out = {"findings": findings, "session": session, "priority": priority, "accepted": None, "error": None}
    if not priority:
        print(f"[flow] {len(findings)} finding(s), none actionable")
        return out
    when_et = (now or datetime.now(timezone.utc)).astimezone().strftime("%a %m-%d %H:%M %Z")
    message = of.render(findings, session, when_et)
    out["message"] = message
    if dry_run:
        print(f"[flow] DRY RUN would send {priority}:\n{message}")
        return out
    try:
        from telegram_alert import send_telegram

        out["accepted"] = bool(
            send_telegram(
                message,
                priority=priority,
                dedupe_minutes=int(cfg["dedupe_minutes"]),
                producer=cfg["producer"],
                message_class="market_risk",
            )
        )
    except Exception as e:  # noqa: BLE001
        out["accepted"] = False
        out["error"] = f"{type(e).__name__}: {e}"
        print(f"[flow] WARNING send failed: {out['error']}", file=sys.stderr)
    return out
