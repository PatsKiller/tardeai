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
import datetime as _dt
import re
import sys
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

# Stage 1E — reserve Hub Ideas slots for BUY_READY / ENTRY_NEAR long_call expressions.
ENTRY_STATE_CONVICTION_RESERVE = int(os.getenv("OPTIONS_ENTRY_STATE_RESERVE", "8"))
ENTRY_STATE_MAX_AGE_HOURS = int(os.getenv("OPTIONS_ENTRY_STATE_MAX_AGE_H", "36"))

DEBIT_STRATEGIES = frozenset({"protective_put", "long_call"})

OCC_RE = re.compile(
    r"^([A-Z]{1,6})\s*(\d{6})([CP])(\d{8})$"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


_DESK_CFG: Optional[dict] = None
# Why an income idea was not built (2026-09-26); reset per generate_proposals pass.
INCOME_SCREEN_DROPS: List[dict] = []
SOURCE_RECEIPTS: Dict[str, dict] = {}
IV_RANK_BASIS: Dict[str, str] = {}


def _desk_cfg() -> dict:
    global _DESK_CFG
    if _DESK_CFG is None:
        try:
            from options_desk_enterprise import load_desk_config
            _DESK_CFG = load_desk_config()
        except Exception:
            _DESK_CFG = {}
    return _DESK_CFG


def _income_screen(strategy: str, sym: str, contract: Optional[dict], data_source: str, und: float) -> Optional[str]:
    """Named reason an income card must not be built, recorded for the funnel."""
    from lib.options_income_quality import defer_liquidity, income_drop_reason, is_liquid
    reason = income_drop_reason(strategy, contract, data_source, und, _desk_cfg(), session=_SESSION.get("now"))
    if not reason and contract and not is_liquid(contract, _desk_cfg()) \
            and defer_liquidity(_SESSION.get("now"), _desk_cfg()):
        LIQUIDITY_DEFERRED.append({"symbol": sym, "strategy": strategy, "strike": contract.get("strike"),
                                   "oi": contract.get("oi"), "bid_ask_spread_pct": contract.get("bid_ask_spread_pct"),
                                   "session": _SESSION.get("now")})
    if reason:
        INCOME_SCREEN_DROPS.append({
            "symbol": sym, "strategy": strategy, "reason": reason,
            "strike": (contract or {}).get("strike"), "premium": (contract or {}).get("mid"),
            "oi": (contract or {}).get("oi"), "bid_ask_spread_pct": (contract or {}).get("bid_ask_spread_pct"),
        })
    return reason


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
            """SELECT iv_pct, captured_at FROM options_iv_history
               WHERE symbol=%s AND captured_at > NOW() - INTERVAL '365 days'
               ORDER BY captured_at ASC""",
            (sym.upper(),),
            fetch="all",
        ) or []
        vals = [_f(r.get("iv_pct")) for r in rows if _f(r.get("iv_pct")) > 0]
        # 2026-09-26: 5 readings from the same week (XAR 31.7-33.5%) made a "52-week
        # rank" of -95 -> 0 and refused the name. Trust history only once it is deep
        # and long enough; otherwise the caller falls back to the chain/Finviz proxy.
        cfg = _desk_cfg()
        min_n = int(cfg.get("iv_history_min_samples") or 60)
        min_span = float(cfg.get("iv_history_min_span_days") or 90)
        stamps = [r.get("captured_at") for r in rows if r.get("captured_at") is not None]
        span_days = (stamps[-1] - stamps[0]).total_seconds() / 86400.0 if len(stamps) >= 2 else 0.0
        if len(vals) < min_n or span_days < min_span:
            return None
        lo, hi = min(vals), max(vals)
        if hi <= lo:
            return 50.0
        return round(100.0 * (current_iv_pct - lo) / (hi - lo), 1)
    except Exception:
        return None


def _iv_rank_proxy(
    sym: str,
    tech: dict,
    chain_iv: Optional[float] = None,
    *,
    chain_lookup: bool = False,
    price: float = 0.0,
) -> float:
    """IV rank: prefer DB history; fallback to chain + Finviz proxy.

    2026-09-26: technical_snapshot.json covers holdings only, so every watchlist
    name arrived with no IV at all and scored the constant 12.5. With
    ``chain_lookup`` (generation passes only; tests stay offline) a name with no
    technical IV reads the at-the-money IV from its Schwab chain.
    """
    iv_pct = _f(tech.get("iv") or tech.get("volatility"))
    if chain_lookup and iv_pct <= 0 and not chain_iv:
        px = price or _f(tech.get("price") or tech.get("last"))
        chain_iv = _chain_atm_iv_pct(_schwab_chain(sym, strikes=16), px)
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
        IV_RANK_BASIS[sym] = "historical IV rank"
        return max(0.0, min(100.0, hist))
    if iv_pct <= 0 and not (hi > lo and px > 0) and vol_boost <= 0:
        # No IV, no 52-week range, no volatility: the blend is a constant 12.5 that
        # cleared the conviction floor on nothing (2026-09-26). Say "unknown" as 0.
        return 0.0
    IV_RANK_BASIS[sym] = "proxy blend of IV, price range and volatility; not historical IV rank"
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
        # Options desk is Schwab Path B + 2FA only (operator 2026-09-25).
        # Alpaca paper accounts are excluded from options generation / Hub.
        return {
            "broker": "alpaca",
            "execution_mode": "excluded",
            "execution_label": "Excluded · Alpaca (options desk is Schwab-only)",
            "auto_eligible": False,
            "options_desk_excluded": True,
        }
    return {
        "broker": "other",
        "execution_mode": "manual",
        "execution_label": "Manual",
        "auto_eligible": False,
    }


SCHWAB_ACCOUNT_PRIORITY: Tuple[str, ...] = (
    "schwab_taxable", "schwab_roth_ira", "schwab_rollover_ira",
)


def _canonical_account(h: dict) -> str:
    """Canonical account_key — never use human display_name as the execution key."""
    return (h.get("account") or h.get("account_id") or "").strip()


def _normalize_account_key(raw: str, holdings: Optional[List[dict]] = None) -> str:
    """Map display labels ('Fidelity Rollover Ira') back to account_key when leaked."""
    s = (raw or "").strip()
    if not s:
        return ""
    if "_" in s and s == s.lower():
        return s
    for h in holdings or []:
        disp = (h.get("account_display") or "").strip()
        key = _canonical_account(h)
        if s.lower() == disp.lower() or s.lower().replace(" ", "_") == key.lower():
            return key
    return s.lower().replace(" ", "_") if " " in s else s


def _accounts_for_symbol(symbol: str, holdings: List[dict]) -> List[dict]:
    sym = (symbol or "").upper()
    return [
        h for h in holdings
        if (h.get("symbol") or "").upper() == sym and not h.get("is_cash")
    ]


def _auto_select_account(
    symbol: str,
    holdings: List[dict],
    *,
    strategy: str = "",
    cash_map: Optional[Dict[str, float]] = None,
    min_shares: float = 0,
) -> str:
    """Auto-pick account: symbol lot first; wheel plays default to Schwab (auto), Fidelity stays manual."""
    lots = _accounts_for_symbol(symbol, holdings)
    if min_shares > 0:
        lots = [h for h in lots if _f(h.get("shares")) >= min_shares]
    if lots:
        lots.sort(key=lambda h: (-_f(h.get("shares")), -_f(h.get("market_value"))))
        return _canonical_account(lots[0])
    wheel = strategy in ("cash_secured_put", "long_call", "credit_spread", "long_put", "protective_put")
    if wheel:
        cmap = cash_map or {}
        for key in SCHWAB_ACCOUNT_PRIORITY:
            if cmap.get(key, 0) >= 5000:
                return key
        for key in SCHWAB_ACCOUNT_PRIORITY:
            if any(_canonical_account(h) == key for h in holdings):
                return key
        return "schwab_taxable"
    return ""


def _stamp_execution(p: dict, account: str = "", holdings: Optional[List[dict]] = None) -> dict:
    """Attach broker + execution_mode labels to a proposal row."""
    acct = _normalize_account_key(account or p.get("account") or "", holdings)
    prof = _execution_profile(acct)
    p["account"] = acct
    if acct and not p.get("account_display"):
        p["account_display"] = acct.replace("_", " ").title()
    p["broker"] = prof["broker"]
    p["execution_mode"] = prof["execution_mode"]
    p["execution_label"] = prof["execution_label"]
    p["auto_eligible"] = prof["auto_eligible"]
    # Slice A — first-class options identity GUIDs (stable across rescans).
    try:
        from scripts.lib.options_identity import stamp_proposal_identity
    except Exception:
        from lib.options_identity import stamp_proposal_identity  # type: ignore
    try:
        stamp_proposal_identity(p)
    except Exception as e:  # a missing GUID must be visible, not swallowed (48% coverage 09-24..26)
        p["identity_error"] = f"{type(e).__name__}: {str(e)[:120]}"
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
    strikes: int = 16,
    target_abs_delta: Optional[float] = None,
) -> Tuple[Optional[dict], str]:
    """Pick live chain contract or BS estimate."""
    chain = _schwab_chain(sym, strikes=strikes)
    und = _f(chain.get("underlying_price")) or price
    contract = _pick_chain_contract(chain, side, target_strike, target_dte, target_abs_delta=target_abs_delta)
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
    """Latest holdings of record — prefer served/persistent state over checkout-local.

    Stage 1 / holdings-backfill addendum (2026-09-24): CC/protective-put generation
    and the holdings funnel must refresh from what we currently own, not a stale
    worktree sleeve. Does not widen IV/intent gates.
    """
    candidates: List[Path] = []
    try:
        from scripts.lib.persistent_state_root import portfolio_state_write_targets
        for d in portfolio_state_write_targets(PROJECT_ROOT):
            candidates.append(Path(d) / "holdings.json")
    except Exception:
        try:
            from lib.persistent_state_root import portfolio_state_write_targets  # type: ignore
            for d in portfolio_state_write_targets(PROJECT_ROOT):
                candidates.append(Path(d) / "holdings.json")
        except Exception:
            pass
    candidates.append(STATE_DIR / "holdings.json")
    # Canonical persistent-state precedence, never filesystem mtime: copying an
    # old snapshot must not make it the newest observed portfolio.
    best = next((p for p in candidates if p.is_file()), None)
    best_mtime = best.stat().st_mtime if best is not None else None
    h = _load_json(best) if best is not None else {}
    if not isinstance(h, dict):
        h = {}
    raw = h.get("holdings") or []
    normalized = [_normalize_holding(x) for x in raw if (x.get("symbol") or "").upper()]
    # Options desk / Lifecycle tree: Schwab (+ Fidelity manual) only — drop Alpaca lots.
    kept, dropped_alpaca = [], 0
    for row in normalized:
        prof = _execution_profile(row.get("account") or "")
        if prof.get("broker") == "alpaca" or prof.get("options_desk_excluded"):
            dropped_alpaca += 1
            row["options_desk_excluded"] = True
            continue
        kept.append(row)
    meta = dict(h) if isinstance(h, dict) else {}
    meta["_holdings_path"] = str(best) if best is not None else None
    meta["_holdings_mtime"] = best_mtime if best is not None else None
    meta["_alpaca_holdings_excluded"] = dropped_alpaca
    meta["_inventory_holdings"] = normalized
    meta["_observed_at"] = h.get("as_of") or h.get("observed_at") or h.get("updated_at") or h.get("generated_at")
    return kept, meta


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


def _entry_state_conviction_symbols(limit: int = 15) -> List[dict]:
    """Stage 1E — BUY_READY / ENTRY_NEAR → Hub conviction universe (advisory long_call).

    Latest-per-symbol from cio_entry_states within ENTRY_STATE_MAX_AGE_HOURS.
    ATR preference reuses cio_options_fluency.atr_volatility_elevated (0.40 rule) — no fork.
    Falls back to empty on DB miss. Does not widen IV/intent or auto-trade.
    """
    out: List[dict] = []
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return out
        rows = _execute(
            """SELECT DISTINCT ON (upper(symbol))
                      upper(symbol) AS symbol, state, evaluated_at, details
                 FROM cio_entry_states
                WHERE state IN ('BUY_READY', 'ENTRY_NEAR')
                  AND evaluated_at > NOW() - (%s * INTERVAL '1 hour')
                ORDER BY upper(symbol), evaluated_at DESC
                LIMIT %s""",
            (int(ENTRY_STATE_MAX_AGE_HOURS), int(limit)),
            fetch="all",
        ) or []
    except Exception:
        return out

    desk_atr: Dict[str, float] = {}
    try:
        desk = _load_json(PROJECT_ROOT / "data" / "runtime" / "reentry_decision_desk_latest.json") or {}
        for r in desk.get("rows") or []:
            sym = (r.get("symbol") or "").upper()
            atr_v = _f(r.get("atr"))
            if sym and atr_v > 0:
                desk_atr[sym] = atr_v
    except Exception:
        pass

    try:
        from lib.cio_options_fluency import atr_volatility_elevated
    except Exception:
        try:
            from scripts.lib.cio_options_fluency import atr_volatility_elevated  # type: ignore
        except Exception:
            atr_volatility_elevated = None  # type: ignore

    for r in rows:
        sym = (r.get("symbol") or "").upper()
        state = str(r.get("state") or "")
        if not sym or state not in ("BUY_READY", "ENTRY_NEAR"):
            continue
        details = r.get("details") or {}
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except Exception:
                details = {}
        if not isinstance(details, dict):
            details = {}
        price = _f(details.get("price"))
        entry_low = _f(details.get("entry_low"))
        entry_high = _f(details.get("entry_high"))
        stop = _f(details.get("stop"))
        target = _f(details.get("target"))
        atr = _f(details.get("atr"))
        if atr <= 0:
            atr = desk_atr.get(sym, 0.0)
        vol_elevated = False
        atr_vs = None
        if atr_volatility_elevated is not None:
            vol_elevated, atr_vs, _ = atr_volatility_elevated(
                price=price or entry_high or entry_low, stop=stop, atr=atr if atr > 0 else None,
            )
        atr_note = ""
        if atr_vs is not None:
            atr_note = f" ATR/stop={atr_vs:.2f}" + (" elevated" if vol_elevated else "")
        zone = ""
        if entry_low > 0 or entry_high > 0:
            zone = f" zone ${entry_low:.2f}–${entry_high:.2f}" if entry_low and entry_high else ""
        out.append({
            "symbol": sym,
            "source": "entry_state",
            "confidence": 0.62,
            "bias": "bullish",
            "direction": "bullish",
            "entry_state": state,
            "entry_low": entry_low or None,
            "entry_high": entry_high or None,
            "stop": stop or None,
            "target": target or None,
            "atr": atr if atr > 0 else None,
            "price": price or None,
            "volatility_elevated": bool(vol_elevated),
            "atr_vs_distance_to_stop": atr_vs,
            "summary": f"{state} entry{zone}{atr_note}".strip(),
            "evaluated_at": str(r.get("evaluated_at") or ""),
        })
    return out[:limit]


def _watchlist_buy_conviction_rows(limit: int = 40) -> List[dict]:
    """Buy and strong-buy watchlist names. Not the whole watchlist. [] if the DB is down."""
    try:
        from lib.options_pipeline.universe import (
            _fetch_watchlist_buy_rows,
            _normalize_verdict,
        )
    except Exception:
        return []
    out: List[dict] = []
    for row in _fetch_watchlist_buy_rows():
        verdict = _normalize_verdict(row.get("card_rec")) or _normalize_verdict(row.get("synth_rec"))
        if not verdict:
            continue
        sym = str(row.get("symbol") or "").upper()
        if not sym or not sym.isalpha() or len(sym) > 6:
            continue
        out.append({
            "symbol": sym,
            "source": "watchlist_buy_strong_buy",
            "confidence": 0.64 if verdict == "strong_buy" else 0.60,
            "summary": f"watchlist {verdict.replace('_', ' ')}",
            "verdict": verdict,
        })
        if len(out) >= limit:
            break
    return out


