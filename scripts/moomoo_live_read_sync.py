#!/usr/bin/env python3
"""moomoo_live_read_sync.py — READ-ONLY sync for the live moomoo account.

Mirrors alpaca_live_read_sync.py: merges positions AND uninvested cash into
holdings.json through protected_holdings_write, and leaves portfolio_totals to
portfolio_loader/portfolio_repricer (they own the exclusion logic; a naive local sum
disagrees with the repricer and desyncs total_cash/total_gain).

READ PLANE ONLY. Uses MoomooTradeReader, which exposes accinfo_query /
position_list_query and hard-refuses place/modify/cancel/unlock. No order path, no
trade unlock, never sets is_enabled / api_write_enabled.

The REAL US account is under SecurityFirm.FUTUINC; FUTUSECURITIES shows only the
SIMULATE account and reads exactly like "no live account exists".

  .venv/bin/python scripts/moomoo_live_read_sync.py --dry-run
  .venv/bin/python scripts/moomoo_live_read_sync.py
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

log = logging.getLogger("moomoo_live_read_sync")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

try:
    from env_bootstrap import load_env
    load_env()
except Exception:
    pass

HOLDINGS_PATH = ROOT / "data" / "portfolios" / "state" / "holdings.json"
ACCOUNT_KEY = "moomoo_taxable_live"
DISPLAY_NAME = "Moomoo Taxable (Live · read-only data)"


def _now():
    return datetime.now(timezone.utc)


def _live_account() -> dict | None:
    """The one REAL account, or None. Never guesses — SIMULATE is explicitly excluded."""
    from moomoo.client import MoomooTradeReader
    r = MoomooTradeReader()
    accs = [a for a in r.accounts() if a.get("trd_env", "").upper() == "REAL"]
    if not accs:
        log.warning("no REAL moomoo account (only SIMULATE) — nothing to sync")
        return None
    if len(accs) > 1:
        log.warning("%d REAL accounts found; syncing the first (%s)", len(accs), accs[0]["acc_id"])
    return r.snapshot(accs[0]["acc_id"])


def _to_holdings_rows(snap: dict) -> list[dict]:
    """Positions + a CASH row, shaped like the Schwab/Alpaca rows.

    Cash uses `cash` (uninvested), never `total_assets` — total_assets includes position
    market value, which the position rows already carry, so it would double-count.
    """
    now = _now()
    rows: list[dict] = []

    for p in snap.get("positions") or []:
        code = (p.get("code") or "").strip()
        sym = code.split(".")[-1].upper() if code else ""
        qty = p.get("qty") or 0.0
        if not sym or abs(qty) < 1e-12:
            continue
        px = p.get("nominal_price")
        mv = p.get("market_val")
        if mv is None and px is not None:
            mv = px * qty
        cost = p.get("cost_price")
        rows.append({
            "symbol": sym, "name": sym, "account": ACCOUNT_KEY, "account_id": ACCOUNT_KEY,
            "shares": qty, "quantity": qty,
            "price": px, "current_price": px, "market_value": mv,
            "cost_basis": (cost * qty) if cost else None, "avg_cost": cost or None,
            "source": "moomoo_live_read",
            "as_of": now.date().isoformat(), "updated_at": now.isoformat(),
        })

    cash = snap.get("cash")
    if cash is not None and abs(float(cash)) >= 0.005:
        rows.append({
            "symbol": "CASH", "name": "Cash & Cash Investments",
            "account": ACCOUNT_KEY, "account_id": ACCOUNT_KEY,
            "asset_type": "cash", "bucket": "Cash", "is_cash": True,
            "shares": float(cash), "quantity": float(cash),
            "price": 1.0, "current_price": 1.0, "market_value": float(cash),
            "day_change": 0, "day_change_pct": 0,
            "source": "moomoo_live_read",
            "as_of": now.date().isoformat(), "updated_at": now.isoformat(),
        })
    return rows


def _merge(rows: list[dict], *, dry_run: bool, preserve_prior_cash: bool) -> dict:
    """Replace only this account's rows; every other account is untouched."""
    if not HOLDINGS_PATH.exists():
        return {"ok": False, "error": "holdings.json missing"}
    data = json.loads(HOLDINGS_PATH.read_text())
    holdings = list(data.get("holdings") or [])
    others = [h for h in holdings if (h.get("account") or "") != ACCOUNT_KEY]
    prior = [h for h in holdings if (h.get("account") or "") == ACCOUNT_KEY]

    if preserve_prior_cash and not any(r.get("is_cash") for r in rows):
        carried = [h for h in prior if h.get("is_cash")]
        if carried:
            rows = list(rows) + carried
            log.warning("account read unusable — carried forward prior CASH row")

    if not rows and not prior:
        return {"ok": True, "wrote": False, "reason": "empty_noop_no_prior", "n": 0}

    data["holdings"] = others + rows
    data["updated_at"] = _now().isoformat()
    if dry_run:
        return {"ok": True, "wrote": False, "dry_run": True, "n": len(rows)}

    from holdings_guard import protected_holdings_write
    res = protected_holdings_write(data, source="moomoo_live_read_sync",
                                   account_key=ACCOUNT_KEY, protect_basis=False,
                                   target_path=str(HOLDINGS_PATH))
    return {"ok": True, "wrote": True, "n": len(rows), "guard": res}


def _touch_broker_account(ok: bool) -> None:
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""UPDATE broker_accounts
                          SET connection_status=%s, last_sync_at=now(), updated_at=now()
                        WHERE account_key=%s""", ("ok" if ok else "error", ACCOUNT_KEY))
        conn.commit()
    except Exception as e:
        log.warning("broker_accounts touch failed: %s", str(e)[:120])


def run(*, dry_run: bool = False) -> dict:
    try:
        snap = _live_account()
    except Exception as e:
        _touch_broker_account(False)
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    if snap is None:
        return {"ok": True, "skipped": True, "reason": "no REAL account"}

    rows = _to_holdings_rows(snap)
    merge = _merge(rows, dry_run=dry_run,
                   preserve_prior_cash=not any(r.get("is_cash") for r in rows))
    if not dry_run:
        _touch_broker_account(True)
    return {
        "ok": True, "account": ACCOUNT_KEY, "acc_id": snap["acc_id"],
        "cash": snap.get("cash"), "total_assets": snap.get("total_assets"),
        "n_positions": len(snap.get("positions") or []),
        "merge": merge,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    out = run(dry_run=args.dry_run)
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
