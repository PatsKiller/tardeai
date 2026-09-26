"""CIO review of one researched options thesis -> a Decision with its own GUID.

Operator 2026-09-26: "LLM CIO review, you confirm". A complete options thesis is
reviewed by the CIO (agent ``alex``) through the governed router
(``llm_router.get_llm_response`` task ``cio_synthesis``: DeepSeek, caps, budget,
off-peak routing). The review issues one of APPROVE / REJECT / MORE_RESEARCH /
MONITOR_ONLY with reasoning, concerns, challenged assumptions and evidence for
and against. It is advisory: approving a trade is still the operator's click
plus per-order 2FA.

Reuses the entry review's rails (buy_ready_cio_review): no sizing keys or sizing
language, and every number in the text must trace to a supplied fact. Mode comes
from ``options_thesis_lifecycle.cio_review_mode`` (off | dry | live).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

try:
    from scripts.lib import buy_ready_cio_review as br
except ImportError:  # scripts/ on sys.path
    from lib import buy_ready_cio_review as br  # type: ignore

SCHEMA = "OptionsCIOReview@v1"
OUTCOMES = ("APPROVE", "REJECT", "MORE_RESEARCH", "MONITOR_ONLY")
CONFIDENCE = ("HIGH", "MEDIUM", "LOW")

PROMPT = """ROLE: You are the Trade-AI CIO reviewing ONE options idea for {SYMBOL}.
You are advisory (READ_ONLY_ADVISORY, MBI_BEHAVIOR=0). You NEVER size, order, set
stops, weight, or instruct execution. You never invent numbers: every figure you
cite must appear in SUPPLIED FACTS. If a fact is missing or stale, say so.

SUPPLIED FACTS (JSON):
{FACTS}

TASK - return JSON only:
{{"outcome": "APPROVE|REJECT|MORE_RESEARCH|MONITOR_ONLY",
  "confidence": "HIGH|MEDIUM|LOW",
  "reasoning": "why, in plain English, tied to the thesis and the option's purpose",
  "concerns": ["..."],
  "assumptions_challenged": ["..."],
  "evidence_for": ["..."],
  "evidence_against": ["..."],
  "exit_plan_view": "is the stated exit plan adequate for this structure",
  "unknowns": ["missing or stale inputs that limited this review"]}}
