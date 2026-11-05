"""Read-only per-contract protective-put/collar economics over injected snapshots.

No contract quantity is selected. Unit prices and covered-share payoff levels describe a
standard 100-share contract, never a position-wide floor. Holdings qualify the research
question; the operator alone chooses any coverage and execution. No broker or writer path.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from lib.cio_canonical_quote import apply_canonical_quote_fields

SCHEMA = "ProtectivePutAdvisory@v2"
CONFIG_RELPATH = Path("config") / "protective_put_advisory.json"

DEFAULTS: dict[str, Any] = {
    "schema": "ProtectivePutAdvisoryConfig@v1",
    "enabled": True,
    "min_position_pct_of_book": 2.0,
    "event_window_days_before": 10,
    "event_window_days_after": 2,
    "put_floor_pct_below_spot": 10.0,
    "collar_cap_pct_above_spot": 15.0,
    "estimated_cost_pct_of_position": 2.5,
    "min_days_to_expiry": 7,
    "max_days_to_expiry": 60,
    "exclude_symbols": ["CASH"],
    # cc-deepseek-5 second review (2026-11-05): a quoted premium can exceed the position it protects. A hedge
    # costing more than this share of the position is refused, never shown with a plausible-looking number.
    "max_cost_pct_of_position": 25.0,
    # ... and a quoted strike can sit far from the floor the basis names (a broker stop of 235 beside a 150 put).
    # Past this distance the suggestion says so: the target, the distance and the direction travel with it.
    "max_floor_distance_pct_of_target": 5.0,
}

#: A symbol that cannot be a single stock position we would hedge with an equity put.
_OPTION_SHAPE = (" ", "/")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Read the documented repository config; unusable config is explicit, never enabled by fallback."""
    target = Path(path) if path is not None else Path(__file__).resolve().parents[3] / CONFIG_RELPATH
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("advisory configuration is unreadable or invalid JSON") from exc
    if not isinstance(loaded, dict):
        raise ValueError("advisory configuration must be an object")
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in loaded.items() if not k.startswith("_")})
    if not isinstance(cfg.get("enabled"), bool):
        raise ValueError("enabled must be a boolean")
    for key, default in DEFAULTS.items():
        if isinstance(default, (int, float)) and not isinstance(default, bool):
            value = _num(cfg.get(key))
            if value is None or value < 0:
                raise ValueError(f"{key} must be a finite nonnegative number")
    if float(cfg["min_days_to_expiry"]) > float(cfg["max_days_to_expiry"]):
        raise ValueError("expiry bounds are reversed")
    if not isinstance(cfg.get("exclude_symbols"), list) or not all(isinstance(s, str) for s in cfg["exclude_symbols"]):
        raise ValueError("exclude_symbols must be a list of strings")
    return cfg


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def _position_quantity(position: Mapping[str, Any]) -> float | None:
    """Existing quantity/shares aliases, preserving a real zero before trying a fallback."""
    for key in ("quantity", "shares"):
        quantity = _num(position.get(key))
        if quantity is not None:
            return quantity
    return None


def _per_share_mark(position: Mapping[str, Any]) -> dict[str, Any] | None:
    """Pure named-quote semantics, bounded to the sanctioned stored-position fields.

    The legacy current_price field is explicitly untrusted by portfolio_positions.
    A fractional bare price with no value to classify it could itself be total value.
    No quote is fetched, and a snapshot/as-of reference is never claimed to be live.
    """
    if position.get("conflicted") or position.get("not_for_valuation") or position.get("proxy"):
        return None
    explicit = "canonical_mark" in position
    canonical = _num(position.get("canonical_mark"))
    if explicit and (canonical is None or canonical <= 0):
        return None
    quantity = _position_quantity(position)
    row = dict(position)
    # Normalise aliases once so valuation, source classification and eligibility agree.
    row["shares"] = quantity
    row["quantity"] = quantity
    row.pop("qty", None)
    row.pop("value", None)
    row.pop("current_price", None)
    for key in ("market_value", "price", "mark", "last", "official_close", "previous_close", "prev_close", "close"):
        row[key] = _num(position.get(key))
    if quantity is not None and 0 < abs(quantity) < 1 and row["market_value"] is None:
        row["price"] = None  # no value evidence to disambiguate a fractional legacy price
    named = apply_canonical_quote_fields(row)
    if named.get("conflicted"):
        return None
    derived = _num(named.get("canonical_mark"))
    if explicit and derived is not None and named.get("canonical_mark_source") != "implied_from_mv":
        # Apply the same genuine-mark conflict contract to the supplied named mark.
        if apply_canonical_quote_fields({"mark": canonical, "last": derived}).get("conflicted"):
            return None
    source = position.get("canonical_mark_source") if explicit else named.get("canonical_mark_source")
    stamp = position.get("canonical_mark_as_of") if explicit else named.get("canonical_mark_as_of")
    mark = canonical if explicit else _num(named.get("canonical_mark"))
    if mark is None or mark <= 0:
        return None
    basis = (
        "implied_from_mv" if source == "implied_from_mv" else "named_canonical_mark" if explicit else "snapshot_mark"
    )
    return {
        "price": mark,
        "source": str(source) if source else "canonical_mark",
        "as_of": stamp if isinstance(stamp, str) else None,
        "basis": basis,
    }


