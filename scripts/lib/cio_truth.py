"""CIO display truth over existing registered projections; no store or authority.

All functions are read-only. Callers may inject projections for fixture rendering.
Missing evidence stays None with a reason. No provider, broker or execution calls.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import hashlib
import re
import math
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .account_display import canonical_key, account_label, location_facts
from .stop_session_evidence import stop_observation_freshness


def _number(value) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _timestamp(value) -> datetime | None:
    if value is None:
        return None
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _evidence(source, as_of, now, *, reason=None, max_age_h=26) -> dict:
    at = _timestamp(as_of)
    age = (now - at).total_seconds() / 3600 if at else None
    return {"source": source, "as_of": at.isoformat() if at else None,
            "age_hours": round(age, 3) if age is not None else None,
            "stale": age is None or age < 0 or age > max_age_h,
            "gap": {"reason": reason} if reason else None}


def _sum_known(rows, key) -> float | None:
    values = [_number(r.get(key)) for r in rows]
    return round(sum(values), 2) if all(v is not None for v in values) else None


def _holdings_clock(value, source_field) -> dict:
    """Normalize the holdings writer's explicit ET format; never infer a zone.

    Legacy ``... ET`` means America/New_York, including the date's DST offset.
    Other naive values, invalid values and ambiguous DST wall times stay gaps.
    """
    result = {"source_field": source_field, "raw": value, "as_of": None,
              "timezone": None, "gap": None}
    try:
        explicit_et = isinstance(value, str) and value.endswith(" ET")
        text = value[:-3] if explicit_et else value
        dt = text if isinstance(text, datetime) else datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        if explicit_et:
            if dt.tzinfo:
                raise ValueError("conflicting offset and ET suffix")
            zone = ZoneInfo("America/New_York")
            a, b = dt.replace(tzinfo=zone, fold=0), dt.replace(tzinfo=zone, fold=1)
            if a.utcoffset() != b.utcoffset():
                raise ValueError("ambiguous or nonexistent ET wall time")
            dt = a
            result["timezone"] = "America/New_York (explicit legacy ET suffix)"
        elif dt.tzinfo is None:
            raise ValueError("holdings clock requires an explicit timezone")
        else:
            result["timezone"] = "explicit UTC offset"
        result["as_of"] = dt.isoformat()
    except (TypeError, ValueError) as exc:
        result["gap"] = {"reason": "holdings clock unavailable" if value in (None, "") else str(exc)}
    return result



def _position_clock(row: dict, now: datetime) -> dict:
    """Only explicitly named position/provider observations can date a row.

    Generic updated_at/as_of fields also describe loader/valuation writes. Their
    producer must declare observation semantics before they can date positions.
    Date-only observations retain their raw evidence but have no known instant.
    """
    observation = row.get("observation") if isinstance(row.get("observation"), dict) else {}
    candidates = [(key, row.get(key)) for key in ("broker_position_as_of_at", "provider_observed_at")]
    candidates += [("observation.provider_observed_at", observation.get("provider_observed_at")),
                   ("broker_position_as_of", row.get("broker_position_as_of"))]
    field, value = next(((k, v) for k, v in candidates if v not in (None, "")), (None, None))
    if field is None:
        field = next((k for k in ("updated_at", "as_of") if row.get(k)), None)
        return {"source_field": field, "raw": row.get(field) if field else None,
                "as_of": None, "timezone": None, "status": "UNKNOWN",
                "gap": {"reason": "no declared position observation instant; generic updated_at/as_of is insufficient"}}
    out = _holdings_clock(value, field)
    if out["as_of"]:
        out["as_of"] = _timestamp(out["as_of"]).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if out["as_of"] and _timestamp(out["as_of"]) > now:
        out.update(as_of=None, gap={"reason": "position observation is in the future relative to evaluation clock"})
    out["status"] = "KNOWN" if out["as_of"] else "UNKNOWN"
    return out


def _position_clock_aggregate(rows: list[dict]) -> dict:
    """Oldest observed row dates the whole set only when EVERY row is observed."""
    clocks = [r["position_clock"] for r in rows]
    known = sorted((c["as_of"] for c in clocks if c["as_of"]), key=_timestamp)
    unknown = len(clocks) - len(known)
    complete = bool(rows) and unknown == 0
    return {"source_field": "holdings[].position_clock", "raw": None,
            "as_of": known[0] if complete else None, "status": "KNOWN" if complete else "UNKNOWN",
            "aggregation": "oldest row; unknown if any row lacks a declared observation instant",
            "known_rows": len(known), "unknown_rows": unknown,
            "oldest_known_as_of": known[0] if known else None,
            "newest_known_as_of": known[-1] if known else None,
            "mixed": len(set(known)) > 1, "complete": complete,
            "gap": None if complete else {"reason": f"{unknown} row(s) lack a declared position observation instant"
                                           if rows else "no position rows observed"}}


def _worthless_delisted(row: dict) -> bool:
    """A delisted holding carried at exactly $0 with no positive mark."""
    if not row.get("delisted"):
        return False
    value, price = _number(row.get("market_value")), _number(row.get("price"))
    return value == 0 and (price is None or price == 0)


def _day_coverage(rows) -> dict:
    """Sum of the KNOWN day changes plus what was left out, by row and value.

    One holding without a day change used to make the whole figure None, so a
    single unpriced line blanked TODAY for every account. The known part is a
    real number; the unknown part is reported beside it, never guessed.
    """
    known = [r for r in rows if _number(r.get("day_change")) is not None]
    unknown = [r for r in rows if _number(r.get("day_change")) is None]
    return {"known_usd": round(sum(_number(r["day_change"]) for r in known), 2) if known else None,
            "complete": bool(rows) and not unknown,
            "known_rows": len(known), "unknown_rows": len(unknown),
            "unknown_value_usd": _sum_known(unknown, "market_value") if unknown else 0.0,
            "unknown_accounts": sorted({r.get("account_id") or "" for r in unknown} - {""})}


def portfolio_for(holdings_doc: dict, *, now: datetime | None = None) -> dict:
    """One holdings aggregate for every display, including all account rows.

    Total/value/day P&L come from holdings rows, not stale account summaries or
    another quote clock. A missing non-cash day change is unknown, not zero:
    the day figure is the sum of the known rows, flagged incomplete, with the
    unknown rows and their value named (``day_pl_coverage``).
    Position count is distinct held account+symbol, non-cash, value >= $100.
    """
    from .portfolio_positions import is_cash
    now = now or datetime.now(timezone.utc)
    rows = []
    for raw in holdings_doc.get("holdings") or []:
        r = deepcopy(raw)
        r["account_id"] = canonical_key(r.get("account") or r.get("account_id"))
        r["account_label"] = account_label(r["account_id"])
        r["is_cash"] = is_cash(r)
        if r["is_cash"] and r.get("day_change") is None:
            r["day_change"] = 0.0
        elif r.get("day_change") is None and _worthless_delisted(r):
            # A delisted line carried at $0 with no mark cannot move: its day
            # change is a known zero, not an unknown. A morning broker reload
            # re-adds these rows without a day_change, and one of them used to
            # blank TODAY for the whole book (2026-10-26).
            r["day_change"] = 0.0
            r["day_change_basis"] = "delisted_zero_value"
        r["position_clock"] = _position_clock(r, now)
        rows.append(r)
    total = _sum_known(rows, "market_value") if rows else None
    cash = _sum_known([r for r in rows if r["is_cash"]], "market_value") if rows else None
    day_cov = _day_coverage(rows)
    day = day_cov["known_usd"]
    clocks = {"positions": _position_clock_aggregate(rows),
              "position_list": _holdings_clock(holdings_doc.get("positions_built_at"), "positions_built_at"),
              "valuation": _holdings_clock(holdings_doc.get("generated_at"), "generated_at"),
              "quote": _holdings_clock(holdings_doc.get("last_repriced"), "last_repriced"),
              "day_pnl": {"source_field": "holdings[].day_change", "as_of": None, "status": "UNKNOWN",
                          "gap": {"reason": "stored day_change has no declared per-row observation clock"}}}
    field = next((f for f in ("last_repriced", "generated_at", "as_of") if holdings_doc.get(f)), "as_of")
    aggregate_clock = _holdings_clock(holdings_doc.get(field), field)
    at = aggregate_clock["as_of"]
    noncash = [r for r in rows if not r["is_cash"] and not r.get("is_loan")]
    held = [r for r in noncash if (_number(r.get("shares", r.get("quantity"))) or 0) > 0]
    counted = [r for r in held if (_number(r.get("market_value")) or 0) >= 100]
    keys = {(r["account_id"], str(r.get("symbol") or "").upper()) for r in counted}
    accounts = []
    summaries: dict[str, list[dict]] = {}
    for key, summary in (holdings_doc.get("account_summaries") or {}).items():
        summaries.setdefault(canonical_key(key), []).append({"source_key": key, "summary": deepcopy(summary or {})})
    for account in sorted({r["account_id"] for r in rows} | set(summaries)):
        group = [r for r in rows if r["account_id"] == account]
        aliases = summaries.get(account) or []
        summary_rows = [a["summary"] for a in aliases]
        states = {str(s.get("state")) for s in summary_rows if s.get("state")}
        reported = [_number(s.get("total_value")) for s in summary_rows]
        summary_conflict = (any(len({_number(s.get(field)) for s in summary_rows}) > 1
                                for field in ("total_value", "holdings_count"))
                            or len({s.get("state") for s in summary_rows}) > 1)
        position_clock = _position_clock_aggregate(group)
        acov = _day_coverage(group)
        # A linked funded account without rows is missing, never flat or dropped.
        empty = (not group and bool(summary_rows)
                 and all(_number(s.get("total_value")) == 0 and _number(s.get("holdings_count")) == 0
                         for s in summary_rows))
        accounts.append({"account_id": account, "account_label": account_label(account),
                         "total_usd": _sum_known(group, "market_value") if group else (0.0 if empty else None),
                         "cash_usd": _sum_known([r for r in group if r["is_cash"]], "market_value") if group else (0.0 if empty else None),
                         "reported_total_usd": reported[0] if reported and len(set(reported)) == 1 else None,
                         "summary_alias_evidence": aliases, "summary_alias_conflict": summary_conflict,
                         "empty": empty,
                         "day_pl_usd": 0.0 if empty else acov["known_usd"],
                         "day_pl_complete": empty or acov["complete"],
                         "day_pl_unknown_rows": acov["unknown_rows"],
                         "day_pl_unknown_value_usd": acov["unknown_value_usd"],
                         "status": next(iter(states)) if len(states) == 1 else "UNCLASSIFIED",
                         "position_clock": position_clock,
                         "as_of": position_clock["as_of"]})
    missing_accounts = [r["account_id"] for r in accounts if r["day_pl_usd"] is None]
    day_complete = day_cov["complete"] and not missing_accounts
    unobserved_accounts = [r["account_id"] for r in accounts if not r["empty"] and r["as_of"] is None]
    clocks["positions"]["unknown_accounts"] = unobserved_accounts
    if unobserved_accounts:
        clocks["positions"].update(as_of=None, complete=False, status="UNKNOWN",
                                    gap={"reason": "position observations incomplete for: " + ", ".join(unobserved_accounts)})
    reason = "holdings unavailable" if not rows else (
        "holding value or day P&L missing" if total is None or day is None else
        (f"day P&L partial: {day_cov['unknown_rows']} holding row(s) without a day change "
         f"(${day_cov['unknown_value_usd']:,.2f} of value) excluded" if not day_cov["complete"] else None))
    if missing_accounts:
        reason = (reason + "; " if reason else "") + "day P&L missing accounts: " + ", ".join(missing_accounts)
    summary_conflicts = [r["account_id"] for r in accounts if r["summary_alias_conflict"]]
    if summary_conflicts:
        reason = (reason + "; " if reason else "") + "account summary aliases disagree: " + ", ".join(summary_conflicts)
    reason = reason or (aggregate_clock["gap"] or {}).get("reason")
    return {"total_usd": total, "cash_usd": cash, "day_pl_usd": day,
            # Coverage travels with the day figure. Partial is shown as partial,
            # never blanked and never silently called complete.
            "day_pl_complete": day_complete,
            "day_pl_coverage": {"known_rows": day_cov["known_rows"], "unknown_rows": day_cov["unknown_rows"],
                                "unknown_value_usd": day_cov["unknown_value_usd"],
                                "unknown_accounts": day_cov["unknown_accounts"],
                                "missing_accounts": missing_accounts},
            "positions_as_of": clocks["positions"]["as_of"],
            "valuation_as_of": clocks["valuation"]["as_of"], "quote_as_of": clocks["quote"]["as_of"],
            "clock_provenance": clocks,
            "quote_source": holdings_doc.get("reprice_source"),
            "day_pl_pct": round(day / (total - day) * 100, 3)
            if total is not None and day is not None and total - day > 0 else None,
            "position_count": len(keys) if rows else None,
            "position_counts": {"definition": "held non-cash account+symbol with market_value >= 100",
                                "all_rows": len(rows), "cash_rows": sum(r["is_cash"] for r in rows),
                                "non_cash_rows": len(noncash), "held_rows": len(held),
                                "below_100": len(held) - len(counted), "counted": len(keys),
                                "excluded_cusip_zero": sum(1 for r in noncash if len(str(r.get("symbol") or "")) == 9
                                                           and (_number(r.get("market_value")) or 0) == 0)},
            "accounts": accounts, "holdings": rows,
            "stored_totals": deepcopy(holdings_doc.get("portfolio_totals") or {}),
            "document_source": holdings_doc.get("document_source"),
            "document_fallback_reason": holdings_doc.get("document_fallback_reason"),
            **_evidence(_HOLDINGS_EVIDENCE.get(holdings_doc.get("document_source"),
                                               "portfolio_positions.load_store canonical holdings"),
                        at, now, reason=reason or holdings_doc.get("document_fallback_reason"))}


#: Where the holdings aggregate came from (lib/holdings_document.py). A fallback names itself and its reason.
_HOLDINGS_EVIDENCE = {
    "positions_current": "positions_current (DB) rendered by holdings_export.build_document",
    "holdings_json_fallback": "holdings store file fallback (database unavailable or the render refused)",
    "holdings_json": "portfolio_positions.load_store canonical holdings",
}


_ACTIVE_STOP_STATES = {"active", "working", "open", "new", "accepted", "partially_filled"}
# Schwab reports a resting STOP order as AWAITING_STOP_CONDITION; brokers/order_lifecycle.py maps it to
# pending_activation. Missing here, a resting stop showed as state "unknown" on Risk and in the prospectus stop plan.
_PENDING_STOP_STATES = {"pending_activation", "pending", "awaiting_parent_order", "awaiting_condition",
                        "awaiting_stop_condition", "pending_new", "queued", "awaiting_manual_review"}
_DEAD_STOP_STATES = {"canceled", "cancelled", "rejected", "expired", "replaced", "not_in_read"}


# Stop categories for display (board 15 "Stop source"): one per counted position, in the order the desk shows them.
STOP_CATEGORIES = ("active", "pending_activation", "filled", "unknown", "planned", "none")
_RESTING_STOP_STATES = ("active", "pending_activation")


def _stop_category(p: dict) -> str:
    state = p.get("stop_state")
    if state in ("active", "pending_activation", "filled", "unknown"):
        return state
    return "planned" if p.get("stop_source") == "planned" and p.get("stop_price") is not None else "none"


def _unproven_protection(p: dict) -> bool:
    """A broker stop was read but its current protection cannot be established either way.

    ``stop_for`` demotes a resting stop whose observation is not current (``STALE``/``UNAVAILABLE``) to
    ``stop_state == "unknown"``, and an unmapped broker status lands there too. Such a position is neither
    proven protected nor proven unprotected: an unknown observation must not become a definite "unprotected"
    count or dollar figure any more than it may become a zero-risk one.
    """
    return p.get("stop_state") == "unknown"


def _resting_summary(counted: list[dict], total_usd, *, broker_available: bool) -> dict:
    """Counted positions by stop category plus the loss if every resting broker stop (active or pending) fills.

    Display only. ``loss_at_stop_usd`` stays the active-stop figure; pending stops are reported beside it.
    """
    if not broker_available:
        return {"stop_breakdown": None, "loss_at_resting_stops_usd": None, "resting_heat_pct": None}
    breakdown = {}
    for cat in STOP_CATEGORIES:
        group = [p for p in counted if p.get("stop_category") == cat]
        breakdown[cat] = {"count": len(group), "value_usd": _sum_known(group, "market_value") if group else 0,
                          "symbols": [{"symbol": p["symbol"], "account_id": p["account_id"],
                                       "account_label": p.get("account_label")} for p in group]}
    resting = [p for p in counted if p.get("stop_category") in _RESTING_STOP_STATES]
    losses = [p.get("loss_at_resting_stop_usd") for p in resting]
    loss = round(sum(losses), 2) if all(v is not None for v in losses) else None
    return {"stop_breakdown": breakdown, "loss_at_resting_stops_usd": loss,
            "resting_heat_pct": round(loss / total_usd * 100, 3) if total_usd and loss is not None else None}


_ORDER_ID_IN_DESCRIPTION = re.compile(r"\border\s+(\d{6,})", re.IGNORECASE)
# On one broker read every observation shares captured_at; a working order outranks a filled one.
_STATE_RANK = {"active": 3, "pending_activation": 2, "unknown": 1, "filled": 0}


def _when(raw) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _norm_state(raw) -> str:
    raw = str(raw or "").lower().replace(" ", "_")
    return ("active" if raw in _ACTIVE_STOP_STATES else "pending_activation" if raw in _PENDING_STOP_STATES
            else "filled" if raw == "filled" else "unknown")


def fill_ledger(broker_rows, *, db_query=None, ledger_rows=None) -> dict | None:
    """order_id -> {"sold_at", "rebought_at"} for every FILLED stop observation, from the trade ledger.

    Schwab's order read keeps returning filled orders for weeks, so a filled observation alone does not say whether
    the sale is history (already in the ledger, position since re-bought) or still waiting for the holdings sync.
    The ledger names each fill's order id ("order <id>" in ``trade_transactions.description``). ``None`` means
    the ledger is unreadable (callers then say so instead of asserting a state). Read-only.
    """
    filled = [r for r in (broker_rows or []) if str(r.get("status") or "").lower() == "filled" and r.get("order_id")]
    if not filled:
        return {}
    if ledger_rows is None:
        symbols = sorted({str(r.get("symbol") or "").upper() for r in filled})
        ledger_rows = _query_rows(
            db_query,
            "SELECT trade_time, trade_date, action, symbol, account, description FROM trade_transactions "
            "WHERE upper(symbol) = ANY(%s) AND action IN ('Buy', 'Sell') ORDER BY trade_time",
            (symbols,))
        if ledger_rows is None:
            return None
    sales, buys = {}, {}
    for t in ledger_rows:
        at = _when(t.get("trade_time")) or _when(t.get("trade_date"))
        if at is None:
            continue
        key = (canonical_key(t.get("account")), str(t.get("symbol") or "").upper())
        action = str(t.get("action") or "").lower()
        if action == "buy":
            buys.setdefault(key, []).append(at)
        elif action == "sell":
            m = _ORDER_ID_IN_DESCRIPTION.search(str(t.get("description") or ""))
            if m:
                sales[m.group(1)] = (key, at)
    out = {}
    for r in filled:
        oid = str(r.get("order_id"))
        if oid not in sales:
            continue
        key, sold_at = sales[oid]
        later = [b for b in buys.get(key, []) if b > sold_at]
        out[oid] = {"sold_at": sold_at.isoformat(), "rebought_at": min(later).isoformat() if later else None}
    return out


def stop_for(account: str, symbol: str, *, broker_rows=None, planned=None, now=None, fills=None,
             holding_updated_at=None) -> dict:
    """Display-only stop precedence by canonical account+symbol, including state.

    ``broker_rows`` are persisted stop_last_known observations, never a broker
    request. Terminal observations cannot become active protection. A planned
    level is displayed but does not prove a resting broker order exists.

    ``fills`` (from ``fill_ledger``) settles a FILLED observation: when the ledger holds its sale and the position
    was re-bought, or holdings were refreshed after the sale, the fill is history and never "awaiting sync"
    (2026-10-31: a stopped-out and re-bought name kept reading "awaiting holdings sync"). Without
    ``fills`` a filled state says what it is waiting for and since when instead of asserting a stale state.
    """
    now = now or datetime.now(timezone.utc)
    account, symbol = canonical_key(account), str(symbol or "").upper()
    matches = [r for r in (broker_rows or []) if canonical_key(r.get("account")) == account
               and str(r.get("symbol") or "").upper() == symbol]
    # The newest observation for each order wins.
    latest = {}
    for r in matches:
        key = str(r.get("order_id") or "position")
        if key not in latest or str(r.get("captured_at") or "") > str(latest[key].get("captured_at") or ""):
            latest[key] = r
    held_at = _when(holding_updated_at)
    history = None
    viable = []
    for r in latest.values():
        status = str(r.get("status") or "").lower()
        if status in _DEAD_STOP_STATES:
            continue
        info = (fills or {}).get(str(r.get("order_id"))) if status == "filled" else None
        if info:
            sold_at, rebought_at = _when(info.get("sold_at")), _when(info.get("rebought_at"))
            if sold_at and ((rebought_at and rebought_at > sold_at) or (held_at and held_at > sold_at)):
                if history is None or sold_at > _when(history["filled_at"]):
                    history = {"filled_at": sold_at.isoformat(),
                               "rebought_at": rebought_at.isoformat() if rebought_at else None}
                continue  # the sale is settled history; the current position is a new lot
        viable.append(r)
    row = max(viable, key=lambda r: (str(r.get("captured_at") or ""), _STATE_RANK.get(_norm_state(r.get("status")), 0)),
              default={})
    raw_state = str(row.get("status") or "").lower().replace(" ", "_")
    state = ("active" if raw_state in _ACTIVE_STOP_STATES else "pending_activation" if raw_state in _PENDING_STOP_STATES
             else "filled" if raw_state == "filled" else "unknown" if row else "none")
    sp = _number(row.get("stop_price"))
    source = "broker_resting" if row else "none"
    at = row.get("captured_at")
    if not row and planned:
        for key in (f"{symbol}:{account}", symbol):
            candidates = [(k, v) for k, v in planned.items() if str(k).split(":")[0].upper() == symbol
                          and (k == key or (":" in str(k) and canonical_key(str(k).split(":", 1)[1]) == account))]
            for _, p in candidates:
                if isinstance(p, dict) and canonical_key(p.get("account")) in ("", "all", account):
                    sp = _number(p.get("stop_price", p.get("stop")))
                    if sp is not None:
                        source, at = "planned", p.get("set_date") or p.get("as_of")
                        break
            if source == "planned":
                break
    meta = _evidence("stop_last_known" if row else "stops.json", at, now,
                     reason="stop state not recorded" if state == "unknown" else None)
    observation = stop_observation_freshness(at, now=now) if row else None
    observed_state = state
    note = None
    if observation is not None:
        meta.update(as_of=observation["as_of"], stale=observation["status"] != "FRESH")
        if observation["status"] == "UNAVAILABLE":
            # The raw reported clock remains in stop_observation for diagnosis;
            # it cannot establish a usable observation time or an elapsed age.
            meta.update(as_of=None, age_hours=None)
        if meta["stale"]:
            meta["gap"] = {"reason": observation["reason"]}
            if state in ("active", "pending_activation"):
                # Preserve the recorded state separately; an old observation
                # cannot establish current protection or an active-stop count.
                state = "unknown"
                note = observation["reason"]
    if state == "filled":
        seen = _when(row.get("captured_at"))
        seen_label = _et_label(seen) if seen else "an unrecorded time"
        info = (fills or {}).get(str(row.get("order_id")))
        if fills is None:
            note = f"stop filled (broker read {seen_label}) · sale not yet checked against the trade ledger"
        elif not info:
            note = f"stop filled (broker read {seen_label}) · waiting for the sale to reach the trade ledger"
        elif held_at:
            note = (f"stop filled {_et_label(_when(info['sold_at']))} · waiting for the holdings sync"
                    f" (holdings last updated {_et_label(held_at)})")
        else:  # no holding context (e.g. the live-stops route): state the recorded fact, claim no wait
            note = f"stop filled {_et_label(_when(info['sold_at']))} · sale recorded in the trade ledger"
    elif history:
        filled_label = _et_label(_when(history["filled_at"]))
        rebought = _when(history.get("rebought_at"))
        note = (f"previous stop filled {filled_label}"
                + (f" · re-bought {_et_label(rebought)}" if rebought else " · holdings refreshed since")
                + ("" if state in ("active", "pending_activation") else " · no broker stop on the current position"))
    return {"account_id": account, "account_label": account_label(account), "symbol": symbol,
            "stop_price": sp, "stop_source": source, "stop_state": state,
            "stop_status_raw": row.get("status"), "stop_captured_at": meta["as_of"],
            "broker_protected": state == "active" and not meta["stale"] and sp is not None and sp > 0,
            "stop_state_observed": observed_state, "stop_observation": observation,
            "stop_qty": _number(row.get("qty")), "order_id": row.get("order_id"),
            # The broker order KIND survives a page view: a trailing order has no fixed trigger price, so without it
            # an active observation with an unknown price could not be told apart from a stop whose price was lost.
            "stop_order_type": (str(row.get("order_type") or "").strip().upper() or None),
            "stop_note": note, "stop_history": history, **meta}


_SOURCE_LABELS = {"cio_opportunity_projection": "CIO opportunity review", "cio_decisions": "CIO decision",
                  "cio_entry_states": "Trade AI entry check", "security_research_spine": "CIO research memory",
                  "hermes_watchlist_lifecycle": "Research watch review", "cio_instrument_records": "CIO record",
                  "decision_engine": "CIO decision engine", "watch_review": "Watch review"}


def _conflict_view(guid, row, raw, review) -> dict:
    field = str(raw.get("field") or "stance")
    values = deepcopy(raw.get("values") or [])
    if not values:
        values = [{"source": "cio_instrument_records", "value": row.get(field, row.get("stance")),
                   "at": row.get("as_of")},
                  {"source": raw.get("source"), "value": raw.get("value", raw.get("stance")),
                   "at": raw.get("as_of") or raw.get("at")}]
    sides = [{"source": v.get("source"), "source_label": _SOURCE_LABELS.get(v.get("source"),
               str(v.get("source") or "Source unavailable").replace("_", " ")),
              "value": v.get("value"), "as_of": v.get("at") or v.get("as_of")} for v in values]
    stable = json.dumps([guid, field, [(v["source"], v["value"]) for v in sides]], sort_keys=True, default=str)
    cid = raw.get("conflict_id") or raw.get("id") or "conflict-" + hashlib.sha256(stable.encode()).hexdigest()[:20]
    resolved = bool(raw.get("resolved") and review.get("resolution_proven") and review.get("conflict_id") in (None, cid))
    severity = raw.get("severity")
    if severity not in ("P0", "P1", "P2", "P3"):
        severity = None  # Classification belongs exclusively to the conflict engine.
    summary = " · ".join(f"{s['source_label']}: {s['value'] if s['value'] is not None else 'not recorded'}" for s in sides)
    return {"id": cid, "security_guid": guid, "field": field, "label": field.replace("_", " ").capitalize(),
            "severity": severity, "summary": summary, "sides": sides,
            "source_a": sides[0] if sides else None, "source_b": sides[1] if len(sides) > 1 else None,
            "blocker": raw.get("blocker") or raw.get("note") or "Sources disagree; a recorded CIO review is needed.",
            "clear_condition": raw.get("clear_condition") or "A CIO decision that cites the conflicting evidence and confirms the record.",
            "resolved": resolved, "blocks_action": not resolved,
            "evidence_refs": deepcopy(raw.get("evidence_refs") or []), "gap": {"reason": "source value or timestamp unavailable"}
            if any(s["value"] is None or not s["as_of"] for s in sides) else None}


def _review_view(row) -> dict:
    raw = (row.get("research") or {}).get("review_lifecycle") or row.get("review_lifecycle") or {}
    fields = ("status", "request_id", "created_at", "requested_at", "researching_at", "answered_at", "completed_at",
              "conflict_resolved_at", "updated_at", "research_id", "old_stance", "new_stance", "reason", "evidence_refs", "conflict_id",
              "readback_verification")
    out = {k: deepcopy(raw.get(k)) for k in fields}
    proven = bool(out["status"] == "CONFLICT_RESOLVED" and out["request_id"]
                  and out["conflict_resolved_at"] and out["evidence_refs"]
                  and out["readback_verification"] == "CIO-owned linked publication and canonical record agree"
                  and str(out["new_stance"] or "").upper() == str(row.get("stance") or "").upper()
                  and all(c.get("resolved") for c in row.get("conflicts") or []))
    out["resolution_proven"] = proven
    out["state"] = ("decided" if proven else "researching" if out["status"] == "RESEARCHING"
                    else "awaiting_decision" if out["status"] == "ANSWERED_PENDING_CIO"
                    else "queued" if out["status"] == "REQUESTED" else "failed" if out["status"] == "FAILED"
                    else "blocked" if out["status"] == "BLOCKED" else "unknown")
    out["gap"] = {"reason": "canonical review lifecycle unavailable"} if not raw else None
    return out


def _material_clock(row) -> tuple[str | None, list[dict], str | None]:
    """Oldest material evidence clock, never the projection's assembly time.

    W10 owns freshness thresholds. Naive/unreadable input times remain missing
    so its T1/R1 adapter can emit DATA_ERROR rather than invent a UTC offset.
    """
    from .cio_company_facts import timestamp
    if not row:
        return None, [], None  # no CIO record: stance_for reports that gap; it is not a timestamp defect
    explicit = row.get("inputs_as_of")
    components = [{"source": c.get("source"), "value": c.get("value"),
                   "as_of": c.get("evidence_at"), "weight": c.get("weight")}
                  for c in (row.get("conviction_components") or {}).values()
                  if isinstance(c, dict) and c.get("value") is not None and (_number(c.get("weight")) or 0) > 0]
    raw = [explicit] if explicit is not None else [c["as_of"] for c in components] if components else [row.get("evidence_at")]
    dates = [timestamp(value) for value in raw]
    if not dates or any(value is None for value in dates):
        return None, components, "oldest material input time unavailable or lacks timezone"
    return min(dates).isoformat(), components, None


def stance_for(security_guid: str, *, db_query=None, now: datetime | None = None,
               projection: dict[str, Any] | None = None, **projection_kwargs) -> dict[str, Any]:
    """One GUID's CIO stance/conviction, conflicts and provenance.

    Wraps data_broker.cio_prospect, including its store/shadow admission and
    freshness rules. A symbol match is never a substitute for a GUID match.
    ``projection`` is the unmodified get_prospects response for batch consumers.
    Lower-level advice remains in conflicts; it never replaces the CIO stance.
    """
    guid = str(security_guid or "").strip()
    if projection is None and guid:
        from .data_broker.cio_prospect import get_prospects
        projection = get_prospects(db_query=db_query, symbols=[guid], now=now, **projection_kwargs)
    doc = projection or {}
    rows = [r for r in doc.get("prospects", []) if str(r.get("security_guid") or "") == guid and guid]
    row = max(rows, key=lambda r: (int(r.get("revision") or 0), str(r.get("as_of") or "")), default={})
    missing = not row or row.get("stance") is None or row.get("conviction") is None
    material_at, material_inputs, material_gap = _material_clock(row)
    review = _review_view(row)
    conflicts = [_conflict_view(guid, row, c, review) for c in row.get("conflicts") or [] if isinstance(c, dict)]
    conflicts = sorted({c["id"]: c for c in conflicts}.values(), key=lambda c: (c["resolved"], c["severity"] or "Z", c["id"]))
    return {
        "security_guid": guid or None,
        "symbol": row.get("symbol"),
        "stance": row.get("stance"),
        "conviction": row.get("conviction"),
        "conflicts": conflicts,
        "conflict_source": "saved CIO record diagnostics; engine findings classify flags",
        "review": review,
        "revision": row.get("revision"),
        "as_of": row.get("as_of") or doc.get("as_of"),
        "inputs_as_of": material_at,
        "material_inputs": material_inputs,
        "input_time_gap": {"reason": material_gap} if material_gap else None,
        "age_hours": row.get("age_hours", doc.get("age_hours")),
        "stale": bool(row.get("stale", doc.get("stale", True))),
        "source": deepcopy(doc.get("source") or {}),
        "gap": {"reason": "CIO stance or conviction unavailable for this security GUID"} if missing else None,
    }


def conflicts_for(security_guid: str, **kwargs) -> dict:
    """Typed conflict list from the same strict GUID stance lookup; no resolution action."""
    stance = stance_for(security_guid, **kwargs)
    return {k: stance[k] for k in ("security_guid", "symbol", "stance", "conviction", "conflicts", "review",
                                   "source", "as_of", "stale", "gap")}


def stances_for_symbols(symbols, *, root=None, db_query=None, projection=None, now=None,
                        identity_resolver=None, **projection_kwargs) -> dict:
    """One batch projection and confirmed registry lookups; no ticker/GUID guess."""
    from .identity_carriage import resolve_security_identity
    from .data_broker.cio_prospect import get_prospects
    resolve_identity = identity_resolver or resolve_security_identity
    names = list(dict.fromkeys(str(s).upper() for s in symbols if str(s).strip()))
    identities = {symbol: resolve_identity(symbol, root=root) for symbol in names}
    guids = {symbol: (identity.get("security_guid") if identity.get("identity_status") == "CONFIRMED" else None)
             for symbol, identity in identities.items()}
    if projection is None:
        if root is not None:
            projection_kwargs.setdefault("shadow_base", Path(root) / "data/cio/cio_prospect_shadow.json")
        # LIVEFIX-K (2026-11-06): filter to the requested GUIDs BEFORE any ``limit``. Unfiltered, a limit keeps the
        # top-N prospects by conviction, so most requested names were absent and read as "no CIO stance".
        projection_kwargs.setdefault("symbols", [g for g in guids.values() if g])
        projection = get_prospects(db_query=db_query, now=now, **projection_kwargs)
    result = {}
    for symbol in names:
        identity = identities[symbol]
        guid = guids[symbol]
        result[symbol] = {**stance_for(guid, projection=projection, now=now),
                          "identity_status": identity.get("identity_status", "UNRESOLVED")}
    return result


def conflict_inputs_payload(query=None, *, db_query=None, now=None, projection=None) -> dict:
    q = query or {}
    guid = q.get("security_guid")
    guid = guid[0] if isinstance(guid, list) and guid else guid
    result = conflicts_for(guid, db_query=db_query, now=now, projection=projection)
    return {"ok": not bool(result["gap"]), "read_only": True, **result}


def conflict_payload(query=None, *, root=None, db_query=None, now=None, projection=None, engine_reader=None) -> dict:
    """Pass the engine read projection unchanged; never reinterpret old flags.

    W10 owns the registered reader and query filtering. It may be injected after
    that source is accepted. Until then absence is an explicit service gap.
    """
    now = now or datetime.now(timezone.utc)
    if projection is None and engine_reader is not None:
        projection = engine_reader(root=root, query=query or {}, now=now)
    if isinstance(projection, dict):
        return deepcopy(projection)
    return {"ok": False, "read_only": True, "findings": [],
            **_evidence("conflict engine read projection", None, now,
                        reason="conflict engine accepted source not yet integrated")}


def security_inputs_for(security_guid, *, document, projection=None, db_query=None, now=None) -> dict:
    """Canonical facts for W10's Input/Subject adapters; no comparison rules."""
    stance = stance_for(security_guid, projection=projection, db_query=db_query, now=now)
    positions = [r for r in document["positions"]["rows"] if (_number(r.get("market_value")) or 0) >= 100]
    held_rows = [r for r in positions if r.get("security_guid") == security_guid]
    complete = bool(document["portfolio"]["holdings"]) and all(r.get("security_guid") for r in positions)
    held = True if held_rows else False if complete else None
    return {"security_guid": security_guid, "symbol": stance["symbol"],
            "canonical": {"source": "CIO record", "value": stance["stance"], "as_of": stance["inputs_as_of"],
                          "subject_id": security_guid, "role": "claim"},
            "record_as_of": stance["as_of"], "material_inputs": stance["material_inputs"],
            "conviction": stance["conviction"], "context": {"held": held,
                "accounts": [r["account_id"] for r in held_rows]},
            "protection_inputs": [{"source": "stop_last_known", "value": r["stop_state"],
                                   "as_of": r.get("stop_captured_at"), "account": r["account_id"],
                                   "subject_id": security_guid, "role": "protection"} for r in held_rows],
            "saved_diagnostics": stance["conflicts"], "review": stance["review"],
            "gap": stance["gap"] or stance["input_time_gap"] or ({"reason": "held identity coverage incomplete"} if held is None else None)}