Use MORE_RESEARCH when a catalyst, exit or bear case is too thin to judge;
MONITOR_ONLY when the thesis is sound but the timing or price is not."""


def build_facts(p: dict[str, Any]) -> dict[str, Any]:
    memo = p.get("committee_memo") or {}
    pe = p.get("plain_english") or {}
    return {
        "symbol": p.get("symbol"), "strategy": p.get("strategy"), "classification": memo.get("classification_label"),
        "spot": p.get("underlying_price"), "strike": p.get("strike"), "expiration": p.get("expiration"),
        "dte": p.get("dte"), "premium": p.get("premium"), "contracts": p.get("contracts"),
        "breakeven": p.get("breakeven"), "pop_pct": p.get("pop_pct"), "iv_rank": p.get("iv_rank"),
        "max_loss": p.get("max_loss"), "max_profit": p.get("max_profit"),
        "oi": p.get("oi"), "bid_ask_spread_pct": p.get("bid_ask_spread_pct"),
        "thesis": memo.get("investment_thesis"), "counter_evidence": memo.get("contrarian_view"),
        "why_now": memo.get("why_now"), "exit_plan": memo.get("exit_plan"),
        "research_answers": p.get("research_answers") or {},
        "plain_english": {k: pe.get(k) for k in ("objective", "premium_line", "breakeven_line", "scenarios")},
    }


def validate(review: Any, facts: dict[str, Any]) -> tuple[bool, list[str]]:
    errs: list[str] = []
    if not isinstance(review, dict):
        return False, ["review is not a JSON object"]
    if review.get("outcome") not in OUTCOMES:
        errs.append(f"outcome must be one of {OUTCOMES}")
    if review.get("confidence") not in CONFIDENCE:
        errs.append(f"confidence must be one of {CONFIDENCE}")
    if not str(review.get("reasoning") or "").strip():
        errs.append("reasoning missing")
    bad = sorted(br._keys_deep(review) & set(br.BEHAVIOR_FIELDS))
    if bad:
        errs.append(f"MBI_BEHAVIOR=0: sizing/behaviour keys refused {bad}")
    text = json.dumps({k: review.get(k) for k in ("reasoning", "concerns", "assumptions_challenged",
                                                   "evidence_for", "evidence_against", "exit_plan_view")},
                      default=str)
    if br._SIZING_TEXT.search(text):
        errs.append("MBI_BEHAVIOR=0: sizing/quantity language refused")
    fact_nums = br._numbers_in(facts)
    untraced = sorted({n for n in br._numbers_in(json.loads(text)) if not br._traceable(n, fact_nums)})
    if untraced:
        errs.append(f"numbers not traceable to SUPPLIED FACTS: {untraced[:8]}")
    return (not errs), errs


def _default_llm(prompt: str, *, symbol: str, job_key: str) -> dict[str, Any]:
    try:
        from llm_router import get_llm_response  # type: ignore
    except ImportError:
        from scripts.llm_router import get_llm_response  # type: ignore
    return get_llm_response("cio_synthesis", prompt, high_impact=True, max_tokens=1200,
                            metadata={"symbol": symbol, "agent": "alex", "task": "options_thesis_review"},
                            job_key=job_key)


def review(p: dict[str, Any], *, mode: str, llm_fn: Optional[Callable[[str], Any]] = None,
           now: Optional[datetime] = None) -> dict[str, Any]:
    """Run (or dry-run) the review. Never raises; never sizes."""
    now = now or datetime.now(timezone.utc)
    sym = str(p.get("symbol") or "").upper()
    guid = p.get("option_strategy_guid") or ""
    facts = build_facts(p)
    job_key = f"options_thesis_review:{guid}:{(p.get('options_thesis') or {}).get('pin')}"
    base = {"schema": SCHEMA, "symbol": sym, "position_guid": guid, "mode": mode, "job_key": job_key,
            "agent": "alex", "as_of": now.replace(microsecond=0).isoformat(), "mbi_behavior": 0,
            "authority": "READ_ONLY_ADVISORY"}
    if mode == "off":
        return {**base, "status": "DISABLED"}
    prompt = PROMPT.replace("{SYMBOL}", sym).replace("{FACTS}", json.dumps(facts, default=str)[:6000])
    if mode != "live":
        return {**base, "status": "DRY_RUN", "prompt_chars": len(prompt)}
    try:
        resp = (llm_fn or (lambda x: _default_llm(x, symbol=sym, job_key=job_key)))(prompt)
    except Exception as exc:  # noqa: BLE001
        return {**base, "status": "LLM_ERROR", "reason": f"{type(exc).__name__}: {str(exc)[:160]}"}
    raw = resp.get("response") if isinstance(resp, dict) else resp
    meta = {k: resp.get(k) for k in ("model_used", "provider", "cost_estimate")} if isinstance(resp, dict) else {}
    try:
        r = br._parse_json(raw)
    except (ValueError, TypeError) as exc:
        return {**base, "status": "INVALID", "errors": [f"unparseable: {exc}"], "model": meta}
    ok, errs = validate(r, facts)
    if not ok:
        return {**base, "status": "INVALID", "errors": errs, "model": meta}
    return {**base, "status": "OK", "review": r, "model": meta,
            "decision_guid": f"dec_{uuid.uuid4()}"}


INSERT_SQL = (
    "INSERT INTO cio_decisions (decision_id, symbol, action, action_class, priority, decision_safety, "
    "human_review_required, rationale, status, agent_votes, metadata) "
    "VALUES (%s,%s,%s,'options_thesis_review','high','safe',true,%s,'proposed','{}',%s::jsonb)"
)


def decision_row(result: dict[str, Any]) -> Optional[tuple]:
    if result.get("status") != "OK":
        return None
    r = result["review"]
    meta = json.dumps({"review": r, "position_guid": result.get("position_guid"), "model": result.get("model"),
                       "schema": SCHEMA}, default=str)
    return (result["decision_guid"], result["symbol"], r["outcome"],
            f"{r['outcome']}: {str(r.get('reasoning') or '')[:400]}", meta)
