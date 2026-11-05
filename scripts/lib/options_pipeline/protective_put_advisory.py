"""protective_put_advisory.py — D32 SPEC §5: advisory protective put / collar suggestions.

For a **single-stock** position above a configured share of the book, with an earnings or
known event inside the configured window, suggest a protective put (and, when a call quote
is available, a collar) with the floor it puts under the position and what it would cost.

The system never places, sizes, stops or cancels an order (AGENTS.md §0 rule 1,
``MBI_BEHAVIOR = 0``). Every suggestion carries that fact in its own payload
(``placed_by_system: False``), and this module has no import path to a broker, a queue
writer or a CIO behavior write: it takes plain data in and returns plain data out.

Inputs are injected, never read here:

* ``positions`` — holdings rows: ``symbol``, ``account``, ``quantity``/``shares``,
  ``market_value``, ``price`` (optional ``stop_price``), optional ``asset_class``.
* ``book_value`` — the whole book, so a position's share can be measured.
* ``events`` — ``{symbol: {"event_date": "YYYY-MM-DD", "days_to_event": int, ...}}``.
  ``days_to_event`` is days until the event (negative = after it).
* ``chains`` — optional ``{symbol: {"underlying_price": float, "expirations": [
  {"exp": "YYYY-MM-DD", "dte": int, "strikes": [{"side": "put"|"call", "strike": ...,
  "bid": ..., "ask": ..., "multiplier": 100}]}]}}`` — the same snapshot shape
  ``options_advisory_candidates`` consumes.

Without a chain the cost is a **labeled estimate** from config
(``estimated_cost_pct_of_position``) and ``cost_is_estimate`` is True. A floor price is
reported only when a real strike was chosen; it is never invented from a chain that is
not there (the estimate keeps the strike only if the caller supplied one).

Only a LONG position is ever advised: a put on a short adds the exposure it claims to
remove, and ``position_value`` erases the sign, so the side is a gate
(``not_a_long_position``). ``cost_per_share`` and ``floor_after_cost`` are on the HELD
shares — ``_contracts`` may cover more (``over``) or fewer (``partial``) shares than the
position holds — and the quoted premium per covered share is reported beside them as
``cost_per_covered_share``.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA = "ProtectivePutAdvisory@v1"
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
}

#: A symbol that cannot be a single stock position we would hedge with an equity put.
_OPTION_SHAPE = (" ", "/")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Config from ``path`` (or the repo default), merged over the built-in defaults.

    An unreadable or non-object file yields the defaults with ``enabled`` unchanged —
    the advisory is not worth crashing a page over, and the defaults are conservative.
    """
    cfg = dict(DEFAULTS)
    target = Path(path) if path else Path(__file__).resolve().parents[2] / CONFIG_RELPATH
    try:
        loaded = json.loads(Path(target).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    if isinstance(loaded, dict):
        cfg.update({k: v for k, v in loaded.items() if not k.startswith("_")})
    return cfg


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def position_value(position: Mapping[str, Any]) -> float | None:
    """Market value of one holdings row, from ``market_value`` or price × quantity."""
    mv = _num(position.get("market_value"))
    if mv is not None and mv > 0:
        return mv
    price = _num(position.get("price"))
    qty = _num(position.get("quantity", position.get("shares")))
    if price and qty:
        return abs(price * qty)
    return None


def pct_of_book(value: float | None, book_value: float | None) -> float | None:
    """A position's share of the book in percent; None when the book is unknown/zero."""
    value, book = _num(value), _num(book_value)
    if not value or not book or book <= 0:
        return None
    return round(100.0 * value / book, 4)


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
        bid is not None and ask is not None and strike is not None
        and bid >= 0 and ask > 0 and ask >= bid and strike > 0
        and mult == 100 and not row.get("nonstandard")
    )


def _expiry_for(chain: Mapping[str, Any], cfg: Mapping[str, Any], days_to_event: float | None) -> Mapping[str, Any] | None:
    """Nearest expiration at or after the event (and inside the DTE bounds), else the nearest in bounds."""
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
        if after:
            return min(after, key=lambda pair: pair[0])[1]
    return min(usable, key=lambda pair: pair[0])[1]