def _read_json(path: Path) -> dict:
    try:
        # A display resolver never loads a whole growing research/plan archive.
        if path.stat().st_size > 4 * 1024 * 1024:
            return {}
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _query_rows(db_query, sql, params=None) -> list[dict] | None:
    if db_query is None:
        return None
    try:
        rows = db_query(sql, params, fetch="all")
        return [dict(r) for r in rows] if isinstance(rows, (list, tuple)) else None
    except Exception:
        return None


def _manual_broker_rows(db_query) -> list[dict]:
    """Operator-recorded resting orders at brokers with no order API (Fidelity GTC stops).

    A persisted observation of a real order is the same kind of evidence as a ``stop_last_known`` row, so the
    stored page model reads it with no broker call. Without it a Fidelity holding with an operator-recorded stop
    fell out of the holdings projection and was labelled NO_STOP while Stop Management still showed the order
    (codex review of PR 2180 at 17199ab97). A missing table or DB yields ``[]`` — the stop_last_known rows stand.
    """
    rows = _query_rows(
        db_query,
        "SELECT account, symbol, order_id, order_type, stop_price, qty, status, updated_at "
        "FROM manual_broker_stops WHERE active = TRUE "
        "AND lower(COALESCE(status,'open')) NOT IN ('cancelled','canceled','filled','closed','expired')")
    return [{**dict(r), "captured_at": r.get("updated_at")} for r in rows or []]


