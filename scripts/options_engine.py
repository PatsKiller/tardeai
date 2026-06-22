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


def _load_holdings() -> Tuple[List[dict], dict]:
    h = _load_json(STATE_DIR / "holdings.json") or {}
    return h.get("holdings") or [], h


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
                if sym and len(sym) <= 6 and sym.isalpha():
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
                if sym and sym not in out:
                    out[sym] = {
                        "symbol": sym,
                        "source": "fused_signal",
                        "confidence": _f(r.get("confidence") or r.get("fused_score"), 0.5),
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
    """0–100 composite edge; turnkey threshold MIN_EDGE_SCORE."""
    pop_s = min(100.0, max(0.0, pop)) * 0.35
    iv_s = min(100.0, iv_rank) * 0.20
    rr_s = min(100.0, rr * 25.0) * 0.20
    cat_s = min(15.0, catalyst_boost)
    conv_s = min(10.0, conviction * 10.0)
    return round(pop_s + iv_s + rr_s + cat_s + conv_s, 1)


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

        target_strike = price * (1 + default_otm)
        if price < 50:
            target_strike = round(target_strike / 0.5) * 0.5
        elif price < 200:
            target_strike = round(target_strike / 2.5) * 2.5
        else:
            target_strike = round(target_strike / 5.0) * 5.0

        chain = _schwab_chain(sym)
        und = _f(chain.get("underlying_price")) or price
        contract = _pick_chain_contract(chain, "call", target_strike, default_dte)
        data_source = "schwab_chain"
        if contract:
            premium = contract["mid"]
            strike = contract["strike"]
            dte = contract["dte"]
            iv = contract.get("iv") or 0.25
            exp = contract.get("exp")
        else:
            data_source = "bs_estimate"
            from portfolio_options import _estimate_premium
            atr = _f(tech.get("atr")) or price * 0.015
            iv_pct = _f(tech.get("iv"))
            premium = _estimate_premium(price, target_strike, atr, iv_pct, default_dte)
            strike = target_strike
            dte = default_dte
            iv = (iv_pct / 100.0) if iv_pct else 0.25
            exp = (_now().date() + timedelta(days=dte)).isoformat()

        iv_rank = _iv_rank_proxy(sym, tech, chain_iv=iv)
        if iv_rank < min_iv and sym not in cc_syms:
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
            catalyst_boost=12.0 if in_intent else 3.0,
            conviction=_f(aegis.get("confidence"), 0.6),
        )
        if in_intent and pop >= MIN_POP_PCT:
            edge = max(edge, pop * 0.55 + 18.0)
        min_edge = MIN_EDGE_CC_INTENT if in_intent else MIN_EDGE_SCORE
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
        proposals.append({
            "id": _proposal_id("covered_call", sym, h.get("account_display") or h.get("account") or "", strike, exp),
            "strategy": "covered_call",
            "symbol": sym,
            "underlying": sym,
            "account": h.get("account_display") or h.get("account") or "",
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
        })
    proposals.sort(key=lambda x: -x["edge_score"])
    return proposals


