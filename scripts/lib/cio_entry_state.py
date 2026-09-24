"""CIO entry state — the CIO's call on whether a tracked name is ready to buy, getting close, or not yet.

Operator decisions 2026-09-15:
  (a) the CIO is in the process for entry state and BUY;
  (b) the operator is alerted, and the CIO is alerted;
  (c) small caps are in scope and labeled as small caps.

This module is pure: it turns one symbol's evidence into a state and renders the two messages.
It never sizes, orders, sets stops or writes to a broker. BUY_READY means "the CIO says this is ready
for your review", and the operator still decides.

States (most actionable first):
  BUY_READY   price inside the plan's entry zone, plan R:R >= MIN_RR, fresh quote, not blocked
  ENTRY_NEAR  price within NEAR_PCT above the zone top (or within one ATR), otherwise the same
  NOT_YET     a valid plan exists, but price is not at or near the zone
  BLOCKED     a hard reason prevents an entry call (quarantine, CIO disposal call, wash sale,
              stale quote, broken plan, earnings inside the blackout)
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

MIN_RR = 2.0
NEAR_PCT = 3.0
MAX_QUOTE_AGE_H = 4.0
EARNINGS_BLACKOUT_DAYS = 2
BLOCKING_CIO_ACTIONS = {"AVOID", "SELL", "EXIT", "TRIM", "TRIM_REVIEW", "REDUCE"}
ACTIONABLE = ("BUY_READY", "ENTRY_NEAR")


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None  # NaN → None


def _days_until(d: Any, today: date) -> int | None:
    if not d:
        return None
    try:
        day = d if isinstance(d, date) else datetime.fromisoformat(str(d)[:10]).date()
    except ValueError:
        return None
    return (day - today).days


def evaluate(ev: dict, *, today: date | None = None) -> dict:
    """ev keys: symbol, price, quote_age_h, entry_low, entry_high, stop, target, atr, quality_state,
    cio_action, wash_blocked, held, earnings_date, market_cap_label (dict from market_cap_label.cap_label),
    catalyst (str), plan_source, rsi. Returns {state, reasons, distance_pct, rr, ...}."""
    today = today or datetime.now(timezone.utc).date()
    sym = str(ev.get("symbol") or "").upper()
    price, lo, hi = _f(ev.get("price")), _f(ev.get("entry_low")), _f(ev.get("entry_high"))
    stop, target, atr = _f(ev.get("stop")), _f(ev.get("target")), _f(ev.get("atr"))
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    ref_entry = hi if hi is not None else lo
    rr = None
    if ref_entry and stop is not None and target is not None and ref_entry > stop:
        rr = round((target - ref_entry) / (ref_entry - stop), 2)
    blocked: list[str] = []
    if price is None:
        blocked.append("no current price")
    age = _f(ev.get("quote_age_h"))
    if age is not None and age > MAX_QUOTE_AGE_H:
        blocked.append(f"quote is {age:.1f}h old")
    if lo is None and hi is None:
        blocked.append("no entry zone in the plan")
    if stop is None or target is None or rr is None:
        blocked.append("plan has no valid stop/target")
    elif rr < MIN_RR:
        blocked.append(f"plan R:R {rr} is below {MIN_RR}")
    if str(ev.get("quality_state") or "").upper() == "QUARANTINED":
        blocked.append("quality gate quarantined")
    cio_action = str(ev.get("cio_action") or "").upper()
    if cio_action in BLOCKING_CIO_ACTIONS:
        blocked.append(f"CIO decision is {cio_action}")
    if ev.get("wash_blocked"):
        blocked.append("wash-sale window")
    if price is not None and stop is not None and price <= stop:
        blocked.append("price is at or below the plan stop")
    earn_days = _days_until(ev.get("earnings_date"), today)
    if earn_days is not None and 0 <= earn_days <= EARNINGS_BLACKOUT_DAYS:
        blocked.append(f"earnings in {earn_days} day(s)")

    distance_pct = None
    if price is not None and hi is not None and hi > 0:
        distance_pct = round((price - hi) / hi * 100.0, 2) if price > hi else (
            round((price - lo) / lo * 100.0, 2) if (lo and price < lo) else 0.0)

    if blocked:
        state = "BLOCKED"
    elif lo is not None and hi is not None and lo <= price <= hi:
        state = "BUY_READY"
    elif hi is not None and price > hi and (
            (price - hi) / hi * 100.0 <= NEAR_PCT or (atr is not None and price - hi <= atr)):
        state = "ENTRY_NEAR"
    else:
        state = "NOT_YET"
    return {
        "symbol": sym, "state": state, "reasons": blocked, "distance_pct": distance_pct, "rr": rr,
        "price": price, "entry_low": lo, "entry_high": hi, "stop": stop, "target": target,
        "quality_state": ev.get("quality_state"), "cio_action": cio_action or None,
        "market_cap_label": (ev.get("market_cap_label") or {}).get("code"),
        "catalyst": ev.get("catalyst"), "plan_source": ev.get("plan_source"), "held": bool(ev.get("held")),
        "earnings_in_days": earn_days,
    }


def _money(v: float | None) -> str:
    return "—" if v is None else (f"${v:,.2f}" if v >= 1 else f"${v:.4f}")


def _cap_text(ev: dict) -> str:
    try:
        from lib.market_cap_label import pill
    except ImportError:
        from scripts.lib.market_cap_label import pill
    return pill(ev.get("market_cap_label") or {})


def _identity_text(ev: dict) -> str:
    """Company name and sector/industry, when known. Empty string when not.

    description_1s already reads 'Esco Technologies Inc — Scientific & Technical
    Instruments', so the industry is dropped when it would merely repeat that tail.
    """
    company = (ev.get("company") or "").strip()
    sector = (ev.get("sector") or "").strip()
    industry = (ev.get("industry") or "").strip()
    if not (company or sector or industry):
        return ""
    if company:
        head = company.rstrip(".")
        if sector and sector.lower() not in head.lower():
            head = f"{head} · {sector}"
        return head
    return " · ".join(p for p in (sector, industry) if p)


def render_operator(result: dict, ev: dict) -> str:
    """Plain operator text. Header is the routing sentinel ('CIO entry —'); no WAIT/AVOID wording."""
    head = "🟢 CIO entry — BUY READY" if result["state"] == "BUY_READY" else "🟡 CIO entry — getting close"
    where = ("price is inside the entry zone" if result["state"] == "BUY_READY"
             else f"price is {result['distance_pct']:+.1f}% from the top of the entry zone")
    lines = [f"{head}: {result['symbol']}"]
    # Identity before mechanics. Until 2026-09-21 this alert named a bare ticker and a
    # market-cap pill: the operator was asked to decide on "ESE" without being told it
    # is Esco Technologies, a Technology / Scientific & Technical Instruments name.
    # Every field came from symbol_profiles, which the runner never queried.
    ident = _identity_text(ev)
    if ident:
        lines.append(ident)
    cap = _cap_text(ev)
    if cap:
        lines.append(cap)
    lines += [
        f"Price {_money(result['price'])} · {where}",
        f"Zone {_money(result['entry_low'])}–{_money(result['entry_high'])} · stop {_money(result['stop'])} · "
        f"target {_money(result['target'])} · R:R {result['rr']}",
    ]
    if result.get("catalyst"):
        lines.append(f"Catalyst: {str(result['catalyst'])[:160]}")
    if result.get("cio_action"):
        lines.append(f"CIO view: {result['cio_action'].replace('_', ' ').title()}")
    if result.get("held"):
        lines.append("Already held — this would be an add.")
    # Stage 1D — institutional equity + options packet (BUY_READY and ENTRY_NEAR).
    if result.get("state") in ("BUY_READY", "ENTRY_NEAR"):
        packet_block = _institutional_packet_block(result, ev, for_cio=False)
        if packet_block:
            lines.extend(packet_block.split("\n"))
    lines.append("Advisory only: review and decide; nothing is placed automatically.")
    return "\n".join(lines)


def render_digest(results: list[dict]) -> str:
    """One operator message for the names past the per-run alert cap (same routing sentinel)."""
    ready = [r["symbol"] for r in results if r["state"] == "BUY_READY"]
    near = [r["symbol"] for r in results if r["state"] == "ENTRY_NEAR"]
    lines = [f"🟢 CIO entry — {len(results)} more names ready or getting close"]
    if ready:
        lines.append("BUY READY: " + ", ".join(ready))
    if near:
        lines.append("Getting close: " + ", ".join(near))
    lines.append("Open the Watch desk for zones, stops and targets. Advisory only.")
    return "\n".join(lines)


def _institutional_packet_block(result: dict, ev: dict, *, for_cio: bool) -> str:
    """Stage 1D institutional packet; degrade to legacy alt line if module absent."""
    try:
        from scripts.lib.cio_options_fluency import (  # noqa: PLC0415
            format_buy_ready_packet_lines,
            build_buy_ready_packet,
        )
    except ImportError:
        try:
            from lib.cio_options_fluency import (  # type: ignore[no-redef]  # noqa: PLC0415
                format_buy_ready_packet_lines,
                build_buy_ready_packet,
            )
        except ImportError:
            return _options_alt_line_legacy(result)
    merged = {
        **(ev or {}),
        "symbol": result.get("symbol"),
        "plan_source": result.get("plan_source") or (ev or {}).get("plan_source"),
        "catalyst": result.get("catalyst") or (ev or {}).get("catalyst"),
        "held": result.get("held") if result.get("held") is not None else (ev or {}).get("held"),
        "atr": (ev or {}).get("atr"),
    }
    packet = build_buy_ready_packet(result, merged)
    cap = _cap_text(ev) if for_cio else ""
    lines = format_buy_ready_packet_lines(packet, for_cio=for_cio, cap_label=cap or None)
    if for_cio:
        lines.append(
            "Confirm or refute the equity entry and options alternative (Approve/Reject/Modify) for the operator."
        )
    return "\n".join(lines)


def _options_alt_line_legacy(result: dict) -> str:
    """Fallback single-line alt when full packet module cannot import."""
    try:
        from scripts.lib.cio_options_fluency import (  # noqa: PLC0415
            format_entry_options_alternative_block,
            select_entry_options_alternative,
        )
    except ImportError:
        try:
            from lib.cio_options_fluency import (  # type: ignore[no-redef]  # noqa: PLC0415
                format_entry_options_alternative_block,
                select_entry_options_alternative,
            )
        except ImportError:
            return ""
    alt = select_entry_options_alternative(
        str(result.get("symbol") or ""),
        entry_low=result.get("entry_low"),
        entry_high=result.get("entry_high"),
        stop=result.get("stop"),
        target=result.get("target"),
    )
    return format_entry_options_alternative_block(alt)


def render_cio(result: dict, ev: dict) -> str:
    state = "BUY_READY" if result["state"] == "BUY_READY" else "ENTRY_NEAR"
    cap = _cap_text(ev)
    head = (
        f"Entry state {state} for {result['symbol']}{' (' + cap + ')' if cap else ''}."
    )
    if result.get("state") in ("BUY_READY", "ENTRY_NEAR"):
        packet_block = _institutional_packet_block(result, ev, for_cio=True)
        if packet_block:
            # for_cio packet already opens with Entry state line — avoid double head when present
            if packet_block.startswith("Entry state"):
                return packet_block
            return f"{head}\n{packet_block}"
    return (
        f"{head} price {_money(result['price'])}, zone {_money(result['entry_low'])}–"
        f"{_money(result['entry_high'])}, stop {_money(result['stop'])}, target "
        f"{_money(result['target'])}, R:R {result['rr']}. Plan source "
        f"{result.get('plan_source') or 'unknown'}. Confirm or refute the entry for the operator."
    )


def transition_key(result: dict, day: date | None = None) -> str:
    """One alert per symbol per state per day."""
    day = day or datetime.now(timezone.utc).date()
    return f"cio_entry:{result['symbol']}:{result['state']}:{day.isoformat()}"
