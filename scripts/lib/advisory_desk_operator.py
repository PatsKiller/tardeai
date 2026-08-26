"""Advisory Desk operator-grade truth — field-state, freshness, and joins.

READ_ONLY_ADVISORY. Zero broker / order / stop / risk / 2FA authority.
MEMORY_BEHAVIOR_INFLUENCE remains 0. This module never mutates production
behavior; it only attaches explicit provenance so the operator can see
what is known, how current it is, and why a field is blank.

Do not invent prices, analyst targets, or memory. Missing is labeled.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

OPERATOR_TRUTH_VERSION = "advisory.operator.v1"
CONTRACT = "advisory_desk.operator.v1"
AUTHORITY = "READ_ONLY_ADVISORY"

AVAILABLE = "AVAILABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
STALE = "STALE"
CONFLICTED = "CONFLICTED"
NOT_CONFIGURED = "NOT_CONFIGURED"
NOT_RUN = "NOT_RUN"

FRESH_CURRENT = "CURRENT"
FRESH_STALE = "STALE"
FRESH_EXPIRED = "EXPIRED"
FRESH_UNAVAILABLE = "UNAVAILABLE"
FRESH_NO_PRODUCER = "NO_PRODUCER"

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
PARTIAL = "PARTIAL"
FAILED = "FAILED"

# Desk cache policy is owned by advisory_desk.DEFAULT_MAX_AGE_S (300s).
# These thresholds classify *source* clocks, not process clocks.
FACTS_STALE_S = 6 * 3600
FACTS_EXPIRED_S = 24 * 3600
OPINION_STALE_S = 18 * 3600
OPINION_EXPIRED_S = 36 * 3600
WATCH_STALE_S = 6 * 3600
REENTRY_STALE_S = 6 * 3600
MEMORY_STALE_S = 36 * 3600
STREET_STALE_S = 14 * 86400

# The scheduled daily producer that writes SENSES/MEMORY shadow receipts at
# influence=0 (scripts/advisory_shadow_seed.py). Once wired, these sources have
# a real producer, so an aged receipt is a genuine STALE — not NO_PRODUCER.
SHADOW_SEED_PRODUCER = "advisory_shadow_seed"

WATCH_CONTRACT = "watch_intelligence.broker.v1"

KEEP_REENTRY_STATES = frozenset({
    "READY TO REVIEW",
    "NEAR ENTRY",
    "OVERSOLD REVIEW",
    "WASH BLOCK",
    "OVERBOUGHT WAIT",
    "STALE",
    "MISSING MARKET",
    "MISSING PLAN",
})

SETUP_WATCH = "WATCH"
SETUP_NEAR_TRIGGER = "NEAR_TRIGGER"
SETUP_REVIEW_NOW = "REVIEW_NOW"
SETUP_WAIT_DATA = "WAIT_DATA"
SETUP_STALE = "STALE"
SETUP_BLOCKED = "BLOCKED"
SETUP_AVOID = "AVOID"
SETUP_MANAGING = "MANAGING"

WATCH_FILTERS = (
    "all",
    "needs_attention",
    "near_trigger",
    "review_now",
    "starred",
    "strongest_evidence",
    "catalyst_upcoming",
    "needs_data",
    "stale",
    "avoid",
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STATE_DIR = _PROJECT_ROOT / "data" / "portfolios" / "state"
_RUNTIME = _PROJECT_ROOT / "data" / "runtime"
_CIO = _PROJECT_ROOT / "data" / "cio"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def parse_ts(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if hasattr(value, "isoformat") and not isinstance(value, str):
        try:
            return parse_ts(value.isoformat())
        except Exception:
            return None
    s = str(value).strip()
    if not s:
        return None
    for suffix in (" ET", " EST", " EDT", " UTC"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            return datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]), tzinfo=timezone.utc)
        except ValueError:
            return None
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def age_seconds(value: Any, *, now: Optional[datetime] = None) -> Optional[float]:
    ts = parse_ts(value)
    if ts is None:
        return None
    return max(0.0, ((now or _now()) - ts).total_seconds())


def _f(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        n = float(value)
        return n if n == n else None
    except (TypeError, ValueError):
        return None


def field_state(
    value: Any = None,
    *,
    state: str = AVAILABLE,
    source: Optional[str] = None,
    as_of: Any = None,
    freshness: Optional[str] = None,
    quality: Optional[str] = None,
    reason: Optional[str] = None,
    display: Optional[str] = None,
) -> dict[str, Any]:
    """Canonical displayed-field envelope. Never a bare null + em dash."""
    if freshness is None:
        if state == AVAILABLE:
            freshness = FRESH_CURRENT
        elif state == STALE:
            freshness = FRESH_STALE
        elif state == NOT_APPLICABLE:
            freshness = None
        else:
            freshness = FRESH_UNAVAILABLE
    return {
        "value": value,
        "state": state,
        "source": source,
        "as_of": str(as_of) if as_of not in (None, "") else None,
        "freshness": freshness,
        "quality": quality or state,
        "reason": reason,
        "display": display,
    }


def classify_freshness(
    as_of: Any,
    *,
    stale_s: float,
    expired_s: float,
    now: Optional[datetime] = None,
) -> str:
    age = age_seconds(as_of, now=now)
    if age is None:
        return FRESH_UNAVAILABLE
    if age >= expired_s:
        return FRESH_EXPIRED
    if age >= stale_s:
        return FRESH_STALE
    return FRESH_CURRENT


def no_producer_freshness(as_of: Any, *, stale_s: float, now: Optional[datetime] = None) -> str:
    """Freshness for a source with no scheduled producer.

    SENSES and MEMORY now have a daily producer (SHADOW_SEED_PRODUCER) and use
    classify_freshness directly. This helper remains for any genuinely
    producer-less source: an aged receipt there is *informational*, not a job
    that fell behind — stamp NO_PRODUCER rather than a misleading STALE.
    """
    f = classify_freshness(as_of, stale_s=stale_s, expired_s=7 * 86400, now=now)
    return FRESH_NO_PRODUCER if f in (FRESH_STALE, FRESH_EXPIRED) else f


def na(reason: str, *, source: Optional[str] = None) -> dict[str, Any]:
    return field_state(None, state=NOT_APPLICABLE, source=source, reason=reason, display="N/A")


def missing(reason: str, *, source: Optional[str] = None, as_of: Any = None) -> dict[str, Any]:
    return field_state(
        None, state=DATA_UNAVAILABLE, source=source, as_of=as_of,
        freshness=FRESH_UNAVAILABLE, reason=reason, display="unavailable",
    )


def _unwrap(obj: Any) -> Any:
    if isinstance(obj, dict) and "value" in obj and ("state" in obj or "source" in obj or "freshness_state" in obj):
        return obj.get("value")
    return obj


def _card_of(item: dict[str, Any]) -> dict[str, Any]:
    card = item.get("card")
    if isinstance(card, dict):
        return card
    return item if isinstance(item, dict) else {}


def cache_meta(desk: dict[str, Any], *, cache_path: Optional[Path] = None, now: Optional[datetime] = None) -> dict[str, Any]:
    """Classify the deterministic desk snapshot. Does not invent a second policy."""
    now = now or _now()
    data = desk.get("data") if isinstance(desk.get("data"), dict) else {}
    computed = data.get("computed_at") or desk.get("computed_at")
    hit = bool(desk.get("cache_hit"))
    age = desk.get("cache_age_s")
    if age is None:
        age = age_seconds(computed, now=now)
        if age is None and cache_path and cache_path.exists():
            age = max(0.0, now.timestamp() - cache_path.stat().st_mtime)
    try:
        from lib.data_broker.advisory_desk import DEFAULT_MAX_AGE_S
        max_age = float(DEFAULT_MAX_AGE_S)
    except Exception:
        max_age = 300.0
    if computed is None and age is None:
        state = FRESH_UNAVAILABLE
    elif age is not None and age > FACTS_EXPIRED_S:
        state = FRESH_EXPIRED
    elif age is not None and age > max(max_age, FACTS_STALE_S):
        state = FRESH_STALE
    elif age is not None and age > max_age:
        # Past the builder window but not yet "facts stale". Label STALE so
        # the API cannot call a bypassed 23h snapshot current.
        state = FRESH_STALE
    else:
        state = FRESH_CURRENT
    return {
        "desk_computed_at": computed,
        "desk_cache_age_seconds": round(float(age), 1) if age is not None else None,
        "desk_cache_hit": hit,
        "desk_freshness_state": state,
        "desk_cache_policy_s": max_age,
    }


def _parse_holdings_source_clock(raw: Any) -> tuple[datetime | None, str | None]:
    """Parse a holdings.json source clock to an aware datetime.

    ``as_of`` is date-only (midnight UTC → already STALE by evening ET). The
    repricer stamps ``last_repriced`` / ``generated_at`` with an `` ET`` suffix
    (e.g. ``2026-08-19 16:45:01 ET``) that is the authoritative price clock.
    Never let a date-only label masquerade as a live mark.
    """
    if raw is None:
        return None, None
    s = str(raw).strip()
    if not s:
        return None, None
    try:
        from brokers.quote_time import parse_quote_ts
        dt = parse_quote_ts(s)
        if dt is not None:
            return dt.astimezone(timezone.utc), s
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc), s
    except Exception:
        return None, None


def holdings_source_freshness(*, now: datetime | None = None) -> dict[str, Any]:
    """Freshness of the underlying holdings.json clock — not desk-build cache.

    Prefers the repricer price clock (``last_repriced`` / ``generated_at``)
    over the date-only ``as_of`` label. The position-list clock
    (``positions_built_at``) is intentionally not used: it is when the list was
    constructed, not when prices were last refreshed.
    """
    now = now or datetime.now(timezone.utc)
    raw = _load_json(_STATE_DIR / "holdings.json")
    as_of, source_field = None, None
    for field in ("last_repriced", "generated_at", "as_of", "asOf"):
        candidate = raw.get(field)
        dt, label = _parse_holdings_source_clock(candidate)
        if dt is not None:
            as_of, source_field = label, field
            break
        if candidate and source_field is None:
            # Preserve a present-but-unparseable value for the honest fallback.
            source_field = field
    dt = None
    if as_of:
        dt, _ = _parse_holdings_source_clock(as_of)
    if dt is None:
        state = FRESH_UNAVAILABLE
        age = None
    else:
        age = (now - dt).total_seconds()
        if age > FACTS_EXPIRED_S:
            state = FRESH_EXPIRED
        elif age > FACTS_STALE_S:
            state = FRESH_STALE
        else:
            state = FRESH_CURRENT
    return {
        "holdings_source_as_of": as_of,
        "holdings_source_age_seconds": round(age, 1) if age is not None else None,
        "holdings_source_freshness": state,
        "holdings_source_clock_field": source_field,
        "holdings_reprice_source": raw.get("reprice_source"),
    }


def compute_desk_health(
    *,
    structural_ok: bool,
    plausibility_pass: bool,
    fact_freshness: str,
    source_completeness: str,
    opinion_freshness: str,
    reentry_freshness: str,
    watch_freshness: str,
    memory_health: str,
    holdings_source_freshness: str | None = None,
) -> dict[str, Any]:
    dims = {
        "STRUCTURAL_VALIDATION": "PASS" if structural_ok else "FAIL",
        "PLAUSIBILITY": "PASS" if plausibility_pass else "FAIL",
        "FACT_FRESHNESS": fact_freshness,
        "FACT_FRESHNESS_SCOPE": "desk_build_cache",
        "HOLDINGS_SOURCE_FRESHNESS": holdings_source_freshness or "NOT_EVALUATED",
        "SOURCE_COMPLETENESS": source_completeness,
        "OPINION_FRESHNESS": opinion_freshness,
        "REENTRY_FRESHNESS": reentry_freshness,
        "WATCH_INTELLIGENCE_FRESHNESS": watch_freshness,
        "MEMORY_PROVIDER_HEALTH": memory_health,
    }
    if not structural_ok:
        overall = FAILED
        reason = "structural validation failed"
    elif holdings_source_freshness in (FRESH_STALE, FRESH_EXPIRED):
        overall = STALE
        reason = (
            "holdings source clock is "
            f"{holdings_source_freshness}; desk-build FACT_FRESHNESS={fact_freshness} "
            "is cache age only"
        )
    elif fact_freshness == FRESH_EXPIRED:
        overall = STALE
        reason = "deterministic facts expired"
    elif fact_freshness == FRESH_STALE:
        overall = STALE
        reason = "deterministic facts stale"
    elif fact_freshness == FRESH_UNAVAILABLE:
        overall = FAILED
        reason = "deterministic facts unavailable"
    elif source_completeness in (PARTIAL, DEGRADED) or watch_freshness in (FRESH_STALE, FRESH_UNAVAILABLE) or reentry_freshness in (FRESH_STALE, FRESH_UNAVAILABLE):
        overall = PARTIAL
        reason = "one or more source families incomplete or stale"
    elif opinion_freshness in (FRESH_STALE, FRESH_EXPIRED):
        overall = DEGRADED
        reason = "prior synthesis / Flash opinions are old; facts may still be current"
    elif memory_health in (FAILED,):
        overall = DEGRADED
        reason = "memory provider unhealthy"
    elif not plausibility_pass:
        overall = DEGRADED
        reason = "plausibility gate FAIL"
    else:
        overall = HEALTHY
        reason = "structural pass and facts current"
    return {
        "overall": overall,
        "reason": reason,
        "dimensions": dims,
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def load_live_holdings() -> dict[tuple[str, str], dict[str, Any]]:
    raw = _load_json(_STATE_DIR / "holdings.json")
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for h in raw.get("holdings") or []:
        if not isinstance(h, dict):
            continue
        sym = str(h.get("symbol") or "").strip().upper()
        if not sym or sym == "CASH" or h.get("is_cash"):
            continue
        acct = str(h.get("account") or "")
        out[(sym, acct)] = h
        out.setdefault((sym, ""), h)
    return out


def load_reentry_projection() -> dict[str, Any]:
    """Canonical Re-Entry Decision Desk projection (latest artifact, no rebuild)."""
    path = _RUNTIME / "reentry_decision_desk_latest.json"
    raw = _load_json(path)
    rows = raw.get("rows") if isinstance(raw.get("rows"), list) else []
    if not rows and isinstance(raw.get("data"), dict):
        rows = raw["data"].get("rows") or []
    by: dict[str, dict[str, Any]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "").strip().upper()
        if sym:
            by[sym] = r
    as_of = raw.get("generated_at") or raw.get("as_of") or raw.get("computed_at")
    if path.exists() and not as_of:
        as_of = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    return {
        "ok": bool(raw.get("ok", bool(rows))),
        "as_of": as_of,
        "source": "reentry_decision_desk_latest.json",
        "freshness": classify_freshness(as_of, stale_s=REENTRY_STALE_S, expired_s=FACTS_EXPIRED_S),
        "row_count": len(rows),
        "by_symbol": by,
        "path": str(path),
    }


def project_reentry(sym: str, raw: Optional[dict[str, Any]], *, as_of: Any, freshness: str) -> dict[str, Any]:
    if not raw:
        return {
            "symbol": sym,
            "state": field_state(None, state=DATA_UNAVAILABLE, source="reentry_decision_desk",
                                 reason="no_reentry_row", freshness=FRESH_UNAVAILABLE),
            "available": False,
            "as_of": as_of,
            "freshness": freshness,
            "source": "reentry_decision_desk",
        }
    intel = raw.get("intel") if isinstance(raw.get("intel"), dict) else {}
    advisory = raw.get("advisory") if isinstance(raw.get("advisory"), dict) else {}
    price = _f(raw.get("price") if raw.get("price") is not None else intel.get("price"))
    low = _f(raw.get("entry_low") if raw.get("entry_low") is not None else raw.get("reentry_range_low"))
    high = _f(raw.get("entry_high") if raw.get("entry_high") is not None else raw.get("reentry_range_high"))
    rsi = _f(raw.get("rsi") if raw.get("rsi") is not None else intel.get("rsi"))
    dist = intel.get("distance_pct")
    if dist is None:
        dist = raw.get("distance_pct")
    dist_f = _f(dist)
    state = intel.get("state") or raw.get("reentry_state") or "WAIT"
    reason = intel.get("reason") or advisory.get("reason") or raw.get("rationale") or ""
    action = intel.get("action") or advisory.get("action") or raw.get("next_action") or ""
    wash = intel.get("wash_blocked")
    if wash is None:
        wash = raw.get("wash_blocked")
    if dist_f == 0:
        dist_label = "IN ZONE"
    elif dist_f is None:
        dist_label = None
    elif dist_f > 0:
        dist_label = f"{dist_f:+.1f}% above zone"
    else:
        dist_label = f"{dist_f:+.1f}% below zone"
    last_exit = raw.get("last_exit") or raw.get("exit") or {}
    if not isinstance(last_exit, dict):
        last_exit = {"summary": last_exit}
    return {
        "symbol": sym,
        "available": True,
        "as_of": as_of or raw.get("as_of") or intel.get("as_of"),
        "freshness": freshness,
        "source": "reentry_decision_desk",
        "state": field_state(state, source="reentry_decision_desk", as_of=as_of, freshness=freshness),
        "price": field_state(price, source="reentry_decision_desk", as_of=as_of, freshness=freshness)
                 if price is not None else missing("no_reentry_price", source="reentry_decision_desk"),
        "entry_low": field_state(low, source="reentry_decision_desk", as_of=as_of)
                     if low is not None else missing("no_entry_zone", source="reentry_decision_desk"),
        "entry_high": field_state(high, source="reentry_decision_desk", as_of=as_of)
                      if high is not None else missing("no_entry_zone", source="reentry_decision_desk"),
        "entry_zone_display": (
            f"${low:.2f}–${high:.2f}" if low is not None and high is not None else None
        ),
        "distance_pct": field_state(dist_f, source="reentry_decision_desk", as_of=as_of)
                        if dist_f is not None else missing("no_distance", source="reentry_decision_desk"),
        "distance_label": dist_label,
        "rsi": field_state(rsi, source="reentry_decision_desk", as_of=as_of)
               if rsi is not None else missing("no_rsi", source="reentry_decision_desk"),
        "rsi_band": "40–70",
        "wash_blocked": bool(wash),
        "wash_status": "BLOCKED" if wash else "CLEAR",
        "next_action": field_state(action or None, source="reentry_decision_desk", as_of=as_of)
                       if action else missing("no_next_action", source="reentry_decision_desk"),
        "reason": reason,
        "last_exit": last_exit,
        "confirmations": advisory.get("confirmations") or raw.get("confirmations"),
        "why": reason,
        "raw_state": state,
    }


def join_watch_intelligence(symbols: list[str]) -> dict[str, Any]:
    """Consume watch_intelligence.broker.v1. Never revive watch_decision_desk."""
    wanted = [s.strip().upper() for s in symbols if s and str(s).strip()]
    wanted = list(dict.fromkeys(wanted))
    as_of = None
    items: dict[str, dict[str, Any]] = {}
    error = None
    try:
        from lib.watchlist_intelligence import list_intelligence
        from lib.data_broker.watch_intelligence import compose_broker_item, CONTRACT_VERSION
        raw = list_intelligence(symbols=wanted, limit=max(len(wanted), 1), priority_only=False, offset=0)
        cards = {str(c.get("symbol") or "").upper(): c for c in (raw.get("cards") or []) if isinstance(c, dict)}
        as_of = raw.get("generated_at") or raw.get("as_of")
        for sym in wanted:
            card = cards.get(sym)
            try:
                composed = compose_broker_item(sym, card=card) if card is not None else compose_broker_item(sym)
            except Exception as exc:  # noqa: BLE001
                items[sym] = {"ok": False, "symbol": sym, "error": type(exc).__name__}
                continue
            items[sym] = composed
            if composed.get("ok") and as_of is None:
                as_of = (composed.get("card") or {}).get("price_as_of")
        contract = CONTRACT_VERSION
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        contract = WATCH_CONTRACT
        items = {s: {"ok": False, "symbol": s, "error": error} for s in wanted}
    # Freshness is the newest quote we actually joined.
    quote_times = []
    for it in items.values():
        card = _card_of(it) if it.get("ok") else {}
        if card.get("price_as_of"):
            quote_times.append(card.get("price_as_of"))
    newest = None
    for t in quote_times:
        ts = parse_ts(t)
        if ts and (newest is None or ts > parse_ts(newest)):  # type: ignore[operator]
            newest = t
    return {
        "contract": contract,
        "as_of": newest or as_of,
        "freshness": classify_freshness(newest or as_of, stale_s=WATCH_STALE_S, expired_s=FACTS_EXPIRED_S),
        "error": error,
        "items": items,
        "coverage": sum(1 for it in items.values() if it.get("ok")),
        "requested": len(wanted),
        "source": "watch_intelligence.broker.v1",
    }


def project_watch(composed: dict[str, Any]) -> dict[str, Any]:
    if not composed or not composed.get("ok"):
        return {
            "available": False,
            "reason": (composed or {}).get("error") or "symbol_not_found",
            "contract": WATCH_CONTRACT,
        }
    card = _card_of(composed)
    item = composed.get("item") if isinstance(composed.get("item"), dict) else {}
    domains = item.get("domains") if isinstance(item.get("domains"), dict) else {}
    street = card.get("street_consensus") if isinstance(card.get("street_consensus"), dict) else {}
    last = _f(card.get("last"))
    q_asof = card.get("price_as_of")
    q_src = card.get("price_source") or "watch_canonical_quote"
    q_fresh = str(card.get("freshness_state") or classify_freshness(q_asof, stale_s=WATCH_STALE_S, expired_s=FACTS_EXPIRED_S))
    target = _f(street.get("target_mean") if street else card.get("target_mean"))
    target_as_of = street.get("as_of") if street else None
    analysts = street.get("analyst_count") if street else card.get("analyst_count")
    street_fresh = classify_freshness(target_as_of, stale_s=STREET_STALE_S, expired_s=90 * 86400)
    rating = card.get("street_rating") or (street.get("rating") if street else None)
    rsi = _f(card.get("rsi"))
    rvol = _f(card.get("rvol"))
    atr = _f(card.get("atr"))
    support = _f(card.get("support"))
    resistance = _f(card.get("resistance"))
    trade_state = card.get("trade_ai_state")
    proposal = card.get("proposal_allowed")
    next_action = card.get("next_operator_action") or card.get("allowed_action_now")
    primary_risk = card.get("primary_risk")
    meaning = card.get("operator_meaning") or card.get("one_line_thesis")
    catalyst = card.get("catalyst_summary")
    pct_off_high = _f(card.get("pct_off_52w_high") or card.get("off_52w_high_pct"))
    return {
        "available": True,
        "contract": WATCH_CONTRACT,
        "source": "watch_intelligence.broker.v1",
        "as_of": q_asof,
        "freshness": q_fresh,
        "identity": {
            "symbol": card.get("symbol"),
            "company": card.get("company"),
            "sector": card.get("sector"),
            "industry": card.get("industry"),
            "instrument_type": card.get("instrument_type") or "stock",
        },
        "quote": {
            "last": field_state(last, source=q_src, as_of=q_asof, freshness=q_fresh)
                    if last is not None else missing("no_canonical_watch_quote", source=q_src),
            "day_change_pct": field_state(_f(card.get("day_change_pct")), source=q_src, as_of=q_asof, freshness=q_fresh)
                              if card.get("day_change_pct") is not None else missing("no_day_change", source=q_src),
            "price_source": q_src,
            "price_as_of": q_asof,
            "freshness_state": q_fresh,
            "market_session": card.get("market_session") or card.get("market_state"),
        },
        "trade_ai": {
            "primary_state": field_state(trade_state, source="decision_packets+projection", as_of=q_asof)
                             if trade_state else missing("no_trade_ai_state", source="decision_packets"),
            "proposal_allowed": bool(proposal),
            "operator_meaning": meaning,
            "allowed_action_now": next_action,
            "next_operator_action": next_action,
            "primary_risk": primary_risk,
            "next_review": card.get("next_review_time"),
        },
        "technicals": {
            "support": field_state(support, source="watchlist_strategy_cards") if support is not None
                       else missing("no_support", source="watchlist_strategy_cards"),
            "resistance": field_state(resistance, source="watchlist_strategy_cards") if resistance is not None
                          else missing("no_resistance", source="watchlist_strategy_cards"),
            "rsi": field_state(rsi, source="watchlist_items|enrichment") if rsi is not None
                   else missing("no_rsi", source="watchlist_items|enrichment"),
            "rvol": field_state(rvol, source="watchlist_items") if rvol is not None
                    else missing("no_rvol", source="watchlist_items"),
            "atr": field_state(atr, source="enrichment_cache") if atr is not None
                   else missing("no_atr", source="enrichment_cache"),
            "setup": card.get("technical_setup"),
            "freshness": card.get("technical_freshness"),
        },
        "catalyst": {
            "summary": field_state(catalyst, source="catalyst_events") if catalyst
                       else missing("no_catalyst", source="catalyst_events"),
            "freshness": classify_freshness(q_asof, stale_s=WATCH_STALE_S, expired_s=FACTS_EXPIRED_S),
        },
        "relative": {
            "summary": card.get("relative_performance_summary") or card.get("absolute_performance_summary"),
            "pct_off_52w_high": pct_off_high,
        },
        "street": {
            "rating": field_state(rating, source=street.get("source") if street else "yahoo", as_of=target_as_of,
                                  freshness=street_fresh) if rating else missing("no_street_rating", source="yahoo"),
            "analyst_count": field_state(analysts, source=street.get("source") if street else "yahoo", as_of=target_as_of)
                             if analysts is not None else missing("no_analyst_count", source="yahoo"),
            "target": field_state(target, source=street.get("source") if street else "yahoo", as_of=target_as_of,
                                  freshness=street_fresh, quality=STALE if street_fresh == FRESH_STALE else AVAILABLE)
                      if target is not None else missing("no_analyst_target", source="yahoo"),
            "target_as_of": target_as_of,
            "upside_pct": street.get("implied_upside_pct") if street else card.get("implied_upside_pct"),
            "upside_note": "versus verified/current watch quote only" if last is not None else "no current reference",
        },
        "reviews": {
            "cio": card.get("cio_review") or {"status": "NOT_RUN"},
            "maria": card.get("maria_review") or {"status": "NOT_RUN"},
        },
        "starred": bool(card.get("starred")),
        "held": bool(card.get("held")),
        "material_change": bool(card.get("material_change")),
        "domains_present": sorted(domains.keys()) if domains else [],
        "why_wait": meaning or primary_risk,
    }


def derive_setup_state(watch: dict[str, Any], *, verdict: str) -> str:
    if not watch.get("available"):
        return SETUP_WAIT_DATA
    trade = ((watch.get("trade_ai") or {}).get("primary_state") or {}).get("value")
    trade_u = str(trade or "").upper()
    q_fresh = str((watch.get("quote") or {}).get("freshness_state") or "")
    last = ((watch.get("quote") or {}).get("last") or {}).get("value")
    tech_fresh = str(((watch.get("technicals") or {}).get("freshness") or "")).upper()
    if trade_u in {"AVOID"} or verdict == "AVOID":
        return SETUP_AVOID
    if trade_u in {"BLOCKED", "DETERMINISTIC_FAIL"}:
        # Phase 1 — a BLOCKED/DETERMINISTIC_FAIL whose only admission is a STALE
        # technical snapshot must not read as blocked once the Hub has refreshed
        # that snapshot to CURRENT. Fall through to the normal evaluation instead
        # of echoing the stale admission. (RESEARCH_ONLY / no-mechanics blocks
        # carry non-CURRENT technicals and stay BLOCKED.)
        if tech_fresh == "CURRENT":
            trade_u = "WAIT"
        else:
            return SETUP_BLOCKED
    if trade_u in {"STALE"} or q_fresh in {FRESH_STALE, "STALE", FRESH_EXPIRED} or (
        last is None and q_fresh in {FRESH_UNAVAILABLE, "DATA_UNAVAILABLE"}
    ):
        if last is None:
            return SETUP_WAIT_DATA
        return SETUP_STALE
    if trade_u in {"MANAGING"}:
        return SETUP_MANAGING
    if trade_u in {"REVIEW", "REVIEW_NOW", "READY"}:
        return SETUP_REVIEW_NOW
    if trade_u in {"NEAR", "NEAR_TRIGGER", "NEAR ENTRY"}:
        return SETUP_NEAR_TRIGGER
    rsi = _f(((watch.get("technicals") or {}).get("rsi") or {}).get("value"))
    last_f = _f(last)
    support = _f(((watch.get("technicals") or {}).get("support") or {}).get("value"))
    resistance = _f(((watch.get("technicals") or {}).get("resistance") or {}).get("value"))
    if last_f is not None and support is not None and support > 0:
        if abs(last_f - support) / support <= 0.03:
            return SETUP_NEAR_TRIGGER
    if last_f is not None and resistance is not None and resistance > 0:
        if 0 <= (resistance - last_f) / resistance <= 0.02:
            return SETUP_NEAR_TRIGGER
    if rsi is not None and rsi >= 70:
        return SETUP_WATCH
    return SETUP_WATCH


def watch_filter_tags(watch: dict[str, Any], setup: str) -> list[str]:
    tags = ["all"]
    if setup in {SETUP_REVIEW_NOW, SETUP_NEAR_TRIGGER, SETUP_BLOCKED, SETUP_WAIT_DATA, SETUP_STALE}:
        tags.append("needs_attention")
    if setup == SETUP_NEAR_TRIGGER:
        tags.append("near_trigger")
    if setup == SETUP_REVIEW_NOW:
        tags.append("review_now")
    if watch.get("starred"):
        tags.append("starred")
    street = watch.get("street") or {}
    rating = ((street.get("rating") or {}).get("value") or "")
    if str(rating).upper() in {"STRONG BUY", "BUY"} and ((street.get("analyst_count") or {}).get("value") or 0):
        tags.append("strongest_evidence")
    cat = ((watch.get("catalyst") or {}).get("summary") or {}).get("value")
    if cat:
        tags.append("catalyst_upcoming")
    if setup == SETUP_WAIT_DATA:
        tags.append("needs_data")
    if setup == SETUP_STALE:
        tags.append("stale")
    if setup == SETUP_AVOID:
        tags.append("avoid")
    return tags


def watch_rank(watch: dict[str, Any], setup: str) -> int:
    """Lower is more useful. Never sort solely alphabetically."""
    order = {
        SETUP_REVIEW_NOW: 0,
        SETUP_NEAR_TRIGGER: 1,
        SETUP_BLOCKED: 2,
        SETUP_WAIT_DATA: 3,
        SETUP_STALE: 4,
        SETUP_AVOID: 8,
        SETUP_MANAGING: 6,
        SETUP_WATCH: 5,
    }
    score = order.get(setup, 7) * 100
    if watch.get("starred"):
        score -= 15
    if watch.get("material_change"):
        score -= 8
    analysts = _f(((watch.get("street") or {}).get("analyst_count") or {}).get("value")) or 0
    score -= min(10, int(analysts / 5))
    return score


def join_durable_memory(symbols: list[str]) -> dict[str, Any]:
    """Program 3 durable AIF memory — not the legacy advisory thrash object."""
    influence = os.environ.get("GOVERNED_MEMORY_ADVISORY_INFLUENCE", "OFF")
    mbi = os.environ.get("MEMORY_BEHAVIOR_INFLUENCE", "0")
    try:
        from scripts.lib.agent_durable_memory import get_durable_provider
        from scripts.lib.agent_memory_governance import retrieve_for_context
    except Exception:
        try:
            from lib.agent_durable_memory import get_durable_provider  # type: ignore
            from lib.agent_memory_governance import retrieve_for_context  # type: ignore
        except Exception as exc:  # noqa: BLE001
            return {
                "available": False,
                "state": NOT_CONFIGURED,
                "reason": f"provider_import:{type(exc).__name__}",
                "influence_mode": influence,
                "memory_behavior_influence": mbi,
                "by_symbol": {},
                "as_of": None,
                "legacy_advisory_memory_separated": True,
            }
    try:
        prov = get_durable_provider()
        health = prov.health() if hasattr(prov, "health") else {"status": "OK"}
        result = retrieve_for_context(
            prov,
            query="advisory desk operator truth",
            symbols=list(dict.fromkeys(s.upper() for s in symbols if s)),
            top_k=12,
            budget_tokens=1200,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "state": FAILED,
            "reason": f"retrieval:{type(exc).__name__}",
            "influence_mode": influence,
            "memory_behavior_influence": mbi,
            "by_symbol": {},
            "as_of": None,
            "legacy_advisory_memory_separated": True,
        }
    supporting = [r for r in (result.get("supporting") or []) if isinstance(r, dict)]
    counter = [r for r in (result.get("counter_memory") or result.get("counter") or []) if isinstance(r, dict)]
    disputed = [r for r in (result.get("conflicts") or []) if isinstance(r, dict)]
    by: dict[str, dict[str, Any]] = {}
    for rec in supporting + counter:
        rec_syms = rec.get("symbols") or rec.get("symbol") or []
        if isinstance(rec_syms, str):
            rec_syms = [rec_syms]
        if not rec_syms:
            rec_syms = ["*"]
        for s in rec_syms:
            key = str(s).upper()
            bucket = by.setdefault(key, {"supporting": [], "counter": [], "disputed": []})
            dest = "counter" if rec in counter else "supporting"
            bucket[dest].append({
                "memory_id": rec.get("memory_id"),
                "status": rec.get("status") or rec.get("display_status"),
                "subject": rec.get("subject") or rec.get("summary") or rec.get("content"),
                "memory_type": rec.get("memory_type"),
                "as_of": rec.get("created_at") or rec.get("admitted_at") or rec.get("as_of"),
            })
    # The MEMORY clock reflects the newest *admission*, not the top-ranked
    # retrieval. The daily shadow seed writes one admission/day; reading the
    # admission receipt keeps the clock honest (CURRENT → STALE → EXPIRED) even
    # when the heartbeat does not rank first among supporting memories.
    last_admitted_at = None
    try:
        rp = getattr(prov, "receipts_path", None)
        if rp and Path(rp).is_file():
            tail = Path(rp).read_text(encoding="utf-8", errors="replace").splitlines()[-50:]
            for line in reversed(tail):
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(r, dict) and r.get("accepted"):
                    ts = r.get("admitted_at") or r.get("at")
                    if ts:
                        last_admitted_at = ts
                        break
    except OSError:
        last_admitted_at = None
    as_of = last_admitted_at
    if not as_of and supporting:
        as_of = supporting[0].get("created_at") or supporting[0].get("admitted_at")
    provider_name = getattr(prov, "name", None) or type(prov).__name__
    status = result.get("retrieval_status") or ("OK" if supporting or counter else "EMPTY")
    return {
        "available": True,
        "state": AVAILABLE if status in {"OK", "EMPTY", "RETRIEVAL_OK", "RETRIEVAL_EMPTY"} else DEGRADED,
        "retrieval_status": status,
        "provider": provider_name,
        "producer": SHADOW_SEED_PRODUCER,
        "health": health if isinstance(health, dict) else {"status": str(health)},
        "influence_mode": influence,
        "memory_behavior_influence": mbi,
        "supporting_count": len(supporting),
        "counter_count": len(counter),
        "disputed_count": len(disputed),
        "no_match_semantics": "retrieval succeeded; zero relevant memories is not an error",
        "legacy_advisory_memory_separated": True,
        "as_of": as_of,
        "by_symbol": by,
    }


def join_financial_senses(symbols: list[str]) -> dict[str, Any]:
    """Read existing FS receipts. Never call live FS providers from the desk."""
    path = _CIO / "agent_tool_traces.jsonl"
    mode = os.environ.get("FINANCIAL_SENSES_ADVISORY_INFLUENCE", "OFF")
    wanted = {s.upper() for s in symbols if s}
    by: dict[str, list[dict[str, Any]]] = {s: [] for s in wanted}
    last_as_of = None
    receipts = 0
    if path.is_file():
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
        except OSError:
            lines = []
        for line in lines:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            blob = json.dumps(rec).lower()
            is_fs = bool(
                rec.get("fs_provider") or rec.get("fs_capability")
                or rec.get("tool_name") == "financial_senses"
                or "financial_senses" in blob
            )
            if not is_fs:
                continue
            receipts += 1
            ts = rec.get("ended_at") or rec.get("started_at") or rec.get("at")
            if ts:
                last_as_of = ts
            rec_syms = rec.get("symbols") or []
            if rec.get("symbol"):
                rec_syms = list(rec_syms) + [rec.get("symbol")]
            rec_syms = [str(s).upper() for s in rec_syms if s]
            if not rec_syms:
                continue
            snippet = {
                "at": ts,
                "provider": rec.get("fs_provider") or rec.get("provider"),
                "capability": rec.get("fs_capability") or rec.get("tool_name"),
                "status": rec.get("status"),
                "summary": rec.get("summary") or rec.get("reason") or rec.get("error"),
            }
            for s in rec_syms:
                if s in by:
                    by[s].append(snippet)
    covered = sum(1 for s, rows in by.items() if rows)
    freshness = (
        classify_freshness(last_as_of, stale_s=36 * 3600, expired_s=7 * 86400)
        if last_as_of else FRESH_UNAVAILABLE
    )
    return {
        "available": path.is_file(),
        "state": AVAILABLE if receipts else NOT_RUN,
        "source": "agent_tool_traces.jsonl",
        "influence_mode": mode,
        "receipts_available": receipts,
        "row_coverage": covered,
        "as_of": last_as_of,
        "freshness": freshness,
        "producer": SHADOW_SEED_PRODUCER,
        "by_symbol": {s: rows[-3:] for s, rows in by.items()},
        "reason": (
            "no_current_evidence" if not receipts
            else ("fs_receipt_stale" if freshness in (FRESH_STALE, FRESH_EXPIRED) else None)
        ),
    }


def _lot_shares(row: dict[str, Any]) -> Optional[float]:
    lots = row.get("lot_basis") or (row.get("expand") or {}).get("lots") or {}
    if isinstance(lots, dict):
        return _f(lots.get("total_shares"))
    return None


def holdings_field_states(
    row: dict[str, Any],
    *,
    live: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Class-aware current financial facts with explicit field states."""
    rcls = str(row.get("row_class") or "")
    facts = row.get("canonical_financial_facts") or {}
    if not isinstance(facts, dict):
        facts = {}
    if rcls == "watchlist":
        return {
            "position": na("no_open_position", source="advisory_desk"),
            "shares": na("no_open_position", source="holdings.json"),
            "current_mark": na("no_open_position", source="holdings.json"),
            "market_value": na("no_open_position", source="holdings.json"),
            "total_cost_basis": na("no_open_position", source="holdings.json"),
            "average_cost": na("no_open_position", source="holdings.json"),
            "unrealized_pl": na("no_open_position", source="holdings.json"),
            "as_of": na("no_open_position", source="holdings.json"),
            "note": "Not held — shares / lots / cost basis N/A",
        }
    if rcls in {"closed_journal", "allocation"}:
        reason = "position_closed" if rcls == "closed_journal" else "not_a_security_position"
        return {
            "position": na(reason, source="advisory_desk"),
            "shares": na(reason, source="holdings.json"),
            "current_mark": na(reason, source="holdings.json") if rcls == "closed_journal"
                            else missing("allocation_has_no_mark"),
            "market_value": na(reason, source="holdings.json") if rcls == "closed_journal"
                            else field_state(_f(row.get("market_value")), source="allocation"),
            "total_cost_basis": na(reason, source="holdings.json"),
            "average_cost": na(reason, source="holdings.json"),
            "unrealized_pl": na(reason, source="holdings.json"),
            "note": "Position closed — market value / cost basis N/A" if rcls == "closed_journal" else "Allocation row",
        }

    live = live or {}
    # Prefer the live (symbol, account) row, then the desk opinion row, then
    # provenance facts. attach_advisory_row_provenance is keyed by symbol only
    # and last-write-wins across accounts (SCHD taxable must not inherit IRA).
    shares = _f(live.get("shares"))
    if shares is None:
        shares = _f(row.get("shares"))
    if shares is None:
        shares = _f(facts.get("shares"))
    if shares is None:
        shares = _lot_shares(row)
    mv = _f(live.get("market_value"))
    if mv is None:
        mv = _f(row.get("market_value"))
    if mv is None:
        mv = _f(facts.get("market_value"))
    mark = _f(live.get("canonical_mark"))
    if mark is None:
        mark = _f(row.get("canonical_mark"))
    if mark is None:
        mark = _f(facts.get("current_mark"))
    ref_px = _f(live.get("price") if live.get("price") is not None else row.get("price"))
    ref_cur = _f(live.get("current_price") if live.get("current_price") is not None else row.get("current_price"))
    as_of = (
        live.get("canonical_mark_as_of") or live.get("as_of")
        or row.get("as_of") or row.get("price_as_of") or facts.get("as_of")
    )
    source = live.get("canonical_mark_source") or row.get("price_source") or facts.get("source") or "holdings.json"
    basis = _f(live.get("cost_basis"))
    if basis is None:
        basis = _f(row.get("adjusted_cost") or row.get("cost_basis"))
    if basis is None:
        basis = _f(facts.get("total_cost_basis"))
    avg = _f(facts.get("avg_cost_per_share") or row.get("average_cost") or live.get("average_cost"))
    if avg is None and shares and shares > 0 and basis is not None:
        avg = basis / shares
    upl = _f(facts.get("unrealized_pl"))
    if upl is None and mv is not None and basis is not None:
        upl = mv - basis

    if live and not any((shares, mark, mv)) and str(row.get("symbol") or "").upper() not in {
        str(live.get("symbol") or "").upper()
    }:
        # live dict is the matching row; empty match handled by caller
        pass

    fresh = classify_freshness(as_of, stale_s=FACTS_STALE_S, expired_s=FACTS_EXPIRED_S)
    mark_state = AVAILABLE
    mark_quality = facts.get("quality") or "VERIFIED_AS_OF"
    mark_reason = None
    if mark is None:
        mark_state = DATA_UNAVAILABLE
        mark_quality = DATA_UNAVAILABLE
        mark_reason = "no_canonical_mark"
        if not live and not facts:
            mark_reason = "stale_cached_row_missing_price_fields"
    elif fresh == FRESH_STALE:
        mark_state = STALE
        mark_quality = STALE
        mark_reason = "canonical_mark_older_than_6h"
    elif fresh == FRESH_EXPIRED:
        mark_state = STALE
        mark_quality = STALE
        mark_reason = "canonical_mark_older_than_24h"

    implied = None
    implied_fs = None
    if shares and shares > 0 and mv is not None:
        implied = mv / shares
        implied_fs = field_state(
            round(implied, 4),
            state=AVAILABLE,
            source="derived:market_value/shares",
            as_of=as_of,
            freshness=fresh,
            quality="DERIVED_REFERENCE",
            reason="implied_price_from_market_value",
            display=f"${implied:,.2f} (derived)",
        )

    ref_snap = None
    ref_candidate = ref_cur or ref_px
    if ref_candidate is not None:
        same = mark is not None and abs(ref_candidate - mark) / max(abs(mark), 1e-9) <= 0.002
        if not same:
            ref_src = live.get("price_source") or row.get("price_source") or "finviz"
            ref_snap = field_state(
                ref_candidate,
                state=AVAILABLE,
                source=str(ref_src),
                as_of=live.get("updated_at") or row.get("updated_at"),
                freshness=classify_freshness(live.get("updated_at") or row.get("updated_at"), stale_s=FACTS_STALE_S, expired_s=FACTS_EXPIRED_S),
                quality="NON_CANONICAL_REFERENCE",
                reason="secondary_market_snapshot_not_promoted",
            )

    why_missing: list[str] = []
    if mark is None:
        why_missing.append(mark_reason or "no_canonical_mark")
        if implied_fs:
            why_missing.append("implied_price_available_from_market_value")
        if ref_snap:
            why_missing.append("reference_snapshot_available_not_canonical")
        if shares is None:
            why_missing.append("shares_missing_on_desk_row")
    if live is None:
        why_missing.append("symbol_not_in_current_holdings")

    return {
        "position": field_state("OPEN", source="holdings.json", as_of=as_of, freshness=fresh),
        "shares": field_state(shares, source="holdings.json", as_of=as_of, freshness=fresh)
                  if shares is not None else missing("shares_unavailable", source="holdings.json", as_of=as_of),
        "current_mark": field_state(
            mark, state=mark_state, source=source, as_of=as_of, freshness=fresh if mark is not None else FRESH_UNAVAILABLE,
            quality=mark_quality, reason=mark_reason,
        ),
        "market_value": field_state(mv, source="holdings.json", as_of=as_of, freshness=fresh)
                        if mv is not None else missing("market_value_unavailable", source="holdings.json"),
        "total_cost_basis": field_state(basis, source=row.get("cost_basis_source") or "holdings.json", as_of=as_of)
                            if basis is not None else missing("cost_basis_unavailable"),
        "average_cost": field_state(round(avg, 4) if avg is not None else None, source="holdings.json", as_of=as_of)
                        if avg is not None else missing("average_cost_unavailable"),
        "unrealized_pl": field_state(round(upl, 2) if upl is not None else None, source="holdings.json", as_of=as_of)
                         if upl is not None else missing("unrealized_pl_unavailable"),
        "as_of": field_state(as_of, source=source, as_of=as_of, freshness=fresh)
                 if as_of else missing("no_source_clock", source=source),
        "source": source,
        "quality": mark_quality,
        "implied_price": implied_fs,
        "reference_market_snapshot": ref_snap,
        "why_missing": why_missing,
        "live_holdings_joined": bool(live),
    }