def generate_defined_risk_proposals(
    convictions: List[dict],
    tech_map: dict,
    owned: set,
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
            continue
        chain = _schwab_chain(sym, strikes=10)
        und = _f(chain.get("underlying_price")) or price
        iv_rank = _iv_rank_proxy(sym, tech)
        if iv_rank < MIN_IV_RANK:
            continue

        conf = _f(c.get("confidence"), 0.5)
        sev = (c.get("severity") or "").lower()
        bullish = sev in ("opportunity", "positive", "bullish", "") or "opportunity" in (c.get("source") or "")

        if bullish and conf >= 0.6:
            target_strike = round(und * 1.04 / 2.5) * 2.5 if und > 50 else round(und * 1.05, 1)
            contract = _pick_chain_contract(chain, "call", target_strike, 35)
            data_source = "schwab_chain"
            if not contract:
                from portfolio_options import _estimate_premium
                atr = _f(tech.get("atr")) or price * 0.02
                iv_pct = _f(tech.get("iv"))
                est = _estimate_premium(und, target_strike, atr, iv_pct, 35)
                if est <= 0:
                    continue
                contract = {"mid": est, "strike": target_strike, "dte": 35,
                              "exp": (_now().date() + timedelta(days=35)).isoformat(), "iv": iv_pct / 100.0 or 0.3}
                data_source = "bs_estimate"
            premium = contract["mid"]
            strike, dte, iv = contract["strike"], contract["dte"], contract.get("iv") or 0.3
            pop = 100.0 - _pop_otm_call(und, strike, max(0.05, iv), dte)
            max_loss = round(premium * 100, 2)
            max_profit = "unlimited"
            breakeven = round(strike + premium, 2)
            rr = premium * 100 / max(strike * 100, 1)
            edge = _edge_score(pop, iv_rank, rr * 0.5, conviction=conf)
            if edge < MIN_EDGE_SCORE + 5:
                continue
            proposals.append({
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
                "max_profit": max_profit,
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
            })
        elif conf >= 0.55:
            target_strike = round(und * 0.92 / 2.5) * 2.5 if und > 50 else round(und * 0.93, 1)
            contract = _pick_chain_contract(chain, "put", target_strike, 30)
            data_source = "schwab_chain"
            if not contract:
                from portfolio_options import _estimate_premium
                atr = _f(tech.get("atr")) or price * 0.02
                iv_pct = _f(tech.get("iv"))
                est = _estimate_premium(und, target_strike, atr, iv_pct, 30)
                if est <= 0:
                    continue
                contract = {"mid": est, "strike": target_strike, "dte": 30,
                              "exp": (_now().date() + timedelta(days=30)).isoformat(), "iv": iv_pct / 100.0 or 0.3}
                data_source = "bs_estimate"
            premium = contract["mid"]
            strike, dte, iv = contract["strike"], contract["dte"], contract.get("iv") or 0.3
            pop = _pop_otm_put(und, strike, max(0.05, iv), dte)
            max_profit = round(premium * 100, 2)
            max_loss = round((strike - premium) * 100, 2)
            breakeven = round(strike - premium, 2)
            rr = max_profit / max(max_loss, 1)
            edge = _edge_score(pop, iv_rank, rr, conviction=conf)
            if edge < MIN_EDGE_SCORE or pop < MIN_POP_PCT:
                continue
            proposals.append({
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
                    "technical": f"Defined-risk entry, POP {pop:.0f}%",
                }),
                "quality_pass": True,
                "data_source": data_source,
                "execution_note": _execution_note(
                    "Verify buying power + SSDI income context before entry."
                ),
                "generated_at": _iso(),
            })
    proposals.sort(key=lambda x: -x["edge_score"])
    return proposals[:12]


