"""CIO review of a BUY_READY / ENTRY_NEAR packet — governed, validated, advisory.

M5 2026-09-24 (operator: "build options"). The runner's page ended "Confirm or
refute the entry for the operator" and nothing ever answered it: the CIO wake it
emitted carried ``symbol`` where the reactive cycle reads ``symbols``, so the
review ran subject-less. This module is the answer: one subject-bound review per
BUY_READY/ENTRY_NEAR transition, by the CIO (agent ``alex``), through the
governed router (``llm_router.get_llm_response`` task ``cio_synthesis`` — its
DeepSeek caps, budget and off-peak routing apply), with the prompt below
verbatim, and a strict validator:

* verdict ∈ {APPROVE, MODIFY, REJECT}; all nine scores present, integers 1-10;
* no sizing: the keys of cio_instrument_record.BEHAVIOR_FIELDS are refused at
  any depth, and share/contract/dollar-size phrasing is refused in text;
* every number in the free text must trace to a number in SUPPLIED FACTS.

Modes (``CIO_ENTRY_REVIEW_MODE``): ``off`` | ``dry`` (default — builds facts and
prompt, makes NO model call) | ``live``. Going live is a deliberate operator
switch after a dry run (AGENTS.md §0 rule 7).
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

SCHEMA = "BuyReadyCIOReview@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
VERDICTS = ("APPROVE", "MODIFY", "REJECT")
SCORE_KEYS = ("conviction", "edge", "catalyst", "timing", "liquidity", "drawdown_risk",
              "concentration_risk", "correlation_risk", "execution_quality")
#: Mirrors scripts/lib/cio_instrument_record.BEHAVIOR_FIELDS (MBI_BEHAVIOR=0).
BEHAVIOR_FIELDS = ("recommended_delta_usd", "size_usd", "shares", "qty", "order",
                   "stop", "limit", "target_weight_pct", "trade", "execution")
_SIZING_TEXT = re.compile(
    r"\b(buy|sell|add|purchase|allocate|put)\s+(\$?\d[\d,.]*\s*(k|m)?\s*)(shares?|contracts?|lots?|of\b|in\b|into\b)"
    r"|\b\d[\d,.]*\s+(shares|contracts)\b|\bposition size\b|\bsize (it|the position) (at|to)\b",
    re.I,
)
_NUM = re.compile(r"(?<![A-Za-z_])-?\$?\d[\d,]*\.?\d*%?")

PROJECT_ROOT = Path(__file__).resolve().parents[2]

REVIEW_PROMPT = """ROLE: You are the Trade-AI CIO reviewing ONE BUY_READY entry packet for {SYMBOL}.
You are advisory (READ_ONLY_ADVISORY, MBI_BEHAVIOR=0). You NEVER size, order,
set stops, weight, or instruct execution. You never invent numbers: every
figure you cite must appear in the SUPPLIED FACTS block with its as-of time.
If a required fact is missing or stale, say so and lower confidence; do not guess.

SUPPLIED FACTS (JSON): equity plan {entry_zone, stop, target, rr_worst, rr_at_quote,
quote, quote_age}, structure {atr, atr_to_stop, trend, iv_rank (+ "proxy" flag),
iv_percentile|null, earnings_date|null}, options_alternatives [ranked; each with
strategy, strike(s), expiry, DTE, delta/gamma/theta/vega, OI, volume, bid/ask
spread %, breakeven, max_loss_per_unit, value_at_target_per_unit, POP_estimate,
chain_as_of, why_this_strike, why_this_expiry, neighbours_rejected],
portfolio {held_shares, pct_of_book, sector_pct, top_correlations, options_net_delta,
concentration_limit_pct, cash_state}, research {thesis, catalysts, open_questions}.

TASK — return JSON only:
1. verdict: APPROVE | MODIFY | REJECT (for presenting to the operator, not for trading).
2. scores 1-10 with one-line evidence each: conviction, edge, catalyst, timing,
   liquidity, drawdown_risk, concentration_risk, correlation_risk, execution_quality
   (spread/slippage/assignment/vol).
3. equity_view: confirm/refute the entry zone, stop placement vs ATR, target
   plausibility, worst-case R:R.
4. options_view: which ranked alternative (if any) better fits the thesis, target and
   holding period than stock, and why; name the trade-off (capital per unit, max loss
   per unit, breakeven, return at target, time decay). If none fits, say why.
5. portfolio_view: whether this ADD raises concentration/sector/correlation risk
   beyond stated limits — facts and flags only, never a size.
6. modifications (if MODIFY): concrete changes to the PLAN (e.g. wait for zone low,
   prefer the debit spread, tighten thesis check) — never an order or quantity.
