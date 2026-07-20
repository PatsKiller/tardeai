"""deep_itm_generator.py — deep-ITM call (stock replacement) paper proposal generator.

Pipeline: eligible underlying → lib.strategy_research.options_chain.deep_itm_call_analysis
(read-only, honest-degrade feasibility engine) → config gates (delta / DTE / spread /
OI / volume / earnings / capital-vs-shares) → score (feasibility × underlying
conviction) → proposal rows in the SAME shape options_engine's covered-call rows use →
options_desk_enterprise.sync_approval_queue (the existing options_approval_queue,
manual-review lane).

SAFETY INVARIANTS (test-enforced):
  • Every proposal carries educational_paper_model=True, requires_manual_review=True,
    paper_only=True, execution_mode='manual_review_only', auto_eligible=False.
  • enterprise.live_eligible is ALWAYS False with an explicit paper-model block, so
    options_desk_enterprise.resolve_approval refuses live approval and
    check_preflight_approval refuses live submit (desk fail-closed gates).
  • No broker submit / order / 2FA module is imported here — chain reads happen
    inside the AST-proven read-only options_chain research adapter.
  • Chains degrade honestly (weekends/holidays/no link) — a degraded underlying
    yields a per-underlying reason, never fabricated numbers.
"""
from __future__ import annotations

import json
import datetime as _dt
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

STRATEGY_ID = "deep_itm_call"
DISCOVERY_REF = {
    "source": "hermes_discovery_candidates",
    "candidate_id": 339,
    "label": "Deep ITM Call (stock replacement)",
    "candidate_status": "APPROVED_RESEARCH_ONLY",
}
PAPER_MODEL_BLOCK = (
    "educational_paper_model — paper/manual-review lane only; no live execution path"
)
EXECUTION_NOTE = (
    "PAPER MODEL — educational stock-replacement analysis. Manual review only; "
    "no auto-execution, no live order path. Outcomes feed the deep_itm_call "
    "validation gate (30 paper outcomes, PF>1.3, WR>55%) before any live consideration."
)

