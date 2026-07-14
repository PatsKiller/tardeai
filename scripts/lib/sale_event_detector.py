"""sale_event_detector — detect broker sells → deploy_events rows (advisory only).

Sources: trade_transactions SELL rows (Schwab + Fidelity/SnapTrade ingest).
Idempotent on event_key derived from dedupe_key or txn id.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATE = PROJECT_ROOT / "data" / "portfolios" / "state"
CLASS_RULES = PROJECT_ROOT / "config" / "asset_classification_rules.json"

SELL_ACTIONS = frozenset({"sell", "sold"})
SKIP_SYMBOLS = frozenset({"CASH", "SPAXX"})
DEFAULT_ACCOUNTS = (
    "schwab_rollover_ira",
    "schwab_taxable",
    "schwab_roth",
    "fidelity_rollover_ira",
)
MIN_PROCEEDS_USD = 500.0


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _instrument_meta(symbol: str) -> dict[str, Any]:
    sym = symbol.upper()
    rules = _load_json(CLASS_RULES, {})
    aliases = {k.upper(): v.upper() for k, v in (rules.get("aliases") or {}).items()}
    sym = aliases.get(sym, sym)
    overrides = {k.upper(): v for k, v in (rules.get("asset_type_overrides") or {}).items()}
    instrument_type = overrides.get(sym, "stock")
    proxy_symbol, proxy_sleeve = None, None
    try:
        from holding_proxies import HOLDING_PROXY_MAP
        if sym in HOLDING_PROXY_MAP:
            proxy_symbol, proxy_sleeve = HOLDING_PROXY_MAP[sym]
        elif instrument_type in ("mutual_fund", "fund"):
            proxy_symbol, proxy_sleeve = "SCHG", "US large-cap blend (fund proxy)"
    except Exception:
        pass
    return {
        "symbol": sym,
        "instrument_type": instrument_type,
        "proxy_symbol": proxy_symbol,
        "proxy_sleeve": proxy_sleeve,
    }


def _is_sell_row(row: dict[str, Any]) -> bool:
    action = str(row.get("action") or "").strip().lower()
    sym = str(row.get("symbol") or "").upper().strip()
    if sym in SKIP_SYMBOLS or not sym:
        return False
    if action in SELL_ACTIONS:
        return True
    return "sell" in action and "short" not in action


def _proceeds(row: dict[str, Any]) -> float:
    try:
        amt = float(row.get("amount") or 0)
    except (TypeError, ValueError):
        amt = 0.0
    if amt:
        return abs(amt)
    try:
        return abs(float(row.get("quantity") or 0) * float(row.get("price") or 0))
    except (TypeError, ValueError):
        return 0.0


def event_key_for_row(row: dict[str, Any]) -> str:
    dk = str(row.get("dedupe_key") or "").strip()
    if dk:
        return f"txn:{dk}"
    tid = row.get("id") or row.get("txn_id")
    if tid:
        return f"txn_id:{tid}"
    acct = row.get("account") or ""
    sym = str(row.get("symbol") or "").upper()
    td = str(row.get("trade_date") or "")[:10]
    amt = round(_proceeds(row), 2)
    return f"fallback:{acct}:{sym}:{td}:{amt}"


def normalize_sell_row(row: dict[str, Any], *, source: str = "live_detect",
                       status: str | None = None, dismiss_reason: str | None = None) -> dict[str, Any]:
    meta = _instrument_meta(str(row.get("symbol") or ""))
    sold_at = row.get("trade_date")
    if isinstance(sold_at, datetime):
        sold_at = sold_at.date()
    elif sold_at and not isinstance(sold_at, date):
        sold_at = date.fromisoformat(str(sold_at)[:10])
    proceeds = _proceeds(row)
    try:
        shares = float(row.get("quantity") or 0)
    except (TypeError, ValueError):
        shares = 0.0
    shares = abs(shares)
    out = {
        "event_key": event_key_for_row(row),
        "symbol": meta["symbol"],
        "account": str(row.get("account") or ""),
        "sold_at": sold_at,
        "proceeds_usd": round(proceeds, 2),
        "shares_sold": round(shares, 6) if shares else None,
        "realized_pnl": row.get("realized_pnl"),
        "instrument_type": meta["instrument_type"],
        "proxy_symbol": meta["proxy_symbol"],
        "proxy_sleeve": meta["proxy_sleeve"],
        "status": status or "open",
        "proceeds_settled": False,
        "cash_visible_usd": None,
        "lookthrough_delta": [],
        "redeploy_plan": [],
        "source": source,
        "txn_ref": row.get("dedupe_key") or str(row.get("id") or ""),
        "txn_id": row.get("id"),
        "dismiss_reason": dismiss_reason,
        "metadata": {
            "description": (str(row.get("description") or ""))[:200] or None,
            "import_source": row.get("import_source"),
        },
    }
    return out


def load_sell_transactions(*, days: int = 730, accounts: tuple[str, ...] | None = None,
                           since: date | None = None) -> list[dict[str, Any]]:
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    accts = accounts or DEFAULT_ACCOUNTS
    start = since or (date.today() - timedelta(days=days))
    cur.execute(
        """SELECT id, trade_date, action, symbol, quantity, price, amount, fees,
                  description, account, import_source, dedupe_key, trade_time
           FROM trade_transactions
           WHERE trade_date >= %s AND account = ANY(%s)
           ORDER BY trade_date, trade_time NULLS LAST, id""",
        (start.isoformat(), list(accts)),
    )
    keys = [d[0] for d in cur.description]
    rows = [dict(zip(keys, r)) for r in cur.fetchall()]
    return [r for r in rows if _is_sell_row(r) and _proceeds(r) >= MIN_PROCEEDS_USD]


def enrich_realized_pnl(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach realized_pnl from FIFO lifecycle aggregation when missing."""
    try:
        from journal_ticker_lifecycle import aggregate_ticker_activity
        norm = [{
            "trade_date": r.get("trade_date"),
            "trade_time": r.get("trade_time"),
            "action": r.get("action"),
            "symbol": r.get("symbol"),
            "quantity": r.get("quantity"),
            "price": r.get("price"),
            "amount": r.get("amount"),
            "account": r.get("account"),
        } for r in rows]
        agg = aggregate_ticker_activity(norm)
        for r in rows:
            sym = str(r.get("symbol") or "").upper()
            td = str(r.get("trade_date") or "")[:10]
            trips = (agg.get(sym) or {}).get("round_trips") or []
            for t in trips:
                if str(t.get("date") or "")[:10] == td:
                    r["realized_pnl"] = t.get("realized_pnl")
                    break
    except Exception:
        pass
    return rows


