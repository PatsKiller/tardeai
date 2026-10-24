"""Stored Watch market evidence: batched reads, pure request-time view, zero providers/writes.

Quote identity/observation fields stay together. Existing canonical artifacts win
when present; otherwise the existing latest_quote projection supplies stored data.
Levels follow the existing context's master -> strategy precedence, with explicit
closed-session resistance fallback. No price targets, stops or averages become levels.
"""
from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from lib.data_broker.latest_quote import DEFAULT_MAX_AGE_SECONDS, get_latest_quotes

SCHEMA = "WatchMarketFacts@v1"
RESISTANCE_KEY = "portfolio.reentry.resistance.v1"
MASTER_SQL = "SELECT symbol, support, resistance FROM watchlist_symbol_master WHERE symbol = ANY(%s)"
STRATEGY_SQL = """SELECT DISTINCT ON (symbol) symbol, support, resistance, created_at
FROM watchlist_strategy_cards WHERE symbol = ANY(%s) ORDER BY symbol, created_at DESC"""
PREF_SQL = "SELECT value FROM ui_prefs WHERE key=%s"
CANONICAL_KEYS = (
    "last", "day_change_pct", "price_as_of", "observed_at", "price_source", "quote_id", "source_record_id",
    "market_session", "freshness_state", "market_state", "missing", "winning_branch", "mq_source",
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) and n > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else str(value).strip() if value else None


def _instant(value: Any) -> datetime | None:
    raw = _iso(value)
    if not raw or len(raw) == 10:
        return None  # a closed-session date is not a timestamp
    try:
        at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return at.astimezone(timezone.utc) if at.tzinfo else None
    except (TypeError, ValueError):
        return None


def _symbols(values: Iterable[Any]) -> list[str]:
    return sorted({str(v).strip().upper() for v in values if str(v or "").strip()})


