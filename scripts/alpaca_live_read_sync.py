#!/usr/bin/env python3
"""alpaca_live_read_sync.py — read-only sync for live Alpaca accounts (api_read_enabled only).

Iterates broker_accounts where broker=alpaca AND environment=live AND api_read_enabled=true.
With default R4 scaffolds (api_read=false) this makes ZERO API calls.

Merges positions AND the account's uninvested cash into holdings.json via
protected_holdings_write only. Totals are left to portfolio_loader/portfolio_repricer.
Never sets is_enabled / api_write_enabled / live_arm_token.

  .venv/bin/python scripts/alpaca_live_read_sync.py
  .venv/bin/python scripts/alpaca_live_read_sync.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

log = logging.getLogger("alpaca_live_read_sync")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

try:
    from env_bootstrap import load_env
    load_env()
except Exception:
    pass

HOLDINGS_PATH = ROOT / "data" / "portfolios" / "state" / "holdings.json"
FAIL_STREAK_PATH = ROOT / "data" / "runtime" / "alpaca_live_read_fail_streak.json"


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _live_read_accounts():
    cur = _conn().cursor()
    cur.execute(
        """SELECT account_key, display_name, credential_slot
             FROM broker_accounts
            WHERE lower(broker)='alpaca' AND environment='live'
              AND COALESCE(api_read_enabled, false)=true
            ORDER BY account_key"""
    )
    cols = ["account_key", "display_name", "credential_slot"]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _positions_to_holdings_rows(account_key: str, positions: list) -> list:
    """Map Alpaca position objects → holdings.json row shape (Schwab-like)."""
    rows = []
    now = datetime.now(timezone.utc).isoformat()
    for p in positions or []:
        sym = (p.get("symbol") or "").upper()
        if not sym:
            continue
        try:
            qty = float(p.get("qty") or p.get("qty_available") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if abs(qty) < 1e-12:
            continue
        try:
            price = float(p.get("current_price") or p.get("asset_current_price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        try:
            mv = float(p.get("market_value") or (price * qty))
        except (TypeError, ValueError):
            mv = price * qty
        try:
            avg = float(p.get("avg_entry_price") or 0)
        except (TypeError, ValueError):
            avg = 0.0
        rows.append({
            "symbol": sym,
            "account": account_key,
            "shares": qty,
            "quantity": qty,
            "price": price,
            "market_value": mv,
            "cost_basis": avg * qty if avg else None,
            "avg_cost": avg or None,
            "name": p.get("symbol"),
            "source": "alpaca_live_read",
            "as_of": now,
            "updated_at": now,
        })
    return rows


def _account_to_cash_row(account_key: str, acct: dict | None) -> list:
    """Map the Alpaca account's uninvested cash → a holdings.json CASH row.

    Positions are emitted separately by _positions_to_holdings_rows, so this MUST use
    `cash` (uninvested) and never `equity` (cash + position market value) or the
    account double-counts.

    Without this the account is invisible to the portfolio whenever it holds no
    positions: the sync mapped positions only, used the account object as a mere
    `bool` hint, and with 0 positions no-op'd entirely — so $5,000 of live cash in
    alpaca_taxable_live never reached the $1.25M total (2026-07-28).
    """
    if not acct:
        return []
    raw = acct.get("cash")
    if raw is None:
        return []
    try:
        cash = float(raw)
    except (TypeError, ValueError):
        return []
    if abs(cash) < 0.005:
        return []
    now = datetime.now(timezone.utc)
    # Shape mirrors the Schwab cash rows so the repricer's cash anchor, the Cash
    # bucket and the portfolio UI treat it identically.
    return [{
        "symbol": "CASH",
        "name": "Cash & Cash Investments",
        "account": account_key,
        "account_id": account_key,
        "asset_type": "cash",
        "bucket": "Cash",
        "is_cash": True,
        "shares": cash,
        "quantity": cash,
        "price": 1.0,
        "current_price": 1.0,
        "market_value": cash,
        "day_change": 0,
        "day_change_pct": 0,
        "source": "alpaca_live_read",
        "as_of": now.date().isoformat(),
        # Stamp the broker confirmation time here for the same reason as the Schwab
        # rows: portfolio_repricer._preserve_broker_snapshot is write-once and can
        # only backfill this field when absent, never refresh it.
        "broker_position_as_of": now.date().isoformat(),
        "updated_at": now.isoformat(),
    }]


def _merge_account_into_holdings(
    account_key: str, new_rows: list, *, dry_run: bool, preserve_prior_cash: bool = False
) -> dict:
    """Replace only this account's rows; keep all other accounts intact.

    Empty new_rows with no prior alpaca rows → pure no-op (must not zero portfolio).

    preserve_prior_cash carries forward the account's existing CASH row when the
    account object could not be read this cycle, so a transient API miss cannot
    silently delete a real cash balance.

    Deliberately does NOT touch portfolio_totals. The naive sum this used to write
    disagreed with portfolio_repricer by ~$450 (it ignored the is_loan/no-cost-basis
    exclusion logic) and left total_cash/total_cost/total_gain stale beside a changed
    total_value. portfolio_loader + portfolio_repricer own the totals and rebuild them
    from the rows — and portfolio_loader auto-creates an account_summaries entry for
    any new account key, so this account is picked up without further config. This
    matches schwab_position_sync, which likewise replaces only its own rows.
    """
    if not HOLDINGS_PATH.exists():
        return {"ok": False, "error": "holdings.json missing"}
    data = json.loads(HOLDINGS_PATH.read_text())
    holdings = list(data.get("holdings") or [])
    others = [h for h in holdings if (h.get("account") or "") != account_key]
    prior_acct = [h for h in holdings if (h.get("account") or "") == account_key]

    if preserve_prior_cash and not any(r.get("is_cash") for r in new_rows):
        carried = [h for h in prior_acct if h.get("is_cash")]
        if carried:
            new_rows = list(new_rows) + carried
            log.warning("%s: account read unusable — carried forward prior CASH row", account_key)

    if not new_rows and not prior_acct:
        return {"ok": True, "wrote": False, "reason": "empty_noop_no_prior", "n": 0}

    merged = others + new_rows
    data["holdings"] = merged
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    if dry_run:
        return {"ok": True, "wrote": False, "dry_run": True, "n": len(new_rows)}

    from holdings_guard import protected_holdings_write
    res = protected_holdings_write(
        data,
        source="alpaca_live_read_sync",
        account_key=account_key,
        protect_basis=False,
        target_path=str(HOLDINGS_PATH),
    )
    return {"ok": True, "wrote": True, "n": len(new_rows), "guard": res}


def _streak_path():
    FAIL_STREAK_PATH.parent.mkdir(parents=True, exist_ok=True)
    return FAIL_STREAK_PATH


def _bump_fail(account_key: str) -> int:
    p = _streak_path()
    try:
        d = json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        d = {}
    d[account_key] = int(d.get(account_key) or 0) + 1
    p.write_text(json.dumps(d))
    return d[account_key]


def _clear_fail(account_key: str):
    p = _streak_path()
    try:
        d = json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        d = {}
    if account_key in d:
        d[account_key] = 0
        p.write_text(json.dumps(d))


def _telegram(msg: str):
    try:
        from telegram_alert import send_telegram
        send_telegram(msg, bypass_router=True)  # uses all configured chat_ids from env
    except Exception as e:
        log.warning("telegram: %s", e)


def sync_one(account_key: str, *, dry_run: bool = False, force: bool = False) -> dict:
    """Sync one account. force=True skips api_read_enabled (tests only — not used by cron)."""
    from brokers import alpaca_read_client as arc

    enabled, row = arc._api_read_enabled(account_key)
    if not force and not enabled:
        return {"account": account_key, "ok": True, "skipped": True, "reason": "api_read_disabled"}

    try:
        positions = arc.fetch_positions(account_key) if enabled or force else []
        acct = arc.fetch_account(account_key) if (enabled or force) else None
        activities = arc.fetch_activities(account_key) if (enabled or force) else []
    except arc.MethodNotAllowedError:
        raise
    except Exception as e:
        n = _bump_fail(account_key)
        try:
            cur = _conn().cursor()
            cur.execute(
                "UPDATE broker_accounts SET connection_status=%s, updated_at=now() WHERE account_key=%s",
                ("error", account_key),
            )
            _conn().commit()
        except Exception:
            pass
        if n >= 3:
            _telegram(f"⚠️ Alpaca live read sync FAILED ×{n} for {account_key}: {str(e)[:120]}")
        return {"account": account_key, "ok": False, "error": str(e)[:200], "fail_streak": n}

    pos_rows = _positions_to_holdings_rows(account_key, positions)
    cash_rows = _account_to_cash_row(account_key, acct)
    rows = pos_rows + cash_rows
    merge = _merge_account_into_holdings(
        account_key, rows, dry_run=dry_run,
        # acct unreadable → don't let a transient miss delete a real cash balance
        preserve_prior_cash=not cash_rows,
    )

    # Attribute fills into a lightweight runtime journal tag file (no P&L rewrite)
    try:
        tag_path = ROOT / "data" / "runtime" / "alpaca_live_read_fills.jsonl"
        tag_path.parent.mkdir(parents=True, exist_ok=True)
        with tag_path.open("a") as f:
            for act in (activities or [])[:20]:
                f.write(json.dumps({
                    "account_key": account_key,
                    "source": "alpaca_live_read",
                    "activity": {k: act.get(k) for k in (
                        "id", "symbol", "side", "qty", "price", "transaction_time", "type"
                    ) if k in act},
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                }) + "\n")
    except Exception:
        pass

    first_ok = False
    try:
        cur = _conn().cursor()
        cur.execute("SELECT connection_status FROM broker_accounts WHERE account_key=%s", (account_key,))
        prev = (cur.fetchone() or [None])[0]
        cur.execute(
            """UPDATE broker_accounts SET connection_status=%s, last_sync_at=now(), updated_at=now()
               WHERE account_key=%s""",
            ("ok", account_key),
        )
        _conn().commit()
        first_ok = (prev or "") != "ok"
    except Exception:
        pass

    _clear_fail(account_key)
    if first_ok and not dry_run:
        _telegram(f"✅ Alpaca live read sync OK for {account_key} (n_pos={len(pos_rows)})")

    return {
        "account": account_key,
        "ok": True,
        "n_positions": len(pos_rows),
        "cash": cash_rows[0]["market_value"] if cash_rows else None,
        "equity_hint": bool(acct),
        "merge": merge,
    }


def run(*, dry_run: bool = False) -> dict:
    accts = _live_read_accounts()
    results = []
    if not accts:
        log.info("no live alpaca accounts with api_read_enabled=true — zero API calls")
        return {"ok": True, "accounts": [], "results": [], "api_calls": 0}

    for a in accts:
        key = a["account_key"]
        try:
            results.append(sync_one(key, dry_run=dry_run))
        except Exception as e:
            results.append({"account": key, "ok": False, "error": str(e)[:200]})
            log.exception("sync %s", key)

    return {
        "ok": all(r.get("ok") for r in results),
        "accounts": [a["account_key"] for a in accts],
        "results": results,
        "api_calls": len(accts),
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
