#!/usr/bin/env python3
"""alpaca_live_read_sync.py — read-only sync for live Alpaca accounts (api_read_enabled only).

Iterates broker_accounts where broker=alpaca AND environment=live AND api_read_enabled=true.
With default R4 scaffolds (api_read=false) this makes ZERO API calls.

Merges positions into holdings.json via protected_holdings_write only.
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

log = logging.getLogger("alpaca_live_read_sync")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

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


def _merge_account_into_holdings(account_key: str, new_rows: list, *, dry_run: bool) -> dict:
    """Replace only this account's equity rows; keep all other accounts intact.

    Empty new_rows with no prior alpaca rows → pure no-op (must not zero portfolio).
    """
    if not HOLDINGS_PATH.exists():
        return {"ok": False, "error": "holdings.json missing"}
    data = json.loads(HOLDINGS_PATH.read_text())
    holdings = list(data.get("holdings") or [])
    others = [h for h in holdings if (h.get("account") or "") != account_key]
    prior_acct = [h for h in holdings if (h.get("account") or "") == account_key]

    if not new_rows and not prior_acct:
        return {"ok": True, "wrote": False, "reason": "empty_noop_no_prior", "n": 0}

    merged = others + new_rows
    # recompute totals from all holdings
    total = 0.0
    for h in merged:
        try:
            total += float(h.get("market_value") or 0)
        except (TypeError, ValueError):
            pass
    data["holdings"] = merged
    data.setdefault("portfolio_totals", {})["total_value"] = total
    data["portfolio_totals"]["as_of"] = datetime.now(timezone.utc).isoformat()
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    if dry_run:
        return {"ok": True, "wrote": False, "dry_run": True, "n": len(new_rows), "total": total}

    from holdings_guard import protected_holdings_write
    res = protected_holdings_write(
        data,
        source="alpaca_live_read_sync",
        account_key=account_key,
        protect_basis=False,
        target_path=str(HOLDINGS_PATH),
    )
    return {"ok": True, "wrote": True, "n": len(new_rows), "guard": res, "total": total}


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

    rows = _positions_to_holdings_rows(account_key, positions)
    merge = _merge_account_into_holdings(account_key, rows, dry_run=dry_run)

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
        _telegram(f"✅ Alpaca live read sync OK for {account_key} (n_pos={len(rows)})")

    return {
        "account": account_key,
        "ok": True,
        "n_positions": len(rows),
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