def approvals_for(*, db_query=None, rows=None, projection=None, now=None) -> dict:
    """Typed queue counts; paper/broker proposals are disjoint account groups.

    All counts use complete COUNT queries, never page lengths. A missing queue
    makes the combined total unknown while preserving other measured counts.
    """
    now = now or datetime.now(timezone.utc)
    if projection is not None:
        # W11's unified operator queue owns de-duplication and typed counts.
        # Never add its total to legacy queue counts at the display layer.
        return deepcopy(projection)
    if rows is None:
        rows = _query_rows(db_query, """
            SELECT 'actions' AS kind, COUNT(*) AS count, NULL::text AS account FROM action_queue WHERE status='pending'
            UNION ALL SELECT 'decisions', COUNT(*), NULL::text FROM john_decision_queue WHERE status='pending_john'
            UNION ALL SELECT 'proposals', COUNT(*), COALESCE(target_account,final_account,proposed_account)
                      FROM paper_trade_proposals WHERE status='PENDING' GROUP BY 3
            UNION ALL SELECT 'options', COUNT(*), NULL::text FROM options_approval_queue WHERE status='pending'
        """)
    by_type = {k: None for k in ("actions", "decisions", "paper", "broker", "options", "unclassified_proposals")}
    if rows is not None:
        by_type = {k: 0 for k in by_type}
        for r in rows:
            kind = r.get("kind")
            if kind == "proposals":
                account_type = location_facts(r)["account_type"]
                kind = "paper" if account_type == "paper" else "unclassified_proposals" if account_type == "unknown" else "broker"
            if kind in by_type:
                n = _number(r.get("count"))
                by_type[kind] = by_type[kind] + int(n) if n is not None and by_type[kind] is not None else None
    total = sum(by_type.values()) if all(v is not None for v in by_type.values()) else None
    return {"total": total, "by_type": by_type,
            **_evidence("action_queue / john_decision_queue / paper_trade_proposals / options_approval_queue",
                        now if rows is not None else None, now, reason="approval queues unavailable" if total is None else None)}