def _pick_strike(expiry: Mapping[str, Any], side: str, target: float) -> Mapping[str, Any] | None:
    """The tradable strike closest to ``target`` on one side, preferring the lower ask on a tie."""
    rows = [
        row for row in expiry.get("strikes") or []
        if isinstance(row, Mapping) and str(row.get("side") or "").lower() == side and _quote(row)
    ]
    if not rows:
        return None
    return min(rows, key=lambda row: (abs(float(row["strike"]) - target), float(row["ask"])))


def _contracts(shares: float | None) -> tuple[int, str]:
    """(contracts, cover) — at least one contract; say honestly whether that covers the shares."""
    if shares is None or shares <= 0:
        return 1, "unknown"
    if shares < 100:
        return 1, "over"      # one contract covers more shares than the position holds
    whole = int(shares // 100)
    return max(1, whole), ("full" if abs(shares - whole * 100) < 1e-9 else "partial")


def suggest_for_position(
    position: Mapping[str, Any],
    *,
    book_value: float | None,
    event: Mapping[str, Any] | None = None,
    chain: Mapping[str, Any] | None = None,
    cfg: Mapping[str, Any] | None = None,
    now: date | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """One suggestion for one position, or ``(None, reason)`` when a gate says no.

    Gates, in order: enabled; single stock; a known positive value; at or above the size
    threshold; a known event inside the window. Nothing is ever placed.
    """
    cfg = cfg or DEFAULTS
    if not cfg.get("enabled", True):
        return None, "advisory_disabled"
    if not is_single_stock(position, cfg):
        return None, "not_a_single_stock"
    shares = _num(position.get("quantity", position.get("shares")))
    if shares is not None and shares <= 0:
        # cc-deepseek-3 second review (2026-11-05): a put on a SHORT adds the exposure it claims to remove, and
        # ``position_value`` erases the sign, so -300 shares produced a "protective put" on the wrong side. Which
        # side a position is on is a gate, not a detail: only a long can be advised.
        return None, "not_a_long_position"
    value = position_value(position)
    if value is None:
        return None, "position_value_unknown"
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

    spot = _num(position.get("price"))
    if spot is None and value and _num(position.get("quantity", position.get("shares"))):
        spot = value / abs(float(position.get("quantity", position.get("shares"))))
    stop = _num(position.get("stop_price", position.get("stop")))

    # Floor target: the broker stop when one exists (the position is already defended there),
    # otherwise the configured distance below spot.
    if stop and stop > 0:
        floor_target, floor_basis = stop, "broker_stop"
    elif spot and spot > 0:
        floor_target = spot * (1.0 - float(cfg["put_floor_pct_below_spot"]) / 100.0)
        floor_basis = f"spot_minus_{cfg['put_floor_pct_below_spot']}pct"
    else:
        return None, "no_price_or_stop_for_a_floor"

    expiry = _expiry_for(chain or {}, cfg, days) if chain else None
    put = _pick_strike(expiry, "put", floor_target) if expiry else None
    call = None
    if expiry and spot:
        call = _pick_strike(expiry, "call", spot * (1.0 + float(cfg["collar_cap_pct_above_spot"]) / 100.0))

    contracts, cover = _contracts(shares)
    covered_shares = max(1.0, contracts * 100.0)
    # cc-deepseek-3 second review (2026-11-05): ``_contracts`` deliberately labels over/partial coverage, so dividing
    # cost and floor by the covered contracts' 100s showed $20.50 a share for a hedge costing $51.25 of each of the
    # 40 held shares — and a floor $30.75 too high. The operator's per-share numbers are on the HELD shares; the
    # covered-share figure is kept, named for what it is.
    held_shares = shares if shares is not None and shares > 0 else covered_shares
    estimate_cost = round(value * float(cfg["estimated_cost_pct_of_position"]) / 100.0, 2)
    if put is not None:
        put_cost = round(float(put["ask"]) * 100.0 * contracts, 2)
        cost_usd, cost_is_estimate = put_cost, False
        floor_price = float(put["strike"])
        strike_source = "chain"
        expiry_label = str(expiry.get("exp") or expiry.get("dte"))
    else:
        cost_usd, cost_is_estimate = estimate_cost, True
        floor_price = round(floor_target, 2)
        strike_source = "target_not_a_quoted_strike" if chain else "estimate"
        expiry_label = None

    suggestion: dict[str, Any] = {
        "schema": SCHEMA,
        "symbol": str(position.get("symbol") or "").upper(),
        "account": position.get("account"),
        "shares": shares,
        "position_value": round(value, 2),
        "pct_of_book": share,
        "event": {
            "date": (event or {}).get("event_date") or (event or {}).get("date") or (event or {}).get("earnings_date"),
            "days_to_event": days,
        },
        "structure": "protective_put",
        "floor_price": floor_price,
        "floor_basis": floor_basis,
        "floor_after_cost": round(floor_price - (cost_usd / held_shares), 2),
        "floor_strike_source": strike_source,
        "expiry": expiry_label,
        "contracts": contracts,
        "cover": cover,
        "cost_usd": cost_usd,
        "cost_is_estimate": cost_is_estimate,
        "cost_per_share": round(cost_usd / held_shares, 2),
        "cost_per_covered_share": round(cost_usd / covered_shares, 2),
        "protection_per_share": round(max(0.0, (spot or value) - floor_price), 2) if spot else None,
        # The rails, restated in the payload so no consumer can mistake a suggestion for an order.
        "advisory_only": True,
        "placed_by_system": False,
        "operator_action": "Review and place yourself if you choose; the system will not place, size or cancel it.",
    }
    if expiry_label is None:
        suggestion["cost_basis"] = (
            f"LABELED ESTIMATE: {cfg['estimated_cost_pct_of_position']}% of the position value; "
            "no option chain was supplied, so this is not a quoted premium."
        )

    if call is not None and put is not None:
        credit = round(float(call["bid"]) * 100.0 * contracts, 2)
        net = round(put_cost - credit, 2)
        suggestion["collar"] = {
            "cap_price": float(call["strike"]),
            "call_credit_usd": credit,
            "net_cost_usd": net,
            "net_is_credit": net < 0,
            "note": "A collar sells upside above the cap to pay for the floor; it also limits the gain on the shares.",
        }
    return suggestion, None


def suggest_for_book(
    positions: Iterable[Mapping[str, Any]],
    *,
    book_value: float | None,
    events: Mapping[str, Mapping[str, Any]] | None = None,
    chains: Mapping[str, Mapping[str, Any]] | None = None,
    cfg: Mapping[str, Any] | None = None,
    now: date | None = None,
) -> dict[str, Any]:
    """The whole advisory: suggestions plus, for every row examined, why it was skipped."""
    cfg = cfg or DEFAULTS
    events = events or {}
    chains = chains or {}
    suggestions: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    examined = 0
    for position in positions or []:
        if not isinstance(position, Mapping):
            continue
        examined += 1
        symbol = str(position.get("symbol") or "").upper()
        suggestion, reason = suggest_for_position(
            position,
            book_value=book_value,
            event=events.get(symbol),
            chain=chains.get(symbol),
            cfg=cfg,
            now=now,
        )
        if suggestion:
            suggestions.append(suggestion)
        else:
            skipped.append({"symbol": symbol, "account": position.get("account"), "skipped": reason})
    suggestions.sort(key=lambda row: (-float(row["pct_of_book"]), row["symbol"]))
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now().astimezone().isoformat(),
        "advisory_only": True,
        "placed_by_system": False,
        "min_position_pct_of_book": float(cfg["min_position_pct_of_book"]),
        "event_window_days": [float(cfg["event_window_days_before"]), float(cfg["event_window_days_after"])],
        "examined": examined,
        "suggestions": suggestions,
        "skipped": skipped,
        "note": (
            "Advisory only. The system never places, sizes, stops or cancels an order, and it never "
            "writes a CIO behavior field; the operator places anything he chooses."
        ),
    }