def _cash_by_account() -> dict[str, float]:
    out: dict[str, float] = {}
    try:
        hold = _load_json(STATE / "holdings.json", {}).get("holdings") or []
        for h in hold:
            if not h.get("is_cash"):
                continue
            acct = str(h.get("account") or "")
            out[acct] = out.get(acct, 0.0) + float(h.get("market_value") or 0)
    except Exception:
        pass
    return out


def attach_cash_snapshot(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cash = _cash_by_account()
    for ev in events:
        acct = str(ev.get("account") or "")
        ev["cash_visible_usd"] = round(cash.get(acct, 0.0), 2) if acct else None
        proc = float(ev.get("proceeds_usd") or 0)
        vis = float(ev.get("cash_visible_usd") or 0)
        if proc > 0 and vis >= proc * 0.85:
            ev["proceeds_settled"] = True
    return events


def detect_sell_events(*, days: int = 14, accounts: tuple[str, ...] | None = None,
                       since: date | None = None, source: str = "live_detect",
                       dismiss_after_days: int | None = None) -> list[dict[str, Any]]:
    """Build normalized deploy event dicts from recent sells (no DB write)."""
    from lib.deploy_events_db import backfill_status_for_date
    raw = load_sell_transactions(days=days, accounts=accounts, since=since)
    raw = enrich_realized_pnl(raw)
    events = []
    for row in raw:
        status, dismiss_reason = "open", None
        if dismiss_after_days is not None:
            sold = row.get("trade_date")
            if isinstance(sold, datetime):
                sold = sold.date()
            elif sold and not isinstance(sold, date):
                sold = date.fromisoformat(str(sold)[:10])
            if sold:
                status, dismiss_reason = backfill_status_for_date(
                    sold, dismiss_after_days=dismiss_after_days)
        ev = normalize_sell_row(row, source=source, status=status, dismiss_reason=dismiss_reason)
        events.append(ev)
    return attach_cash_snapshot(events)


def sync_deploy_events(*, apply: bool = True, days: int = 14, since: date | None = None,
                       source: str = "live_detect", dismiss_after_days: int | None = None,
                       accounts: tuple[str, ...] | None = None) -> dict[str, Any]:
    from db_adapter import _get_conn
    from lib.deploy_events_db import upsert_deploy_event
    events = detect_sell_events(
        days=days, accounts=accounts, since=since, source=source,
        dismiss_after_days=dismiss_after_days,
    )
    report: dict[str, Any] = {
        "applied": apply,
        "source": source,
        "candidates": len(events),
        "upserted": [],
        "errors": [],
    }
    if not apply:
        report["events"] = events
        return report
    conn = _get_conn()
    cur = conn.cursor()
    for ev in events:
        try:
            if apply:
                try:
                    from lib.deploy_intelligence_engine import enrich_event
                    ev = enrich_event(ev)
                except Exception:
                    pass
            report["upserted"].append(upsert_deploy_event(cur, ev))
        except Exception as e:
            report["errors"].append({"event_key": ev.get("event_key"), "error": str(e)[:200]})
    conn.commit()
    report["created"] = sum(1 for u in report["upserted"] if u.get("created"))
    report["updated"] = sum(1 for u in report["upserted"] if not u.get("created"))
    return report