#!/usr/bin/env python3
"""api_budget.py — unified daily budget ledger for ALL external news/data APIs.

Before: each provider's limit was tracked nowhere or in a silo
(Brave had its own 25/day). Now: one DB-backed ledger every caller checks BEFORE spending a request.

  from api_budget import spend, remaining
  if spend("finviz_news"):      # records the call, returns False if budget exhausted
      ... make the request ...

Caps come from env (API_BUDGET_<PROVIDER>, with sane free-tier defaults below) — no hardcoding beyond
documented defaults. Read-only callers fail-open on ledger errors (a broken ledger must not kill ingestion).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# documented free-tier defaults; override via env API_BUDGET_<PROVIDER>
DEFAULT_CAPS = {
    # newsapi / finnhub / polygon / fmp retired 2026-09-13 — config/data_source_authority.json
    "brave": 25,          # existing budget honored
    "finviz_news": 1500,  # token-based, polite cap
    "alphavantage": 22,   # 25/day free — tight
}


def _cap(provider: str) -> int:
    return int(os.getenv(f"API_BUDGET_{provider.upper()}", DEFAULT_CAPS.get(provider, 500)))


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _ensure(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS api_budget_ledger (
        provider TEXT NOT NULL, day DATE NOT NULL DEFAULT CURRENT_DATE,
        calls INT NOT NULL DEFAULT 0, PRIMARY KEY (provider, day))""")


_EXHAUSTED_LOGGED: set = set()


def spend(provider: str, n: int = 1) -> bool:
    """Record n calls if they fit the cap. Returns True if within budget, False if exhausted (caller skips).

    The cap is checked BEFORE the ledger is incremented (2026-10-10): a refused call is not recorded, so
    `calls` counts permitted requests only and can never read above the cap ("exhausted 23/22" was the
    old increment-then-compare shape counting refusals as spend).
    """
    try:
        cap = _cap(provider)
        conn = _conn(); cur = conn.cursor()
        _ensure(cur)
        cur.execute("""INSERT INTO api_budget_ledger (provider, day, calls)
                       SELECT %s, CURRENT_DATE, %s WHERE %s <= %s
                       ON CONFLICT (provider, day) DO UPDATE SET calls = api_budget_ledger.calls + EXCLUDED.calls
                       WHERE api_budget_ledger.calls + EXCLUDED.calls <= %s
                       RETURNING calls""", (provider, n, n, cap, cap))
        row = cur.fetchone()
        conn.commit()
        if row is None:
            if provider not in _EXHAUSTED_LOGGED:   # log once per process
                _EXHAUSTED_LOGGED.add(provider)
                print(f"  [api-budget] {provider} daily budget exhausted (cap {cap}) — skipping further calls")
            return False
        return True
    except Exception:
        return True   # fail-open: ledger problems must never kill ingestion


def remaining(provider: str) -> int:
    try:
        conn = _conn(); cur = conn.cursor()
        _ensure(cur)
        cur.execute("SELECT calls FROM api_budget_ledger WHERE provider=%s AND day=CURRENT_DATE", (provider,))
        r = cur.fetchone()
        return max(0, _cap(provider) - (r[0] if r else 0))
    except Exception:
        return _cap(provider)


def status() -> dict:
    out = {}
    try:
        conn = _conn(); cur = conn.cursor()
        _ensure(cur)
        cur.execute("SELECT provider, calls FROM api_budget_ledger WHERE day=CURRENT_DATE")
        used = dict(cur.fetchall())
        for p in DEFAULT_CAPS:
            out[p] = {"used": used.get(p, 0), "cap": _cap(p)}
    except Exception:
        pass
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(status(), indent=2))