7. unknowns: every missing/stale input that limited this review.
Refuse and return verdict=REJECT with reason "INSUFFICIENT_FACTS" if the quote or
chain is stale beyond policy or the plan levels are missing."""

OUTPUT_CONTRACT = (
    'Return exactly one JSON object: {"verdict": "...", "reason": "...", "scores": {"<name>": '
    '{"score": 1-10, "evidence": "..."}}, "equity_view": "...", "options_view": "...", '
    '"portfolio_view": "...", "modifications": ["..."], "unknowns": ["..."]}'
)


def mode() -> str:
    m = str(os.environ.get("CIO_ENTRY_REVIEW_MODE") or "dry").strip().lower()
    return m if m in ("off", "dry", "live") else "dry"


def _f(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_facts(packet: dict[str, Any]) -> dict[str, Any]:
    """SUPPLIED FACTS from a BuyReadyInstitutionalPacket — nothing invented."""
    eq = packet.get("equity") or {}
    struct = packet.get("structure_indicators") or {}
    alts = (packet.get("options_alternatives") or {})
    port = packet.get("portfolio_risk") or {}
    thesis = packet.get("thesis_indicators") or {}
    price, lo, hi = _f(eq.get("price")), _f(eq.get("entry_low")), _f(eq.get("entry_high"))
    stop, target = _f(eq.get("stop")), _f(eq.get("target"))
    rr_quote = None
    if price and stop is not None and target is not None and price > stop:
        rr_quote = round((target - price) / (price - stop), 2)
    alt_rows = []
    for a in (alts.get("alternatives") or [])[:4]:
        legs = a.get("legs") or []
        pc = a.get("per_contract") or {}
        g = a.get("greeks_per_share") or {}
        alt_rows.append({
            "rank": a.get("rank"), "strategy": a.get("strategy"), "qualified": a.get("qualified"),
            "disqualified_by": a.get("disqualified_by"),
            "strikes": [leg.get("strike") for leg in legs], "expiry": legs[0].get("exp") if legs else None,
            "dte": legs[0].get("dte") if legs else None,
            "delta": g.get("delta"), "gamma": g.get("gamma"), "theta_per_day": g.get("theta_per_day"),
            "vega": g.get("vega_per_vol_pt"),
            "oi": [leg.get("oi") for leg in legs], "volume": [leg.get("volume") for leg in legs],
            "spread_pct": (a.get("liquidity") or {}).get("bid_ask_spread_pct"),
            "breakeven": pc.get("breakeven"), "max_loss_per_unit": pc.get("max_loss"),
            "capital_per_unit": pc.get("capital"), "value_at_target_per_unit": pc.get("value_at_target_expiry"),
            "return_at_target_pct": pc.get("return_at_target_pct"), "pop_estimate": a.get("pop_estimate"),
            "why_this_strike": a.get("why_this_strike"), "why_this_expiry": a.get("why_this_expiry"),
            "neighbours_rejected": a.get("neighbours_rejected"),
        })
    return {
        "symbol": packet.get("symbol"),
        "equity_plan": {"entry_zone": [lo, hi], "stop": stop, "target": target, "rr_worst": eq.get("rr"),
                        "rr_at_quote": rr_quote, "quote": price, "quote_age": eq.get("quote_age_h"),
                        "state": eq.get("state"), "plan_source": eq.get("plan_source")},
        "structure": {"atr": struct.get("atr"), "atr_to_stop": struct.get("atr_vs_distance_to_stop"),
                      "trend": struct.get("trend"), "iv_rank": struct.get("iv_rank"),
                      "iv_rank_source": struct.get("iv_rank_source"), "iv_percentile": struct.get("iv_percentile"),
                      "earnings_date": struct.get("earnings_date")},
        "options_alternatives": alt_rows,
        "options_status": alts.get("status"), "chain_as_of": alts.get("chain_as_of"),
        "stock_per_share": alts.get("stock_per_share"),
        "portfolio": {"held_shares": port.get("held_units_total"), "held": port.get("held"),
                      "pct_of_book": port.get("pct_of_total_book"),
                      "pct_of_invested_capital": port.get("pct_of_invested_capital"),
                      "sector_pct": port.get("sector_exposure_whole_book"),
                      "top_correlations": (port.get("correlations") or {}).get("top"),
                      "correlation_coverage": (port.get("correlations") or {}).get("coverage"),
                      "options_net_delta": (port.get("options_book") or {}).get("net_delta_shares"),
                      "concentration_limit_pct": (port.get("ips_limits") or {}).get("max_single_position_pct"),
                      "sector_limit_pct": (port.get("ips_limits") or {}).get("max_sector_concentration_pct"),
                      "cash_state": port.get("cash_state"), "flags": port.get("flags")},
        "research": {"thesis": thesis.get("thesis") or thesis.get("summary"), "catalysts": thesis.get("catalyst"),
                     "open_questions": thesis.get("open_questions"), "pe": thesis.get("pe"),
                     "sector": thesis.get("sector")},
    }


def render_prompt(facts: dict[str, Any]) -> str:
    return (REVIEW_PROMPT.replace("{SYMBOL}", str(facts.get("symbol") or "?"))
            + "\n\nSUPPLIED FACTS:\n" + json.dumps(facts, default=str, sort_keys=True)
            + "\n\n" + OUTPUT_CONTRACT)


def _numbers_in(obj: Any) -> list[float]:
    out: list[float] = []
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, str):
        for m in _NUM.finditer(obj):
            s = m.group(0).replace("$", "").replace(",", "").rstrip("%")
            try:
                out.append(float(s))
            except ValueError:
                pass
        return out
    if isinstance(obj, dict):
        for v in obj.values():
            out += _numbers_in(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out += _numbers_in(v)
    return out


def _traceable(n: float, fact_nums: list[float]) -> bool:
    if abs(n) <= 10 and float(n).is_integer():
        return True  # scores, ranks, list ordinals
    for f in fact_nums:
        if abs(n - f) <= 0.011 or (f and abs(n - f) / abs(f) <= 0.005):
            return True
        if abs(f) < 1.5 and abs(n - 100 * f) <= 0.6:  # 0.62 delta/POP quoted as 62%
            return True
    return False


def _keys_deep(obj: Any) -> set[str]:
    ks: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks.add(str(k))
            ks |= _keys_deep(v)
    elif isinstance(obj, list):
        for v in obj:
            ks |= _keys_deep(v)
    return ks


def validate_review(review: Any, facts: dict[str, Any]) -> tuple[bool, list[str]]:
    errs: list[str] = []
    if not isinstance(review, dict):
        return False, ["review is not a JSON object"]
    if review.get("verdict") not in VERDICTS:
        errs.append(f"verdict must be one of {VERDICTS}")
    scores = review.get("scores")
    if not isinstance(scores, dict):
        errs.append("scores missing")
    else:
        for k in SCORE_KEYS:
            s = scores.get(k)
            val = s.get("score") if isinstance(s, dict) else s
            if not isinstance(val, int) or isinstance(val, bool) or not 1 <= val <= 10:
                errs.append(f"score {k} must be an integer 1-10")
    for k in ("equity_view", "options_view", "portfolio_view"):
        if not isinstance(review.get(k), str) or not review.get(k).strip():
            errs.append(f"{k} missing")
    bad_keys = sorted(_keys_deep(review) & set(BEHAVIOR_FIELDS))
    if bad_keys:
        errs.append(f"MBI_BEHAVIOR=0: sizing/behaviour keys refused {bad_keys}")
    text = json.dumps({k: review.get(k) for k in ("reason", "scores", "equity_view", "options_view",
                                                   "portfolio_view", "modifications", "unknowns")}, default=str)
    for m in _SIZING_TEXT.finditer(text):
        # Quoting the EXISTING holding ("you hold 130.27 shares") is a fact, not sizing.
        if re.search(r"\b(hold|holds|held|holding|own|owns|owned)\b[^.]{0,24}$", text[max(0, m.start() - 30):m.start()], re.I):
            continue
        errs.append("MBI_BEHAVIOR=0: sizing/quantity language refused")
        break
    fact_nums = _numbers_in(facts)
    untraced = sorted({n for n in _numbers_in(json.loads(text)) if not _traceable(n, fact_nums)})
    if untraced:
        errs.append(f"numbers not traceable to SUPPLIED FACTS: {untraced[:8]}")
    return (not errs), errs


def _parse_json(text: str) -> Any:
    s = str(text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?|```$", "", s).strip()
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("no JSON object in response")
    return json.loads(s[i:j + 1])


def _default_llm(prompt: str, *, symbol: str, job_key: str) -> dict[str, Any]:
    try:
        from llm_router import get_llm_response  # type: ignore
    except ImportError:
        from scripts.llm_router import get_llm_response  # type: ignore
    return get_llm_response("cio_synthesis", prompt, high_impact=True, max_tokens=1400,
                            metadata={"symbol": symbol, "agent": "alex", "task": "buy_ready_review"},
                            job_key=job_key)


def review_packet(packet: dict[str, Any], *, llm_fn: Optional[Callable[..., dict[str, Any]]] = None,
                  review_mode: Optional[str] = None, timeout_s: Optional[float] = None,
                  now: Optional[datetime] = None) -> dict[str, Any]:
    """Run (or dry-run) the CIO review. Never raises; never sizes."""
    now = now or datetime.now(timezone.utc)
    m = review_mode or mode()
    facts = build_facts(packet)
    sym = str(packet.get("symbol") or "").upper()
    state = (packet.get("equity") or {}).get("state")
    job_key = f"buy_ready_review:{sym}:{state}:{now.date().isoformat()}"
    base = {"schema": SCHEMA, "authority": AUTHORITY, "symbol": sym, "state": state, "mode": m,
            "job_key": job_key, "agent": "alex", "as_of": now.replace(microsecond=0).isoformat(),
            "mbi_behavior": 0}
    if m == "off":
        return {**base, "status": "DISABLED"}
    prompt = render_prompt(facts)
    if m == "dry":
        return {**base, "status": "DRY_RUN", "prompt_chars": len(prompt), "facts": facts,
                "note": "no model call (CIO_ENTRY_REVIEW_MODE=dry)"}
    fn = llm_fn or (lambda p: _default_llm(p, symbol=sym, job_key=job_key))
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["resp"] = fn(prompt)
        except Exception as exc:  # noqa: BLE001
            box["err"] = f"{type(exc).__name__}: {str(exc)[:160]}"

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout_s if timeout_s is not None else float(os.environ.get("CIO_ENTRY_REVIEW_TIMEOUT_S") or 90))
    if t.is_alive():
        return {**base, "status": "PENDING", "reason": "TIMEOUT"}
    if "err" in box:
        return {**base, "status": "LLM_ERROR", "reason": box["err"]}
    resp = box.get("resp") or {}
    raw = resp.get("response") if isinstance(resp, dict) else resp
    meta = {k: resp.get(k) for k in ("model_used", "provider", "cost_estimate", "latency")} if isinstance(resp, dict) else {}
    try:
        review = _parse_json(raw)
    except (ValueError, TypeError) as exc:
        return {**base, "status": "INVALID", "errors": [f"unparseable: {exc}"], "model": meta}
    ok, errs = validate_review(review, facts)
    if not ok:
        return {**base, "status": "INVALID", "errors": errs, "model": meta}
    return {**base, "status": "OK", "review": review, "model": meta}


def decision_row(result: dict[str, Any], now: Optional[datetime] = None) -> Optional[tuple]:
    """cio_decisions row (action_class='entry_review') for an OK review, else None."""
    if result.get("status") != "OK":
        return None
    now = now or datetime.now(timezone.utc)
    r = result["review"]
    did = f"cio-entry-review-{str(result['symbol']).lower()}-{now.strftime('%Y%m%d%H%M%S')}"
    rationale = f"{r['verdict']}: {str(r.get('reason') or r.get('equity_view') or '')[:400]}"
    meta = json.dumps({"review": r, "model": result.get("model"), "job_key": result.get("job_key"),
                       "schema": SCHEMA}, default=str)
    return (did, result["symbol"], r["verdict"], rationale, meta)


INSERT_SQL = (
    "INSERT INTO cio_decisions (decision_id, symbol, action, action_class, priority, decision_safety, "
    "human_review_required, rationale, status, agent_votes, metadata) "
    "VALUES (%s,%s,%s,'entry_review','high','safe',true,%s,'proposed','{}',%s::jsonb)"
)


def format_review_lines(result: Optional[dict[str, Any]]) -> list[str]:
    if not result:
        return ["CIO review: not run"]
    st = result.get("status")
    if st == "OK":
        r = result["review"]
        mods = r.get("modifications") or []
        lines = [f"CIO review ({result.get('agent')}): {r['verdict']} — {str(r.get('reason') or '')[:160]}"]
        if r.get("options_view"):
            lines.append(f"  options: {str(r['options_view'])[:180]}")
        if r.get("portfolio_view"):
            lines.append(f"  book: {str(r['portfolio_view'])[:180]}")
        if mods:
            lines.append("  modify: " + "; ".join(str(x)[:90] for x in mods[:3]))
        return lines
    if st == "PENDING":
        return ["CIO review: pending — follow-up when it lands"]
    if st == "DRY_RUN":
        return ["CIO review: not enabled (dry run — no model call)"]
    if st == "DISABLED":
        return ["CIO review: disabled"]
    return [f"CIO review: unavailable ({st}{': ' + str((result.get('errors') or [result.get('reason')])[0])[:100] if (result.get('errors') or result.get('reason')) else ''})"]


__all__ = ["REVIEW_PROMPT", "SCHEMA", "build_facts", "decision_row", "format_review_lines", "mode",
           "render_prompt", "review_packet", "validate_review", "INSERT_SQL"]