def position_value(position: Mapping[str, Any]) -> float | None:
    """Known nonnegative market value, or a finite price × holding quantity; None is not zero."""
    mv = _num(position.get("market_value"))
    if mv is not None and mv >= 0:
        return mv
    quantity = _position_quantity(position)
    if quantity == 0:
        return 0.0
    if quantity is None:
        return None
    if _num(position.get("price")) == 0 and "canonical_mark" not in position:
        return 0.0
    mark = _per_share_mark(position)
    if mark is None:
        return None
    value = abs(mark["price"] * quantity)
    return value if math.isfinite(value) else None


def pct_of_book(value: float | None, book_value: float | None) -> float | None:
    """A position's share of the book in percent; None when the book is unknown/zero."""
    value, book = _num(value), _num(book_value)
    if not value or not book or book <= 0:
        return None
    share = (value / book) * 100.0
    return round(share, 4) if math.isfinite(share) else None


def is_single_stock(position: Mapping[str, Any], cfg: Mapping[str, Any] | None = None) -> bool:
    """True when this row is a single-stock equity position the advisory would cover."""
    cfg = cfg or DEFAULTS
    symbol = str(position.get("symbol") or "").strip().upper()
    if not symbol:
        return False
    if symbol in {str(s).strip().upper() for s in cfg.get("exclude_symbols") or ()}:
        return False
    if any(token in symbol for token in _OPTION_SHAPE):
        return False  # an option leg is not the position this suggestion protects
    asset = str(position.get("asset_class") or position.get("security_type") or "").strip().lower()
    if asset in {"cash", "option", "etf", "fund", "mutual fund"}:
        return asset not in {"cash", "option"}  # ETFs/funds may carry an event; cash/options never
    return True


def in_event_window(days_to_event: Any, cfg: Mapping[str, Any] | None = None) -> bool:
    """True when the event is inside the configured before/after window (inclusive)."""
    cfg = cfg or DEFAULTS
    days = _num(days_to_event)
    if days is None:
        return False
    return -float(cfg["event_window_days_after"]) <= days <= float(cfg["event_window_days_before"])


def _event_days(event: Mapping[str, Any] | None, now: date | None = None) -> float | None:
    """Days to the event: the supplied number wins; else derived from ``event_date``."""
    if not isinstance(event, Mapping):
        return None
    given = _num(event.get("days_to_event", event.get("days")))
    if given is not None:
        return given
    raw = event.get("event_date") or event.get("date") or event.get("earnings_date")
    if not raw:
        return None
    try:
        when = datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return float((when - (now or date.today())).days)


def _quote(row: Mapping[str, Any]) -> bool:
    """A tradable quote: positive ask, bid ≤ ask, standard multiplier, finite strike."""
    bid, ask = _num(row.get("bid")), _num(row.get("ask"))
    strike = _num(row.get("strike"))
    mult = _num(row.get("multiplier", 100))
    return bool(
        bid is not None
        and ask is not None
        and strike is not None
        and bid >= 0
        and ask > 0
        and ask >= bid
        and strike > 0
        and mult == 100
        and not row.get("nonstandard")
    )


def _expiry_for(
    chain: Mapping[str, Any], cfg: Mapping[str, Any], days_to_event: float | None
) -> Mapping[str, Any] | None:
    """Nearest in-bounds expiration that reaches the known event; never fall back before it."""
    expirations = [e for e in chain.get("expirations") or [] if isinstance(e, Mapping)]
    usable = []
    for expiry in expirations:
        dte = _num(expiry.get("dte"))
        if dte is None or dte < float(cfg["min_days_to_expiry"]) or dte > float(cfg["max_days_to_expiry"]):
            continue
        usable.append((dte, expiry))
    if not usable:
        return None
    if days_to_event is not None:
        after = [pair for pair in usable if pair[0] >= max(0.0, days_to_event)]
        if not after:
            return None
        return min(after, key=lambda pair: pair[0])[1]
    return min(usable, key=lambda pair: pair[0])[1]


