"""Historical TradeInView replay from stored facts only; never provider fallback."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json

from lib.data_broker import tradeinview_sources as src
from lib.data_broker.trade_calendar import one

SCHEMA = "TradeReplay@v1"


def _trip(snapshot, ident):
    if ident.startswith("journal:"):
        from lib.data_broker.holding_history import history_trips
        trips, gaps = history_trips(snapshot)
    else:
        trips, gaps = src.normalise_closed(snapshot)
    found = next((r for r in trips if r["trade_id"] == ident), None)
    if found or not ident.startswith("open:"):
        return found, gaps
    for row in src.file_document(snapshot, "holdings").get("holdings") or []:
        acct = src.account(row.get("account") or row.get("account_id"))
        sym = src.symbol(row.get("symbol"))
        if ident != f"open:{acct['account_id']}:{sym}" or row.get("is_cash"):
            continue
        qty = src.number(row.get("shares", row.get("quantity")))
        if qty is None or qty <= 0:
            continue
        price = src.number(row.get("avg_cost"))
        return {"trade_id": ident, "symbol": sym, **acct, "entry_at": None, "exit_at": None,
                "entry_date": None, "exit_date": None, "entry_price": price, "exit_price": None,
                "shares": qty, "realized_pl": None, "return_pct": None, "hold_days": None,
                "hold_days_basis": None, "basis_unknown": price is None or bool(row.get("basis_partial")),
                "basis_reason": "opening fill and complete basis not established from current holdings",
                "source": "holdings_accounts", "provenance": [{"source": "holdings_accounts",
                    "record_id": ident, "observed_at": src.iso(row.get("provider_observed_at")),
                    "writer": "holdings_accounts canonical producer"}]}, gaps
    return None, gaps


def collect_inputs(snapshot, query, database, root, now):
    """Additional bounded SELECT/file reads; caller supplies the same read seam."""
    trip, _ = _trip(snapshot, str(one(query, "trade_id") or ""))
    if not trip:
        return
    sym = trip["symbol"]
    start = trip.get("entry_date") or (now.date() - timedelta(days=90)).isoformat()
    end = trip.get("exit_date") or now.date().isoformat()
    # A daily bar is a session observation. Padding avoids dropping a stored
    # midnight UTC bar; the pure builder applies the actual holding-day bounds.
    lower = date.fromisoformat(start) - timedelta(days=1)
    upper = date.fromisoformat(end) + timedelta(days=2)
    queries = (
        ("market_ohlcv_bars", "SELECT bar_time AS time,open,high,low,close,volume FROM market_ohlcv_bars "
         "WHERE upper(symbol)=%s AND timeframe='daily' AND bar_time >= %s AND bar_time < %s "
         "ORDER BY bar_time LIMIT 5001"),
        ("ticker_prices", "SELECT price_date AS time,close_price AS close FROM ticker_prices "
         "WHERE upper(symbol)=%s AND price_date >= %s AND price_date < %s ORDER BY price_date LIMIT 5001"),
    )
    for table, sql in queries:
        try:
            rows = database(sql, (sym, lower.isoformat(), upper.isoformat()))
            if rows is None:
                raise ValueError("stored SELECT unavailable")
            snapshot["replay_bars"] = {"status": "ok", "table": table, "rows": rows[:5000],
                                        "truncated": len(rows) > 5000}
            if rows:
                break
        except Exception as exc:
            snapshot["replay_bars"] = {"status": "missing", "table": table,
                                        "reason": type(exc).__name__, "rows": []}
    for name, sql in (
        ("stop_last_known", "SELECT account,symbol,order_id,stop_price,status,captured_at FROM stop_last_known "
         "WHERE upper(symbol)=%s ORDER BY captured_at LIMIT 5001"),
    ):
        try:
            rows = database(sql, (sym,))
            if rows is None:
                raise ValueError("stored SELECT unavailable")
            snapshot["sources"][name] = {"status": "ok", "rows": rows[:5000], "truncated": len(rows) > 5000}
        except Exception as exc:
            snapshot["sources"][name] = {"status": "missing", "reason": type(exc).__name__, "rows": []}
    path = root / "data/cio/cio_opportunity_assessments.jsonl"
    try:
        if path.stat().st_size > 32_000_000:
            raise ValueError("CIO history exceeds read bound")
        rows = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                if row.get("symbol") == sym:
                    rows.append(row)
        snapshot["sources"]["cio_opportunity_history"] = {"status": "ok", "rows": rows[-5000:],
                                                          "truncated": len(rows) > 5000}
    except (OSError, ValueError) as exc:
        snapshot["sources"]["cio_opportunity_history"] = {"status": "missing", "rows": [],
                                                          "reason": type(exc).__name__}


def _coordinate(value):
    """Chart day coordinate is not an invented observation timestamp."""
    d = src.day(value)
    return (d, int(datetime.combine(date.fromisoformat(d), time(), timezone.utc).timestamp())) if d else (None, None)


def _within(trip, value):
    day = src.day(value)
    if not day or not trip.get("entry_date"):
        return False
    at, start, end = src.instant(value), src.instant(trip.get("entry_at")), src.instant(trip.get("exit_at"))
    if at is not None and start is not None and at < start:
        return False
    if at is not None and end is not None and at > end:
        return False
    return day >= trip["entry_date"] and (not trip.get("exit_date") or day <= trip["exit_date"])


def build_replay(snapshot, query, *, now=None):
    now = now or datetime.now(timezone.utc)
    ident = str(one(query, "trade_id") or "")
    interval = str(one(query, "interval", "1D"))
    trip, gaps = _trip(snapshot, ident)
    empty_stats = {"max_gain_pct": None, "max_drawdown_pct": None,
        "metrics_basis": "not measured", "metrics_missing_reason": "stored holding-range bars unavailable",
        "exit_kind": "unknown", "exit_label": "Unknown", "exit_basis": "fill does not declare exit type",
        "coach_note": None}
    out = {"ok": trip is not None, "schema": SCHEMA, "as_of": snapshot.get("as_of") or now.isoformat(), "trade_id": ident,
        "trade": trip, "symbol": trip["symbol"] if trip else "", "account_id": trip.get("account_id") if trip else None,
        "account_label": trip.get("account_label") if trip else None, "interval": interval,
        "available_intervals": [], "kind": "none", "bars": [], "markers": [], "stats": empty_stats,
        "source": {"table": None, "as_of": None, "stored_only": True, "bar_basis": "stored bars only"},
        "gaps": gaps, "provider_calls": 0, "writes": 0, "read_only": True}
    if not trip:
        return dict(out, error="recorded_trade_not_found")
    source = snapshot.get("replay_bars") or {}
    bars = []
    for row in source.get("rows") or []:
        # Daily bar_time is the stored session key, not an execution instant:
        # midnight UTC must not move to the preceding ET trading day.
        value = row.get("time")
        bar_day = value.date().isoformat() if isinstance(value, datetime) else str(value or "")[:10]
        day, coord = _coordinate(bar_day)
        close = src.number(row.get("close"))
        if not day or close is None or close <= 0:
            continue
        bar = {"time": day, "t": coord, "close": close,
               "observed_at": src.iso(row.get("time"))}
        bar.update({key: src.number(row.get(key)) for key in ("open", "high", "low", "volume")})
        bars.append(bar)
    bars.sort(key=lambda r: r["time"])
    out["available_intervals"] = ["1D"] if bars else []
    if interval != "1D":
        return dict(out, ok=False, error="interval_not_stored")
    out["bars"] = bars
    candles = bool(bars) and all(all(b[k] is not None and b[k] > 0 for k in ("open", "high", "low"))
                                and b["low"] <= min(b["open"], b["close"])
                                and b["high"] >= max(b["open"], b["close"]) for b in bars)
    out["kind"] = "candles" if candles else "closes" if bars else "none"
    out["source"].update(table=source.get("table"), as_of=(bars[-1]["observed_at"] or bars[-1]["time"]) if bars else None,
        bar_basis="daily session OHLC; not tick or intraday execution prices" if candles else "recorded daily closes only")
    if not bars or source.get("status") != "ok" or source.get("truncated"):
        gaps.append({"source": source.get("table") or "stored bars",
                     "reason": "stored bar coverage missing or truncated"})
    for kind, at_key, day_key, price_key in (("buy", "entry_at", "entry_date", "entry_price"),
                                            ("sell", "exit_at", "exit_date", "exit_price")):
        day, coord = _coordinate(trip.get(at_key) or trip.get(day_key))
        price = trip.get(price_key)
        if day and price is not None:
            out["markers"].append({"time": day, "t": coord, "kind": kind, "label": kind.title() + " fill",
                "price": price, "source": trip["source"], "at": trip.get(at_key),
                "date_basis": "recorded fill timestamp" if trip.get(at_key) else "recorded fill date only"})
    for name in ("stop_last_known", "cio_opportunity_history"):
        if gap := src.source_gap(snapshot, name):
            gaps.append(gap)
    for row in src.source_rows(snapshot, "stop_last_known"):
        if src.symbol(row.get("symbol")) != trip["symbol"]:
            continue
        if src.account(row.get("account"))["account_id"] != trip.get("account_id"):
            continue
        day, coord = _coordinate(row.get("captured_at"))
        if day and _within(trip, row.get("captured_at")):
            out["markers"].append({"time": day, "t": coord, "kind": "stop", "label": "Observed stop",
                "price": src.number(row.get("stop_price")), "source": "stop_last_known",
                "at": src.iso(row.get("captured_at")), "record_id": row.get("order_id")})
    for row in src.source_rows(snapshot, "cio_opportunity_history"):
        if src.symbol(row.get("symbol")) != trip["symbol"]:
            continue
        day, coord = _coordinate(row.get("written_at"))
        assessment = row.get("assessment") or {}
        if day and _within(trip, row.get("written_at")):
            label = "CIO " + str(assessment.get("stance") or "stance unavailable")
            if (conv := src.number(assessment.get("conviction"))) is not None:
                label += f" · conviction {conv:g}"
            out["markers"].append({"time": day, "t": coord, "kind": "cio", "label": label,
                "price": None, "source": "cio_opportunity_assessments.jsonl", "at": src.iso(row.get("written_at"))})
    entry = trip.get("entry_price")
    held = [b for b in bars if trip.get("entry_date") and b["time"] >= trip["entry_date"]
            and b["time"] <= (trip.get("exit_date") or src.day(now))]
    if held and entry is not None and entry > 0 and not trip.get("basis_unknown") and not source.get("truncated"):
        highs = [b["high"] if candles else b["close"] for b in held]
        lows = [b["low"] if candles else b["close"] for b in held]
        out["stats"].update(max_gain_pct=round((max(highs) / entry - 1) * 100, 4),
            max_drawdown_pct=round(min(0, (min(lows) / entry - 1) * 100), 4),
            metrics_basis="MFE/MAE relative to recorded entry; available daily session-range proxy" if candles else
                "MFE/MAE relative to recorded entry; available daily close-only proxy; intraday extremes unavailable",
            metrics_missing_reason=None)
    # Classification is an originating recorded fact; mark crossing a stop does
    # not prove that an order filled. No price-proximity exit-type guessing.
    recorded = str(trip.get("classification") or "").strip().lower()
    if recorded in ("stop", "stop_loss", "target", "manual"):
        kind = "stop" if recorded.startswith("stop") else recorded
        out["stats"].update(exit_kind=kind, exit_label=kind.title(), exit_basis="recorded trip classification")
    return out


def get_replay(query=None):
    query = query or {}
    ident = str(one(query, "trade_id") or "")
    if not ident or len(ident) > 1024:
        return {"ok": False, "schema": SCHEMA, "error": "recorded_trade_id_required"}
    return build_replay(src.collect_snapshot(kind="replay", query=query), query)
