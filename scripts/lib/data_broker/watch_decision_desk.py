# DEPRECATED 2026-08-06: No known consumers (build_watch_decision_desk not called from any API route or consumer).
# Scheduled for removal. See Wave B/C Data Broker compliance remediation.
"""Watch MAIN Setup Decision Desk — deterministic broker-backed advisories.

Mirrors Re-Entry Decision Desk patterns for MAIN lane symbols:
quotes + indicator_snapshot + entry plan + ticket validation + critics + fund look-through.
No LLM on READY / PROPOSE-READY derivation."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

from lib.data_broker.reentry_decision_desk import (
    DEFAULT_BOOK,
    MAX_ALLOC_PCT,
    RISK_PCT,
    RSI_READY_HIGH,
    RSI_READY_LOW,
    STALE_HOURS,
    _age_hours,
    _f,
    _load_fund_lookthrough_map,
    _lookthrough_payload,
    _near_ma,
    _pref_json,
    _quote,
    _scripts_path,
    _weekend_fresh_ok,
)
from lib.data_broker.symbol_profile import get_symbol_profiles
from lib.data_broker.entry_plan import get_entry_plans
from lib.data_broker.research_card import get_research_cards
from lib.data_broker.final_synthesis import get_final_synthesis

RESISTANCE_KEY = "portfolio.reentry.resistance.v1"
FAIL_RE = re.compile(r"FAIL|REJECT|BLOCK", re.I)
PASS_RE = re.compile(r"^(PASS|PASS_WITH_WARNINGS|ADMITTED|OK)$", re.I)
PENDING_REC_RE = re.compile(
    r"NOT RUN|UNVALIDATED|UNAVAILABLE|PENDING|REQUIRED|QUALITY_NOT_ASSESSED|REVIEW_UNAVAILABLE",
    re.I,
)
MA_TOUCH_PCT = 1.5


def _is_failure(state: str | None) -> bool:
    return bool(FAIL_RE.search(str(state or "")))


def _is_ticket_pass(det: str | None) -> bool:
    return bool(PASS_RE.match(str(det or "").strip()))


def _ticket_state(packet: dict | None) -> dict[str, str]:
    packet = packet or {}
    validation = (packet.get("current_actionable_plan") or {}).get("ticket_validation") or {}
    review = packet.get("ticket_review") or {}
    validated0 = None
    tv = review.get("tickets_validated")
    if isinstance(tv, list) and tv:
        validated0 = tv[0] if isinstance(tv[0], dict) else None
    det_raw = str(validation.get("state") or (validated0 or {}).get("state") or "NOT RUN").upper()
    rec_raw = str((review.get("reconciled") or {}).get("state") or "NOT RUN").upper()
    reviews = review.get("reviews") or {}

    def _lane(key: str) -> str:
        return str((reviews.get(key) or {}).get("verdict") or "NOT RUN").upper()

    return {
        "deterministic": det_raw or "NOT RUN",
        "reconciled": rec_raw or "NOT RUN",
        "local": _lane("local"),
        "deepseek-flash": _lane("deepseek-flash"),
        "deepseek-v4": _lane("deepseek-v4"),
        "grok": _lane("grok"),
        "chatgpt": _lane("chatgpt"),
    }


def _is_ticket_pending(ticket: dict[str, str]) -> bool:
    det = ticket.get("deterministic") or "NOT RUN"
    rec = ticket.get("reconciled") or "NOT RUN"
    if _is_failure(det) or _is_failure(rec):
        return False
    if _is_ticket_pass(det):
        return False
    return (
        det == "NOT RUN"
        or bool(PENDING_REC_RE.search(rec))
        or det == "REVIEW_REQUIRED"
    )


def _admission_now(item: dict | None) -> str:
    item = item or {}
    n = str(item.get("now_status") or "").upper()
    if n in ("GO", "WAIT", "NOGO"):
        return n
    if item.get("starred"):
        return "WAIT"
    return "NOGO"


def _cio_blocks(item: dict | None) -> bool:
    item = item or {}
    block = {"AVOID", "IGNORE", "SELL", "REBALANCE_TRIM"}
    for key in ("latest_recommendation", "synthesis_recommendation", "recommendation"):
        if str(item.get(key) or "").strip().upper() in block:
            return True
    return False


def derive_setup_state(
    *,
    admitted: str,
    ticket: dict[str, str],
    price: float | None,
    rsi: float | None,
    as_of: str | None,
    cio_blocked: bool = False,
    trust_degraded: bool = False,
) -> dict[str, Any]:
    """Operator-visible MAIN desk state (deterministic; no LLM)."""
    now = admitted
    if _is_failure(ticket.get("deterministic")) or _is_failure(ticket.get("reconciled")):
        now = "NOGO"
    elif cio_blocked:
        now = "NOGO"
    elif admitted == "NOGO":
        now = "NOGO"
    elif price is None:
        now = "WAIT"
    elif admitted == "GO":
        now = "GO"
    else:
        now = admitted

    data_gap: str | None = None
    if price is None:
        data_gap = "price_missing"
    elif rsi is None:
        data_gap = "rsi_missing"

    age_h = _age_hours(as_of)
    stale = age_h is None or not _weekend_fresh_ok(age_h)

    desk_state = now
    if data_gap:
        desk_state = "DATA GAP"
    elif cio_blocked:
        desk_state = "NOGO"
    elif stale and now in ("GO", "WAIT"):
        desk_state = "STALE"
    elif trust_degraded and now == "GO":
        # Trust is not quote-stale — keep GO/pending, strip PROPOSE-READY only
        desk_state = "TICKET PENDING" if _is_ticket_pending(ticket) else "GO"
    elif now == "GO" and _is_ticket_pass(ticket.get("deterministic")) and price is not None and not trust_degraded:
        desk_state = "PROPOSE-READY"
    elif now == "GO" and _is_ticket_pending(ticket):
        desk_state = "TICKET PENDING"

    why: list[str] = []
    if cio_blocked:
        why.append("CIO AVOID/SELL (research card or synthesis) — park / not proposeable.")
    elif trust_degraded and now == "GO":
        why.append("CIO TRUST DEGRADED — dual/Street gates not propose-grade (buy-side).")
    elif now == "NOGO" and (_is_failure(ticket.get("deterministic")) or _is_failure(ticket.get("reconciled"))):
        why.append("Ticket deterministic/reconciled FAIL — not proposeable.")
    elif now == "NOGO":
        why.append("MAIN admission NOGO — park or suppress.")
    elif price is None:
        why.append("Quote missing — refresh price before acting.")
    elif rsi is None:
        why.append("RSI missing from indicator_confluence_cache — run indicator_cache_refresh for MAIN symbols.")
    elif now == "WAIT":
        why.append("MAIN WAIT — fill plan / data gaps before GO.")
    elif desk_state == "TICKET PENDING":
        why.append("Setup GO — run critics before propose (ticket pending).")
    elif desk_state == "PROPOSE-READY":
        why.append("Ticket validated — propose / open evidence.")
    elif stale:
        why.append(f"Quote stale ({age_h:.0f}h) — refresh before acting.")

    actionable = (
        now == "GO"
        and _is_ticket_pass(ticket.get("deterministic"))
        and price is not None
        and not data_gap
        and not cio_blocked
        and not trust_degraded
    )
    return {
        "now": now,
        "desk_state": desk_state,
        "data_gap": data_gap,
        "stale": stale,
        "price_age_h": age_h,
        "why": why,
        "actionable": actionable,
        "ticket_pending": now == "GO" and _is_ticket_pending(ticket) and not cio_blocked,
        "cio_blocked": cio_blocked,
        "trust_degraded": trust_degraded,
    }


def _provenance_chips(item: dict | None) -> list[dict[str, str]]:
    item = item or {}
    chips: list[dict[str, str]] = []
    src = str(item.get("source") or item.get("wl_source") or "").strip()
    if src:
        chips.append({"tone": "info", "label": f"source:{src}", "detail": "MAIN source allowlist member"})
    if item.get("starred"):
        chips.append({"tone": "green", "label": "operator ★", "detail": "Star grants M1 identity"})
    if item.get("directive_id"):
        chips.append({"tone": "amber", "label": "sector directive", "detail": "via watch_directives"})
    origin = str(item.get("origin_system") or "").lower()
    if "defense" in origin or "finviz" in origin:
        chips.append({"tone": "info", "label": "screener feed", "detail": origin or "Finviz/defense screener"})
    if item.get("in_portfolio") or str(item.get("source") or "").lower() == "portfolio":
        chips.append({"tone": "info", "label": "portfolio", "detail": "Book-held or portfolio-sourced"})
    sector = str(item.get("profile_sector") or "").strip()
    if sector and sector.lower() not in ("", "—"):
        chips.append({"tone": "info", "label": sector[:24], "detail": "Sector context — open Sectors desk for universe"})
    return chips


def build_watch_advisory(
    *,
    symbol: str,
    desk_state: str,
    price: float | None,
    entry_low: float | None,
    entry_high: float | None,
    stop: float | None,
    target: float | None,
    rr: float | None,
    rsi: float | None,
    sma_20: float | None,
    sma_50: float | None,
    sma_200: float | None,
    sma20_pct: float | None,
    sma50_pct: float | None,
    sma200_pct: float | None,
    macd_signal: str | None,
    alignment: str | None = None,
    obv_signal: str | None = None,
    obv_trend: str | None = None,
    cmf_signal: str | None = None,
    cmf_value: float | None = None,
    volume_ratio: float | None = None,
    instrument_type: str | None = None,
    resistance: dict[str, Any],
    catalyst: dict[str, Any] | None,
    earnings_date: str | None,
    ticket: dict[str, str],
    book_equity: float,
    why: list[str],
    company: str | None = None,
    lookthrough: dict[str, Any] | None = None,
    price_age_h: float | None = None,
) -> dict[str, Any]:
    """Broker-style advisory for MAIN setup desk (deterministic)."""
    today = datetime.now(timezone.utc).date().isoformat()
    entry_mid = None
    if entry_low is not None and entry_high is not None:
        entry_mid = (entry_low + entry_high) / 2
    elif price is not None:
        entry_mid = price

    risk_per_share = None
    if entry_mid is not None and stop is not None and entry_mid > stop:
        risk_per_share = round(entry_mid - stop, 4)

    max_dollar_risk = round(book_equity * RISK_PCT, 2)
    max_alloc = round(book_equity * MAX_ALLOC_PCT, 2)
    shares_1pct = None
    alloc = None
    sizing_note = "Need entry + stop to size"
    if risk_per_share and risk_per_share > 0:
        shares_1pct = int(max_dollar_risk // risk_per_share)
        alloc = round(shares_1pct * entry_mid, 2) if entry_mid and shares_1pct else None
        if alloc is not None and alloc > max_alloc and entry_mid and entry_mid > 0:
            shares_1pct = int(max_alloc // entry_mid)
            alloc = round(shares_1pct * entry_mid, 2)
            sizing_note = f"Capped at {MAX_ALLOC_PCT * 100:.0f}% allocation"
        else:
            sizing_note = f"{RISK_PCT * 100:.0f}% risk rule on ${book_equity:,.0f} book"

    ma_touch = None
    if _near_ma(price, sma_200):
        ma_touch = ("200-SMA", sma_200, sma200_pct)
    elif _near_ma(price, sma_50):
        ma_touch = ("50-SMA", sma_50, sma50_pct)
    elif _near_ma(price, sma_20):
        ma_touch = ("20-SMA", sma_20, sma20_pct)

    align = str(alignment or "").lower()
    above_structure = (
        price is not None and sma_20 is not None and price >= sma_20
        and (align in ("bullish", "aligned", "up") or (sma_50 is not None and sma_20 >= sma_50))
    )
    ma_met = bool(ma_touch) or bool(above_structure)
    if ma_touch:
        ma_name, ma_level, ma_pct = ma_touch
        ma_detail = f"Price holding {ma_name} @ ${ma_level:.2f}"
        if ma_pct is not None:
            ma_detail += f" ({ma_pct:+.1f}%)"
    elif above_structure:
        ma_detail = f"Price above SMA20 @ ${sma_20:.2f}" + (f" · alignment {alignment}" if alignment else "")
    else:
        ma_detail = "Not within 1.5% of SMA20/50/200 and not holding above SMA20"

    res_state = str((resistance or {}).get("state") or "UNAVAILABLE").upper()
    res_level = _f((resistance or {}).get("level") or (resistance or {}).get("resistance"))
    in_zone = (
        entry_low is not None and price is not None
        and entry_low <= price <= (entry_high or entry_low)
    )

    earn_days = None
    if earnings_date:
        try:
            earn_days = (datetime.fromisoformat(str(earnings_date)[:10]).date()
                         - datetime.now(timezone.utc).date()).days
        except Exception:
            earn_days = None

    lt = _lookthrough_payload(lookthrough) if lookthrough else None
    is_fund = bool(lt and lt.get("available")) or str(instrument_type or "").lower() in (
        "fund", "mutualfund", "mutual_fund", "etf", "equityetf",
    )
    vol_met: bool | None
    if is_fund:
        vol_met = True
        vol_detail = "N/A — fund/ETF (no meaningful share volume); skipped"
    elif volume_ratio is not None:
        vol_met = float(volume_ratio) >= 1.0
        vol_detail = f"Volume ratio {float(volume_ratio):.2f}x avg"
    else:
        obv_ok = str(obv_signal or "").upper() in ("BULLISH", "POSITIVE") or str(obv_trend or "").lower() in ("up", "rising", "improving")
        cmf_ok = str(cmf_signal or "").upper() in ("BULLISH", "POSITIVE") or (cmf_value is not None and float(cmf_value) > 0)
        if obv_ok or cmf_ok:
            vol_met = True
            vol_detail = "Money-flow confirms (OBV/CMF)"
        elif obv_signal is None and cmf_signal is None and cmf_value is None:
            vol_met = None
            vol_detail = "Volume/OBV/CMF unavailable in indicator cache"
        else:
            vol_met = False
            vol_detail = f"OBV {obv_signal or '—'} · CMF {cmf_signal or '—'} — weak accumulation"

    fresh_ok = _weekend_fresh_ok(price_age_h)
    if fresh_ok and price_age_h is not None and price_age_h > 36:
        fresh_detail = f"Quote age {price_age_h:.0f}h (weekend/session hold — OK ≤{STALE_HOURS:.0f}h)"
    elif price_age_h is not None:
        fresh_detail = f"Quote age {price_age_h:.0f}h"
    else:
        fresh_detail = "Quote age unknown"
    # Free critics required for MET. deepseek-v4 is paid/optional — shown but not required.
    free_lanes = ("local", "deepseek-flash", "grok", "chatgpt")
    critics_ok = all(
        (ticket.get(k) or "NOT RUN") not in ("NOT RUN", "UNVALIDATED", "UNAVAILABLE", "")
        for k in free_lanes
    )
    ds_v4 = ticket.get("deepseek-v4") or "NOT RUN"
    critics_detail = (
        f"DeepSeek Flash {ticket.get('deepseek-flash') or 'NOT RUN'} · "
        f"Local {ticket.get('local') or 'NOT RUN'} · "
        f"Grok {ticket.get('grok') or 'NOT RUN'} · "
        f"ChatGPT {ticket.get('chatgpt') or 'NOT RUN'}"
    )
    if ds_v4 not in ("NOT RUN", ""):
        critics_detail += f" · DeepSeek v4 {ds_v4}"

    criteria = [
        {
            "id": "ticket",
            "met": _is_ticket_pass(ticket.get("deterministic")),
            "label": "Deterministic ticket validation",
            "detail": f"State {ticket.get('deterministic')} — reconciled {ticket.get('reconciled')}",
        },
        {
            "id": "critics",
            "met": critics_ok if _is_ticket_pass(ticket.get("deterministic")) else None,
            "label": "Multi-lane critics (DeepSeek Flash / local / Grok / ChatGPT)",
            "detail": critics_detail,
        },
        {
            "id": "zone",
            "met": in_zone or (entry_low is not None and res_state in ("ABOVE", "TESTING")),
            "label": "Entry zone / structure",
            "detail": (
                f"In zone ${entry_low:.2f}–${entry_high:.2f}" if in_zone and entry_low is not None
                else (f"Resistance {res_state} @ ${res_level:.2f}" if res_level is not None else "No zone on plan")
            ),
        },
        {
            "id": "ma_bounce",
            "met": ma_met,
            "label": "Moving average bounce / hold",
            "detail": ma_detail,
        },
        {
            "id": "rsi_reset",
            "met": rsi is not None and RSI_READY_LOW <= rsi < RSI_READY_HIGH,
            "label": "RSI in setup band",
            "detail": f"RSI {rsi:.1f} (band {RSI_READY_LOW:.0f}–{RSI_READY_HIGH:.0f})" if rsi is not None else "RSI unavailable",
        },
        {
            "id": "macd",
            "met": bool(macd_signal) and str(macd_signal).upper() not in ("BEARISH", "NEGATIVE", "SELL"),
            "label": "MACD confirmation",
            "detail": f"MACD {macd_signal}" if macd_signal else "MACD unavailable",
        },
        {
            "id": "volume",
            "met": vol_met,
            "label": "Volume / money-flow confirmation",
            "detail": vol_detail,
        },
        {
            "id": "rr",
            "met": rr is not None and rr >= 2.0,
            "label": "Reward-to-risk (≥2:1 preferred)",
            "detail": f"R:R {rr}:1" if rr is not None else "Need stop + target on plan",
        },
        {
            "id": "invalidation",
            "met": stop is not None,
            "label": "Invalidation stop on plan",
            "detail": f"Stop ${stop:.2f}" if stop is not None else "No stop on entry plan",
        },
        {
            "id": "catalyst",
            "met": not (earn_days is not None and 0 <= earn_days <= 5),
            "label": "Catalyst / earnings window clear",
            "detail": (
                f"Earnings in {earn_days}d ({earnings_date})" if earn_days is not None and earn_days <= 5
                else (f"Next earnings {earnings_date}" if earnings_date
                      else ("Catalyst verified" if catalyst and catalyst.get("verified")
                            else "No near-term earnings on file"))
            ),
        },
        {
            "id": "fresh",
            "met": fresh_ok,
            "label": "Quote / indicator freshness",
            "detail": fresh_detail,
        },
    ]

    action_map = {
        "PROPOSE-READY": "Propose / open evidence — ticket validated",
        "TICKET PENDING": "Run critics before propose",
        "DATA GAP": "Refresh quote / RSI cache",
        "STALE": "Refresh stale quote before acting",
        "GO": "Review setup — MAIN GO",
        "WAIT": "Fix data / plan gaps — MAIN WAIT",
        "NOGO": "Park / suppress — not proposeable",
    }

    return {
        "date": today,
        "action": action_map.get(desk_state, desk_state),
        "ticker": symbol,
        "company": company,
        "desk_state": desk_state,
        "stop_loss": stop,
        "target": target,
        "rr": rr,
        "criteria": criteria,
        "rationale": why[:8],
        "lookthrough": lt,
        "sizing": {
            "book_equity": book_equity,
            "max_dollar_risk": max_dollar_risk,
            "risk_per_share": risk_per_share,
            "shares": shares_1pct,
            "allocation": alloc,
            "formula": "shares = (book × 1%) / (entry − stop)",
            "note": sizing_note,
        },
    }


def _main_lane_symbols(db_query: Callable, *, max_symbols: int = 80) -> list[str]:
    _scripts_path()
    try:
        from lib.watch_lane_admission import main_sql_source_clause, load_policy
        main_sql, main_params = main_sql_source_clause(load_policy())
        rows = db_query(
            f"""SELECT DISTINCT upper(wi.symbol) AS symbol
                FROM watchlist_items wi
                WHERE wi.status <> 'removed' AND {main_sql}
                ORDER BY 1
                LIMIT %s""",
            (*main_params, max_symbols),
        ) or []
        return [str(r["symbol"]).upper() for r in rows if r.get("symbol")]
    except Exception:
        return []


def _watch_meta(db_query: Callable, symbols: list[str]) -> dict[str, dict]:
    if not symbols:
        return {}
    # Phase 1: read base watchlist_items + ancillary tables (decision_packets, watchlist_symbol_master,
    #          watchlist_analysis_maturity, operator_starred_symbols) via direct SQL — these don't have
    #          broker wrappers yet (deferred to Phase 2).
    rows = db_query(
        """SELECT DISTINCT ON (upper(wi.symbol))
                  upper(wi.symbol) AS symbol, wi.source, wi.status, wi.directive_id,
                  wi.origin_system, wi.in_directive_watch,
                  EXISTS (
                      SELECT 1 FROM operator_starred_symbols s
                      WHERE upper(s.symbol) = upper(wi.symbol)
                  ) AS starred,
                  dpk.packet AS decision_packet,
                  sm.in_portfolio,
                  am.decision_quality_status, am.actionable AS decision_actionable
           FROM watchlist_items wi
           LEFT JOIN LATERAL (
               SELECT dpp.packet FROM decision_packets dpp
               WHERE upper(dpp.symbol) = upper(wi.symbol) AND dpp.superseded_by IS NULL
               ORDER BY dpp.generated_at DESC LIMIT 1
           ) dpk ON true
           LEFT JOIN watchlist_symbol_master sm ON sm.symbol = wi.symbol
           LEFT JOIN LATERAL (
               SELECT decision_quality_status, actionable
               FROM watchlist_analysis_maturity t
               WHERE t.symbol = wi.symbol LIMIT 1
           ) am ON true
           WHERE upper(wi.symbol) = ANY(%s) AND wi.status <> 'removed'
           ORDER BY upper(wi.symbol), wi.updated_at DESC""",
        (symbols,),
    ) or []

    # Phase 2: read canonical broker stores for symbol_profiles, entry_plans, research_cards,
    #          and final_synthesis via broker wrappers.
    profiles = get_symbol_profiles(db_query, symbols)
    entry_plans = get_entry_plans(db_query, symbols)
    research_cards = get_research_cards(db_query, symbols)
    synthesis_data = get_final_synthesis(db_query, symbols)

    # Phase 3: merge broker data into watchlist item dicts.
    try:
        from lib.watch_lane_admission import annotate_item, load_policy
        pol = load_policy()
    except Exception:
        pol = None
        annotate_item = None  # type: ignore

    out: dict[str, dict] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            continue
        item = dict(row)
        # Overlay broker data
        prof = profiles.get(sym) or {}
        item["profile_sector"] = prof.get("sector")
        item["profile_industry"] = prof.get("industry")
        item["instrument_type"] = prof.get("instrument_type")
        item["next_earnings_date"] = prof.get("next_earnings_date")

        ep = entry_plans.get(sym) or {}
        item["entry_zone_low"] = ep.get("entry_zone_low")
        item["entry_zone_high"] = ep.get("entry_zone_high")
        item["stop_price"] = ep.get("stop_price")
        item["target_price"] = ep.get("target_price")
        item["entry_rr"] = ep.get("risk_reward")

        rc = research_cards.get(sym) or {}
        item["latest_recommendation"] = rc.get("latest_recommendation")

        fs = synthesis_data.get(sym) or {}
        item["synthesis_recommendation"] = fs.get("recommendation")
        item["models_agree"] = fs.get("models_agree")
        item["dual_consensus_json"] = fs.get("dual_consensus_json")
        item["cio_model_used"] = fs.get("model_used")
        item["synthesis_updated_at"] = fs.get("updated_at")
        item["decision_safety"] = fs.get("decision_safety")

        if annotate_item is not None:
            try:
                annotate_item(item, pol)
            except Exception:
                pass
        out[sym] = item
    return out


def _trust_degraded(item: dict | None) -> bool:
    """True when buy-side CIO is TRUST DEGRADED (blocks propose-ready). Fail-open otherwise."""
    item = item or {}
    rec = item.get("synthesis_recommendation") or item.get("latest_recommendation")
    dual = item.get("dual_consensus_json")
    if not rec and not dual and item.get("models_agree") is None:
        return False
    try:
        from lib.cio_trust_bundle import BUY_SIDE, compute_cio_trust_bundle, _rec
        import json
        if isinstance(dual, str):
            try:
                dual = json.loads(dual)
            except Exception:
                dual = {}
        trust = compute_cio_trust_bundle(
            recommendation=rec,
            synthesis_updated_at=item.get("synthesis_updated_at"),
            models_agree=item.get("models_agree"),
            dual_consensus=dual if isinstance(dual, dict) else {},
            model_used=item.get("cio_model_used"),
            decision_quality_status=item.get("decision_quality_status"),
            decision_safety=item.get("decision_safety"),
            actionable=item.get("decision_actionable"),
            instrument_type=item.get("instrument_type"),
            on_main=True,
        )
        if str(trust.get("level") or "").upper() != "DEGRADED":
            return False
        # HOLD/AVOID are not propose candidates — don't treat as trust-block desk state
        return _rec(rec) in BUY_SIDE or not _rec(rec)
    except Exception:
        return False


def build_watch_decision_desk(
    db_query: Callable,
    symbols: list[str] | None = None,
    *,
    max_symbols: int = 80,
) -> dict[str, Any]:
    """Build deterministic Watch MAIN Decision Desk payload."""
    _scripts_path()
    from lib.data_broker.catalyst_record import get_catalyst_record
    from lib.data_broker.indicator_snapshot import get_indicator_snapshot
    from lib.data_broker.portfolio_snapshot import get_portfolio_snapshot

    if not symbols:
        symbols = _main_lane_symbols(db_query, max_symbols=max_symbols)
    else:
        symbols = [str(s).upper() for s in symbols if s][:max_symbols]

    resistance_pref = _pref_json(db_query, RESISTANCE_KEY)
    resistance_map = resistance_pref.get("symbols") or {}
    snap = get_portfolio_snapshot()
    book_equity = _f((snap.get("totals") or {}).get("total_value")) or DEFAULT_BOOK
    fund_lt_map = _load_fund_lookthrough_map()

    indicators = get_indicator_snapshot(symbols) if symbols else {"by_symbol": {}}
    by_ind = indicators.get("by_symbol") or {}
    meta = _watch_meta(db_query, symbols)

    rows_out: list[dict[str, Any]] = []
    price_ages: list[float] = []
    rsi_ages: list[float] = []
    stale_n = 0
    gap_n = 0
    ticket_pending_n = 0
    propose_ready_n = 0

    for sym in symbols:
        quote = _quote(sym)
        ind = by_ind.get(sym) or {}
        item = meta.get(sym) or {}
        packet = item.get("decision_packet") or {}
        if isinstance(packet, str):
            import json
            try:
                packet = json.loads(packet)
            except Exception:
                packet = {}

        ticket = _ticket_state(packet if isinstance(packet, dict) else {})
        admitted = _admission_now(item)
        price = quote.get("price")
        rsi = _f(ind.get("rsi"))
        ind_age_h = _age_hours(ind.get("computed_at"))

        entry_low = _f(item.get("entry_zone_low"))
        entry_high = _f(item.get("entry_zone_high"))
        stop = _f(item.get("stop_price"))
        target = _f(item.get("target_price"))
        rr = _f(item.get("entry_rr"))
        if rr is None and price and stop and target and price > stop:
            risk = price - stop
            reward = target - price
            if risk > 0:
                rr = round(reward / risk, 2)

        res = resistance_map.get(sym) or {}
        try:
            cat = get_catalyst_record(db_query, sym)
        except Exception:
            cat = None

        earnings_date = None
        ed = item.get("next_earnings_date")
        if ed:
            earnings_date = ed.isoformat()[:10] if hasattr(ed, "isoformat") else str(ed)[:10]

        cio_blocked = _cio_blocks(item)
        trust_degraded = _trust_degraded(item)
        intel = derive_setup_state(
            admitted=admitted,
            ticket=ticket,
            price=price,
            rsi=rsi,
            as_of=quote.get("as_of"),
            cio_blocked=cio_blocked,
            trust_degraded=trust_degraded,
        )
        age_h = intel.get("price_age_h")
        if age_h is not None:
            price_ages.append(float(age_h))
        if ind_age_h is not None:
            rsi_ages.append(float(ind_age_h))
        if intel.get("stale"):
            stale_n += 1
        if intel.get("data_gap"):
            gap_n += 1
        if intel.get("ticket_pending"):
            ticket_pending_n += 1
        if intel.get("actionable"):
            propose_ready_n += 1

        company = " · ".join(x for x in [item.get("profile_sector"), item.get("profile_industry")] if x)
        instrument_type = str(item.get("instrument_type") or "")
        lookthrough = fund_lt_map.get(sym)

        advisory = build_watch_advisory(
            symbol=sym,
            desk_state=str(intel.get("desk_state") or intel.get("now")),
            price=price,
            entry_low=entry_low,
            entry_high=entry_high,
            stop=stop,
            target=target,
            rr=rr,
            rsi=rsi,
            sma_20=_f(ind.get("sma_20")),
            sma_50=_f(ind.get("sma_50")),
            sma_200=_f(ind.get("sma_200")),
            sma20_pct=_f(ind.get("sma20_pct")),
            sma50_pct=_f(ind.get("sma50_pct")),
            sma200_pct=_f(ind.get("sma200_pct")),
            macd_signal=ind.get("macd_signal"),
            alignment=ind.get("alignment"),
            obv_signal=ind.get("obv_signal"),
            obv_trend=ind.get("obv_trend"),
            cmf_signal=ind.get("cmf_signal"),
            cmf_value=_f(ind.get("cmf")),
            volume_ratio=_f(ind.get("volume_ratio")),
            instrument_type=instrument_type,
            resistance=res,
            catalyst=cat,
            earnings_date=earnings_date,
            ticket=ticket,
            book_equity=book_equity,
            why=list(intel.get("why") or []),
            company=company[:80] if company else None,
            lookthrough=lookthrough,
            price_age_h=age_h,
        )

        chips = _provenance_chips(item)
        if cio_blocked:
            chips.append({"tone": "red", "label": "CIO block", "detail": "AVOID/SELL on research card or synthesis"})
        elif trust_degraded:
            chips.append({"tone": "amber", "label": "TRUST DEGRADED", "detail": "dual/Street/synthesis gates failed"})
        if intel.get("data_gap") == "rsi_missing":
            chips.append({"tone": "red", "label": "RSI gap", "detail": "indicator_confluence_cache missing"})
        elif intel.get("stale") and not cio_blocked:
            chips.append({"tone": "amber", "label": "stale quote", "detail": f"{age_h:.0f}h old" if age_h else "stale"})

        rows_out.append({
            "symbol": sym,
            "now": intel.get("now"),
            "desk_state": intel.get("desk_state"),
            "data_gap": intel.get("data_gap"),
            "actionable": intel.get("actionable"),
            "ticket_pending": intel.get("ticket_pending"),
            "cio_blocked": cio_blocked,
            "trust_degraded": trust_degraded,
            "price": price,
            "price_as_of": quote.get("as_of"),
            "price_source": quote.get("source"),
            "price_age_h": age_h,
            "rsi": rsi,
            "rsi_computed_at": ind.get("computed_at"),
            "rsi_age_h": ind_age_h,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "stop": stop,
            "target": target,
            "rr": rr,
            "ticket": ticket,
            "advisory": advisory,
            "chips": chips,
            "provenance": {
                "source": item.get("source"),
                "origin_system": item.get("origin_system"),
                "directive_id": item.get("directive_id"),
                "sector": item.get("profile_sector"),
            },
            "resistance": res,
            "catalyst": cat,
        })

    def _median(vals: list[float]) -> float | None:
        if not vals:
            return None
        s = sorted(vals)
        mid = len(s) // 2
        return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2

    actionable_rows = [r for r in rows_out if r.get("now") in ("GO", "WAIT") and not r.get("data_gap")]
    med_price_age = _median([float(r["price_age_h"]) for r in actionable_rows if r.get("price_age_h") is not None])
    med_rsi_age = _median([float(r["rsi_age_h"]) for r in actionable_rows if r.get("rsi_age_h") is not None])

    return {
        "ok": True,
        "llm_in_path": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol_count": len(rows_out),
        "rows": rows_out,
        "by_symbol": {r["symbol"]: r for r in rows_out},
        "freshness": {
            "price_age_h_median": round(med_price_age, 1) if med_price_age is not None else None,
            "rsi_age_h_median": round(med_rsi_age, 1) if med_rsi_age is not None else None,
            "stale_symbol_count": stale_n,
            "data_gap_count": gap_n,
            "ticket_pending_count": ticket_pending_n,
            "propose_ready_count": propose_ready_n,
            "symbol_count": len(rows_out),
            "resistance_generated_at": resistance_pref.get("generated_at"),
        },
    }
