"""live_trading_interlock.py — the hard gate-interlock (2026-06-04; R1 2026-07-21).

THE SAFETY for the editable ATM + proposal controls. Any write that would arm execution, change
risk, or approve a trade against a LIVE account is REFUSED unless the live-trading gate has passed
(paper_validation_policy.live_trading_allowed = TRUE). Paper accounts are always writable. Unknown
accounts fail CLOSED (refused).

R1: account_mode() prefers broker_accounts.environment (+ automation posture); falls back to
legacy accounts.mode and logs every fallback/disagreement to interlock_parity_log. Behavior
contract unchanged. Legacy table remains until R1b (parity window clean).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

# Identity aliases (emitters may still use old labels until R3 backfill completes)
_ALIASES = {
    "alpaca_paper": "tradeai_automated",  # hardcode-ok: legacy identity → canonical
    "ALPACA_PAPER": "tradeai_automated",
    "tradeai_automated": "tradeai_automated",
    "fidelity_401k": "fidelity_rollover_ira",  # hardcode-ok: legacy label → canonical import row
}


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


def _normalize(account_label: str) -> str:
    raw = (account_label or "").strip()
    if not raw:
        return ""
    return _ALIASES.get(raw, _ALIASES.get(raw.lower(), raw))


def _canonical_mode(conn, account_label: str):
    """Return 'paper' | 'live' | None from broker_accounts.environment."""
    key = _normalize(account_label)
    if not key:
        return None
    cur = conn.cursor()
    cur.execute(
        """SELECT environment FROM broker_accounts
           WHERE account_key=%s OR lower(account_key)=lower(%s)
           LIMIT 1""",
        (key, key),
    )
    r = cur.fetchone()
    if not r:
        return None
    env = (r[0] or "").strip().lower()
    if env == "paper":
        return "paper"
    if env in ("live", "import"):
        # import = real-money book lineage, not paper automation — treat as live for arming
        return "live"
    return None


def _legacy_mode(conn, account_label: str):
    """Return 'paper' | 'live' | None from legacy accounts.mode."""
    key = _normalize(account_label)
    # also try raw label for pre-alias rows
    cur = conn.cursor()
    for candidate in (key, (account_label or "").strip()):
        if not candidate:
            continue
        cur.execute("SELECT mode FROM accounts WHERE account_label=%s", (candidate,))
        r = cur.fetchone()
        if r:
            m = (r[0] or "").strip().lower()
            return m if m in ("paper", "live") else None
    return None


def _log_parity(conn, account, canonical, legacy, caller, action, detail=None):
    try:
        agreed = (canonical == legacy) or (canonical is None and legacy is None)
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO interlock_parity_log
               (account, canonical_answer, legacy_answer, agreed, caller, action, detail)
               VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)""",
            (
                account,
                canonical,
                legacy,
                agreed,
                (caller or "")[:200],
                (action or "")[:80],
                __import__("json").dumps(detail or {}),
            ),
        )
        conn.commit()
        if not agreed:
            try:
                import logging
                logging.getLogger(__name__).warning(
                    "interlock parity disagree account=%s canonical=%s legacy=%s caller=%s",
                    account, canonical, legacy, caller,
                )
            except Exception:
                pass
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def account_mode(conn, account_label, *, caller=None, action=None, log_parity=True):
    """Return 'paper' | 'live' | None (unknown).

    Prefers broker_accounts.environment; falls back to legacy accounts.mode.
    """
    raw = (account_label or "").strip()
    canonical = _canonical_mode(conn, raw)
    legacy = _legacy_mode(conn, raw)
    if log_parity:
        _log_parity(conn, raw or "?", canonical, legacy, caller or "account_mode",
                    action or "resolve",
                    {"normalized": _normalize(raw)})
    if canonical is not None:
        return canonical
    return legacy


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
    mode = account_mode(conn, account_label, caller="assert_writable", action=action)
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
    # Self-proof: live refused (policy off), paper allowed, unknown refused; R1 canonical keys.
    conn = _conn()
    gs = gate_status(conn)
    print(f"GATE: passed={gs['passed']} live_trading_allowed={gs['live_trading_allowed']} "
          f"criteria_met={gs['criteria_met']}")
    for acct in (
        "tradeai_automated", "alpaca_paper",  # paper + legacy alias
        "schwab_taxable", "schwab_roth_ira", "schwab_rollover_ira",
        "fidelity_rollover_ira", "fidelity_401k",
        "alpaca_taxable_live", "alpaca_ira_live",  # scaffolds (may be unknown until R4)
        "bogus_account",
    ):
        try:
            r = assert_writable(conn, acct, "arm")
            print(f"  ALLOW  {acct:22} -> {r['mode']}")
        except InterlockRefused as e:
            print(f"  REFUSE {acct:22} -> {e.reason}")
    conn.close()