def financial_queue_items(*, db_query=None, now=None, limit=200) -> dict:
    """Bounded source rows for W11's unified queue; no decision capability.

    Source IDs and explicit recommendation/proposal references support causal
    de-duplication. A symbol or similar title is never an entity identifier.
    Missing sources and truncation keep global completeness false.
    """
    now = now or datetime.now(timezone.utc)
    limit = max(1, min(200, int(limit)))
    sources = {
        "action_queue": ("actions", "SELECT id,recommendation_id,symbol,action,status,created_at,expires_at,dedupe_key "
                         "FROM action_queue WHERE status='pending' ORDER BY id LIMIT %s"),
        "john_decision_queue": ("decisions", "SELECT id,category,title,status,created_at,provenance "
                                "FROM john_decision_queue WHERE status='pending_john' ORDER BY id LIMIT %s"),
        "paper_trade_proposals": ("proposals", "SELECT id,symbol,COALESCE(target_account,final_account,proposed_account) AS account,"
                                  "target_account,status,created_at "
                                  "FROM paper_trade_proposals WHERE status='PENDING' ORDER BY id LIMIT %s"),
        "options_approval_queue": ("options", "SELECT id,proposal_id,symbol,status,created_at "
                                  "FROM options_approval_queue WHERE status='pending' ORDER BY id LIMIT %s"),
    }
    items, gaps = [], []
    for table, (kind, sql) in sources.items():
        rows = _query_rows(db_query, sql, (limit+1,))
        if rows is None:
            gaps.append({"source": table, "reason": "source unreadable"})
            continue
        if len(rows) > limit:
            gaps.append({"source": table, "reason": "source exceeds bounded page; total not established"})
        for row in rows[:limit]:
            identifier = row.get("id")
            if identifier is None:
                gaps.append({"source": table, "reason": "stable source id unavailable"})
                continue
            source_key = f"{table}:{identifier}"
            item_kind = kind
            account = canonical_key(row.get("target_account") or row.get("account"))
            if kind == "proposals":
                account_type = location_facts({"account": account})["account_type"]
                item_kind = "paper" if account_type == "paper" else "unclassified_proposals" if account_type == "unknown" else "broker"
            refs = [{"source": table, "id": str(identifier)}]
            if row.get("recommendation_id") is not None:
                refs.append({"source": "recommendation_registry", "id": str(row["recommendation_id"])})
            if row.get("proposal_id") is not None:
                refs.append({"source": "options_proposal", "id": str(row["proposal_id"])})
            provenance = row.get("provenance")
            if isinstance(provenance, str):
                try:
                    provenance = json.loads(provenance)
                except ValueError:
                    provenance = {}
            if isinstance(provenance, dict):
                for ref in provenance.get("source_refs") or []:
                    if isinstance(ref, dict) and ref.get("source") and ref.get("id") is not None:
                        refs.append({"source": str(ref["source"]), "id": str(ref["id"])})
            items.append({"key": source_key, "source": table, "source_id": str(identifier),
                          "canonical_entity_id": source_key, "source_refs": refs, "kind": item_kind,
                          "symbol": row.get("symbol"), "account_id": account or None,
                          "account_label": account_label(account) if account else None,
                          "status": row.get("status"), "created_at": row.get("created_at"),
                          "expires_at": row.get("expires_at"), "category": row.get("category"),
                          "title": row.get("title"), "action": row.get("action"),
                          "read_only": True, "can_decide": False})
    return {"items": items, "complete": not gaps, "gaps": gaps, "scope": "financial_source_rows",
            "as_of": now.isoformat(), "source": "existing approval queue rows", "limit_per_source": limit}


def paper_win_rate(*, db_query=None, stats=None, now=None) -> dict:
    """Same closed-trade denominator as live_trading_gate, including flat rows.

    Display only: the execution gate is never called or changed here.
    """
    now = now or datetime.now(timezone.utc)
    if stats is None:
        rows = _query_rows(db_query, "SELECT COUNT(*) AS closed, COUNT(*) FILTER (WHERE pnl > 0) AS wins "
                           "FROM paper_trades WHERE status='closed'")
        stats = rows[0] if rows else {}
    closed, wins = _number(stats.get("closed")), _number(stats.get("wins"))
    valid = closed is not None and wins is not None and 0 <= wins <= closed
    return {"closed": int(closed) if valid else None, "wins": int(wins) if valid else None,
            "win_rate": round(wins / closed, 4) if valid and closed else None,
            "win_rate_pct": round(100 * wins / closed, 1) if valid and closed else None,
            **_evidence("paper_trades status=closed", now if valid else None, now,
                        reason="no closed paper trades" if valid and not closed else "paper result counts unavailable" if not valid else None)}


def regime_for(*, db_query=None, projection=None, now=None) -> dict:
    """Regime and VIX from one classifier snapshot's input, with its clock."""
    now = now or datetime.now(timezone.utc)
    if projection is None:
        from .data_broker.market_regime import get_market_regime
        projection = get_market_regime(db_query, history=1, now=now) if db_query else {}
    row = projection.get("regime") or {}
    vix = _number(row.get("vix"))
    vix_at = row.get("generated_at") or row.get("created_at")
    if vix is None and row.get("snapshot_id"):
        values = _query_rows(db_query, "SELECT value, created_at FROM market_regime_indicators "
                             "WHERE snapshot_id=%s AND indicator_key='vix_close' ORDER BY created_at DESC LIMIT 1",
                             (row["snapshot_id"],))
        if values:
            vix, vix_at = _number(values[0].get("value")), values[0].get("created_at")
    reason = "classifier output unavailable" if not row else "VIX input unavailable for classifier snapshot" if vix is None else None
    return {"label": row.get("regime_label"), "vix": vix,
            "vix_as_of": _timestamp(vix_at).isoformat() if _timestamp(vix_at) else None,
            "snapshot_id": row.get("snapshot_id"), "confidence": _number(row.get("confidence")),
            "parts": {k: row.get(k) for k in ("volatility_state", "trend_state", "breadth_state", "macro_state")},
            **_evidence("market_regime_snapshots + matching market_regime_indicators.snapshot_id",
                        row.get("generated_at") or row.get("created_at"), now, reason=reason)}


def capital_for(portfolio: dict, *, plan=None, policy=None, now=None) -> dict:
    """Display waterfall only; never feeds a sizing or order path.

    Earmarked dollars remain part of current cash and are excluded from free
    investable cash. Future raise is a distinct figure, never added twice.
    Policy limits are read; no unconfirmed default becomes operator policy.
    """
    now = now or datetime.now(timezone.utc)
    plan, policy = plan or {}, policy or {}
    cash = portfolio.get("cash_usd")
    posture = plan.get("cash_posture") or plan.get("cash_policy_band") or plan.get("cash") or {}
    sources = plan.get("capital_sources") or plan.get("sources") or {}
    reserved = _number(posture.get("reserve_usd", plan.get("reserved_capital_usd")))
    earmarked = _number(sources.get("earmarked_redeploy_usd", plan.get("earmarked_redeploy_usd")))
    future = _number(sources.get("total_prospective_raise_usd", plan.get("prospective_raise_usd")))
    fields = policy.get("fields") or {}
    def confirmed(name):
        field = fields.get(name) or {}
        return field.get("value") if field.get("operator_confirmed") else None
    hierarchy = confirmed("concentration_hierarchy") or {}
    cash_band = confirmed("cash_target_range_pct")
    if reserved is None and cash_band is not None and portfolio.get("total_usd") is not None:
        minimum = _number(cash_band.get("min"))
        floor = _number(confirmed("minimum_liquidity_reserve_usd"))
        if minimum is not None:
            reserved = round(max(portfolio["total_usd"] * minimum / 100, floor or 0), 2)
    policy_max = _number(hierarchy.get("max_single_position_pct", hierarchy.get("max_single_name_pct")))
    # Alert thresholds are operational metadata, distinct from the policy cap.
    alert = _number((plan.get("policy") or {}).get("concentration_fire_pct", plan.get("concentration_fire_pct")))
    free = max(0, cash - reserved - earmarked) if all(v is not None for v in (cash, reserved, earmarked)) else None
    gaps = []
    if free is None:
        gaps.append("cash reserve or earmark evidence unavailable")
    if cash_band is None or policy_max is None:
        gaps.append("confirmed policy limits unavailable")
    if cash is not None and earmarked is not None and earmarked > cash:
        gaps.append("earmarked cash exceeds current cash")
        free = None
    return {"cash_usd": cash, "reserved_usd": reserved, "earmarked_usd": earmarked,
            "investable_usd": round(free, 2) if free is not None else None,
            "prospective_raise_usd": future, "policy_max_pct": policy_max,
            "alert_level_pct": alert, "cash_band": cash_band,
            "current_cash_pct": round(100 * cash / portfolio["total_usd"], 2)
            if cash is not None and portfolio.get("total_usd") else None,
            "post_plan_cash_usd": _number(plan.get("post_plan_cash_usd")),
            "post_plan_cash_pct": _number(plan.get("post_plan_cash_pct")),
            **_evidence("canonical holdings + CIO capital plan + operator investment policy",
                        plan.get("as_of") or portfolio.get("as_of"), now, reason="; ".join(gaps) or None)}


def status_for(root, *, now=None, db_query=None, scorecard=None) -> dict:
    """One evaluation set shared by CIO Overview, observability and scorecard.

    Existing lightweight scorecard collectors remain the domain evaluators.
    Measured DeepSeek completions come from the raw research ledger, evaluated
    by the existing non-error predicate. Missing ledger access stays unknown.
    """
    now = now or datetime.now(timezone.utc)
    if scorecard is None:
        from .cio_scorecard import get_cio_scorecard
        try:
            scorecard = get_cio_scorecard(root=Path(root), materialized_only=True)
        except Exception:
            scorecard = {}
    evaluations = deepcopy(scorecard.get("tiles") or [])
    rows = _query_rows(db_query, "SELECT recommendation,status,created_at FROM hermes_external_research "
                       "WHERE lane='deepseek' AND created_at >= %s", (now - timedelta(hours=24),))
    completed = None
    if rows is not None:
        from .research_lane_health import non_error_count
        completed = non_error_count(rows)
    for row in evaluations:
        if row.get("id") == "hermes_research":
            metrics = [m for m in row.get("metrics", []) if m.get("label") != "DeepSeek ok 24h"]
            row["metrics"] = [{"label": "DeepSeek ok 24h", "value": completed}, *metrics]
            # Do not turn an operational blocker green from throughput alone.
            # A blocked/dark zero-success verdict is corrected when the ledger
            # proves delivery; any other blocker remains visible.
            if completed and row.get("status") in ("dark", "blocked") and any(
                    word in str(row.get("verdict") or "").lower() for word in ("zero", "no recent", "non-error")):
                row.update(status="degraded", working=None,
                           verdict=f"{completed} DeepSeek completions in the ledger; monitor evaluation needs review.")
    return {"evaluations": evaluations, "deepseek_ok_24h": completed,
            "summary": {state: sum(r.get("status") == state for r in evaluations)
                        for state in ("working", "degraded", "blocked", "dark")},
            **_evidence("CIO scorecard evaluations + hermes_external_research", scorecard.get("as_of"), now,
                        reason="DeepSeek completion ledger unavailable" if completed is None else None)}


def apply_status_evaluations(scorecards, canonical_status) -> list[dict]:
    """Format one evaluation set into observability's existing domain shape."""
    ids = {"Desk / Telegram": "desk_telegram", "Hermes / Research": "hermes_research",
           "Shared Spine": "shared_spine", "Decisions": "decisions",
           "Outcomes / Learning": "outcomes_learning", "Platform / Pin": "platform_pin"}
    evaluations = {r.get("id"): r for r in canonical_status.get("evaluations") or []}
    result = []
    for raw in scorecards:
        row = deepcopy(raw)
        evaluation = evaluations.get(ids.get(row.get("name")))
        if evaluation:
            state = evaluation.get("status")
            row.update(status={"working": "WORKING", "degraded": "DEGRADED",
                               "blocked": "BLOCKED", "dark": "BLOCKED"}.get(state, "BLOCKED"),
                       value=evaluation.get("verdict"), blocker=evaluation.get("verdict") if state != "working" else None,
                       metrics=deepcopy(evaluation.get("metrics") or []),
                       source="cio_truth.status_for", last_success=evaluation.get("last_success"),
                       observed_at=canonical_status.get("as_of"))
        result.append(row)
    return result


