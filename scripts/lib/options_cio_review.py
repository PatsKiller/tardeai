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
MONITOR_ONLY when the thesis is sound but the timing or price is not.
Be concise: reasoning at most 150 words; each list at most 4 short items. Return the
JSON object only, complete, with no text before or after it."""


def _pct(a: Any, b: Any) -> Optional[float]:
    try:
        a, b = float(a), float(b)
        return round(100.0 * (a - b) / b, 1) if b else None
    except (TypeError, ValueError):
        return None


def _clip(v: Any, n: int) -> Any:
    return (v[:n] + "…") if isinstance(v, str) and len(v) > n else v


def _prior_decisions(p: dict[str, Any], memory: Optional[dict[str, Any]]) -> Optional[list[dict[str, Any]]]:
    """Prior options memory from M2 when enabled (config memory_reads, env override).

    None = reads off (the key is left out of the facts); [] = on, nothing found
    or the read failed. Never raises."""
    m = memory or {}
    try:
        try:
            from scripts.lib import options_memory_envelope as ome
            from scripts.lib.options_thesis_lifecycle import DEFAULTS
        except ImportError:  # scripts/ on sys.path
            from lib import options_memory_envelope as ome  # type: ignore
            from lib.options_thesis_lifecycle import DEFAULTS  # type: ignore
        if not ome.options_memory_reads_enabled(m.get("memory_reads")):
            return None
        loader = m.get("loader") or ome.load_prior_options_facts
        rows = loader(p.get("option_strategy_guid"), p.get("symbol"),
                      limit=int(m.get("limit") or DEFAULTS["memory_reads_limit"]),
                      lookback_days=int(m.get("lookback_days") or DEFAULTS["memory_reads_lookback_days"]))
        return list(rows or [])
    except Exception:  # noqa: BLE001 — memory is advisory; failure is "no priors"
        return []


def _first(*vals: Any) -> Any:
    for v in vals:
        if v is not None:
            return v
    return None


def liquidity_facts(p: dict[str, Any]) -> dict[str, Any]:
    """Quote liquidity as the desk saw it. A credit spread carries no top-level ``oi``:
    the gate's verdict is ``enterprise.liquidity`` and the two quotes are ``legs_liquidity``
    (2026-09-27: the CIO saw null OI while the card showed 366)."""
    ent = (p.get("enterprise") or {}).get("liquidity") or {}
    legs = [dict(l) for l in (p.get("legs_liquidity") or []) if isinstance(l, dict)]
    lead = legs[0] if legs else {}
    return {
        "oi": _first(p.get("oi"), ent.get("oi"), lead.get("open_interest")),
        "volume": _first(p.get("volume"), ent.get("volume"), lead.get("volume")),
        "bid_ask_spread_pct": _first(p.get("bid_ask_spread_pct"), ent.get("bid_ask_spread_pct"), lead.get("spread_pct")),
        "gate_pass": ent.get("pass"),
        "issues": list(ent.get("issues") or []),
        "legs": [{k: l.get(k) for k in ("role", "strike", "bid", "ask", "mid", "open_interest", "volume", "spread_pct")}
                 for l in legs],
    }


def _default_disclosures(symbol: Any) -> list[dict[str, Any]]:
    try:
        from scripts.lib import sec_filing_documents as sfd
    except ImportError:  # scripts/ on sys.path
        from lib import sec_filing_documents as sfd  # type: ignore
    return sfd.load_primary_disclosures(str(symbol or ""))


def build_facts(p: dict[str, Any], *, memory: Optional[dict[str, Any]] = None,
                disclosures_loader: Optional[Callable[[Any], list[dict[str, Any]]]] = None) -> dict[str, Any]:
    """Supplied facts for the review. ``memory`` = {memory_reads, limit, lookback_days,
    loader?} from options_thesis_lifecycle settings; prior options facts from the CIO's
    bitemporal memory land in ``prior_decisions`` (their numbers are then traceable).
    ``disclosures_loader(symbol)`` supplies dated 8-K exhibit sentences (default: the
    stored sec_filing_documents rows); it lands in ``primary_disclosures``."""
    memo = p.get("committee_memo") or {}
    pe = p.get("plain_english") or {}
    spot, strike, prem, dte = p.get("underlying_price"), p.get("strike"), p.get("premium"), p.get("dte")
    # Derived figures the reviewer would otherwise compute and then fail the
    # traceability rail on (2026-09-26: DELL breakeven 16.8% below spot was refused).
    derived = {
        # Signed and unsigned: reviewers write "16.8% below spot", the rail compares values.
        "strike_vs_spot_pct": _pct(strike, spot),
        "breakeven_vs_spot_pct": _pct(p.get("breakeven"), spot),
        "strike_distance_from_spot_pct": abs(_pct(strike, spot) or 0) or None,
        "breakeven_distance_from_spot_pct": abs(_pct(p.get("breakeven"), spot) or 0) or None,
        "premium_pct_of_strike": round(100.0 * float(prem) / float(strike), 2) if prem and strike else None,
        "annualized_yield_pct": (round(100.0 * float(prem) / float(strike) * 365.0 / max(int(dte), 1), 1)
                                 if prem and strike and dte else None),
        "desk_floor_min_pop_pct": 52, "desk_floor_min_edge": 62,
    }
    ra = p.get("research_answers") or {}
    facts = {
        "symbol": p.get("symbol"), "strategy": p.get("strategy"), "classification": memo.get("classification_label"),
        "spot": p.get("underlying_price"), "strike": p.get("strike"), "expiration": p.get("expiration"),
        "dte": p.get("dte"), "premium": p.get("premium"), "contracts": p.get("contracts"),
        "breakeven": p.get("breakeven"), "pop_pct": p.get("pop_pct"), "iv_rank": p.get("iv_rank"),
        "max_loss": p.get("max_loss"), "max_profit": p.get("max_profit"),
        "derived": derived,
        # Long narrative is clipped per field so the research answers are never cut off.
        "thesis": _clip(memo.get("investment_thesis"), 1200), "counter_evidence": _clip(memo.get("contrarian_view"), 600),
        "why_now": memo.get("why_now"), "exit_plan": memo.get("exit_plan"),
        "research_answers": {k: _clip(v, 600) for k, v in ra.items() if k != "research_id"},
        "plain_english": {k: pe.get(k) for k in ("objective", "premium_line", "breakeven_line", "scenarios")},
    }
    liq = liquidity_facts(p)
    facts["oi"], facts["bid_ask_spread_pct"] = liq["oi"], liq["bid_ask_spread_pct"]
    facts["liquidity"] = liq
    # Reported SEC fundamentals (sec_xbrl lines set on the proposal by options_engine) and the
    # dated 8-K exhibit sentences; both are primary and were missing from the packet.
    fund = p.get("fundamentals") or {}
    facts["fundamentals"] = {"state": fund.get("state"), "lines": list(fund.get("lines") or [])[:12],
                             "filing_url": fund.get("filing_url")}
    try:
        disclosures = list((disclosures_loader or _default_disclosures)(p.get("symbol")) or [])
    except Exception:  # noqa: BLE001 — primary text is advisory; failure is "none on file"
        disclosures = []
    facts["primary_disclosures"] = disclosures
    try:
        from scripts.lib import sec_filing_documents as _sfd
    except ImportError:  # scripts/ on sys.path
        from lib import sec_filing_documents as _sfd  # type: ignore
    note = _sfd.rpo_note(facts["fundamentals"]["lines"], disclosures)
    if note:
        facts["rpo_vs_backlog_note"] = note
    prior = _prior_decisions(p, memory)
    if prior is not None:
        facts["prior_decisions"] = prior
    return facts


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


def _default_llm(prompt: str, *, symbol: str, job_key: str, max_tokens: int = 2500) -> dict[str, Any]:
    try:
        from llm_router import get_llm_response  # type: ignore
    except ImportError:
        from scripts.llm_router import get_llm_response  # type: ignore
    # 2026-09-26 first live run: 1200 output tokens cut both reviews off before the
    # closing brace ("no JSON object in response"). Limit now comes from config.
    return get_llm_response("cio_synthesis", prompt, high_impact=True, max_tokens=max_tokens,
                            metadata={"symbol": symbol, "agent": "alex", "task": "options_thesis_review"},
                            job_key=job_key)


def review(p: dict[str, Any], *, mode: str, llm_fn: Optional[Callable[[str], Any]] = None,
           now: Optional[datetime] = None, max_tokens: int = 2500,
           memory: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Run (or dry-run) the review. Never raises; never sizes."""
    now = now or datetime.now(timezone.utc)
    sym = str(p.get("symbol") or "").upper()
    guid = p.get("option_strategy_guid") or ""
    facts = build_facts(p, memory=memory)
    job_key = f"options_thesis_review:{guid}:{(p.get('options_thesis') or {}).get('pin')}"
    base = {"schema": SCHEMA, "symbol": sym, "position_guid": guid, "mode": mode, "job_key": job_key,
            "agent": "alex", "as_of": now.replace(microsecond=0).isoformat(), "mbi_behavior": 0,
            "authority": "READ_ONLY_ADVISORY"}
    if mode == "off":
        return {**base, "status": "DISABLED"}
    prompt = PROMPT.replace("{SYMBOL}", sym).replace("{FACTS}", json.dumps(facts, default=str))
    if "prior_decisions" in facts:
        base["prior_decisions_count"] = len(facts["prior_decisions"])
    if mode != "live":
        return {**base, "status": "DRY_RUN", "prompt_chars": len(prompt)}
    try:
        resp = (llm_fn or (lambda x: _default_llm(x, symbol=sym, job_key=job_key, max_tokens=max_tokens)))(prompt)
    except Exception as exc:  # noqa: BLE001
        return {**base, "status": "LLM_ERROR", "reason": f"{type(exc).__name__}: {str(exc)[:160]}"}
    raw = resp.get("response") if isinstance(resp, dict) else resp
    meta = {k: resp.get(k) for k in ("model_used", "provider", "cost_estimate")} if isinstance(resp, dict) else {}
    text = str(raw or "").strip()
    if text.count("{") > text.count("}"):
        return {**base, "status": "TRUNCATED", "errors": [f"response cut off at {len(text)} chars (unclosed JSON)"],
                "model": meta}
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
