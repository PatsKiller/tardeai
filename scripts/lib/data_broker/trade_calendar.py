"""TradeInView calendar: explicit ET month, stored closed trips and dated events."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timezone

from lib.data_broker import tradeinview_sources as src

SCHEMA = "TradeCalendar@v1"


def one(query: dict, key: str, default=None):
    value = query.get(key, default)
    return value[0] if isinstance(value, list) and value else value


def build_calendar(snapshot: dict, query: dict, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    raw_month = str(one(query, "month") or "")
    try:
        first = date.fromisoformat(raw_month + "-01")
        if first.strftime("%Y-%m") != raw_month:
            raise ValueError
    except ValueError:
        return {"ok": False, "schema": SCHEMA, "error": "explicit_month_required",
                "reason": "month must be YYYY-MM; no implicit 30-day history window"}
    scope = str(one(query, "names", "held_watch"))
    if scope not in ("held", "held_watch"):
        return {"ok": False, "schema": SCHEMA, "error": "invalid_names_scope"}
    raw_account = str(one(query, "account") or "")
    acct = src.account(raw_account)["account_id"] if raw_account else None
    if raw_account and acct is None:
        return {"ok": False, "schema": SCHEMA, "error": "account_not_identified"}
    trips, gaps = src.normalise_closed(snapshot)
    complete = src.coverage(snapshot, ("schwab_round_trips", "trade_closed"))
    # A missing date prevents a trustworthy monthly total, rather than being
    # silently dropped from the month which it might belong to.
    undated = [r for r in trips if not r.get("exit_date")]
    if undated:
        complete = {"status": "PARTIAL", "missing_sources": complete["missing_sources"],
                    "reasons": [*complete["reasons"], "closed trips have no usable exit date"]}
        gaps.append({"source": "closed trips", "reason": "exit dates missing", "count": len(undated)})
    selected = [r for r in trips if (r.get("exit_date") or "").startswith(raw_month + "-")
                and (not acct or r.get("account_id") == acct)]
    events, event_gaps = _events(snapshot, raw_month, scope)
    gaps += event_gaps
    days = []
    for n in range(1, calendar.monthrange(first.year, first.month)[1] + 1):
        d = date(first.year, first.month, n).isoformat()
        rows = [r for r in selected if r["exit_date"] == d]
        stats = src.trip_stats(rows, complete=complete["status"] == "COMPLETE")
        symbols = []
        for sym in sorted({r["symbol"] for r in rows}):
            group = [r for r in rows if r["symbol"] == sym]
            agg = src.trip_stats(group, complete=complete["status"] == "COMPLETE")
            symbols.append({"symbol": sym, "realized_pl": agg["realized_pl"],
                            "known_realized_pl": agg["known_realized_pl"], "trade_count": agg["round_trip_count"]})
        days.append({"date": d, "realized_pl": stats["realized_pl"],
                     "known_realized_pl": stats["known_realized_pl"], "trade_count": stats["round_trip_count"],
                     "known_trade_count": len(rows), "unpriced_trade_count": stats["unpriced_trade_count"],
                     "symbols": symbols, "trades": rows, "events": [e for e in events if e["date"] == d],
                     "heat_intensity": None, "coverage": complete})
    magnitude = max((abs(d["realized_pl"]) for d in days if d["realized_pl"] is not None), default=0)
    for d in days:
        if d["realized_pl"] is not None:
            d["heat_intensity"] = abs(d["realized_pl"]) / magnitude if magnitude else 0
    weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(first.year, first.month):
        dates = [date(first.year, first.month, n).isoformat() if n else None for n in week]
        rows = [r for r in selected if r["exit_date"] in dates]
        stats = src.trip_stats(rows, complete=complete["status"] == "COMPLETE")
        valid = [d for d in dates if d]
        weeks.append({"start_date": valid[0], "end_date": valid[-1], "days": dates[:5],
                      "included_dates": dates, "realized_pl": stats["realized_pl"],
                      "known_realized_pl": stats["known_realized_pl"], "trade_count": stats["round_trip_count"],
                      "known_trade_count": len(rows), "coverage": complete})
    stats = src.trip_stats(selected, complete=complete["status"] == "COMPLETE")
    active = sum(bool(d["known_trade_count"]) for d in days)
    all_priced = complete["status"] == "COMPLETE" and stats["unpriced_trade_count"] == 0
    accounts = {r.get("account_id"): r.get("account_label") for r in trips if r.get("account_id")}
    non_grid = [d for d in days if date.fromisoformat(d["date"]).weekday() >= 5
                and (d["known_trade_count"] or d["events"])]
    if non_grid:
        gaps.append({"source": "calendar", "reason": "recorded activity outside weekday grid",
                     "dates": [d["date"] for d in non_grid]})
    return {"ok": True, "schema": SCHEMA, "as_of": now.isoformat(), "month": raw_month,
            "account": acct, "names": scope,
            "summary": {"realized_pl": stats["realized_pl"], "known_realized_pl": stats["known_realized_pl"],
                        "trade_count": stats["round_trip_count"], "known_trade_count": len(selected),
                        "green_days": sum(d["realized_pl"] > 0 for d in days if d["realized_pl"] is not None)
                            if all_priced else None,
                        "active_days": active if complete["status"] == "COMPLETE" else None,
                        "known_active_days": active, "unpriced_trade_count": stats["unpriced_trade_count"],
                        "coverage": complete},
            "days": days, "weeks": weeks, "non_grid_days": non_grid, "events": events,
            "account_options": [{"id": k, "label": v} for k, v in sorted(accounts.items())],
            "gaps": gaps, "provider_calls": 0, "writes": 0, "read_only": True}


def _events(snapshot: dict, month: str, scope: str) -> tuple[list[dict], list[dict]]:
    holdings = src.file_document(snapshot, "holdings")
    held = {src.symbol(r.get("symbol")) for r in holdings.get("holdings") or []
            if (src.number(r.get("shares", r.get("quantity"))) or 0) > 0 and not r.get("is_cash")}
    watch = set(((snapshot.get("operator_membership") or {}).get("names") or {}))
    names = held | watch if scope == "held_watch" else held
    gaps = [g] if (g := src.source_gap(snapshot, "catalyst_events")) else []
    events = []
    for row in src.source_rows(snapshot, "catalyst_events"):
        sym = src.symbol(row.get("symbol"))
        kind = str(row.get("event_type") or row.get("catalyst_type") or "").lower().replace("-", "_")
        event_type = kind if kind in ("earnings", "catalyst", "ex_dividend", "wash_sale", "macro") else "other"
        if event_type != "macro" and sym not in names:
            continue
        event_date = src.day(row.get("event_date") or row.get("scheduled_at"))
        basis = "stored event date"
        if not event_date and event_type in ("catalyst", "other"):
            event_date = src.day(row.get("published_at"))
            basis = "publication date; event date not recorded"
        if not event_date:
            gaps.append({"source": "catalyst_events", "reason": "event date not recorded",
                         "symbol": sym or None, "record_id": row.get("id")})
            continue
        if not event_date.startswith(month + "-"):
            continue
        title = row.get("headline") or row.get("title")
        if not title:
            gaps.append({"source": "catalyst_events", "reason": "event title missing", "record_id": row.get("id")})
            continue
        events.append({"id": "catalyst:" + str(row.get("event_guid") or row.get("id")),
                       "type": event_type, "source_event_type": kind or None, "symbol": sym or None,
                       "title": str(title), "date": event_date, "date_basis": basis,
                       "source": row.get("source"), "source_ref": row.get("source_url"),
                       "as_of": src.iso(row.get("updated_at") or row.get("created_at")),
                       "missing_reason": None if row.get("source") else "origin source not recorded"})
    if not events and not gaps:
        gaps.append({"source": "catalyst_events", "reason": "no dated events on file for selected names/month"})
    # A wash-sale endpoint is not reconstructed from a loss plus a guessed
    # duration. Only an actual stored window end may be surfaced here.
    desk = src.file_document(snapshot, "reentry")
    for row in desk.get("rows") or []:
        sym = src.symbol(row.get("symbol"))
        end = src.day(row.get("wash_until"))
        if sym not in names or not end or not end.startswith(month + "-"):
            continue
        events.append({"id": "wash-sale:" + sym + ":" + end, "type": "wash_sale", "symbol": sym,
                       "title": "Stored wash-sale window ends", "date": end,
                       "source": "reentry_decision_desk_latest.json", "source_ref": None,
                       "as_of": src.iso(desk.get("computed_at")), "missing_reason": None})
    return events, gaps


def get_calendar(query: dict | None = None) -> dict:
    q = query or {}
    return build_calendar(src.collect_snapshot(kind="calendar", query=q), q)