def generate_credit_spread_proposals(
    convictions: List[dict],
    tech_map: dict,
) -> List[dict]:
    """Bull put / bear call credit spreads on high-conviction names (defined risk)."""
    proposals: List[dict] = []
    for c in convictions[:15]:
        sym = c["symbol"]
        tech = tech_map.get(sym) or {}
        price = _f(tech.get("price") or tech.get("last"))
        if price <= 0:
            continue
        chain = _schwab_chain(sym, strikes=12)
        und = _f(chain.get("underlying_price")) or price
        iv_rank = _iv_rank_proxy(sym, tech)
        if iv_rank < MIN_IV_RANK:
            continue
        conf = _f(c.get("confidence"), 0.5)
        if conf < 0.58:
            continue
        # Bull put credit spread: sell higher strike put, buy lower strike put
        short_strike = round(und * 0.93 / 2.5) * 2.5 if und > 50 else round(und * 0.94, 1)
        long_strike = round(short_strike * 0.95 / 2.5) * 2.5 if und > 50 else round(short_strike * 0.96, 1)
        short_c = _pick_chain_contract(chain, "put", short_strike, 30)
        long_c = _pick_chain_contract(chain, "put", long_strike, 30)
        if not short_c or not long_c:
            continue
        net_credit = round(max(0.05, short_c["mid"] - long_c["mid"]), 2)
        if net_credit < 0.10:
            continue
        width = short_strike - long_strike
        max_loss = round((width - net_credit) * 100, 2)
        pop = _pop_otm_put(und, short_strike, max(0.05, short_c.get("iv") or 0.25), short_c["dte"])
        rr = (net_credit * 100) / max(max_loss, 1)
        edge = _edge_score(pop, iv_rank, rr, conviction=conf)
        if edge < MIN_EDGE_SCORE or pop < MIN_POP_PCT:
            continue
        proposals.append({
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
            "execution_note": _execution_note(),
            "generated_at": _iso(),
        })
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

    cc = generate_covered_call_proposals(holdings, tech_map, intent_cfg, aegis_map)
    convictions = _high_conviction_symbols()
    dr = generate_defined_risk_proposals(convictions, tech_map, owned)
    spreads = generate_credit_spread_proposals(convictions, tech_map)
    pool = cc + dr + spreads
    strict = [p for p in pool if p.get("quality_pass") and p.get("edge_score", 0) >= MIN_EDGE_SCORE]
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

    seen = set()
    deduped = []
    for p in strict:
        key = (p.get("strategy"), p.get("symbol"), p.get("strike"), p.get("account"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)
    all_p = sorted(deduped, key=lambda x: -x["edge_score"])

    out = {
        "generated_at": _iso(),
        "count": len(all_p),
        "covered_calls": len(cc),
        "defined_risk": len(dr),
        "credit_spreads": len(spreads),
        "fallback_tier_used": fallback_used,
        "quality_gate": {
            "min_edge_score": MIN_EDGE_SCORE,
            "min_pop_pct": MIN_POP_PCT,
            "min_iv_rank": MIN_IV_RANK,
            "relaxed_edge_floor": MIN_EDGE_CC_INTENT,
        },
        "proposals": all_p,
        "strategy_overview": {
            "total_edge_avg": round(sum(p["edge_score"] for p in all_p) / max(len(all_p), 1), 1),
            "avg_pop": round(sum(p.get("pop_pct", 50) for p in all_p) / max(len(all_p), 1), 1),
            "income_opportunities": sum(1 for p in all_p if p["strategy"] == "covered_call"),
            "conviction_plays": sum(1 for p in all_p if p["strategy"] != "covered_call"),
            "note": "High-quality only — proposals below edge/POP gates are excluded.",
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
    return {
        "captured_at": _iso(),
        "options": {
            "proposal_count": props.get("count", 0),
            "cache_age_min": age_min,
            "fallback_tier_used": props.get("fallback_tier_used", False),
            "open_legs": mon.get("position_count", 0),
            "needs_action": mon.get("needs_action_count", 0),
        },
        "trades": {"pending_proposals": pending},
        "watchlist": {"stale_active_7d": wl_stale},
        "rotation": {"pending_recommendations": rot_pending},
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

    out = {
        "monitored_at": _iso(),
        "position_count": len(monitored),
        "still_working": working,
        "needs_action_count": len(needs_action),
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
        "proposals": props.get("strategy_overview") or {},
        "monitor": mon.get("summary") or {},
        "proposal_count": props.get("count", 0),
        "open_positions": mon.get("position_count", 0),
        "needs_action": mon.get("needs_action_count", 0),
        "quality_gate": props.get("quality_gate"),
    }


def filter_proposals(
    proposals: List[dict],
    *,
    symbol: str = "",
    sector: str = "",
    strategy: str = "",
    min_dte: int = 0,
    max_dte: int = 999,
    min_pop: float = 0,
    min_edge: float = 0,
) -> List[dict]:
    sym_u = symbol.upper()
    out = []
    for p in proposals:
        if sym_u and sym_u not in (p.get("symbol") or "").upper():
            continue
        if strategy and p.get("strategy") != strategy:
            continue
        dte = int(p.get("dte") or 0)
        if dte < min_dte or dte > max_dte:
            continue
        if _f(p.get("pop_pct")) < min_pop:
            continue
        if _f(p.get("edge_score")) < min_edge:
            continue
        if sector:
            # sector filter optional — enrichment not always on proposal row
            pass
        out.append(p)
    return out


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