#!/usr/bin/env python3
"""strategy_ticket_review.py — adversarial critics of the EXACT final ticket.

Runs ONLY after deterministic construction and validation. Three free lanes:

    LOCAL_CRITIC          local_llm.generate_local_only (cloud structurally off)
    GROK_OAUTH_CRITIC     free Grok OAuth lane (llm_lane)
    CHATGPT_OAUTH_CRITIC  free ChatGPT OAuth lane (llm_lane)

Every critic receives the same immutable review packet (canonical facts, the
exact ticket, the deterministic validator report) and NO other critic's
verdict. Reviews bind to ticket_hash + facts_hash — a changed ticket voids
them. Critics may PASS/CAUTION/REJECT/UNAVAILABLE; they can NEVER create
mechanics, change prices, grant eligibility, or override a deterministic
failure. One completed lane is SINGLE_LANE, never consensus.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

CRITIC_SCHEMA_KEYS = ("verdict", "math_check", "semantic_contradictions",
                      "missing_evidence", "stale_inputs", "risk_objections")

_SYSTEM = (
    "You are an adversarial trading-desk ticket reviewer. You NEVER create or "
    "adjust mechanics; you only critique the exact ticket given. Independently "
    "recompute the simple arithmetic (risk = entry-stop, reward = target-entry, "
    "R:R = reward/risk for longs; inverted for shorts) from the numbers in the "
    "ticket. Check whether the entry is actionable at the CURRENT price, whether "
    "a watch level is mislabeled as an entry, whether trigger/entry-mode/stop/"
    "target describe ONE coherent setup, whether inputs are stale, and whether "
    "no-trade is more honest. Reply with STRICT JSON only, matching exactly: "
    '{"verdict":"PASS|CAUTION|REJECT","math_check":{"entry_consistent":bool,'
    '"stop_consistent":bool,"target_consistent":bool,"rr_recomputed":number|null,'
    '"rr_matches":bool|null},"semantic_contradictions":[],"missing_evidence":[],'
    '"stale_inputs":[],"risk_objections":[],"questions":[],"evidence_citations":[]}')


def _now():
    return datetime.now(timezone.utc).isoformat()


def build_review_packet(symbol: str, ticket: dict, facts: dict,
                        validation: dict) -> dict:
    """The immutable packet every critic sees (and nothing else)."""
    return {
        "symbol": symbol,
        "current_price": facts.get("live_price") or facts.get("enriched_price"),
        "atr": facts.get("atr"),
        "quote_as_of": facts.get("live_price_as_of") or facts.get("enriched_at"),
        "ticket": {k: ticket.get(k) for k in
                   ("structure", "entry_mode", "entry_state", "entry_zone",
                    "limit_price", "stop_price", "targets", "risk_reward",
                    "trigger", "invalidation", "mechanics_current")},
        "deterministic_validation": {k: validation.get(k) for k in
                                     ("state", "hard_failures", "warnings",
                                      "recomputed", "ticket_hash", "facts_hash")},
    }


def _prompt(pkt: dict) -> str:
    return ("Review this strategy ticket adversarially. Current market truth and "
            "the deterministic validator's independent recomputation are included "
            "— challenge BOTH the ticket and any incoherence you find.\n\n"
            + json.dumps(pkt, indent=1, default=str)
            + "\n\nRemember: STRICT JSON only, the exact schema from your instructions.")


def _parse(text: str) -> dict | None:
    t = (text or "").strip()
    if "```" in t:
        t = t.split("```")[1].lstrip("json").strip()
    try:
        start, end = t.index("{"), t.rindex("}") + 1
        obj = json.loads(t[start:end])
        if str(obj.get("verdict", "")).upper() in ("PASS", "CAUTION", "REJECT"):
            obj["verdict"] = str(obj["verdict"]).upper()
            return obj
    except Exception:
        pass
    return None


def _finish(base: dict, parsed: dict | None, raw_err: str | None = None) -> dict:
    if parsed is None:
        base.update(verdict="UNAVAILABLE",
                    error=raw_err or "unparseable critic response (raw kept in audit)")
        return base
    for k in CRITIC_SCHEMA_KEYS:
        base[k] = parsed.get(k) if parsed.get(k) is not None else base.get(k)
    base["verdict"] = parsed["verdict"]
    base["questions"] = parsed.get("questions") or []
    base["evidence_citations"] = parsed.get("evidence_citations") or []
    return base


def run_local_critic(symbol, ticket, facts, validation) -> dict:
    import local_llm
    pkt = build_review_packet(symbol, ticket, facts, validation)
    base = {"review_type": "LOCAL_CRITIC", "provider_family": "LOCAL_OLLAMA",
            "model": None, "verdict": "UNAVAILABLE",
            "ticket_hash_reviewed": validation.get("ticket_hash"),
            "facts_hash_reviewed": validation.get("facts_hash"),
            "reviewed_at": _now(), "math_check": {}, "semantic_contradictions": [],
            "missing_evidence": [], "stale_inputs": [], "risk_objections": []}
    r = local_llm.generate_local_only(_prompt(pkt), system=_SYSTEM)
    if not r.get("ok"):
        base["error"] = r.get("error")
        return base
    base["model"] = r.get("model")
    return _finish(base, _parse(r.get("text")), "local model returned non-schema text")


def run_oauth_critic(lane: str, symbol, ticket, facts, validation) -> dict:
    """lane: 'grok' | 'chatgpt' — the free OAuth lanes, independently."""
    import llm_lane
    pkt = build_review_packet(symbol, ticket, facts, validation)
    fam = {"grok": "XAI", "chatgpt": "OPENAI"}[lane]
    base = {"review_type": f"{lane.upper()}_OAUTH_CRITIC", "provider_family": fam,
            "model": None, "verdict": "UNAVAILABLE",
            "ticket_hash_reviewed": validation.get("ticket_hash"),
            "facts_hash_reviewed": validation.get("facts_hash"),
            "reviewed_at": _now(), "math_check": {}, "semantic_contradictions": [],
            "missing_evidence": [], "stale_inputs": [], "risk_objections": []}
    try:
        if not llm_lane.available(lane):
            base["error"] = f"{lane} lane unavailable"
            return base
        out = llm_lane.generate(lane, _SYSTEM + "\n\n" + _prompt(pkt),
                                max_tokens=900)
        text = out.get("text") if isinstance(out, dict) else str(out)
        base["model"] = (out.get("model") if isinstance(out, dict) else None) or lane
        return _finish(base, _parse(text), f"{lane} returned non-schema text")
    except Exception as e:
        base["error"] = f"{type(e).__name__}: {str(e)[:140]}"
        return base


def run_free_reviews(symbol, ticket, facts, validation, *,
                     lanes=("local", "grok", "chatgpt")) -> dict:
    """Run the configured free critics on the exact ticket. Never consensus with
    fewer than two completed independent provider families."""
    reviews = {}
    if "local" in lanes:
        reviews["local"] = run_local_critic(symbol, ticket, facts, validation)
    if "grok" in lanes:
        reviews["grok"] = run_oauth_critic("grok", symbol, ticket, facts, validation)
    if "chatgpt" in lanes:
        reviews["chatgpt"] = run_oauth_critic("chatgpt", symbol, ticket, facts, validation)
    completed = [r for r in reviews.values() if r["verdict"] != "UNAVAILABLE"]
    fams = {r["provider_family"] for r in completed}
    reviews["_meta"] = {
        "completed": len(completed), "independent_families": len(fams),
        "consensus_possible": len(fams) >= 2,
        "single_lane": len(completed) == 1,
        "reviewed_at": _now(),
    }
    return reviews
