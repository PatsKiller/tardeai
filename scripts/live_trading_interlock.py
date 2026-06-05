"""live_trading_interlock.py — the hard gate-interlock (2026-06-04).

THE SAFETY for the editable ATM + proposal controls. Any write that would arm execution, change
risk, or approve a trade against a LIVE account is REFUSED unless the live-trading gate has passed
(paper_validation_policy.live_trading_allowed = TRUE). Paper accounts are always writable. Unknown
accounts fail CLOSED (refused). This makes it physically impossible for the dashboard controls to
reach a live account before the system's own readiness bar is met — regardless of what is clicked.

The controls (ATM state, risk edits, proposal approve) call assert_writable(account) FIRST; if it
raises InterlockRefused the endpoint returns 403 before any guard/confirm/apply runs.
"""
import os
from datetime import datetime, timezone


class InterlockRefused(Exception):
    """Raised when a write targets a live account and the gate has not passed."""
    def __init__(self, reason, detail=None):
        self.reason = reason
        self.detail = detail or {}
        super().__init__(reason)


def _conn():
    import psycopg2
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def account_mode(conn, account_label):
    """Return 'paper' | 'live' | None (unknown) for an account_label."""
    cur = conn.cursor()
    cur.execute("SELECT mode FROM accounts WHERE account_label=%s", (account_label,))
    r = cur.fetchone()
    return r[0] if r else None


def gate_status(conn):
    """Live-trading gate state + progress. `passed` is governed by the master flag
    live_trading_allowed (criteria are required-but-not-sufficient: even if every criterion is met,
    governance must still flip the flag)."""
    cur = conn.cursor()
    cur.execute("""SELECT validation_start_date, minimum_validation_days, minimum_closed_trades,
                          minimum_win_rate, minimum_profit_factor, live_trading_allowed
                   FROM paper_validation_policy WHERE active=true ORDER BY id DESC LIMIT 1""")
    row = cur.fetchone()
    if not row:
        return {"passed": False, "live_trading_allowed": False, "criteria_met": False,
                "reason": "no active validation policy", "checks": {}}
    start, min_days, min_trades, min_wr, min_pf, allowed = row
    days = (datetime.now(timezone.utc).date() - start).days if start else 0
    cur.execute("""SELECT count(*), COALESCE(AVG(CASE WHEN pnl>0 THEN 1.0 ELSE 0 END),0)
                   FROM paper_trades WHERE status IN ('closed','CLOSED') AND pnl IS NOT NULL""")
    n, wr = cur.fetchone()
    cur.execute("""SELECT COALESCE(SUM(CASE WHEN pnl>0 THEN pnl ELSE 0 END),0),
                          COALESCE(ABS(SUM(CASE WHEN pnl<0 THEN pnl ELSE 0 END)),0)
                   FROM paper_trades WHERE status IN ('closed','CLOSED') AND pnl IS NOT NULL""")
    gp, gl = cur.fetchone()
    pf = float(gp) / float(gl) if gl and float(gl) > 0 else 0.0
    checks = {
        "days":          {"have": days,                 "need": min_days or 0,        "ok": days >= (min_days or 0)},
        "closed_trades": {"have": n,                    "need": min_trades or 0,      "ok": n >= (min_trades or 0)},
        "win_rate":      {"have": round(float(wr), 3),  "need": float(min_wr or 0),   "ok": float(wr) >= float(min_wr or 0)},
        "profit_factor": {"have": round(pf, 2),         "need": float(min_pf or 0),   "ok": pf >= float(min_pf or 0)},
    }
    return {
        "live_trading_allowed": bool(allowed),
        "criteria_met": all(c["ok"] for c in checks.values()),
        "passed": bool(allowed),
        "checks": checks,
    }


def assert_writable(conn, account_label, action="write"):
    """THE INTERLOCK. Raise InterlockRefused if the target account is LIVE and the gate hasn't
    passed. Paper accounts always pass. Unknown accounts fail CLOSED (refused)."""
    mode = account_mode(conn, account_label)
    if mode is None:
        raise InterlockRefused(f"unknown account '{account_label}' — refused (fail-closed)",
                               {"account": account_label})
    if mode == "paper":
        return {"ok": True, "account": account_label, "mode": "paper"}
    gs = gate_status(conn)
    if not gs.get("passed"):
        raise InterlockRefused(
            f"live-trading gate not passed — '{action}' on live account '{account_label}' refused",
            {"account": account_label, "mode": mode, "gate": gs})
    return {"ok": True, "account": account_label, "mode": mode, "gate_passed": True}


if __name__ == "__main__":
    # Self-proof: live accounts refused, paper allowed, unknown refused.
    conn = _conn()
    gs = gate_status(conn)
    print(f"GATE: passed={gs['passed']} live_trading_allowed={gs['live_trading_allowed']} "
          f"criteria_met={gs['criteria_met']}")
    for acct in ("schwab_taxable", "schwab_roth_ira", "schwab_rollover_ira", "fidelity_401k",
                 "alpaca_paper", "bogus_account"):
        try:
            r = assert_writable(conn, acct, "arm")
            print(f"  ALLOW  {acct:22} -> {r['mode']}")
        except InterlockRefused as e:
            print(f"  REFUSE {acct:22} -> {e.reason}")
    conn.close()
