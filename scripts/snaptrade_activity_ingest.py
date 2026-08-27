#!/usr/bin/env python3
"""snaptrade_activity_ingest.py — ingest read-only Fidelity/SnapTrade activity into the local trade_transactions table.

"Read-only" describes the SnapTrade/Fidelity side only (audit finding L3, docs/audits/
CIO_PLATFORM_AUDIT_2026-08-27.md: never confirmed as a blanket claim — this script does write
local DB state). SnapTrade holdings sync is positions/basis only. This script fills the missing
ledger side for mapped Fidelity accounts: buys, sells, dividends, interest, and cash movements.
It is dry-run by default and writes only to the local `trade_transactions` table with --apply.
It never submits broker orders and never mutates anything on the SnapTrade/Fidelity side.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "brokers"))

ACCOUNTS_MAP_PATH = PROJECT_ROOT / "config" / "snaptrade_accounts.json"


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _load_account_map() -> dict[str, str]:
    if not ACCOUNTS_MAP_PATH.exists():
        return {}
    try:
        cfg = json.loads(ACCOUNTS_MAP_PATH.read_text())
        raw = cfg.get("accounts", cfg) if isinstance(cfg, dict) else {}
        return {str(k): str(v) for k, v in raw.items()}
    except Exception:
        return {}


def _pick(d: dict, *keys):
    for k in keys:
        if k in d and d.get(k) not in (None, ""):
            return d.get(k)
    return None


def _num(v, default=0.0) -> float:
    try:
        if isinstance(v, str):
            v = re.sub(r"[$,+]", "", v).strip()
        return float(v)
    except (TypeError, ValueError):
        return default


def _date(raw) -> str:
    s = str(raw or "")[:10]
    return s if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else dt.date.today().isoformat()


def _time(raw) -> str | None:
    s = str(raw or "")
    return s or None


def _symbol(activity: dict) -> str:
    for obj in (activity.get("symbol"), activity.get("instrument"), activity.get("security")):
        if isinstance(obj, dict):
            v = _pick(obj, "symbol", "raw_symbol", "ticker")
            if v:
                return str(v).upper().strip()
        elif obj:
            return str(obj).upper().strip()
    desc = str(_pick(activity, "description", "name", "type") or "")
    m = re.search(r"\(([A-Z][A-Z0-9.\-]{0,9})\)", desc)
    return m.group(1).upper() if m else "CASH"


def _description(activity: dict) -> str:
    return str(_pick(activity, "description", "name", "type", "transaction_type") or "")[:120]


def _activity_id(activity: dict) -> str:
    return str(_pick(activity, "id", "activity_id", "transaction_id", "trade_id") or "")[:120]


# SnapTrade structured activity types → trade_transactions actions. Checked before the description
# heuristics: fund names like "SCHWAB US DIVIDEND EQUITY ETF" otherwise misclassify a BUY as Dividend.
_TYPE_ACTIONS = {
    "BUY": "Buy",
    "SELL": "Sell",
    "DIVIDEND": "Dividend",
    "INTEREST": "Interest",
    "REI": "Reinvested Dividend",
    "DIVIDEND_REINVESTMENT": "Reinvested Dividend",
}


def _classify(activity: dict) -> str:
    typ = str(_pick(activity, "type", "transaction_type", "activity_type") or "").strip().upper()
    mapped = _TYPE_ACTIONS.get(typ) or _TYPE_ACTIONS.get(typ.replace(" ", "_"))
    if mapped:
        return mapped
    if typ in ("CONTRIBUTION", "EXTERNAL_TRANSFER_IN", "TRANSFER_IN"):
        return "Cash Receipt"
    if typ in ("WITHDRAWAL", "EXTERNAL_TRANSFER_OUT", "TRANSFER_OUT"):
        return "Cash Transfer"
    raw = " ".join(str(_pick(activity, k) or "") for k in (
        "type", "transaction_type", "activity_type", "description", "name",
    )).upper()
    if ("REINVEST" in raw or "DRIP" in raw) and ("DIVIDEND" in raw or "DISTRIBUTION" in raw):
        return "Reinvested Dividend"
    if "DIVIDEND" in raw or "DISTRIBUTION" in raw:
        return "Dividend"
    if "INTEREST" in raw:
        return "Interest"
    if "SELL" in raw or "SOLD" in raw:
        return "Sell"
    if "BUY" in raw or "BOUGHT" in raw:
        return "Buy"
    if "TRANSFER" in raw or "ROLLOVER" in raw:
        return "Cash Receipt" if _num(_pick(activity, "amount", "net_amount", "netAmount")) >= 0 else "Cash Transfer"
    return "Activity"


def normalize_activity(activity: dict, account_key: str) -> dict | None:
    """Map a SnapTrade activity dict to the trade_transactions row shape."""
    action = _classify(activity)
    desc = _description(activity)
    sym = _symbol(activity)
    qty = abs(_num(_pick(activity, "units", "quantity", "qty", "shares")))
    price = _num(_pick(activity, "price", "trade_price", "execution_price"), 0.0)
    amount = _num(_pick(activity, "amount", "net_amount", "netAmount", "cash_amount", "value"), 0.0)
    fees = abs(_num(_pick(activity, "fees", "fee", "commission"), 0.0))
    if action in ("Dividend", "Interest", "Cash Receipt", "Cash Transfer"):
        qty = 0.0
        price = 0.0
        if sym == "CASH" and action == "Dividend":
            m = re.search(r"\(([A-Z][A-Z0-9.\-]{0,9})\)", desc)
            if m:
                sym = m.group(1).upper()
    if action == "Reinvested Dividend":
        if price <= 0 and qty > 0 and amount:
            price = abs(amount) / qty
        if sym == "CASH":
            m = re.search(r"\(([A-Z][A-Z0-9.\-]{0,9})\)", desc)
            if m:
                sym = m.group(1).upper()
    if action in ("Buy", "Sell") and (not sym or sym == "CASH") and qty <= 0:
        return None
    uid = _activity_id(activity)
    if not uid:
        uid = f"snap:{account_key}:{_date(_pick(activity, 'trade_date', 'date', 'settlement_date', 'time'))}:{action}:{sym}:{qty:g}:{amount:g}:{desc[:30]}"
    return {
        "trade_date": _date(_pick(activity, "trade_date", "date", "settlement_date", "time", "created_at")),
        "action": action,
        "symbol": sym or "CASH",
        "quantity": round(qty, 3),
        "price": round(price, 4),
        "amount": round(amount, 2),
        "fees": round(fees, 2),
        "description": desc,
        "account": account_key,
        "uid": uid,
        "trade_time": _time(_pick(activity, "time", "trade_date", "date", "created_at")),
    }


def _dedupe_key(r: dict) -> str:
    return f"{r['trade_date']}|{r['action']}|{r['symbol']}|{float(r['quantity']):.3f}|{r['account']}|{r['uid']}"


def run(apply: bool = False, days: int = 45) -> dict:
    from brokers import snaptrade_credentials as creds
    from brokers import snaptrade_read as sr

    if not creds.status().get("ready"):
        return {"ok": False, "error": "client keys not set"}
    if not creds.user_status().get("ready"):
        return {"ok": False, "error": "no connected SnapTrade user"}
    acct_map = _load_account_map()
    if not acct_map:
        return {"ok": False, "error": f"no account mapping in {ACCOUNTS_MAP_PATH}"}

    user = sr.SnapTradeUser.from_env()
    accounts = sr.list_accounts(user)
    start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).date().isoformat()
    end = dt.datetime.now(dt.timezone.utc).date().isoformat()
    rows: list[dict] = []
    report = {"accounts": {}, "rows_total": 0, "by_action": {}, "window_start": start}
    for a in accounts:
        aid = str(a.get("id") or a.get("account_id") or "")
        key = acct_map.get(aid)
        if not key:
            continue
        try:
            acts = sr.activities(user, aid, start=start, end=end)
        except Exception as e:
            report["accounts"][key] = {"error": str(e)[:160]}
            continue
        mapped = [r for r in (normalize_activity(x, key) for x in acts or []) if r]
        rows.extend(mapped)
        report["accounts"][key] = {"mapped": len(mapped), "by_action": dict(collections.Counter(r["action"] for r in mapped))}

    report["rows_total"] = len(rows)
    report["by_action"] = dict(collections.Counter(r["action"] for r in rows))
    if not rows:
        report["mode"] = "no rows"
        return report

    conn = _conn()
    cur = conn.cursor()
    accounts_in_scope = sorted({r["account"] for r in rows})
    cur.execute("""SELECT count(*) FROM trade_transactions WHERE account = ANY(%s) AND trade_date >= %s""",
                (accounts_in_scope, start))
    report["existing_in_window"] = cur.fetchone()[0]
    if apply:
        cur.execute("""DELETE FROM trade_transactions
                       WHERE account = ANY(%s) AND trade_date >= %s AND import_source='snaptrade_activity'""",
                    (accounts_in_scope, start))
        report["deleted"] = cur.rowcount
        for r in rows:
            cur.execute("""INSERT INTO trade_transactions
                             (trade_date, action, symbol, quantity, price, amount, fees, description,
                              account, import_source, dedupe_key, trade_time)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'snaptrade_activity',%s,%s)
                           ON CONFLICT (dedupe_key) DO UPDATE SET price=EXCLUDED.price,
                             quantity=EXCLUDED.quantity, amount=EXCLUDED.amount, fees=EXCLUDED.fees,
                             description=EXCLUDED.description, trade_time=EXCLUDED.trade_time""",
                        (r["trade_date"], r["action"], r["symbol"], r["quantity"], r["price"], r["amount"],
                         r["fees"], r["description"], r["account"], _dedupe_key(r), r.get("trade_time")))
        conn.commit()
        report["inserted"] = len(rows)
    conn.close()
    report["mode"] = "APPLIED" if apply else "DRY-RUN (no writes)"
    return report


def main():
    ap = argparse.ArgumentParser(description="SnapTrade/Fidelity read-only activity ingest.")
    ap.add_argument("--apply", action="store_true", help="write mapped activities to trade_transactions")
    ap.add_argument("--days", type=int, default=45)
    args = ap.parse_args()
    out = run(apply=args.apply, days=args.days)
    print(json.dumps(out, indent=2, default=str))
    sys.exit(0 if out.get("error") is None else 1)


if __name__ == "__main__":
    main()
