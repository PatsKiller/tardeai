#!/usr/bin/env python3
"""blind_review_runner.py — the impure half of the blind pass.

blind_review.py is PURE: it builds prompts, refuses anchors, and measures
agreement. This module is what actually calls the model lanes, parses their
JSON, and turns a set of completed first passes into a reconciled result. The
split is deliberate — the agreement arithmetic and the blindness guarantee are
testable without a network, and only the network lives here.

THE TWO INVARIANTS THIS ENFORCES AT RUNTIME
-------------------------------------------
1. Every lane receives the SAME facts packet and NO verdict from anyone. The
   packet passes through blind_review.assert_blind() before a single call is
   made, so a stray anchor key aborts the whole pass rather than quietly
   producing correlated "agreement".

2. A lane that times out, errors, or returns unparseable output is NOT a lane.
   It contributes nothing to the agreement count. One completed lane can never
   be a consensus — measure_agreement() already returns SINGLE_SOURCE, and the
   badge discloses it.

WHY grok + chatgpt + local
--------------------------
Two independent cloud lanes plus the local model give a genuine three-way first
pass. The value is in the DISAGREEMENT: when the cloud lanes split on timing but
agree on thesis, that is the signal the one-word verdict destroyed.

A model MAY interpret evidence into a thesis/direction/timing view. It may NOT
author a price, a payoff, or an eligibility decision — those stay in
deterministic code. This module only ever writes into the packet's HORIZON
dimensions (thesis, direction, timing, confidence), never into a family's
mechanics or state.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import blind_review as br             # noqa: E402
import decision_packet as dp          # noqa: E402

LANE_MODEL = {"chatgpt": "gpt-5.4", "grok": "grok-3-mini", "local": None}

# Default is the two GENUINELY independent cloud lanes: grok (xAI) and chatgpt
# (OpenAI). The `local` lane is deliberately NOT in the default — when the local
# Ollama is down it falls back to gpt-4o-mini, i.e. another OpenAI model, which
# correlates with the chatgpt lane and inflates apparent agreement while adding
# ~240s of timeout ladder. Two independent providers is an honest blind pass;
# add `local` via BLIND_REVIEW_LANES only when Ollama is healthy.
def _default_lanes():
    raw = os.getenv("BLIND_REVIEW_LANES", "grok,chatgpt")
    return tuple(x.strip().lower() for x in raw.split(",") if x.strip())


BLIND_TIMEOUT = int(os.getenv("BLIND_REVIEW_TIMEOUT", "90"))


def _parse_json(raw: str) -> dict | None:
    """Extract the JSON object a model returned. Models wrap output in prose or
    ```json fences; a lane whose output cannot be parsed is treated as a lane
    that did not complete, never as an empty-but-present opinion."""
    if not raw:
        return None
    text = str(raw).strip()
    # strip a fenced block if present
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _sanitise(out: dict) -> dict:
    """Coerce a lane's output to the known vocabularies. An out-of-vocabulary
    token becomes the safe 'unresolved' value rather than propagating a made-up
    state into the packet — the model interprets, but only within the contract.
    """
    def pick(value, allowed, fallback):
        return value if value in allowed else fallback

    lt = out.get("long_term_thesis") or {}
    tt = out.get("tactical_timing") or {}
    di = out.get("direction") or {}
    inst = out.get("instrument") or {}
    er = out.get("event_risk") or {}

    def conf(x):
        try:
            return max(0.0, min(1.0, float(x)))
        except (TypeError, ValueError):
            return 0.0

    return {
        "long_term_thesis": {
            "state": pick(lt.get("state"), dp.THESIS_STATES, "INSUFFICIENT_EVIDENCE"),
            "confidence": conf(lt.get("confidence")),
            "why": [str(x)[:240] for x in (lt.get("why") or [])][:6],
            "what_changes_view": [str(x)[:240] for x in (lt.get("what_changes_view") or [])][:6],
        },
        "tactical_timing": {
            "state": pick(tt.get("state"), dp.TIMING_STATES, "NO_VALID_SETUP"),
            "confidence": conf(tt.get("confidence")),
            "trigger": str(tt.get("trigger") or "")[:240],
            "invalidation": str(tt.get("invalidation") or "")[:240],
        },
        "direction": {
            "tactical": pick(di.get("tactical"), dp.DIRECTIONS, "UNRESOLVED"),
            "swing": pick(di.get("swing"), dp.DIRECTIONS, "UNRESOLVED"),
            "long_term": pick(di.get("long_term"), dp.DIRECTIONS, "UNRESOLVED"),
        },
        "instrument": {
            "preferred": str(inst.get("preferred") or "")[:60],
            "why": [str(x)[:240] for x in (inst.get("why") or [])][:6],
            "rejected": [str(x)[:60] for x in (inst.get("rejected") or [])][:8],
        },
        "event_risk": {
            "impact": pick(str(er.get("impact") or "").upper(), dp.EVENT_STATES, "UNKNOWN"),
            "detail": str(er.get("detail") or "")[:240],
        },
        "data_sufficient": bool(out.get("data_sufficient")),
        "evidence_used": [str(x)[:120] for x in (out.get("evidence_used") or [])][:12],
        "unresolved_questions": [str(x)[:200] for x in (out.get("unresolved_questions") or [])][:8],
    }


def run_one_lane(lane: str, facts: dict, *, timeout: int = BLIND_TIMEOUT) -> dict:
    """Call one lane blind. Returns {ok, lane, model, output|error}. Never raises
    — a lane failure must degrade the pass, not abort it."""
    import llm_lane
    result = {"ok": False, "lane": lane, "model": LANE_MODEL.get(lane)}
    try:
        if not llm_lane.available(lane):
            result["error"] = f"{lane} lane unavailable"
            return result
    except Exception as exc:
        result["error"] = f"availability check failed: {type(exc).__name__}"
        return result

    # Blindness is re-checked here, immediately before the call, so nothing added
    # to the packet between construction and dispatch can slip an anchor through.
    try:
        prompt = br.build_blind_prompt(facts)
    except br.BlindnessViolation as exc:
        result["error"] = f"BLINDNESS VIOLATION (pass aborted): {exc}"
        result["fatal"] = True
        return result

    try:
        raw = llm_lane.generate(prompt, lane=lane, timeout=timeout,
                                model=LANE_MODEL.get(lane))
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return result

    parsed = _parse_json(raw)
    if parsed is None:
        result["error"] = "unparseable output"
        result["raw_preview"] = str(raw)[:200]
        return result

    result["ok"] = True
    result["output"] = _sanitise(parsed)
    return result


def run_blind_pass(facts: dict, *, lanes=None, timeout: int = BLIND_TIMEOUT) -> dict:
    """Run the blind first pass across lanes and reconcile deterministically.

    Returns a model_review block matching the packet contract, with the
    per-lane raw results attached for audit.
    """
    lanes = tuple(lanes) if lanes else _default_lanes()

    # One assert_blind up front gives a single, clear failure if the facts carry
    # an anchor, rather than N identical per-lane failures.
    try:
        br.assert_blind(facts)
    except br.BlindnessViolation as exc:
        return {"mode": "UNAVAILABLE", "lanes_requested": list(lanes),
                "lanes_completed": [], "agreement_by_dimension": {},
                "minority_views": [], "unresolved": [f"blindness violation: {exc}"],
                "fatal": True, "lane_results": []}

    lane_results = [run_one_lane(ln, facts, timeout=timeout) for ln in lanes]
    completed = {r["lane"]: r["output"] for r in lane_results if r.get("ok")}

    agreement = br.measure_agreement(completed)
    n, requested = len(completed), len(lanes)
    # Mode is relative to what was REQUESTED, but one lane is never a consensus.
    #   all requested lanes completed, >=2 independent  -> BLIND
    #   some completed, >=2                              -> BLIND_PARTIAL
    #   exactly one                                      -> SINGLE_LANE (never consensus)
    #   none                                             -> UNAVAILABLE
    mode = ("UNAVAILABLE" if n == 0 else "SINGLE_LANE" if n == 1
            else "BLIND" if n == requested else "BLIND_PARTIAL")

    # Per-dimension display, e.g. "THESIS 3/3 · TIMING 1/3".
    badge = br.consensus_badge(agreement, blind=True)

    return {
        "mode": mode,
        "lanes_requested": list(lanes),
        "lanes_completed": sorted(completed.keys()),
        "agreement_by_dimension": {d: v.get("display")
                                   for d, v in (agreement.get("dimensions") or {}).items()},
        "agreement_detail": agreement.get("dimensions"),
        "badge": badge,
        "minority_views": _minority_views(completed, agreement),
        "unresolved": _pooled_unresolved(completed),
        "reconciled": _reconcile(completed) if completed else None,
        "lane_results": [{"lane": r["lane"], "ok": r.get("ok"),
                          "error": r.get("error"),
                          "model": r.get("model")} for r in lane_results],
        "_completed_outputs": completed,     # consumed by the caller, not persisted raw
    }


def _minority_views(completed: dict, agreement: dict) -> list:
    """On a split dimension, record what the outvoted lane(s) said, so the
    minority is preserved rather than averaged away."""
    out = []
    for dim, info in (agreement.get("dimensions") or {}).items():
        if info.get("agreement") not in ("SPLIT", "MAJORITY"):
            continue
        votes = info.get("votes") or {}
        ordered = sorted(votes.items(), key=lambda kv: -len(kv[1]))
        for value, srcs in ordered[1:]:
            if value == "UNKNOWN":
                continue
            out.append({"dimension": dim, "view": value, "lanes": srcs})
    return out


def _pooled_unresolved(completed: dict) -> list:
    seen, out = set(), []
    for lane, o in completed.items():
        for q in (o.get("unresolved_questions") or []):
            if q not in seen:
                seen.add(q)
                out.append(q)
    return out[:12]


def _reconcile(completed: dict) -> dict:
    """Deterministic reconciliation: for each dimension take the plurality token,
    confidence-weighted only as a tie-break. Reconciliation is counting, not a
    model's job, so no extra lane is spent here."""
    def plurality(getter, fallback):
        tally: dict = {}
        for lane, o in completed.items():
            v = getter(o)
            if not v or v in ("UNRESOLVED", "UNKNOWN", "INSUFFICIENT_EVIDENCE"):
                continue
            tally.setdefault(v, []).append(lane)
        if not tally:
            return fallback, 0.0, []
        best = max(tally.items(), key=lambda kv: len(kv[1]))
        agree = len(best[1]) / max(1, len(completed))
        return best[0], round(agree, 2), best[1]

    thesis, thesis_agree, thesis_lanes = plurality(
        lambda o: (o.get("long_term_thesis") or {}).get("state"), "INSUFFICIENT_EVIDENCE")
    timing, timing_agree, _ = plurality(
        lambda o: (o.get("tactical_timing") or {}).get("state"), "NO_VALID_SETUP")
    dir_tac, _, _ = plurality(lambda o: (o.get("direction") or {}).get("tactical"), "UNRESOLVED")
    dir_sw, _, _ = plurality(lambda o: (o.get("direction") or {}).get("swing"), "UNRESOLVED")
    dir_lt, _, _ = plurality(lambda o: (o.get("direction") or {}).get("long_term"), "UNRESOLVED")
    instrument, _, _ = plurality(lambda o: (o.get("instrument") or {}).get("preferred"), "")

    # Confidence is the mean across lanes that named the plurality thesis.
    def mean_conf(getter, lanes):
        vals = [float(getter(completed[l]) or 0) for l in lanes] if lanes else []
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    return {
        "thesis_state": thesis,
        "thesis_agreement": thesis_agree,
        "thesis_confidence": mean_conf(
            lambda o: (o.get("long_term_thesis") or {}).get("confidence"), thesis_lanes),
        "tactical_timing": timing,
        "timing_agreement": timing_agree,
        "direction": {"tactical": dir_tac, "swing": dir_sw, "long_term": dir_lt},
        "preferred_instrument": instrument,
    }