def _researched_watchlist_rows(limit: Optional[int] = None) -> List[dict]:
    """All active/researched watchlist names, not only BUY/STRONG_BUY.

    This is intentionally separate from the legacy conviction resolver.  A
    researched neutral or bearish name can be useful for puts and hedges; the
    deterministic strategy gates decide whether an option is admissible.
    """
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            SOURCE_RECEIPTS["watchlist"] = {"status": "UNAVAILABLE", "reason": "database unavailable"}
            return []
        # 2026-09-27: this query selected wi.catalyst_headline / wi.catalyst_at, columns
        # watchlist_items never had; the error was swallowed below and the lane contributed
        # 0 of ~2,700 eligible names to the desk since 09-25. Catalysts live in
        # catalyst_events (latest headline per symbol); the failure is now logged, not hidden.
        rows = _execute(
            """SELECT DISTINCT ON (upper(wi.symbol))
                      upper(wi.symbol) AS symbol,
                      rc.latest_recommendation AS card_rec,
                      fs.recommendation AS synth_rec,
                      wi.hermes_composite_score,
                      ce.headline AS catalyst_headline,
                      ce.published_at AS catalyst_at,
                      rc.updated_at AS research_card_at,
                      fs.updated_at AS synthesis_at
                 FROM watchlist_items wi
                 LEFT JOIN watchlist_research_cards rc ON upper(rc.symbol) = upper(wi.symbol)
                 LEFT JOIN watchlist_final_synthesis fs ON upper(fs.symbol) = upper(wi.symbol)
                 LEFT JOIN LATERAL (
                      SELECT headline, published_at FROM catalyst_events c
                       WHERE upper(c.symbol) = upper(wi.symbol)
                       ORDER BY c.published_at DESC NULLS LAST, c.created_at DESC
                       LIMIT 1
                 ) ce ON TRUE
                WHERE wi.status IN ('active', 'researched')
                ORDER BY upper(wi.symbol), GREATEST(
                  COALESCE(fs.updated_at, 'epoch'::timestamp),
                  COALESCE(rc.updated_at, 'epoch'::timestamp),
                  COALESCE(ce.published_at, 'epoch'::timestamptz)
                ) DESC NULLS LAST
                LIMIT %s""",
            (limit,), fetch="all",
        )
        if rows is None:
            raise RuntimeError("watchlist query did not return a result")
    except Exception as e:  # noqa: BLE001 -- a lane that cannot read says so
        print(f"[options_engine] researched-watchlist lane unavailable: {type(e).__name__}: {str(e)[:160]}", file=sys.stderr)
        INCOME_SCREEN_DROPS.append({"symbol": "*", "strategy": "*", "reason": "RESEARCH_LANE_UNAVAILABLE",
                                    "detail": f"{type(e).__name__}: {str(e)[:160]}"})
        SOURCE_RECEIPTS["watchlist"] = {"status": "UNAVAILABLE", "reason": type(e).__name__}
        return []
    SOURCE_RECEIPTS["watchlist"] = {"status": "COMPLETE", "rows": len(rows), "as_of": _iso()}
    out: List[dict] = []
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            continue
        verdict = row.get("synth_rec") or row.get("card_rec")
        out.append({
            "symbol": sym,
            "source": "watchlist",
            "source_lanes": ["watchlist"],
            "research_status": "researched" if verdict or row.get("catalyst_headline") else "research_required",
            "research_artifact_id": f"watchlist:{sym}" if verdict or row.get("catalyst_headline") else None,
            "verdict": verdict,
            "summary": row.get("catalyst_headline") or f"researched watchlist name ({verdict or 'unresolved'})",
            "catalyst": row.get("catalyst_headline"),
            "research_as_of": row.get("synthesis_at") or row.get("research_card_at") or row.get("catalyst_at"),
            "confidence": None,  # a research quality score is not directional conviction
            "research_quality_score": row.get("hermes_composite_score"),
        })
    return out


def _reentry_research_rows(limit: Optional[int] = None) -> List[dict]:
    """Read-only re-entry research lane for former holdings and exit reviews."""
    try:
        from lib.options_research_universe import reentry_research_rows
        snapshot = _load_json(PROJECT_ROOT / "data" / "runtime" / "reentry_decision_desk_latest.json") or {}
        rows = reentry_research_rows(snapshot)[:limit]
        # The dashboard projection is capped. Read complete membership from the same
        # authoritative preference/exit sources, without invoking its quote-producing builder.
        from db_adapter import _execute, USE_DB
        from lib.data_broker.reentry_decision_desk import RESISTANCE_KEY
        if not USE_DB:
            raise RuntimeError("reentry membership database unavailable")
        prefs = _execute("SELECT value FROM ui_prefs WHERE key=%s", (RESISTANCE_KEY,), fetch="all")
        if prefs is None:
            raise RuntimeError("reentry preference query did not return a result")
        pref = prefs[0] if prefs else {}
        exits = _execute("""SELECT DISTINCT upper(symbol) AS symbol FROM trade_transactions
            WHERE trade_date >= CURRENT_DATE - 365
              AND (lower(coalesce(action,'')) IN
                ('sell','sold','assigned','assignment','expired','exercise','exercised','close','closed')
                OR lower(coalesce(action,'')) LIKE 'sell%%') ORDER BY 1""", fetch="all")
        if exits is None:
            raise RuntimeError("reentry exit query did not return a result")
        value = (pref or {}).get("value") or {}
        if isinstance(value, str):
            value = json.loads(value)
        symbols = set((value.get("symbols") or {}).keys())
        symbols.update(r['symbol'] for r in exits if r.get('symbol'))
        known = {r['symbol'] for r in rows}
        rows.extend({'symbol': str(s).upper(), 'source': 'reentry', 'source_lanes': ['reentry'],
                     'research_status': 'research_required'} for s in sorted(symbols)
                    if str(s).upper() not in known)
        rows = rows[:limit]
        SOURCE_RECEIPTS["reentry"] = {"status": "COMPLETE" if limit is None else "PARTIAL",
            "rows": len(rows), "membership_as_of": _iso(),
            "as_of": snapshot.get("computed_at") or snapshot.get("as_of") or snapshot.get("generated_at"),
            "research_snapshot_rows": len(snapshot.get("rows") or []),
            "membership_basis": "reentry resistance preference plus 365-day exit ledger; uncapped"}
    except Exception as exc:
        SOURCE_RECEIPTS["reentry"] = {"status": "UNAVAILABLE", "reason": type(exc).__name__}
        rows = locals().get('rows', [])
    # Overlay shared spine summaries onto reentry rows (CADI-012).
    try:
        from lib.cross_asset.hooks import overlay_thesis_fields_from_spine
    except Exception:
        try:
            from scripts.lib.cross_asset.hooks import overlay_thesis_fields_from_spine
        except Exception:
            return rows
    out = []
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            out.append(row)
            continue
        fields = overlay_thesis_fields_from_spine(
            {"thesis_summary": row.get("summary"), "thesis_state": row.get("research_status")},
            sym,
            root=PROJECT_ROOT,
            silo="reentry",
        )
        enriched = dict(row)
        if fields.get("security_research_spine") and fields.get("thesis_summary"):
            enriched["summary"] = fields["thesis_summary"]
            enriched["research_status"] = "researched"
            enriched.setdefault("source_lanes", [])
            lanes = set(enriched.get("source_lanes") or [])
            lanes.add("cio_research")
            lanes.add("security_research_spine")
            enriched["source_lanes"] = sorted(lanes)
            if fields.get("source_refs"):
                enriched["research_artifact_id"] = fields["source_refs"][0]
        out.append(enriched)
    return out


def _research_universe_rows() -> List[dict]:
    """Union all research-qualified option underlyings and retain source lanes."""
    from lib.options_research_universe import merge_research_rows

    rows: List[dict] = []
    # CADI-012: CIO spine first so merge_research_rows first-wins keeps shared thesis.
    try:
        from lib.cross_asset.hooks import spine_rows_for_root
        rows.extend(spine_rows_for_root(PROJECT_ROOT, limit=0))
    except Exception:
        try:
            from scripts.lib.cross_asset.hooks import spine_rows_for_root
            rows.extend(spine_rows_for_root(PROJECT_ROOT, limit=0))
        except Exception:
            pass
    rows.extend(_high_conviction_symbols())
    rows.extend(_watchlist_buy_conviction_rows())
    rows.extend(_researched_watchlist_rows())
    rows.extend(_reentry_research_rows())
    merged = merge_research_rows(rows)
    return merged  # membership is independent of research/approval readiness


def _high_conviction_symbols(limit: int = 25) -> List[dict]:
    """Layer 4 + fused signals + Aegis CC candidates + Stage 1E entry_state."""
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
    # Operator-starred symbols (2026-07-17): a star is the operator's own conviction signal —
    # it now ALWAYS enters the options scan universe (was: inference/fused/action signals only,
    # so starred names never got option plays unless something else also flagged them).
    try:
        from db_adapter import _execute as _star_q
        starred = _star_q(
            """SELECT symbol FROM operator_starred_symbols
               ORDER BY starred_at DESC LIMIT 15""",
            fetch="all") or []
        for r in starred:
            sym = (r.get("symbol") or "").upper()
            if sym and sym not in out and sym.isalpha() and len(sym) <= 6:
                out[sym] = {
                    "symbol": sym,
                    "source": "operator_starred",
                    "confidence": 0.62,
                    "summary": "operator-starred watchlist name",
                }
    except Exception:
        pass

    # Stage 1E — BUY_READY / ENTRY_NEAR win over weaker sources; reserve slots so V/AXTI
    # are not truncated by layer4 noise.
    entry_rows = _entry_state_conviction_symbols(limit=ENTRY_STATE_CONVICTION_RESERVE)
    for er in entry_rows:
        sym = er["symbol"]
        prior = out.get(sym)
        if prior:
            sources = list({prior.get("source"), "entry_state"} - {None})
            er = {
                **prior,
                **er,
                "sources": sources,
                "source": "entry_state",
                "confidence": max(_f(prior.get("confidence"), 0.0), _f(er.get("confidence"), 0.62)),
            }
        out[sym] = er

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

    entry_first = [v for v in out.values() if v.get("source") == "entry_state"]
    others = [v for v in out.values() if v.get("source") != "entry_state"]
    merged = entry_first[:ENTRY_STATE_CONVICTION_RESERVE] + others
    return merged[:limit]


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


# One chain read per (symbol, width) per generation pass: the IV lookup and the
# contract picker share it, so reading IV from the chain costs no extra call.
_CHAIN_CACHE: Dict[tuple, dict] = {}
_SCAN_CHAINS = None  # immutable lazy mapping supplied only during worker projection


def _schwab_chain(symbol: str, strikes: int = 12) -> dict:
    if _SCAN_CHAINS is not None:
        return _SCAN_CHAINS.get(symbol.upper(), {"status": "pending"})
    key = (symbol.upper(), int(strikes))
    if (symbol.upper(), 0) in _CHAIN_CACHE:
        return _CHAIN_CACHE[(symbol.upper(), 0)]
    if key in _CHAIN_CACHE:
        return _CHAIN_CACHE[key]
    try:
        import schwab_transport
        out = schwab_transport.get_option_chain(symbol.upper(), strike_count=strikes) or {}
    except Exception as e:
        out = {"status": "error", "error": str(e)[:120]}
    _CHAIN_CACHE[key] = out
    return out


def _chain_fetched_at(symbol: str) -> Optional[str]:
    """When the cached chain for ``symbol`` was read (normalize_option_chain stamps it)."""
    if _SCAN_CHAINS is not None:
        return (_SCAN_CHAINS.get(symbol.upper()) or {}).get("fetched_at")
    for (sym, _n), out in _CHAIN_CACHE.items():
        if sym == symbol.upper() and isinstance(out, dict) and out.get("fetched_at"):
            return out["fetched_at"]
    return None


def _chain_atm_iv_pct(chain: dict, price: float) -> Optional[float]:
    """Median IV (percent) of the contracts nearest the money, 14-60 DTE."""
    if not chain or price <= 0:
        return None
    vals: List[tuple] = []
    for exp in chain.get("expirations") or []:
        dte = int(exp.get("dte") or 0)
        if dte < 14 or dte > 60:
            continue
        for row in exp.get("strikes") or []:
            iv = _f(row.get("iv"))
            k = _f(row.get("strike"))
            if iv > 0 and k > 0:
                vals.append((abs(k - price) / price, iv if iv > 3 else iv * 100.0))
    if not vals:
        return None
    vals.sort()
    near = sorted(v for _, v in vals[:6])
    return round(near[len(near) // 2], 2)


def _pick_chain_contract(
    chain: dict,
    side: str,
    target_strike: float,
    target_dte: int,
    *,
    target_abs_delta: Optional[float] = None,
) -> Optional[dict]:
    """Nearest DTE/strike with a preference for two-sided liquid quotes.

    Stage B (2026-09-25): proximity alone once preferred a zero-bid / 100% spread
    row and stamped absurd enterprise blocks. Among contracts near the target,
    prefer real bid/ask and tighter spread — do NOT widen max_spread_pct.
    """
    if chain.get("status") not in (None, "ok") and "expirations" not in chain:
        return None
    candidates: List[tuple] = []
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
            two_sided = bid > 0 and ask > bid
            spread_pct = (
                100.0 * (ask - bid) / mid if two_sided and mid > 0 else 999.0
            )
            proximity = abs(strike - target_strike) + abs(dte - target_dte) * 0.15
            oi = None if row.get("oi") is None else int(_f(row.get("oi")))
            vol = int(_f(row.get("volume")))
            delta = _f(row.get("delta"))
            if target_abs_delta and delta:
                # Strike by delta when the chain carries it; strike units keep the DTE weight comparable.
                proximity = abs(abs(delta) - target_abs_delta) * max(abs(target_strike), 1.0) + abs(dte - target_dte) * 0.15
            contract = {
                "exp": exp.get("exp"),
                "dte": dte,
                "strike": strike,
                "bid": bid,
                "ask": ask,
                "mid": round(mid, 2),
                "iv": _f(row.get("iv")) / 100.0 if _f(row.get("iv")) > 3 else _f(row.get("iv")),
                "delta": delta,
                "oi": oi,
                "volume": vol,
                "bid_ask_spread_pct": round(spread_pct, 2) if spread_pct < 900 else None,
                # Fill truth (2026-09-27): keep what the chain said, and when it said it.
                "last": _f(row.get("last")) if row.get("last") is not None else None,
                "mark": _f(row.get("mark")) if row.get("mark") is not None else None,
                "quote_time": row.get("quote_time"),
                "multiplier": row.get("multiplier", 100),
                "nonstandard": row.get("nonstandard", False),
            }
            if contract["nonstandard"] or _f(contract["multiplier"], 100) != 100:
                continue  # legacy policy supports standard 100-share deliverables only
            # sort key: proximity, then spread, then prefer higher OI
            candidates.append((proximity, spread_pct, -(oi or 0), contract))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1], t[2]))
    # 2026-09-26: prefer a contract the enterprise liquidity gate can pass, within a
    # configured distance of the target, before falling back to raw proximity.
    try:
        from lib.options_income_quality import is_liquid, setting
        cfg = _desk_cfg()
        slack = abs(target_strike) * float(setting(cfg, "picker_strike_slack_pct")) / 100.0
        best = candidates[0][0]
        liquid_near = [c for c in candidates if c[0] <= best + max(slack, 1.0) and is_liquid(c[3], cfg)]
        if liquid_near:
            return liquid_near[0][3]
    except Exception:
        pass
    best_prox = candidates[0][0]
    # Within ~2% of underlying (or $1 floor) of the nearest strike, prefer liquidity.
    strike_slack = max(1.0, abs(target_strike) * 0.02)
    near = [c for c in candidates if c[0] <= best_prox + strike_slack]
    liquid = [c for c in near if c[1] < 900.0]
    pool = liquid if liquid else near
    return pool[0][3]