def _raw(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[index]
    except (TypeError, IndexError, KeyError):
        return None


def load_snapshot(db_query: Callable[..., Any] | None, symbols: Iterable[Any], *, now: datetime,
                  cards: dict[str, dict] | None = None) -> dict[str, Any]:
    """One stored snapshot for gather's 60s cache; each source fails independently.

    db_query is injected. None is explicitly unavailable, never a request to
    connect. No raw exception text is retained in the public snapshot/view.
    """
    syms = _symbols(symbols)
    result: dict[str, Any] = {"symbols": syms, "quotes": {}, "master": {}, "strategy": {}, "closed": {},
                              "read_status": {}, "canonical": {}, "provider_calls": 0}
    for sym, card in (cards or {}).items():
        explicit = bool(card.get("source_record_id") or card.get("quote_id") is not None
                        or card.get("winning_branch") in ("market_quotes", "enrichment")
                        or set(card.get("missing") or []) & {"canonical_quote_identity", "canonical_market_quote"})
        if sym.upper() in syms and explicit:
            result["canonical"][sym.upper()] = deepcopy({k: card.get(k) for k in CANONICAL_KEYS})
    if not syms or db_query is None:
        result["read_status"] = {k: "unavailable" for k in ("quotes", "master", "strategy", "closed")}
        return result
    quote_inputs: list[Any] = []

    def quote_reader(sql, params):
        rows = list(db_query(sql, params) or [])
        quote_inputs.extend(rows)
        return rows

    quote_batch = get_latest_quotes(quote_reader, syms, max_age_seconds=DEFAULT_MAX_AGE_SECONDS, now=now)
    result["quotes"] = quote_batch.get("symbols") or {}
    for row in quote_inputs:
        rec = result["quotes"].get(str(_raw(row, "symbol", 0) or "").upper())
        if rec is not None:
            # Keep the original record's precision; normalization cannot turn a date
            # into an observed midnight or a malformed boolean into a dollar price.
            rec["as_of"] = _iso(_raw(row, "fetched_at", 5))
            if isinstance(_raw(row, "price", 1), bool):
                rec["price"] = None
    result["read_status"]["quotes"] = "ok" if quote_batch.get("ok") else "unavailable"
    for name, sql in (("master", MASTER_SQL), ("strategy", STRATEGY_SQL)):
        try:
            rows = db_query(sql, (syms,)) or []
            result[name] = {str(r["symbol"]).upper(): dict(r) for r in rows
                            if isinstance(r, dict) and str(r.get("symbol") or "").upper() in syms}
            result["read_status"][name] = "ok"
        except Exception:  # noqa: BLE001 - independent, sanitized missing-source state
            result["read_status"][name] = "unavailable"
    try:
        rows = db_query(PREF_SQL, (RESISTANCE_KEY,)) or []
        row = rows if isinstance(rows, dict) else rows[0] if rows else {}
        payload = row.get("value") or {}
        payload = json.loads(payload) if isinstance(payload, str) else payload
        closed = payload.get("symbols") if isinstance(payload, dict) else None
        result["closed"] = {str(s).upper(): r for s, r in closed.items() if isinstance(r, dict)} if isinstance(closed, dict) else {}
        result["invalid_closed_symbols"] = [str(s).upper() for s, r in closed.items() if not isinstance(r, dict)] if isinstance(closed, dict) else []
        result["read_status"]["closed"] = "ok" if isinstance(closed, dict) else "invalid"
    except Exception:  # noqa: BLE001 - never expose DB/credential details to an operator surface
        result["read_status"]["closed"] = "unavailable"
    return result


def _price(snapshot: dict, sym: str, now: datetime) -> dict:
    artifact = (snapshot.get("canonical") or {}).get(sym)
    canonical = artifact is not None
    rec = artifact if canonical else (snapshot.get("quotes") or {}).get(sym) or {}
    value = _number(rec.get("last") if canonical else rec.get("price"))
    observed = _iso(rec.get("price_as_of") if canonical else rec.get("as_of"))
    source = rec.get("price_source") if canonical else rec.get("source")
    label = f"Canonical Watch quote · {source or 'source unavailable'}" if canonical else "Stored quote"
    if canonical and rec.get("mq_source"):
        label += f" · {rec['mq_source']}"
    if not canonical and rec.get("provider"):
        label += f" · {rec['provider']}"
    out = {"value": value, "as_of": observed, "source": source or None, "source_label": label,
           "stale": True, "freshness": "UNKNOWN", "age_seconds": None, "reason": None,
           "quote_artifact": deepcopy(artifact) if canonical else None}
    if canonical and (not rec.get("source_record_id") or rec.get("quote_id") is None or not source
                      or "canonical_quote_identity" in (rec.get("missing") or [])):
        out.update(value=None, reason="Canonical quote identity is unavailable.")
        return out  # do not mask a canonical fail-closed result with an unrelated quote
    if value is None:
        unavailable = (snapshot.get("read_status") or {}).get("quotes") == "unavailable"
        out.update(freshness="MISSING", reason="Stored quote read unavailable." if unavailable and not canonical
                   else "No valid stored price is available.")
        return out
    at = _instant(observed)
    if at is None:
        out["reason"] = "Price observation timestamp is missing or unknown."
    elif at > now:
        out["reason"] = "Price observation timestamp is in the future."
    else:
        age = (now - at).total_seconds()
        if canonical:
            from lib.watch_canonical_quote import derive_freshness

            state, _ = derive_freshness(observed, now=now)
            stale = state in ("STALE", "DATA_UNAVAILABLE")
        else:
            stale = age > DEFAULT_MAX_AGE_SECONDS
            state = "STALE" if stale else "CURRENT"
        out.update(age_seconds=round(age, 1), stale=stale, freshness=state,
                   reason="Price observation is stale." if stale else None)
    return out


def _level(snapshot: dict, sym: str, kind: str, price: float | None) -> dict:
    notes: list[str] = []
    specs = [("master", "watchlist_symbol_master", "Watch symbol master"),
             ("strategy", "watchlist_strategy_cards", "Strategy card")]
    if kind == "resistance":
        specs.append(("closed", f"ui_prefs:{RESISTANCE_KEY}", "Closed-session resistance cache"))
    for name, source, label in specs:
        rec = (snapshot.get(name) or {}).get(sym) or {}
        value = _number(rec.get(kind))
        if name == "closed" and str(rec.get("state") or "").upper() == "UNAVAILABLE":
            value = None
        if value is None:
            status = (snapshot.get("read_status") or {}).get(name)
            invalid = status == "invalid" or (name == "closed" and sym in snapshot.get("invalid_closed_symbols", []))
            reason = "read unavailable" if status == "unavailable" else "data invalid" if invalid else "invalid" if rec.get(kind) is not None else "missing"
            notes.append(f"{label} {kind} {reason}.")
            continue
        crossed = price is not None and (value > price if kind == "support" else value < price)
        if crossed:
            notes.append(f"{label} {kind} is {'above' if kind == 'support' else 'below'} the shown price.")
            continue
        observed = _iso(rec.get("created_at")) if name == "strategy" else _iso(rec.get("as_of")) if name == "closed" else None
        basis = "strategy card created_at" if name == "strategy" else "last closed session" if name == "closed" else "not exposed by source"
        compatibility = "UNKNOWN" if price is None else "BELOW_OR_AT_PRICE" if kind == "support" else "ABOVE_OR_AT_PRICE"
        if price is None:
            notes.append("Price unavailable; nearest-level relation is unknown.")
        notes.append("Level observation time unavailable." if observed is None else
                     "Closed-session date; level freshness is not assessed." if name == "closed" else
                     "Strategy-card creation time; level freshness is not assessed.")
        return {"value": value, "as_of": observed, "as_of_basis": basis, "source": source, "source_label": label,
                "stale": None, "freshness": "UNKNOWN", "compatibility": compatibility, "reason": " ".join(notes),
                "source_state": rec.get("state") if name == "closed" else None}
    return {"value": None, "as_of": None, "source": None, "source_label": "No reference", "stale": None,
            "freshness": "MISSING", "compatibility": "UNKNOWN", "reason": " ".join(notes), "as_of_basis": None}


def view(snapshot: dict | None, symbol: str, *, now: datetime) -> dict:
    """Pure view at request time: never reuse cached freshness or generated_at as observation time."""
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    snapshot = snapshot or {}
    sym = symbol.upper().strip()
    price = _price(snapshot, sym, now)
    return {"schema": SCHEMA, "evaluated_at": now.isoformat(), "price": price,
            "support": _level(snapshot, sym, "support", price["value"]),
            "resistance": _level(snapshot, sym, "resistance", price["value"]), "provider_calls": 0,
            "selection": "First compatible symbol-master reference, strategy fallback, then closed-session resistance."}
