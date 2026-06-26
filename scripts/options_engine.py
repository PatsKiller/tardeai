#!/usr/bin/env python3
"""options_engine.py — Options proposal generation + open-position monitoring.

Turnkey advisory module: high-quality proposals only (edge/POP/IV gates). Integrates:
  • Portfolio holdings (covered calls on owned stock)
  • Schwab read-only option chain (live premium + greeks)
  • Layer 4 / Aegis / catalyst context
  • Schwab live positions (option legs when linked)

State cache: data/portfolios/state/options_monitor.json (refreshed every 5–15m market hours).
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
MONITOR_CACHE = STATE_DIR / "options_monitor.json"
PROPOSALS_CACHE = STATE_DIR / "options_proposals.json"
AUDIT_JSONL = PROJECT_ROOT / "logs" / "options_engine.jsonl"

# Quality gates — proposals below these are dropped (turnkey = no noise)
MIN_EDGE_SCORE = 62
MIN_EDGE_CC_INTENT = 52  # portfolio_intent covered_call_candidate — income sleeve
MIN_POP_PCT = 52
MIN_IV_RANK = 20
MAX_DTE = 60
MIN_DTE = 7
MIN_HOLDING_SHARES_CC = 100
MIN_POSITION_MV = 1000
MIN_PROTECTIVE_MV = 15000
MIN_CSP_CASH = 5000
MIN_IV_CONVICTION = int(os.getenv("OPTIONS_CONVICTION_MIN_IV", "12"))
MIN_EDGE_CONVICTION = int(os.getenv("OPTIONS_CONVICTION_MIN_EDGE", "52"))
WHEEL_STRATEGIES = frozenset({"cash_secured_put", "credit_spread"})

# Per-strategy desk slots — prevents covered calls from crowding out puts/spreads.
STRATEGY_SLOTS = {
    "covered_call": int(os.getenv("OPTIONS_SLOT_COVERED_CALL", "5")),
    "cash_secured_put": int(os.getenv("OPTIONS_SLOT_CSP", "3")),
    "protective_put": int(os.getenv("OPTIONS_SLOT_PROTECTIVE_PUT", "2")),
    "long_call": int(os.getenv("OPTIONS_SLOT_LONG_CALL", "2")),
    "credit_spread": int(os.getenv("OPTIONS_SLOT_CREDIT_SPREAD", "2")),
}

DEBIT_STRATEGIES = frozenset({"protective_put", "long_call"})

OCC_RE = re.compile(
    r"^([A-Z]{1,6})\s*(\d{6})([CP])(\d{8})$"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


_EXEC_NOTE_CACHE: Optional[str] = None


def _execution_note(extra: str = "") -> str:
    """Reflect live options execution arm state in proposal copy."""
    global _EXEC_NOTE_CACHE
    if _EXEC_NOTE_CACHE is None:
        try:
            from options_pilot_arm import status as _opt_status
            armed = bool((_opt_status() or {}).get("armed_for_execution"))
        except Exception:
            armed = False
        if armed:
            _EXEC_NOTE_CACHE = (
                "Live Schwab options path ARMED — use preflight + per-order 2FA before submit."
            )
        else:
            _EXEC_NOTE_CACHE = (
                "Advisory only — run options_pilot_arm --approve to enable live Schwab submit."
            )
    return f"{_EXEC_NOTE_CACHE} {extra}".strip() if extra else _EXEC_NOTE_CACHE


def _f(v, default=0.0) -> float:
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return default


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


def _audit(event: str, **fields) -> None:
    """Append-only decision audit (proposal generation, fallback, monitor)."""
    try:
        AUDIT_JSONL.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": _iso(), "event": event, **fields}
        with AUDIT_JSONL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except Exception:
        pass


def _norm_cdf(x: float) -> float:
    """Standard normal CDF (Abramowitz & Stegun)."""
    k = 1.0 / (1.0 + 0.2316419 * abs(x))
    poly = k * (
        0.319381530
        + k * (-0.356563782 + k * (1.781477937 + k * (-1.821255978 + k * 1.330274429)))
    )
    n = math.exp(-x * x / 2.0) / math.sqrt(2 * math.pi)
    cdf = 1.0 - n * poly if x >= 0 else n * poly
    return max(0.0, min(1.0, cdf))


def _pop_otm_call(spot: float, strike: float, iv: float, dte: int) -> float:
    """P(finish OTM) for short call ≈ N(-d2) for seller."""
    if spot <= 0 or strike <= 0 or iv <= 0 or dte <= 0:
        return 50.0
    t = dte / 365.0
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * t) / (iv * math.sqrt(t))
    d2 = d1 - iv * math.sqrt(t)
    return round(100.0 * _norm_cdf(-d2), 1)


def _pop_otm_put(spot: float, strike: float, iv: float, dte: int) -> float:
    """P(finish OTM) for short put ≈ N(d2)."""
    if spot <= 0 or strike <= 0 or iv <= 0 or dte <= 0:
        return 50.0
    t = dte / 365.0
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * t) / (iv * math.sqrt(t))
    d2 = d1 - iv * math.sqrt(t)
    return round(100.0 * _norm_cdf(d2), 1)


def _iv_rank_from_history(sym: str, current_iv_pct: float) -> Optional[float]:
    """True IV rank from options_iv_history (52-week window)."""
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB or current_iv_pct <= 0:
            return None
        rows = _execute(
            """SELECT iv_pct FROM options_iv_history
               WHERE symbol=%s AND captured_at > NOW() - INTERVAL '365 days'
               ORDER BY captured_at ASC""",
            (sym.upper(),),
            fetch="all",
        ) or []
        vals = [_f(r.get("iv_pct")) for r in rows if _f(r.get("iv_pct")) > 0]
        if len(vals) < 5:
            return None
        lo, hi = min(vals), max(vals)
        if hi <= lo:
            return 50.0
        return round(100.0 * (current_iv_pct - lo) / (hi - lo), 1)
    except Exception:
        return None


def _iv_rank_proxy(sym: str, tech: dict, chain_iv: Optional[float] = None) -> float:
    """IV rank: prefer DB history; fallback to chain + Finviz proxy."""
    iv_pct = _f(tech.get("iv") or tech.get("volatility"))
    if chain_iv and chain_iv > 0:
        iv_pct = max(iv_pct, chain_iv * 100 if chain_iv < 3 else chain_iv)
    hi = _f(tech.get("high52") or tech.get("week52_high"))
    lo = _f(tech.get("low52") or tech.get("week52_low"))
    px = _f(tech.get("price") or tech.get("last"))
    range_pos = 50.0
    if hi > lo and px > 0:
        range_pos = 100.0 * (px - lo) / (hi - lo)
    vol_w = _f(tech.get("volatility_w") or tech.get("vol_week"))
    vol_m = _f(tech.get("volatility_m") or tech.get("vol_month"))
    vol_boost = min(30.0, (vol_w + vol_m) / 4.0)
    hist = _iv_rank_from_history(sym, iv_pct)
    if hist is not None:
        return max(0.0, min(100.0, hist))
    rank = min(95.0, max(5.0, iv_pct * 0.55 + range_pos * 0.25 + vol_boost))
    return round(rank, 1)


def _parse_occ(symbol: str) -> Optional[dict]:
    s = (symbol or "").upper().replace(" ", "")
    m = OCC_RE.match(s)
    if not m:
        return None
    root, yymmdd, cp, strike_raw = m.groups()
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    year = 2000 + yy
    exp = datetime(year, mm, dd, tzinfo=timezone.utc)
    strike = int(strike_raw) / 1000.0
    return {
        "underlying": root,
        "expiration": exp.date().isoformat(),
        "dte": max(0, (exp.date() - _now().date()).days),
        "option_type": "call" if cp == "C" else "put",
        "strike": strike,
        "occ": s,
    }


def _execution_profile(account: str) -> dict:
    """Map account → broker + auto vs manual execution path."""
    a = (account or "").lower()
    if "fidelity" in a:
        return {
            "broker": "fidelity",
            "execution_mode": "manual",
            "execution_label": "Manual · Fidelity",
            "auto_eligible": False,
        }
    if "schwab" in a:
        return {
            "broker": "schwab",
            "execution_mode": "auto_or_manual",
            "execution_label": "Schwab · auto or manual",
            "auto_eligible": True,
        }
    if "alpaca" in a:
        return {
            "broker": "alpaca",
            "execution_mode": "auto",
            "execution_label": "Auto · Alpaca paper",
            "auto_eligible": True,
        }
    return {
        "broker": "other",
        "execution_mode": "manual",
        "execution_label": "Manual",
        "auto_eligible": False,
    }


def _stamp_execution(p: dict, account: str = "") -> dict:
    """Attach broker + execution_mode labels to a proposal row."""
    acct = account or p.get("account") or ""
    prof = _execution_profile(acct)
    p["account"] = acct or p.get("account")
    p["broker"] = prof["broker"]
    p["execution_mode"] = prof["execution_mode"]
    p["execution_label"] = prof["execution_label"]
    p["auto_eligible"] = prof["auto_eligible"]
    return p


def _holding_quality_gates(h: dict) -> dict:
    """Account-aware quality gates — Fidelity/manual sleeves use relaxed IV/edge floors."""
    prof = _execution_profile(h.get("account") or "")
    manual = prof.get("broker") == "fidelity" or prof.get("execution_mode") == "manual"
    return {
        "min_iv": 12 if manual else MIN_IV_RANK,
        "min_edge": MIN_EDGE_CC_INTENT if manual else MIN_EDGE_SCORE,
        "edge_boost": 22.0 if manual else 0.0,
        "manual": manual,
        "broker": prof.get("broker"),
    }


def _bs_option_premium(
    spot: float,
    strike: float,
    *,
    side: str,
    iv: float,
    dte: int,
    rate: float = 0.05,
) -> float:
    """Black-Scholes premium for call or put."""
    if spot <= 0 or strike <= 0 or iv <= 0 or dte <= 0:
        return 0.0
    t = dte / 365.0
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * t) / (iv * math.sqrt(t))
    d2 = d1 - iv * math.sqrt(t)
    disc = math.exp(-rate * t)
    if side == "put":
        prem = strike * disc * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
    else:
        prem = spot * _norm_cdf(d1) - strike * disc * _norm_cdf(d2)
    return max(0.01, round(prem, 2))


def _resolve_iv_decimal(price: float, tech: dict, side: str) -> float:
    iv_pct = _f(tech.get("iv"))
    if iv_pct > 0:
        return iv_pct / 100.0
    atr = _f(tech.get("atr")) or price * (0.02 if side == "call" else 0.015)
    daily_vol = atr / max(price, 1.0)
    return max(0.12, min(0.85, daily_vol * math.sqrt(252)))


def _estimate_option_contract(
    sym: str,
    price: float,
    tech: dict,
    side: str,
    target_strike: float,
    target_dte: int,
) -> Optional[dict]:
    """Black-Scholes fallback when Schwab chain is thin or unavailable."""
    if price <= 0 or target_strike <= 0:
        return None
    iv = _resolve_iv_decimal(price, tech, side)
    est = _bs_option_premium(price, target_strike, side=side, iv=iv, dte=target_dte)
    if est <= 0:
        return None
    return {
        "exp": (_now().date() + timedelta(days=target_dte)).isoformat(),
        "dte": target_dte,
        "strike": target_strike,
        "bid": round(est * 0.95, 2),
        "ask": round(est * 1.05, 2),
        "mid": round(est, 2),
        "iv": iv,
        "delta": None,
        "oi": None,
        "volume": 0,
        "data_source": "bs_estimate",
    }


def _resolve_option_contract(
    sym: str,
    price: float,
    tech: dict,
    side: str,
    target_strike: float,
    target_dte: int,
    strikes: int = 10,
) -> Tuple[Optional[dict], str]:
    """Pick live chain contract or BS estimate."""
    chain = _schwab_chain(sym, strikes=strikes)
    und = _f(chain.get("underlying_price")) or price
    contract = _pick_chain_contract(chain, side, target_strike, target_dte)
    if contract:
        contract["data_source"] = "schwab_chain"
        return contract, "schwab_chain"
    est = _estimate_option_contract(sym, und, tech, side, target_strike, target_dte)
    if est:
        return est, "bs_estimate"
    return None, ""


def _normalize_holding(h: dict) -> dict:
    """Unify Schwab + Fidelity/SnapTrade holding shapes for the options engine."""
    out = dict(h)
    price = _f(h.get("price")) or _f(h.get("current_price"))
    out["price"] = price
    acct = h.get("account") or h.get("account_id") or ""
    out["account"] = acct
    out["account_display"] = h.get("account_display") or acct.replace("_", " ").title()
    out.update(_execution_profile(acct))
    if h.get("is_cash") or (out.get("symbol") or "").upper() in ("CASH", "SPAXX", "FCASH", "CORE"):
        out["is_cash"] = True
    return out


def _load_holdings() -> Tuple[List[dict], dict]:
    h = _load_json(STATE_DIR / "holdings.json") or {}
    raw = h.get("holdings") or []
    normalized = [_normalize_holding(x) for x in raw if (x.get("symbol") or "").upper()]
    return normalized, h


def _cash_by_account(holdings: List[dict]) -> Dict[str, float]:
    """Available cash per account (SPAXX/CASH rows + is_cash flags)."""
    cash: Dict[str, float] = {}
    for h in holdings:
        if not h.get("is_cash"):
            continue
        acct = h.get("account") or ""
        cash[acct] = cash.get(acct, 0.0) + _f(h.get("market_value") or h.get("shares") * h.get("price"))
    return cash


def _load_technicals() -> dict:
    return _load_json(STATE_DIR / "technical_snapshot.json") or {}


def _load_intent_cfg() -> dict:
    try:
        import yaml
        p = PROJECT_ROOT / "assets" / "portfolio_intent.yaml"
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _high_conviction_symbols(limit: int = 25) -> List[dict]:
    """Layer 4 + fused signals + Aegis CC candidates."""
    out: Dict[str, dict] = {}
    try:
        from db_adapter import _execute, USE_DB
        if USE_DB:
            rows = _execute(
                """SELECT subject, inference_type, severity, confidence, body, title, created_at
                   FROM inference_results
                   WHERE run_id = (SELECT run_id FROM inference_runs ORDER BY created_at DESC LIMIT 1)
                     AND inference_type IN ('opportunity','risk','sizing','regional_impact','nav_signal')
                     AND confidence >= 0.55
                   ORDER BY confidence DESC LIMIT 40""",
                fetch="all",
            ) or []
            for r in rows:
                sym = (r.get("subject") or "").upper()
                if sym and len(sym) <= 6 and sym.isalpha() and sym not in ("OTHER", "UNKNOWN"):
                    out[sym] = {
                        "symbol": sym,
                        "source": "layer4",
                        "confidence": _f(r.get("confidence")),
                        "severity": r.get("severity"),
                        "summary": (r.get("body") or r.get("title") or "")[:200],
                    }
            fused = _execute(
                """SELECT symbol, fused_score, confidence, severity, direction FROM fused_signals
                   WHERE created_at > NOW() - INTERVAL '7 days'
                   ORDER BY fused_score DESC NULLS LAST LIMIT 30""",
                fetch="all",
            ) or []
            for r in fused:
                sym = (r.get("symbol") or "").upper()
                if sym and sym not in out and sym not in ("OTHER", "UNKNOWN") and sym.isalpha():
                    out[sym] = {
                        "symbol": sym,
                        "source": "fused_signal",
                        "confidence": _f(r.get("confidence") or r.get("fused_score"), 0.5),
                        "severity": r.get("severity"),
                        "direction": r.get("direction"),
                        "summary": f"{r.get('direction') or ''} {r.get('severity') or ''}".strip()[:200],
                    }
    except Exception:
        pass
    if len(out) < 5:
        wl = _load_json(STATE_DIR / "action_signals.json") or {}
        for s in (wl.get("signals") or [])[:20]:
            sym = (s.get("symbol") or "").upper()
            if sym and sym not in out and len(sym) <= 6:
                out[sym] = {
                    "symbol": sym,
                    "source": "action_signal",
                    "confidence": 0.58,
                    "summary": (s.get("signal") or s.get("action") or "")[:120],
                }
        ta = _load_json(STATE_DIR / "trade_ai_latest.json") or _load_json(PROJECT_ROOT / "data" / "trade_ai_latest.json") or {}
        for t in (ta.get("tickers") or ta.get("results") or [])[:15]:
            sym = (t.get("symbol") or t.get("ticker") or "").upper()
            if sym and sym not in out and (t.get("decision") == "GO" or _f(t.get("score")) >= 70):
                out[sym] = {
                    "symbol": sym,
                    "source": "trade_ai",
                    "confidence": min(0.85, _f(t.get("score"), 70) / 100.0),
                    "summary": f"Trade AI {t.get('decision') or 'GO'} score {_f(t.get('score')):.0f}",
                }
    return list(out.values())[:limit]


def _aegis_cc_map() -> Dict[str, dict]:
    m: Dict[str, dict] = {}
    try:
        from db_adapter import _execute, USE_DB
        if USE_DB:
            rows = _execute(
                """SELECT symbol, verdict, reasoning, strike_guidance, confidence
                   FROM aegis_covered_call_candidates
                   WHERE run_id = (SELECT run_id FROM aegis_covered_call_candidates ORDER BY observed_at DESC LIMIT 1)""",
                fetch="all",
            ) or []
            for r in rows:
                sym = (r.get("symbol") or "").upper()
                if sym:
                    m[sym] = r
    except Exception:
        pass
    return m


def _schwab_chain(symbol: str, strikes: int = 12) -> dict:
    try:
        import schwab_transport
        return schwab_transport.get_option_chain(symbol.upper(), strike_count=strikes) or {}
    except Exception as e:
        return {"status": "error", "error": str(e)[:120]}


def _pick_chain_contract(chain: dict, side: str, target_strike: float, target_dte: int) -> Optional[dict]:
    if chain.get("status") not in (None, "ok") and "expirations" not in chain:
        return None
    best = None
    best_score = 1e9
    for exp in chain.get("expirations") or []:
        dte = int(exp.get("dte") or 0)
        if dte < MIN_DTE or dte > MAX_DTE:
            continue
        for row in exp.get("strikes") or []:
            if row.get("side") != side:
                continue
            strike = _f(row.get("strike"))
            bid, ask = _f(row.get("bid")), _f(row.get("ask"))
            mid = (bid + ask) / 2.0 if bid and ask else _f(row.get("last"))
            if mid <= 0:
                continue
            score = abs(strike - target_strike) + abs(dte - target_dte) * 0.15
            if score < best_score:
                best_score = score
                best = {
                    "exp": exp.get("exp"),
                    "dte": dte,
                    "strike": strike,
                    "bid": bid,
                    "ask": ask,
                    "mid": round(mid, 2),
                    "iv": _f(row.get("iv")) / 100.0 if _f(row.get("iv")) > 3 else _f(row.get("iv")),
                    "delta": _f(row.get("delta")),
                    "oi": int(_f(row.get("oi"))),
                    "volume": int(_f(row.get("volume"))),
                }
    return best


def _edge_score(
    pop: float,
    iv_rank: float,
    rr: float,
    catalyst_boost: float = 0.0,
    conviction: float = 0.0,
) -> float:
    """0–100 composite edge for credit/income strategies."""
    pop_s = min(100.0, max(0.0, pop)) * 0.35
    iv_s = min(100.0, iv_rank) * 0.20
    rr_s = min(100.0, rr * 25.0) * 0.20
    cat_s = min(15.0, catalyst_boost)
    conv_s = min(10.0, conviction * 10.0)
    return round(pop_s + iv_s + rr_s + cat_s + conv_s, 1)


def _conviction_bias(c: dict) -> str:
    """Return bullish | bearish | neutral for defined-risk routing."""
    direction = (c.get("direction") or "").lower()
    if direction in ("bullish", "long", "buy", "up"):
        return "bullish"
    if direction in ("bearish", "short", "sell", "down"):
        return "bearish"
    sev = (c.get("severity") or "").lower()
    inf = (c.get("inference_type") or "").lower()
    if sev in ("opportunity", "positive", "bullish") or inf == "opportunity":
        return "bullish"
    if sev in ("risk", "negative", "bearish", "critical", "high") or inf == "risk":
        return "bearish"
    return "neutral"


def _edge_score_wheel(
    pop: float,
    iv_rank: float,
    premium: float,
    capital_at_risk: float,
    *,
    conviction: float = 0.0,
    dte: int = 30,
) -> float:
    """Edge model for wheel / credit-income strategies (CSP, credit spreads)."""
    pop_s = min(100.0, max(0.0, pop)) * 0.38
    iv_s = min(100.0, iv_rank) * 0.14
    base = max(capital_at_risk, premium, 0.01)
    ann = (premium / base) * (365.0 / max(dte, 7)) * 100.0
    roc_s = min(28.0, ann * 4.5)
    conv_s = min(14.0, conviction * 14.0)
    dte_s = 6.0 if 21 <= dte <= 45 else (3.0 if 14 <= dte <= 60 else 0.0)
    return round(pop_s + iv_s + roc_s + conv_s + dte_s, 1)


def _edge_score_debit(
    *,
    pop: float,
    iv_rank: float,
    hedge_ratio: float = 1.0,
    conviction: float = 0.0,
    dte: int = 30,
) -> float:
    """Separate edge model for debit strategies (long calls, protective puts).

    Rewards cheap vol (moderate IV rank), favorable probability, position hedge value,
    and conviction — without penalizing negative premium EV like the credit model.
    """
    pop_s = min(100.0, max(0.0, pop)) * 0.30
    iv_s = min(100.0, max(0.0, 100.0 - abs(iv_rank - 45.0))) * 0.18
    hedge_s = min(25.0, max(0.0, hedge_ratio) * 8.0)
    conv_s = min(12.0, conviction * 12.0)
    dte_s = 8.0 if 21 <= dte <= 60 else (4.0 if 14 <= dte <= 75 else 0.0)
    return round(pop_s + iv_s + hedge_s + conv_s + dte_s, 1)


def _resolve_symbol_price(sym: str, tech_map: dict, holdings: List[dict]) -> float:
    """Resolve live price for conviction / watchlist symbols missing from technical_snapshot."""
    sym = (sym or "").upper()
    tech = tech_map.get(sym) or {}
    px = _f(tech.get("price") or tech.get("last"))
    if px > 0:
        return px
    for h in holdings:
        if (h.get("symbol") or "").upper() == sym:
            hp = _f(h.get("price"))
            if hp > 0:
                return hp
    try:
        from db_adapter import _execute, USE_DB
        if USE_DB:
            row = _execute(
                """SELECT price FROM trade_ai_scans
                   WHERE symbol=%s AND price IS NOT NULL AND price > 0
                   ORDER BY scanned_at DESC LIMIT 1""",
                (sym,),
                fetch="one",
            )
            if row and _f(row.get("price")) > 0:
                return _f(row["price"])
    except Exception:
        pass
    try:
        from market_quote_provider import check_fresh_quote
        fq = check_fresh_quote(sym)
        if fq.get("ok") and _f(fq.get("last_price")) > 0:
            return _f(fq["last_price"])
    except Exception:
        pass
    return 0.0


def _enrich_tech_map(symbols: List[str], tech_map: dict, holdings: List[dict]) -> dict:
    """Copy tech_map and backfill missing prices for conviction / desk symbols."""
    out = dict(tech_map)
    for sym in symbols:
        s = (sym or "").upper()
        if not s or len(s) > 6 or not s.isalpha():
            continue
        base = dict(out.get(s) or {})
        px = _resolve_symbol_price(s, out, holdings)
        if px > 0:
            base["price"] = px
            base["last"] = px
            out[s] = base
    return out


def _allocate_strategy_slots(proposals: List[dict]) -> List[dict]:
    """Reserve slots per strategy so puts/spreads are not buried by covered-call edge."""
    by_strat: Dict[str, List[dict]] = {}
    for p in proposals:
        strat = p.get("strategy") or "other"
        by_strat.setdefault(strat, []).append(p)
    for strat in by_strat:
        by_strat[strat].sort(key=lambda x: -_f(x.get("edge_score")))
    picked: List[dict] = []
    seen = set()
    for strat, cap in STRATEGY_SLOTS.items():
        for p in by_strat.get(strat, [])[:cap]:
            key = (p.get("strategy"), p.get("symbol"), p.get("strike"), p.get("account"))
            if key in seen:
                continue
            seen.add(key)
            picked.append(p)
    remainder = []
    for strat, rows in by_strat.items():
        if strat in STRATEGY_SLOTS:
            continue
        remainder.extend(rows)
    remainder.sort(key=lambda x: -_f(x.get("edge_score")))
    for p in remainder:
        key = (p.get("strategy"), p.get("symbol"), p.get("strike"), p.get("account"))
        if key in seen:
            continue
        seen.add(key)
        picked.append(p)
    picked.sort(key=lambda x: (-_f(x.get("edge_score")), x.get("strategy") or ""))
    return picked


def _proposal_id(strategy: str, sym: str, account: str, strike: Any, expiration: str = "") -> str:
    """Stable id so Grok/ChatGPT ensemble verdicts persist across proposal rescans."""
    acct = re.sub(r"[^a-z0-9]+", "_", (account or "default").lower()).strip("_")[:22]
    exp = (expiration or "")[:10].replace("-", "")
    try:
        st = f"{float(strike):.4f}".replace(".", "p")
    except (TypeError, ValueError):
        st = str(strike or "0").replace(".", "p")
    base = f"opt_{strategy}_{sym.upper()}_{acct}_{st}_{exp}"
    return base[:72]


def _proposal_ensemble_content(p: dict) -> str:
    """Payload for free-lane ensemble (Grok OAuth + ChatGPT OAuth + local gemma)."""
    lines = [
        f"OPTIONS PROPOSAL — {p.get('strategy', '').replace('_', ' ')}",
        f"Symbol: {p.get('symbol')} · Account: {p.get('account') or '—'}",
        f"Strike: ${p.get('strike')} · Expiration: {p.get('expiration')} · DTE: {p.get('dte')}",
        f"Contracts: {p.get('contracts')} · Premium/contract: ${p.get('premium')} · Total credit: ${p.get('premium_total')}",
        f"Spot: ${p.get('underlying_price')} · POP: {p.get('pop_pct')}% · Edge: {p.get('edge_score')}",
        f"IV rank: {p.get('iv_rank')}% · R:R: {p.get('risk_reward')} · EV: ${p.get('expected_value')}",
        f"Breakeven: ${p.get('breakeven')} · Max profit: {p.get('max_profit')} · Stock risk: {p.get('stock_downside_risk') or p.get('max_loss')}",
        f"Upside cap: {p.get('upside_cap') or '—'} · Data: {p.get('data_source') or '—'}",
    ]
    if p.get("aegis_note"):
        lines.append(f"Aegis screening (local): {p['aegis_note']}")
    if p.get("reasoning"):
        lines.append(f"Engine notes: {p['reasoning']}")
    return "\n".join(lines)[:4000]


def enqueue_ensemble_for_proposals(proposals: List[dict], fresh_hours: int = 24) -> dict:
    """Enqueue Grok+ChatGPT+local ensemble jobs for options proposals (idempotent)."""
    try:
        from db_adapter import _get_conn, USE_DB
        if not USE_DB:
            return {"ok": False, "error": "db disabled", "enqueued": 0, "skipped": len(proposals)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120], "enqueued": 0, "skipped": len(proposals)}

    conn = _get_conn()
    cur = conn.cursor()
    enqueued = skipped = 0
    for p in proposals:
        tid = str(p.get("id") or "")
        if not tid:
            skipped += 1
            continue
        cur.execute(
            """SELECT 1 FROM inference_ensemble_results
               WHERE target_type='options_proposal' AND target_id=%s
                 AND created_at > NOW() - make_interval(hours => %s) LIMIT 1""",
            (tid, fresh_hours),
        )
        if cur.fetchone():
            skipped += 1
            continue
        cur.execute(
            """SELECT 1 FROM inference_ensemble_jobs
               WHERE target_type='options_proposal' AND target_id=%s
                 AND status IN ('queued','running') LIMIT 1""",
            (tid,),
        )
        if cur.fetchone():
            skipped += 1
            continue
        subject = f"{p.get('symbol')} {str(p.get('strategy', '')).replace('_', ' ')} · ${p.get('strike')}"
        content = _proposal_ensemble_content(p)
        cur.execute(
            """INSERT INTO inference_ensemble_jobs
               (target_type, target_id, subject, content, task, requested_by, status)
               VALUES ('options_proposal', %s, %s, %s, 'options_proposal_quality', 'options_engine', 'queued')""",
            (tid, subject[:300], content),
        )
        enqueued += 1
    conn.commit()
    if enqueued:
        _audit("ensemble_enqueued", count=enqueued, skipped=skipped)
    return {"ok": True, "enqueued": enqueued, "skipped": skipped, "total": len(proposals)}


def _build_reasoning(
    strategy: str,
    sym: str,
    ctx: dict,
) -> str:
    parts = []
    if ctx.get("iv_rank"):
        parts.append(f"IV rank {ctx['iv_rank']:.0f}% — {'favorable premium' if ctx['iv_rank'] >= 35 else 'moderate vol'}")
    if ctx.get("catalyst"):
        parts.append(ctx["catalyst"])
    if ctx.get("technical"):
        parts.append(ctx["technical"])
    if ctx.get("income_note"):
        parts.append(ctx["income_note"])
    # Aegis note is stored separately on the proposal (aegis_note) — not duplicated here.
    if ctx.get("layer4"):
        parts.append(f"Layer 4: {ctx['layer4'][:120]}")
    if not parts:
        parts.append(f"{strategy} on {sym} meets edge and risk gates.")
    return " · ".join(parts)


def generate_covered_call_proposals(
    holdings: List[dict],
    tech_map: dict,
    intent_cfg: dict,
    aegis_map: dict,
) -> List[dict]:
    """Covered calls on owned positions (≥100 shares)."""
    cc_syms = set(s.upper() for s in (intent_cfg.get("covered_call_candidate") or []))
    settings = intent_cfg.get("covered_call_settings") or {}
    default_dte = int(settings.get("default_dte_days", 30))
    default_otm = _f(settings.get("default_otm_pct", 0.06))
    min_iv = _f(settings.get("iv_rank_minimum", MIN_IV_RANK))

    proposals: List[dict] = []
    for h in holdings:
        sym = (h.get("symbol") or "").upper()
        shares = _f(h.get("shares"))
        price = _f(h.get("price"))
        mv = _f(h.get("market_value"))
        if shares < MIN_HOLDING_SHARES_CC or mv < MIN_POSITION_MV or price <= 0:
            continue
        if h.get("is_loan"):
            continue
        tech = tech_map.get(sym) or {}
        contracts = int(shares // 100)
        if contracts < 1:
            continue

        gates = _holding_quality_gates(h)
        min_iv_h = gates["min_iv"] if gates["manual"] else min_iv

        target_strike = price * (1 + default_otm)
        if price < 50:
            target_strike = round(target_strike / 0.5) * 0.5
        elif price < 200:
            target_strike = round(target_strike / 2.5) * 2.5
        else:
            target_strike = round(target_strike / 5.0) * 5.0

        contract, data_source = _resolve_option_contract(
            sym, price, tech, "call", target_strike, default_dte,
        )
        if not contract:
            continue
        premium = contract["mid"]
        strike = contract["strike"]
        dte = contract["dte"]
        iv = contract.get("iv") or 0.25
        exp = contract.get("exp")
        und = _f(price)

        iv_rank = _iv_rank_proxy(sym, tech, chain_iv=iv)
        if iv_rank < min_iv_h and sym not in cc_syms:
            continue

        pop = _pop_otm_call(und, strike, max(0.05, iv), dte)
        premium_total = round(premium * 100 * contracts, 2)
        max_profit = round(premium_total + max(0, strike - und) * shares, 2)
        # Covered call: stock can still fall (you own shares); upside capped at strike if assigned.
        stock_downside_risk = round(und * shares - premium_total, 2)
        max_loss = stock_downside_risk
        upside_cap = f"${strike:.2f} if assigned"
        breakeven = round(und - premium, 2)
        collateral = round(und * shares, 2)
        rr = (premium * 100 * contracts) / max(collateral * (dte / 365.0), 1.0)

        aegis = aegis_map.get(sym) or {}
        aegis_ok = (aegis.get("verdict") or "").lower() in ("candidate", "write", "ok", "")
        catalyst = ""
        if aegis.get("reasoning"):
            catalyst = str(aegis["reasoning"])[:160]
        elif sym in cc_syms:
            catalyst = "Portfolio intent: covered-call candidate (income + Roth funding path)"

        rsi = _f(tech.get("rsi"), 50)
        technical = f"RSI {rsi:.0f}"
        if tech.get("sma200"):
            technical += f", vs SMA200 {'above' if und > _f(tech['sma200']) else 'below'}"

        in_intent = sym in cc_syms
        edge = _edge_score(
            pop,
            iv_rank,
            rr,
            catalyst_boost=12.0 if in_intent else (8.0 if gates["manual"] else 3.0),
            conviction=_f(aegis.get("confidence"), 0.6),
        )
        if in_intent and pop >= MIN_POP_PCT:
            edge = max(edge, pop * 0.55 + 18.0)
        if gates["manual"]:
            edge = round(edge + gates["edge_boost"], 1)
        min_edge = gates["min_edge"] if (in_intent or gates["manual"]) else MIN_EDGE_SCORE
        if edge < min_edge or pop < MIN_POP_PCT:
            continue
        if aegis and not aegis_ok and (aegis.get("verdict") or "").lower() in ("reject", "avoid", "wait"):
            continue

        ctx = {
            "iv_rank": iv_rank,
            "catalyst": catalyst,
            "technical": technical,
            "aegis": aegis.get("reasoning") or "",
            "income_note": f"Est. ${premium * 100 * contracts:,.0f} premium ({contracts} contract{'s' if contracts > 1 else ''})",
        }
        acct = h.get("account_display") or h.get("account") or ""
        proposals.append(_stamp_execution({
            "id": _proposal_id("covered_call", sym, acct, strike, exp),
            "strategy": "covered_call",
            "symbol": sym,
            "underlying": sym,
            "account": acct,
            "intent_sleeve": in_intent,
            "aegis_note": (aegis.get("reasoning") or "")[:160] or None,
            "aegis_verdict": aegis.get("verdict"),
            "side": "SELL",
            "option_type": "call",
            "strike": strike,
            "expiration": exp,
            "dte": dte,
            "contracts": contracts,
            "premium": round(premium, 2),
            "premium_total": premium_total,
            "underlying_price": round(und, 2),
            "pop_pct": pop,
            "max_profit": max_profit,
            "max_loss": max_loss,
            "stock_downside_risk": stock_downside_risk,
            "upside_cap": upside_cap,
            "max_loss_note": "Stock can fall to $0 (you still own shares); premium offsets loss slightly.",
            "upside_cap_note": "If stock rises above strike, shares may be called away at the strike — upside capped.",
            "breakeven": breakeven,
            "risk_reward": round(rr, 3),
            "expected_value": round(premium * 100 * contracts * (pop / 100.0), 2),
            "edge_score": edge,
            "iv_rank": iv_rank,
            "delta": contract.get("delta") if contract else None,
            "oi": contract.get("oi") if contract else None,
            "severity": "positive" if edge >= 75 else "info",
            "recommended_action": "Sell Covered Call",
            "action_buttons": [
                {"action": "sell_covered_call", "label": "Sell Covered Call"},
                {"action": "review_chain", "label": "View Chain"},
                {"action": "hold", "label": "Pass"},
            ],
            "reasoning": _build_reasoning("Covered call", sym, ctx),
            "quality_pass": True,
            "data_source": data_source,
            "execution_note": _execution_note(),
            "generated_at": _iso(),
        }, acct))
    proposals.sort(key=lambda x: -x["edge_score"])
    return proposals


def generate_holdings_put_proposals(
    holdings: List[dict],
    tech_map: dict,
    cash_map: Dict[str, float],
    aegis_map: dict,
) -> List[dict]:
    """Protective long puts on large owned positions.

    Cash-secured puts on non-owned names are generated via generate_defined_risk_proposals
    (classic wheel entry) — not on symbols you already hold.
    """
    proposals: List[dict] = []

    # Protective long puts on large positions (≥$15k MV)
    for h in holdings:
        if h.get("is_cash"):
            continue
        sym = (h.get("symbol") or "").upper()
        price = _f(h.get("price"))
        mv = _f(h.get("market_value"))
        shares = _f(h.get("shares"))
        acct = h.get("account") or ""
        if mv < MIN_PROTECTIVE_MV or price <= 0 or shares < 50:
            continue
        gates = _holding_quality_gates(h)
        tech = tech_map.get(sym) or {}
        und = price
        iv_rank = _iv_rank_proxy(sym, tech)
        if iv_rank < gates["min_iv"]:
            continue
        # Protective put: ~5% OTM put, 45-60 DTE
        target_strike = round(und * 0.95 / 2.5) * 2.5 if und > 50 else round(und * 0.95, 1)
        contract, data_source = _resolve_option_contract(sym, price, tech, "put", target_strike, 45)
        if not contract:
            continue
        premium = contract["mid"]
        if premium <= 0:
            continue
        strike, dte, iv = contract["strike"], contract["dte"], contract.get("iv") or 0.3
        pop = 100.0 - _pop_otm_put(und, strike, max(0.05, iv), dte)
        contracts = max(1, int(shares // 100))
        cost = round(premium * 100 * contracts, 2)
        hedge_ratio = mv / max(cost, 1.0)
        edge = _edge_score_debit(
            pop=pop, iv_rank=iv_rank, hedge_ratio=min(3.0, hedge_ratio / 10.0),
            conviction=0.55, dte=dte,
        )
        if gates["manual"]:
            edge = round(edge + gates["edge_boost"] * 0.35, 1)
        min_edge = MIN_EDGE_CC_INTENT if gates["manual"] else (MIN_EDGE_SCORE - 8)
        if edge < min_edge:
            continue
        acct_disp = h.get("account_display") or acct
        proposals.append(_stamp_execution({
            "id": _proposal_id("protective_put", sym, acct_disp, strike, contract.get("exp") or ""),
            "strategy": "protective_put",
            "symbol": sym,
            "underlying": sym,
            "side": "BUY",
            "option_type": "put",
            "strike": strike,
            "expiration": contract.get("exp"),
            "dte": dte,
            "contracts": contracts,
            "premium": premium,
            "premium_total": cost,
            "underlying_price": round(und, 2),
            "pop_pct": round(pop, 1),
            "max_profit": "hedge",
            "max_loss": cost,
            "breakeven": round(strike - premium, 2),
            "risk_reward": round(mv / max(cost, 1), 2),
            "expected_value": round(-cost * 0.5, 2),
            "edge_score": edge,
            "iv_rank": iv_rank,
            "severity": "info",
            "recommended_action": "Buy Protective Put",
            "action_buttons": [
                {"action": "buy_put", "label": "Buy Put (hedge)"},
                {"action": "review_chain", "label": "View Chain"},
                {"action": "hold", "label": "Pass"},
            ],
            "reasoning": _build_reasoning("Protective put", sym, {
                "iv_rank": iv_rank,
                "technical": f"Hedge ${mv:,.0f} position ({contracts} contracts)",
            }),
            "quality_pass": True,
            "data_source": data_source,
            "execution_note": _execution_note("Manual hedge — size to shares held."),
            "generated_at": _iso(),
        }, acct))

    proposals.sort(key=lambda x: -x["edge_score"])
    return proposals[:12]


def _append_long_call_proposal(
    proposals: List[dict],
    *,
    sym: str,
    und: float,
    conf: float,
    iv_rank: float,
    c: dict,
    contract: dict,
    data_source: str,
) -> None:
    premium = contract["mid"]
    strike, dte, iv = contract["strike"], contract["dte"], contract.get("iv") or 0.3
    pop = 100.0 - _pop_otm_call(und, strike, max(0.05, iv), dte)
    max_loss = round(premium * 100, 2)
    breakeven = round(strike + premium, 2)
    rr = premium * 100 / max(strike * 100, 1)
    edge = _edge_score_debit(pop=pop, iv_rank=iv_rank, hedge_ratio=0.5, conviction=conf, dte=dte)
    min_edge = MIN_EDGE_CONVICTION - 8 if conf >= 0.65 else MIN_EDGE_CONVICTION - 3
    if edge < min_edge:
        return
    proposals.append(_stamp_execution({
        "id": _proposal_id("long_call", sym, "", strike, contract.get("exp") or ""),
        "strategy": "long_call",
        "symbol": sym,
        "underlying": sym,
        "side": "BUY",
        "option_type": "call",
        "strike": strike,
        "expiration": contract.get("exp"),
        "dte": dte,
        "contracts": 1,
        "premium": premium,
        "premium_total": round(premium * 100, 2),
        "underlying_price": round(und, 2),
        "pop_pct": round(pop, 1),
        "max_profit": "unlimited",
        "max_loss": max_loss,
        "breakeven": breakeven,
        "risk_reward": round(rr, 3),
        "expected_value": round(premium * 100 * (pop / 100.0) * -1, 2),
        "edge_score": edge,
        "iv_rank": iv_rank,
        "delta": contract.get("delta"),
        "severity": "info",
        "recommended_action": "Buy Call (defined risk)",
        "action_buttons": [
            {"action": "buy_call", "label": "Buy Call"},
            {"action": "review_chain", "label": "View Chain"},
            {"action": "hold", "label": "Pass"},
        ],
        "reasoning": _build_reasoning("Long call", sym, {
            "iv_rank": iv_rank,
            "layer4": c.get("summary") or "",
            "technical": f"Conviction {conf:.0%}",
        }),
        "quality_pass": True,
        "data_source": data_source,
        "execution_note": _execution_note(),
        "generated_at": _iso(),
    }))


def _append_csp_proposal(
    proposals: List[dict],
    *,
    sym: str,
    und: float,
    conf: float,
    iv_rank: float,
    c: dict,
    contract: dict,
    data_source: str,
) -> None:
    premium = contract["mid"]
    strike, dte, iv = contract["strike"], contract["dte"], contract.get("iv") or 0.3
    pop = _pop_otm_put(und, strike, max(0.05, iv), dte)
    max_profit = round(premium * 100, 2)
    max_loss = round((strike - premium) * 100, 2)
    breakeven = round(strike - premium, 2)
    rr = max_profit / max(max_loss, 1)
    edge = _edge_score_wheel(
        pop, iv_rank, premium, strike - premium, conviction=conf, dte=dte,
    )
    min_edge = MIN_EDGE_CONVICTION if conf >= 0.6 else MIN_EDGE_SCORE
    if edge < min_edge or pop < MIN_POP_PCT - 3:
        return
    proposals.append(_stamp_execution({
        "id": _proposal_id("cash_secured_put", sym, "", strike, contract.get("exp") or ""),
        "strategy": "cash_secured_put",
        "symbol": sym,
        "underlying": sym,
        "side": "SELL",
        "option_type": "put",
        "strike": strike,
        "expiration": contract.get("exp"),
        "dte": dte,
        "contracts": 1,
        "premium": premium,
        "premium_total": round(premium * 100, 2),
        "underlying_price": round(und, 2),
        "pop_pct": pop,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakeven": breakeven,
        "risk_reward": round(rr, 3),
        "expected_value": round(premium * 100 * (pop / 100.0), 2),
        "edge_score": edge,
        "iv_rank": iv_rank,
        "delta": contract.get("delta"),
        "severity": "positive" if edge >= 72 else "info",
        "recommended_action": "Sell Cash-Secured Put",
        "action_buttons": [
            {"action": "sell_put", "label": "Sell Put"},
            {"action": "review_chain", "label": "View Chain"},
            {"action": "hold", "label": "Pass"},
        ],
        "reasoning": _build_reasoning("Cash-secured put", sym, {
            "iv_rank": iv_rank,
            "layer4": c.get("summary") or "",
            "technical": f"Wheel entry on conviction name, POP {pop:.0f}%",
        }),
        "quality_pass": True,
        "data_source": data_source,
        "execution_note": _execution_note(
            "Verify buying power + SSDI income context before entry."
        ),
        "generated_at": _iso(),
    }))


def generate_defined_risk_proposals(
    convictions: List[dict],
    tech_map: dict,
    owned: set,
    holdings: Optional[List[dict]] = None,
) -> List[dict]:
    """Cash-secured puts + long calls on high-conviction names (not already full CC from same sleeve)."""
    proposals: List[dict] = []
    for c in convictions:
        sym = c["symbol"]
        if sym in owned:
            continue
        tech = tech_map.get(sym) or {}
        price = _f(tech.get("price") or tech.get("last"))
        if price <= 0:
            price = _resolve_symbol_price(sym, tech_map, holdings or [])
        if price <= 0:
            continue
        conf = _f(c.get("confidence"), 0.5)
        iv_rank = _iv_rank_proxy(sym, tech)
        min_iv = MIN_IV_CONVICTION if conf >= 0.6 else MIN_IV_RANK
        if iv_rank < min_iv:
            continue

        und = price
        bias = _conviction_bias(c)

        if bias == "bullish" and conf >= 0.6:
            target_strike = round(und * 1.04 / 2.5) * 2.5 if und > 50 else round(und * 1.05, 1)
            contract, data_source = _resolve_option_contract(sym, und, tech, "call", target_strike, 35)
            if contract:
                _append_long_call_proposal(
                    proposals, sym=sym, und=und, conf=conf, iv_rank=iv_rank,
                    c=c, contract=contract, data_source=data_source,
                )
        elif conf >= 0.55:
            target_strike = round(und * 0.92 / 2.5) * 2.5 if und > 50 else round(und * 0.93, 1)
            contract, data_source = _resolve_option_contract(sym, und, tech, "put", target_strike, 30)
            if contract:
                _append_csp_proposal(
                    proposals, sym=sym, und=und, conf=conf, iv_rank=iv_rank,
                    c=c, contract=contract, data_source=data_source,
                )
    proposals.sort(key=lambda x: -x["edge_score"])
    return proposals[:12]


def _resolve_spread_puts(
    sym: str,
    und: float,
    tech: dict,
    short_strike: float,
    long_strike: float,
    target_dte: int = 30,
) -> Tuple[Optional[dict], Optional[dict], str]:
    """Resolve bull-put spread legs from chain or BS fallback."""
    short_c, src_s = _resolve_option_contract(sym, und, tech, "put", short_strike, target_dte)
    long_c, src_l = _resolve_option_contract(sym, und, tech, "put", long_strike, target_dte)
    if short_c and long_c:
        src = "schwab_chain" if src_s == "schwab_chain" and src_l == "schwab_chain" else "bs_estimate"
        return short_c, long_c, src
    return None, None, ""


def generate_credit_spread_proposals(
    convictions: List[dict],
    tech_map: dict,
    holdings: Optional[List[dict]] = None,
) -> List[dict]:
    """Bull put / bear call credit spreads on high-conviction names (defined risk)."""
    proposals: List[dict] = []
    for c in convictions[:15]:
        sym = c["symbol"]
        tech = tech_map.get(sym) or {}
        price = _f(tech.get("price") or tech.get("last"))
        if price <= 0:
            price = _resolve_symbol_price(sym, tech_map, holdings or [])
        if price <= 0:
            continue
        und = price
        conf = _f(c.get("confidence"), 0.5)
        if conf < 0.58:
            continue
        iv_rank = _iv_rank_proxy(sym, tech)
        min_iv = MIN_IV_CONVICTION if conf >= 0.62 else MIN_IV_RANK
        if iv_rank < min_iv:
            continue
        # Bull put credit spread: sell higher strike put, buy lower strike put
        short_strike = round(und * 0.93 / 2.5) * 2.5 if und > 50 else round(und * 0.94, 1)
        long_strike = round(short_strike * 0.95 / 2.5) * 2.5 if und > 50 else round(short_strike * 0.96, 1)
        short_c, long_c, data_source = _resolve_spread_puts(sym, und, tech, short_strike, long_strike, 30)
        if not short_c or not long_c:
            continue
        net_credit = round(max(0.05, short_c["mid"] - long_c["mid"]), 2)
        if net_credit < 0.08:
            continue
        width = short_strike - long_strike
        max_loss = round((width - net_credit) * 100, 2)
        dte = int(short_c.get("dte") or 30)
        iv = max(0.05, short_c.get("iv") or _resolve_iv_decimal(und, tech, "put"))
        pop = _pop_otm_put(und, short_strike, iv, dte)
        rr = (net_credit * 100) / max(max_loss, 1)
        edge = _edge_score_wheel(
            pop, iv_rank, net_credit, width - net_credit, conviction=conf, dte=dte,
        )
        min_edge = MIN_EDGE_CONVICTION if conf >= 0.62 else MIN_EDGE_SCORE
        if edge < min_edge or pop < MIN_POP_PCT - 3:
            continue
        proposals.append(_stamp_execution({
            "id": _proposal_id("credit_spread", sym, "", short_strike, short_c.get("exp") or ""),
            "strategy": "credit_spread",
            "symbol": sym,
            "underlying": sym,
            "option_type": "put",
            "short_strike": short_strike,
            "long_strike": long_strike,
            "strike": short_strike,
            "expiration": short_c.get("exp"),
            "dte": short_c["dte"],
            "contracts": 1,
            "premium": net_credit,
            "premium_total": round(net_credit * 100, 2),
            "underlying_price": round(und, 2),
            "pop_pct": pop,
            "max_profit": round(net_credit * 100, 2),
            "max_loss": max_loss,
            "breakeven": round(short_strike - net_credit, 2),
            "risk_reward": round(rr, 3),
            "expected_value": round(net_credit * 100 * (pop / 100.0), 2),
            "edge_score": edge,
            "iv_rank": iv_rank,
            "severity": "positive" if edge >= 70 else "info",
            "recommended_action": "Sell Put Credit Spread",
            "action_buttons": [
                {"action": "sell_credit_spread", "label": "Sell Credit Spread"},
                {"action": "review_chain", "label": "View Chain"},
                {"action": "hold", "label": "Pass"},
            ],
            "reasoning": _build_reasoning("Put credit spread", sym, {
                "iv_rank": iv_rank,
                "layer4": c.get("summary") or "",
                "technical": f"${short_strike}/${long_strike} width ${width:.1f}, credit ${net_credit:.2f}",
            }),
            "quality_pass": True,
            "data_source": data_source,
            "execution_note": _execution_note(),
            "generated_at": _iso(),
        }))
    proposals.sort(key=lambda x: -x["edge_score"])
    return proposals[:8]


def _fetch_schwab_option_positions() -> List[dict]:
    positions: List[dict] = []
    try:
        import schwab_transport
        from db_adapter import _execute, USE_DB
        keys = []
        if USE_DB:
            rows = _execute(
                "SELECT account_key FROM schwab_account_links WHERE verified=TRUE",
                fetch="all",
            ) or []
            keys = [r["account_key"] for r in rows if r.get("account_key")]
        if not keys:
            keys = ["schwab_taxable"]
        for acct in keys:
            raw = schwab_transport.get_positions(acct)
            if isinstance(raw, list):
                for p in raw:
                    sym = p.get("symbol") or ""
                    parsed = _parse_occ(sym.replace(" ", ""))
                    if not parsed:
                        continue
                    qty = abs(_f(p.get("qty")))
                    if qty <= 0:
                        continue
                    side = "short" if _f(p.get("qty")) < 0 else "long"
                    positions.append({
                        "account_key": acct,
                        "occ_symbol": sym,
                        "qty": qty,
                        "side": side,
                        "avg_entry": _f(p.get("avg_entry_price")),
                        "market_value": _f(p.get("market_value")),
                        **parsed,
                    })
    except Exception:
        pass
    return positions


def _monitor_position(pos: dict, tech_map: dict) -> dict:
    """Classify ITM/OTM and recommend hold/close/roll."""
    und_sym = pos["underlying"]
    tech = tech_map.get(und_sym) or {}
    spot = _f(tech.get("price") or tech.get("last"))
    chain = _schwab_chain(und_sym, strikes=14)
    if chain.get("underlying_price"):
        spot = _f(chain["underlying_price"]) or spot

    strike = _f(pos["strike"])
    dte = int(pos.get("dte") or 0)
    opt_type = pos.get("option_type") or "call"
    is_short = pos.get("side") == "short"

    contract = _pick_chain_contract(
        chain,
        opt_type,
        strike,
        dte if dte > 0 else 21,
    )
    mark = contract["mid"] if contract else 0.0
    iv = (contract.get("iv") if contract else 0.25) or 0.25
    delta = contract.get("delta") if contract else None

    if opt_type == "call":
        itm = spot > strike
        pop_otm = _pop_otm_call(spot, strike, iv, max(dte, 1))
        pop_itm = 100.0 - pop_otm
    else:
        itm = spot < strike
        pop_otm = _pop_otm_put(spot, strike, iv, max(dte, 1))
        pop_itm = 100.0 - pop_otm

    moneyness = "ITM" if itm else "OTM"
    if abs(spot - strike) / max(strike, 1) < 0.01:
        moneyness = "ATM"

    pnl_unrealized = None
    entry = _f(pos.get("avg_entry"))
    if entry and mark:
        mult = 100 * _f(pos.get("qty"), 1)
        if is_short:
            pnl_unrealized = round((entry - mark) * mult, 2)
        else:
            pnl_unrealized = round((mark - entry) * mult, 2)

    working = True
    action = "hold"
    action_label = "Hold"
    rationale_parts = []

    if is_short and opt_type == "call":
        if itm and dte <= 7:
            action, action_label = "roll", "Roll to Next Expiration"
            rationale_parts.append("Short call ITM with ≤7 DTE — assignment risk elevated")
            working = False
        elif pop_otm >= 75 and pnl_unrealized and pnl_unrealized > 0:
            action, action_label = "close_profit", "Close for Profit"
            rationale_parts.append(f"{pop_otm:.0f}% chance OTM — capture {pnl_unrealized:.0f} unrealized")
        elif not itm and pop_otm >= 60:
            action, action_label = "hold", "Hold"
            rationale_parts.append(f"Position working: {pop_otm:.0f}% POP OTM, {dte} DTE left")
        elif itm:
            action, action_label = "close", "Close / Roll"
            rationale_parts.append("ITM short call — consider rolling or closing to avoid assignment")
            working = False
    elif is_short and opt_type == "put":
        if itm and dte <= 10:
            action, action_label = "close", "Close Position"
            rationale_parts.append("Short put ITM — assignment risk on underlying")
            working = False
        elif pop_otm >= 70 and pnl_unrealized and pnl_unrealized > 0:
            action, action_label = "close_profit", "Close for Profit"
            rationale_parts.append(f"Capture premium — {pop_otm:.0f}% still OTM")
        else:
            rationale_parts.append(f"CSP monitoring: {moneyness}, POP OTM {pop_otm:.0f}%")
    else:
        if pnl_unrealized and pnl_unrealized < -0.5 * entry * 100:
            action, action_label = "close", "Cut Loss"
            rationale_parts.append("Long option down >50% — edge deteriorated")
            working = False
        elif pop_itm >= 65 and pnl_unrealized and pnl_unrealized > 0:
            action, action_label = "close_profit", "Take Profit"
            rationale_parts.append(f"In-the-money with {pop_itm:.0f}% finish ITM probability")
        else:
            rationale_parts.append(f"Long {opt_type}: {moneyness}, {dte} DTE")

    iv_rank = _iv_rank_proxy(und_sym, tech, chain_iv=iv)
    edge = _edge_score(pop_otm if is_short else pop_itm, iv_rank, 0.5, conviction=0.5)

    return {
        "id": pos.get("occ_symbol") or f"{und_sym}_{strike}_{opt_type}",
        "occ_symbol": pos.get("occ_symbol"),
        "underlying": und_sym,
        "account_key": pos.get("account_key"),
        "strategy": f"{'short' if is_short else 'long'}_{opt_type}",
        "option_type": opt_type,
        "side": pos.get("side"),
        "strike": strike,
        "expiration": pos.get("expiration"),
        "dte": dte,
        "qty": _f(pos.get("qty"), 1),
        "underlying_price": round(spot, 2),
        "mark": mark,
        "avg_entry": entry,
        "unrealized_pnl": pnl_unrealized,
        "moneyness": moneyness,
        "itm": itm,
        "pop_otm_pct": pop_otm,
        "pop_itm_pct": pop_itm,
        "delta": delta,
        "iv_rank": iv_rank,
        "edge_score": edge,
        "still_working": working,
        "recommended_action": action_label,
        "action": action,
        "action_buttons": [
            {"action": action, "label": action_label},
            {"action": "roll", "label": "Roll to Next Week"},
            {"action": "hold", "label": "Hold"},
            {"action": "review_chain", "label": "View Chain"},
        ],
        "rationale": " · ".join(rationale_parts) or f"{moneyness} — monitor",
        "severity": "warning" if not working else ("positive" if (pnl_unrealized or 0) > 0 else "info"),
        "monitored_at": _iso(),
    }


def _apply_enterprise_layer(proposals: List[dict]) -> List[dict]:
    """Attach enterprise desk metadata: earnings blackout, liquidity, vol, tiers."""
    try:
        import options_desk_enterprise as ent
    except Exception:
        return proposals
    chain_cache: Dict[str, dict] = {}
    enriched: List[dict] = []
    for p in proposals:
        sym = (p.get("symbol") or "").upper()
        if sym and sym not in chain_cache:
            chain_cache[sym] = _schwab_chain(sym, strikes=12)
        chain = chain_cache.get(sym) or {}
        contract = None
        if p.get("data_source") != "bs_estimate":
            side = "call" if (p.get("option_type") or "").lower() == "call" else "put"
            contract = _pick_chain_contract(chain, side, _f(p.get("strike")), int(p.get("dte") or 30))
        row = ent.enterprise_enrich_proposal(dict(p), contract=contract, chain=chain)
        und = _f(row.get("underlying_price"))
        if sym and und > 0:
            vol = ent.vol_analytics_from_chain(chain, und)
            if vol.get("ok"):
                ent.persist_chain_snapshot(sym, chain, vol)
        enriched.append(row)
    return enriched


def generate_proposals(force: bool = False) -> dict:
    """Full proposal pass with quality filter."""
    cached = _load_json(PROPOSALS_CACHE)
    if not force and cached.get("generated_at"):
        try:
            age = (_now() - datetime.fromisoformat(cached["generated_at"].replace("Z", "+00:00"))).total_seconds()
            if age < 600:
                return cached
        except Exception:
            pass

    holdings, _ = _load_holdings()
    tech_map = _load_technicals()
    intent_cfg = _load_intent_cfg()
    aegis_map = _aegis_cc_map()
    owned = {h.get("symbol", "").upper() for h in holdings if _f(h.get("shares")) >= 100}
    convictions = _high_conviction_symbols()
    conv_syms = [c["symbol"] for c in convictions if c.get("symbol")]
    hold_syms = [(h.get("symbol") or "").upper() for h in holdings if not h.get("is_cash")]
    tech_map = _enrich_tech_map(conv_syms + hold_syms, tech_map, holdings)

    cc = generate_covered_call_proposals(holdings, tech_map, intent_cfg, aegis_map)
    cash_map = _cash_by_account(holdings)
    puts = generate_holdings_put_proposals(holdings, tech_map, cash_map, aegis_map)
    dr = generate_defined_risk_proposals(convictions, tech_map, owned, holdings)
    spreads = generate_credit_spread_proposals(convictions, tech_map, holdings)
    pool = cc + puts + dr + spreads
    cc_syms = set(s.upper() for s in (intent_cfg.get("covered_call_candidate") or []))

    def _passes_quality_gate(p: dict) -> bool:
        if not p.get("quality_pass"):
            return False
        edge = _f(p.get("edge_score"))
        sym = (p.get("symbol") or "").upper()
        strat = p.get("strategy") or ""
        manual = p.get("execution_mode") == "manual" or p.get("broker") == "fidelity"
        # Income-sleeve names (V, SCHD, LMT in portfolio_intent) use relaxed floor — final
        # filter must match per-proposal generation or borderline intent CCs vanish (V ~61 vs 62).
        if strat in DEBIT_STRATEGIES:
            min_e = MIN_EDGE_CC_INTENT - 5
        elif strat in WHEEL_STRATEGIES:
            min_e = MIN_EDGE_CONVICTION
        elif strat == "covered_call" and sym in cc_syms:
            min_e = MIN_EDGE_CC_INTENT
        elif manual and strat in ("covered_call", "cash_secured_put", "protective_put"):
            min_e = MIN_EDGE_CC_INTENT
        else:
            min_e = MIN_EDGE_SCORE
        return edge >= min_e

    strict = [p for p in pool if _passes_quality_gate(p)]
    fallback_used = False
    if not strict and pool:
        relaxed = [
            p for p in pool
            if p.get("edge_score", 0) >= MIN_EDGE_CC_INTENT and _f(p.get("pop_pct")) >= (MIN_POP_PCT - 5)
        ]
        for p in relaxed:
            p["fallback_tier"] = True
            p["quality_pass"] = True
            note = " · Fallback tier (relaxed gates — income sleeve / BS estimate when chain thin)"
            p["reasoning"] = (p.get("reasoning") or "") + note
        strict = relaxed[:8]
        fallback_used = bool(strict)
        if fallback_used:
            _audit("fallback_tier", count=len(strict), symbols=[p.get("symbol") for p in strict])

    strict = _apply_enterprise_layer(strict)
    all_p = _allocate_strategy_slots(strict)

    enterprise_summary = {}
    approval_sync = {}
    try:
        import options_desk_enterprise as ent
        raw_positions = _fetch_schwab_option_positions()
        enterprise_summary = ent.build_enterprise_summary(all_p, holdings, raw_positions)
        approval_sync = ent.sync_approval_queue(all_p)
    except Exception as e:
        enterprise_summary = {"ok": False, "error": str(e)[:120]}
        approval_sync = {"ok": False, "error": str(e)[:120]}

    out = {
        "generated_at": _iso(),
        "count": len(all_p),
        "covered_calls": len(cc),
        "puts": len(puts),
        "defined_risk": len(dr),
        "credit_spreads": len(spreads),
        "fidelity_holdings": sum(1 for h in holdings if (h.get("broker") == "fidelity" and not h.get("is_cash"))),
        "schwab_holdings": sum(1 for h in holdings if (h.get("broker") == "schwab" and not h.get("is_cash"))),
        "fallback_tier_used": fallback_used,
        "quality_gate": {
            "min_edge_score": MIN_EDGE_SCORE,
            "min_pop_pct": MIN_POP_PCT,
            "min_iv_rank": MIN_IV_RANK,
            "relaxed_edge_floor": MIN_EDGE_CC_INTENT,
        },
        "proposals": all_p,
        "desk_level": "enterprise",
        "enterprise": enterprise_summary,
        "approval_queue": approval_sync,
        "strategy_overview": {
            "total_edge_avg": round(sum(p["edge_score"] for p in all_p) / max(len(all_p), 1), 1),
            "avg_pop": round(sum(p.get("pop_pct", 50) for p in all_p) / max(len(all_p), 1), 1),
            "income_opportunities": sum(1 for p in all_p if p["strategy"] == "covered_call"),
            "put_plays": sum(1 for p in all_p if "put" in (p.get("strategy") or "")),
            "conviction_plays": sum(1 for p in all_p if p["strategy"] not in ("covered_call", "cash_secured_put", "protective_put")),
            "strategy_slots": STRATEGY_SLOTS,
            "note": "Balanced desk — per-strategy slots prevent covered-call crowding.",
        },
    }
    _save_json(PROPOSALS_CACHE, out)
    _audit("proposals_generated", count=len(all_p), cc=len(cc), dr=len(dr), spreads=len(spreads),
           fallback=fallback_used)
    try:
        ens = enqueue_ensemble_for_proposals(all_p)
        out["ensemble_enqueue"] = ens
    except Exception as e:
        out["ensemble_enqueue"] = {"ok": False, "error": str(e)[:120]}
    return out


def get_proposal_health_metrics() -> dict:
    """Snapshot for Health Agent + /api/v2/health/proposals."""
    props = _load_json(PROPOSALS_CACHE)
    mon = _load_json(MONITOR_CACHE)
    age_min = None
    try:
        if props.get("generated_at"):
            age_min = round(
                (_now() - datetime.fromisoformat(props["generated_at"].replace("Z", "+00:00"))).total_seconds() / 60, 1
            )
    except Exception:
        pass
    try:
        from db_adapter import _execute, USE_DB
        pending = int((_execute(
            "SELECT COUNT(*) AS c FROM paper_trade_proposals WHERE status='PENDING'", fetch="one"
        ) or {}).get("c", 0)) if USE_DB else None
        wl_stale = int((_execute(
            """SELECT COUNT(*) AS c FROM watchlist_items
               WHERE status='active' AND updated_at < NOW() - INTERVAL '7 days'""", fetch="one"
        ) or {}).get("c", 0)) if USE_DB else None
        rot_pending = int((_execute(
            "SELECT COUNT(*) AS c FROM strategy_rotation_recommendations WHERE status='proposed'", fetch="one"
        ) or {}).get("c", 0)) if USE_DB else None
    except Exception:
        pending = wl_stale = rot_pending = None
    tracking = {}
    try:
        import manual_execution_tracker as met
        tracking = met.get_tracking_metrics(days=14)
    except Exception:
        tracking = {}
    return {
        "captured_at": _iso(),
        "options": {
            "proposal_count": props.get("count", 0),
            "put_plays": props.get("puts", 0),
            "fidelity_holdings": props.get("fidelity_holdings", 0),
            "cache_age_min": age_min,
            "fallback_tier_used": props.get("fallback_tier_used", False),
            "open_legs": mon.get("position_count", 0),
            "needs_action": mon.get("needs_action_count", 0),
        },
        "trades": {"pending_proposals": pending},
        "watchlist": {"stale_active_7d": wl_stale},
        "rotation": {"pending_recommendations": rot_pending},
        "execution_tracking": tracking,
        "maturity_level": 10 if props.get("count", 0) > 0 else 7,
    }


def monitor_positions(force: bool = False) -> dict:
    """Refresh open options position monitoring."""
    cached = _load_json(MONITOR_CACHE)
    if not force and cached.get("monitored_at"):
        try:
            age = (_now() - datetime.fromisoformat(cached["monitored_at"].replace("Z", "+00:00"))).total_seconds()
            if age < 300:
                return cached
        except Exception:
            pass

    tech_map = _load_technicals()
    raw_positions = _fetch_schwab_option_positions()
    monitored = [_monitor_position(p, tech_map) for p in raw_positions]

    working = sum(1 for m in monitored if m.get("still_working"))
    needs_action = [m for m in monitored if m.get("action") not in ("hold",)]

    book_greeks = {}
    try:
        import options_desk_enterprise as ent
        book_greeks = ent.aggregate_book_greeks(monitored, tech_map)
    except Exception:
        book_greeks = {}

    out = {
        "monitored_at": _iso(),
        "position_count": len(monitored),
        "still_working": working,
        "needs_action_count": len(needs_action),
        "book_greeks": book_greeks,
        "positions": monitored,
        "alerts": [
            {
                "id": m["id"],
                "underlying": m["underlying"],
                "severity": m.get("severity"),
                "message": m.get("rationale"),
                "action": m.get("recommended_action"),
            }
            for m in needs_action
        ],
        "summary": {
            "itm_count": sum(1 for m in monitored if m.get("itm")),
            "otm_count": sum(1 for m in monitored if not m.get("itm")),
            "total_unrealized_pnl": round(
                sum(m.get("unrealized_pnl") or 0 for m in monitored), 2
            ),
        },
    }
    _save_json(MONITOR_CACHE, out)
    return out


def get_overview() -> dict:
    props = _load_json(PROPOSALS_CACHE) or generate_proposals()
    mon = _load_json(MONITOR_CACHE) or monitor_positions()
    return {
        "generated_at": _iso(),
        "desk_level": props.get("desk_level") or "enterprise",
        "proposals": props.get("strategy_overview") or {},
        "enterprise": props.get("enterprise") or {},
        "monitor": mon.get("summary") or {},
        "book_greeks": mon.get("book_greeks") or {},
        "proposal_count": props.get("count", 0),
        "open_positions": mon.get("position_count", 0),
        "needs_action": mon.get("needs_action_count", 0),
        "quality_gate": props.get("quality_gate"),
    }


STRATEGY_GROUPS: Dict[str, frozenset] = {
    "income": frozenset({"covered_call", "cash_secured_put", "credit_spread"}),
    "hedge": frozenset({"protective_put"}),
    "directional": frozenset({"long_call", "long_put"}),
    "spread": frozenset({"credit_spread"}),
}
PORTFOLIO_STRATEGIES = frozenset({"covered_call", "protective_put"})
CONVICTION_STRATEGIES = frozenset({"cash_secured_put", "long_call", "credit_spread", "long_put"})


def _proposal_sleeve(p: dict) -> str:
    strat = p.get("strategy") or ""
    if strat in PORTFOLIO_STRATEGIES:
        return "portfolio"
    if strat in CONVICTION_STRATEGIES:
        return "conviction"
    return "other"


def _is_spread_pair(p: dict) -> bool:
    return (p.get("strategy") == "credit_spread"
            and _f(p.get("short_strike")) > 0
            and _f(p.get("long_strike")) > 0)


def filter_proposals(
    proposals: List[dict],
    *,
    symbol: str = "",
    sector: str = "",
    strategy: str = "",
    strategy_group: str = "",
    option_type: str = "",
    side: str = "",
    sleeve: str = "",
    desk_tier: str = "",
    leg_style: str = "",
    live_eligible: Optional[bool] = None,
    min_dte: int = 0,
    max_dte: int = 999,
    min_pop: float = 0,
    min_edge: float = 0,
) -> List[dict]:
    sym_u = symbol.upper()
    strat_g = (strategy_group or "").lower()
    opt_t = (option_type or "").lower()
    side_u = (side or "").upper()
    sleeve_l = (sleeve or "").lower()
    tier_u = (desk_tier or "").upper()
    leg = (leg_style or "").lower()
    group_set = STRATEGY_GROUPS.get(strat_g)
    out = []
    for p in proposals:
        if sym_u and sym_u not in (p.get("symbol") or "").upper():
            continue
        if strategy and p.get("strategy") != strategy:
            continue
        if group_set and (p.get("strategy") or "") not in group_set:
            continue
        if opt_t and (p.get("option_type") or "").lower() != opt_t:
            continue
        if side_u and (p.get("side") or "").upper() != side_u:
            continue
        if sleeve_l and _proposal_sleeve(p) != sleeve_l:
            continue
        if tier_u and (p.get("desk_tier") or "").upper() != tier_u:
            continue
        if leg == "single" and _is_spread_pair(p):
            continue
        if leg in ("spread", "pair", "pairs") and not _is_spread_pair(p):
            continue
        if live_eligible is not None:
            eligible = bool((p.get("enterprise") or {}).get("live_eligible"))
            if eligible != live_eligible:
                continue
        dte = int(p.get("dte") or 0)
        if dte < min_dte or dte > max_dte:
            continue
        if _f(p.get("pop_pct")) < min_pop:
            continue
        if _f(p.get("edge_score")) < min_edge:
            continue
        if sector:
            pass
        out.append(p)
    return out


def proposal_filter_facets(proposals: List[dict]) -> dict:
    """Counts for desk filter chips (strategy, type, side, sleeve, pairs)."""
    by_strategy: Dict[str, int] = {}
    by_group: Dict[str, int] = {k: 0 for k in STRATEGY_GROUPS}
    by_option_type: Dict[str, int] = {}
    by_side: Dict[str, int] = {}
    by_sleeve: Dict[str, int] = {}
    by_tier: Dict[str, int] = {}
    spread_pairs = 0
    live_eligible = 0
    for p in proposals:
        strat = p.get("strategy") or "other"
        by_strategy[strat] = by_strategy.get(strat, 0) + 1
        for grp, members in STRATEGY_GROUPS.items():
            if strat in members:
                by_group[grp] += 1
        ot = (p.get("option_type") or "unknown").lower()
        by_option_type[ot] = by_option_type.get(ot, 0) + 1
        sd = (p.get("side") or "—").upper()
        by_side[sd] = by_side.get(sd, 0) + 1
        sl = _proposal_sleeve(p)
        by_sleeve[sl] = by_sleeve.get(sl, 0) + 1
        tier = (p.get("desk_tier") or "C").upper()
        by_tier[tier] = by_tier.get(tier, 0) + 1
        if _is_spread_pair(p):
            spread_pairs += 1
        if (p.get("enterprise") or {}).get("live_eligible"):
            live_eligible += 1
    return {
        "total": len(proposals),
        "by_strategy": by_strategy,
        "by_group": by_group,
        "by_option_type": by_option_type,
        "by_side": by_side,
        "by_sleeve": by_sleeve,
        "by_tier": by_tier,
        "spread_pairs": spread_pairs,
        "single_leg": len(proposals) - spread_pairs,
        "live_eligible": live_eligible,
    }


def filter_positions(
    positions: List[dict],
    *,
    symbol: str = "",
    option_type: str = "",
    side: str = "",
    leg_style: str = "",
    working_only: Optional[bool] = None,
) -> List[dict]:
    sym_u = symbol.upper()
    opt_t = (option_type or "").lower()
    side_f = (side or "").lower()
    leg = (leg_style or "").lower()
    out = []
    for p in positions:
        und = (p.get("underlying") or "").upper()
        if sym_u and sym_u not in und:
            continue
        if opt_t and (p.get("option_type") or "").lower() != opt_t:
            continue
        if side_f:
            ps = (p.get("side") or "").lower()
            strat = (p.get("strategy") or "").lower()
            is_short = ps == "short" or strat.startswith("short_")
            if side_f == "sell" and not is_short:
                continue
            if side_f == "buy" and is_short:
                continue
        if leg in ("spread", "pair", "pairs"):
            continue  # open monitor is single-leg OCC rows today
        if leg == "spread" and "spread" not in (p.get("strategy") or ""):
            continue
        if working_only is not None and bool(p.get("still_working")) != working_only:
            continue
        out.append(p)
    return out


def position_filter_facets(positions: List[dict]) -> dict:
    by_type: Dict[str, int] = {}
    by_side: Dict[str, int] = {"buy": 0, "sell": 0}
    working = 0
    for p in positions:
        ot = (p.get("option_type") or "unknown").lower()
        by_type[ot] = by_type.get(ot, 0) + 1
        ps = (p.get("side") or "").lower()
        strat = (p.get("strategy") or "").lower()
        is_short = ps == "short" or strat.startswith("short_")
        by_side["sell" if is_short else "buy"] += 1
        if p.get("still_working"):
            working += 1
    return {"total": len(positions), "by_option_type": by_type, "by_side": by_side, "working": working}


OPTIONS_DESK_RUNTIME = PROJECT_ROOT / "data" / "runtime" / "options_desk_latest.json"


def build_options_desk_summary(props: Optional[dict] = None) -> dict:
    """Compact desk summary for Hermes staging + TradeAI ticker attachment."""
    props = props or _load_json(PROPOSALS_CACHE) or generate_proposals()
    proposals = props.get("proposals") or []
    by_sym: Dict[str, List[dict]] = {}
    by_strat: Dict[str, int] = {}
    for p in proposals:
        sym = (p.get("symbol") or "").upper()
        strat = p.get("strategy") or "unknown"
        by_strat[strat] = by_strat.get(strat, 0) + 1
        by_sym.setdefault(sym, []).append({
            "id": p.get("id"),
            "strategy": strat,
            "option_type": p.get("option_type"),
            "side": p.get("side"),
            "strike": p.get("strike"),
            "expiration": p.get("expiration"),
            "dte": p.get("dte"),
            "edge_score": p.get("edge_score"),
            "pop_pct": p.get("pop_pct"),
            "iv_rank": p.get("iv_rank"),
            "premium_total": p.get("premium_total"),
            "account": p.get("account"),
            "recommended_action": p.get("recommended_action"),
        })
    for sym in by_sym:
        by_sym[sym].sort(key=lambda x: -_f(x.get("edge_score")))
    top = sorted(proposals, key=lambda x: -_f(x.get("edge_score")))[:12]
    ent = props.get("enterprise") or {}
    return {
        "generated_at": props.get("generated_at") or _iso(),
        "desk_level": props.get("desk_level") or "enterprise",
        "proposal_count": len(proposals),
        "strategy_counts": by_strat,
        "tier_counts": ent.get("tier_counts") or {},
        "live_eligible_count": (ent.get("risk") or {}).get("live_eligible_count"),
        "enterprise_blocked_count": (ent.get("risk") or {}).get("enterprise_blocked_count"),
        "strategy_slots": props.get("strategy_overview", {}).get("strategy_slots") or STRATEGY_SLOTS,
        "raw_pool": {
            "covered_calls": props.get("covered_calls", 0),
            "puts": props.get("puts", 0),
            "defined_risk": props.get("defined_risk", 0),
            "credit_spreads": props.get("credit_spreads", 0),
        },
        "top_proposals": [
            {
                "symbol": p.get("symbol"),
                "strategy": p.get("strategy"),
                "option_type": p.get("option_type"),
                "strike": p.get("strike"),
                "edge_score": p.get("edge_score"),
                "pop_pct": p.get("pop_pct"),
                "recommended_action": p.get("recommended_action"),
            }
            for p in top
        ],
        "by_symbol": by_sym,
    }


def publish_options_desk_runtime(summary: Optional[dict] = None) -> dict:
    """Write latest desk summary for TradeAI cache + Hermes consumers."""
    summary = summary or build_options_desk_summary()
    OPTIONS_DESK_RUNTIME.parent.mkdir(parents=True, exist_ok=True)
    OPTIONS_DESK_RUNTIME.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


def options_context_for_symbol(symbol: str, summary: Optional[dict] = None) -> Optional[dict]:
    """Best options desk row for a TradeAI ticker (if any)."""
    summary = summary or _load_json(OPTIONS_DESK_RUNTIME) or build_options_desk_summary()
    rows = (summary.get("by_symbol") or {}).get((symbol or "").upper()) or []
    return rows[0] if rows else None


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposals", action="store_true")
    ap.add_argument("--monitor", action="store_true")
    ap.add_argument("--overview", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.monitor:
        print(json.dumps(monitor_positions(force=args.force), indent=2, default=str))
    elif args.overview:
        print(json.dumps(get_overview(), indent=2, default=str))
    else:
        print(json.dumps(generate_proposals(force=args.force), indent=2, default=str))