def _edge_score(
    pop: float,
    iv_rank: float,
    rr: float,
    catalyst_boost: float = 0.0,
    conviction: float = 0.0,
    yield_ann_pct: Optional[float] = None,
) -> float:
    """0–100 composite edge for credit/income strategies.

    ``yield_ann_pct`` (covered calls, 2026-09-26): the premium's annualized yield
    on the covered shares, scored on the configured scale (full 20 points at
    ``edge_roc_full_credit_ann_pct``). The old ``rr * 25`` term gave SPCX's
    $4.10 / 27-day call on a $148.57 stock -- ~37% annualized -- under 2 of 20
    points, so no covered call could clear 62 on premium.
    """
    pop_s = min(100.0, max(0.0, pop)) * 0.35
    iv_s = min(100.0, iv_rank) * 0.20
    if yield_ann_pct is not None:
        from lib.options_income_quality import roc_score
        rr_s = roc_score(float(yield_ann_pct), _desk_cfg(), 20.0)
    else:
        rr_s = min(100.0, rr * 25.0) * 0.20
    cat_s = min(15.0, catalyst_boost)
    conv_s = min(10.0, conviction * 10.0)
    return round(pop_s + iv_s + rr_s + cat_s + conv_s, 1)


def _cc_yield_ann_pct(premium: float, underlying: float, dte: int) -> float:
    """Covered-call premium as an annualized % of the covered shares' value."""
    if premium <= 0 or underlying <= 0:
        return 0.0
    return (premium / underlying) * (365.0 / max(int(dte or 0), 1)) * 100.0


def _conviction_bias(c: dict) -> str:
    from lib.options_research_universe import conviction_bias
    return conviction_bias(c)


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
    from lib.options_income_quality import roc_score
    roc_s = roc_score(ann, _desk_cfg(), 28.0)
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


# Where each symbol's spot came from on this pass (shown on the card).
_PRICE_SOURCE: Dict[str, dict] = {}
_SESSION: dict = {}  # market session for this run (weekend-aware liquidity, 2026-09-27)
LIQUIDITY_DEFERRED: list = []  # ideas kept despite closed-market quotes, for the funnel
_FUNDAMENTALS: dict = {}  # per-run cache of fundamentals card blocks (F5)
_INSTRUMENT_CLASS: dict = {}  # per-run cache: OPERATING_COMPANY | ETF | LEVERAGED_FUND


def _spot_for(sym: str, price: float) -> float:
    """The option's own spot: the Schwab chain's underlying when present, else ``price``."""
    try:
        cu = _f((_schwab_chain(sym, strikes=16) or {}).get("underlying_price"))
    except Exception:
        cu = 0.0
    if cu > 0:
        _PRICE_SOURCE[sym.upper()] = {"source": "schwab_chain_underlying", "as_of": _iso(),
                                      "replaced": round(price, 2) if price and abs(cu / price - 1) > 0.005 else None}
        return cu
    return price


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
    # 2026-09-26: DELL priced at $524.14 from a scanner row dated 2026-09-05 while
    # market_quotes had $563.28 at the 09-25 close. Take the FRESHEST dated price
    # of scan vs quote, and refuse one older than price_max_age_hours.
    try:
        from db_adapter import _execute, USE_DB
        if USE_DB:
            cands = []
            row = _execute(
                """SELECT price, scanned_at AS at FROM trade_ai_scans
                   WHERE symbol=%s AND price IS NOT NULL AND price > 0
                   ORDER BY scanned_at DESC LIMIT 1""", (sym,), fetch="one")
            if row and _f(row.get("price")) > 0:
                cands.append(("trade_ai_scans", _f(row["price"]), row.get("at")))
            row = _execute(
                """SELECT price, fetched_at AS at FROM market_quotes
                   WHERE symbol=%s AND price IS NOT NULL AND price > 0
                   ORDER BY fetched_at DESC LIMIT 1""", (sym,), fetch="one")
            if row and _f(row.get("price")) > 0:
                cands.append(("market_quotes", _f(row["price"]), row.get("at")))
            cands = [c for c in cands if c[2] is not None]
            if cands:
                src, px, at = max(cands, key=lambda c: c[2])
                max_age_h = float(_desk_cfg().get("price_max_age_hours") or 96)
                age_h = (_now() - (at if at.tzinfo else at.replace(tzinfo=timezone.utc))).total_seconds() / 3600.0
                if age_h <= max_age_h:
                    _PRICE_SOURCE[sym] = {"source": src, "as_of": at.isoformat(), "age_hours": round(age_h, 1)}
                    return px
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
    """Order every proposal; display limits must never erase evaluated candidates."""
    return sorted(proposals, key=lambda p: (
        bool((p.get("enterprise") or {}).get("blocks")) or p.get("approvable") is not True,
        -_f(p.get("edge_score")), str(p.get("strategy") or ""), str(p.get("id") or ""),
    ))


def _proposal_id(strategy: str, sym: str, account: str, strike: Any, expiration: str = "",
                 trade_date: str = "", long_strike: Any = None) -> str:
    """Stable WITHIN A TRADE DATE so ensemble verdicts persist across rescans."""
    acct = re.sub(r"[^a-z0-9]+", "_", (account or "default").lower()).strip("_")[:22]
    exp = (expiration or "")[:10].replace("-", "")
    try:
        st = f"{float(strike):.4f}".replace(".", "p")
    except (TypeError, ValueError):
        st = str(strike or "0").replace(".", "p")
    # Order gates (2026-09-27): a spread's id named only the SHORT strike, so a changed
    # long leg kept the same proposal_id and inherited its approved queue row.
    if long_strike is not None:
        try:
            st += "_l" + f"{float(long_strike):.4f}".replace(".", "p")
        except (TypeError, ValueError):
            st += "_l" + str(long_strike).replace(".", "p")
    # DATE-SCOPED (2026-07-20). The id was globally stable, so a contract that
    # once reached a TERMINAL queue status could never be proposed again: the
    # deterministic id collided with the old row and the upsert preserves
    # terminal statuses. A July-6 RTX row stuck in ALPACA_PAPER_REJECTED (an
    # expired DAY order, not a judgement on the trade) blocked the 2026-07-20
    # canary at the pick step with "no fresh pending proposal".
    # Scoping by TRADE DATE keeps the original purpose — ids stay stable within
    # a session so rescans are idempotent and ensemble verdicts persist — while
    # letting a new day propose the same contract on a fresh row. Old rows are
    # retained as evidence rather than mutated.
    day = (trade_date or _dt.datetime.now().strftime("%Y%m%d")).replace("-", "")[:8]
    base = f"opt_{strategy}_{sym.upper()}_{acct}_{st}_{exp}"
    # Reserve room for the suffix so truncation can never drop the date scope.
    return f"{base[:61]}_d{day}"[:72]


def _proposal_ensemble_content(p: dict) -> str:
    """Payload for the Aegis review: the proposal plus the house's deterministic facts and memory.

    2026-09-26 (operator): reviewers must judge against the thesis the house holds
    (pin, evidence, counter-evidence, invalidation), the stored options-thesis
    version and the plain-English outcomes -- not the trade numbers alone.
    """
    lines = [
        f"OPTIONS PROPOSAL — {p.get('strategy', '').replace('_', ' ')}",
        f"Symbol: {p.get('symbol')} · Account: {p.get('account') or '—'}",
        f"Strike: ${p.get('strike')} · Expiration: {p.get('expiration')} · DTE: {p.get('dte')}",
        f"Contracts: {p.get('contracts')} · Premium/contract: ${p.get('premium')} · "
        f"{'Total debit (you pay)' if p.get('strategy') in DEBIT_STRATEGIES or p.get('strategy') == 'long_put' else 'Total credit (you collect)'}: ${p.get('premium_total')}",
        f"Spot: ${p.get('underlying_price')} · POP: {p.get('pop_pct')}% · Edge: {p.get('edge_score')}",
        f"IV rank: {p.get('iv_rank')}% · R:R: {p.get('risk_reward')} · EV: ${p.get('expected_value')}",
        f"Breakeven: ${p.get('breakeven')} · Max profit: {p.get('max_profit')} · Stock risk: {p.get('stock_downside_risk') or p.get('max_loss')}",
        f"Upside cap: {p.get('upside_cap') or '—'} · Data: {p.get('data_source') or '—'}",
    ]
    if p.get("aegis_note"):
        lines.append(f"Aegis screening: {p['aegis_note']}")
    if p.get("reasoning"):
        lines.append(f"Engine notes: {p['reasoning']}")
    memo = p.get("committee_memo") or {}
    ot = p.get("options_thesis") or {}
    if memo and not memo.get("error"):
        lines += [
            "HOUSE FACTS (deterministic, from stored memory):",
            f"Classification: {memo.get('classification_label')} · Research: {memo.get('research_status')} · Confidence: {memo.get('confidence')}",
            f"Symbol thesis {p.get('thesis_version_at_decision') or 'none'} ({p.get('thesis_state') or 'unknown'}): {memo.get('investment_thesis')}",
            f"Counter-evidence: {memo.get('contrarian_view')}",
            f"Why now: {memo.get('why_now')}",
            f"Thesis invalid when: {'; '.join((memo.get('exit_plan') or {}).get('thesis_invalid_when') or [])}",
            f"Options thesis {ot.get('pin') or 'not stored'}; missing: {', '.join(ot.get('missing_required') or []) or 'none'}",
        ]
    pe = p.get("plain_english") or {}
    if pe:
        lines.append(f"Plain English: {pe.get('objective')} {pe.get('premium_line')} {pe.get('breakeven_line')}")
    lines.append("Judge only against these facts; name any missing fact rather than assume it.")
    return "\n".join(lines)[:4000]


def _options_ensemble_lanes() -> Optional[str]:
    """Options review lanes from config/inference_layers.yaml ensemble.options_lanes (JSON for the job row)."""
    try:
        import yaml
        cfg = yaml.safe_load((PROJECT_ROOT / "config" / "inference_layers.yaml").read_text()) or {}
        lanes = ((cfg.get("inference_layers") or cfg).get("ensemble") or {}).get("options_lanes")
        return json.dumps(list(lanes)) if lanes else None
    except Exception:
        return None