def _memory_for_symbol(bundle: dict[str, Any], symbol: str) -> dict[str, Any]:
    by = bundle.get("by_symbol") or {}
    rec = by.get(symbol.upper()) or by.get("*") or {"supporting": [], "counter": [], "disputed": []}
    supporting = rec.get("supporting") or []
    counter = rec.get("counter") or []
    status = bundle.get("retrieval_status") or "EMPTY"
    if not bundle.get("available"):
        state = bundle.get("state") or NOT_CONFIGURED
        reason = bundle.get("reason") or "memory_provider_unavailable"
    elif status in {"OK", "RETRIEVAL_OK", "EMPTY", "RETRIEVAL_EMPTY"}:
        state = AVAILABLE
        reason = None if (supporting or counter) else "no_relevant_durable_memories"
    else:
        state = DATA_UNAVAILABLE
        reason = str(status)
    return {
        "provider": bundle.get("provider"),
        "retrieval_status": status,
        "state": state,
        "reason": reason,
        "supporting": supporting,
        "counter": counter,
        "disputed": rec.get("disputed") or [],
        "legacy_separated": True,
        "influence_mode": bundle.get("influence_mode"),
        "memory_behavior_influence": bundle.get("memory_behavior_influence"),
        "no_match_semantics": bundle.get("no_match_semantics"),
        "as_of": bundle.get("as_of"),
        "summary": (
            f"{len(supporting)} relevant durable memories / retrieval {status}"
            if bundle.get("available") else f"memory {state}: {reason}"
        ),
    }