def scorecard_payload(*, root=None, now=None, db_query=None, canonical_status=None) -> dict:
    if root is None:
        from .canonical_store_registry import production_state_root
        root = production_state_root()
    status = canonical_status or status_for(root, now=now, db_query=db_query)
    summary = status["summary"]
    return {"ok": True, "authority": "READ_ONLY_ADVISORY", "as_of": status.get("as_of"),
            "tiles": deepcopy(status["evaluations"]),
            "summary": {"working": summary["working"], "degraded": summary["degraded"],
                        "blocked_or_dark": summary["blocked"] + summary["dark"],
                        "tile_count": len(status["evaluations"])}, "truth": status}


def observability_payload(*, root=None, now=None, db_query=None, canonical_status=None) -> dict:
    """Read-only replacement without the heavy get_home attention writer."""
    from .cio_observability import build_observability
    from .cio_scorecard import _light_home, _light_brain, _light_health
    if root is None:
        from .canonical_store_registry import production_state_root
        root = production_state_root()
    root = Path(root)
    status = canonical_status or status_for(root, now=now, db_query=db_query)
    out = build_observability(home=_light_home(root), brain=_light_brain(root, materialized_only=True), research_ops={},
                              data_health=_light_health(root), now=status.get("as_of"), canonical_status=status)
    out["truth"] = status
    return out


def risk_payload(*, root=None, now=None, db_query=None, inputs=None, document=None) -> dict:
    """Current read-only Risk endpoint. No second stop lookup or cache publish."""
    doc = document or resolve(root, now, db_query=db_query, inputs=inputs)
    portfolio, risk, stops = doc["portfolio"], doc["positions"], doc["stops"]
    positions = []
    for raw in risk["rows"]:
        p = deepcopy(raw)
        price, sp = _number(p.get("price")), p.get("stop_price")
        p.update(current_price=price, has_stop=sp is not None,
                 distance_to_stop_pct=round(100 * (price - sp) / price, 2) if price and sp else None,
                 max_loss_dollar=round(max(0, price-sp) * (_number(p.get("shares")) or 0), 2) if price and sp else None,
                 risk_excluded=False, environment=p.get("environment") or "real")
        positions.append(p)
    denominator = _sum_known(positions, "market_value") if positions else None
    unprotected = risk.get("unprotected_value_usd")
    unproven = risk.get("unproven_value_usd")
    # codex-cloud P1 on #2677: `unprotected_value_usd` deliberately EXCLUDES a position whose broker status is
    # unmapped (FQ-116: an unproven stop is neither protected nor unprotected), so subtracting only the
    # unprotected figure from the total silently reclassified every unproven dollar as PROTECTED. A synthetic
    # $11,000 holding with an unmapped status reported `unproven_value_usd=11000` and still counted $11,000 as
    # protected. Protected is derived, so it may only be stated when every part of the subtraction is known; the
    # unproven figure is published beside it rather than absorbed into it.
    protected = (round(denominator - unprotected - unproven, 2)
                 if denominator is not None and unprotected is not None and unproven is not None else None)
    return {"portfolio_heat_pct": risk.get("portfolio_heat_pct"), "total_risk_dollars": risk.get("loss_at_stop_usd"),
            "pct_protected": round(100 * protected / denominator, 2) if denominator and protected is not None else None,
            "total_protected_mv": protected,
            "total_unprotected_mv": unprotected, "total_unproven_mv": unproven,
            "position_count": portfolio.get("position_count"),
            "position_counts": portfolio.get("position_counts"), "paper_position_count": None,
            "positions": positions, "stops": {f"{p['account_id']}:{p['symbol']}": p for p in stops["rows"]},
            "positions_basis": "holdings_live", "positions_as_of": portfolio.get("positions_as_of"),
            "clock_provenance": portfolio.get("clock_provenance"),
            "stop_health": {"protected_count": stops["active_count"], "pending_count": stops["pending_count"],
                            "filled_count": stops["filled_count"], "unprotected_count": stops["unprotected_count"]},
            "correlation": [], "escalation": {}, "source": "cio_truth", "truth": {k: portfolio[k] for k in
                                                                                      ("source", "as_of", "stale", "gap")}}


def _today_census(prior: dict, p: dict) -> dict:
    """Recount TODAY's account census from the SAME rows the figure came from.

    The legacy census was built before this overlay, from raw holdings keys
    (schwab_roth) against a snapshot keyed canonically (schwab_roth_ira), and it
    counted an unknown (None) day as "flat". After the overlay replaced the
    figures, the header said "5/5 represented, all zero change" over a TODAY of
    None (2026-10-26). Keys here are canonical; None is missing, never zero; an
    account whose figure leaves rows out is named as partial.
    """
    linked = {canonical_key(a) for key in ("contributing_accounts", "zero_change_accounts",
                                           "empty_accounts", "missing_accounts")
              for a in (prior.get(key) or [])} - {""}
    rows = {r["account_id"]: r for r in p.get("accounts") or []}
    empty = sorted(({canonical_key(a) for a in (prior.get("empty_accounts") or [])} - set(rows) - {""})
                   | {r["account_id"] for r in rows.values() if r.get("empty")})
    contributing, zero_change, missing, partial = [], [], [], []
    for acct in sorted((linked | set(rows)) - set(empty)):
        row = rows.get(acct)
        change = _number((row or {}).get("day_pl_usd"))
        if change is None:
            missing.append(acct)
            continue
        (contributing if change != 0 else zero_change).append(acct)
        if row.get("day_pl_complete") is False:
            partial.append(acct)
    cov = p.get("day_pl_coverage") or {}
    funded = len(contributing) + len(zero_change) + len(missing)
    represented = len(contributing) + len(zero_change)
    unknown_rows = int(cov.get("unknown_rows") or 0)
    return {"linked_account_count": funded + len(empty), "funded_account_count": funded,
            "represented_account_count": represented, "contributing_accounts": contributing,
            "zero_change_accounts": zero_change, "empty_accounts": empty, "missing_accounts": missing,
            "partial_accounts": partial, "unknown_rows": unknown_rows,
            "unknown_value_usd": cov.get("unknown_value_usd"),
            "complete": not missing and p.get("day_pl_complete") is not False,
            "coverage_reason": (
                f"{represented}/{funded} funded account(s) represented"
                + (f"; {len(empty)} empty ({', '.join(empty)})" if empty else "")
                + (f"; MISSING {', '.join(missing)}" if missing else "")
                + (f"; PARTIAL {', '.join(partial)}: {unknown_rows} holding row(s) without a day change excluded"
                   if partial else ""))}



_DAY_DEFINITION = (
    "Sum of finite stored holding day_change across current accounts; cash and worthless delisted rows "
    "without day_change are flat. Missing rows remain unknown. No quote-percent/broker P&L fallback, "
    "transfer adjustment, or closed-position P&L is added."
)


