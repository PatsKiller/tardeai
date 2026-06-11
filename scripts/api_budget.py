#!/usr/bin/env python3
"""api_budget.py — unified daily budget ledger for ALL external news/data APIs.

Before: each provider's limit was tracked nowhere (NewsAPI 500/day could exhaust by lunch) or in a silo
(Brave had its own 25/day). Now: one DB-backed ledger every caller checks BEFORE spending a request.

  from api_budget import spend, remaining
  if spend("newsapi"):          # records the call, returns False if budget exhausted
      ... make the request ...

Caps come from env (API_BUDGET_<PROVIDER>, with sane free-tier defaults below) — no hardcoding beyond
documented defaults. Read-only callers fail-open on ledger errors (a broken ledger must not kill ingestion).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# documented free-tier defaults; override via env API_BUDGET_NEWSAPI etc.
DEFAULT_CAPS = {
    "newsapi": 450,       # 500/day free — headroom
    "finnhub": 800,       # 60/min free; daily soft cap
    "polygon": 250,       # 5/min free
    "fmp": 230,           # 250/day free
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


def spend(provider: str, n: int = 1) -> bool:
    """Record n calls. Returns True if within budget, False if exhausted (caller should skip)."""
    try:
        conn = _conn(); cur = conn.cursor()
        _ensure(cur)
        cur.execute("""INSERT INTO api_budget_ledger (provider, day, calls) VALUES (%s, CURRENT_DATE, %s)
                       ON CONFLICT (provider, day) DO UPDATE SET calls = api_budget_ledger.calls + %s
                       RETURNING calls""", (provider, n, n))
        calls = cur.fetchone()[0]
        conn.commit()
        if calls > _cap(provider):
            if calls - n <= _cap(provider):   # log once at the crossing
                print(f"  [api-budget] {provider} daily budget exhausted ({calls}/{_cap(provider)}) — skipping further calls")
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