def _senses_for_symbol(bundle: dict[str, Any], symbol: str) -> dict[str, Any]:
    rows = (bundle.get("by_symbol") or {}).get(symbol.upper()) or []
    if rows:
        latest = rows[-1]
        return {
            "state": AVAILABLE,
            "receipts": rows,
            "latest": latest,
            "as_of": latest.get("at"),
            "influence_mode": bundle.get("influence_mode"),
            "summary": f"latest validated evidence @ {latest.get('at') or 'unknown'} ({latest.get('capability') or latest.get('provider') or 'fs'})",
        }
    return {
        "state": NOT_RUN if bundle.get("state") == NOT_RUN else DATA_UNAVAILABLE,
        "receipts": [],
        "latest": None,
        "as_of": bundle.get("as_of"),
        "influence_mode": bundle.get("influence_mode"),
        "reason": "no_current_evidence",
        "summary": "no current evidence",
    }


def _opinion_timestamps(opinions: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(opinions, dict):
        return {"flash": None, "synthesis": None, "freshness": FRESH_UNAVAILABLE}
    synth_at = opinions.get("generated_at") or opinions.get("as_of") or opinions.get("computed_at")
    flash_at = synth_at
    rows = opinions.get("rows")
    if isinstance(rows, dict):
        for rec in rows.values():
            if isinstance(rec, dict) and rec.get("generated_at"):
                flash_at = rec.get("generated_at")
                break
    return {
        "flash": flash_at,
        "synthesis": synth_at,
        "flash_freshness": classify_freshness(flash_at, stale_s=OPINION_STALE_S, expired_s=OPINION_EXPIRED_S),
        "synthesis_freshness": classify_freshness(synth_at, stale_s=OPINION_STALE_S, expired_s=OPINION_EXPIRED_S),
    }


def why_advisory_call(row: dict[str, Any], *, watch: Optional[dict[str, Any]], reentry: Optional[dict[str, Any]]) -> str:
    verdict = str(row.get("verdict") or "")
    rationale = str(row.get("rationale") or "").strip()
    if verdict == "RE_ENTER" and reentry and reentry.get("available"):
        return reentry.get("why") or rationale or "Re-entry desk produced a reviewable state."
    if str(row.get("row_class")) == "watchlist" and watch and watch.get("available"):
        trade = ((watch.get("trade_ai") or {}).get("primary_state") or {}).get("value")
        meaning = (watch.get("trade_ai") or {}).get("operator_meaning")
        risk = (watch.get("trade_ai") or {}).get("primary_risk")
        tech_fresh = str(((watch.get("technicals") or {}).get("freshness") or "")).upper()
        if str(trade or "").upper() in {"BLOCKED", "DETERMINISTIC_FAIL"} and tech_fresh == "CURRENT":
            # The Hub refreshed the technical snapshot to CURRENT, so the stale
            # "technical snapshot is STALE" admission no longer applies; keep the
            # why aligned with the un-blocked setup state.
            trade = "WAIT"
            meaning = "technicals refreshed (CURRENT)"
            risk = None
        parts = [p for p in (f"Trade AI {trade}" if trade else None, meaning, risk) if p]
        if parts:
            return " — ".join(parts)
    if rationale:
        return rationale
    return f"Desk verdict {verdict or 'NONE'} with no additional evidence attached."


def enrich_row(
    row: dict[str, Any],
    *,
    watch_join: dict[str, Any],
    reentry_join: dict[str, Any],
    memory_join: dict[str, Any],
    senses_join: dict[str, Any],
    live_holdings: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    sym = str(row.get("symbol") or "").upper()
    acct = str(row.get("account") or "")
    rcls = str(row.get("row_class") or "")
    live = live_holdings.get((sym, acct)) or live_holdings.get((sym, ""))
    # Stale-cache artifact: symbol no longer held.
    if rcls == "holding" and live is None:
        live = None

    composed = (watch_join.get("items") or {}).get(sym)
    watch = project_watch(composed) if composed else (
        project_watch({"ok": False, "error": "not_requested"}) if rcls == "watchlist"
        else {"available": False, "reason": "not_a_watch_row"}
    )
    if rcls == "watchlist" and not watch.get("available") and composed is None:
        watch = {
            "available": False,
            "reason": "watch_intelligence_not_joined",
            "contract": WATCH_CONTRACT,
        }

    raw_re = (reentry_join.get("by_symbol") or {}).get(sym)
    want_reentry = rcls == "closed_journal" or str(row.get("verdict")) == "RE_ENTER" or raw_re
    reentry = project_reentry(
        sym, raw_re,
        as_of=reentry_join.get("as_of"),
        freshness=str(reentry_join.get("freshness") or FRESH_UNAVAILABLE),
    ) if want_reentry else {
        "available": False,
        "state": na("not_a_reentry_candidate", source="reentry_decision_desk"),
        "reason": "not_a_reentry_candidate",
    }

    setup = derive_setup_state(watch, verdict=str(row.get("verdict") or "")) if rcls == "watchlist" else None
    filters = watch_filter_tags(watch, setup) if setup else []
    rank = watch_rank(watch, setup) if setup else 50

    facts = holdings_field_states(row, live=live)
    memory = _memory_for_symbol(memory_join, sym)
    senses = _senses_for_symbol(senses_join, sym)

    # Do not force a meaningless WAIT 0.30 when WI has a real state.
    setup_confidence = row.get("confidence")
    if rcls == "watchlist" and watch.get("available"):
        trade = ((watch.get("trade_ai") or {}).get("primary_state") or {}).get("value")
        if trade and setup in {SETUP_NEAR_TRIGGER, SETUP_REVIEW_NOW}:
            setup_confidence = max(float(setup_confidence or 0), 0.45)
        elif trade and setup == SETUP_BLOCKED:
            setup_confidence = max(float(setup_confidence or 0), 0.40)

    why = why_advisory_call(row, watch=watch if watch.get("available") else None, reentry=reentry if reentry.get("available") else None)

    operator = {
        "version": OPERATOR_TRUTH_VERSION,
        "authority": AUTHORITY,
        "setup_state": setup,
        "watch_filters": filters,
        "watch_rank": rank,
        "field_states": facts,
        "watch_intelligence": watch if rcls in {"watchlist", "holding", "closed_journal"} else None,
        "reentry": reentry,
        "durable_memory": memory,
        "financial_senses": senses,
        "why_call": why,
        "why_missing": facts.get("why_missing") or [],
    }
    row = dict(row)
    row["operator"] = operator
    row["setup_state"] = setup
    row["watch_filters"] = filters
    row["watch_rank"] = rank
    row["field_states"] = facts
    row["watch_intelligence"] = watch
    row["reentry"] = reentry
    row["durable_memory"] = memory
    row["financial_senses"] = senses
    row["why_call"] = why
    if setup_confidence is not None and rcls == "watchlist":
        row["setup_confidence"] = setup_confidence
    # Pass-through re-entry scalars the old _row_view dropped.
    if reentry.get("available"):
        row["reentry_state"] = ((reentry.get("state") or {}).get("value") if isinstance(reentry.get("state"), dict) else reentry.get("raw_state"))
        row["reentry_entry_low"] = (reentry.get("entry_low") or {}).get("value") if isinstance(reentry.get("entry_low"), dict) else None
        row["reentry_entry_high"] = (reentry.get("entry_high") or {}).get("value") if isinstance(reentry.get("entry_high"), dict) else None
        row["reentry_price"] = (reentry.get("price") or {}).get("value") if isinstance(reentry.get("price"), dict) else None
        row["reentry_rsi"] = (reentry.get("rsi") or {}).get("value") if isinstance(reentry.get("rsi"), dict) else None
        row["reentry_distance_label"] = reentry.get("distance_label")
        row["reentry_next_action"] = (reentry.get("next_action") or {}).get("value") if isinstance(reentry.get("next_action"), dict) else None
        row["reentry_reason"] = reentry.get("reason")
        row["reentry_wash_status"] = reentry.get("wash_status")
    return row


def enrich_desk(
    desk: dict[str, Any],
    *,
    opinions: Optional[dict[str, Any]] = None,
    cache_path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Attach operator truth to a build_advisory_desk envelope."""
    now = now or _now()
    data = desk.get("data") if isinstance(desk.get("data"), dict) else {}
    rows_in = list(data.get("rows") or [])
    meta = dict(data.get("metadata") or {})
    symbols = [str(r.get("symbol") or "").upper() for r in rows_in if r.get("symbol")]
    watch_syms = [str(r.get("symbol") or "").upper() for r in rows_in if r.get("row_class") == "watchlist"]
    # Always try WI for watch names + a few acceptance examples when present.
    extra = [s for s in ("PLTR", "FATN", "AMC", "SCHD", "SPCX", "SPXC") if s in symbols or s in watch_syms]
    wi_needed = list(dict.fromkeys(watch_syms + extra))

    live_holdings = load_live_holdings()
    reentry_join = load_reentry_projection()
    watch_join = join_watch_intelligence(wi_needed) if wi_needed else {
        "contract": WATCH_CONTRACT, "items": {}, "as_of": None,
        "freshness": FRESH_UNAVAILABLE, "coverage": 0, "requested": 0,
    }
    memory_join = join_durable_memory(symbols)
    senses_join = join_financial_senses(symbols)

    rows_out = [
        enrich_row(
            r,
            watch_join=watch_join,
            reentry_join=reentry_join,
            memory_join=memory_join,
            senses_join=senses_join,
            live_holdings=live_holdings,
        )
        for r in rows_in
    ]

    cm = cache_meta(desk, cache_path=cache_path, now=now)
    opinions = opinions if isinstance(opinions, dict) else (desk.get("opinions") or {})
    ot = _opinion_timestamps(opinions)
    watch_cov = watch_join.get("coverage") or 0
    watch_req = watch_join.get("requested") or 0
    if watch_req == 0:
        completeness = HEALTHY
    elif watch_cov == 0:
        completeness = DEGRADED
    elif watch_cov < watch_req:
        completeness = PARTIAL
    else:
        completeness = HEALTHY

    mem_health = HEALTHY
    if not memory_join.get("available"):
        mem_health = DEGRADED if memory_join.get("state") != FAILED else FAILED
    elif memory_join.get("state") == FAILED:
        mem_health = FAILED

    hsrc = holdings_source_freshness(now=now)
    health = compute_desk_health(
        structural_ok=bool(meta.get("validation_ok", True)),
        plausibility_pass=str(meta.get("plausibility_gate") or "PASS") == "PASS",
        fact_freshness=str(cm["desk_freshness_state"]),
        source_completeness=completeness,
        opinion_freshness=str(ot.get("synthesis_freshness") or FRESH_UNAVAILABLE),
        reentry_freshness=str(reentry_join.get("freshness") or FRESH_UNAVAILABLE),
        watch_freshness=str(watch_join.get("freshness") or FRESH_UNAVAILABLE),
        memory_health=mem_health,
        holdings_source_freshness=str(hsrc["holdings_source_freshness"]),
    )

    timestamps = {
        "facts": data.get("computed_at") or cm.get("desk_computed_at"),
        "facts_freshness": cm.get("desk_freshness_state"),
        "watch": watch_join.get("as_of"),
        "watch_freshness": watch_join.get("freshness"),
        "reentry": reentry_join.get("as_of"),
        "reentry_freshness": reentry_join.get("freshness"),
        "senses": senses_join.get("as_of"),
        "senses_freshness": senses_join.get("freshness"),
        "memory": memory_join.get("as_of"),
        "memory_freshness": classify_freshness(memory_join.get("as_of"), stale_s=MEMORY_STALE_S, expired_s=7 * 86400)
                            if memory_join.get("as_of") else FRESH_UNAVAILABLE,
        "flash": ot.get("flash"),
        "flash_freshness": ot.get("flash_freshness"),
        "synthesis": ot.get("synthesis"),
        "synthesis_freshness": ot.get("synthesis_freshness"),
        "synthesis_label": (
            "PRIOR SYNTHESIS" if ot.get("synthesis_freshness") in {FRESH_STALE, FRESH_EXPIRED}
            else ("CURRENT SYNTHESIS" if ot.get("synthesis") else "NO SYNTHESIS")
        ),
    }

    operator_truth = {
        "version": OPERATOR_TRUTH_VERSION,
        "contract": CONTRACT,
        "authority": AUTHORITY,
        "memory_behavior_influence": os.environ.get("MEMORY_BEHAVIOR_INFLUENCE", "0"),
        "broker_write_authority": "NONE",
        "enriched_at": now.isoformat(),
        "watch_coverage": {"joined": watch_cov, "requested": watch_req},
        "reentry_coverage": reentry_join.get("row_count") or 0,
        "memory": {
            "provider": memory_join.get("provider"),
            "retrieval_status": memory_join.get("retrieval_status"),
            "producer": memory_join.get("producer"),
            "legacy_separated": True,
        },
        "senses": {
            "receipts_available": senses_join.get("receipts_available"),
            "row_coverage": senses_join.get("row_coverage"),
            "producer": senses_join.get("producer"),
        },
    }

    out = dict(desk)
    data_out = dict(data)
    data_out["rows"] = rows_out
    data_out["operator_truth"] = operator_truth
    data_out["timestamps"] = timestamps
    data_out["desk_health"] = health
    data_out["cache_meta"] = cm
    out["data"] = data_out
    out["operator_truth"] = operator_truth
    out["timestamps"] = timestamps
    out["desk_health"] = health
    out.update(cm)
    return out


def assess_watchdog_advisory(*, now: Optional[datetime] = None) -> dict[str, Any]:
    """Lightweight freshness facts for the autonomy watchdog. Read-only."""
    now = now or _now()
    desk_path = _RUNTIME / "advisory_desk_latest.json"
    opin_path = _RUNTIME / "advisory_opinions_latest.json"
    re_path = _RUNTIME / "reentry_decision_desk_latest.json"
    desk = _load_json(desk_path)
    data = desk.get("data") if isinstance(desk.get("data"), dict) else {}
    rows = data.get("rows") or []
    computed = data.get("computed_at")
    age = age_seconds(computed, now=now)
    if age is None and desk_path.exists():
        age = max(0.0, now.timestamp() - desk_path.stat().st_mtime)
    freshness = classify_freshness(computed, stale_s=300, expired_s=FACTS_EXPIRED_S, now=now)
    if freshness == FRESH_CURRENT and age is not None and age > 300:
        freshness = FRESH_STALE
    watch_rows = [r for r in rows if isinstance(r, dict) and r.get("row_class") == "watchlist"]
    wi = sum(1 for r in watch_rows if (r.get("watch_intelligence") or {}).get("available") or (r.get("operator") or {}).get("watch_intelligence", {}).get("available"))
    re_rows = [r for r in rows if isinstance(r, dict) and (r.get("row_class") == "closed_journal" or r.get("verdict") in ("RE_ENTER", "AdvisoryVerdict.RE_ENTER"))]
    re_cov = sum(1 for r in re_rows if r.get("reentry_state") or (r.get("reentry") or {}).get("available"))
    opin = _load_json(opin_path)
    opin_at = opin.get("generated_at") or opin.get("as_of")
    if opin_path.exists() and not opin_at:
        opin_at = datetime.fromtimestamp(opin_path.stat().st_mtime, tz=timezone.utc).isoformat()
    re_at = (_load_json(re_path).get("generated_at")
             or (datetime.fromtimestamp(re_path.stat().st_mtime, tz=timezone.utc).isoformat() if re_path.exists() else None))
    return {
        "facts_freshness": freshness,
        "desk_age_seconds": round(age, 1) if age is not None else None,
        "desk_computed_at": computed,
        "watch_rows": len(watch_rows),
        "watch_intelligence_joined": wi,
        "reentry_rows": len(re_rows),
        "reentry_fields_present": re_cov,
        "opinion_as_of": opin_at,
        "opinion_freshness": classify_freshness(opin_at, stale_s=OPINION_STALE_S, expired_s=OPINION_EXPIRED_S, now=now),
        "reentry_as_of": re_at,
        "reentry_freshness": classify_freshness(re_at, stale_s=REENTRY_STALE_S, expired_s=FACTS_EXPIRED_S, now=now),
        "operator_truth_version": (desk.get("operator_truth") or data.get("operator_truth") or {}).get("version"),
    }