def market_session_reference(now: datetime | None, *, calendar=None) -> dict:
    """Last already-opened session from the existing backend calendar only.

    This dates a calendar decision, never a position/quote/P&L observation.
    Refuse unzoned evaluation clocks and unavailable/unrecognized calendar facts.
    """
    out = {"status": "UNKNOWN", "latest_open_session": None, "latest_open_at": None,
           "calendar_date": None, "phase": None, "is_trading_day": None,
           "as_of": None, "source": "scripts.market_session", "timezone": "America/New_York",
           "gap": None}
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        out["gap"] = {"reason": "session reference requires an explicit evaluation instant and timezone"}
        return out
    out["as_of"] = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    allowed = {"weekend", "holiday", "closed", "premarket", "regular", "afterhours"}
    try:
        if calendar is None:
            from scripts import market_session as calendar
        et = now.astimezone(ZoneInfo("America/New_York"))
        out["calendar_date"] = et.date().isoformat()
        phase = calendar.current_market_session(now)
        trading = calendar.is_trading_day(now)
        if phase not in allowed or type(trading) is not bool or trading != (phase not in {"weekend", "holiday"}):
            raise ValueError("unrecognized or inconsistent current calendar facts")
        out.update(phase=phase, is_trading_day=trading)
        for days_back in range(14):
            day = et.date() - timedelta(days=days_back)
            opened = datetime.combine(day, calendar.MARKET_OPEN, tzinfo=et.tzinfo)
            if opened > now:
                continue
            candidate_phase = calendar.current_market_session(opened)
            candidate_trading = calendar.is_trading_day(opened)
            if (candidate_phase not in allowed or type(candidate_trading) is not bool
                    or candidate_trading != (candidate_phase not in {"weekend", "holiday"})):
                raise ValueError("unrecognized or inconsistent candidate calendar facts")
            if candidate_trading:
                if candidate_phase != "regular":
                    raise ValueError("calendar does not confirm regular session at declared open")
                out.update(status="KNOWN", latest_open_session=day.isoformat(),
                           latest_open_at=opened.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"))
                return out
        out["gap"] = {"reason": "no proven opened session within the 14-day calendar lookup"}
    except Exception as exc:  # noqa: BLE001 -- UNKNOWN is explicit; no alternate calendar fallback
        out["gap"] = {"reason": f"market_session calendar reference unavailable: {type(exc).__name__}: {exc}"}
    return out


_ECONOMIC_DAY_GAP = (
    "Economic account-day P&L is unproven: stored day_change mixes prior-mark deltas and fill-aware session P&L; "
    "current rows do not establish closed-position, cash/loan or whole-account coverage. "
    "Neither zeros, percentages, retained basis flags nor build/quote clocks resolve this."
)


def _today_payload(prior: dict, p: dict, *, now=None) -> dict:
    """Refuse an economic-day claim while preserving the narrower raw evidence."""
    quote_at = _timestamp(p["quote_as_of"])
    census = _today_census(prior, p)
    gap = {"reason": _ECONOMIC_DAY_GAP, "ticket": "OI-044", "owner": "portfolio/holdings_accounts"}
    return {"contract_version": "TodayPnl@v1", "total_change": None,
            "status": "UNKNOWN", "complete": False, "scope": "ALL_ACCOUNTS_ECONOMIC_DAY",
            "definition": "Full-account economic/session-day P&L, including applicable intraday and closed positions",
            "coverage_reason": _ECONOMIC_DAY_GAP, "gap": gap,
            "linked_account_count": None, "funded_account_count": None, "represented_account_count": None,
            "contributing_accounts": None, "zero_change_accounts": None, "empty_accounts": None,
            "missing_accounts": None, "partial_accounts": None, "unknown_rows": None, "unknown_value_usd": None,
            "calculated_at": None, "calculation_time_source": None, "session_date": None, "session_source": None,
            "calculation_clock": {"as_of": None, "status": "UNKNOWN", "gap": deepcopy(gap)},
            "batch_built_at": p["valuation_as_of"], "batch_build_source": "holdings.generated_at",
            "mark_batch_at": p["quote_as_of"],
            "mark_session_date": quote_at.astimezone(ZoneInfo("America/New_York")).date().isoformat() if quote_at else None,
            "mark_session_source": "holdings.last_repriced" if quote_at else None,
            "mark_source": p["quote_source"], "observation_clock": deepcopy(p["clock_provenance"]["day_pnl"]),
            "market_session": market_session_reference(now if now is not None else datetime.now(timezone.utc)),
            "legacy_evidence": deepcopy(prior),
            "stored_row_evidence": {
                "scope": "CURRENT_STORED_HOLDING_ROWS", "definition": _DAY_DEFINITION,
                "known_sum": p["day_pl_usd"], "row_values_complete": p["day_pl_complete"],
                "census": census,
                "source_values": [{"account_id": r["account_id"], "symbol": r.get("symbol"),
                                   "day_change": _number(r.get("day_change")),
                                   "day_change_pct": _number(r.get("day_change_pct")),
                                   "day_change_raw": (str(r.get("day_change"))
                                                      if r.get("day_change") is not None and _number(r.get("day_change")) is None
                                                      else r.get("day_change")),
                                   "day_change_pct_raw": (str(r.get("day_change_pct"))
                                                          if r.get("day_change_pct") is not None and _number(r.get("day_change_pct")) is None
                                                          else r.get("day_change_pct")),
                                   "day_change_basis": r.get("day_change_basis"),
                                   "is_cash": r.get("is_cash"), "is_loan": r.get("is_loan")}
                                  for r in p["holdings"]]}}


def _day_period(p: dict, census: dict) -> dict:
    """Economic 1D is unavailable; a stored-row sum is not a substitute."""
    return {"period": "1D", "change": None, "change_pct": None,
            "display_change": None, "display_change_pct": None,
            "source": "UNPROVEN_ECONOMIC_DAY", "status": "UNKNOWN", "estimated": False,
            "display_label": "Economic day P&L unavailable", "scope": census["scope"],
            "complete": False, "gap": deepcopy(census["gap"]),
            "calculated_at": None, "session_date": None,
            "batch_built_at": census["batch_built_at"], "mark_batch_at": census["mark_batch_at"],
            "mark_session_date": census["mark_session_date"], "adjustment_note": _ECONOMIC_DAY_GAP}


def performance_payload(payload, *, root=None, now=None, holdings_doc=None, document=None) -> dict:
    """Retain the original performance money/membership; enrich evidence only.

    Legacy economic-day calculations remain available as originally reported.
    Their correctness is UNKNOWN until the source's basis/session/coverage is
    proven; current holding rows must never replace those monetary semantics.
    """
    if document is not None:
        p = document["portfolio"]
    else:
        if holdings_doc is None:
            from .portfolio_positions import load_store, store_path
            holdings_doc = load_store(store_path(root))
        p = portfolio_for(holdings_doc, now=now)
    out = deepcopy(payload)
    census = _today_payload({}, p, now=now)
    census["legacy_evidence"] = {
        "scope": "ORIGINAL_PERFORMANCE_CALCULATION_UNVERIFIED",
        "period_1d": deepcopy((payload.get("periods") or {}).get("1D")),
        "account_1d": {k: deepcopy((v.get("periods") or {}).get("1D"))
                       for k, v in (payload.get("accounts") or {}).items()},
        "period_quality_note": payload.get("period_quality_note")}
    out.update(today_pnl=census, market_session=deepcopy(census["market_session"]),
               clock_provenance=deepcopy(p["clock_provenance"]))
    return out



def _refresh_position_aggregate(aggregate: dict, p: dict, now: datetime | None) -> None:
    """Refresh legacy aggregate aliases/coverage from the SAME normalized rows."""
    from .portfolio_aggregate_contract import STALE_AFTER_HOURS, coverage_by_value, derive_observation_bounds
    at = now or datetime.now(timezone.utc)
    for row in aggregate["accounts"]:
        observed = row["as_of"]
        if row.get("observation_divergence"):
            row["legacy_observation_divergence"] = row["observation_divergence"]
        if row.get("summary_as_of_stale"):
            row["legacy_summary_as_of_stale"] = row["summary_as_of_stale"]
        age = (at - _timestamp(observed)).total_seconds() / 3600 if observed else None
        row.update(position_observation_time=observed, observation_time=observed,
                   position_observation_source="holdings[].position_clock",
                   position_observation_age_hours=age, dated=bool(observed),
                   contributes=not row["empty"],
                   position_row_count=sum(r["account_id"] == row["account"] for r in p["holdings"]),
                   holds_positions=any(r["account_id"] == row["account"] for r in p["holdings"]),
                   freshness="UNKNOWN" if age is None or age < 0 else ("STALE" if age > STALE_AFTER_HOURS else "FRESH"),
                   observation_divergence=None, summary_as_of_stale=None)
    accounts = aggregate["accounts"]
    oldest, oldest_account, newest = derive_observation_bounds(accounts)
    age = (at - _timestamp(oldest)).total_seconds() / 3600 if oldest else None
    coverage = coverage_by_value(accounts, newest_obs=newest, now=at)
    missing_values = [r["account"] for r in accounts if not r["empty"] and r["total_usd"] is None]
    coverage["unknown_value_accounts"] = missing_values
    if missing_values:
        coverage.update(value_dated_pct=None, value_fresh_pct=None, at_newest_pct=None)
    unknown = p["clock_provenance"]["positions"].get("unknown_accounts") or []
    state = "UNAVAILABLE" if not accounts else "COMPLETE"
    reason = "all contributing rows have declared position observations"
    if not accounts:
        reason = "no account observations"
    elif unknown or oldest is None:
        state, reason = "PARTIAL", "position observation UNKNOWN for: " + ", ".join(unknown)
    elif age is None or age < 0 or age > STALE_AFTER_HOURS:
        state, reason = "STALE", "oldest declared position observation is outside the freshness window"
    if aggregate.get("observation_divergences"):
        aggregate["legacy_observation_divergences"] = deepcopy(aggregate["observation_divergences"])
        aggregate["legacy_observation_divergences_status"] = "UNVERIFIED after strict row-clock reprojection"
    aggregate.update(included_account_count=len(accounts), coverage=coverage,
                     position_observation_oldest=oldest, position_observation_oldest_account=oldest_account,
                     position_observation_oldest_age_hours=age, position_observation_newest=newest,
                     position_observation_newest_account=next((r["account"] for r in accounts if r["as_of"] == newest), None)
                     if newest else None,
                     oldest_observation_time=oldest, oldest_observation_account=oldest_account,
                     newest_observation_time=newest, observation_divergences=[],
                     freshness_state=state, freshness_reason=reason,
                     position_clock=deepcopy(p["clock_provenance"]["positions"]))


def overview_payload(payload, *, root=None, now=None, db_query=None, inputs=None, document=None) -> dict:
    """Preserve unrelated Overview fields, replace shared financial/display facts."""
    doc = document or resolve(root, now, db_query=db_query, inputs=inputs)
    out = deepcopy(payload)
    p = doc["portfolio"]
    out.update(portfolio_value=p["total_usd"], total_cash=p["cash_usd"], today_change=None,
               today_pct=None, position_count=p["position_count"], position_counts=p["position_counts"],
               pending_approvals=doc["approvals"]["total"], approval_counts=doc["approvals"],
               paper=doc["paper"], clock_provenance=p.get("clock_provenance"),
               truth={k: p[k] for k in ("source", "as_of", "stale", "gap")})
    out["derived_total_value"] = p["total_usd"]
    pricing = out.setdefault("pricing", {})
    pricing.update(canonical_total_value=p["total_usd"], derived_total_value=p["total_usd"],
                   last_repriced=p["quote_as_of"], reprice_source=p["quote_source"])
    today_pnl = _today_payload(out.get("today_pnl") or {}, p, now=now)
    today_pnl["legacy_evidence"] = {"today_pnl": deepcopy(payload.get("today_pnl")),
                                    "today_change": payload.get("today_change"), "today_pct": payload.get("today_pct"),
                                    "period_1d": deepcopy((payload.get("periods") or {}).get("1D")),
                                    "today_by_account": deepcopy(payload.get("today_by_account"))}
    out["today_pnl"] = today_pnl
    out["market_session"] = deepcopy(today_pnl["market_session"])
    out.setdefault("periods", {})["1D"] = _day_period(p, today_pnl)
    out["today_by_account"] = {r["account_id"]: {"value": r["total_usd"], "change": None,
                                                 "status": "UNKNOWN", "gap": deepcopy(today_pnl["gap"]),
                                                 "account_label": r["account_label"], "as_of": None,
                                                 "batch_built_at": p["valuation_as_of"], "positions_as_of": r["as_of"],
                                                 "complete": False,
                                                 "stored_row_change": r["day_pl_usd"],
                                                 "row_values_complete": r.get("day_pl_complete"),
                                                 "unknown_rows": r.get("day_pl_unknown_rows")}
                               for r in p["accounts"]}
    aggregate = out.setdefault("portfolio_aggregate", {})
    aggregate["aggregate_value"] = p["total_usd"]
    aggregate.update(valuation_time=p["valuation_as_of"], quote_observation_time=p["quote_as_of"],
                     quote_source=p["quote_source"])
    old_accounts = {canonical_key(r.get("account")): r for r in aggregate.get("accounts") or []}
    aggregate["accounts"] = [{**old_accounts.get(r["account_id"], {}), **r,
                              "account": r["account_id"], "total_value": r["total_usd"], "display_value": r["total_usd"]}
                             for r in p["accounts"]]
    _refresh_position_aggregate(aggregate, p, now)
    out.setdefault("trade_ai", {}).update(market_regime=doc["regime"]["label"], vix=doc["regime"]["vix"],
                                           vix_observation_time=doc["regime"]["vix_as_of"], regime_truth=doc["regime"])
    return out


_TODAY_MOVE_NOTE = (
    "Holdings market-day move: the same figure as /api/v2/portfolio/performance periods.1D "
    "(Home Accounts 1D). Economic day P&L (closed/intraday fills, cash/loan) stays unproven (OI-044)."
)


def today_move_payload(market_day: dict | None, account_days: dict | None, today_pnl: dict) -> dict:
    """TODAY as the book's market-day move, from the Accounts-table source.

    LIVEFIX-H 2026-11-06: the header and Home summary read only the economic
    today_change, which overview_payload always nulls (OI-044), so TODAY showed
    "ECONOMIC UNKNOWN / session UNDATED" while Accounts showed the 1D move from
    /portfolio/performance. This block republishes THAT figure (never a new
    sum) with its mark session and the stored-row coverage census, so the
    surfaces agree and any gap is named beside the number instead of hiding it.
    `market_day` / `account_days` are portfolio_market_day / account_market_days
    over the same holdings the performance endpoint uses.
    """
    census = (today_pnl.get("stored_row_evidence") or {}).get("census") or {}
    session = today_pnl.get("mark_session_date")
    change = _number((market_day or {}).get("change"))
    by_account = {}
    for acct, row in sorted((account_days or {}).items()):
        value = _number((row or {}).get("change")) if isinstance(row, dict) else None
        by_account[canonical_key(acct) or acct] = {
            "change": value, "change_pct": _number((row or {}).get("change_pct")) if isinstance(row, dict) else None}
    missing = list(census.get("missing_accounts") or [])
    partial = list(census.get("partial_accounts") or [])
    out = {"contract_version": "TodayMove@v1", "scope": "ALL_ACCOUNTS_HOLDINGS_MARKET_DAY",
           "source": "/api/v2/portfolio/performance periods.1D (portfolio_market_day)",
           "status": "REPORTED" if change is not None else "UNKNOWN",
           "change": change,
           "change_pct": _number((market_day or {}).get("change_pct")) if change is not None else None,
           "by_account": by_account,
           "session_date": session if change is not None else None,
           "session_source": today_pnl.get("mark_session_source") if change is not None and session else None,
           "mark_batch_at": today_pnl.get("mark_batch_at"), "mark_source": today_pnl.get("mark_source"),
           "market_session": deepcopy(today_pnl.get("market_session")),
           "economic_status": today_pnl.get("status"),
           "complete": bool(census) and not missing and not partial,
           "missing_accounts": missing, "partial_accounts": partial,
           "unknown_rows": census.get("unknown_rows"),
           "coverage_reason": census.get("coverage_reason") or "stored-row coverage census unavailable",
           "note": _TODAY_MOVE_NOTE, "gap": None}
    if change is None:
        out["gap"] = {"reason": "performance market-day 1D unavailable (no holdings value)"}
    return out


def basis_for(position: dict, *, mark=None) -> dict:
    """Read the declared broker basis; partial/pre-window basis stays unknown."""
    broker = _number(position.get("cost_basis_broker"))
    stored = _number(position.get("cost_basis"))
    source = position.get("cost_basis_source")
    if broker is None and source == "broker_api":
        broker = stored
    basis = broker if broker is not None else stored
    reason = None
    if ((position.get("basis_partial") or position.get("basis_unknown")) and broker is None) or (basis is not None and basis <= 0):
        basis, reason = None, "basis unknown — incomplete or pre-window lot history"
    elif basis is None:
        reason = "basis unknown — no recorded acquisition cost"
    value = _number(position.get("market_value"))
    if mark is not None:
        shares = _number(position.get("shares"))
        value = round(mark * shares, 2) if shares is not None else None
    pnl = round(value-basis, 2) if value is not None and basis is not None else None
    conflicts = []
    if broker is not None and stored is not None and abs(broker-stored) > 1:
        conflicts.append({"field": "cost_basis", "broker": broker, "stored": stored,
                          "reason": "declared broker basis differs from the stored alternative"})
    return {"cost_basis_usd": basis, "unrealized_pl_usd": pnl,
            "unrealized_pl_pct": round(100*pnl/basis, 2) if pnl is not None and basis else None,
            "source": "broker_api" if broker is not None else source,
            "status": "unknown" if reason else "recorded", "gap": {"reason": reason} if reason else None,
            "conflicts": conflicts}


def holdings_payload(payload, *, root=None, now=None, db_query=None, inputs=None, document=None) -> dict:
    """Keep enrichment fields; quote, valuation, basis and stops share CIO truth."""
    doc = document or resolve(root, now, db_query=db_query, inputs=inputs)
    out = deepcopy(payload)
    previous = {(canonical_key(r.get("account") or r.get("account_id")), str(r.get("symbol") or "").upper()): r
                for r in out.get("holdings") or []}
    stop_by_key = {(r["account_id"], r["symbol"]): r for r in doc["stops"]["rows"]}
    rows = []
    for fact in doc["portfolio"]["holdings"]:
        key = fact["account_id"], str(fact.get("symbol") or "").upper()
        row = {**previous.get(key, {}), **deepcopy(fact)}
        # current_price is a legacy display alias, never a second quote read.
        row["current_price"] = row.get("price")
        basis = basis_for(row, mark=_number(row.get("price")))
        if not row.get("is_cash"):
            row.update(cost_basis=basis["cost_basis_usd"], gain_loss=basis["unrealized_pl_usd"],
                       gain_loss_pct=basis["unrealized_pl_pct"], basis_truth=basis)
        row.update(stop_by_key.get(key) or {})
        rows.append(row)
    p = doc["portfolio"]
    out.update(holdings=rows, count=len(rows), position_count=p["position_count"], total_value=p["total_usd"],
               total_cash=p["cash_usd"], today_change=p["day_pl_usd"], position_counts=p["position_counts"],
               positions_as_of=p["positions_as_of"], valuation_as_of=p["valuation_as_of"],
               quote_as_of=p["quote_as_of"], last_repriced=p["quote_as_of"], generated_at=p["valuation_as_of"],
               clock_provenance=p.get("clock_provenance"),
               truth={k: p[k] for k in ("source", "as_of", "stale", "gap")})
    return out


def realized_for_sale(event: dict, *, round_trips=None, db_query=None) -> dict:
    """FIFO journal P&L for this exact sale's account/date/quantity.

    The journal writer already performs FIFO matching. A partial window or
    unmatched sale is unknown; proceeds are never a realized profit fallback.
    """
    from zoneinfo import ZoneInfo
    sold_at = _timestamp(event.get("sold_at"))
    if len(str(event.get("sold_at") or "")) == 10 and sold_at is not None:
        # deploy_events carries an ET business DATE, not UTC midnight.
        sold_at = sold_at.replace(tzinfo=ZoneInfo("America/New_York"))
    account = canonical_key(event.get("account"))
    symbol = str(event.get("symbol") or "").upper()
    qty = _number(event.get("shares_sold"))
    if round_trips is None and sold_at is not None:
        start = sold_at.astimezone(ZoneInfo("America/New_York")).replace(hour=0, minute=0, second=0, microsecond=0)
        round_trips = _query_rows(db_query, "SELECT account,symbol,qty,entry_price,exit_price,exit_time,net_pnl,basis_status "
                                 "FROM schwab_round_trips WHERE upper(symbol)=%s AND exit_time >= %s "
                                 "AND exit_time < %s AND canary IS NOT TRUE",
                                 (symbol, start, start+timedelta(days=1)))
    rows = []
    if sold_at and qty is not None:
        date = sold_at.astimezone(ZoneInfo("America/New_York")).date()
        rows = [r for r in round_trips or [] if canonical_key(r.get("account")) == account
                and str(r.get("symbol") or "").upper() == symbol and _timestamp(r.get("exit_time"))
                and _timestamp(r["exit_time"]).astimezone(ZoneInfo("America/New_York")).date() == date]
    matched = _sum_known(rows, "qty") if rows else None
    known = bool(rows and matched is not None and qty is not None and abs(matched-qty) < 0.000001
                 and all(_number(r.get("entry_price")) is not None and _number(r.get("entry_price")) > 0
                         and _number(r.get("net_pnl")) is not None for r in rows))
    return {"realized_pnl": _sum_known(rows, "net_pnl") if known else None,
            "cost_basis_usd": round(sum(float(r["qty"])*float(r["entry_price"]) for r in rows), 2) if known else None,
            "basis_status": "known_fifo" if known else "unknown", "source": "schwab_round_trips FIFO journal",
            "gap": None if known else {"reason": "basis unknown — exact sale not fully matched in FIFO ledger"}}


def redeploy_payload(payload, *, db_query=None, round_trips=None) -> dict:
    """Correct the event's displayed realized P&L without rewriting its store."""
    out = deepcopy(payload)
    events = out.get("events") or []
    if round_trips is None and events:
        symbols = sorted({str(e.get("symbol") or "").upper() for e in events})
        dates = [_timestamp(e.get("sold_at")) for e in events]
        dates = [d for d in dates if d]
        round_trips = _query_rows(db_query, "SELECT account,symbol,qty,entry_price,exit_price,exit_time,net_pnl,basis_status "
                                  "FROM schwab_round_trips WHERE upper(symbol)=ANY(%s) AND exit_time >= %s "
                                  "AND exit_time < %s AND canary IS NOT TRUE",
                                  (symbols, min(dates)-timedelta(days=1), max(dates)+timedelta(days=2))) if dates else []
    for event in events:
        basis = realized_for_sale(event, round_trips=round_trips or [])
        event.update(realized_pnl=basis["realized_pnl"], basis_truth=basis,
                     account_id=canonical_key(event.get("account")), account_label=account_label(event.get("account")))
    return out


def positions_payload(payload, *, root=None, now=None, db_query=None, inputs=None, document=None) -> dict:
    """Shared current position facts for Open Trades/stop display readers.

    Other intelligence fields and historical rows retain their existing scope.
    No execution module is imported or called by this adapter.
    """
    doc = document or resolve(root, now, db_query=db_query, inputs=inputs)
    out = deepcopy(payload)
    facts = {(r["account_id"], str(r.get("symbol") or "").upper()): r for r in doc["positions"]["rows"]}
    for key in ("trades", "positions", "rows"):
        for row in out.get(key) or []:
            account = canonical_key(row.get("account") or row.get("account_id"))
            fact = facts.get((account, str(row.get("symbol") or "").upper()))
            row.update(account_id=account, account_label=account_label(account))
            if fact:
                for field in ("price", "shares", "market_value", "stop_price", "stop_source", "stop_state",
                              "stop_captured_at", "broker_protected", "basis_truth", "distance_to_stop_pct", "loss_at_stop_usd",
                              "stop_status_raw", "stop_state_observed", "stop_note", "stop_evidence", "stop_observation"):
                    row[field] = deepcopy(fact.get(field))
                row["current_price"] = row["price"]
                row["cost_basis"] = fact["basis_truth"]["cost_basis_usd"]
                row["gain_loss"] = fact["basis_truth"]["unrealized_pl_usd"]
                row["gain_loss_pct"] = fact["basis_truth"]["unrealized_pl_pct"]
    out.update(position_count=doc["portfolio"]["position_count"], position_counts=doc["portfolio"]["position_counts"])
    return out


def execution_status(payload: dict) -> dict:
    """Display text from supplied gate flags. Never imports or changes a gate."""
    out = deepcopy(payload)
    live = out.get("live_unlock") or {}
    unlocked = live.get("live_unlocked", out.get("live_unlocked"))
    blockers = out.get("current_blockers") or out.get("blockers") or []
    allowed = unlocked is True and not blockers and out.get("operator_approved_live_submit_possible") is True
    out["execution_model"] = ("Operator approval and per-order confirmation required; live execution gates currently allow this path."
                              if allowed else "Live execution is locked or blocked by the current execution gates."
                              if unlocked is False or blockers else "Live execution status is not fully measured.")
    out["execution_display_status"] = "eligible_for_operator_confirmation" if allowed else "locked" if unlocked is False or blockers else "unknown"
    if "armed_for_execution" in out:
        out["armed_for_execution"] = bool(out["armed_for_execution"] and allowed)
    return out


def _capital_inputs(root, db_query, now) -> dict:
    """Read published plan + open event balances; never invoke plan materializers."""
    from .jsonl_bounded import tail_jsonl_lines
    plan = {}
    for line in reversed(tail_jsonl_lines(Path(root) / "data/cio/cio_capital_plans.jsonl", 30,
                                         max_bytes=1024 * 1024)):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("record_type") == "CAPITAL_PLAN_PUBLISHED":
            plan = deepcopy(record.get("plan") or {})
            break
    events = _query_rows(db_query, """SELECT e.id,e.account,e.symbol,
        COALESCE(e.deployable_cash_usd,e.net_proceeds_usd,e.proceeds_usd)
          - COALESCE((SELECT SUM(filled_dollars) FROM redeploy_stage_fills f
                      WHERE f.deploy_event_id=e.id AND f.environment='production'),0) AS remaining_usd
        FROM deploy_events e WHERE e.status IN ('open','partial','locked')""")
    if events is not None and all(_number(r.get("remaining_usd")) is not None for r in events):
        sources = dict(plan.get("capital_sources") or {})
        sources["earmarked_redeploy_usd"] = round(sum(max(0, float(r["remaining_usd"])) for r in events), 2)
        plan["capital_sources"] = sources
    return plan


def _policy_inputs(root) -> dict:
    """Latest recorded policy fields without constructing the writable store.

    OperatorProfile's constructor creates directories. This streaming read
    applies its exact latest-field event rule and never initializes a store.
    """
    from .cio_operator_investment_policy import FIELD_SPECS
    fields = {}
    try:
        with (Path(root) / "data/cio/operator_profile.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    payload = json.loads(line).get("payload") or {}
                except ValueError:
                    continue
                name = payload.get("field_name")
                if name in FIELD_SPECS and payload.get("domain") == FIELD_SPECS[name]["domain"]:
                    field = payload.get("field") or {}
                    confirmed = field.get("status") == "OPERATOR_CONFIRMED"
                    fields[name] = {"value": field.get("value") if confirmed else None,
                                    "operator_confirmed": confirmed, "source": field.get("source"),
                                    "confirmed_at": field.get("confirmed_at"), "status": field.get("status")}
    except OSError:
        pass
    return {"fields": fields}


STOP_DOMAIN = "broker_stops"
_ET = ZoneInfo("America/New_York")


def stop_freshness_contract(registry_path: Path | None = None) -> dict | None:
    """{'open_h', 'closed_h'} for observed broker stops from config/data_source_authority.json, else None."""
    path = registry_path or Path(__file__).resolve().parents[2] / "config" / "data_source_authority.json"
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for group in ("domains", "proposed_domains"):
        for dom in registry.get(group) or []:
            if isinstance(dom, dict) and dom.get("domain") == STOP_DOMAIN:
                try:
                    return {"open_h": float(dom["stale_after_hours"]), "closed_h": float(dom["stale_after_hours_closed"])}
                except (KeyError, TypeError, ValueError):
                    return None
    return None


def _market_open(now: datetime) -> bool:
    t = now.astimezone(_ET)
    if t.weekday() >= 5 or not ((9, 30) <= (t.hour, t.minute) < (16, 0)):
        return False
    try:
        from scripts.market_session import is_trading_day
    except Exception:  # noqa: BLE001 - holiday calendar optional; weekday hours still apply
        return True
    try:
        return bool(is_trading_day(t))
    except Exception:  # noqa: BLE001
        return True


def _et_label(at: datetime) -> str:
    return at.astimezone(_ET).strftime("%a %b %d %H:%M ET").replace(" 0", " ")


def stop_clock(positions, now, *, broker_available=True, contract=None) -> dict:
    """The stop section's clock comes from broker observations only, never a planned stops.json level.

    Stale uses the broker_stops freshness contract: the open-session window while the market is open, the closed
    window otherwise (weekends do not page). A stale read keeps its counts but names their age in a gap.
    """
    observations = [stop_observation_freshness(p.get("stop_captured_at"), now=now)
                    for p in positions if p.get("stop_source") == "broker_resting"]
    unusable = sum(o["status"] == "UNAVAILABLE" for o in observations)
    times = [_timestamp(o["as_of"]) for o in observations if o["status"] != "UNAVAILABLE"]
    at = min(times) if times else None
    meta = _evidence("stop_last_known (broker reads) > stops.json, per account+symbol", at, now,
                     reason="persisted broker stop observations unavailable" if not broker_available else None)
    meta["last_broker_read_at"] = meta["as_of"]
    meta["last_broker_read_label"] = _et_label(at) if at else None
    if not broker_available:
        return meta
    if unusable:
        # One readable row cannot establish a complete refresh clock for its
        # neighbours. Keep partial history explicitly, not as a fresh as_of.
        meta["partial_observation_as_of"] = meta["as_of"]
        meta.update(as_of=None, age_hours=None, stale=True,
                    last_broker_read_at=None, last_broker_read_label=None,
                    gap={"reason": f"Stop observation time is unavailable for {unusable} of "
                                   f"{len(observations)} recorded positions; a complete refresh time is not known."})
        return meta
    if at is None:
        meta["stale"] = True
        meta["gap"] = {"reason": "No broker stop read is recorded for current holdings."}
        return meta
    contract = contract if contract is not None else stop_freshness_contract()
    if contract is None:
        meta["gap"] = {"reason": "Stop freshness threshold unavailable (data_source_authority broker_stops)."}
        return meta
    limit = contract["open_h"] if _market_open(now) else contract["closed_h"]
    meta["stale_after_hours"] = limit
    meta["stale"] = meta["age_hours"] is None or meta["age_hours"] < 0 or meta["age_hours"] > limit
    if meta["stale"]:
        meta["gap"] = {"reason": f"Stop data is {int(meta['age_hours'] or 0)} h old — counts from the last broker stop "
                                 f"read on {meta['last_broker_read_label']}."}
    return meta


def do_now_for(positions, approvals, *, now=None) -> dict:
    """Existing Home queue ordering over the shared CIO display facts only."""
    from .data_broker.home_do_now import item, merge, sort_items
    now = now or datetime.now(timezone.utc)
    items = []
    for p in positions:
        if p.get("broker_protected") or (_number(p.get("market_value")) or 0) < 100:
            continue
        state = p.get("stop_state")
        reason = ("Stop awaiting activation" if state == "pending_activation"
                  else ((p.get("stop_note") or "stop filled · awaiting holdings sync")[:1].upper()
                        + (p.get("stop_note") or "stop filled · awaiting holdings sync")[1:]) if state == "filled"
                  else "No active broker stop observed")
        observation = p.get("stop_observation")
        if observation and observation.get("status") != "FRESH" and state != "filled":
            reason = observation.get("reason") or "Stop observation time is unavailable"
        items.append(item(f"protection:{p['account_id']}:{p['symbol']}", "protect", "P1",
                          f"{p['symbol']} · {p['account_label']}", reason,
                          "Review protection", "/v3/risk", "cio_truth.stops",
                          money=p.get("market_value"), evidence={"account_id": p["account_id"], "stop_state": state}))
    if approvals.get("total"):
        items.append(item("approvals:pending", "decide", "P2", f"{approvals['total']} approvals waiting",
                          "Review the typed approval queues", "Review approvals", "/v3/trading?tab=Proposals",
                          "cio_truth.approvals", evidence={"counts": approvals["by_type"]}))
    ranked = sort_items(merge(items))
    # ``all_items`` is the full ranked list so Home can show "+N more" instead of silently dropping rows.
    return {"items": ranked[:7], "all_items": ranked, "total": len(ranked), "ranking": "home_do_now.sort_items",
            **_evidence("CIO shared protection + typed approval queues", now, now,
                        reason="approval count unavailable" if approvals.get("total") is None else None)}


def resolve(root=None, now=None, *, db_query=None, inputs=None) -> dict:
    """Shared display document; root is a persistent state root containing data/.

    ``inputs`` injects already-read canonical projections for batching/fixtures:
    holdings, broker_stops, planned_stops, regime, approvals, paper_stats,
    capital_plan, policy, cio_status, do_now, companies, sectors, risk_snapshot.
    An explicitly supplied root never falls back to another root or live DB.
    No job runs, broker calls, store writes, new stores or execution imports.
    """
    now = now or datetime.now(timezone.utc)
    inputs = inputs or {}
    if root is None:
        from .canonical_store_registry import production_state_root
        root = production_state_root()
    root = Path(root)
    state = root / "data" / "portfolios" / "state"
    from .portfolio_positions import store_path
    from .holdings_document import load_document
    # DB first (operator 2026-11-06): the export's render of positions_current, the file only as the stated
    # fallback. A non-production root (fixtures, offline copies) never reaches the live DB.
    portfolio = portfolio_for(inputs.get("holdings") if "holdings" in inputs else load_document(store_path(root)), now=now)
    broker = inputs.get("broker_stops") if "broker_stops" in inputs else _query_rows(
        db_query, "SELECT account,symbol,order_id,order_type,stop_price,qty,status,captured_at FROM stop_last_known")
    if "broker_stops" not in inputs:
        # Fidelity has no order API: its GTC stops exist only as persisted operator records. Reading them here is
        # still a stored read — no broker call — and it keeps a protected Fidelity holding out of the NO_STOP bucket.
        manual = _manual_broker_rows(db_query)
        if broker is not None and manual:  # None means the DB is unreadable: keep it unknown, never "zero stops"
            broker = list(broker) + manual
    planned = inputs.get("planned_stops") if "planned_stops" in inputs else _read_json(state / "stops.json")
    fills = inputs.get("stop_fills") if "stop_fills" in inputs else fill_ledger(broker, db_query=db_query)
    positions = []
    for r in portfolio["holdings"]:
        if r["is_cash"] or r.get("is_loan") or (_number(r.get("shares", r.get("quantity"))) or 0) <= 0:
            continue
        p = deepcopy(r)
        p["basis_truth"] = basis_for(p, mark=_number(p.get("price")))
        stop = stop_for(r["account_id"], r.get("symbol"), broker_rows=broker, planned=planned, now=now, fills=fills,
                        holding_updated_at=r.get("updated_at"))
        p.update({k: v for k, v in stop.items() if k not in ("source", "as_of", "age_hours", "stale", "gap")})
        p["stop_evidence"] = {k: stop[k] for k in ("source", "as_of", "age_hours", "stale", "gap")}
        positions.append(p)
    counted_positions = [p for p in positions if (_number(p.get("market_value")) or 0) >= 100]
    unproven_positions = [p for p in counted_positions if _unproven_protection(p)]
    unproven_ids = {id(p) for p in unproven_positions}
    # Proven unprotected only: an unproven row is neither protected nor unprotected, so it never adds to the
    # definite "without protection" figures. It is published separately as the unproven set.
    proven_unprotected = [p for p in counted_positions if not p["broker_protected"] and id(p) not in unproven_ids]
    counts = {state: sum(p["stop_state"] == state for p in counted_positions) for state in ("active", "pending_activation", "filled")}
    stop_rows = [{**{k: p.get(k) for k in ("account_id", "account_label", "symbol", "stop_price", "stop_source", "stop_state",
                                         "stop_captured_at", "broker_protected", "stop_qty", "stop_evidence", "stop_note",
                                         "stop_history", "stop_order_type", "stop_state_observed", "stop_observation")},
                  # the stored broker order id, so a page can show a resting stop without a live broker read
                  "stop_order_id": p.get("order_id")} for p in positions]
    stops = {"rows": stop_rows, "active_count": counts["active"], "pending_count": counts["pending_activation"],
             "filled_count": counts["filled"], "unprotected_count": len(proven_unprotected),
             "unproven_count": len(unproven_positions),
             "position_count": portfolio["position_count"],
             "nearest": None, "awaiting_fill": [],
             **stop_clock(positions, now, broker_available=broker is not None, contract=inputs.get("stop_freshness"))}
    if broker is None:
        for key in ("active_count", "pending_count", "filled_count", "unprotected_count", "unproven_count"):
            stops[key] = None
    # Current holdings and the same stop states supply the display risk summary;
    # stale pre-market risk rows never substitute for the current position set.
    losses = []
    for p in positions:
        price, shares, sp = _number(p.get("price")), _number(p.get("shares")), p.get("stop_price")
        p["distance_to_stop_pct"] = round(100 * (price-sp) / price, 2) if p["broker_protected"] and price and sp else None
        p["loss_at_stop_usd"] = round(max(0, price-sp) * shares, 2) if (
            p["broker_protected"] and price is not None and sp is not None and shares is not None) else None
        if p["broker_protected"]:
            losses.append(p["loss_at_stop_usd"])
        # Display-only (board 15): a broker stop that is resting but not yet active still has a level the operator
        # needs to read ("To stop", "Loss at stop"). These fields never count as protection (broker_protected).
        resting = p.get("stop_source") == "broker_resting" and p.get("stop_state") in _RESTING_STOP_STATES
        p["resting_stop_distance_pct"] = round(100 * (price-sp) / price, 2) if resting and price and sp else None
        p["loss_at_resting_stop_usd"] = round(max(0, price-sp) * shares, 2) if (
            resting and price is not None and sp is not None and shares is not None) else None
        planned_level = p.get("stop_source") == "planned"
        p["planned_stop_distance_pct"] = round(100 * (price-sp) / price, 2) if planned_level and price and sp else None
        p["counted"] = any(p is c for c in counted_positions)
        p["stop_category"] = _stop_category(p)
    # cx-openai D52 triage on #2677: the uncertainty must cover exactly the positions that supply the monetary risk
    # total, and an unmeasured book is not a zero-risk one. `losses` is built above from every broker-protected
    # position; the guard used to read only `counted_positions` (>= $100), so a book whose positions were all smaller
    # than the counting threshold produced an empty `losses` list — and `all([])` is True — publishing
    # loss_at_stop_usd 0.0 and portfolio_heat_pct 0.0 for a stop set nobody had observed.
    uncertain_observation = any(p.get("stop_observation") is not None
                                and p["stop_observation"]["status"] != "FRESH" for p in positions)
    if not portfolio["holdings"] or broker is None or any(v is None for v in losses):
        protected_loss = None
    elif not positions:
        protected_loss = 0.0  # nothing is held, so nothing can be lost at a stop
    elif not losses:
        protected_loss = None  # positions are held and none has an observed active stop: unknown, not zero
    else:
        protected_loss = round(sum(losses), 2)
    if uncertain_observation:
        protected_loss = None  # Unknown evidence must not become a zero-risk figure.
    unprotected_mv = _sum_known([p for p in positions if not p["broker_protected"] and not _unproven_protection(p)],
                                "market_value") if portfolio["holdings"] and broker is not None else None
    unproven_mv = (_sum_known([p for p in positions if _unproven_protection(p)], "market_value")
                   if portfolio["holdings"] and broker is not None else None)
    position_section = {"rows": positions, "loss_at_stop_usd": protected_loss,
                        "portfolio_heat_pct": round(protected_loss / portfolio["total_usd"] * 100, 3)
                        if portfolio.get("total_usd") and protected_loss is not None else None,
                        "unprotected_value_usd": unprotected_mv, "unproven_value_usd": unproven_mv,
                        "largest_name": None,
                        "loss_basis": "loss to observed active stops; unprotected downside is not bounded",
                        **{k: portfolio[k] for k in ("source", "as_of", "stale", "gap")}}
    position_section["as_of"] = portfolio["positions_as_of"]
    position_section.update(_resting_summary(counted_positions, portfolio.get("total_usd"), broker_available=broker is not None))
    if uncertain_observation:
        position_section.update(loss_at_resting_stops_usd=None, resting_heat_pct=None, unprotected_value_usd=None)
        stops["unprotected_count"] = None
    by_symbol = {}
    for p in positions:
        by_symbol[p["symbol"]] = by_symbol.get(p["symbol"], 0) + (_number(p.get("market_value")) or 0)
    if by_symbol and portfolio.get("total_usd"):
        symbol = max(by_symbol, key=by_symbol.get)
        position_section["largest_name"] = {"symbol": symbol, "pct": round(100 * by_symbol[symbol] / portfolio["total_usd"], 3)}
    position_section["concentration"] = [{"symbol": symbol, "value_usd": value,
                                           "pct": round(100 * value / portfolio["total_usd"], 3)
                                           if portfolio.get("total_usd") else None}
                                          for symbol, value in sorted(by_symbol.items(), key=lambda r: -r[1])]
    # No protection inference from a crossed mark: fills remain a separate sync.
    distances = []
    for p in positions:
        price, sp = _number(p.get("price")), p.get("stop_price")
        if price and sp and p["stop_state"] == "active":
            distance = round(100 * (price - sp) / price, 2)
            distances.append({"symbol": p["symbol"], "account_id": p["account_id"], "distance_pct": distance})
            if distance <= 0:
                stops["awaiting_fill"].append({"symbol": p["symbol"], "account_id": p["account_id"], "stop_price": sp,
                                               "reason": "mark at or below observed stop; fill not yet confirmed"})
    # A broker stop that FILLED while the position is still in holdings: the sale is not yet in the holdings sync.
    stops["filled_awaiting_sync"] = [
        {"symbol": p["symbol"], "account_id": p["account_id"], "account_label": p.get("account_label"),
         "stop_price": p.get("stop_price"), "captured_at": p.get("stop_captured_at"),
         "reason": p.get("stop_note") or "stop filled · awaiting holdings sync"}
        for p in counted_positions if p["stop_state"] == "filled"] if broker is not None else []
    stops["nearest"] = min(distances, key=lambda r: abs(r["distance_pct"]), default=None)
    stops["awaiting_fill_count"] = len(stops["awaiting_fill"])
    companies = inputs.get("companies")
    if companies is None:
        try:
            from .data_broker.cio_company_facts import load_snapshot
            companies = load_snapshot(root)
        except Exception:
            companies = {}
    companies = {guid: {"symbol": (v.get("company_facts") or {}).get("symbol"), **v}
                 for guid, v in companies.items()}
    identity_by_symbol = {}
    for guid, record in companies.items():
        if record.get("symbol"):
            identity_by_symbol.setdefault(str(record["symbol"]).upper(), []).append(guid)
    for row in [*portfolio["holdings"], *positions]:
        ids = identity_by_symbol.get(str(row.get("symbol") or "").upper()) or []
        if not row.get("security_guid") and len(ids) == 1:
            row["security_guid"] = ids[0]
            row["security_guid_source"] = "CIO InstrumentRecord company_facts"
    capital_plan = inputs.get("capital_plan") if "capital_plan" in inputs else _capital_inputs(root, db_query, now)
    policy = inputs.get("policy")
    if policy is None:
        policy = _policy_inputs(root)
    sectors = inputs.get("sectors")
    if sectors is None and db_query:
        try:
            from .data_broker.sector_momentum import get_sector_signals
            sectors = get_sector_signals(db_query)
        except Exception:
            sectors = None
    approval_input = inputs.get("approvals")
    approvals = approvals_for(db_query=db_query, rows=approval_input if isinstance(approval_input, list) else None,
                              projection=approval_input if isinstance(approval_input, dict) else None, now=now)
    status = inputs.get("cio_status") if "cio_status" in inputs else status_for(root, now=now, db_query=db_query)
    do_now = inputs.get("do_now") if "do_now" in inputs else do_now_for(positions, approvals, now=now)
    return {"read_only": True, "financial_action": False, "as_of": now.isoformat(),
            "portfolio": portfolio, "positions": position_section, "stops": stops,
            "regime": regime_for(db_query=db_query, projection=inputs.get("regime"), now=now),
            "approvals": approvals,
            "paper": paper_win_rate(db_query=db_query, stats=inputs.get("paper_stats"), now=now),
            "capital": capital_for(portfolio, plan=capital_plan, policy=policy, now=now),
            "cio_status": status,
            "do_now": do_now,
            "companies": {"by_guid": companies, **_evidence("CIO InstrumentRecord research.company_facts", None, now,
                          reason="CIO company facts unavailable" if not companies else None)},
            "conflicts": deepcopy(inputs["conflicts"]) if "conflicts" in inputs else {
                "findings": [], **_evidence("conflict engine read projection", None, now,
                                            reason="conflict engine accepted source not yet integrated")},
            "sectors": sectors or {"sectors": {}, **_evidence("sector_momentum.get_sector_signals", None, now,
                          reason="multi-horizon sector projection unavailable")}}