def _pick_strike(expiry: Mapping[str, Any], side: str, target: float) -> Mapping[str, Any] | None:
    """The tradable strike closest to ``target`` on one side, preferring the lower ask on a tie."""
    rows = [
        row
        for row in expiry.get("strikes") or []
        if isinstance(row, Mapping) and str(row.get("side") or "").lower() == side and _quote(row)
    ]
    if not rows:
        return None
    return min(rows, key=lambda row: (abs(float(row["strike"]) - target), float(row["ask"])))


def suggest_for_position(
    position: Mapping[str, Any],
    *,
    book_value: float | None,
    event: Mapping[str, Any] | None = None,
    chain: Mapping[str, Any] | None = None,
    cfg: Mapping[str, Any] | None = None,
    now: date | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Per-contract research economics, with no selected quantity or position protection claim."""
    cfg = dict(DEFAULTS) if cfg is None else cfg
    if not cfg.get("enabled", True):
        return None, "advisory_disabled"
    if not is_single_stock(position, cfg):
        return None, "not_a_single_stock"
    shares = _position_quantity(position)
    if shares is None:
        return None, "position_quantity_unknown"
    if shares <= 0:
        return None, "not_a_long_position"
    value = position_value(position)
    if value is None:
        return None, "position_value_unknown"
    if value == 0:
        return None, "position_value_zero"
    share = pct_of_book(value, book_value)
    if share is None:
        return None, "book_value_unknown"
    if share < float(cfg["min_position_pct_of_book"]):
        return None, "below_size_threshold"
    days = _event_days(event, now)
    if days is None:
        return None, "no_event"
    if not in_event_window(days, cfg):
        return None, "outside_event_window"

    if not math.isfinite(value / shares):
        return None, "unit_economics_not_finite"
    mark = _per_share_mark(position)
    if mark is None:
        return None, "per_share_mark_unknown"
    spot = mark["price"]
    stop = _num(position.get("stop_price", position.get("stop")))
    if stop is not None and stop > 0:
        floor_target, floor_basis = stop, "broker_stop"
    elif spot > 0:
        floor_target = spot * (1.0 - float(cfg["put_floor_pct_below_spot"]) / 100.0)
        floor_basis = f"spot_minus_{cfg['put_floor_pct_below_spot']}pct"
    else:
        return None, "no_price_or_stop_for_a_floor"

    if not math.isfinite(floor_target):
        return None, "unit_economics_not_finite"

    # An explicitly supplied but unusable snapshot is not an absent snapshot.
    expiry = _expiry_for(chain, cfg, days) if chain is not None else None
    if chain is not None and expiry is None:
        return None, "no_expiry_covers_event"
    put = _pick_strike(expiry, "put", floor_target) if expiry is not None else None
    if chain is not None and put is None:
        return None, "no_usable_put_quote"
    call = (
        _pick_strike(expiry, "call", spot * (1.0 + float(cfg["collar_cap_pct_above_spot"]) / 100.0)) if expiry else None
    )

    # 100 is the standard contract multiplier, not a selected number of contracts.
    reference_value = spot * 100.0
    if not math.isfinite(reference_value) or reference_value <= 0:
        return None, "unit_economics_not_finite"
    unit_cost = (
        float(put["ask"]) * 100.0
        if put is not None
        else reference_value * (float(cfg["estimated_cost_pct_of_position"]) / 100.0)
    )
    if not math.isfinite(unit_cost):
        return None, "unit_economics_not_finite"
    unit_cost = round(unit_cost, 2)
    cost_share = (unit_cost / reference_value) * 100.0
    if not math.isfinite(cost_share):
        return None, "unit_economics_not_finite"
    if cost_share > float(cfg["max_cost_pct_of_position"]):
        return None, "cost_exceeds_position_value"
    strike = float(put["strike"]) if put is not None else None
    floor_after = round(strike - unit_cost / 100.0, 2) if strike is not None else None
    distance = round(abs(strike - floor_target), 2) if strike is not None else None
    relation = (
        ("at" if distance == 0 else "below" if strike < floor_target else "above") if strike is not None else None
    )
    far = distance is not None and distance > abs(floor_target) * (
        float(cfg["max_floor_distance_pct_of_target"]) / 100.0
    )
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "symbol": str(position.get("symbol") or "").upper(),
        "account": position.get("account"),
        "position_value": round(value, 2),
        "pct_of_book": share,
        "reference_price": spot,
        "reference_price_source": mark["source"],
        "reference_price_as_of": mark["as_of"],
        "reference_price_basis": mark["basis"],
        "event": {
            "date": (event or {}).get("event_date") or (event or {}).get("date") or (event or {}).get("earnings_date"),
            "days_to_event": days,
        },
        "structure": "protective_put",
        "economics_basis": "per_contract",
        "contract_multiplier": 100,
        "coverage_status": "not_selected",
        "coverage_note": "Contract quantity is not selected. No position-wide floor or covered/uncovered holding count is implied.",
        "position_floor_after_cost": None,
        "floor_price": strike,
        "floor_basis": floor_basis,
        "floor_target": round(floor_target, 2),
        "floor_distance": distance,
        "floor_target_relation": relation,
        "floor_strike_far_from_target": far,
        "floor_strike_source": "chain" if put is not None else "unquoted_target",
        "floor_per_covered_share_after_premium": floor_after if floor_after is not None and floor_after > 0 else None,
        "floor_after_premium_note": "Per covered share of a standard contract only; no holding coverage has been selected.",
        "expiry": str(expiry.get("exp") or expiry.get("dte")) if put is not None else None,
        "cost_per_contract_usd": unit_cost,
        "cost_per_covered_share": round(unit_cost / 100.0, 4),
        "cost_is_estimate": put is None,
        "cost_basis": (
            "Quoted ask per standard contract."
            if put is not None
            else f"LABELED ESTIMATE: {cfg['estimated_cost_pct_of_position']}% of the value of 100 reference shares; "
            "no option chain was supplied, so this is not a quoted premium or floor."
        ),
        "advisory_only": True,
        "placed_by_system": False,
        "operator_action": "Review unit economics. The operator alone chooses any quantity; the system never places, sizes or cancels an order.",
    }
    if far:
        result["floor_warning"] = (
            f"The quoted ${strike:,.2f} strike is ${distance:,.2f} {relation} the intended target "
            f"of ${floor_target:,.2f} ({floor_basis}); it does not defend that target level."
        )
    if floor_after is not None and floor_after <= 0:
        result["floor_after_premium_note"] = (
            "Premium meets or exceeds the quoted strike; no positive covered-share floor remains."
        )
    if call is not None and put is not None:
        if shares < 100:
            result["collar_unavailable_reason"] = "insufficient_shares_for_standard_covered_call"
        else:
            credit = float(call["bid"]) * 100.0
            if not math.isfinite(credit):
                result["collar_unavailable_reason"] = "call_unit_economics_not_finite"
                return result, None
            credit = round(credit, 2)
            net = round(unit_cost - credit, 2)
            result["collar_per_contract"] = {
                "cap_price": float(call["strike"]),
                "required_owned_shares_per_contract": 100,
                "call_credit_per_contract_usd": credit,
                "net_cost_per_contract_usd": net,
                "net_is_credit": net < 0,
                "note": "Unit economics only. A standard short call requires 100 owned shares; quantity is not selected. Upside above the cap is exchanged for premium.",
            }
    return result, None


def suggest_for_book(
    positions: Iterable[Mapping[str, Any]],
    *,
    book_value: float | None,
    events: Mapping[str, Mapping[str, Any]] | None = None,
    chains: Mapping[str, Mapping[str, Any]] | None = None,
    cfg: Mapping[str, Any] | None = None,
    now: date | None = None,
) -> dict[str, Any]:
    """Project injected rows into unit economics or an explicit unavailable/skipped reason."""
    cfg = dict(DEFAULTS) if cfg is None else cfg
    positions = list(positions)
    values = [position_value(position) for position in positions]
    book = _num(book_value)
    book_known = book is not None and book >= 0 and not (book == 0 and any(v is not None and v > 0 for v in values))
    events = events or {}
    chains = chains or {}
    suggestions, skipped = [], []
    examined = 0
    for position in positions:
        examined += 1
        symbol = str(position.get("symbol") or "").upper()
        suggestion, reason = suggest_for_position(
            position, book_value=book_value, event=events.get(symbol), chain=chains.get(symbol), cfg=cfg, now=now
        )
        if suggestion is not None:
            suggestions.append(suggestion)
        else:
            skipped.append({"symbol": symbol, "account": position.get("account"), "skipped": reason})
    suggestions.sort(key=lambda row: (-float(row["pct_of_book"]), row["symbol"]))
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "ok" if book_known else "unavailable",
        "book_value": book,
        "book_value_basis": "provided",
        "position_valuations_complete": all(value is not None for value in values),
        "unvalued_positions": sum(value is None for value in values),
        "advisory_only": True,
        "placed_by_system": False,
        "economics_basis": "per_contract",
        "coverage_status": "not_selected",
        "examined": examined,
        "suggestions": suggestions,
        "skipped": skipped,
        "note": "Per-contract economics only; the system never selects a quantity, places, stops or cancels an order.",
    }
