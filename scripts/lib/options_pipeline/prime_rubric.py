"""prime_rubric.py — prime-readiness rubric for the Alpaca paper options lane (Stage 3, Part E).

Scores an options_approval_queue row (deep-ITM paper-model proposals first)
across 10 weighted components (each 0-100), producing a prime_json blob with an
overall prime_score 0-100 and a verdict LABEL:

    < 40    NOT_PRIME
    40-60   PAPER_ONLY
    60-80   PRIME_FOR_PAPER
    >= 80   READY_FOR_LIVE_REVIEW_OPERATOR_ONLY

ADVISORY ONLY — HARD INVARIANTS (test-enforced by grep + AST in
tests/test_options_prime_rubric.py):
  • The verdict is a LABEL, nothing more. This module NEVER transitions queue
    status, never writes any status column, never places or previews an order,
    and never imports the alpaca_paper submit lane (or any broker/HTTP module).
    READY_FOR_LIVE_REVIEW_OPERATOR_ONLY is deliberately NOT the state-machine
    string — reaching READY_FOR_LIVE_REVIEW stays an operator-only transition
    owned by lib.options_pipeline.alpaca_paper.
  • Honest degradation: unavailable inputs score neutral (50) with an explicit
    note, or are excluded with weight renormalization (paper_fill_quality) —
    numbers are never fabricated.
  • The ONLY DB write surface is persist_prime(): one UPDATE merging
    meta.prime_json on the queue row. Reads follow the db_adapter
    one-statement rule.

Component scores (0-100 each; weights sum to 1.0):
  spread_score              tighter bid/ask spread = higher (0 at max_spread_pct)
  oi_volume_score           log-scaled open interest (70%) + volume (30%)
  delta_fit_score           100 inside the strategy's delta window; -10/0.01 outside
  extrinsic_score           lower extrinsic % of premium = higher (deep-ITM: 0 at 20%)
  breakeven_distance_score  smaller breakeven move = higher (0 at +10%)
  iv_rank_score             100 - IV rank (cheap = high); unavailable → 50 + note
  earnings_risk_score       earnings before expiry flagged → 15; unknown → 50; clear → 100
  account_sizing_score      min(premium vs max_premium_paper cap, premium vs portfolio)
  thesis_freshness_score    watchlist research/CIO note age: 100 ≤7d → 0 at 90d
  paper_fill_quality_score  fill-vs-mid slippage when an Alpaca fill exists;
                            no fill → None and EXCLUDED from the weighted sum
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

RUBRIC_ENGINE = "options_prime_rubric_v1"

# Verdict LABELS (deliberately distinct from queue statuses — see module doc).
VERDICT_NOT_PRIME = "NOT_PRIME"
VERDICT_PAPER_ONLY = "PAPER_ONLY"
VERDICT_PRIME_FOR_PAPER = "PRIME_FOR_PAPER"
VERDICT_LIVE_REVIEW_LABEL = "READY_FOR_LIVE_REVIEW_OPERATOR_ONLY"

VERDICT_BANDS = (
    (40.0, VERDICT_NOT_PRIME),          # score < 40
    (60.0, VERDICT_PAPER_ONLY),         # 40 <= score < 60
    (80.0, VERDICT_PRIME_FOR_PAPER),    # 60 <= score < 80
    (None, VERDICT_LIVE_REVIEW_LABEL),  # score >= 80
)

WEIGHTS: Dict[str, float] = {
    "spread_score": 0.12,
    "oi_volume_score": 0.10,
    "delta_fit_score": 0.12,
    "extrinsic_score": 0.12,
    "breakeven_distance_score": 0.10,
    "iv_rank_score": 0.08,
    "earnings_risk_score": 0.10,
    "account_sizing_score": 0.10,
    "thesis_freshness_score": 0.08,
    "paper_fill_quality_score": 0.08,
}

# Tunables (documented so the math is auditable)
DEFAULT_MAX_SPREAD_PCT = 10.0     # spread_score hits 0 here
DEFAULT_DELTA_WINDOW = (0.80, 0.95)
EXTRINSIC_ZERO_AT_PCT = 20.0      # extrinsic 20% of premium → 0
BREAKEVEN_ZERO_AT_PCT = 10.0      # +10% move to breakeven → 0
EARNINGS_FLAGGED_SCORE = 15.0
NEUTRAL_SCORE = 50.0
DEFAULT_MAX_PREMIUM_PAPER = 5000.0
PORTFOLIO_FREE_PCT = 0.25         # ≤0.25% of portfolio → 100
PORTFOLIO_ZERO_AT_PCT = 2.0       # 2% of portfolio → 0
FRESH_FULL_DAYS = 7.0             # note ≤7d old → 100
FRESH_ZERO_DAYS = 90.0            # note 90d old → 0
FILL_SLIP_ZERO_AT_PCT = 4.0       # fill 4% over mid → 0

# Queue statuses the --all-queued CLI sweep scores. String literals on purpose:
# this module must not import the alpaca_paper lane (test-enforced).
SCOREABLE_STATUSES = (
    "pending", "approved",
    "READY_FOR_ALPACA_PAPER", "ALPACA_PAPER_SUBMITTED", "ALPACA_PAPER_FILLED",
    "ALPACA_PAPER_CLOSED", "OUTCOME_RECORDED", "READY_FOR_LIVE_REVIEW",
)

Executor = Callable[..., Any]  # (sql, params=None, fetch=None) -> rows | True | None


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x  # NaN guard


def _clamp(x: float) -> float:
    return round(min(100.0, max(0.0, x)), 1)


def _default_executor() -> Executor:
    from db_adapter import _execute
    return _execute


def _parse_ts(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _jload(v: Any) -> dict:
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except (TypeError, ValueError):
            v = {}
    return v if isinstance(v, dict) else {}


# ── component scorers (pure; each returns (score|None, detail, inputs)) ──────

Component = Tuple[Optional[float], str, Dict[str, Any]]


def spread_score(spread_pct: Any, max_spread_pct: float = DEFAULT_MAX_SPREAD_PCT) -> Component:
    s = _f(spread_pct)
    if s is None:
        return 0.0, "spread unquotable — scored 0 (fail-honest)", {"spread_pct": None}
    score = _clamp(100.0 * (1.0 - s / max_spread_pct))
    return score, f"bid/ask spread {s:.2f}% (0 at {max_spread_pct:.0f}%)", {
        "spread_pct": s, "max_spread_pct": max_spread_pct}


def oi_volume_score(oi: Any, volume: Any) -> Component:
    o = max(0.0, _f(oi) or 0.0)
    v = max(0.0, _f(volume) or 0.0)
    # log-scaled: OI 100→50, 1000→100 · volume 10→50, 100→100
    oi_pts = _clamp(50.0 * math.log10(o / 10.0)) if o > 10 else 0.0
    vol_pts = _clamp(50.0 * math.log10(v)) if v > 1 else 0.0
    score = _clamp(0.7 * oi_pts + 0.3 * vol_pts)
    return score, f"OI {int(o)} (pts {oi_pts:.0f}) · volume {int(v)} (pts {vol_pts:.0f}), 70/30 blend", {
        "oi": int(o), "volume": int(v), "oi_pts": oi_pts, "vol_pts": vol_pts}


def delta_fit_score(delta: Any, window: Tuple[float, float] = DEFAULT_DELTA_WINDOW) -> Component:
    lo, hi = sorted(float(x) for x in window)
    d = _f(delta)
    if d is None:
        return NEUTRAL_SCORE, "no usable delta (ITM-depth proxy mode) — neutral 50", {
            "delta": None, "window": [lo, hi]}
    ad = abs(d)
    dist = 0.0 if lo <= ad <= hi else (lo - ad if ad < lo else ad - hi)
    score = _clamp(100.0 - dist * 1000.0)  # 0.05 outside → 50, 0.10 outside → 0
    detail = (f"Δ{ad:.2f} inside target window [{lo:.2f}, {hi:.2f}]" if dist == 0
              else f"Δ{ad:.2f} is {dist:.2f} outside target window [{lo:.2f}, {hi:.2f}]")
    return score, detail, {"delta": ad, "window": [lo, hi], "distance": round(dist, 4)}


def extrinsic_score(extrinsic_value: Any, premium: Any) -> Component:
    ext, prem = _f(extrinsic_value), _f(premium)
    if ext is None or prem is None or prem <= 0:
        return NEUTRAL_SCORE, "extrinsic/premium unavailable — neutral 50", {
            "extrinsic_value": ext, "premium": prem}
    pct = max(0.0, ext / prem * 100.0)
    score = _clamp(100.0 * (1.0 - pct / EXTRINSIC_ZERO_AT_PCT))
    return score, f"extrinsic ${ext:.2f} = {pct:.1f}% of premium (deep-ITM: lower is better, 0 at {EXTRINSIC_ZERO_AT_PCT:.0f}%)", {
        "extrinsic_value": ext, "premium": prem, "extrinsic_pct": round(pct, 2)}


def breakeven_distance_score(breakeven_move_pct: Any) -> Component:
    m = _f(breakeven_move_pct)
    if m is None:
        return NEUTRAL_SCORE, "breakeven move unavailable — neutral 50", {"breakeven_move_pct": None}
    if m <= 0:
        return 100.0, f"breakeven {m:+.1f}% — already at/below spot", {"breakeven_move_pct": m}
    score = _clamp(100.0 * (1.0 - m / BREAKEVEN_ZERO_AT_PCT))
    return score, f"needs {m:+.1f}% move to breakeven (0 at +{BREAKEVEN_ZERO_AT_PCT:.0f}%)", {
        "breakeven_move_pct": m}


def iv_rank_score(iv_context: Any) -> Component:
    ctx = iv_context if isinstance(iv_context, dict) else {}
    if not ctx.get("available"):
        reason = ctx.get("reason") or "iv context unavailable"
        return NEUTRAL_SCORE, f"IV rank unavailable ({reason}) — neutral 50, noted", {
            "available": False, "reason": reason, "days": ctx.get("days")}
    rank = _f(ctx.get("iv_rank"))
    if rank is None:
        return NEUTRAL_SCORE, "IV context available but rank missing — neutral 50", {"available": True}
    score = _clamp(100.0 - rank)
    return score, f"IV rank {rank:.0f}% ({ctx.get('verdict_label') or ctx.get('verdict') or 'n/a'}) — cheap is high", {
        "available": True, "iv_rank": rank, "verdict": ctx.get("verdict")}


def earnings_risk_score(candidate_flags: Any, gate_flags: Any) -> Component:
    cf = candidate_flags if isinstance(candidate_flags, dict) else {}
    gf = [str(x) for x in (gate_flags or [])]
    ebe = cf.get("earnings_before_expiry")
    flagged = ebe is True or any("earnings_before_expiry" in f for f in gf)
    unknown = (ebe is None and not flagged) or "earnings_unknown" in gf
    if flagged:
        return EARNINGS_FLAGGED_SCORE, "earnings before expiry FLAGGED — event risk on the debit", {
            "earnings_before_expiry": True, "gate_flags": gf}
    if unknown:
        return NEUTRAL_SCORE, "earnings date unknown — neutral 50", {
            "earnings_before_expiry": None, "gate_flags": gf}
    return 100.0, "no earnings before expiry", {"earnings_before_expiry": False, "gate_flags": gf}


def account_sizing_score(premium_total: Any, max_premium_paper: Any,
                         portfolio_value: Any) -> Component:
    pt = _f(premium_total)
    cap = _f(max_premium_paper) or DEFAULT_MAX_PREMIUM_PAPER
    if pt is None or pt <= 0:
        return NEUTRAL_SCORE, "premium_total unavailable — neutral 50", {"premium_total": pt}
    cap_ratio = pt / cap
    cap_score = _clamp(100.0 * (1.0 - cap_ratio))
    inputs: Dict[str, Any] = {"premium_total": pt, "max_premium_paper": cap,
                              "cap_ratio": round(cap_ratio, 4), "cap_score": cap_score}
    pv = _f(portfolio_value)
    if pv and pv > 0:
        pct = pt / pv * 100.0
        if pct <= PORTFOLIO_FREE_PCT:
            port_score = 100.0
        else:
            port_score = _clamp(100.0 * (PORTFOLIO_ZERO_AT_PCT - pct)
                                / (PORTFOLIO_ZERO_AT_PCT - PORTFOLIO_FREE_PCT))
        inputs.update(portfolio_value=pv, portfolio_pct=round(pct, 3), portfolio_score=port_score)
        score = min(cap_score, port_score)  # conservative: worst of the two
        detail = (f"premium ${pt:,.0f} = {cap_ratio:.0%} of ${cap:,.0f} paper cap "
                  f"(score {cap_score:.0f}) · {pct:.2f}% of portfolio (score {port_score:.0f}) — min taken")
    else:
        score = cap_score
        detail = (f"premium ${pt:,.0f} = {cap_ratio:.0%} of ${cap:,.0f} paper cap "
                  f"(portfolio value unavailable — cap ratio only)")
        inputs.update(portfolio_value=None)
    return round(score, 1), detail, inputs


def thesis_freshness_score(latest_note_at: Any, *, now: Optional[datetime] = None) -> Component:
    ts = _parse_ts(latest_note_at)
    if ts is None:
        return NEUTRAL_SCORE, "no watchlist research/CIO note found — neutral 50, noted", {
            "latest_note_at": None}
    age_days = max(0.0, (_now(now) - ts).total_seconds() / 86400.0)
    if age_days <= FRESH_FULL_DAYS:
        score = 100.0
    else:
        score = _clamp(100.0 * (FRESH_ZERO_DAYS - age_days) / (FRESH_ZERO_DAYS - FRESH_FULL_DAYS))
    return score, f"underlying note {age_days:.1f}d old (100 ≤{FRESH_FULL_DAYS:.0f}d → 0 at {FRESH_ZERO_DAYS:.0f}d)", {
        "latest_note_at": ts.isoformat(), "age_days": round(age_days, 1)}


def paper_fill_quality_score(alpaca_json: Any, premium_mid: Any) -> Component:
    aj = alpaca_json if isinstance(alpaca_json, dict) else {}
    fill = aj.get("fill") or {}
    fill_px = _f(fill.get("price"))
    mid = _f(premium_mid)
    if fill_px is None or fill_px <= 0:
        return None, "no Alpaca fill yet — component excluded (weights renormalized)", {
            "fill_price": None}
    if mid is None or mid <= 0:
        return NEUTRAL_SCORE, "fill exists but proposal mid missing — neutral 50", {
            "fill_price": fill_px, "mid": None}
    slip_pct = (fill_px - mid) / mid * 100.0
    score = 100.0 if slip_pct <= 0 else _clamp(100.0 * (1.0 - slip_pct / FILL_SLIP_ZERO_AT_PCT))
    return score, f"filled {fill_px:.2f} vs mid {mid:.2f} → slippage {slip_pct:+.2f}% (0 at +{FILL_SLIP_ZERO_AT_PCT:.0f}%)", {
        "fill_price": fill_px, "mid": mid, "slippage_pct": round(slip_pct, 3)}


# ── defensive context readers (outage → None, never raise) ───────────────────

def _state_dir() -> Path:
    return Path(os.getenv("OPTIONS_PIPELINE_STATE_DIR",
                          str(PROJECT_ROOT / "data" / "portfolios" / "state")))


def read_portfolio_value() -> Optional[float]:
    """Total portfolio value from holdings.json (None on any failure)."""
    try:
        raw = json.loads((_state_dir() / "holdings.json").read_text(encoding="utf-8"))
        v = _f((raw.get("portfolio_totals") or {}).get("total_value"))
        return v if v and v > 0 else None
    except Exception:
        return None


def fetch_latest_note_at(symbol: str, executor: Optional[Executor] = None) -> Optional[datetime]:
    """Most recent watchlist research-card update or CIO synthesis for the underlying."""
    try:
        ex = executor or _default_executor()
        row = ex(
            """SELECT GREATEST(
                 (SELECT MAX(updated_at) FROM watchlist_research_cards
                   WHERE UPPER(symbol) = UPPER(%s)),
                 (SELECT MAX(created_at) FROM watchlist_final_synthesis
                   WHERE UPPER(symbol) = UPPER(%s))
               ) AS latest_note_at""",
            (symbol, symbol), fetch="one")
        return _parse_ts(dict(row).get("latest_note_at")) if row else None
    except Exception:
        return None


def _registry_max_premium(strategy_id: str) -> float:
    try:
        from lib.options_pipeline.universe import load_strategy_registry
        row = (load_strategy_registry().get("strategies") or {}).get(strategy_id) or {}
        v = _f(row.get("max_premium_paper"))
        return v if v and v > 0 else DEFAULT_MAX_PREMIUM_PAPER
    except Exception:
        return DEFAULT_MAX_PREMIUM_PAPER


# ── scoring one queue row ────────────────────────────────────────────────────

_UNSET = object()


def verdict_for_score(score: float) -> str:
    for ceiling, label in VERDICT_BANDS:
        if ceiling is None or score < ceiling:
            return label
    return VERDICT_NOT_PRIME  # unreachable


def score_proposal(queue_row: dict, *,
                   max_premium_paper: Any = None,
                   portfolio_value: Any = _UNSET,
                   latest_note_at: Any = _UNSET,
                   executor: Optional[Executor] = None,
                   now: Optional[datetime] = None) -> dict:
    """Score one options_approval_queue row → prime_json dict (pure given inputs).

    All context inputs are injectable for tests; when omitted, portfolio value
    comes from holdings.json and thesis freshness from the watchlist tables
    (both defensive — unavailable → honest neutral component).
    """
    pj = _jload(queue_row.get("proposal_json"))
    meta = _jload(queue_row.get("meta"))
    p_meta = _jload(pj.get("meta"))
    policy = _jload(p_meta.get("selection_policy"))
    candidate = _jload(_jload(p_meta.get("analysis")).get("candidate"))
    alpaca_json = _jload(meta.get("alpaca_json"))
    symbol = (pj.get("underlying") or pj.get("symbol") or queue_row.get("symbol") or "").upper()
    strategy_id = pj.get("strategy") or queue_row.get("strategy") or "deep_itm_call"

    cap = _f(max_premium_paper) or _registry_max_premium(strategy_id)
    pv = read_portfolio_value() if portfolio_value is _UNSET else portfolio_value
    note_at = (fetch_latest_note_at(symbol, executor) if latest_note_at is _UNSET
               else latest_note_at)

    window = tuple(policy.get("delta_range") or DEFAULT_DELTA_WINDOW)
    max_spread = _f(policy.get("max_spread_pct")) or DEFAULT_MAX_SPREAD_PCT

    computed: Dict[str, Component] = {
        "spread_score": spread_score(pj.get("spread_pct"), max_spread),
        "oi_volume_score": oi_volume_score(pj.get("oi"), pj.get("volume")),
        "delta_fit_score": delta_fit_score(pj.get("delta"), window),
        "extrinsic_score": extrinsic_score(pj.get("extrinsic_value"), pj.get("premium")),
        "breakeven_distance_score": breakeven_distance_score(pj.get("breakeven_move_pct")),
        "iv_rank_score": iv_rank_score(pj.get("iv_context")
                                       or _jload(p_meta.get("analysis")).get("iv_context")),
        "earnings_risk_score": earnings_risk_score(candidate.get("flags"),
                                                   p_meta.get("gate_flags")),
        "account_sizing_score": account_sizing_score(pj.get("premium_total"), cap, pv),
        "thesis_freshness_score": thesis_freshness_score(note_at, now=now),
        "paper_fill_quality_score": paper_fill_quality_score(alpaca_json, pj.get("premium")),
    }

    components: Dict[str, dict] = {}
    excluded: List[str] = []
    notes: List[str] = []
    weighted = 0.0
    weight_used = 0.0
    for name, (score, detail, inputs) in computed.items():
        w = WEIGHTS[name]
        components[name] = {"score": score, "weight": w, "detail": detail, "inputs": inputs}
        if score is None:
            excluded.append(name)
            continue
        weighted += score * w
        weight_used += w
        if score == NEUTRAL_SCORE and ("neutral" in detail):
            notes.append(f"{name}: {detail}")
    if excluded:
        notes.append(f"excluded (no data, weights renormalized): {', '.join(excluded)}")

    prime = round(weighted / weight_used, 1) if weight_used > 0 else 0.0
    return {
        "engine": RUBRIC_ENGINE,
        "proposal_id": queue_row.get("proposal_id"),
        "symbol": symbol,
        "strategy": strategy_id,
        "prime_score": prime,
        "verdict": verdict_for_score(prime),
        "verdict_is_label_only": True,   # rubric never transitions status / places orders
        "components": components,
        "excluded_components": excluded,
        "weight_used": round(weight_used, 4),
        "weights_total": round(sum(WEIGHTS.values()), 4),
        "notes": notes,
        "scored_at": _now(now).isoformat(),
    }


# ── queue access + persistence (one statement per call) ──────────────────────

def get_queue_row(proposal_id: str, executor: Optional[Executor] = None) -> Optional[dict]:
    ex = executor or _default_executor()
    row = ex("""SELECT id, proposal_id, symbol, strategy, status, proposal_json, meta
                FROM options_approval_queue WHERE proposal_id=%s""",
             (proposal_id,), fetch="one")
    return dict(row) if row else None


def list_scoreable_rows(executor: Optional[Executor] = None) -> List[dict]:
    ex = executor or _default_executor()
    rows = ex("""SELECT id, proposal_id, symbol, strategy, status, proposal_json, meta
                 FROM options_approval_queue WHERE status = ANY(%s)
                 ORDER BY updated_at""",
              (list(SCOREABLE_STATUSES),), fetch="all")
    return [dict(r) for r in rows] if rows else []


def persist_prime(proposal_id: str, prime_json: dict,
                  executor: Optional[Executor] = None) -> bool:
    """ONE UPDATE: merge {"prime_json": ...} into the queue row's meta. Never
    touches status or any other column."""
    ex = executor or _default_executor()
    res = ex(
        """UPDATE options_approval_queue
           SET meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb,
               updated_at = NOW()
           WHERE proposal_id = %s""",
        (json.dumps({"prime_json": prime_json}, default=str), proposal_id))
    return res is not None


def score_and_persist(proposal_id: str, *, dry_run: bool = False,
                      executor: Optional[Executor] = None) -> dict:
    """Fetch → score → (persist) → return {"ok", "prime_json", "persisted"}."""
    ex = executor or _default_executor()
    row = get_queue_row(proposal_id, ex)
    if not row:
        return {"ok": False, "error": f"proposal {proposal_id!r} not in options_approval_queue"}
    prime = score_proposal(row, executor=ex)
    persisted = False
    if not dry_run:
        persisted = persist_prime(proposal_id, prime, ex)
        if not persisted:
            return {"ok": False, "error": "db unavailable — prime_json NOT persisted",
                    "prime_json": prime}
    return {"ok": True, "proposal_id": proposal_id, "prime_json": prime,
            "persisted": persisted, "dry_run": dry_run}
