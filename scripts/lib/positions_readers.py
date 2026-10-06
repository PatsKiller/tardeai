"""READ-ONLY broker readers for scripts/positions_sync.py (positions store phase 1, 2026-10-06).

Each reader returns {"ok": True, "cash", "equity", "positions": [...], "source"} or {"ok": False, "error"}.
They reuse the read clients the existing read syncs already use and add no new broker surface:
  * Alpaca LIVE  — brokers.alpaca_read_client (GET-only; refuses non-GET). Paper is never read here:
    paper is training only and never counted in live totals.
  * moomoo       — moomoo.client.MoomooTradeReader (accinfo_query / position_list_query only; the
    order path raises MoomooAuthorityError).
An error is an error: an unreachable broker never reads as "no positions".
"""
from __future__ import annotations

from typing import Any, Optional


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def read_alpaca_live(account_key: str) -> dict:
    from brokers import alpaca_read_client as arc  # type: ignore
    acct = arc.fetch_account(account_key)
    if not isinstance(acct, dict) or "cash" not in acct:
        return {"ok": False, "error": f"alpaca account read failed: {str(acct)[:120]}"}
    if str(acct.get("status") or "").upper() not in ("ACTIVE", ""):
        return {"ok": False, "error": f"alpaca account status {acct.get('status')}"}
    raw = arc.fetch_json(account_key, "/v2/positions")
    if not isinstance(raw, list):
        return {"ok": False, "error": f"alpaca positions read failed: {str(raw)[:120]}"}
    rows = []
    for p in raw:
        qty = _f(p.get("qty")) or 0.0
        cost = _f(p.get("cost_basis"))
        rows.append({"symbol": str(p.get("symbol") or "").upper(), "qty": qty, "cost_basis_total": cost,
                     "avg_cost": _f(p.get("avg_entry_price")), "broker_market_value": _f(p.get("market_value")),
                     "asset_type": p.get("asset_class")})
    return {"ok": True, "cash": _f(acct.get("cash")) or 0.0, "equity": _f(acct.get("equity")),
            "positions": rows, "source": "alpaca_live_api"}


def read_moomoo(account_key: str) -> dict:
    from moomoo.client import MoomooTradeReader  # type: ignore
    r = MoomooTradeReader()
    real = [a for a in r.accounts() if str(a.get("trd_env", "")).upper() == "REAL"]
    if not real:
        return {"ok": False, "error": "moomoo: no REAL account visible under FUTUINC"}
    snap = r.snapshot(real[0]["acc_id"])
    rows = []
    for p in snap.get("positions") or []:
        code = str(p.get("code") or "")
        sym = code.split(".", 1)[1] if "." in code else code
        qty = p.get("qty") or 0.0
        cp = p.get("cost_price")
        # moomoo reports cost_price 0.0 for granted/reward shares: basis is $0 by the broker's account,
        # recorded as such (an inflow, not a return) — never invented.
        rows.append({"symbol": sym.upper(), "qty": qty,
                     "cost_basis_total": None if cp is None else round(cp * qty, 2),
                     "avg_cost": cp, "broker_market_value": p.get("market_val"), "asset_type": "EQUITY"})
    return {"ok": True, "cash": snap.get("cash") or 0.0, "equity": snap.get("total_assets"),
            "positions": rows, "source": "moomoo_opend"}
