#!/usr/bin/env python3
"""generate_max_hold_exit_proposals.py — turn the unenforced `auto_exit_at_max_hold` config into an
ACTIONABLE, approval-gated time-exit. For each open paper position held past its strategy's
max_hold_days, create an advisory CLOSE PROPOSAL (paper_time_exit_proposals, status=pending_review).

ADVISORY ONLY — this NEVER closes a position. The operator approves via the API/UI; approval routes
through the paper-only interlock + the existing close_paper_trade path (see api_v2 time-exit-proposals
approve handler). No silent auto-close.

  python3 scripts/generate_max_hold_exit_proposals.py [--apply]
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
_MAX_HOLD_CACHE = {}


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _strategy_max_hold(strategy):
    if not strategy:
        return None
    if strategy in _MAX_HOLD_CACHE:
        return _MAX_HOLD_CACHE[strategy]
    val = None
    try:
        p = PROJECT_ROOT / "config" / "strategies" / f"{strategy}.yaml"
        if p.exists():
            m = re.search(r"max_hold_days:\s*(\d+)", p.read_text())
            val = int(m.group(1)) if m else None
    except Exception:
        val = None
    _MAX_HOLD_CACHE[strategy] = val
    return val


def _send_proposal_alert(pid, symbol, strategy, hold_days, max_hold_days, overdue_by, upnl):
    """Telegram alert via chokepoint with one-tap approve/reject keyboard."""
    try:
        from telegram_alert import send_telegram
        txt = (f"⏳ *Time-exit proposal: {symbol}* (id={pid})\n"
               f"Strategy: {strategy} — held {hold_days}d > max {max_hold_days}d (+{overdue_by})\n"
               + (f"Unrealized: {upnl}%\n" if upnl is not None else "")
               + "Past strategy max-hold. Approve/dismiss via buttons or /v3 time-exit proposals "
               f"(proposal id {pid}).")
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Close now", "callback_data": f"texitapprove:{pid}"},
                {"text": "✖ Dismiss", "callback_data": f"texitreject:{pid}"},
            ]]
        }
        send_telegram(txt, reply_markup=keyboard)
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="generate_max_hold_exit_proposals",
                subject_key=f"proposal:time_exit:{pid}",
                retention_class="operational", severity="warning",
                sanitized_body=txt[:500], short_summary=txt[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


def decide(proposal_id, action, operator="operator"):
    """Shared, HARD-GUARDED decision used by the API endpoint AND the Telegram one-tap handler. Broker/
    account agnostic. APPROVE: live_trading_interlock on the TRADE's own account (paper passes, live/
    unknown refused) + the account-appropriate closer's self-guard. No auto-close; no assumed broker."""
    import importlib, json as _j
    conn = _conn(); cur = conn.cursor()
    cur.execute("SELECT trade_id, symbol, status FROM paper_time_exit_proposals WHERE id=%s", (int(proposal_id),))
    row = cur.fetchone()
    if not row:
        return {"ok": False, "error": "proposal not found"}
    trade_id, symbol, status = row
    if status != "pending_review":
        return {"ok": False, "error": f"already {status}", "symbol": symbol}
    if action == "reject":
        cur.execute("UPDATE paper_time_exit_proposals SET status='rejected', decided_by=%s, decided_at=NOW() WHERE id=%s",
                    (operator, int(proposal_id))); conn.commit()
        return {"ok": True, "status": "rejected", "symbol": symbol}
    if action != "approve":
        return {"ok": False, "error": "action must be approve|reject"}
    cur.execute("SELECT account FROM paper_trades WHERE id=%s", (trade_id,))
    ar = cur.fetchone()
    # Broker/account AGNOSTIC: use the TRADE's own account (no assumed broker). Normalize case to the
    # interlock's accounts-table keys. A trade with no account fails closed. The gate is the broker-agnostic
    # interlock (account_mode must be paper, else refused) + the account-appropriate closer's own self-guard.
    acct = ar[0].strip().lower() if ar and ar[0] else None
    if not acct:
        return {"ok": False, "error": "trade has no account — refused (fail closed)", "symbol": symbol}
    try:
        lti = importlib.import_module("live_trading_interlock")
        closer = importlib.import_module("paper_trade_closer")
        cconn = closer.get_db()
        try:
            # interlock uses positional cursors (r[0]); use the db_adapter conn, NOT the closer's dict-cursor conn
            lti.assert_writable(conn, acct, action="close")
        except Exception as e:
            cur.execute("UPDATE paper_time_exit_proposals SET status='apply_failed', apply_result=%s, decided_by=%s, decided_at=NOW() WHERE id=%s",
                        (f"interlock refused ({acct}): {str(e)[:100]}", operator, int(proposal_id))); conn.commit()
            return {"ok": False, "error": f"interlock refused for {acct}", "symbol": symbol}
        result = closer.close_paper_trade(cconn, paper_trade_id=trade_id, reason="time_exit_max_hold")
        ok = bool(result and (result.get("success") or result.get("status") in ("closed", "ok")))
        cur.execute("UPDATE paper_time_exit_proposals SET status=%s, apply_result=%s, decided_by=%s, decided_at=NOW() WHERE id=%s",
                    ("applied" if ok else "apply_failed", _j.dumps(result, default=str)[:400], operator, int(proposal_id))); conn.commit()
        return {"ok": ok, "status": "applied" if ok else "apply_failed", "symbol": symbol, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)[:160], "symbol": symbol}


def run(apply=False):
    conn = _conn(); cur = conn.cursor()
    cur.execute("""SELECT id, symbol, strategy_id, entry_price, current_price, entry_time,
                     GREATEST(0, DATE_PART('day', now() - entry_time))::int AS hold_days
                   FROM paper_trades WHERE status='open' AND entry_time IS NOT NULL""")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    report = {"open": len(rows), "overdue": 0, "proposed": 0, "detail": []}
    for r in rows:
        mh = _strategy_max_hold(r.get("strategy_id"))
        hd = r.get("hold_days") or 0
        if not mh or hd <= mh:
            continue
        report["overdue"] += 1
        # one open proposal per trade — don't duplicate
        cur.execute("""SELECT 1 FROM paper_time_exit_proposals
                       WHERE trade_id=%s AND status IN ('pending_review','approved') LIMIT 1""", (r["id"],))
        if cur.fetchone():
            continue
        upnl = None
        try:
            if r.get("entry_price") and r.get("current_price"):
                upnl = round((float(r["current_price"]) - float(r["entry_price"])) / float(r["entry_price"]) * 100, 2)
        except Exception:
            pass
        if apply:
            cur.execute("""INSERT INTO paper_time_exit_proposals
                             (trade_id, symbol, strategy_id, hold_days, max_hold_days, overdue_by_days,
                              entry_price, current_price, unrealized_pnl_pct)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                        (r["id"], r["symbol"], r.get("strategy_id"), hd, mh, hd - mh,
                         r.get("entry_price"), r.get("current_price"), upnl))
            _pid = cur.fetchone()[0]; conn.commit()
            _send_proposal_alert(_pid, r["symbol"], r.get("strategy_id"), hd, mh, hd - mh, upnl)
        report["proposed"] += 1
        report["detail"].append({"trade_id": r["id"], "symbol": r["symbol"], "strategy": r.get("strategy_id"),
                                 "hold_days": hd, "max_hold_days": mh, "overdue_by": hd - mh, "upnl_pct": upnl})
    print(json.dumps(report, indent=2))
    return report


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true")
    run(apply=ap.parse_args().apply)


if __name__ == "__main__":
    main()
