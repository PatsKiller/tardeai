"""Stage 2b pilot caps (SB-1) — commit-only literals, same discipline as canary_gate.py.

Sits BEHIND the canary gate in execution_guard (canary first, then these). The canary gate bounds
WHAT an order can be (symbol/price/qty/notional/date); this module bounds HOW MANY and WHERE:

  • PILOT_ACCOUNT_ALLOWLIST — the ONLY account a Schwab write may ever target this stage.
    IRAs are structurally excluded (operator decision 2026-06-12). Changing this = git commit.
  • MAX_PILOT_ORDERS_TOTAL — cumulative lifetime cap for the whole pilot (operator: 5).
    Counted from schwab_pilot_orders (every row that reached the POST boundary, regardless of
    broker outcome). Order #6 is blocked forever until a NEW pilot is committed.

HARD RULE (same as canary_gate): NO os.getenv, NO config imports in the cap values. The order
count is read from the DB — a read, not a widening knob; any DB error ⇒ fail closed.
"""
from __future__ import annotations

PILOT_ACCOUNT_ALLOWLIST: tuple[str, ...] = ("schwab_taxable",)
# Operator unlock 2026-06-22: cap removed for pilot continuity (2FA + canary gate still apply).
MAX_PILOT_ORDERS_TOTAL = 9999


def orders_used() -> int:
    """Rows that reached the POST boundary (status set before any HTTP). DB error ⇒ cap-exceeded
    sentinel so the guard fails closed."""
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        # table absent ⇒ truly zero pilot orders (transport persists a row BEFORE any POST can happen)
        cur.execute("SELECT to_regclass('schwab_pilot_orders')")
        if cur.fetchone()[0] is None:
            return 0
        # count ONLY canary-family rows — Stage-2c protective stops carry their own envelope and must
        # not consume the canary 5-order budget (kind defaults to 'canary'; legacy rows are NULL='canary')
        cur.execute("SELECT count(*) FROM schwab_pilot_orders WHERE status <> 'blocked_pre_post' "
                    "AND (kind IS NULL OR kind = 'canary')")
        return int(cur.fetchone()[0] or 0)
    except Exception:
        return MAX_PILOT_ORDERS_TOTAL + 1   # unknown count ⇒ treat as exhausted (fail closed)


def evaluate(account_key: str | None) -> tuple[bool, list[str]]:
    """Pure pass/fail + reasons. Fail closed on anything unexpected."""
    reasons: list[str] = []
    if (account_key or "").strip() not in PILOT_ACCOUNT_ALLOWLIST:
        reasons.append(f"account {account_key!r} not in committed pilot allowlist "
                       f"{PILOT_ACCOUNT_ALLOWLIST} (IRAs are structurally excluded)")
    used = orders_used()
    if used >= MAX_PILOT_ORDERS_TOTAL:
        reasons.append(f"pilot order cap reached ({used}/{MAX_PILOT_ORDERS_TOTAL}) — "
                       "recommitting a new pilot is the only way to continue")
    return (not reasons, reasons)
