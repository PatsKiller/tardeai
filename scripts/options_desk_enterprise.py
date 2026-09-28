#!/usr/bin/env python3
"""options_desk_enterprise.py — Enterprise trade desk layer for options_engine.

Adds institutional-grade controls on top of the advisory desk:
  • Earnings / event blackout (FMP calendar)
  • Liquidity gates (OI, volume, bid-ask spread)
  • Vol analytics (term structure, put/call skew from live chain)
  • Book-level greeks aggregation (Δ, Γ, Θ, ν)
  • Portfolio risk preflight (concentration, net delta, notional caps)
  • Desk approval queue (operator review before live submit)
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
DESK_RUNTIME = PROJECT_ROOT / "data" / "runtime" / "options_desk_enterprise.json"

SHORT_STRATEGIES = frozenset({"covered_call", "cash_secured_put", "credit_spread"})
BLOCKING_STRATEGIES = frozenset({"covered_call", "cash_secured_put", "credit_spread", "long_call"})

# Sentinel: the earnings provider could not answer. NEVER equal to "" (no
# scheduled earnings) — event gates must treat these two cases differently.
EARNINGS_UNKNOWN = "UNKNOWN"
_EARNINGS_LAST_ERROR = ""

# Session labels (lib.canonical_observation.market_session, lower-cased) that are a
# closed market for a listed equity option order. Only REGULAR is open.
CLOSED_SESSIONS = frozenset({"closed", "unsupported", "weekend", "pre_market", "after_hours"})


def _f(v, default=0.0) -> float:
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return default


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def load_desk_config() -> dict:
    """Merge portfolio_intent options_desk_settings with env overrides."""
    cfg: dict = {}
    try:
        import yaml
        intent = yaml.safe_load((PROJECT_ROOT / "assets" / "portfolio_intent.yaml").read_text()) or {}
        cfg = dict(intent.get("options_desk_settings") or {})
        cc = intent.get("covered_call_settings") or {}
        cfg.setdefault("earnings_blackout_days", cc.get("earnings_blackout_days", 14))
    except Exception:
        cfg = {}
    cfg.setdefault("earnings_blackout_days", int(os.getenv("OPTIONS_EARNINGS_BLACKOUT_DAYS", "14")))
    cfg.setdefault("min_open_interest", int(os.getenv("OPTIONS_MIN_OI", "50")))
    cfg.setdefault("min_volume", int(os.getenv("OPTIONS_MIN_VOLUME", "5")))
    cfg.setdefault("max_bid_ask_spread_pct", float(os.getenv("OPTIONS_MAX_SPREAD_PCT", "12.0")))
    cfg.setdefault("require_chain_for_live", os.getenv("OPTIONS_REQUIRE_CHAIN_LIVE", "1") == "1")
    cfg.setdefault("max_net_delta_pct", float(os.getenv("OPTIONS_MAX_NET_DELTA_PCT", "35.0")))
    cfg.setdefault("max_symbol_notional_pct", float(os.getenv("OPTIONS_MAX_SYMBOL_NOTIONAL_PCT", "25.0")))
    cfg.setdefault("approval_required", os.getenv("OPTIONS_APPROVAL_REQUIRED", "1") == "1")
    # Order gates (2026-09-27): an approval is a decision about ONE set of legs at ONE
    # time. It is pinned (approval_pin) and expires; preflight_desk_gate refuses after this.
    cfg.setdefault("approval_ttl_minutes", int(os.getenv("OPTIONS_APPROVAL_TTL_MINUTES", "240")))
    cfg.setdefault("desk_tier_edge_a", float(os.getenv("OPTIONS_DESK_TIER_A_EDGE", "72")))
    cfg.setdefault("desk_tier_edge_b", float(os.getenv("OPTIONS_DESK_TIER_B_EDGE", "62")))
    # Defined-risk credit spreads: refuse max_profit / max_loss below this floor.
    # 0.25 ⇒ may lose at most 4× the credit. AMZN-class 0.06 R:R ($66 vs $1,184)
    # was Tier A / live eligible with no model veto (2026-09-25) — that is immature.
    # Does NOT apply to cash_secured_put (assignment economics are different).
    cfg.setdefault(
        "min_credit_spread_rr",
        float(os.getenv("OPTIONS_MIN_CREDIT_SPREAD_RR", "0.25")),
    )
    # Hard preflight limits (live path only — advisory desk may warn)
    hr = cfg.get("hard_risk_limits") or {}
    cfg.setdefault("hard_max_contracts_per_order", int(hr.get("max_contracts_per_order", 5)))
    cfg.setdefault("hard_max_daily_orders", int(hr.get("max_daily_orders", 10)))
    cfg.setdefault("hard_max_daily_notional", float(hr.get("max_daily_notional", 50_000)))
    cfg.setdefault("hard_max_daily_loss", float(hr.get("max_daily_loss", 5_000)))
    cfg.setdefault("hard_max_per_strategy_notional", float(hr.get("max_per_strategy_notional", 30_000)))
    cfg.setdefault("hard_max_per_account_notional", float(hr.get("max_per_account_notional", 75_000)))
    cfg.setdefault("hard_min_buying_power", float(hr.get("min_buying_power", 5_000)))
    cfg.setdefault("hard_quote_max_age_seconds", int(hr.get("quote_max_age_seconds", 120)))
    cfg.setdefault("hard_chain_max_age_seconds", int(hr.get("chain_max_age_seconds", 300)))
    cfg.setdefault("hard_quote_move_tolerance_pct", float(hr.get("quote_move_tolerance_pct", 2.0)))
    return cfg


def _hard_block(
    code: str,
    reason: str,
    *,
    severity: str = "hard",
    source: str = "options_desk_enterprise",
    snapshot: Optional[dict] = None,
) -> dict:
    return {
        "code": code,
        "reason": reason,
        "severity": severity,
        "source": source,
        "function": "evaluate_hard_risk_blocks",
        "snapshot": snapshot or {},
    }


def is_desk_queue_approved(proposal_id: str) -> bool:
    ok, _ = check_preflight_approval(proposal_id)
    return ok


def evaluate_hard_risk_blocks(
    proposal: dict,
    *,
    mode: str = "live",
    holdings: Optional[List[dict]] = None,
    positions: Optional[List[dict]] = None,
    cfg: Optional[dict] = None,
) -> List[dict]:
    """Configurable hard preflight rejects for live paths. Each block is machine-coded."""
    # Live-adjacent modes that must surface hard risk blocks. ``submit``/``preflight`` are the
    # P0-4 readiness modes; ``advisory``/``dry_run``/``audit`` intentionally return no blocks.
    if mode not in ("live", "operator_required", "submit", "preflight"):
        return []
    # ORDER GATE (2026-09-27): on the order path an input the desk does not have is a
    # refusal, not a pass. ``live``/``operator_required`` keep the old "skip when absent"
    # behaviour because they compute live_eligible for the desk render; ``submit`` and
    # ``preflight`` are the modes that stand between an approved card and a broker call.
    fail_closed = mode in ("submit", "preflight")
    cfg = cfg or load_desk_config()
    blocks: List[dict] = []
    warnings: List[dict] = []
    sym = (proposal.get("symbol") or proposal.get("underlying") or "").upper()
    strat = proposal.get("strategy") or ""
    dte = int(proposal.get("dte") or 30)
    contracts = int(proposal.get("contracts") or 1)
    ent = proposal.get("enterprise") or {}
    liq = ent.get("liquidity") or proposal.get("liquidity") or {}

    # Earnings blackout
    blackout = ent.get("earnings") or earnings_blackout_check(sym, dte=dte, strategy=strat)
    if blackout.get("in_blackout"):
        # Preserve the SPECIFIC refusal (EARNINGS_TIMESTAMP_UNKNOWN /
        # EARNINGS_TIMESTAMP_INVALID) as the top-level code. Flattening every
        # earnings refusal to 'earnings_blackout' made a dead provider
        # indistinguishable from a genuine scheduled blackout in the UI,
        # refusal analytics and health alerts (2026-07-20 review).
        code = blackout.get("refusal_code") or "earnings_blackout"
        # OPERATOR-ACKNOWLEDGED EARNINGS RISK — authorised by the operator
        # 2026-07-20 ("wire it"), scoped deliberately narrow.
        #
        # Selling premium through an earnings print is a legitimate strategy and
        # the risk is the operator's to take. Without this the desk offers an
        # actionable covered_call_earnings_iv card that the gate always refuses,
        # recreating the exact CSCO contradiction the incident was about. An
        # acknowledgement the gate ignores is worse than no acknowledgement.
        #
        # ALL of these must hold for the downgrade:
        #   * the block is a SCHEDULED-earnings blackout, not unknown/invalid;
        #   * the ack names the EXACT earnings date carried in this block, so
        #     consent to one report can never silently cover a different or
        #     rescheduled one;
        #   * the ack records who acknowledged it and when, for the audit trail.
        #
        # EARNINGS_TIMESTAMP_UNKNOWN and EARNINGS_TIMESTAMP_INVALID are NOT
        # acknowledgeable — you cannot consent to a risk whose date the system
        # could not establish. Share coverage, liquidity, account tier and
        # per-order 2FA are untouched and still gate the order.
        # Must be a dict. A truthy non-dict (e.g. operator_ack="yes" from a
        # sloppy caller) previously raised AttributeError here — a crash inside
        # the block evaluator is strictly worse than a block, since it can take
        # out the whole evaluation. Anything that is not a mapping is simply not
        # an acknowledgement.
        _ack = proposal.get("operator_ack")
        _ack = _ack if isinstance(_ack, dict) else {}
        _blk_date = str(blackout.get("next_earnings") or "")
        _ack_ok = (
            code == "earnings_blackout"
            and str(_ack.get("code")) == "EARNINGS_INSIDE_CONTRACT"
            and bool(_blk_date)
            and str(_ack.get("earnings_date") or "") == _blk_date
            and bool(_ack.get("acknowledged_by"))
            and bool(_ack.get("acknowledged_at"))
        )
        if _ack_ok:
            warnings.append({
                "code": "EARNINGS_INSIDE_CONTRACT_ACKNOWLEDGED",
                "severity": "warning",
                "reason": (f"Earnings {_blk_date} fall inside this contract — risk accepted by "
                           f"{_ack.get('acknowledged_by')} at {_ack.get('acknowledged_at')}"),
                "source": "options_desk_enterprise",
                "snapshot": {"blackout": blackout, "operator_ack": _ack},
            })
        else:
            blocks.append(_hard_block(code, blackout.get("reason") or "earnings window",
                                      snapshot=blackout))

    # Ex-dividend risk for covered calls
    if strat == "covered_call" and proposal.get("ex_div_within_dte"):
        blocks.append(_hard_block("ex_dividend_cc_risk", "ex-dividend within DTE for covered call",
                                  snapshot={"ex_div": proposal.get("ex_div_date")}))

    # Liquidity / chain
    if proposal.get("data_source") == "bs_estimate" and cfg.get("require_chain_for_live"):
        blocks.append(_hard_block("bs_estimate_only", "Black-Scholes-only estimate — live chain required",
                                  snapshot={"data_source": "bs_estimate"}))
    if proposal.get("occ_symbol") is None and proposal.get("contract") is None and cfg.get("require_chain_for_live"):
        blocks.append(_hard_block("no_resolved_occ", "no resolved OCC contract on proposal"))
    if fail_closed and (not isinstance(liq, dict) or "pass" not in liq):
        blocks.append(_hard_block("liquidity_unknown",
                                  "no liquidity verdict on this proposal (enterprise.liquidity absent)",
                                  snapshot={"liquidity": liq if isinstance(liq, dict) else None}))
        liq = {}
    if isinstance(liq, dict) and not liq.get("pass", True):
        for issue in liq.get("issues") or []:
            code = "liquidity_gate"
            if "OI" in str(issue):
                code = "oi_below_threshold"
            elif "volume" in str(issue).lower():
                code = "volume_below_threshold"
            elif "spread" in str(issue).lower():
                code = "spread_too_wide"
            blocks.append(_hard_block(code, str(issue), snapshot=liq))

    # Defined-risk credit spread asymmetric payoff (2026-09-25 maturity).
    rr_reason = credit_spread_rr_block(proposal, cfg=cfg)
    if rr_reason:
        blocks.append(_hard_block(
            "credit_spread_rr_below_floor",
            rr_reason,
            snapshot={
                "risk_reward": credit_spread_rr_ratio(proposal),
                "min_credit_spread_rr": cfg.get("min_credit_spread_rr"),
                "max_profit": proposal.get("max_profit"),
                "max_loss": proposal.get("max_loss"),
            },
        ))

    # Quote / chain staleness. On the order path an ABSENT age is unknown, not fresh.
    q_age = proposal.get("quote_age_seconds")
    if q_age is None:
        if fail_closed:
            blocks.append(_hard_block("quote_age_unknown",
                                      "quote age unknown (no quote_time on the proposal's contract)",
                                      snapshot={"quote_time": proposal.get("quote_time"),
                                                "quotes_as_of": proposal.get("quotes_as_of")}))
    elif float(q_age) > cfg.get("hard_quote_max_age_seconds", 120):
        blocks.append(_hard_block("quote_stale", f"quote age {q_age}s exceeds cap",
                                  snapshot={"quote_age_seconds": q_age}))
    c_age = proposal.get("chain_age_seconds")
    if c_age is None:
        if fail_closed:
            blocks.append(_hard_block("chain_age_unknown",
                                      "chain age unknown (no fetched_at on the chain this proposal came from)",
                                      snapshot={"chain_fetched_at": proposal.get("chain_fetched_at")}))
    elif float(c_age) > cfg.get("hard_chain_max_age_seconds", 300):
        blocks.append(_hard_block("option_chain_stale", f"chain age {c_age}s exceeds cap",
                                  snapshot={"chain_age_seconds": c_age}))
    session = proposal.get("market_session")
    if session is None or str(session).strip() == "":
        if fail_closed:
            blocks.append(_hard_block("market_session_unknown",
                                      "market session unknown (proposal carries no market_session)"))
    elif str(session).strip().lower() in CLOSED_SESSIONS:
        # Listed equity options trade in the regular session only; a weekend or
        # pre/after-hours label is a closed market for an option order.
        blocks.append(_hard_block("market_closed", f"session={session} (options trade in the regular session only)",
                                  snapshot={"market_session": session}))

    # Contract caps
    if contracts > cfg.get("hard_max_contracts_per_order", 5):
        blocks.append(_hard_block("max_contracts_per_order",
                                  f"{contracts} > {cfg['hard_max_contracts_per_order']}",
                                  snapshot={"contracts": contracts}))

    notional = _f(proposal.get("premium_total")) or _f(proposal.get("max_loss")) or _f(proposal.get("underlying_price")) * 100 * contracts
    if notional > cfg.get("hard_max_per_strategy_notional", 30_000):
        blocks.append(_hard_block("max_per_strategy_notional",
                                  f"notional ${notional:,.0f} exceeds strategy cap",
                                  snapshot={"notional": notional, "strategy": strat}))

    # Minimum buying power for the live submit. The desk never reads buying power (that
    # is a broker read, outside the desk grant), so on the order path its absence is a
    # refusal by design: buying_power_unknown until a granted layer supplies it.
    bp = proposal.get("buying_power")
    if bp is None:
        if fail_closed:
            blocks.append(_hard_block("buying_power_unknown",
                                      "buying power unknown (no broker buying-power read on this proposal)",
                                      snapshot={"min": cfg.get("hard_min_buying_power")}))
    elif _f(bp) < cfg.get("hard_min_buying_power", 5_000):
        blocks.append(_hard_block("min_buying_power",
                                  f"buying power ${_f(bp):,.0f} below minimum ${cfg.get('hard_min_buying_power'):,.0f}",
                                  snapshot={"buying_power": _f(bp), "min": cfg.get("hard_min_buying_power")}))

    # Assignment risk flag
    if proposal.get("assignment_risk") or proposal.get("deep_itm_short"):
        blocks.append(_hard_block("assignment_exercise_risk", "assignment/exercise risk flagged",
                                  snapshot={"assignment_risk": True}))

    # Portfolio-level when context provided
    if holdings is not None and positions is not None:
        book = portfolio_risk_preflight([proposal], holdings, positions, cfg=cfg)
        for w in book.get("hard_blocks") or []:
            if isinstance(w, dict):
                blocks.append(w)
            else:
                blocks.append(_hard_block("portfolio_risk", str(w), snapshot=book.get("limits")))

    # Enterprise blocks from enrich
    for b in ent.get("blocks") or proposal.get("enterprise_blocks") or []:
        if isinstance(b, str):
            blocks.append(_hard_block("enterprise_block", b))
        elif isinstance(b, dict):
            blocks.append(b)

    return blocks


_EARNINGS_CACHE: Dict[str, str] = {}
_EARNINGS_CACHE_AT: Optional[datetime] = None


def earnings_calendar(symbols: List[str]) -> Dict[str, str]:
    """Next earnings date per symbol (FMP), cached 6h."""
    global _EARNINGS_CACHE, _EARNINGS_CACHE_AT
    syms = {s.upper() for s in symbols if s}
    fresh = bool(_EARNINGS_CACHE_AT) and (_now() - _EARNINGS_CACHE_AT).total_seconds() < 21600
    missing = {s for s in syms if s not in _EARNINGS_CACHE}
    # Refetch when the cache is stale, OR when newly-requested symbols aren't cached
    # yet — otherwise a name added mid-window silently skips its earnings blackout.
    if not fresh or missing:
        to_fetch = syms if not fresh else missing
        # Source of record is scripts/earnings_provider.py (symbol_profiles,
        # written daily from yfinance by earnings_enrich.py, with an on-demand
        # yfinance lookup for symbols outside enrichment coverage). The former
        # FMP v3 path is dead: HTTP 403 for non-legacy keys, and the key is
        # additionally quota-exhausted (verified 2026-07-20).
        from earnings_provider import get_earnings, SCHEDULED, NONE_SCHEDULED
        unknown: set[str] = set()
        reasons = []
        for s, info in get_earnings(to_fetch).items():
            if info.state == SCHEDULED and info.date:
                _EARNINGS_CACHE[s] = info.date.isoformat()
            elif info.state == NONE_SCHEDULED:
                _EARNINGS_CACHE[s] = ""
            else:
                # Provider could not answer for THIS symbol — never cache a
                # clearing value; the event gate must fail closed on it.
                _EARNINGS_CACHE.pop(s, None)
                unknown.add(s)
                reasons.append(f"{s}: {info.reason}")
        if reasons:
            globals()["_EARNINGS_LAST_ERROR"] = "; ".join(reasons)[:300]
        if not fresh:
            _EARNINGS_CACHE_AT = _now()
        return {s: (EARNINGS_UNKNOWN if s in unknown else _EARNINGS_CACHE.get(s, ""))
                for s in syms}
    return {s: _EARNINGS_CACHE.get(s, "") for s in syms}


def earnings_blackout_check(
    symbol: str,
    *,
    dte: int,
    strategy: str,
    blackout_days: Optional[int] = None,
) -> dict:
    """Return blackout status for short premium / directional entries near earnings."""
    cfg = load_desk_config()
    days = int(blackout_days or cfg.get("earnings_blackout_days") or 14)
    sym = (symbol or "").upper()
    if strategy not in BLOCKING_STRATEGIES:
        return {"in_blackout": False, "symbol": sym, "strategy": strategy}
    cal = earnings_calendar([sym])
    earn_raw = cal.get(sym) or ""
    if earn_raw == EARNINGS_UNKNOWN:
        # FAIL CLOSED: unknown event timing is not "no event". A blocking
        # strategy must not be cleared by a dead provider (2026-07-20 — FMP v3
        # earning_calendar returns 403 for non-legacy keys).
        return {
            "in_blackout": True,
            "symbol": sym,
            "strategy": strategy,
            "next_earnings": None,
            "days_to_earnings": None,
            "data_blocked": True,
            "refusal_code": "EARNINGS_TIMESTAMP_UNKNOWN",
            "reason": (f"Earnings timing unavailable — provider error "
                       f"({_EARNINGS_LAST_ERROR[:120] or 'unknown'}); "
                       f"{strategy} fails closed until an earnings source is restored"),
        }
    if not earn_raw:
        return {"in_blackout": False, "symbol": sym, "next_earnings": None, "days_to_earnings": None}
    try:
        if not isinstance(earn_raw, (str, date)):
            raise TypeError(f"non-date earnings value of type {type(earn_raw).__name__}")
        earn_dt = earn_raw if isinstance(earn_raw, date) else date.fromisoformat(str(earn_raw)[:10])
    except (ValueError, TypeError) as e:
        # FAIL CLOSED: a value we cannot parse is UNKNOWN timing, not proof that
        # no event exists. Previously this returned in_blackout=False, so a
        # malformed/partial provider row cleared the gate (2026-07-20 review).
        return {
            "in_blackout": True,
            "symbol": sym,
            "strategy": strategy,
            "next_earnings": None,
            "days_to_earnings": None,
            "data_blocked": True,
            "refusal_code": "EARNINGS_TIMESTAMP_INVALID",
            "raw_value": str(earn_raw)[:60],
            "reason": (f"Earnings value {str(earn_raw)[:40]!r} is not a usable date "
                       f"({e}) — {strategy} fails closed on unparseable event timing"),
        }
    today = date.today()
    days_to = (earn_dt - today).days
    # Block if earnings falls before expiration or within blackout window
    in_window = 0 <= days_to <= days
    expires_before_earn = dte >= days_to > 0
    in_blackout = in_window or expires_before_earn
    return {
        "in_blackout": in_blackout,
        "symbol": sym,
        "strategy": strategy,
        "next_earnings": earn_dt.isoformat(),
        "days_to_earnings": days_to,
        "blackout_days": days,
        "reason": (
            f"Earnings {earn_dt} in {days_to}d — inside {days}d blackout"
            if in_blackout else ""
        ),
    }


def liquidity_gate(contract: dict, *, cfg: Optional[dict] = None) -> dict:
    """Hard liquidity check on a chain contract."""
    cfg = cfg or load_desk_config()
    bid, ask = _f(contract.get("bid")), _f(contract.get("ask"))
    mid = _f(contract.get("mid"))
    if mid <= 0 and bid > 0 and ask > 0:
        mid = (bid + ask) / 2.0
    oi_missing = contract.get("oi") is None
    oi = int(_f(contract.get("oi")))
    vol = int(_f(contract.get("volume")))
    spread_pct = 100.0 * (ask - bid) / mid if mid > 0 and ask >= bid else 999.0
    min_oi = int(cfg.get("min_open_interest") or 50)
    min_vol = int(cfg.get("min_volume") or 5)
    max_spread = float(cfg.get("max_bid_ask_spread_pct") or 12.0)
    issues = []
    if oi_missing:
        # Still refused, but named: a chain row without the field is not "0 open interest".
        issues.append("OI unknown (chain field missing)")
    elif oi < min_oi:
        issues.append(f"OI {oi} < {min_oi}")
    if vol < min_vol and oi < min_oi * 2:
        issues.append(f"volume {vol} < {min_vol}")
    if spread_pct > max_spread:
        issues.append(f"spread {spread_pct:.1f}% > {max_spread}%")
    if mid <= 0:
        issues.append("no quotable mid")
    return {
        "pass": not issues,
        "oi": oi,
        "volume": vol,
        "bid_ask_spread_pct": round(spread_pct, 2) if spread_pct < 900 else None,
        "mid": round(mid, 4) if mid else None,
        "issues": issues,
    }


def vol_analytics_from_chain(chain: dict, underlying: float) -> dict:
    """Term structure + put/call skew from normalized Schwab chain."""
    if not chain or underlying <= 0:
        return {"ok": False}
    expirations = chain.get("expirations") or []
    if not expirations:
        return {"ok": False, "reason": chain.get("reason") or chain.get("status") or "empty_chain"}
    term: List[dict] = []
    for exp in sorted(expirations, key=lambda x: int(x.get("dte") or 0))[:8]:
        dte = int(exp.get("dte") or 0)
        if dte < 7:
            continue
        call_ivs, put_ivs = [], []
        for row in exp.get("strikes") or []:
            strike = _f(row.get("strike"))
            if strike <= 0:
                continue
            moneyness = abs(strike - underlying) / underlying
            if moneyness > 0.08:
                continue
            iv = _f(row.get("iv"))
            if iv > 3:
                iv /= 100.0
            if iv <= 0:
                continue
            if row.get("side") == "call":
                call_ivs.append(iv)
            elif row.get("side") == "put":
                put_ivs.append(iv)
        if not call_ivs and not put_ivs:
            continue
        atm_call = sum(call_ivs) / len(call_ivs) if call_ivs else None
        atm_put = sum(put_ivs) / len(put_ivs) if put_ivs else None
        atm = None
        skew = None
        if atm_call and atm_put:
            atm = (atm_call + atm_put) / 2.0
            skew = round((atm_put - atm_call) * 100.0, 2)
        elif atm_call:
            atm = atm_call
        elif atm_put:
            atm = atm_put
        term.append({
            "exp": exp.get("exp"),
            "dte": dte,
            "atm_iv_pct": round(atm * 100.0, 2) if atm else None,
            "put_call_skew_pct": skew,
        })
    if not term:
        return {"ok": False, "reason": "no_atm_iv"}
    front = term[0]
    back = term[-1] if len(term) > 1 else term[0]
    contango = None
    if front.get("atm_iv_pct") and back.get("atm_iv_pct"):
        contango = round(back["atm_iv_pct"] - front["atm_iv_pct"], 2)
    return {
        "ok": True,
        "underlying": round(underlying, 2),
        "term_structure": term,
        "front_iv_pct": front.get("atm_iv_pct"),
        "back_iv_pct": back.get("atm_iv_pct"),
        "term_slope_pct": contango,
        "avg_put_skew_pct": round(
            sum(t["put_call_skew_pct"] for t in term if t.get("put_call_skew_pct") is not None)
            / max(1, sum(1 for t in term if t.get("put_call_skew_pct") is not None)),
            2,
        ) if any(t.get("put_call_skew_pct") is not None for t in term) else None,
    }


def build_iv_surface_grid(chain: dict, underlying: float, *, max_exps: int = 6, moneyness: float = 0.12) -> dict:
    """Strike × DTE IV grid from normalized Schwab chain (heatmap / surface UI)."""
    if not chain or underlying <= 0:
        return {"ok": False}
    expirations = sorted(chain.get("expirations") or [], key=lambda x: int(x.get("dte") or 0))
    expirations = [e for e in expirations if int(e.get("dte") or 0) >= 7][:max_exps]
    if not expirations:
        return {"ok": False, "reason": "no_expirations"}
    strike_set: set = set()
    for exp in expirations:
        for row in exp.get("strikes") or []:
            strike = _f(row.get("strike"))
            if strike > 0 and abs(strike - underlying) / underlying <= moneyness:
                strike_set.add(round(strike, 2))
    strikes = sorted(strike_set)
    if not strikes:
        return {"ok": False, "reason": "no_strikes"}
    cells: List[dict] = []
    expiries: List[dict] = []
    for exp in expirations:
        dte = int(exp.get("dte") or 0)
        expiries.append({"exp": exp.get("exp"), "dte": dte})
        by_strike: Dict[float, List[float]] = {}
        for row in exp.get("strikes") or []:
            strike = round(_f(row.get("strike")), 2)
            if strike not in strike_set:
                continue
            iv = _f(row.get("iv"))
            if iv > 3:
                iv /= 100.0
            if iv <= 0:
                continue
            by_strike.setdefault(strike, []).append(iv)
        for strike in strikes:
            ivs = by_strike.get(strike) or []
            cells.append({
                "strike": strike,
                "dte": dte,
                "exp": exp.get("exp"),
                "iv_pct": round(sum(ivs) / len(ivs) * 100.0, 1) if ivs else None,
            })
    return {
        "ok": True,
        "underlying": round(underlying, 2),
        "strikes": strikes,
        "expiries": expiries,
        "cells": cells,
    }


def fetch_vol_history(symbol: str, limit: int = 48) -> List[dict]:
    """Recent ATM IV / skew snapshots for trends sparkline."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return []
    conn = _conn()
    if not conn:
        return []
    lim = max(1, min(int(limit), 200))
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT captured_at, vol_analytics_json
               FROM options_chain_snapshots
               WHERE symbol = %s
               ORDER BY captured_at DESC
               LIMIT %s""",
            (sym, lim),
        )
        rows = cur.fetchall() or []
    except Exception:
        return []
    out: List[dict] = []
    for captured_at, vol_json in reversed(rows):
        vol = vol_json if isinstance(vol_json, dict) else {}
        if isinstance(vol_json, str):
            try:
                vol = json.loads(vol_json)
            except Exception:
                vol = {}
        out.append({
            "captured_at": captured_at.isoformat() if hasattr(captured_at, "isoformat") else str(captured_at),
            "front_iv_pct": vol.get("front_iv_pct"),
            "back_iv_pct": vol.get("back_iv_pct"),
            "term_slope_pct": vol.get("term_slope_pct"),
            "avg_put_skew_pct": vol.get("avg_put_skew_pct"),
        })
    return out


def _theta_decay_estimate(delta: float, gamma: float, iv: float, spot: float, dte: int) -> float:
    """Rough daily theta when chain theta unavailable."""
    if dte <= 0 or spot <= 0:
        return 0.0
    t = max(dte, 1) / 365.0
    vol = max(iv, 0.12)
    # Brenner-Subrahmanyam approximation scaled per contract. Returns the long-option
    # daily theta (negative), matching real chain theta convention; aggregate_book_greeks
    # flips the sign for short legs via side_mult.
    approx = -(spot * vol) / (2 * math.sqrt(t)) / 365.0
    # ATM contracts decay faster than OTM — magnitude scalar, NOT a sign flip.
    moneyness_scale = 1.0 if abs(delta) < 0.55 else 0.5
    return round(approx * moneyness_scale * 100.0, 2)


def aggregate_book_greeks(positions: List[dict], tech_map: Optional[dict] = None) -> dict:
    """Portfolio-level greeks from monitored open legs."""
    tech_map = tech_map or {}
    net_delta = net_gamma = net_theta = net_vega = 0.0
    net_delta_notional = 0.0
    by_underlying: Dict[str, dict] = {}
    legs = 0
    for pos in positions:
        qty = _f(pos.get("qty"), 1)
        mult = qty * 100.0
        delta = _f(pos.get("delta"))
        if delta == 0:
            # Estimate from moneyness if missing
            spot = _f(pos.get("underlying_price"))
            strike = _f(pos.get("strike"))
            dte = int(pos.get("dte") or 30)
            iv = 0.25
            if spot > 0 and strike > 0 and dte > 0:
                t = dte / 365.0
                d1 = (math.log(spot / strike) + 0.5 * iv * iv * t) / (iv * math.sqrt(t))
                def _ncdf(x: float) -> float:
                    k = 1.0 / (1.0 + 0.2316419 * abs(x))
                    poly = k * (0.319381530 + k * (-0.356563782 + k * (1.781477937 + k * (-1.821255978 + k * 1.330274429))))
                    n = math.exp(-x * x / 2.0) / math.sqrt(2 * math.pi)
                    return 1.0 - n * poly if x >= 0 else n * poly

                is_call = (pos.get("option_type") or "").lower() == "call"
                delta = _ncdf(d1) if is_call else _ncdf(d1) - 1.0
        side_mult = -1.0 if (pos.get("side") or "").upper() == "SHORT" or "short" in (pos.get("strategy") or "") else 1.0
        leg_delta = delta * mult * side_mult
        gamma = _f(pos.get("gamma")) * mult * side_mult
        theta = _f(pos.get("theta")) * mult * side_mult
        vega = _f(pos.get("vega")) * mult * side_mult
        if theta == 0:
            # Estimate is long-convention (negative); flip for short premium so the
            # book's net theta/day reflects decay collected, not decay paid.
            theta = _theta_decay_estimate(delta, gamma, 0.25, _f(pos.get("underlying_price")), int(pos.get("dte") or 30)) * qty * side_mult
        net_delta += leg_delta
        net_gamma += gamma
        net_theta += theta
        net_vega += vega
        net_delta_notional += leg_delta * _f(pos.get("underlying_price"))
        und = (pos.get("underlying") or "").upper()
        if und:
            bucket = by_underlying.setdefault(und, {"delta": 0.0, "theta": 0.0, "legs": 0})
            bucket["delta"] += leg_delta
            bucket["theta"] += theta
            bucket["legs"] += 1
        legs += 1
    return {
        "leg_count": legs,
        "net_delta_shares": round(net_delta, 1),
        "net_delta_notional": round(net_delta_notional, 2),
        "net_gamma": round(net_gamma, 4),
        "net_theta_per_day": round(net_theta, 2),
        "net_vega": round(net_vega, 2),
        "by_underlying": {
            k: {kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()}
            for k, v in sorted(by_underlying.items(), key=lambda x: -abs(x[1].get("delta", 0)))
        },
    }


def credit_spread_rr_ratio(proposal: dict) -> Optional[float]:
    """max_profit / max_loss for a credit_spread, or None if not computable."""
    if (proposal.get("strategy") or "") != "credit_spread":
        return None
    rr = proposal.get("risk_reward")
    if rr is not None:
        try:
            v = float(rr)
            if v >= 0:
                return v
        except (TypeError, ValueError):
            pass
    mx_p = _f(proposal.get("max_profit"))
    mx_l = _f(proposal.get("max_loss"))
    if mx_p > 0 and mx_l > 0:
        return mx_p / mx_l
    # Reconstruct from credit + width when stamped fields missing.
    credit = _f(proposal.get("premium_total"))
    if credit <= 0:
        credit = _f(proposal.get("premium")) * 100.0
    short_k = _f(proposal.get("short_strike") or proposal.get("strike"))
    long_k = _f(proposal.get("long_strike"))
    if credit > 0 and short_k > 0 and long_k > 0 and short_k > long_k:
        width = short_k - long_k
        mx_l = (width * 100.0) - credit
        if mx_l > 0:
            return credit / mx_l
    return None


def credit_spread_rr_block(
    proposal: dict,
    *,
    cfg: Optional[dict] = None,
) -> Optional[str]:
    """Human-readable refuse reason when credit_spread R:R is below floor; else None."""
    if (proposal.get("strategy") or "") != "credit_spread":
        return None
    cfg = cfg or load_desk_config()
    floor = _f(cfg.get("min_credit_spread_rr"), 0.25)
    if floor <= 0:
        return None  # operator disabled
    rr = credit_spread_rr_ratio(proposal)
    if rr is None:
        return "credit_spread R:R unknown — refuse rather than guess"
    if rr < floor:
        mx_p = _f(proposal.get("max_profit"))
        mx_l = _f(proposal.get("max_loss"))
        return (
            f"credit_spread R:R {rr:.3f} < min {floor:.2f} "
            f"(max profit ${mx_p:,.0f} vs max loss ${mx_l:,.0f}) — "
            f"asymmetric payoff refused"
        )
    return None


def desk_tier(edge: float, cfg: Optional[dict] = None) -> str:
    cfg = cfg or load_desk_config()
    if edge >= _f(cfg.get("desk_tier_edge_a"), 72):
        return "A"
    if edge >= _f(cfg.get("desk_tier_edge_b"), 62):
        return "B"
    return "C"


def enterprise_enrich_proposal(
    proposal: dict,
    *,
    contract: Optional[dict] = None,
    chain: Optional[dict] = None,
    cfg: Optional[dict] = None,
) -> dict:
    """Attach enterprise metadata and hard gates to a proposal row."""
    cfg = cfg or load_desk_config()
    sym = (proposal.get("symbol") or "").upper()
    strat = proposal.get("strategy") or ""
    dte = int(proposal.get("dte") or 30)
    edge = _f(proposal.get("edge_score"))

    blackout = earnings_blackout_check(sym, dte=dte, strategy=strat)
    liq = {"pass": True, "issues": []}
    if contract:
        liq = liquidity_gate(contract, cfg=cfg)
    elif proposal.get("data_source") == "bs_estimate" and cfg.get("require_chain_for_live"):
        liq = {"pass": False, "issues": ["BS estimate only — not eligible for live auto path"]}

    vol = {}
    und = _f(proposal.get("underlying_price"))
    if chain and und > 0:
        vol = vol_analytics_from_chain(chain, und)

    blocks = []
    if blackout.get("in_blackout"):
        blocks.append(blackout.get("reason") or "earnings_blackout")
    if not liq.get("pass"):
        # 2026-09-27: closed-market quotes (weekend OI 0, 100%+ spreads) are not a
        # liquidity verdict. Say so; the idea stays blocked until live quotes and a
        # fresh Validate, which approval requires anyway.
        try:
            from lib.canonical_observation import market_session
            from lib.options_income_quality import defer_liquidity
            session = market_session()
        except Exception:  # noqa: BLE001
            session, defer_liquidity = None, (lambda *_a, **_k: False)
        if defer_liquidity(session, cfg):
            proposal["liquidity_pending"] = True
            blocks.append(f"awaiting live quotes (market {str(session).lower().replace('_', ' ')}): "
                          + "; ".join(liq.get("issues") or []))
        else:
            blocks.extend(liq.get("issues") or [])
    rr_reason = credit_spread_rr_block(proposal, cfg=cfg)
    if rr_reason:
        blocks.append(rr_reason)

    tier = desk_tier(edge, cfg)
    live_eligible = not blocks and liq.get("pass", True)
    # No chain contract means no verifiable fill liquidity — never live-eligible,
    # regardless of the require_chain_for_live operator override.
    if contract is None:
        live_eligible = False
    if proposal.get("data_source") == "bs_estimate" and cfg.get("require_chain_for_live"):
        live_eligible = False

    proposal["desk_tier"] = tier
    proposal["enterprise"] = {
        "tier": tier,
        "live_eligible": live_eligible,
        "blocks": blocks,
        "earnings": blackout,
        "liquidity": liq,
        "vol_analytics": vol if vol.get("ok") else None,
        "approval_required": bool(cfg.get("approval_required")),
    }
    if blocks:
        proposal["enterprise_blocked"] = True
        note = " · Enterprise block: " + "; ".join(blocks[:3])
        proposal["reasoning"] = (proposal.get("reasoning") or "") + note
    return proposal


def portfolio_risk_preflight(
    proposals: List[dict],
    holdings: List[dict],
    positions: List[dict],
    *,
    cfg: Optional[dict] = None,
) -> dict:
    """Book-level risk snapshot for desk operator."""
    cfg = cfg or load_desk_config()
    total_mv = sum(_f(h.get("market_value")) for h in holdings if not h.get("is_cash")) or 1.0
    greeks = aggregate_book_greeks(positions)
    # Dollar-delta exposure (share-equivalent delta × each leg's real underlying price)
    # as a pct of book MV. No assumed share price.
    net_delta_pct = abs(greeks.get("net_delta_notional") or 0.0) / total_mv * 100.0

    sym_notional: Dict[str, float] = {}
    for p in proposals:
        sym = (p.get("symbol") or "").upper()
        notional = _f(p.get("premium_total")) or _f(p.get("max_loss")) or _f(p.get("underlying_price")) * 100
        sym_notional[sym] = sym_notional.get(sym, 0.0) + notional

    concentration = sorted(
        [{"symbol": s, "notional": round(v, 2), "pct": round(v / total_mv * 100, 2)} for s, v in sym_notional.items()],
        key=lambda x: -x["pct"],
    )
    top_sym_pct = concentration[0]["pct"] if concentration else 0.0
    warnings = []
    hard_blocks: List[dict] = []
    if net_delta_pct > _f(cfg.get("max_net_delta_pct"), 35):
        msg = f"Net delta exposure ~{net_delta_pct:.1f}% exceeds cap"
        warnings.append(msg)
        hard_blocks.append(_hard_block("max_net_delta_pct", msg,
                                      snapshot={"net_delta_pct": net_delta_pct,
                                                "cap": cfg.get("max_net_delta_pct")}))
    if top_sym_pct > _f(cfg.get("max_symbol_notional_pct"), 25):
        msg = f"Top symbol concentration {top_sym_pct:.1f}% exceeds cap"
        warnings.append(msg)
        hard_blocks.append(_hard_block("max_symbol_notional_pct", msg,
                                      snapshot={"top_sym_pct": top_sym_pct,
                                                "cap": cfg.get("max_symbol_notional_pct")}))

    blocked_count = sum(1 for p in proposals if p.get("enterprise_blocked"))
    live_count = sum(1 for p in proposals if (p.get("enterprise") or {}).get("live_eligible"))

    return {
        "captured_at": _iso(),
        "portfolio_mv": round(total_mv, 2),
        "proposal_count": len(proposals),
        "live_eligible_count": live_count,
        "enterprise_blocked_count": blocked_count,
        "greeks": greeks,
        "net_delta_pct_proxy": round(net_delta_pct, 2),
        "concentration": concentration[:8],
        "warnings": warnings,
        "hard_blocks": hard_blocks,
        "limits": {
            "max_net_delta_pct": cfg.get("max_net_delta_pct"),
            "max_symbol_notional_pct": cfg.get("max_symbol_notional_pct"),
        },
    }


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def sync_approval_queue(proposals: List[dict], *, apply: bool = True) -> dict:
    """Upsert desk proposals into options_approval_queue for operator review."""
    conn = _conn()
    if not conn:
        return {"ok": False, "error": "no_db"}
    cfg = load_desk_config()
    if not cfg.get("approval_required"):
        return {"ok": True, "skipped": True, "reason": "approval_not_required"}
    upserted = 0
    cur = conn.cursor()
    # Self-cleaning sweep (2026-07-17): pending rows past expires_at auto-reject each desk
    # cycle, so the queue can never accumulate stale approvals again (health finding
    # 'queue not being cleaned' — 8 rows dating back to 06-26). The CHECK constraint has no
    # 'expired' status; system-rejected is the terminal state the desk already understands,
    # and the re-proposal path is unaffected (the desk re-queues fresh ids daily).
    cur.execute(
        """UPDATE options_approval_queue
           SET status='rejected', reviewer='system_expiry', reviewed_at=NOW(), updated_at=NOW(),
               review_note='auto-expired: passed 24h expires_at without operator review'
           WHERE status='pending' AND expires_at < NOW()""")
    for p in proposals:
        pid = p.get("id")
        if not pid:
            continue
        ent = p.get("enterprise") or {}
        thesis_blocks = list(p.get("thesis_blocks") or [])
        # 2026-09-26: an option needs the same thesis bar as a stock purchase.
        # resolve_approval refuses any row with blocks, so this fails closed.
        status = "blocked" if (p.get("enterprise_blocked") or thesis_blocks) else "pending"
        # A row marked blocked with an EMPTY blocks_json tells the operator
        # nothing — the Options desk rendered "Blocked (11)" with no reasons
        # attached (2026-07-20). If the enricher did not attach its block list,
        # recompute it here so the refusal is always explainable. Same principle
        # as everywhere else today: never show an absence where a reason exists.
        _blocks = ent.get("blocks") or []
        if status == "blocked" and not _blocks:
            try:
                _blocks = evaluate_hard_risk_blocks(p) or []
            except Exception as _be:
                _blocks = [{"code": "block_reason_unavailable",
                            "reason": f"blocked, but reasons could not be recomputed: "
                                      f"{type(_be).__name__}"}]
        _blocks = list(_blocks) + [b for b in thesis_blocks if b not in _blocks]
        cur.execute(
            """INSERT INTO options_approval_queue
               (proposal_id, symbol, strategy, desk_tier, edge_score, status,
                live_eligible, blocks_json, proposal_json, expires_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb, NOW() + INTERVAL '24 hours')
               ON CONFLICT (proposal_id) DO UPDATE SET
                 desk_tier=EXCLUDED.desk_tier,
                 edge_score=EXCLUDED.edge_score,
                 status=CASE WHEN options_approval_queue.status IN ('approved','rejected','executed')
                            THEN options_approval_queue.status ELSE EXCLUDED.status END,
                 live_eligible=EXCLUDED.live_eligible,
                 blocks_json=EXCLUDED.blocks_json,
                 proposal_json=EXCLUDED.proposal_json,
                 updated_at=NOW()""",
            (
                pid,
                p.get("symbol"),
                p.get("strategy"),
                p.get("desk_tier") or "C",
                _f(p.get("edge_score")),
                status,
                bool(ent.get("live_eligible")),
                json.dumps(_blocks),
                json.dumps(p, default=str),
            ),
        )
        upserted += 1
    if apply:
        conn.commit()
    return {"ok": True, "upserted": upserted}


def fetch_approval_queue(*, status: str = "", limit: int = 50) -> List[dict]:
    conn = _conn()
    if not conn:
        return []
    cur = conn.cursor()
    if status:
        cur.execute(
            """SELECT id, proposal_id, symbol, strategy, desk_tier, edge_score, status,
                      live_eligible, blocks_json, reviewer, review_note, created_at, updated_at
               FROM options_approval_queue
               WHERE status=%s ORDER BY edge_score DESC NULLS LAST, created_at DESC LIMIT %s""",
            (status, limit),
        )
    else:
        cur.execute(
            """SELECT id, proposal_id, symbol, strategy, desk_tier, edge_score, status,
                      live_eligible, blocks_json, reviewer, review_note, created_at, updated_at
               FROM options_approval_queue
               WHERE status IN ('pending','blocked') ORDER BY desk_tier, edge_score DESC LIMIT %s""",
            (limit,),
        )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def resolve_approval(
    proposal_id: str,
    action: str,
    *,
    reviewer: str = "operator",
    note: str = "",
) -> dict:
    """Approve or reject a queued options proposal."""
    action = (action or "").lower()
    if action not in ("approve", "reject"):
        return {"ok": False, "error": "action must be approve or reject"}
    new_status = "approved" if action == "approve" else "rejected"
    conn = _conn()
    if not conn:
        return {"ok": False, "error": "no_db"}
    cur = conn.cursor()
    cur.execute(
        """UPDATE options_approval_queue
           SET status=%s, reviewer=%s, review_note=%s, reviewed_at=NOW(), updated_at=NOW()
           WHERE proposal_id=%s AND status IN ('pending','blocked')
           RETURNING id, symbol, strategy, live_eligible, blocks_json, proposal_json""",
        (new_status, reviewer, note[:500], proposal_id),
    )
    row = cur.fetchone()
    if not row:
        conn.rollback()
        return {"ok": False, "error": "proposal not in queue or already resolved"}
    if action == "approve":
        blocks = row[4] or []
        # Refuse on ACTUAL blocks, not on live_eligible alone.
        #
        # This gate used to fire whenever live_eligible was False, and the
        # Defense CC card inserts every queued covered call with
        # live_eligible=false + blocks_json='[]'. The result was a row that
        # could never be approved — refused for "enterprise blocks remain" while
        # reporting an EMPTY block list — and therefore could never reach the
        # 2FA/submit step at all (operator hit this on CSCO, 2026-07-20).
        #
        # This does not weaken anything: the approval queue is a MANUAL REVIEW
        # queue and approving places no order. live_eligible is about LIVE
        # execution eligibility, which is re-evaluated downstream —
        # /api/v2/options/preflight re-runs evaluate_hard_risk_blocks in submit
        # mode and per-order 2FA still gates the actual order. The real safety
        # boundary is those gates, not this status flip.
        if blocks:
            conn.rollback()
            return {"ok": False,
                    "error": f"cannot approve — {len(blocks)} enterprise block(s) remain",
                    "blocks": blocks}
        # 2026-09-26 (operator): approve only on a fresh live Schwab validation.
        stale = _validation_refusal(cur, proposal_id)
        if stale:
            conn.rollback()
            return {"ok": False, "error": stale}
        # 2026-09-27 (order gates): pin WHAT was approved and WHEN. sync_approval_queue and
        # the CC card upsert keep status='approved' while overwriting proposal_json, so
        # without a pin a changed long leg (same proposal_id) would ride the old approval.
        # preflight_desk_gate recomputes the hash from the CURRENT proposal and refuses on
        # mismatch (legs_changed) or after approval_ttl_minutes (approval_expired).
        pj = row[5]
        if isinstance(pj, str):
            try:
                pj = json.loads(pj)
            except ValueError:
                pj = {}
        pin = approval_pin(pj if isinstance(pj, dict) else {})
        pin.update({"approved_at": _iso(), "reviewer": reviewer})
        cur.execute(
            """UPDATE options_approval_queue
               SET meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb
               WHERE proposal_id=%s""",
            (json.dumps({"approval": pin}, default=str), proposal_id),
        )
    conn.commit()
    _record_thesis_approval(cur, proposal_id, action, reviewer, note)
    return {"ok": True, "proposal_id": proposal_id, "status": new_status, "symbol": row[1], "strategy": row[2]}


def _validation_refusal(cur, proposal_id: str) -> Optional[str]:
    """Reason to refuse approval unless a fresh VALIDATED result exists, else None."""
    try:
        cur.execute("SELECT proposal_json->>'option_strategy_guid' FROM options_approval_queue WHERE proposal_id=%s",
                    (proposal_id,))
        r = cur.fetchone()
        guid = r[0] if r else None
        if not guid:
            return "no strategy GUID on this proposal; regenerate before approving"
        try:
            from scripts.lib.options_thesis import OptionsThesisStore
            from scripts.lib.options_validate import fresh_validation, settings
        except ImportError:
            from lib.options_thesis import OptionsThesisStore  # type: ignore
            from lib.options_validate import fresh_validation, settings  # type: ignore
        mins = float(settings(load_desk_config())["fresh_minutes"])
        if fresh_validation(OptionsThesisStore().history(guid), mins) is None:
            return f"validate against live Schwab data first (needs a VALIDATED result within {mins:g} min)"
        return None
    except Exception as e:  # fail closed: no approval without proof of a fresh quote
        return f"validation check unavailable ({type(e).__name__}); validate and retry"


def _record_thesis_approval(cur, proposal_id: str, action: str, reviewer: str, note: str) -> None:
    """CIO approval record on the options thesis (append-only). Best-effort, never blocks."""
    try:
        cur.execute("SELECT proposal_json->>'option_strategy_guid' FROM options_approval_queue WHERE proposal_id=%s",
                    (proposal_id,))
        r = cur.fetchone()
        guid = r[0] if r else None
        if not guid:
            return
        try:
            from scripts.lib.options_thesis import OptionsThesisStore
        except ImportError:
            from lib.options_thesis import OptionsThesisStore  # type: ignore
        OptionsThesisStore().record_approval(guid, proposal_id=proposal_id, action=action,
                                             reviewer=reviewer, note=note)
    except Exception:
        pass


def _fetch_queue_row(proposal_id: str) -> Optional[dict]:
    """The desk's own record of a proposal: queue status, eligibility, stored legs, approval pin.

    Returns None when the proposal is not in the queue. Raises RuntimeError when the queue
    cannot be read -- callers on the order path treat that as a refusal, never a pass.
    Tests replace this with an in-memory fake; nothing else in the gate touches the DB.
    """
    conn = _conn()
    if not conn:
        raise RuntimeError("approval queue unavailable")
    cur = conn.cursor()
    cur.execute(
        """SELECT status, live_eligible, blocks_json, proposal_json, reviewed_at, meta, expires_at
           FROM options_approval_queue WHERE proposal_id=%s""",
        (proposal_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    out = dict(zip(("status", "live_eligible", "blocks_json", "proposal_json", "reviewed_at", "meta", "expires_at"), row))
    for k in ("blocks_json", "proposal_json", "meta"):
        if isinstance(out.get(k), str):
            try:
                out[k] = json.loads(out[k])
            except ValueError:
                pass
    return out


def check_preflight_approval(proposal_id: str, *, row: Optional[dict] = None) -> Tuple[bool, str]:
    """Gate live submit on desk approval when required. Any status but 'approved' refuses."""
    cfg = load_desk_config()
    if not cfg.get("approval_required"):
        return True, ""
    if row is None:
        try:
            row = _fetch_queue_row(proposal_id)
        except Exception as e:
            return False, f"approval queue unavailable ({type(e).__name__})"
    if not row:
        return False, "proposal not in desk approval queue — operator review required"
    status, live_eligible, blocks = row.get("status"), row.get("live_eligible"), row.get("blocks_json") or []
    if status == "rejected":
        return False, "desk rejected this proposal"
    if status != "approved":
        return False, f"desk status={status} — approve in queue before submit"
    if not live_eligible:
        names = [b.get("code") if isinstance(b, dict) else str(b) for b in blocks[:3]]
        return False, f"not live-eligible: {', '.join(names) if names else 'enterprise block'}"
    return True, ""


# ---------------------------------------------------------------------------
# Order gates (operator work order 2026-09-27, PR 3). Desk layer only: nothing here
# imports brokers.*, builds an intent, or requests 2FA. Everything is decided from the
# proposal the desk holds, its approval-queue row and the options thesis store.
# ---------------------------------------------------------------------------

_LEG_FIELDS = ("symbol", "strategy", "account", "expiration", "short_strike", "long_strike", "contracts", "option_type")


def _canon_num(v: Any) -> Any:
    if v is None or v == "":
        return None
    try:
        f = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return str(v)
    return f"{f:.4f}"


def canonical_legs(proposal: dict) -> dict:
    """The legs an approval is a decision about, normalised so a re-serialised proposal hashes the same."""
    p = proposal or {}
    short_strike = p.get("short_strike")
    if short_strike is None:
        short_strike = p.get("strike")
    return {
        "symbol": str(p.get("symbol") or p.get("underlying") or "").upper(),
        "strategy": str(p.get("strategy") or ""),
        "account": str(p.get("account") or ""),
        "expiration": str(p.get("expiration") or "")[:10],
        "short_strike": _canon_num(short_strike),
        "long_strike": _canon_num(p.get("long_strike")),
        "contracts": _canon_num(p.get("contracts") or 1),
        "option_type": str(p.get("option_type") or "").lower(),
    }


def approval_pin(proposal: dict) -> dict:
    """What an approval binds to: the strategy GUID and a sha256 of the canonical legs."""
    legs = canonical_legs(proposal)
    digest = hashlib.sha256(json.dumps(legs, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "approved_strategy_guid": (proposal or {}).get("option_strategy_guid"),
        "approved_hash": digest,
        "legs": legs,
        "proposal_id": (proposal or {}).get("id"),
    }


def _parse_ts(v: Any) -> Optional[datetime]:
    """ISO string (Z ok), epoch seconds or epoch milliseconds -> aware UTC datetime; else None."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, (int, float)):
        try:
            secs = float(v) / (1000.0 if float(v) > 1e11 else 1.0)
            return datetime.fromtimestamp(secs, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        dt = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _age_seconds(ts: Any, now: datetime) -> Optional[float]:
    dt = _parse_ts(ts)
    if dt is None:
        return None
    return round(max(0.0, (now - dt).total_seconds()), 1)


def stamp_freshness(
    proposal: dict,
    *,
    now: Optional[datetime] = None,
    session: Optional[str] = None,
    chain_fetched_at: Optional[str] = None,
) -> dict:
    """Stamp the inputs evaluate_hard_risk_blocks fails closed on, from the timestamps the
    proposal carries. Run at generation (engine) and again at preflight from the STORED
    timestamps, so the ages are as of now, not as of the scan.

    * ``market_session``      from the caller (engine run / preflight clock)
    * ``chain_age_seconds``   from the chain's ``fetched_at`` (normalize_option_chain stamps it)
    * ``quote_age_seconds``   from the contract's ``quote_time`` (oldest leg on a spread)
    * ``buying_power``        deliberately NOT stamped: it needs a broker read, which the
                              desk does not hold a grant for, so the gate refuses with
                              buying_power_unknown by design until a granted layer supplies it.
    A timestamp the desk does not have leaves the key ABSENT (never 0), so the gate refuses.
    """
    now = now or _now()
    if session is not None:
        proposal["market_session"] = session
    if chain_fetched_at:
        proposal["chain_fetched_at"] = chain_fetched_at
    c_age = _age_seconds(proposal.get("chain_fetched_at"), now)
    if c_age is None:
        proposal.pop("chain_age_seconds", None)
    else:
        proposal["chain_age_seconds"] = c_age
    # Quote time: the contract's own stamp first; on a spread the OLDEST leg quote.
    candidates: List[Any] = []
    for leg in proposal.get("legs_liquidity") or []:
        if isinstance(leg, dict) and leg.get("quote_time"):
            candidates.append(leg["quote_time"])
    for leg in (proposal.get("spread_quote") or {}).get("legs") or []:
        if isinstance(leg, dict) and leg.get("quote_time"):
            candidates.append(leg["quote_time"])
    if not candidates:
        for k in ("quote_time", "quotes_as_of"):
            if proposal.get(k):
                candidates.append(proposal[k])
    ages = [a for a in (_age_seconds(c, now) for c in candidates) if a is not None]
    if ages:
        proposal["quote_age_seconds"] = max(ages)
    else:
        proposal.pop("quote_age_seconds", None)
    proposal["freshness_as_of"] = _iso(now)
    return proposal


def archive_approval_rows(proposals: List[dict], *, apply: bool = True) -> dict:
    """Queue rows for ARCHIVED (thesis-abandoned) ideas stop being approvable.

    The engine used to drop abandoned proposals BEFORE sync_approval_queue, so a row
    already 'approved' for an idea the desk had archived survived untouched and
    check_preflight_approval would still pass it. Rows are matched by proposal_id AND by
    strategy GUID (yesterday's date-scoped id for the same idea). The status CHECK has no
    'archived', so the row becomes 'blocked' with a THESIS_ABANDONED block; the archive is
    recorded in meta. Alpaca-lane and terminal rows are left alone.
    """
    conn = _conn()
    if not conn:
        return {"ok": False, "error": "no_db"}
    cur = conn.cursor()
    archived: List[str] = []
    for p in proposals:
        pid = p.get("id")
        guid = p.get("option_strategy_guid")
        if not pid and not guid:
            continue
        reason = str(p.get("thesis_abandoned") or "abandoned")
        block = {"code": "THESIS_ABANDONED", "severity": "hard", "source": "options_desk_enterprise",
                 "function": "archive_approval_rows",
                 "reason": f"thesis archived as abandoned: {reason}"}
        cur.execute(
            """UPDATE options_approval_queue
               SET status='blocked', live_eligible=FALSE,
                   blocks_json=%s::jsonb,
                   review_note=%s,
                   meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb,
                   updated_at=NOW()
               WHERE status IN ('pending','approved','blocked')
                 AND (proposal_id=%s OR (%s <> '' AND proposal_json->>'option_strategy_guid' = %s))
               RETURNING proposal_id""",
            (json.dumps([block]), f"archived: {reason}"[:500],
             json.dumps({"archived": {"at": _iso(), "reason": reason, "proposal_id": pid, "option_strategy_guid": guid}}),
             pid or "", guid or "", guid or ""),
        )
        archived += [r[0] for r in cur.fetchall()]
    if apply:
        conn.commit()
    return {"ok": True, "archived": sorted(set(archived))}


def _thesis_store():
    try:
        from scripts.lib.options_thesis import OptionsThesisStore
    except ImportError:
        from lib.options_thesis import OptionsThesisStore  # type: ignore
    return OptionsThesisStore()


def _refusal(code: str, reason: str, **detail: Any) -> dict:
    out = {"code": code, "reason": reason, "gate": "desk_preflight"}
    if detail:
        out["detail"] = detail
    return out


def preflight_desk_gate(
    proposal_id: str,
    proposal: dict,
    *,
    store=None,
    now: Optional[datetime] = None,
    row: Optional[dict] = None,
    cfg: Optional[dict] = None,
    holdings: Optional[tuple] = None,
) -> dict:
    """Every desk-side reason an options ORDER must not be created, in one place.

    Runs BEFORE any broker call (intent, authorize, 2FA) and reads only desk state: the
    approval-queue row, the options thesis store and the proposal the desk holds.
    Returns {"ok": bool, "refusals": [...]} -- all refusals, not the first, so the
    operator sees the whole distance to an order. Checks:
      1. queue row exists, status == 'approved', live_eligible
      2. approval not older than options_desk_settings.approval_ttl_minutes  (approval_expired)
      3. approval pin: strategy GUID and canonical-legs hash unchanged        (legs_changed)
      4. lifecycle not ARCHIVED_* / abandoned                                 (thesis_abandoned)
      5. thesis bar cleared and CIO decision APPROVE (lib.options_thesis.thesis_blocks)
      6. fresh VALIDATED event                            (lib.options_validate.fresh_validation)
      7. liquidity pass on the proposal and on EVERY leg
      8. evaluate_hard_risk_blocks(mode="submit") empty, with the freshness inputs
         recomputed from the stored timestamps as of ``now``
      9. protective put / covered call: shares and cost basis reconciled to the holdings
         snapshot of record (reconcile_hedge_holdings)
    """
    cfg = cfg or load_desk_config()
    now = now or _now()
    proposal = dict(proposal or {})
    refusals: List[dict] = []

    # 1. queue status
    if row is None:
        try:
            row = _fetch_queue_row(proposal_id)
        except Exception as e:
            refusals.append(_refusal("queue_unavailable", f"approval queue unavailable ({type(e).__name__})"))
            row = None
    if cfg.get("approval_required", True):
        if not row:
            refusals.append(_refusal("not_in_queue", "proposal not in desk approval queue — operator review required"))
        else:
            ok_ap, why = check_preflight_approval(proposal_id, row=row)
            if not ok_ap:
                refusals.append(_refusal("not_approved", why, status=row.get("status")))
    approval = ((row or {}).get("meta") or {}).get("approval") if isinstance((row or {}).get("meta"), dict) else None
    approval = approval if isinstance(approval, dict) else {}
    derived_pin = False
    if row and row.get("status") == "approved" and not approval.get("approved_hash"):
        # Operator 2026-09-27: a row approved before the pin existed is pinned to what it
        # STORED -- the proposal_json the reviewer looked at, and reviewed_at as approved_at.
        # No re-approval for its own sake; the TTL then says honestly whether it is still good.
        stored = row.get("proposal_json")
        if isinstance(stored, str):
            try:
                stored = json.loads(stored)
            except ValueError:
                stored = None
        if isinstance(stored, dict) and stored:
            approval = dict(approval_pin(stored), approved_at=approval.get("approved_at") or row.get("reviewed_at"),
                            reviewer=row.get("reviewer"), derived_from="proposal_json+reviewed_at")
            derived_pin = True

    if row and row.get("status") == "approved":
        # 2. expiry
        approved_at = _parse_ts(approval.get("approved_at"))
        ttl_min = float(cfg.get("approval_ttl_minutes") or 240)
        if approved_at is None:
            refusals.append(_refusal("approval_pin_missing",
                                     "approval carries no pin and no stored proposal/review time; re-approve"))
        elif (now - approved_at).total_seconds() > ttl_min * 60:
            refusals.append(_refusal("approval_expired",
                                     f"approved {_iso(approved_at)} is older than {ttl_min:g} min; re-approve",
                                     approved_at=_iso(approved_at), ttl_minutes=ttl_min))
        # 3. pin
        if approval.get("approved_hash"):
            cur_pin = approval_pin(proposal)
            if cur_pin["approved_hash"] != approval.get("approved_hash"):
                refusals.append(_refusal("legs_changed",
                                         "the legs differ from the ones that were approved; re-approve",
                                         approved=approval.get("legs"), current=cur_pin["legs"]))
            if (approval.get("approved_strategy_guid") or None) != (cur_pin["approved_strategy_guid"] or None):
                refusals.append(_refusal("strategy_guid_changed",
                                         "the strategy GUID differs from the approved one; re-approve",
                                         approved=approval.get("approved_strategy_guid"),
                                         current=cur_pin["approved_strategy_guid"]))

    # 4-6. lifecycle, thesis, validation -- all keyed by the strategy GUID
    guid = proposal.get("option_strategy_guid")
    if not guid:
        refusals.append(_refusal("strategy_guid_missing", "proposal has no option_strategy_guid; regenerate"))
    else:
        try:
            store = store or _thesis_store()
            try:
                from scripts.lib.options_thesis import thesis_blocks as _thesis_blocks
                from scripts.lib.options_validate import fresh_validation as _fresh, settings as _vsettings
            except ImportError:
                from lib.options_thesis import thesis_blocks as _thesis_blocks  # type: ignore
                from lib.options_validate import fresh_validation as _fresh, settings as _vsettings  # type: ignore
            life = store.lifecycle(guid) or {}
            stage = str(life.get("stage") or "")
            if life.get("abandoned") or stage.startswith("ARCHIVED"):
                refusals.append(_refusal("thesis_abandoned",
                                         f"options thesis is {stage or 'abandoned'}: "
                                         f"{(life.get('abandoned') or {}).get('reason') or 'archived'}",
                                         stage=stage))
            record = store.current(guid)
            codes_seen = set()
            if record is None:
                refusals.append(_refusal("thesis_missing", "no options thesis record on file for this strategy"))
            else:
                for b in _thesis_blocks(record):
                    codes_seen.add(b.get("code"))
                    refusals.append(_refusal(str(b.get("code") or "thesis_block"), str(b.get("reason") or "")))
            for b in proposal.get("thesis_blocks") or []:
                code = str((b or {}).get("code") if isinstance(b, dict) else b)
                if code not in codes_seen:
                    codes_seen.add(code)
                    refusals.append(_refusal(code, str((b or {}).get("reason") if isinstance(b, dict) else b)))
            outcome = ((life.get("decision") or {}).get("outcome"))
            if outcome != "APPROVE" and "awaiting_cio_decision" not in codes_seen:
                refusals.append(_refusal("cio_decision_not_approve",
                                         f"CIO decision on file: {outcome or 'none'}; an order needs APPROVE",
                                         outcome=outcome))
            mins = float(_vsettings(cfg)["fresh_minutes"])
            if _fresh(store.history(guid), mins, now=now) is None:
                refusals.append(_refusal("validation_stale",
                                         f"no VALIDATED result within {mins:g} min; validate against live Schwab data",
                                         fresh_minutes=mins))
        except Exception as e:  # fail closed: a gate that cannot read its inputs refuses
            refusals.append(_refusal("thesis_check_unavailable",
                                     f"thesis/lifecycle/validation check unavailable ({type(e).__name__})"))

    # 7. liquidity on the proposal and on every leg
    ent = proposal.get("enterprise") or {}
    liq = ent.get("liquidity") if isinstance(ent, dict) else None
    if not isinstance(liq, dict) or "pass" not in liq:
        refusals.append(_refusal("liquidity_unknown", "no liquidity verdict on this proposal"))
    else:
        if not liq.get("pass"):
            refusals.append(_refusal("liquidity_failed", "; ".join(str(i) for i in (liq.get("issues") or [])) or
                                     "liquidity gate failed"))
        for leg in liq.get("legs") or []:
            if isinstance(leg, dict) and not leg.get("pass", False):
                refusals.append(_refusal("liquidity_failed",
                                         f"{leg.get('role') or 'leg'} {leg.get('strike')}: "
                                         + ("; ".join(str(i) for i in (leg.get("issues") or [])) or "no liquidity verdict"),
                                         leg=leg.get("role"), strike=leg.get("strike")))
    for leg in proposal.get("legs_liquidity") or []:
        if isinstance(leg, dict) and leg.get("two_sided") is False:
            refusals.append(_refusal("leg_quote_not_two_sided",
                                     f"{leg.get('role') or 'leg'} {leg.get('strike')}: quote is not two-sided",
                                     leg=leg.get("role"), strike=leg.get("strike")))

    # 8. hard risk blocks in submit mode, freshness recomputed as of now
    try:
        try:
            from scripts.lib.canonical_observation import market_session as _ms
        except ImportError:
            from lib.canonical_observation import market_session as _ms  # type: ignore
        session_now: Optional[str] = _ms(now)
    except Exception:
        session_now = None
    proposal["market_session_at_generation"] = proposal.get("market_session")
    if session_now is not None:
        stamp_freshness(proposal, now=now, session=session_now)
    else:
        proposal.pop("market_session", None)  # unknown, not the stale generation label
        stamp_freshness(proposal, now=now)
    seen_codes = {r["code"] for r in refusals}
    seen = set()
    for b in evaluate_hard_risk_blocks(proposal, mode="submit", cfg=cfg):
        key = (b.get("code"), b.get("reason"))
        if b.get("code") in seen_codes or key in seen:
            continue
        seen.add(key)
        refusals.append(_refusal(str(b.get("code") or "hard_block"), str(b.get("reason") or ""),
                                 snapshot=b.get("snapshot") or None))

    # 9. hedge reconciliation (reviewer 2026-09-27, item 3): a protective put or covered call
    #    is presented as insurance on / income from HELD shares, so the shares and cost basis
    #    are reconciled to the holdings snapshot of record before an order exists.
    hedge = None
    if str(proposal.get("strategy") or "") in ("protective_put", "covered_call"):
        hedge = reconcile_hedge_holdings(proposal, now=now, cfg=cfg, holdings=holdings)
        for r in hedge.get("refusals") or []:
            refusals.append(r)

    return {
        "ok": not refusals,
        "gate": "desk_preflight",
        "proposal_id": proposal_id,
        "checked_at": _iso(now),
        "market_session": proposal.get("market_session"),
        "quote_age_seconds": proposal.get("quote_age_seconds"),
        "chain_age_seconds": proposal.get("chain_age_seconds"),
        "hedge_reconciliation": hedge,
        "approval_pin_derived": derived_pin,
        "refusals": refusals,
    }


def _fnone(v: Any) -> Optional[float]:
    """float or None -- unlike _f, absence is not zero (a card without shares_held is unknown)."""
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _load_holdings_snapshot() -> tuple[list, dict]:
    """The holdings of record the engine itself reads (persistent state first)."""
    try:
        import options_engine as _oe
    except ImportError:  # pragma: no cover
        from scripts import options_engine as _oe  # type: ignore
    rows, meta = _oe._load_holdings()
    return list(rows or []), dict(meta or {})


def reconcile_hedge_holdings(proposal: dict, *, now: Optional[datetime] = None, cfg: Optional[dict] = None,
                             holdings: Optional[tuple] = None) -> dict:
    """Shares and cost basis of the hedged position, from the holdings snapshot of record.

    Refuses (fail closed) when: no snapshot; the snapshot is older than
    ``options_desk_settings.holdings_max_age_hours`` (default 36 -- a Friday close still
    covers a Sunday review); the symbol is not held in the proposal's account; fewer shares
    are held than the contracts insure/cover; or no cost basis is on file. Reports the
    hedged position against BASIS as well as against the mark, because the card's floor and
    max-loss figures are from the mark and the operator's P/L is from basis.
    """
    cfg = cfg or load_desk_config()
    now = now or _now()
    sym = str(proposal.get("symbol") or "").upper()
    acct = str(proposal.get("account") or "")
    contracts = int(_fnone(proposal.get("contracts")) or 1)
    covered = contracts * 100
    refusals: List[dict] = []
    out: dict = {"symbol": sym, "account": acct, "shares_required": covered}
    try:
        rows, meta = holdings if holdings is not None else _load_holdings_snapshot()
    except Exception as e:  # noqa: BLE001
        return {**out, "refusals": [_refusal("holdings_unavailable", f"holdings snapshot unreadable ({type(e).__name__})")]}
    if not rows:
        return {**out, "refusals": [_refusal("holdings_unavailable", "no holdings snapshot of record")]}
    max_age_h = float(cfg.get("holdings_max_age_hours") or 36)
    as_of = _parse_ts(meta.get("data_as_of") or meta.get("generated_at") or meta.get("as_of"))
    out["snapshot_as_of"] = _iso(as_of) if as_of else None
    if as_of is None:
        refusals.append(_refusal("holdings_age_unknown", "holdings snapshot carries no timestamp"))
    elif (now - as_of).total_seconds() > max_age_h * 3600:
        refusals.append(_refusal("holdings_stale",
                                 f"holdings snapshot {_iso(as_of)} is older than {max_age_h:g} h; refresh before an order",
                                 max_age_hours=max_age_h))
    matches = [r for r in rows if str(r.get("symbol") or "").upper() == sym and not r.get("is_cash")
               and (not acct or str(r.get("account") or r.get("account_key") or "") == acct)]
    if not matches:
        refusals.append(_refusal("shares_not_held",
                                 f"{sym} is not held in {acct or 'the proposal account'} per the holdings snapshot"))
        return {**out, "refusals": refusals}
    held = round(sum(float(_fnone(r.get("shares") or r.get("quantity")) or 0.0) for r in matches), 4)
    basis_total = sum(float(_fnone(r.get("cost_basis")) or 0.0) for r in matches)
    basis_ps = round(basis_total / held, 4) if held and basis_total else None
    out.update({"shares_held": held, "shares_on_card": _fnone(proposal.get("shares_held")),
                "cost_basis_total": round(basis_total, 2) if basis_total else None, "cost_basis_per_share": basis_ps})
    if held + 1e-6 < covered:
        refusals.append(_refusal("insufficient_shares",
                                 f"{contracts} contract(s) insure/cover {covered} shares but {held:g} are held",
                                 shares_held=held, shares_required=covered))
    card_shares = _fnone(proposal.get("shares_held"))
    if card_shares is not None and abs(card_shares - held) > 0.01:
        refusals.append(_refusal("shares_changed",
                                 f"card was built on {card_shares:g} shares; {held:g} are held now — regenerate",
                                 shares_on_card=card_shares, shares_held=held))
    if basis_ps is None:
        refusals.append(_refusal("cost_basis_missing", f"no cost basis on file for {sym} in {acct or 'the account'}"))
    else:
        k, prem, spot = _fnone(proposal.get("strike")), _fnone(proposal.get("premium")), _fnone(proposal.get("underlying_price"))
        if k and prem is not None:
            insured = min(held, covered)
            if str(proposal.get("strategy") or "") == "protective_put":
                out["floor_per_share_after_premium"] = round(k - prem, 2)
                out["pl_vs_basis_at_floor"] = round((k - prem - basis_ps) * insured, 2)
            else:
                out["called_away_per_share_incl_premium"] = round(k + prem, 2)
                out["pl_vs_basis_if_called"] = round((k + prem - basis_ps) * insured, 2)
            if spot:
                out["pl_vs_basis_at_mark"] = round((spot - basis_ps) * held, 2)
    out["refusals"] = refusals
    return {**out, "ok": not refusals}


def persist_chain_snapshot(symbol: str, chain: dict, vol: dict) -> None:
    """Light vol surface persistence for desk analytics."""
    conn = _conn()
    if not conn or not vol.get("ok"):
        return
    sym = symbol.upper()
    # fetch_vol_history reads only vol_analytics_json. Persisting the full chain blob
    # both bloated the table and risked invalid JSON (a byte-slice of serialized JSON
    # is malformed → ::jsonb cast threw → snapshot silently lost). Store a small,
    # always-valid summary instead.
    chain_meta = {
        "underlying_price": _f(chain.get("underlying_price")),
        "expiration_count": len(chain.get("expirations") or []),
        "note": "summary only — full chain not persisted (size/retention)",
    }
    keep_days = int(os.getenv("OPTIONS_SNAPSHOT_RETENTION_DAYS", "45"))
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO options_chain_snapshots (symbol, chain_json, vol_analytics_json, captured_at)
               VALUES (%s, %s::jsonb, %s::jsonb, NOW())""",
            (sym, json.dumps(chain_meta), json.dumps(vol, default=str)),
        )
        # Bounded retention — uses idx_options_chain_snap_sym_time; cheap per-symbol prune.
        cur.execute(
            "DELETE FROM options_chain_snapshots WHERE symbol=%s AND captured_at < NOW() - (%s || ' days')::interval",
            (sym, str(keep_days)),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def prune_chain_snapshots(keep_days: Optional[int] = None) -> dict:
    """Global retention sweep across all symbols. Run from a daily cron so symbols
    that stop receiving new snapshots still get their tail pruned (the per-insert
    prune in persist_chain_snapshot only touches the symbol being written)."""
    days = int(keep_days if keep_days is not None else os.getenv("OPTIONS_SNAPSHOT_RETENTION_DAYS", "45"))
    conn = _conn()
    if not conn:
        return {"ok": False, "error": "no_db"}
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM options_chain_snapshots WHERE captured_at < NOW() - (%s || ' days')::interval",
            (str(days),),
        )
        deleted = cur.rowcount
        conn.commit()
        return {"ok": True, "deleted": deleted, "keep_days": days}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "error": str(e)[:160]}


def build_enterprise_summary(
    proposals: List[dict],
    holdings: List[dict],
    positions: List[dict],
) -> dict:
    risk = portfolio_risk_preflight(proposals, holdings, positions)
    tiers = {"A": 0, "B": 0, "C": 0}
    for p in proposals:
        tiers[p.get("desk_tier") or "C"] = tiers.get(p.get("desk_tier") or "C", 0) + 1
    summary = {
        "generated_at": _iso(),
        "desk_level": "enterprise",
        "tier_counts": tiers,
        "risk": risk,
        "config": {k: load_desk_config()[k] for k in (
            "earnings_blackout_days", "min_open_interest", "min_volume",
            "max_bid_ask_spread_pct", "approval_required", "max_net_delta_pct",
        )},
    }
    _save_json(DESK_RUNTIME, summary)
    return summary