DEFAULT_SELECTION_POLICY: Dict[str, Any] = {
    "delta_range": [0.80, 0.95],
    "dte_buckets": [60, 90, 180],
    "max_spread_pct": 10.0,
    "min_open_interest": 100,
    "min_volume": 1,
    "allow_earnings_before_expiry": False,
    "earnings_flag_override": False,
    "allow_delta_proxy": True,
    "max_capital_pct_vs_shares": 0.35,
    "max_underlyings_per_run": 15,
    "max_proposals_per_run": 5,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if x != x else x  # NaN guard


def load_pipeline_config() -> dict:
    """Strategy YAML (config/strategies/deep_itm_call.yaml) with policy defaults filled."""
    try:
        from strategy_config_loader import load_strategy_config
        cfg = load_strategy_config(STRATEGY_ID) or {}
    except Exception:
        cfg = {}
    policy = dict(DEFAULT_SELECTION_POLICY)
    policy.update(cfg.get("selection_policy") or {})
    cfg["selection_policy"] = policy
    cfg.setdefault("strategy_id", STRATEGY_ID)
    cfg.setdefault("paper_only", True)
    cfg.setdefault("execution_mode", "manual_review_only")
    cfg.setdefault(
        "underlying_quality_gate",
        {"watchlist_verdicts": ["strong_buy", "buy"], "include_current_holdings": True,
         "conviction_floor": 0.55},
    )
    return cfg


def _proposal_id(strategy: str, sym: str, account: str, strike: Any, expiration: str = "",
                 trade_date: str = "") -> str:
    """Stable-within-a-day proposal id — SAME format as options_engine._proposal_id."""
    acct = re.sub(r"[^a-z0-9]+", "_", (account or "default").lower()).strip("_")[:22]
    exp = (expiration or "")[:10].replace("-", "")
    try:
        st = f"{float(strike):.4f}".replace(".", "p")
    except (TypeError, ValueError):
        st = str(strike or "0").replace(".", "p")
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


# ── config gates over one analysis candidate row ─────────────────────────────

def evaluate_candidate_gates(
    candidate: dict,
    bucket: dict,
    policy: dict,
) -> Dict[str, Any]:
    """Apply the strategy's selection gates to one deep_itm_call_analysis candidate.

    Returns {"pass": bool, "rejects": [...], "flags": [...]}. Rejections are honest
    machine-readable reasons; flags are non-fatal disclosures (e.g. delta proxy mode).
    """
    rejects: List[str] = []
    flags: List[str] = []
    cflags = candidate.get("flags") or {}

    # Quotable data
    if cflags.get("no_quote") or candidate.get("mid") is None:
        rejects.append("no_quotable_mid")

    # Delta band (greeks path) or disclosed proxy (no-greeks chains)
    lo, hi = sorted(float(x) for x in (policy.get("delta_range") or [0.80, 0.95]))
    delta = candidate.get("delta")
    mode = bucket.get("selection_mode") or ("delta" if delta is not None else "itm_pct_proxy")
    if delta is not None:
        if not (lo <= abs(float(delta)) <= hi):
            rejects.append(f"delta_{abs(float(delta)):.2f}_outside_[{lo},{hi}]")
    elif mode == "itm_pct_proxy":
        if policy.get("allow_delta_proxy", True):
            flags.append("delta_proxy_itm_depth")
        else:
            rejects.append("no_usable_delta_and_proxy_disallowed")
    else:
        rejects.append("no_usable_delta")

    # DTE bucket membership
    buckets = [int(b) for b in (policy.get("dte_buckets") or [])]
    if int(bucket.get("target_dte") or 0) not in buckets:
        rejects.append(f"dte_bucket_{bucket.get('target_dte')}_not_configured")

    # Spread
    spread = candidate.get("spread_pct")
    max_spread = _f(policy.get("max_spread_pct"), 10.0)
    if spread is None:
        rejects.append("spread_unquotable")
    elif float(spread) > max_spread:
        rejects.append(f"spread_{float(spread):.1f}pct_gt_{max_spread}")

    # Open interest / volume
    oi = int(_f(candidate.get("oi")))
    if oi < int(policy.get("min_open_interest") or 0):
        rejects.append(f"oi_{oi}_lt_{policy.get('min_open_interest')}")
    vol = int(_f(candidate.get("volume")))
    if vol < int(policy.get("min_volume") or 0):
        rejects.append(f"volume_{vol}_lt_{policy.get('min_volume')}")

    # Earnings before expiry — reject unless explicitly flagged by operator config
    ebe = cflags.get("earnings_before_expiry")
    if ebe is True:
        if policy.get("allow_earnings_before_expiry") or policy.get("earnings_flag_override"):
            flags.append("earnings_before_expiry_operator_flagged")
        else:
            rejects.append("earnings_before_expiry")
    elif ebe is None:
        flags.append("earnings_unknown")

    # Capital efficiency vs 100 shares
    cvs = candidate.get("capital_vs_100_shares") or {}
    ratio = cvs.get("capital_ratio_pct")
    cap = _f(policy.get("max_capital_pct_vs_shares"), 0.35) * 100.0
    if ratio is None:
        rejects.append("capital_ratio_unknown")
    elif float(ratio) > cap:
        rejects.append(f"capital_ratio_{float(ratio):.1f}pct_gt_{cap:.0f}")

    return {"pass": not rejects, "rejects": rejects, "flags": flags, "selection_mode": mode}


# ── scoring ──────────────────────────────────────────────────────────────────

# IV-rank edge modifiers (2026-07-06) — ADVISORY ONLY, bounded, NEVER a gate:
# a rich-IV proposal still queues (with a disclosed pay-up warning); the
# modifier only nudges ranking. Unavailable/insufficient IV history → 1.0.
IV_EDGE_MODIFIER_CHEAP = 1.10   # verdict extrinsic_cheap  (rank < 30)
IV_EDGE_MODIFIER_RICH = 0.90    # verdict extrinsic_rich   (rank > 70)
IV_RICH_FLAG = "iv_rich_pay_up_warning"


def apply_iv_edge_modifier(edge: float, iv_context: Optional[dict]) -> tuple[float, float]:
    """(adjusted_edge, modifier): ×1.1 cheap · ×0.9 rich · ×1.0 otherwise.

    Bounded to [0, 100]; {"available": False} (including honest
    insufficient-history) always yields modifier 1.0. This adjusts ranking
    only — it never rejects a candidate.
    """
    ctx = iv_context or {}
    verdict = ctx.get("verdict") if ctx.get("available") else None
    mod = (IV_EDGE_MODIFIER_CHEAP if verdict == "extrinsic_cheap"
           else IV_EDGE_MODIFIER_RICH if verdict == "extrinsic_rich" else 1.0)
    adjusted = round(min(100.0, max(0.0, _f(edge) * mod)), 1)
    return adjusted, mod


def score_candidate(analysis: dict, candidate: dict, conviction: float) -> float:
    """Winner score = chain feasibility × underlying conviction (0-100 scale).

    Feasibility uses the analysis' own deep_itm_call feasibility score when present,
    blended with the specific contract's liquidity score; conviction (0-1) comes from
    watchlist verdict / holdings intel. No fabricated inputs — missing pieces lower
    the score, they are never invented.
    """
    feas = (analysis.get("feasibility") or {}).get("score")
    liq = candidate.get("liquidity_score")
    parts = [p for p in (feas, liq) if p is not None]
    base = sum(float(p) for p in parts) / len(parts) if parts else 0.0
    conv = max(0.0, min(1.0, _f(conviction, 0.0)))
    return round(base * conv, 1)


# ── proposal row (same shape as options_engine covered-call rows) ────────────

def _build_proposal_row(
    underlying: dict,
    analysis: dict,
    bucket: dict,
    candidate: dict,
    gate_result: dict,
    config: dict,
) -> dict:
    sym = (underlying.get("symbol") or "").upper()
    exp = str(bucket.get("exp") or "")
    strike = candidate.get("strike")
    mid = _f(candidate.get("mid"))
    spot = _f(analysis.get("underlying_price"))
    conviction = _f(underlying.get("conviction"), 0.0)
    edge_base = score_candidate(analysis, candidate, conviction)
    iv_ctx = analysis.get("iv_context") or {"available": False,
                                            "reason": "iv context not computed"}
    edge, iv_mod = apply_iv_edge_modifier(edge_base, iv_ctx)
    delta = candidate.get("delta")

    # IV rich → disclosed flag on the card (advisory; NEVER a reject)
    disclosed_flags = list(gate_result.get("flags") or [])
    if iv_ctx.get("available") and iv_ctx.get("verdict") == "extrinsic_rich":
        disclosed_flags.append(IV_RICH_FLAG)

    try:
        import options_desk_enterprise as ent
        tier = ent.desk_tier(edge)
    except Exception:
        tier = "A" if edge >= 72 else ("B" if edge >= 62 else "C")

    reasoning_bits = [
        f"Deep ITM stock replacement: Δ{abs(float(delta)):.2f}" if delta is not None
        else "Deep ITM stock replacement (ITM-depth proxy — chain carried no greeks)",
        f"debit ${mid * 100:,.0f} controls ~100 shares (${spot * 100:,.0f}) = "
        f"{_f((candidate.get('capital_vs_100_shares') or {}).get('capital_ratio_pct')):.0f}% of share capital",
        f"extrinsic ${_f(candidate.get('extrinsic_value')):.2f}, breakeven ${_f(candidate.get('breakeven')):.2f} "
        f"({_f(candidate.get('breakeven_move_pct')):+.1f}%)",
        f"underlying conviction {conviction:.0%} ({underlying.get('conviction_source') or 'unknown'})",
    ]
    if iv_ctx.get("available"):
        reasoning_bits.append(
            f"IV rank {_f(iv_ctx.get('iv_rank')):.0f}% — "
            f"{iv_ctx.get('verdict_label') or iv_ctx.get('verdict')}")
    if disclosed_flags:
        reasoning_bits.append("flags: " + ", ".join(disclosed_flags))
    reasoning_bits.append("PAPER MODEL — manual review only, never auto-executed")

    row = {
        "id": _proposal_id(STRATEGY_ID, sym, "paper_model", strike, exp),
        "strategy": STRATEGY_ID,
        "strategy_family": config.get("family") or "stock_replacement",
        "symbol": sym,
        "underlying": sym,
        "account": "",
        "account_display": "Paper Model (educational)",
        "broker": "paper_model",
        "side": "BUY",
        "option_type": "call",
        "strike": strike,
        "expiration": exp,
        "dte": bucket.get("dte"),
        "contracts": 1,
        "premium": round(mid, 2),
        "premium_total": round(mid * 100.0, 2),
        "underlying_price": round(spot, 2),
        "pop_pct": round(abs(float(delta)) * 100.0, 1) if delta is not None else None,
        "max_profit": "unlimited",
        "max_loss": candidate.get("max_loss"),
        "breakeven": candidate.get("breakeven"),
        "breakeven_move_pct": candidate.get("breakeven_move_pct"),
        "intrinsic_value": candidate.get("intrinsic_value"),
        "extrinsic_value": candidate.get("extrinsic_value"),
        "capital_vs_100_shares": candidate.get("capital_vs_100_shares"),
        "risk_reward": None,
        "expected_value": None,
        "edge_score": edge,
        "iv_rank": (round(_f(iv_ctx.get("iv_rank")), 1)
                    if iv_ctx.get("available") and iv_ctx.get("iv_rank") is not None
                    else None),
        "iv_context": iv_ctx,
        "delta": delta,
        "oi": candidate.get("oi"),
        "volume": candidate.get("volume"),
        "spread_pct": candidate.get("spread_pct"),
        "liquidity_score": candidate.get("liquidity_score"),
        "severity": "info",
        "recommended_action": "Review Deep ITM Call (paper model)",
        "action_buttons": [
            {"action": "review_chain", "label": "View Chain"},
            {"action": "hold", "label": "Pass"},
        ],
        "reasoning": " · ".join(reasoning_bits),
        "quality_pass": True,
        "data_source": "schwab_chain",
        # ── paper/educational lane flags (HARD SAFETY — test-enforced) ──
        "educational_paper_model": True,
        "requires_manual_review": True,
        "paper_only": True,
        "execution_mode": "manual_review_only",
        "execution_label": "Paper model · manual review only",
        "auto_eligible": False,
        "execution_note": EXECUTION_NOTE,
        "desk_tier": tier,
        "enterprise": {
            "tier": tier,
            "live_eligible": False,          # desk fail-closed: approve + submit both refuse
            "blocks": [PAPER_MODEL_BLOCK],
            "earnings": {
                "in_blackout": bool((candidate.get("flags") or {}).get("earnings_before_expiry")),
                "next_earnings": analysis.get("next_earnings_date"),
            },
            "liquidity": {
                "pass": True,
                "oi": candidate.get("oi"),
                "volume": candidate.get("volume"),
                "bid_ask_spread_pct": candidate.get("spread_pct"),
                "mid": candidate.get("mid"),
                "issues": [],
            },
            "vol_analytics": None,
            "approval_required": True,
            "paper_model": True,
        },
        "meta": {
            "discovery_ref": dict(DISCOVERY_REF),
            "selection_mode": gate_result.get("selection_mode"),
            "gate_flags": disclosed_flags,
            "iv_edge": {"base_edge": edge_base, "modifier": iv_mod,
                        "adjusted_edge": edge,
                        "verdict": iv_ctx.get("verdict") if iv_ctx.get("available") else None},
            "selection_policy": dict(config.get("selection_policy") or {}),
            "underlying_intel": {
                "conviction": conviction,
                "conviction_source": underlying.get("conviction_source"),
                "watchlist_verdict": underlying.get("verdict"),
                "held_shares": underlying.get("held_shares"),
            },
            "dte_bucket": {
                "target_dte": bucket.get("target_dte"),
                "exp": bucket.get("exp"),
                "dte": bucket.get("dte"),
            },
            "analysis": {
                "banner": analysis.get("banner"),
                "generated_at": analysis.get("generated_at"),
                "underlying_price": analysis.get("underlying_price"),
                "delta_range": analysis.get("delta_range"),
                "next_earnings_date": analysis.get("next_earnings_date"),
                "chain_liquidity_score": analysis.get("chain_liquidity_score"),
                "feasibility": analysis.get("feasibility"),
                "iv_context": iv_ctx,
                "candidate": candidate,
            },
        },
        "generated_at": _now_iso(),
    }
    return row


# ── main generator ───────────────────────────────────────────────────────────

def generate_deep_itm_proposals(
    underlyings: List[dict],
    config: Optional[dict] = None,
    *,
    analysis_fn: Optional[Callable[..., dict]] = None,
) -> dict:
    """Run deep_itm_call_analysis per eligible underlying and gate into paper proposals.

    underlyings: [{symbol, conviction (0-1), conviction_source, verdict?, held_shares?}, ...]
    analysis_fn: injectable for tests; defaults to the read-only research engine.

    Returns {"proposals": [...], "per_underlying": [...], "generated_at": ...}.
    Chain-unavailable underlyings degrade honestly with a per-underlying reason.
    """
    cfg = config or load_pipeline_config()
    policy = dict(DEFAULT_SELECTION_POLICY)
    policy.update(cfg.get("selection_policy") or {})
    quality = cfg.get("underlying_quality_gate") or {}
    floor = _f(quality.get("conviction_floor"), 0.55)

    if analysis_fn is None:
        from lib.strategy_research.options_chain import deep_itm_call_analysis as analysis_fn  # noqa: F811

    proposals: List[dict] = []
    per_underlying: List[dict] = []
    cap = int(policy.get("max_underlyings_per_run") or 15)

    for u in (underlyings or [])[:cap]:
        sym = (u.get("symbol") or "").upper()
        if not sym:
            continue
        conviction = _f(u.get("conviction"), 0.0)
        if conviction < floor:
            per_underlying.append({"symbol": sym, "status": "skipped",
                                   "reason": f"conviction {conviction:.2f} below floor {floor:.2f}"})
            continue

        analysis = analysis_fn(
            sym,
            delta_range=tuple(policy.get("delta_range") or (0.80, 0.95)),
            dte_buckets=list(policy.get("dte_buckets") or [60, 90, 180]),
        )
        if not analysis.get("available"):
            per_underlying.append({"symbol": sym, "status": "degraded",
                                   "reason": analysis.get("reason") or "chain unavailable"})
            continue

        kept = 0
        reject_notes: List[str] = []
        for bucket in analysis.get("dte_buckets") or []:
            if not bucket.get("available"):
                reject_notes.append(
                    f"bucket {bucket.get('target_dte')}d: {bucket.get('reason') or 'unavailable'}")
                continue
            best_row = None
            for candidate in bucket.get("candidates") or []:
                gate = evaluate_candidate_gates(candidate, bucket, policy)
                if gate["pass"]:
                    best_row = _build_proposal_row(u, analysis, bucket, candidate, gate, cfg)
                    break
                reject_notes.append(
                    f"bucket {bucket.get('target_dte')}d ${candidate.get('strike')}: "
                    + ",".join(gate["rejects"]))
            if best_row:
                proposals.append(best_row)
                kept += 1
        per_underlying.append({
            "symbol": sym,
            "status": "ok" if kept else "no_candidates_passed_gates",
            "proposals": kept,
            "notes": reject_notes[:6],
        })

    proposals.sort(key=lambda p: -_f(p.get("edge_score")))
    return {
        "generated_at": _now_iso(),
        "strategy": STRATEGY_ID,
        "discovery_ref": dict(DISCOVERY_REF),
        "count": len(proposals),
        "proposals": proposals,
        "per_underlying": per_underlying,
    }


# ── queue integration (existing options desk approval queue) ─────────────────

def submit_to_desk_queue(proposals: List[dict]) -> dict:
    """Upsert paper proposals into the EXISTING options_approval_queue via the desk's
    own writer (options_desk_enterprise.sync_approval_queue) — same table, same shape
    as covered-call/CSP proposals. Fail-closed: refuses any row missing the paper
    flags or claiming live eligibility."""
    for p in proposals:
        ent_flags = p.get("enterprise") or {}
        if (not p.get("educational_paper_model")
                or not p.get("requires_manual_review")
                or not p.get("paper_only")
                or p.get("execution_mode") != "manual_review_only"
                or p.get("auto_eligible")
                or ent_flags.get("live_eligible")):
            return {"ok": False,
                    "error": f"fail-closed: proposal {p.get('id')} missing paper/manual "
                             "flags or claiming live eligibility — refusing queue write"}
    try:
        import options_desk_enterprise as ent_mod
        return ent_mod.sync_approval_queue(list(proposals))
    except Exception as e:  # DB down / import failure → honest failure, never partial
        return {"ok": False, "error": str(e)[:200]}


if __name__ == "__main__":
    # Smoke: config load only (generation is driven by scripts/options_strategy_scanner.py)
    print(json.dumps({"config_loaded": bool(load_pipeline_config()),
                      "strategy": STRATEGY_ID}, indent=2))