def enqueue_ensemble_for_proposals(proposals: List[dict], fresh_hours: int = 24) -> dict:
    """Enqueue Aegis review jobs for options proposals (idempotent); lanes from options_lanes."""
    try:
        from db_adapter import _get_conn, USE_DB
        if not USE_DB:
            return {"ok": False, "error": "db disabled", "enqueued": 0, "skipped": len(proposals)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120], "enqueued": 0, "skipped": len(proposals)}

    conn = _get_conn()
    cur = conn.cursor()
    enqueued = skipped = 0
    lanes_json = _options_ensemble_lanes()
    from lib.options_thesis_lifecycle import settings as lifecycle_settings
    budget = int(lifecycle_settings(_desk_cfg())["max_reviews_per_run"])
    for p in sorted(proposals, key=lambda row: str(row.get("last_review_at") or row.get("generated_at") or "")):
        if p.get("advisory_only") or enqueued >= budget:
            skipped += 1
            continue
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
               (target_type, target_id, subject, content, task, requested_by, status, lanes)
               VALUES ('options_proposal', %s, %s, %s, 'options_proposal_quality', 'options_engine', 'queued', %s::jsonb)""",
            (tid, subject[:300], content, lanes_json),
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


# Operator options intents (2026-10-05). The generic covered-call screen proposed SPCX $185C while the
# operator's standing plan says covered calls must keep the run toward $300 (spec.options_intent on
# the SPCX ticker directive). An active intent's covered-call floor now binds this generator. Fail-
# open to the generic rules only when no intent can be read (never invents a floor).
_INTENT_CC_FLOORS: Optional[Dict[str, Any]] = None


def _intent_cc_floors() -> Dict[str, Any]:
    global _INTENT_CC_FLOORS
    if _INTENT_CC_FLOORS is None:
        floors: Dict[str, Any] = {}
        try:
            from lib.options_intent import store as _ois
            from db_adapter import _execute
            for r in _execute(_ois.SELECT_SQL, None, fetch="all") or []:
                spec = r.get("spec") if isinstance(r, dict) else None
                spec = json.loads(spec) if isinstance(spec, str) else (spec or {})
                it = spec.get(_ois.INTENT_KEY) or {}
                cc = (it.get("plays") or {}).get("covered_call")
                if it.get("status", "active") == "active" and it.get("symbol"):
                    floors[str(it["symbol"]).upper()] = {"covered_call": cc, "thesis_target": it.get("thesis_target"),
                                                         "directive_id": r.get("id") if isinstance(r, dict) else None}
        except Exception:
            floors = {}
        _INTENT_CC_FLOORS = floors
    return _INTENT_CC_FLOORS


def _intent_blocks_covered_call(sym: str, strike: float, spot: float) -> Optional[str]:
    """Reason string when an operator intent forbids this covered-call strike, else None."""
    it = _intent_cc_floors().get(sym.upper())
    if not it:
        return None
    if it.get("covered_call") is None:
        return f"operator options intent #{it.get('directive_id')} has no covered-call play for {sym}"
    from lib.options_intent.ranking import cc_strike_floor
    floor = cc_strike_floor(it["covered_call"], spot=spot, thesis_target=it.get("thesis_target"))
    if floor is not None and strike < floor:
        return (f"operator options intent #{it.get('directive_id')}: covered calls on {sym} must be at or above "
                f"${floor:g} (thesis target ${it.get('thesis_target')})")
    return None


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
        if h.get("is_cash"):
            continue  # cash sweep lines (is_cash) are not optionable equities
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

        from lib.options_income_quality import setting as _qs
        contract, data_source = _resolve_option_contract(
            sym, price, tech, "call", target_strike, default_dte,
            target_abs_delta=float(_qs(_desk_cfg(), "cc_target_delta")),
        )
        if not contract or _income_screen("covered_call", sym, contract, data_source, _f(price)):
            continue
        premium = contract["mid"]
        strike = contract["strike"]
        dte = contract["dte"]
        if _intent_blocks_covered_call(sym, _f(strike), _f(price)):
            continue  # the operator's standing intent overrides the generic strike choice
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
            yield_ann_pct=_cc_yield_ann_pct(premium, und, dte),
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
        acct = _canonical_account(h)
        proposals.append(_stamp_execution({
            "id": _proposal_id("covered_call", sym, acct, strike, exp),
            "strategy": "covered_call",
            "symbol": sym,
            "underlying": sym,
            "account": acct,
            "account_display": h.get("account_display"),
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
            "iv_used": round(float(iv), 4) if iv else None,
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
            "volume": contract.get("volume") if contract else None,
            "bid": contract.get("bid") if contract else None,
            "ask": contract.get("ask") if contract else None,
            "bid_ask_spread_pct": contract.get("bid_ask_spread_pct") if contract else None,
            "quote_time": contract.get("quote_time") if contract else None,
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
        }, acct, holdings))
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
        und = price = _spot_for(sym, price)
        iv_rank = _iv_rank_proxy(sym, tech, chain_lookup=True, price=price)
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
        proposals.append(_stamp_execution({
            "id": _proposal_id("protective_put", sym, acct, strike, contract.get("exp") or ""),
            "strategy": "protective_put",
            "symbol": sym,
            "underlying": sym,
            "account": acct,
            "account_display": h.get("account_display"),
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
            "iv_used": round(float(iv), 4) if iv else None,
            "shares_held": round(float(shares), 3) if shares else None,
            "max_profit": "hedge",
            "max_loss": cost,
            "breakeven": round(strike - premium, 2),
            "risk_reward": round(mv / max(cost, 1), 2),
            "expected_value": round(-cost * 0.5, 2),
            "edge_score": edge,
            "iv_rank": iv_rank,
            "delta": contract.get("delta"),
            "oi": contract.get("oi"),
            "volume": contract.get("volume"),
            "bid": contract.get("bid"),
            "ask": contract.get("ask"),
            "bid_ask_spread_pct": contract.get("bid_ask_spread_pct"),
            "quote_time": contract.get("quote_time"),
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
        }, acct, holdings))

    proposals.sort(key=lambda x: -x["edge_score"])
    return proposals


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
    account: str = "",
    holdings: Optional[List[dict]] = None,
    cash_map: Optional[Dict[str, float]] = None,
) -> Optional[str]:
    """Append a long_call proposal. Returns None on success, else a named drop reason."""
    premium = contract["mid"]
    strike, dte, iv = contract["strike"], contract["dte"], contract.get("iv") or 0.3
    pop = 100.0 - _pop_otm_call(und, strike, max(0.05, iv), dte)
    max_loss = round(premium * 100, 2)
    breakeven = round(strike + premium, 2)
    rr = premium * 100 / max(strike * 100, 1)
    edge = _edge_score_debit(pop=pop, iv_rank=iv_rank, hedge_ratio=0.5, conviction=conf, dte=dte)
    min_edge = MIN_EDGE_CONVICTION - 8 if conf >= 0.65 else MIN_EDGE_CONVICTION - 3
    if edge < min_edge:
        return "EDGE_BELOW"
    acct = account or _auto_select_account(sym, holdings or [], strategy="long_call", cash_map=cash_map)
    from_entry = "entry_state" in set(c.get("source_lanes") or [c.get("source")])
    vol_elevated = bool(c.get("volatility_elevated"))
    entry_state = c.get("entry_state")
    tech_note = f"Conviction {conf:.0%}"
    if from_entry and entry_state:
        tech_note = (
            f"{entry_state} defined-risk expression (stock-replacement / capital-efficient add)"
        )
        if vol_elevated:
            tech_note += (
                " · elevated ATR vs distance-to-stop prefers options vs full equity"
            )
    row = _stamp_execution({
        "id": _proposal_id("long_call", sym, acct, strike, contract.get("exp") or ""),
        "strategy": "long_call",
        "symbol": sym,
        "underlying": sym,
        "account": acct,
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
        "iv_used": round(float(iv), 4) if iv else None,
        "max_profit": "unlimited",
        "max_loss": max_loss,
        "breakeven": breakeven,
        "risk_reward": round(rr, 3),
        "expected_value": round(premium * 100 * (pop / 100.0) * -1, 2),
        "edge_score": edge,
        "iv_rank": iv_rank,
        "delta": contract.get("delta"),
        "quote_time": contract.get("quote_time"),
        "bid": contract.get("bid"), "ask": contract.get("ask"),
        "oi": contract.get("oi"), "volume": contract.get("volume"),
        "bid_ask_spread_pct": contract.get("bid_ask_spread_pct"),
        "multiplier": contract.get("multiplier", 100),
        "non_standard": contract.get("nonstandard", False),
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
            "technical": tech_note,
        }),
        "quality_pass": True,
        "data_source": data_source,
        "execution_note": _execution_note(),
        "generated_at": _iso(),
    }, acct, holdings)
    if from_entry:
        row["conviction_source"] = "entry_state"
        row["entry_state"] = entry_state
        row["entry_zone"] = {
            "low": c.get("entry_low"),
            "high": c.get("entry_high"),
        }
        row["atr"] = c.get("atr")
        row["volatility_elevated"] = vol_elevated
        if c.get("atr_vs_distance_to_stop") is not None:
            row["atr_vs_distance_to_stop"] = c.get("atr_vs_distance_to_stop")
        row["stop"] = c.get("stop")
        row["target"] = c.get("target")
    proposals.append(row)
    return None


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
    account: str = "",
    holdings: Optional[List[dict]] = None,
    cash_map: Optional[Dict[str, float]] = None,
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
    acct = account or _auto_select_account(sym, holdings or [], strategy="cash_secured_put", cash_map=cash_map)
    proposals.append(_stamp_execution({
        "id": _proposal_id("cash_secured_put", sym, acct, strike, contract.get("exp") or ""),
        "strategy": "cash_secured_put",
        "symbol": sym,
        "underlying": sym,
        "account": acct,
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
        "iv_used": round(float(iv), 4) if iv else None,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakeven": breakeven,
        "risk_reward": round(rr, 3),
        "expected_value": round(premium * 100 * (pop / 100.0), 2),
        "edge_score": edge,
        "iv_rank": iv_rank,
        "delta": contract.get("delta"),
        "oi": contract.get("oi"),
        "volume": contract.get("volume"),
        "bid": contract.get("bid"),
        "ask": contract.get("ask"),
        "bid_ask_spread_pct": contract.get("bid_ask_spread_pct"),
        "quote_time": contract.get("quote_time"),
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
    }, acct, holdings))


def generate_defined_risk_proposals(
    convictions: List[dict],
    tech_map: dict,
    owned: set,
    holdings: Optional[List[dict]] = None,
    cash_map: Optional[Dict[str, float]] = None,
    out_entry_drops: Optional[List[dict]] = None,
) -> List[dict]:
    """Cash-secured puts + long calls on high-conviction names (not already full CC from same sleeve).

    Stage 1E: entry_state sources are exempt from the owned≥100 skip for long_call only
    (stock-replacement / held-add). Owned entry_state never opens a CSP on this path.
    Named drops for entry symbols (IV_BELOW / EDGE_BELOW / NO_CONTRACT / PRICE_ZERO).
    """
    proposals: List[dict] = []
    drops = out_entry_drops if out_entry_drops is not None else []

    def _drop_entry(c: dict, reason: str, **extra: Any) -> None:
        if "entry_state" not in set(c.get("source_lanes") or [c.get("source")]):
            return
        drops.append({
            "symbol": c.get("symbol"),
            "entry_state": c.get("entry_state"),
            "reason": reason,
            **extra,
        })

    for c in convictions:
        sym = c["symbol"]
        if _conviction_bias(c) in {"bearish", "conflict", "neutral"}:
            continue
        from_entry = "entry_state" in set(c.get("source_lanes") or [c.get("source")])
        # Owned ≥100 hard-skip — except entry_state long_call (V litmus).
        if sym in owned and not from_entry:
            continue
        tech = tech_map.get(sym) or {}
        price = _f(tech.get("price") or tech.get("last"))
        if price <= 0:
            price = _resolve_symbol_price(sym, tech_map, holdings or [])
        if price <= 0 and from_entry:
            price = _f(c.get("price") or c.get("entry_high") or c.get("entry_low"))
        if price <= 0:
            _drop_entry(c, "PRICE_ZERO")
            continue
        conf = _f(c.get("confidence"), 0.5)
        # Recompute ATR preference with tech atr when entry row lacked it.
        if from_entry and not c.get("volatility_elevated"):
            atr_v = _f(c.get("atr") or tech.get("atr"))
            stop_v = _f(c.get("stop"))
            try:
                from lib.cio_options_fluency import atr_volatility_elevated
                vol_e, atr_vs, _ = atr_volatility_elevated(
                    price=price, stop=stop_v if stop_v > 0 else None,
                    atr=atr_v if atr_v > 0 else None,
                )
                c = dict(c)
                c["volatility_elevated"] = bool(vol_e)
                c["atr_vs_distance_to_stop"] = atr_vs
                if atr_v > 0:
                    c["atr"] = atr_v
            except Exception:
                pass
        iv_rank = _iv_rank_proxy(sym, tech, chain_lookup=True, price=price)
        min_iv = MIN_IV_CONVICTION if conf >= 0.6 else MIN_IV_RANK
        if iv_rank < min_iv:
            _drop_entry(c, "IV_UNKNOWN" if iv_rank <= 0 else "IV_BELOW", iv_rank=iv_rank, min_iv=min_iv)
            if iv_rank <= 0:
                INCOME_SCREEN_DROPS.append({"symbol": sym, "strategy": "any", "reason": "IV_UNKNOWN"})
            continue

        und = price = _spot_for(sym, price)
        bias = _conviction_bias(c)
        owned_entry = from_entry and sym in owned

        if bias == "bullish" and conf >= 0.6:
            target_strike = round(und * 1.04 / 2.5) * 2.5 if und > 50 else round(und * 1.05, 1)
            contract, data_source = _resolve_option_contract(sym, und, tech, "call", target_strike, 35)
            if not contract:
                _drop_entry(c, "NO_CONTRACT")
                continue
            drop = _append_long_call_proposal(
                proposals, sym=sym, und=und, conf=conf, iv_rank=iv_rank,
                c=c, contract=contract, data_source=data_source,
                holdings=holdings, cash_map=cash_map,
            )
            if drop:
                _drop_entry(c, drop, edge_attempted=True)
        elif bias == "bullish" and conf >= 0.55 and not owned_entry and c.get("willing_to_own") is True:
            # entry_state + owned → long_call only; never CSP on a name already held ≥100.
            target_strike = round(und * 0.92 / 2.5) * 2.5 if und > 50 else round(und * 0.93, 1)
            from lib.options_income_quality import setting as _qs
            contract, data_source = _resolve_option_contract(
                sym, und, tech, "put", target_strike, 30,
                target_abs_delta=float(_qs(_desk_cfg(), "csp_target_abs_delta")),
            )
            reason = _income_screen("cash_secured_put", sym, contract, data_source, und)
            if reason:
                _drop_entry(c, reason)
            elif contract:
                _append_csp_proposal(
                    proposals, sym=sym, und=und, conf=conf, iv_rank=iv_rank,
                    c=c, contract=contract, data_source=data_source,
                    holdings=holdings, cash_map=cash_map,
                )
        elif from_entry:
            _drop_entry(c, "NOT_ACTIONABLE", bias=bias, confidence=conf)
    proposals.sort(key=lambda x: -x["edge_score"])
    return proposals


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
    if short_c and long_c and short_c.get("exp") == long_c.get("exp"):
        src = "schwab_chain" if src_s == "schwab_chain" and src_l == "schwab_chain" else "bs_estimate"
        return short_c, long_c, src
    return None, None, ""


def _leg_liq(contract, *, role, strike):
    from lib.options_exposure import leg_liquidity
    return leg_liquidity(contract, role=role, strike=strike)


def generate_credit_spread_proposals(
    convictions: List[dict],
    tech_map: dict,
    holdings: Optional[List[dict]] = None,
    cash_map: Optional[Dict[str, float]] = None,
) -> List[dict]:
    """Bull put / bear call credit spreads on high-conviction names (defined risk)."""
    proposals: List[dict] = []
    for c in convictions:
        if _conviction_bias(c) != "bullish":
            continue
        sym = c["symbol"]
        tech = tech_map.get(sym) or {}
        price = _f(tech.get("price") or tech.get("last"))
        if price <= 0:
            price = _resolve_symbol_price(sym, tech_map, holdings or [])
        if price <= 0:
            continue
        und = price = _spot_for(sym, price)
        conf = _f(c.get("confidence"), 0.5)
        if conf < 0.58:
            continue
        iv_rank = _iv_rank_proxy(sym, tech, chain_lookup=True, price=price)
        min_iv = MIN_IV_CONVICTION if conf >= 0.62 else MIN_IV_RANK
        if iv_rank < min_iv:
            continue
        # Bull put credit spread: sell higher strike put, buy lower strike put
        short_strike = round(und * 0.93 / 2.5) * 2.5 if und > 50 else round(und * 0.94, 1)
        long_strike = round(short_strike * 0.95 / 2.5) * 2.5 if und > 50 else round(short_strike * 0.96, 1)
        short_c, long_c, data_source = _resolve_spread_puts(sym, und, tech, short_strike, long_strike, 30)
        if not short_c or not long_c:
            continue
        # Operator 2026-09-27: the picker may settle on a nearby liquid strike; the card must
        # carry the strikes that were PRICED, not the targets.
        short_strike = _f(short_c.get("strike")) or short_strike
        long_strike = _f(long_c.get("strike")) or long_strike
        if long_strike >= short_strike:
            continue
        # Operator 2026-09-27: price from an explicit fill assumption. The advertised credit was
        # the leg-midpoint difference (DELL $8.10 vs $6.35 selling at bid / buying at ask; ETON
        # $0.89 while crossing the quotes was a $2.00 debit). A midpoint is not a fill.
        from lib.options_economics import spread_quote
        sq = spread_quote(short_c, long_c, session=_SESSION.get("now"),
                          quotes_as_of=(short_c.get("quote_time") or long_c.get("quote_time")
                                        or _chain_fetched_at(sym)))
        if data_source == "bs_estimate":
            # A modelled quote has no bid/ask worth crossing; keep the mid but say so.
            net_credit = sq["mid_credit"]
            sq["credit_basis"] = "midpoint"
            sq["executable_credit"] = None
        else:
            net_credit = sq["executable_credit"]
        if net_credit is None or net_credit <= 0:
            INCOME_SCREEN_DROPS.append({"symbol": sym, "strategy": "credit_spread", "reason": "NO_EXECUTABLE_CREDIT",
                                        "detail": (f"sell {short_strike:g}p at bid {sq['legs'][0]['bid']} - buy "
                                                   f"{long_strike:g}p at ask {sq['legs'][1]['ask']} = {sq['executable_credit']}"
                                                   f" (mid {sq['mid_credit']})"),
                                        "short_strike": short_strike, "long_strike": long_strike,
                                        "session": _SESSION.get("now")})
            continue
        net_credit = round(net_credit, 2)
        if net_credit < 0.08:
            continue
        width = short_strike - long_strike
        # 2026-09-26: ETON built a Tier A spread on OI 0 / 122% spread legs; the income
        # screen now covers spreads: both legs liquid, credit and return-on-risk floors.
        from lib.options_income_quality import defer_liquidity, is_liquid
        if not is_liquid(long_c, _desk_cfg()) and not defer_liquidity(_SESSION.get("now"), _desk_cfg()):
            INCOME_SCREEN_DROPS.append({"symbol": sym, "strategy": "credit_spread", "reason": "NO_LIQUID_CONTRACT",
                                        "strike": long_strike, "oi": long_c.get("oi")})
            continue
        if _income_screen("credit_spread", sym, {**short_c, "mid": net_credit, "spread_capital": width - net_credit},
                          data_source, und):
            continue
        max_loss = round((width - net_credit) * 100, 2)
        dte = int(short_c.get("dte") or 30)
        iv = max(0.05, short_c.get("iv") or _resolve_iv_decimal(und, tech, "put"))
        pop = _pop_otm_put(und, short_strike, iv, dte)
        rr = (net_credit * 100) / max(max_loss, 1)
        # Defined-risk credit spreads must clear the R:R floor before Ideas.
        # POP-heavy edge alone used to ship $66 credit / $1,184 risk as Tier A.
        try:
            import options_desk_enterprise as _ent_rr
            _rr_floor = float((_ent_rr.load_desk_config() or {}).get("min_credit_spread_rr") or 0.25)
        except Exception:
            _rr_floor = 0.25
        if _rr_floor > 0 and rr < _rr_floor:
            continue
        edge = _edge_score_wheel(
            pop, iv_rank, net_credit, width - net_credit, conviction=conf, dte=dte,
        )
        min_edge = MIN_EDGE_CONVICTION if conf >= 0.62 else MIN_EDGE_SCORE
        if edge < min_edge or pop < MIN_POP_PCT - 3:
            continue
        acct = _auto_select_account(sym, holdings or [], strategy="credit_spread", cash_map=cash_map)
        proposals.append(_stamp_execution({
            "id": _proposal_id("credit_spread", sym, acct, short_strike, short_c.get("exp") or "",
                               long_strike=long_strike),
            "strategy": "credit_spread",
            "symbol": sym,
            "underlying": sym,
            "account": acct,
            "option_type": "put",
            "short_strike": short_strike,
            "long_strike": long_strike,
            "strike": short_strike,
            "expiration": short_c.get("exp"),
            # Wave B 2026-09-27: a two-leg order has two quotes; show both.
            "legs_liquidity": [_leg_liq(short_c, role="short put", strike=short_strike),
                               _leg_liq(long_c, role="long put", strike=long_strike)],
            "dte": short_c["dte"],
            "contracts": 1,
            "premium": net_credit,
            "premium_total": round(net_credit * 100, 2),
            # Fill truth (operator 2026-09-27): what the credit is, and what it would be at mid.
            "net_credit": net_credit,
            "executable_credit": sq["executable_credit"],
            "mid_credit": sq["mid_credit"],
            "credit_basis": sq["credit_basis"],
            "credit_haircut": sq["credit_haircut"],
            "fill_assumption": sq["fill_assumption"],
            "spread_quote": sq,
            "quotes_as_of": sq["quotes_as_of"],
            "underlying_price": round(und, 2),
            "pop_pct": pop,
            "iv_used": round(float(iv), 4) if iv else None,
            "max_profit": round(net_credit * 100, 2),
            "max_loss": max_loss,
            "breakeven": round(short_strike - net_credit, 2),
            "max_profit_at_mid": (round(sq["mid_credit"] * 100, 2) if sq["mid_credit"] is not None else None),
            "max_loss_at_mid": (round((width - sq["mid_credit"]) * 100, 2) if sq["mid_credit"] is not None else None),
            "breakeven_at_mid": (round(short_strike - sq["mid_credit"], 2) if sq["mid_credit"] is not None else None),
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
        }, acct, holdings))
    proposals.sort(key=lambda x: -x["edge_score"])
    return proposals


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
                    # Pass through any Schwab-supplied margin/BP fields verbatim —
                    # never invent Reg-T. normalize_positions today does not emit these;
                    # if a future normalizer adds them, the monitor will stamp them.
                    row = {
                        "account_key": acct,
                        "occ_symbol": sym,
                        "qty": qty,
                        "side": side,
                        "avg_entry": _f(p.get("avg_entry_price")),
                        "market_value": _f(p.get("market_value")),
                        **parsed,
                    }
                    for _mk in (
                        "margin_requirement",
                        "maintenance_requirement",
                        "initial_requirement",
                        "buying_power_effect",
                        "bp_effect",
                        "option_margin",
                    ):
                        if p.get(_mk) is not None:
                            row[_mk] = p.get(_mk)
                    positions.append(row)
    except Exception:
        pass
    return positions


def _schwab_margin_stamp(pos: dict) -> dict:
    """Stamp margin/BP only when Schwab already supplied a field — never invent dollars."""
    for key in (
        "margin_requirement",
        "maintenance_requirement",
        "initial_requirement",
        "buying_power_effect",
        "bp_effect",
        "option_margin",
    ):
        if pos.get(key) is not None:
            try:
                val = float(pos.get(key))
            except (TypeError, ValueError):
                continue
            return {
                "margin_status": "OK",
                "margin_usd": round(val, 2),
                "margin_field": key,
                "margin_note": f"Schwab field `{key}`",
                "margin_as_of": _iso(),
            }
    return {
        "margin_status": "MARGIN_UNKNOWN",
        "margin_usd": None,
        "margin_field": None,
        "margin_note": "not on Schwab feed used here",
        "margin_as_of": _iso(),
    }


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
    mark = None
    if contract and contract.get("mid") is not None:
        mark = _f(contract.get("mid"))
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
    pnl_status = "OK"
    pnl_unknown_reason = None
    if not entry or entry <= 0:
        pnl_status = "PNL_UNKNOWN"
        pnl_unknown_reason = "missing avg_entry / fill basis"
    elif mark is None or mark <= 0:
        pnl_status = "PNL_UNKNOWN"
        pnl_unknown_reason = "no chain mark"
    else:
        mult = 100 * _f(pos.get("qty"), 1)
        if is_short:
            pnl_unrealized = round((entry - mark) * mult, 2)
        else:
            pnl_unrealized = round((mark - entry) * mult, 2)

    working = True
    action = "hold"
    action_label = "Hold"
    action_criterion = "Default hold — no harvest/defend rule fired"
    rationale_parts = []

    if is_short and opt_type == "call":
        if itm and dte <= 7:
            action, action_label = "roll", "Roll to Next Expiration"
            action_criterion = "Short call ITM and DTE ≤ 7"
            rationale_parts.append("Short call ITM with ≤7 DTE — assignment risk elevated")
            working = False
        elif pop_otm >= 75 and pnl_unrealized and pnl_unrealized > 0:
            action, action_label = "close_profit", "Close for Profit"
            action_criterion = "POP OTM ≥ 75% and unrealized P&L > 0"
            rationale_parts.append(f"{pop_otm:.0f}% chance OTM — capture {pnl_unrealized:.0f} unrealized")
        elif not itm and pop_otm >= 60:
            action, action_label = "hold", "Hold"
            action_criterion = "Short call OTM with POP OTM ≥ 60%"
            rationale_parts.append(f"Position working: {pop_otm:.0f}% POP OTM, {dte} DTE left")
        elif itm:
            action, action_label = "close", "Close / Roll"
            action_criterion = "Short call ITM (assignment risk)"
            rationale_parts.append("ITM short call — consider rolling or closing to avoid assignment")
            working = False
    elif is_short and opt_type == "put":
        if itm and dte <= 10:
            action, action_label = "close", "Close Position"
            action_criterion = "Short put ITM and DTE ≤ 10"
            rationale_parts.append("Short put ITM — assignment risk on underlying")
            working = False
        elif pop_otm >= 70 and pnl_unrealized and pnl_unrealized > 0:
            action, action_label = "close_profit", "Close for Profit"
            action_criterion = "POP OTM ≥ 70% and unrealized P&L > 0"
            rationale_parts.append(f"Capture premium — {pop_otm:.0f}% still OTM")
        else:
            action_criterion = "Short put monitoring — no close/roll threshold met"
            rationale_parts.append(f"CSP monitoring: {moneyness}, POP OTM {pop_otm:.0f}%")
    else:
        if entry and pnl_unrealized and pnl_unrealized < -0.5 * entry * 100:
            action, action_label = "close", "Cut Loss"
            action_criterion = "Long option unrealized loss > 50% of entry premium"
            rationale_parts.append("Long option down >50% — edge deteriorated")
            working = False
        elif pop_itm >= 65 and pnl_unrealized and pnl_unrealized > 0:
            action, action_label = "close_profit", "Take Profit"
            action_criterion = "Finish-ITM probability ≥ 65% and unrealized P&L > 0"
            rationale_parts.append(f"In-the-money with {pop_itm:.0f}% finish ITM probability")
        else:
            action_criterion = f"Long {opt_type} — no cut/take-profit threshold met"
            rationale_parts.append(f"Long {opt_type}: {moneyness}, {dte} DTE")

    iv_rank = _iv_rank_proxy(und_sym, tech, chain_iv=iv)
    edge = _edge_score(pop_otm if is_short else pop_itm, iv_rank, 0.5, conviction=0.5)

    qty = _f(pos.get("qty"), 1)
    mult = 100.0 * qty
    max_profit_at_open = round(entry * mult, 2) if entry else None
    # Credit (short) is +entry premium; debit (long) is −entry premium — economics label only.
    entry_credit_debit = None
    if entry and entry > 0:
        entry_credit_debit = round(entry * mult, 2) if is_short else round(-entry * mult, 2)
    max_loss_at_open = None
    if entry and strike:
        if is_short and opt_type == "put":
            max_loss_at_open = round(max(0.0, (strike - entry) * mult), 2)
        elif is_short and opt_type == "call":
            max_loss_at_open = round(max(strike * mult * 0.15, entry * mult * 3), 2)
        elif not is_short:
            max_loss_at_open = round(entry * mult, 2)

    profit_captured_pct = None
    if is_short and entry > 0 and mark is not None and mark >= 0:
        profit_captured_pct = round(100.0 * max(0.0, entry - mark) / entry, 1)

    risk_reward = None
    if pnl_unrealized is not None and max_loss_at_open and max_loss_at_open > 0:
        risk_reward = round(abs(pnl_unrealized) / max_loss_at_open, 3)
    elif pnl_unrealized and max_profit_at_open and max_profit_at_open > 0 and is_short:
        risk_reward = round(pnl_unrealized / max_profit_at_open, 3)

    lifecycle_phase = "monitor"
    maturity_note = ""
    if is_short:
        if action in ("close_profit",):
            lifecycle_phase = "harvest"
            maturity_note = "Target reached — close to lock premium before theta/assignment risk rises."
        elif action == "roll":
            lifecycle_phase = "defend"
            maturity_note = "Assignment risk elevated — roll or close; do not let mature unchecked."
        elif action == "close":
            lifecycle_phase = "defend"
            maturity_note = "Position stressed — close or adjust before expiration."
        elif pop_otm >= 72 and dte > 14 and (pnl_unrealized or 0) >= 0:
            lifecycle_phase = "let_mature"
            maturity_note = f"Let mature — {pop_otm:.0f}% POP OTM with {dte} DTE; theta working in your favor."
        elif pop_otm >= 60 and dte > 7:
            lifecycle_phase = "let_mature"
            maturity_note = f"Hold toward expiry — {pop_otm:.0f}% POP OTM; revisit if ITM or ≤7 DTE."
        elif profit_captured_pct is not None and profit_captured_pct >= 50 and dte <= 21:
            lifecycle_phase = "harvest"
            maturity_note = f"Consider harvesting — {profit_captured_pct:.0f}% of premium captured with {dte} DTE left."
        else:
            maturity_note = f"Monitor daily — POP OTM {pop_otm:.0f}%, {dte} DTE to expiration."
    else:
        if action == "close_profit":
            lifecycle_phase = "harvest"
            maturity_note = "Take profit — edge realized; don't overstay long gamma/theta decay."
        elif action == "close":
            lifecycle_phase = "defend"
            maturity_note = "Cut or roll — thesis weakened or loss threshold hit."
        elif dte <= 7 and not itm:
            lifecycle_phase = "harvest"
            maturity_note = f"Expiry approaching ({dte} DTE) — decide roll, close, or let expire worthless."
        elif dte > 14 and pop_itm >= 55:
            lifecycle_phase = "let_mature"
            maturity_note = f"Let work — {pop_itm:.0f}% ITM probability with {dte} DTE remaining."
        else:
            maturity_note = f"Long {opt_type}: {moneyness}, {dte} DTE — watch mark vs entry."

    margin = _schwab_margin_stamp(pos)

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
        "avg_entry": entry if entry else None,
        "entry_credit_debit": entry_credit_debit,
        "unrealized_pnl": pnl_unrealized,
        "pnl_status": pnl_status,
        "pnl_unknown_reason": pnl_unknown_reason,
        "moneyness": moneyness,
        "itm": itm,
        "pop_otm_pct": pop_otm,
        "pop_itm_pct": pop_itm,
        "delta": delta,
        "iv_rank": iv_rank,
        "edge_score": edge,
        "risk_reward": risk_reward,
        "max_profit_at_open": max_profit_at_open,
        "max_loss_at_open": max_loss_at_open,
        "profit_captured_pct": profit_captured_pct,
        "lifecycle_phase": lifecycle_phase,
        "maturity_note": maturity_note,
        "still_working": working,
        "recommended_action": action_label,
        "action": action,
        "action_criterion": action_criterion,
        "action_buttons": [
            {"action": action, "label": action_label},
            {"action": "roll", "label": "Roll to Next Week"},
            {"action": "hold", "label": "Hold"},
            {"action": "review_chain", "label": "View Chain"},
        ],
        "rationale": " · ".join(rationale_parts) or f"{moneyness} — monitor",
        "severity": "warning" if not working else ("positive" if (pnl_unrealized or 0) > 0 else "info"),
        "monitored_at": _iso(),
        **margin,
    }


def _stamp_cio_hub_strip(proposals: List[dict], convictions: List[dict]) -> List[dict]:
    """Stamp advisory CIO entry_state onto Hub proposal cards (Stage C/D, 2026-09-25).

    Cards read ``p.cio.entry_state``. Prefer ``source=entry_state`` when a symbol
    appears on more than one conviction. Never raises into generate_proposals —
    a missing strip is worse than blank Ideas (NameError shipped once and blanked
    the live desk behind the single-threaded server).
    """
    by_sym: Dict[str, dict] = {}
    for c in convictions or []:
        if not isinstance(c, dict):
            continue
        sym = (c.get("symbol") or "").upper()
        if not sym:
            continue
        prior = by_sym.get(sym)
        if prior is None or "entry_state" in set(c.get("source_lanes") or [c.get("source")]):
            by_sym[sym] = c
    for p in proposals or []:
        if not isinstance(p, dict):
            continue
        sym = (p.get("symbol") or p.get("underlying") or "").upper()
        c = by_sym.get(sym)
        if not c:
            continue
        entry = c.get("entry_state")
        if not entry and "entry_state" not in set(c.get("source_lanes") or [c.get("source")]):
            continue
        note_parts: List[str] = []
        if c.get("volatility_elevated"):
            note_parts.append(
                "elevated ATR vs stop — options may be capital-efficient vs full equity"
            )
        atr_vs = c.get("atr_vs_distance_to_stop")
        if atr_vs is not None:
            try:
                note_parts.append(f"ATR/stop={float(atr_vs):.2f}")
            except (TypeError, ValueError):
                pass
        hub_note = " · ".join(note_parts) if note_parts else None
        if entry and not hub_note:
            hub_note = (
                f"CIO {entry} (advisory — does not unlock live; "
                "Path B still needs liquidity + per-order 2FA)"
            )
        p["cio"] = {
            "entry_state": entry or None,
            "source": c.get("source"),
            "confidence": c.get("confidence"),
            "bias": c.get("bias") or c.get("direction"),
            "summary": c.get("summary"),
            "volatility_elevated": bool(c.get("volatility_elevated")),
            "hub_note": hub_note,
        }
    return proposals


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
            # Wider strike window so liquid near-target contracts can win Stage B pick.
            chain_cache[sym] = _schwab_chain(sym, strikes=16)
        chain = chain_cache.get(sym) or {}
        contract = None
        if p.get("data_source") != "bs_estimate":
            # Prefer quotes stamped on the proposal (same contract as the idea).
            bid, ask = _f(p.get("bid")), _f(p.get("ask"))
            mid = _f(p.get("premium")) or _f(p.get("mid"))
            if mid <= 0 and bid > 0 and ask > 0:
                mid = (bid + ask) / 2.0
            if mid > 0 and (bid > 0 or ask > 0 or p.get("oi") is not None):
                contract = {
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "oi": None if p.get("oi") is None else int(_f(p.get("oi"))),
                    "volume": int(_f(p.get("volume"))),
                    "strike": _f(p.get("strike")),
                    "dte": int(p.get("dte") or 0),
                    "exp": p.get("expiration"),
                }
            else:
                side = "call" if (p.get("option_type") or "").lower() == "call" else "put"
                contract = _pick_chain_contract(
                    chain, side, _f(p.get("strike")), int(p.get("dte") or 30),
                )
        row = ent.enterprise_enrich_proposal(dict(p), contract=contract, chain=chain)
        # Operator 2026-09-27: a two-leg order has two quotes; gate BOTH legs. DELL's short leg
        # passed alone (OI 366) while the long leg was never looked at.
        if str(row.get("strategy") or "") == "credit_spread" and row.get("legs_liquidity"):
            try:
                _liq = dict((row.get("enterprise") or {}).get("liquidity") or {})
                _legs, _issues = [], []
                for _leg in row.get("legs_liquidity") or []:
                    _g = ent.liquidity_gate({"bid": _leg.get("bid"), "ask": _leg.get("ask"), "mid": _leg.get("mid"),
                                             "oi": _leg.get("open_interest"), "volume": _leg.get("volume")})
                    _g["role"] = _leg.get("role")
                    _g["strike"] = _leg.get("strike")
                    _legs.append(_g)
                    _issues += [f"{_leg.get('role')} {_leg.get('strike'):g}: {i}" for i in _g.get("issues") or []]
                _liq["legs"] = _legs
                if _issues:
                    _liq["pass"] = False
                    _liq["issues"] = list(_liq.get("issues") or []) + [i for i in _issues if i not in (_liq.get("issues") or [])]
                    _ent = row.setdefault("enterprise", {})
                    _ent["liquidity"] = _liq
                    _ent["live_eligible"] = False
                    if not any("awaiting live quotes" in str(b) or "OI" in str(b) or "spread" in str(b) for b in _ent.get("blocks") or []):
                        try:
                            from lib.canonical_observation import market_session as _ms
                            from lib.options_income_quality import defer_liquidity as _dl
                            _sess = _ms()
                        except Exception:  # noqa: BLE001
                            _sess, _dl = None, (lambda *_a, **_k: False)
                        if _dl(_sess, ent.load_desk_config()):
                            row["liquidity_pending"] = True
                            _ent["blocks"] = list(_ent.get("blocks") or []) + [
                                f"awaiting live quotes (market {str(_sess).lower().replace('_', ' ')}): " + "; ".join(_issues[:3])]
                        else:
                            _ent["blocks"] = list(_ent.get("blocks") or []) + _issues[:3]
                        row["enterprise_blocked"] = True
                else:
                    row.setdefault("enterprise", {})["liquidity"] = _liq
            except Exception as _e:  # noqa: BLE001
                print(f"[options_engine] per-leg liquidity gate skipped for {sym}: {type(_e).__name__}: {_e}", file=sys.stderr)
        und = _f(row.get("underlying_price"))
        if sym and und > 0:
            vol = ent.vol_analytics_from_chain(chain, und)
            if vol.get("ok"):
                ent.persist_chain_snapshot(sym, chain, vol)
        enriched.append(row)
    return enriched


def _attach_options_thesis(proposals: List[dict]) -> None:
    """Same thesis bar as an equity purchase (2026-09-26).

    Before this, nothing in the options path read the symbol thesis store, so every
    card said "no thesis pin" and the approval queue accepted ideas with no thesis.
    Stamps the pin, catalyst and an OptionsThesisRecord (stored append-only by
    strategy GUID); an incomplete record becomes ``thesis_blocks`` that
    sync_approval_queue turns into a refusal.
    """
    try:
        from lib.symbol_thesis_attach import thesis_fields_for_symbol
        from lib.options_thesis import OptionsThesisStore, build_record, thesis_blocks
    except Exception as e:  # never silently: the card must say why there is no thesis
        for p in proposals:
            p["thesis_blocks"] = [{"code": "thesis_unavailable", "reason": f"thesis store unavailable: {type(e).__name__}"}]
        return
    store = OptionsThesisStore()
    cache: Dict[str, dict] = {}
    views: Dict[str, dict] = {}
    try:
        from lib.ticker_cio_view import cio_view
        from lib.options_thesis_lifecycle import queue_position, settings as _life_settings
        _proj = json.loads((PROJECT_ROOT / "data" / "cio" / "hermes_research_projection.json").read_text(encoding="utf-8"))
    except Exception:
        cio_view = None  # type: ignore
        _proj = {}
    for p in proposals:
        sym = str(p.get("symbol") or "").upper()
        if sym not in cache:
            try:
                cache[sym] = thesis_fields_for_symbol(sym)
            except Exception as e:
                cache[sym] = {"thesis_state": "INSUFFICIENT_DATA", "thesis_reason": f"lookup_error:{type(e).__name__}"}
        t = cache[sym]
        # Lifecycle memory first (operator 2026-09-26): research answers and the CIO
        # decision already on file feed this version instead of starting blank.
        guid = p.get("option_strategy_guid")
        life = store.lifecycle(guid) if guid else {}
        p["research_answers"] = dict(((life.get("research") or {}).get("answers")) or {})
        fc = life.get("followup_complete") or {}
        if fc.get("answers"):
            p["research_answers"]["followup"] = fc["answers"]
        dec = life.get("decision") or {}
        if dec:
            p["cio_decision"] = {"decision_guid": dec.get("decision_guid"), "outcome": dec.get("outcome"),
                                 "confidence": dec.get("confidence"), "at": dec.get("recorded_at"),
                                 "review": dec.get("review")}
        if life.get("abandoned"):
            p["thesis_abandoned"] = (life["abandoned"].get("reason") or "abandoned")
        req = life.get("research_request") or {}
        fu = life.get("followup") or {}
        p["lifecycle"] = {
            "stage": life.get("stage"),
            "timeline": life.get("timeline") or [],
            "followup": ({
                "deliverables": [q.get("text") for q in (fu.get("deliverables") or [])],
                "requested_at": fu.get("recorded_at"),
                "due_at": fu.get("due_at"),
                "for_decision": fu.get("for_decision"),
                "delivered": bool(fc) and str(fc.get("recorded_at") or "") > str(fu.get("recorded_at") or ""),
                "research_queue": (queue_position(_proj, fu.get("research_id"), _life_settings(_desk_cfg()))
                                   if fu.get("research_id") else None),
            } if fu else None),
            "decisions": [{"decision_guid": d.get("decision_guid"), "outcome": d.get("outcome"),
                           "at": d.get("recorded_at")} for d in (life.get("decisions") or [])],
            "research_queue": (queue_position(_proj, req.get("research_id"), _life_settings(_desk_cfg()))
                               if req.get("research_id") and not life.get("research") else None),
        }
        if cio_view is not None:
            if sym not in views:
                try:
                    views[sym] = cio_view(sym, t)
                except Exception:
                    views[sym] = {"has_view": False, "error": True}
            p["cio_view"] = views[sym]
        # Reported fundamentals from SEC filings (fundamentals plan F5, 2026-09-27).
        if sym not in _FUNDAMENTALS:
            try:
                from db_adapter import _execute as _fx
                from lib.fundamentals_feed import card_block
                _FUNDAMENTALS[sym] = card_block(sym, _fx)
            except Exception:  # noqa: BLE001
                _FUNDAMENTALS[sym] = {"state": "UNAVAILABLE", "symbol": sym, "lines": []}
        p["fundamentals"] = _FUNDAMENTALS[sym]
        # Instrument class (2026-09-27): ETFs have no company financials; a daily-leveraged
        # fund (PUR 2x) is not a wheel/income underlying under the desk policy.
        if sym not in _INSTRUMENT_CLASS:
            try:
                from db_adapter import _execute as _cx
                from lib.instrument_class import classify_symbol
                _INSTRUMENT_CLASS[sym] = classify_symbol(sym, _cx)
            except Exception:  # noqa: BLE001
                _INSTRUMENT_CLASS[sym] = None
        p["instrument_class"] = _INSTRUMENT_CLASS[sym]
        if p["instrument_class"] in ("ETF", "LEVERAGED_FUND"):
            p["fundamentals"] = {"state": "NOT_APPLICABLE", "symbol": sym, "lines": [],
                                 "reason": "fund: company financial statements do not apply"}
        _lev_policy = str(_desk_cfg().get("leveraged_fund_policy") or "block_income")
        if (p["instrument_class"] == "LEVERAGED_FUND" and _lev_policy == "block_income"
                and str(p.get("strategy") or "") in ("cash_secured_put", "covered_call", "credit_spread")):
            _ent = p.setdefault("enterprise", {})
            # A standing policy block leads: "awaiting live quotes" clears on Monday, this does not.
            _ent["blocks"] = [
                "daily leveraged fund: resets daily and decays over a holding period; not an income/wheel underlying"
            ] + list(_ent.get("blocks") or [])
            _ent["live_eligible"] = False
            p["enterprise_blocked"] = True
        # Honest economics (2026-09-27): expected P/L at expiration over the whole price
        # distribution at the desk's own IV, replacing `credit x POP`; plus net cost if
        # assigned, cash committed, and hedge floor / insured vs uninsured shares.
        try:
            from lib.options_economics import economics as _econ
            _liq = (p.get("enterprise") or {}).get("liquidity") or {}
            p["economics"] = _econ(p, shares_held=p.get("shares_held"),
                                   quote_issues=(list(_liq.get("issues") or []) if _liq.get("pass") is False else None),
                                   session=_SESSION.get("now"))
            p["expected_value"] = p["economics"].get("expected_pl_at_expiry")
            p["expected_value_method"] = p["economics"]["ev_method"]
            if p["economics"].get("ev_caveat"):
                p["expected_value_caveat"] = p["economics"]["ev_caveat"]
            # Protective put (operator 2026-09-27): the card is insurance for held stock, so its
            # headline max loss / breakeven are the hedged position's, and the put-alone figures
            # are labelled as such.
            if str(p.get("strategy") or "") == "protective_put":
                _e = p["economics"]
                if _e.get("hedged_max_loss_from_mark") is not None:
                    p["option_max_loss"] = _e.get("option_max_loss")
                    p["put_breakeven"] = _e.get("put_breakeven")
                    p["max_loss"] = _e["hedged_max_loss_from_mark"]
                    p["max_loss_label"] = "Max loss (hedged shares, to the floor)"
                    p["breakeven"] = _e.get("stock_plus_put_breakeven_from_mark")
                    p["breakeven_label"] = "Stock+put breakeven from mark"
                    p["floor_value"] = _e.get("floor_value_after_premium")
                    p["uninsured_shares"] = _e.get("uninsured_shares")
            from lib.options_economics import stamp_payoff
            stamp_payoff(p, quote_issues=list(_liq.get("issues") or []) if _liq.get("pass") is False else None)
        except Exception:  # noqa: BLE001
            p["expected_value"] = None
        rc = p.get("research_context") or {}
        if not p.get("catalyst") and rc.get("catalyst"):
            p["catalyst"] = rc["catalyst"]  # memo and strategy-fit read the top level
        p["price_source"] = _PRICE_SOURCE.get(sym)
        p["symbol_thesis_id"] = t.get("symbol_thesis_id")
        p["thesis_version_at_decision"] = t.get("symbol_thesis_version")
        p["thesis_state"] = t.get("thesis_state")
        record = build_record(p, t)
        try:
            stored = store.publish(record)
        except Exception as e:
            stored = dict(record, pin=None, store_error=type(e).__name__)
        p["options_thesis"] = {
            "pin": stored.get("pin"),
            "version": stored.get("version"),
            "missing_required": record["missing_required"],
            "pending_operator": record["pending_operator"],
            "thesis_gate_state": record["thesis_gate_state"],
        }
        p["thesis_blocks"] = thesis_blocks(record)
        _stamp_truth_flags(p)
        try:
            from lib.options_plain_english import committee_memo
            p["committee_memo"] = committee_memo(
                p, t, record, exit_rules=_desk_cfg().get("options_exit_rules") or {},
                queue_status=p.get("approval_status"),
            )
        except Exception as e:
            p["committee_memo"] = {"error": type(e).__name__}


_PURPOSE = {
    "cash_secured_put": ("INCOME", "Income"),
    "covered_call": ("INCOME", "Income"),
    "credit_spread": ("DEFINED_RISK_INCOME", "Defined-risk income"),
    "protective_put": ("INSURANCE", "Insurance"),
    "long_put": ("DOWNSIDE", "Downside bet"),
    "long_call": ("UPSIDE", "Upside"),
}


def _not_approvable_reason(p: dict, tb: list, ent: dict) -> str:
    """The real reason a card is not approvable (2026-09-27): every thesis-stage block
    used to read "thesis incomplete", so HOOD -- thesis complete, CIO REJECT -- said
    "thesis incomplete"."""
    # A pending model review is a later prerequisite. Name a deterministic veto
    # first so a blocked quote or earnings event never reads like a review queue.
    hard = [b for b in (ent.get("blocks") or [])
            if not isinstance(b, dict) or (b.get("code") != "awaiting_cio_decision"
            and not str(b.get("code") or "").startswith("thesis_"))]
    hard_codes = {str(b.get("code") or "").lower() for b in hard if isinstance(b, dict)}
    hard_text = " ".join(str(b.get("reason") if isinstance(b, dict) else b) for b in hard).lower()
    if "earnings_timestamp_unknown" in hard_codes or "earnings_timestamp_invalid" in hard_codes:
        return "earnings date unverified"
    if "earnings_blackout" in hard_codes:
        return "earnings event blocks review"
    if hard_codes.intersection({"spread_too_wide", "oi_below_threshold", "volume_below_threshold",
                                "liquidity_gate", "liquidity_unknown", "bs_estimate_only"}):
        return "option quote/liquidity failed"
    if "no_resolved_occ" in hard_codes:
        return "option contract unverified"
    if "daily leveraged fund" in hard_text:
        return "leveraged fund policy"
    if "awaiting live quotes" in hard_text:
        return "awaiting live quotes"
    if hard:
        return "enterprise block"
    codes = [str(b.get("code") if isinstance(b, dict) else "") for b in tb]
    reasons = " ".join(str(b.get("reason") if isinstance(b, dict) else b) for b in tb).upper()
    if "awaiting_cio_decision" in codes:
        if "REJECT" in reasons:
            return "CIO rejected"
        if "MORE_RESEARCH" in reasons:
            return "CIO asked for more research"
        return "awaiting CIO decision"
    if any(c.startswith("thesis_") for c in codes):
        return "thesis incomplete"
    return "enterprise block"


def _stamp_truth_flags(p: dict) -> None:
    """One honest status per card, as pills and filterable keys (operator 2026-09-26).

    A card that fails the thesis bar must not say "live eligible": the approval
    queue refuses it. Thesis blocks join the enterprise blocks the card already
    renders, live eligibility goes false, and ``flags`` names purpose, status,
    thesis gaps and data session so the desk can filter on them.
    """
    ent = p.setdefault("enterprise", {})
    tb = list(p.get("thesis_blocks") or [])
    if tb:
        existing = list(ent.get("blocks") or [])
        ent["blocks"] = existing + [b for b in tb if b not in existing]
        ent["live_eligible"] = False
        p["enterprise_blocked"] = True
    approvable = not (p.get("enterprise_blocked") or ent.get("blocks"))
    # Operator 2026-09-27: "POSITIVE" beside BLOCKED was the edge score talking. Keep the raw
    # edge tone as ``edge_severity``; the card's severity is the card's status.
    if p.get("severity") not in (None, "blocked"):
        p["edge_severity"] = p.get("severity")
    if not approvable:
        p["severity"] = "blocked"
    key, label = _PURPOSE.get(str(p.get("strategy") or ""), ("OTHER", "Other"))
    flags = [{"key": key, "label": label, "tone": "blue"}]
    if approvable:
        flags.append({"key": "APPROVABLE", "label": "Approvable", "tone": "green"})
    else:
        why = _not_approvable_reason(p, tb, ent)
        flags.append({"key": "NOT_APPROVABLE", "label": f"Not approvable: {why}", "tone": "red"})
    missing = (p.get("options_thesis") or {}).get("missing_required") or []
    if missing:
        flags.append({"key": "THESIS_INCOMPLETE", "tone": "amber",
                      "label": "Thesis missing: " + ", ".join(m.replace("_", " ") for m in missing)})
    elif p.get("options_thesis"):
        flags.append({"key": "THESIS_COMPLETE", "label": "Thesis complete", "tone": "green"})
    session = _market_session_now()
    if session and session != "REGULAR":
        flags.append({"key": "CLOSED_MARKET_CHAIN", "tone": "amber",
                      "label": f"Chain read {session.lower().replace('_', ' ')}"})
    p["purpose"] = key
    p["approvable"] = approvable
    p["flags"] = flags
    try:
        from lib.options_plain_english import explain
        p["plain_english"] = explain(p)
    except Exception:
        p["plain_english"] = None
    # Insight first (redesign PR3, 2026-09-27): the card's takeaway is decided HERE, from the
    # CIO decision / truth flags / plain English already on the card, never in the frontend.
    try:
        from lib.ui_insight import build_insight
        p["insight"] = build_insight("options_proposal", p)
    except Exception as _ie:  # noqa: BLE001
        p["insight"] = {"schema": "UiInsight@v1", "headline": "No takeaway available.", "tone": "neutral",
                        "drivers": [], "source": "rule", "as_of": None, "provenance": f"ui_insight:{type(_ie).__name__}"}


def _income_screen_summary() -> dict:
    """Reason -> count and names for income ideas the screen refused to build."""
    by: Dict[str, dict] = {}
    for d in INCOME_SCREEN_DROPS:
        slot = by.setdefault(d["reason"], {"count": 0, "symbols": []})
        slot["count"] += 1
        if d.get("symbol") and d["symbol"] not in slot["symbols"]:
            slot["symbols"].append(d["symbol"])
    return {"reasons": by, "total": len(INCOME_SCREEN_DROPS), "drops": INCOME_SCREEN_DROPS[:200],
            "liquidity_deferred": {"count": len(LIQUIDITY_DEFERRED), "session": _SESSION.get("now"),
                                   "symbols": sorted({d["symbol"] for d in LIQUIDITY_DEFERRED}),
                                   "note": "market closed: quotes are not live; liquidity is checked at the open"}}


def _market_session_now() -> Optional[str]:
    try:
        from lib.canonical_observation import market_session
        return market_session()
    except Exception:
        return None


# A page read inside the regular session may rebuild a snapshot older than this.
# Outside REGULAR the chain is the close: serve it. The daytime cron is the pull.
# force=1 (Force scan, and run_options_monitor) still rebuilds.
_PROPOSAL_CACHE_TTL_S = 600


def proposal_cache_serves(
    cached: dict,
    *,
    now: datetime,
    session: Optional[str],
    force: bool = False,
) -> bool:
    """True when a stored snapshot should be returned instead of reading chains.

    Regular session: serve a snapshot younger than 10 minutes.
    Any other known session (pre-market, after-hours, closed, weekend): serve
    the last snapshot at any age. An unknown session keeps the 10-minute rule.
    """
    if force or not isinstance(cached, dict) or not cached.get("generated_at"):
        return False
    if session and session != "REGULAR":
        return True
    try:
        gen = datetime.fromisoformat(str(cached["generated_at"]).replace("Z", "+00:00"))
        if gen.tzinfo is None:
            gen = gen.replace(tzinfo=timezone.utc)
        now_aw = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        age = (now_aw - gen).total_seconds()
    except (TypeError, ValueError):
        return False
    return age < _PROPOSAL_CACHE_TTL_S


def _universe_census(holdings, convictions, scored_rows, listed) -> dict:
    from lib.options_universe_census import build_universe_census
    return build_universe_census(
        holdings=holdings,
        convictions=convictions,
        scored=len(scored_rows),
        listed=listed,
        inputs_recorded=True,
    )


def read_proposals() -> dict:
    """Read model only: an empty cache never starts research or provider calls."""
    data = _load_json(PROPOSALS_CACHE) or {"proposals": [], "count": 0, "status": "UNAVAILABLE",
                                         "reason": "No completed options scan snapshot"}
    import options_desk_enterprise as ent
    cfg = _desk_cfg()
    for proposal in data.get("proposals", []):
        ent.stamp_freshness(proposal, now=_now(), session=_market_session_now())
        blocks = [b for b in ent.evaluate_hard_risk_blocks(proposal, mode="preflight", cfg=cfg)
                  if b.get("code") in {"quote_age_unknown", "quote_stale", "chain_age_unknown", "option_chain_stale"}]
        if blocks:
            enterprise = proposal.setdefault("enterprise", {})
            enterprise["blocks"] = list(enterprise.get("blocks") or []) + blocks
            enterprise["live_eligible"] = False
            proposal["approvable"] = False
            proposal["enterprise_blocked"] = True
            proposal["readiness_as_of"] = _iso()
    return data


def generate_proposals(force: bool = False, *, scan_inputs: Optional[dict] = None) -> dict:
    """Proposal projection; expanded collection belongs only to the scan worker."""
    if scan_inputs is None:
        from lib.options_scan import load_config
        if load_config(PROJECT_ROOT).get("enabled"):
            return read_proposals()
    cached = _load_json(PROPOSALS_CACHE)
    if proposal_cache_serves(cached, now=_now(), session=_market_session_now(), force=force):
        if not cached.get("universe_census"):
            from lib.options_universe_census import build_universe_census
            cached = dict(cached)
            cached["universe_census"] = build_universe_census(
                listed=cached.get("proposals") or [],
                scored=len(cached.get("proposals") or []),
                inputs_recorded=False,
            )
        return cached

    INCOME_SCREEN_DROPS.clear()
    SOURCE_RECEIPTS.clear()
    _CHAIN_CACHE.clear()
    IV_RANK_BASIS.clear()
    _PRICE_SOURCE.clear()
    LIQUIDITY_DEFERRED.clear()
    _SESSION["now"] = _market_session_now()
    _FUNDAMENTALS.clear()
    _INSTRUMENT_CLASS.clear()
    holdings, holdings_meta = ((scan_inputs["holdings"], scan_inputs["holdings_meta"])
                               if scan_inputs is not None else _load_holdings())
    SOURCE_RECEIPTS["holdings"] = {
        "status": "COMPLETE" if holdings_meta.get("_holdings_path") and holdings_meta.get("_observed_at") else "UNAVAILABLE",
        "observed_at": holdings_meta.get("_observed_at"),
    }
    global _SCAN_CHAINS
    _SCAN_CHAINS = scan_inputs.get("chains", {}) if scan_inputs is not None else None
    tech_map = _load_technicals()
    intent_cfg = _load_intent_cfg()
    aegis_map = _aegis_cc_map()
    owned = {h.get("symbol", "").upper() for h in holdings if _f(h.get("shares")) >= 100}
    # Full research universe: holdings remain the portfolio lane, while
    # researched watchlist and re-entry names are now first-class candidates.
    # The helper is research-qualified only; raw starred/scan names remain
    # visible to their originating desks but do not become option ideas here.
    convictions = scan_inputs["convictions"] if scan_inputs is not None else _research_universe_rows()
    entry_scanned = [
        {
            "symbol": c.get("symbol"),
            "entry_state": c.get("entry_state"),
            "volatility_elevated": bool(c.get("volatility_elevated")),
        }
        for c in convictions if "entry_state" in set(c.get("source_lanes") or [c.get("source")])
    ]
    entry_drops: List[dict] = []
    conv_syms = [c["symbol"] for c in convictions if c.get("symbol")]
    hold_syms = [(h.get("symbol") or "").upper() for h in holdings if not h.get("is_cash")]
    evaluation_holdings, evaluation_convictions = holdings, convictions
    if scan_inputs is not None:
        complete = {sym for sym, receipt in scan_inputs.get("chain_receipts", {}).items()
                    if receipt.get("status") == "COMPLETE"}
        evaluation_holdings = [h for h in holdings if h.get("symbol") in complete]
        evaluation_convictions = [c for c in convictions if c.get("symbol") in complete]
        for sym, chain in scan_inputs.get("chains", {}).items():
            if _f(chain.get("underlying_price")) > 0:
                tech_map.setdefault(sym, {}).update(price=chain["underlying_price"], last=chain["underlying_price"])
        conv_syms = [c["symbol"] for c in evaluation_convictions]
        hold_syms = [h["symbol"] for h in evaluation_holdings]
    else:
        # Compatibility producer keeps its previous provider envelope until expanded
        # capacity is approved. Inventory still contains every name; omitted chains are PENDING.
        lane_budgets = {"watchlist": 120, "reentry": 120, "security_research_spine": 500}
        used = {lane: 0 for lane in lane_budgets}
        evaluation_convictions = []
        for row in convictions:
            lanes = set(row.get("source_lanes") or [row.get("source")])
            budgeted = lanes.intersection(lane_budgets)
            if budgeted and all(used[lane] >= lane_budgets[lane] for lane in budgeted):
                continue
            evaluation_convictions.append(row)
            for lane in budgeted:
                used[lane] += 1
        conv_syms = [c["symbol"] for c in evaluation_convictions if c.get("symbol")]
    tech_map = _enrich_tech_map(conv_syms + hold_syms, tech_map, holdings)

    cc = generate_covered_call_proposals(evaluation_holdings, tech_map, intent_cfg, aegis_map)
    cash_map = _cash_by_account(holdings)
    puts = generate_holdings_put_proposals(evaluation_holdings, tech_map, cash_map, aegis_map)
    dr = generate_defined_risk_proposals(
        evaluation_convictions, tech_map, owned, holdings, cash_map, out_entry_drops=entry_drops,
    )
    spreads = generate_credit_spread_proposals(evaluation_convictions, tech_map, holdings, cash_map)
    pool = cc + puts + dr + spreads
    cc_syms = set(s.upper() for s in (intent_cfg.get("covered_call_candidate") or []))

    def _passes_quality_gate(p: dict) -> bool:
        if not p.get("quality_pass"):
            return False
        edge = _f(p.get("edge_score"))
        sym = (p.get("symbol") or "").upper()
        strat = p.get("strategy") or ""
        # Credit spreads: hard R:R floor (enterprise helper) — never Ideas on 0.06 R:R.
        if strat == "credit_spread":
            try:
                import options_desk_enterprise as _ent_qg
                if _ent_qg.credit_spread_rr_block(p):
                    return False
            except Exception:
                rr = _f(p.get("risk_reward"))
                if rr > 0 and rr < 0.25:
                    return False
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
            if p.get("edge_score", 0) >= MIN_EDGE_CC_INTENT
            and _f(p.get("pop_pct")) >= (MIN_POP_PCT - 5)
            and (
                (p.get("strategy") or "") != "credit_spread"
                or _passes_quality_gate({**p, "quality_pass": True})
            )
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
    try:
        strict = _stamp_cio_hub_strip(strict, convictions)
    except Exception:
        # Desk Ideas must still render if CIO strip stamping fails.
        pass
    all_p = strict
    research_by_symbol = {
        str(c.get("symbol") or "").upper(): c for c in convictions if c.get("symbol")
    }
    for proposal in all_p:
        ctx = research_by_symbol.get(str(proposal.get("symbol") or "").upper())
        if ctx:
            if ctx.get("direction_conflict"):
                ent = proposal.setdefault("enterprise", {})
                ent["blocks"] = list(ent.get("blocks") or []) + ["RESEARCH_DIRECTION_CONFLICT"]
                ent["live_eligible"] = False
                proposal["enterprise_blocked"] = True
            proposal["research_context"] = {
                "source_lanes": list(ctx.get("source_lanes") or []),
                # Operator 2026-09-27: lane membership is not research; say which it is.
                "research_status": ctx.get("research_status") or "unknown",
                "research_lane_status": ctx.get("research_lane_status"),
                "research_artifact_id": ctx.get("research_artifact_id"),
                "research_as_of": ctx.get("research_as_of") or ctx.get("evaluated_at"),
                "summary": ctx.get("summary"),
                "catalyst": ctx.get("catalyst"),
                "reentry_signal": ctx.get("reentry_signal"),
                "reentry_trigger": ctx.get("reentry_trigger"),
                "invalidated_if": ctx.get("invalidated_if"),
            }
    _attach_options_thesis(all_p)
    # A thesis that could not be completed inside the window is archived, not shown -- and
    # (operator 2026-09-27) not counted in another card's combined exposure either.
    for _p in [x for x in all_p if x.get("thesis_abandoned")]:
        INCOME_SCREEN_DROPS.append({"symbol": _p.get("symbol"), "strategy": _p.get("strategy"),
                                    "reason": "THESIS_ABANDONED", "detail": _p["thesis_abandoned"]})
    _archived = [x for x in all_p if x.get("thesis_abandoned")]
    # Order gates (2026-09-27): an archived idea's approval-queue row used to survive
    # untouched (it was dropped before sync_approval_queue), so an 'approved' row for an
    # idea the desk had archived still passed check_preflight_approval. Archive the rows first.
    archive_sync = {}
    if _archived:
        try:
            import options_desk_enterprise as _ent_arch
            archive_sync = _ent_arch.archive_approval_rows(_archived)
        except Exception as _ae:  # noqa: BLE001
            archive_sync = {"ok": False, "error": f"{type(_ae).__name__}: {str(_ae)[:120]}"}
    all_p = [x for x in all_p if not x.get("thesis_abandoned")]
    # Order gates (2026-09-27): stamp the freshness inputs the submit-mode risk evaluator
    # fails closed on -- market_session (this run), chain_age_seconds (the chain's fetched_at),
    # quote_age_seconds (the contract's / oldest leg's quote_time). buying_power is NOT stamped:
    # it needs a broker read the desk holds no grant for, so an order fails closed on
    # buying_power_unknown by design until a granted layer supplies it. Recomputed at preflight.
    try:
        import options_desk_enterprise as _ent_fresh
        _fresh_now = datetime.now(timezone.utc)
        for _p in all_p:
            _ent_fresh.stamp_freshness(_p, now=_fresh_now, session=_SESSION.get("now"),
                                       chain_fetched_at=_chain_fetched_at(str(_p.get("symbol") or "")))
    except Exception as _fe:  # noqa: BLE001
        print(f"[options_engine] freshness stamp skipped: {type(_fe).__name__}: {_fe}", file=sys.stderr)
    # Wave B 2026-09-27: ideas on the same symbol are one bet; say so on each card.
    try:
        from lib.options_exposure import combined_exposure
        _shares = {}
        _shares_acct: dict = {}
        for _h in holdings:
            if not _h.get("is_cash") and _h.get("symbol"):
                _k = str(_h["symbol"]).upper()
                _n = _f(_h.get("shares") or _h.get("quantity"))
                _shares[_k] = round(_shares.get(_k, 0.0) + _n, 3)
                _a = str(_h.get("account") or _h.get("account_key") or "")
                if _a:
                    _shares_acct.setdefault(_k, {})[_a] = round(_shares_acct.get(_k, {}).get(_a, 0.0) + _n, 3)
        _combo = combined_exposure(all_p + _archived, cash_by_account=cash_map, shares_by_symbol=_shares,
                                   shares_by_symbol_account=_shares_acct)
        for _p in all_p:
            _c = _combo.get(str(_p.get("symbol") or "").upper())
            if _c:
                _p["combined_exposure"] = _c
    except Exception as _e:  # noqa: BLE001
        print(f"[options_engine] combined exposure skipped: {type(_e).__name__}: {_e}", file=sys.stderr)

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

    try:
        from lib.options_research_universe import research_universe_summary
        universe_summary = research_universe_summary(convictions)
    except Exception:
        universe_summary = {"total": len(convictions), "research_qualified": len(convictions)}

    from lib.options_universe_census import build_coverage, desk_queue
    if scan_inputs is not None and scan_inputs.get("profile") == "priority":
        refreshed = set(scan_inputs.get("chain_receipts", {}))
        all_p.extend(p for p in (cached or {}).get("proposals", []) if p.get("symbol") not in refreshed)
    if scan_inputs is not None:
        from lib.options_advisory_candidates import generate_candidates
        all_p.extend(generate_candidates(convictions, holdings, scan_inputs.get("chains", {}),
                                         covered_call_block=_intent_blocks_covered_call, drops=INCOME_SCREEN_DROPS))
    for p in all_p:
        p["iv_rank_basis"] = IV_RANK_BASIS.get(p.get("symbol"), "unknown")
        p["desk_queue"] = desk_queue(p, (p.get("research_context") or {}).get("source_lanes") or [])
    all_p = _allocate_strategy_slots(all_p)
    out = {
        "generated_at": _iso(),
        "scan_run_id": (scan_inputs or {}).get("run_id"),
        "scan_status": (scan_inputs or {}).get("run_status", "LEGACY_PARTIAL"),
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
        "entry_directional_scanned": entry_scanned,
        "entry_directional_dropped": entry_drops,
        "research_universe": universe_summary,
        "research_lanes": sorted({lane for c in convictions for lane in (c.get("source_lanes") or [])}),
        "proposals": all_p,
        "universe_census": _universe_census(holdings_meta.get("_inventory_holdings", holdings), convictions, strict, all_p),
        "coverage": build_coverage(
            holdings=holdings_meta.get("_inventory_holdings", holdings), convictions=convictions,
            proposals=all_p, drops=INCOME_SCREEN_DROPS + entry_drops,
            chains=(scan_inputs or {}).get("coverage_receipts", (scan_inputs or {}).get("chain_receipts", {})),
            source_receipts=(scan_inputs or {}).get("source_receipts", dict(SOURCE_RECEIPTS))),
        "income_screen": _income_screen_summary(),
        "holdings_funnel": build_holdings_funnel(holdings=holdings, tech_map=tech_map,
                                                 intent_cfg=intent_cfg, aegis_map=aegis_map,
                                                 resolve_chain=True),
        "market_session": _market_session_now(),
        "desk_level": "enterprise",
        "enterprise": enterprise_summary,
        "approval_queue": approval_sync,
        "archived_queue_rows": archive_sync,
        "strategy_overview": {
            "total_edge_avg": round(sum(_f(p.get("edge_score")) for p in all_p) / max(sum(p.get("edge_score") is not None for p in all_p), 1), 1),
            "avg_pop": round(sum(_f(p.get("pop_pct")) for p in all_p) / max(sum(p.get("pop_pct") is not None for p in all_p), 1), 1),
            "income_opportunities": sum(1 for p in all_p if p["strategy"] == "covered_call"),
            "put_plays": sum(1 for p in all_p if "put" in (p.get("strategy") or "")),
            "conviction_plays": sum(1 for p in all_p if p["strategy"] not in ("covered_call", "cash_secured_put", "protective_put")),
            "strategy_slots": STRATEGY_SLOTS,
            "note": "Complete proposal ledger; display pagination never limits evaluation.",
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
    _SCAN_CHAINS = None
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
    props = read_proposals()
    mon = _load_json(MONITOR_CACHE) or {}
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
    "hedge": frozenset({"protective_put", "collar"}),
    "directional": frozenset({"long_call", "long_put", "debit_spread"}),
    "spread": frozenset({"credit_spread", "debit_spread"}),
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
    return (p.get("strategy") in {"credit_spread", "debit_spread"}
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


def _looks_optionable_symbol(sym: str) -> bool:
    """Ticker-shaped symbols only — CUSIP/all-digit rows are not optionable equities."""
    s = (sym or "").upper().strip()
    if not s or s.isdigit() or len(s) > 10:
        return False
    return bool(re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", s))


def evaluate_covered_call_status(
    h: dict,
    tech_map: dict,
    intent_cfg: dict,
    aegis_map: Optional[dict] = None,
    *,
    resolve_chain: bool = True,
) -> dict:
    """Named drop reason for one holding row — mirrors generate_covered_call_proposals gates.

    Does not widen gates. Returns status in:
      NEED_100_SHARES | MV_BELOW | PRICE_ZERO | NOT_OPTIONABLE | LOAN_RESTRICTED |
      NO_CHAIN | IV_BELOW_FLOOR | EDGE_BELOW | POP_BELOW | AEGIS_REJECT |
      INTENT_BYPASS | CC_ELIGIBLE
    INTENT_BYPASS means the name is on covered_call_candidate and cleared IV via intent
    (still subject to edge/POP); CC_ELIGIBLE means it would pass quality screens.
    """
    aegis_map = aegis_map or {}
    sym = (h.get("symbol") or "").upper()
    shares = _f(h.get("shares"))
    price = _f(h.get("price"))
    mv = _f(h.get("market_value"))
    acct = h.get("account") or ""
    base = {
        "symbol": sym,
        "account": acct,
        "shares": round(shares, 4),
        "market_value": round(mv, 2),
        "price": round(price, 4) if price else 0.0,
        "strategy": "covered_call",
    }
    if h.get("is_cash") or not sym:
        return {**base, "status": "SKIP_CASH", "detail": "cash / empty symbol"}
    if not _looks_optionable_symbol(sym):
        return {**base, "status": "NOT_OPTIONABLE", "detail": "CUSIP or non-ticker symbol"}
    if h.get("is_loan"):
        return {**base, "status": "LOAN_RESTRICTED", "detail": "loan / restricted shares"}
    if price <= 0:
        return {**base, "status": "PRICE_ZERO", "detail": "no usable mark"}
    if shares < MIN_HOLDING_SHARES_CC:
        shares_short = round(max(0.0, MIN_HOLDING_SHARES_CC - shares), 4)
        return {
            **base,
            "status": "NEED_100_SHARES",
            "detail": (
                f"{shares:.2f} shares — need ≥{MIN_HOLDING_SHARES_CC} to cover 1 call "
                f"(short {shares_short} shares). Covered call stays refused — never fake cover."
            ),
            "shares_short": shares_short,
            "alternate_hint": {
                "buy_to_lot": f"Buy ~{shares_short} more shares to cover 1 call",
                "consider": [
                    "cash_secured_put if cash + IV clear (income / wheel — not a fake CC)",
                    "protective_put only when shares ≥50 and MV clears hedge floor",
                ],
                "never": "covered_call on sub-100 share lots",
            },
        }
    if mv < MIN_POSITION_MV:
        return {
            **base,
            "status": "MV_BELOW",
            "detail": f"MV ${mv:,.0f} below ${MIN_POSITION_MV:,.0f} floor",
        }

    cc_syms = set(s.upper() for s in (intent_cfg.get("covered_call_candidate") or []))
    settings = intent_cfg.get("covered_call_settings") or {}
    default_dte = int(settings.get("default_dte_days", 30))
    default_otm = _f(settings.get("default_otm_pct", 0.06))
    min_iv = _f(settings.get("iv_rank_minimum", MIN_IV_RANK))
    in_intent = sym in cc_syms
    gates = _holding_quality_gates(h)
    min_iv_h = gates["min_iv"] if gates["manual"] else min_iv
    tech = tech_map.get(sym) or {}

    target_strike = price * (1 + default_otm)
    if price < 50:
        target_strike = round(target_strike / 0.5) * 0.5
    elif price < 200:
        target_strike = round(target_strike / 2.5) * 2.5
    else:
        target_strike = round(target_strike / 5.0) * 5.0

    contract = None
    data_source = ""
    if resolve_chain:
        contract, data_source = _resolve_option_contract(
            sym, price, tech, "call", target_strike, default_dte,
        )
        if not contract:
            return {
                **base,
                "status": "NO_CHAIN",
                "detail": "no Schwab/BS contract resolved at target strike/DTE",
                "intent_sleeve": in_intent,
            }

    iv = (contract or {}).get("iv") or 0.25
    iv_rank = _iv_rank_proxy(sym, tech, chain_iv=iv if contract else None,
                             chain_lookup=resolve_chain, price=price)
    base["iv_rank"] = round(iv_rank, 1)
    base["intent_sleeve"] = in_intent
    if contract:
        base["data_source"] = data_source
        base["strike"] = contract.get("strike")
        base["dte"] = contract.get("dte")

    if iv_rank < min_iv_h and not in_intent:
        return {
            **base,
            "status": "IV_BELOW_FLOOR",
            "detail": f"IV rank proxy {iv_rank:.0f} < floor {min_iv_h:.0f} (not on covered_call_candidate)",
        }

    und = price
    strike = _f((contract or {}).get("strike"), target_strike)
    dte = int((contract or {}).get("dte") or default_dte)
    premium = _f((contract or {}).get("mid"), 0.5)
    contracts = int(shares // 100)
    pop = _pop_otm_call(und, strike, max(0.05, float(iv)), dte)
    collateral = round(und * shares, 2)
    rr = (premium * 100 * contracts) / max(collateral * (dte / 365.0), 1.0)
    aegis = aegis_map.get(sym) or {}
    edge = _edge_score(
        pop,
        iv_rank,
        rr,
        catalyst_boost=12.0 if in_intent else (8.0 if gates["manual"] else 3.0),
        conviction=_f(aegis.get("confidence"), 0.6),
        yield_ann_pct=_cc_yield_ann_pct(premium, und, dte),
    )
    if in_intent and pop >= MIN_POP_PCT:
        edge = max(edge, pop * 0.55 + 18.0)
    if gates["manual"]:
        edge = round(edge + gates["edge_boost"], 1)
    min_edge = gates["min_edge"] if (in_intent or gates["manual"]) else MIN_EDGE_SCORE
    base["edge_score"] = round(edge, 1)
    base["pop_pct"] = round(pop, 1)
    base["min_edge"] = min_edge

    if pop < MIN_POP_PCT:
        return {
            **base,
            "status": "POP_BELOW",
            "detail": f"POP {pop:.0f}% < {MIN_POP_PCT}%",
        }
    if edge < min_edge:
        status = "INTENT_BYPASS" if in_intent else "EDGE_BELOW"
        # Intent cleared IV but still failed edge — still EDGE_BELOW with intent flag
        if in_intent and edge < min_edge:
            status = "EDGE_BELOW"
        return {
            **base,
            "status": status,
            "detail": (
                f"{shares:,.0f} sh in {acct.replace('_', ' ') or 'account'} covers {contracts} call(s); "
                f"best call ${strike:g} {dte}d pays ${premium:.2f} (POP {pop:.0f}%), "
                f"edge {edge:.1f} < min {min_edge:.0f}"
                + (" (intent sleeve)" if in_intent else "")
            ),
            "premium": round(premium, 2),
            "strike": strike,
            "dte": dte,
        }

    aegis_ok = (aegis.get("verdict") or "").lower() in ("candidate", "write", "ok", "")
    if aegis and not aegis_ok and (aegis.get("verdict") or "").lower() in ("reject", "avoid", "wait"):
        return {
            **base,
            "status": "AEGIS_REJECT",
            "detail": f"Aegis verdict={aegis.get('verdict')}",
        }

    if in_intent and iv_rank < min_iv_h:
        return {
            **base,
            "status": "INTENT_BYPASS",
            "detail": f"intent sleeve cleared IV floor ({iv_rank:.0f} < {min_iv_h:.0f}); quality gates pass",
        }
    return {
        **base,
        "status": "CC_ELIGIBLE",
        "detail": "passes share/IV/edge/POP screens — expect a covered-call card when slots allow",
    }


def evaluate_protective_put_status(
    h: dict,
    tech_map: dict,
    *,
    resolve_chain: bool = True,
) -> dict:
    """Named drop reason for protective-put path on one holding (no gate widening)."""
    sym = (h.get("symbol") or "").upper()
    shares = _f(h.get("shares"))
    price = _f(h.get("price"))
    mv = _f(h.get("market_value"))
    acct = h.get("account") or ""
    base = {
        "symbol": sym,
        "account": acct,
        "shares": round(shares, 4),
        "market_value": round(mv, 2),
        "price": round(price, 4) if price else 0.0,
        "strategy": "protective_put",
    }
    if h.get("is_cash") or not sym:
        return {**base, "status": "SKIP_CASH", "detail": "cash / empty symbol"}
    if not _looks_optionable_symbol(sym):
        return {**base, "status": "NOT_OPTIONABLE", "detail": "CUSIP or non-ticker symbol"}
    if price <= 0:
        return {**base, "status": "PRICE_ZERO", "detail": "no usable mark"}
    if shares < 50:
        return {**base, "status": "NEED_50_SHARES", "detail": f"{shares:.2f} shares — protective put wants ≥50"}
    if mv < MIN_PROTECTIVE_MV:
        return {
            **base,
            "status": "MV_BELOW",
            "detail": f"MV ${mv:,.0f} below ${MIN_PROTECTIVE_MV:,.0f} protective floor",
        }
    gates = _holding_quality_gates(h)
    tech = tech_map.get(sym) or {}
    iv_rank = _iv_rank_proxy(sym, tech)
    base["iv_rank"] = round(iv_rank, 1)
    if iv_rank < gates["min_iv"]:
        return {
            **base,
            "status": "IV_BELOW_FLOOR",
            "detail": f"IV rank proxy {iv_rank:.0f} < floor {gates['min_iv']:.0f}",
        }
    if not resolve_chain:
        return {**base, "status": "PUT_ELIGIBLE_PENDING_CHAIN", "detail": "size/IV ok — chain not resolved"}
    target_strike = round(price * 0.95 / 2.5) * 2.5 if price > 50 else round(price * 0.95, 1)
    contract, data_source = _resolve_option_contract(sym, price, tech, "put", target_strike, 45)
    if not contract:
        return {**base, "status": "NO_CHAIN", "detail": "no put contract resolved"}
    premium = _f(contract.get("mid"))
    if premium <= 0:
        return {**base, "status": "NO_CHAIN", "detail": "put mid ≤ 0"}
    und = price
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
    base["edge_score"] = round(edge, 1)
    base["pop_pct"] = round(pop, 1)
    base["data_source"] = data_source
    if edge < min_edge:
        return {
            **base,
            "status": "EDGE_BELOW",
            "detail": f"edge {edge:.0f} < min {min_edge:.0f}",
        }
    return {
        **base,
        "status": "PUT_ELIGIBLE",
        "detail": "passes protective-put screens",
    }


def build_holdings_funnel(
    *,
    holdings: Optional[List[dict]] = None,
    tech_map: Optional[dict] = None,
    intent_cfg: Optional[dict] = None,
    aegis_map: Optional[dict] = None,
    resolve_chain: bool = True,
) -> dict:
    """Read-only owned-book funnel: why each holding is or is not a CC / protective-put idea.

    Does not change quality gates. resolve_chain=False skips live/BS contract resolution
    (deterministic share/IV-only pass — used in hermetic tests).
    """
    if holdings is None:
        holdings, _meta = _load_holdings()
        holdings_path = (_meta or {}).get("_holdings_path")
        holdings_mtime = (_meta or {}).get("_holdings_mtime")
    else:
        holdings = [_normalize_holding(x) for x in holdings]
        holdings_path = "caller_supplied"
        holdings_mtime = None
    tech_map = tech_map if tech_map is not None else _load_technicals()
    intent_cfg = intent_cfg if intent_cfg is not None else _load_intent_cfg()
    aegis_map = aegis_map or {}

    # 2026-09-26 (operator): fractional leftovers Schwab still carries after a sale
    # (NOC 0.23 sh, $119) were listed as covered-call refusals and read as positions
    # the operator does not own. Below the dust value they collapse into one line.
    try:
        from options_desk_enterprise import load_desk_config
        dust_mv = float(load_desk_config().get("funnel_dust_max_market_value") or 250.0)
    except Exception:
        dust_mv = 250.0
    totals: Dict[str, dict] = {}
    for h in holdings:
        sym = (h.get("symbol") or "").upper()
        if not sym or h.get("is_cash"):
            continue
        t = totals.setdefault(sym, {"total_shares": 0.0, "accounts": {}})
        t["total_shares"] = round(t["total_shares"] + _f(h.get("shares")), 4)
        acct_key = h.get("account") or ""
        t["accounts"][acct_key] = round(t["accounts"].get(acct_key, 0.0) + _f(h.get("shares")), 4)

    rows: List[dict] = []
    residue: List[dict] = []
    for h in holdings:
        if h.get("is_cash"):
            continue
        sym = (h.get("symbol") or "").upper()
        if not sym:
            continue
        mv_h = _f(h.get("market_value")) or _f(h.get("shares")) * _f(h.get("price"))
        if 0 < mv_h < dust_mv and _f(h.get("shares")) < MIN_HOLDING_SHARES_CC:
            residue.append({"symbol": sym, "account": h.get("account") or "",
                            "shares": round(_f(h.get("shares")), 4), "market_value": round(mv_h, 2)})
            continue
        cc = evaluate_covered_call_status(
            h, tech_map, intent_cfg, aegis_map, resolve_chain=resolve_chain,
        )
        put = evaluate_protective_put_status(
            h, tech_map, resolve_chain=resolve_chain,
        )
        rows.append({
            "symbol": sym,
            "account": h.get("account") or "",
            "shares": cc.get("shares"),
            "market_value": cc.get("market_value"),
            "symbol_total_shares": (totals.get(sym) or {}).get("total_shares"),
            "shares_by_account": (totals.get(sym) or {}).get("accounts") or {},
            "cc": cc,
            "protective_put": put,
        })

    def _count(path: str, status: str) -> int:
        n = 0
        for r in rows:
            node = r.get(path) or {}
            if node.get("status") == status:
                n += 1
        return n

    cc_statuses = sorted({(r.get("cc") or {}).get("status") for r in rows if (r.get("cc") or {}).get("status")})
    summary = {
        "holdings_scanned": len(rows),
        "fractional_residue": {
            "count": len(residue),
            "market_value": round(sum(r["market_value"] for r in residue), 2),
            "dust_max_market_value": dust_mv,
            "positions": residue,
            "note": "Fractional leftovers the broker still carries (e.g. after a sale or dividend reinvest). Not option candidates.",
        },
        "holdings_source": holdings_path,
        "holdings_mtime": holdings_mtime,
        "cc_by_status": {s: _count("cc", s) for s in cc_statuses if s},
        "cc_eligible": _count("cc", "CC_ELIGIBLE") + _count("cc", "INTENT_BYPASS"),
        "cc_need_100_shares": _count("cc", "NEED_100_SHARES"),
        "cc_iv_below": _count("cc", "IV_BELOW_FLOOR"),
        "cc_edge_below": _count("cc", "EDGE_BELOW"),
        "cc_no_chain": _count("cc", "NO_CHAIN"),
        "put_eligible": _count("protective_put", "PUT_ELIGIBLE"),
        "put_mv_below": _count("protective_put", "MV_BELOW"),
        "put_iv_below": _count("protective_put", "IV_BELOW_FLOOR"),
        "min_shares_cc": MIN_HOLDING_SHARES_CC,
        "min_iv_rank": MIN_IV_RANK,
        "min_edge": MIN_EDGE_SCORE,
        "intent_cc": list(intent_cfg.get("covered_call_candidate") or []),
        "resolve_chain": resolve_chain,
        "note": (
            "Backfill from latest holdings of record. Propose CC/protective puts only when "
            "gates + edge/IV/size clear — not every owned name. Named drop reasons for every "
            "row; silent omit is a defect. IV/intent floors are not widened here."
        ),
    }
    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": summary,
        "rows": rows,
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
    props = props or read_proposals()
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
            "option_strategy_guid": p.get("option_strategy_guid"),
            "contract_guid": p.get("contract_guid"),
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
                "option_strategy_guid": p.get("option_strategy_guid"),
                "contract_guid": p.get("contract_guid"),
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
