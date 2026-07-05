"""Universal Research Discovery Layer — Stage 2 LLM review lane (spec Part D).

review_candidate() runs an ADVISORY-ONLY LLM triage pass over one discovery
candidate and stores the result as meta_json.llm_review_json plus a
hermes_discovery_audit row (action LLM_REVIEW). It NEVER promotes, approves,
or transitions a candidate:

  HARD RULES (each enforced in code and covered by
  tests/test_hermes_discovery_llm_review.py):
    * A review may only update recommended_action / risk_flags / review
      metadata. The persist statement never touches status /
      safe_action_level / decided_* — and the post-write invariant check
      raises if status drifted anyway.
    * TICKER candidates: symbol_validation's verdict is authoritative. A
      review can never flip NEEDS_VALIDATION -> valid: promotive
      recommended_actions degrade to needs_more_data unless the stored
      ticker_validation verdict is VALID, and meta_json.ticker_validation is
      never rewritten.
    * Professional-review domains (taxes / retirement / legal / medical —
      i.e. domain_policy.requires_professional_review_label) force
      legal_tax_sensitive=true + needs_professional_review=true, and an
      empty required_citations list degrades recommended_action to
      needs_more_data (reject/block are allowed to stand — they need no
      citations and promote nothing).
    * The prompt instructs strict structured-JSON output; parsing is
      defensive — unparseable output is audited as LLM_REVIEW_FAILED
      ("review_failed") with NO meta write.

Lane policy (External LLM policy, docs/hermes/EXTERNAL_LLM_USAGE_POLICY_*.md):
  * Local gemma first, always: local_llm.generate(..., fallback=False) — the
    metered OpenAI/Anthropic fallbacks inside local_llm are explicitly
    disabled; this lane never spends paid API keys.
  * Cloud escalation goes ONLY to the free-OAuth lanes via
    cloud_review.review (ChatGPT :8646 / Grok :8645), ONLY when
    lanes='auto' AND (domain_policy.llm_review_required OR the local
    relevance_score is ambiguous, 0.4-0.6 inclusive) AND today's cloud
    reviews (audit rows whose lanes_used contains a cloud lane) are below
    config/hermes_discovery_schedule.json cloud_lane_daily_cap.
  * lanes='local' never escalates.
  * Cloud packets are redacted: label/summary/domain/scores only — never
    holdings, accounts, or dollar amounts (subject_json is NOT sent).

120s idle-transaction rule: every DB statement here goes through
db_adapter._execute (one statement, committed immediately), so all reads are
committed BEFORE the slow LLM generation — no transaction is ever held open
across an LLM call.

Advisory-only: never imports broker/execution modules.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import domains, inbox
from .symbol_validation import VERDICT_VALID

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEDULE_PATH = Path(os.getenv("HERMES_DISCOVERY_SCHEDULE_JSON")
                     or PROJECT_ROOT / "config" / "hermes_discovery_schedule.json")

REVIEW_VERSION = "discovery-llm-review-v1"

RECOMMENDED_ACTIONS = frozenset({
    "observe_only", "needs_more_data", "approve_research_topic",
    "approve_source", "approve_watch_directive", "stage_ticker_review",
    "reject", "block",
})

# Actions that would move a candidate toward promotion if an operator adopts
# them — these are the ones the hard rules are allowed to degrade.
PROMOTIVE_ACTIONS = frozenset({
    "approve_research_topic", "approve_source", "approve_watch_directive",
    "stage_ticker_review",
})

# Non-promotive actions that stand even without citations (they need none).
_CITATION_EXEMPT_ACTIONS = frozenset({"reject", "block"})

CLOUD_LANES = ("chatgpt", "grok")

# Exact llm_review_json key set (spec Part D) — schema test asserts equality.
REVIEW_SCHEMA_KEYS = (
    "review_version", "reviewed_at", "lanes_used", "domain", "candidate_type",
    "relevance_score", "source_quality_score", "novelty_score", "risk_score",
    "hallucination_risk", "duplicate_risk", "legal_tax_sensitive",
    "needs_professional_review", "recommended_action", "reasoning_summary",
    "evidence_gaps", "required_citations", "confidence", "advisory_only",
)

# Reviews the local lane rates ambiguous get a cloud second opinion.
AMBIGUOUS_LOW, AMBIGUOUS_HIGH = 0.4, 0.6

DEFAULT_CAPS = {"llm_review_daily_cap": 20, "cloud_lane_daily_cap": 5}

REVIEWABLE_STATUSES = ("READY_FOR_REVIEW", "NEEDS_VALIDATION")


class LLMReviewError(inbox.DiscoveryInboxError):
    """Raised on invariant violations inside the review lane."""


# ── config ───────────────────────────────────────────────────────────────────

def _schedule_caps() -> dict[str, int]:
    """Daily caps from config/hermes_discovery_schedule.json (fail-soft to
    the spec defaults 20/5 — a broken config must not disable the caps)."""
    caps = dict(DEFAULT_CAPS)
    try:
        cfg = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
        for key in caps:
            if isinstance(cfg.get(key), (int, float)):
                caps[key] = int(cfg[key])
    except Exception:
        pass
    return caps


# ── seams (monkeypatched by tests; thin by design) ───────────────────────────

def _fetch_candidate(candidate_id: int) -> dict[str, Any] | None:
    return inbox.get_candidate(candidate_id)


def _write_review(candidate_id: int, meta_json: dict, risk_flags: list) -> dict[str, Any]:
    """Persist the review. ONLY meta_json / risk_flags / updated_at — the SET
    list deliberately excludes status, safe_action_level and decided_* (the
    no-promotion hard rule is structural, then re-verified by the caller)."""
    row = inbox._exec(
        """UPDATE hermes_discovery_candidates
           SET meta_json = %s::jsonb, risk_flags = %s::jsonb, updated_at = NOW()
           WHERE id = %s RETURNING *""",
        (json.dumps(meta_json, default=str), json.dumps(risk_flags, default=str),
         candidate_id), fetch="one")
    if row is None:
        raise inbox.DBUnavailableError("llm review persist failed")
    return dict(row)


def _audit_review(candidate_id: int, action: str, actor: str,
                  before: dict | None, after: dict | None, notes: str) -> None:
    inbox._audit(candidate_id, action, actor, before, after, notes)


def _count_llm_reviews_today(cloud_only: bool = False) -> int:
    """Today's review attempts from the audit trail (UTC-day of the DB).

    cloud_only=True counts only LLM_REVIEW rows whose stored
    lanes_used contains a cloud lane — this is the cloud_lane_daily_cap
    counter. The total counter includes LLM_REVIEW_FAILED so a bad-output
    loop can't burn unlimited local attempts either.
    """
    if cloud_only:
        row = inbox._exec(
            """SELECT count(*) AS n FROM hermes_discovery_audit
               WHERE action = 'LLM_REVIEW'
                 AND created_at >= date_trunc('day', now())
                 AND (after_json #> '{meta_json,llm_review_json,lanes_used}') ?| %s""",
            (list(CLOUD_LANES),), fetch="one")
    else:
        row = inbox._exec(
            """SELECT count(*) AS n FROM hermes_discovery_audit
               WHERE action IN ('LLM_REVIEW', 'LLM_REVIEW_FAILED')
                 AND created_at >= date_trunc('day', now())""",
            fetch="one")
    return int(dict(row or {}).get("n") or 0)


def _local_generate(prompt: str) -> str:
    """Local gemma lane. fallback=False is the policy line: local_llm's
    OpenAI/Anthropic fallbacks are metered keys — never used for this lane."""
    import local_llm
    return local_llm.generate(
        prompt,
        timeout=int(os.getenv("HERMES_DISCOVERY_LLM_TIMEOUT", "120")),
        fallback=False, fast=True,
        caller="hermes_discovery_llm_review",
        process_type="DISCOVERY_REVIEW")


def _cloud_available() -> bool:
    try:
        import cloud_review
        return bool(cloud_review.available())
    except Exception:
        return False


def _cloud_review(local_review: dict, candidate: dict, domain: str) -> dict:
    """Free-OAuth second opinion (ChatGPT/Grok). Redacted context only —
    label/summary/domain/scores; never holdings, accounts or amounts."""
    import cloud_review
    ctype = str(candidate.get("candidate_type") or "").upper()
    context = {
        "candidate_type": ctype,
        "research_domain": domain,
        "label": str(candidate.get("label") or "")[:200],
        "summary": str(candidate.get("summary") or "")[:400],
        "discovery_score": candidate.get("discovery_score"),
        "seen_count": candidate.get("seen_count"),
        "local_review": {k: local_review.get(k) for k in (
            "relevance_score", "source_quality_score", "novelty_score",
            "risk_score", "recommended_action", "confidence")},
    }
    symbol = (str(candidate.get("label") or "").upper()
              if ctype == "TICKER_CANDIDATE" else None)
    return cloud_review.review(
        "hermes_discovery_candidate_review",
        local_output=json.dumps(local_review, default=str)[:3500],
        context=context, symbol=symbol, source="hermes_discovery_llm_review")


# ── prompt ───────────────────────────────────────────────────────────────────

def build_review_prompt(candidate: dict[str, Any], domain: str,
                        policy: dict[str, Any]) -> str:
    """Structured-JSON review prompt for the local lane.

    Explicitly instructs: JSON-only output with the exact schema keys, the
    recommended_action enum, and the advisory framing (the model's verdict
    never changes candidate status — an operator decides)."""
    meta = candidate.get("meta_json") or {}
    evidence = []
    for item in (candidate.get("evidence_json") or [])[:6]:
        if isinstance(item, dict):
            evidence.append({k: item.get(k) for k in ("source_domain", "url", "note")
                             if item.get(k)})
    tv = (meta.get("ticker_validation") or {}) if isinstance(meta, dict) else {}
    lines = [
        "You are an ADVISORY-ONLY research triage reviewer for a personal",
        "paper-trading research system's discovery inbox. You review one",
        "discovered research candidate. Your output NEVER changes the",
        "candidate's status and NEVER places, sizes, or routes any trade —",
        "a human operator makes every decision. Never give personal",
        "financial, tax, legal, or medical advice. Never invent facts,",
        "tickers, citations, or numbers not present in the input.",
        "",
        "CANDIDATE:",
        f"  candidate_type: {candidate.get('candidate_type')}",
        f"  label: {str(candidate.get('label') or '')[:200]}",
        f"  summary: {str(candidate.get('summary') or '')[:500]}",
        f"  research_domain: {domain} (risk_level={policy.get('risk_level')})",
        f"  discovery_score: {candidate.get('discovery_score')}",
        f"  seen_count: {candidate.get('seen_count')}",
        f"  in_duplicate_cluster: {bool(candidate.get('duplicate_cluster_id'))}",
        f"  source_domain: {candidate.get('source_domain')}",
        f"  evidence: {json.dumps(evidence, default=str)[:1200]}",
    ]
    if str(candidate.get("candidate_type") or "").upper() == "TICKER_CANDIDATE":
        lines += [
            f"  symbol_validation_verdict: {tv.get('verdict')} "
            f"(reason: {tv.get('reason')})",
            "  NOTE: symbol validation is AUTHORITATIVE. If the verdict is not",
            "  VALID you must not recommend stage_ticker_review or any approve_*.",
        ]
    if policy.get("requires_professional_review_label"):
        lines += [
            "",
            f"  This domain ({domain}) is a professional-review domain",
            "  (tax/retirement/legal/medical). You MUST set",
            "  legal_tax_sensitive=true and needs_professional_review=true,",
            "  and required_citations MUST list the authoritative sources an",
            "  operator should verify (e.g. IRS pubs, statutes, filings).",
        ]
    lines += [
        "",
        "Score the candidate. All *_score / *_risk / confidence values are",
        "floats in [0,1]. recommended_action MUST be exactly one of:",
        "  observe_only | needs_more_data | approve_research_topic |",
        "  approve_source | approve_watch_directive | stage_ticker_review |",
        "  reject | block",
        "(approve_* / stage_ticker_review are advisory suggestions to the",
        "operator only; block = harmful/spam; reject = not useful.)",
        "",
        "Respond with ONLY one JSON object — no markdown fences, no prose",
        "before or after — with EXACTLY these keys:",
        json.dumps({
            "relevance_score": 0.0, "source_quality_score": 0.0,
            "novelty_score": 0.0, "risk_score": 0.0,
            "hallucination_risk": 0.0, "duplicate_risk": 0.0,
            "legal_tax_sensitive": False, "needs_professional_review": False,
            "recommended_action": "observe_only",
            "reasoning_summary": "1-3 sentences",
            "evidence_gaps": ["..."], "required_citations": ["..."],
            "confidence": 0.0,
        }, indent=2),
    ]
    return "\n".join(lines)


# ── defensive parsing / normalization ────────────────────────────────────────

def parse_review_output(raw: Any) -> dict[str, Any] | None:
    """Extract the first {...} JSON object from raw model output.
    Returns None on anything unparseable (caller records review_failed)."""
    txt = str(raw or "").strip()
    if not txt:
        return None
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _clamp01(value: Any, default: float = 0.5) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if f != f:  # NaN
        return default
    return max(0.0, min(1.0, round(f, 4)))


def _str_list(value: Any, cap: int = 8, maxlen: int = 300) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(v).strip()[:maxlen] for v in value if str(v).strip()][:cap]
    if isinstance(value, str) and value.strip():
        return [value.strip()[:maxlen]]
    return []


def _normalize_review(obj: dict[str, Any]) -> dict[str, Any]:
    """Coerce a parsed model object into the review fields (defensive:
    scores clamped to [0,1], unknown recommended_action -> needs_more_data)."""
    review = {
        "relevance_score": _clamp01(obj.get("relevance_score")),
        "source_quality_score": _clamp01(obj.get("source_quality_score")),
        "novelty_score": _clamp01(obj.get("novelty_score")),
        "risk_score": _clamp01(obj.get("risk_score")),
        "hallucination_risk": _clamp01(obj.get("hallucination_risk")),
        "duplicate_risk": _clamp01(obj.get("duplicate_risk")),
        "legal_tax_sensitive": bool(obj.get("legal_tax_sensitive")),
        "needs_professional_review": bool(obj.get("needs_professional_review")),
        "recommended_action": str(obj.get("recommended_action") or "").strip().lower(),
        "reasoning_summary": str(obj.get("reasoning_summary") or "").strip()[:1200],
        "evidence_gaps": _str_list(obj.get("evidence_gaps")),
        "required_citations": _str_list(obj.get("required_citations")),
        "confidence": _clamp01(obj.get("confidence")),
    }
    if review["recommended_action"] not in RECOMMENDED_ACTIONS:
        review["evidence_gaps"] = (review["evidence_gaps"]
                                   + [f"model returned invalid recommended_action "
                                      f"{review['recommended_action']!r}"])[:8]
        review["recommended_action"] = "needs_more_data"
    return review


# ── hard rules ───────────────────────────────────────────────────────────────

def apply_hard_rules(review: dict[str, Any], candidate: dict[str, Any],
                     policy: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Post-LLM enforcement (runs LAST so no lane can undo it). Returns
    (review, rule_notes)."""
    notes: list[str] = []
    meta = candidate.get("meta_json") or {}
    if not isinstance(meta, dict):
        meta = {}

    # Rule: symbol_validation is authoritative for TICKER candidates.
    if str(candidate.get("candidate_type") or "").upper() == "TICKER_CANDIDATE":
        verdict = str((meta.get("ticker_validation") or {}).get("verdict")
                      or "").upper()
        if verdict != VERDICT_VALID and review["recommended_action"] in PROMOTIVE_ACTIONS:
            notes.append(f"ticker override: symbol_validation verdict "
                         f"{verdict or 'MISSING'} is authoritative — "
                         f"{review['recommended_action']} degraded to needs_more_data")
            review["evidence_gaps"] = (review["evidence_gaps"] + [
                "symbol not validated by symbol_validation (authoritative) — "
                "review cannot flip it valid"])[:8]
            review["recommended_action"] = "needs_more_data"

    # Rule: professional-review domains (taxes/retirement/legal/medical).
    if policy.get("requires_professional_review_label"):
        review["legal_tax_sensitive"] = True
        review["needs_professional_review"] = True
        if not review["required_citations"] and \
                review["recommended_action"] not in _CITATION_EXEMPT_ACTIONS:
            notes.append("sensitive domain without citations — "
                         f"{review['recommended_action']} degraded to needs_more_data")
            review["evidence_gaps"] = (review["evidence_gaps"] + [
                f"required_citations empty for professional-review domain "
                f"{policy.get('name')} — citations required"])[:8]
            review["recommended_action"] = "needs_more_data"

    review["advisory_only"] = True
    return review, notes


# ── cloud escalation policy ──────────────────────────────────────────────────

def _escalation_decision(review: dict[str, Any], policy: dict[str, Any],
                         lanes: str, caps: dict[str, int]) -> dict[str, Any]:
    """Decide (and explain) whether this review goes to the cloud lanes."""
    decision = {"escalate": False, "reason": None, "cloud_used_today": None}
    if lanes != "auto":
        decision["reason"] = f"lanes={lanes} — cloud disabled"
        return decision
    required = bool(policy.get("llm_review_required"))
    ambiguous = AMBIGUOUS_LOW <= review["relevance_score"] <= AMBIGUOUS_HIGH
    if not (required or ambiguous):
        decision["reason"] = "not required and relevance not ambiguous"
        return decision
    used = _count_llm_reviews_today(cloud_only=True)
    decision["cloud_used_today"] = used
    if used >= caps["cloud_lane_daily_cap"]:
        decision["reason"] = (f"cloud_lane_daily_cap exhausted "
                              f"({used}/{caps['cloud_lane_daily_cap']})")
        return decision
    if not _cloud_available():
        decision["reason"] = "cloud lanes unavailable"
        return decision
    decision["escalate"] = True
    decision["reason"] = ("domain requires llm review" if required
                          else f"relevance_score {review['relevance_score']} ambiguous")
    return decision


def _apply_cloud_consensus(review: dict[str, Any], cloud: dict[str, Any]
                           ) -> tuple[list[str], list[str]]:
    """Fold the cloud consensus into the review. Returns
    (ok_lane_names, extra_risk_flags)."""
    ok_lanes = [name for name, r in (cloud.get("lanes") or {}).items()
                if isinstance(r, dict) and r.get("ok")]
    flags: list[str] = []
    verdict = str((cloud.get("consensus") or {}).get("verdict") or "UNKNOWN").upper()
    if not ok_lanes:
        return ok_lanes, flags
    if verdict == "DISAGREE":
        flags.append("cloud_review_disagree")
        review["confidence"] = min(review["confidence"], 0.35)
        if review["recommended_action"] in PROMOTIVE_ACTIONS:
            review["evidence_gaps"] = (review["evidence_gaps"] + [
                "cloud lanes disagreed with the local review — needs more data"])[:8]
            review["recommended_action"] = "needs_more_data"
        review["reasoning_summary"] = (review["reasoning_summary"]
                                       + " [cloud consensus: DISAGREE]")[:1200]
    elif verdict == "CAUTION":
        review["confidence"] = min(review["confidence"], 0.6)
        review["reasoning_summary"] = (review["reasoning_summary"]
                                       + " [cloud consensus: CAUTION]")[:1200]
    return ok_lanes, flags


# ── main entrypoint ──────────────────────────────────────────────────────────

def review_candidate(candidate_id: int, lanes: str = "auto", *,
                     actor: str = "llm_review") -> dict[str, Any]:
    """LLM-review one candidate. lanes: 'auto' (local + policy-gated cloud
    escalation) or 'local' (never cloud). Returns
    {ok, candidate_id, status, llm_review_json, lanes_used, escalation}.
    Advisory-only: candidate status is asserted unchanged."""
    if lanes not in ("auto", "local"):
        raise LLMReviewError(f"unknown lanes mode {lanes!r} (valid: auto, local)")
    candidate = _fetch_candidate(candidate_id)
    if not candidate:
        raise inbox.CandidateNotFoundError(f"candidate {candidate_id} not found")
    before = dict(candidate)
    before_status = before.get("status")

    meta = dict(before.get("meta_json") or {})
    domain = str(meta.get("research_domain") or "").strip().lower() \
        or domains.classify_domain(before)
    policy = domains.domain_policy(domain)
    caps = _schedule_caps()

    # All reads above went through auto-commit statements — nothing is held
    # open across the (slow) generation below.
    prompt = build_review_prompt(before, domain, policy)
    raw = _local_generate(prompt)
    parsed = parse_review_output(raw)
    if parsed is None:
        _audit_review(candidate_id, "LLM_REVIEW_FAILED", actor, before, None,
                      f"review_failed: unparseable local LLM output "
                      f"({len(str(raw or ''))} chars) — no meta write")
        return {"ok": False, "candidate_id": candidate_id, "error": "review_failed",
                "status": before_status, "detail": "unparseable LLM output"}

    review = _normalize_review(parsed)
    lanes_used = ["local"]

    escalation = _escalation_decision(review, policy, lanes, caps)
    if escalation["escalate"]:
        try:
            cloud = _cloud_review(review, before, domain)
        except Exception as e:  # cloud is best-effort — never blocks the review
            cloud = {"ok": False, "lanes": {}, "error": str(e)[:200]}
            escalation["reason"] += f" (cloud call failed: {str(e)[:120]})"
        ok_lanes, cloud_flags = _apply_cloud_consensus(review, cloud)
        lanes_used += ok_lanes
    else:
        cloud_flags = []

    # Hard rules LAST — no lane (local or cloud) can undo them.
    review, rule_notes = apply_hard_rules(review, before, policy)

    llm_review_json = {
        "review_version": REVIEW_VERSION,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "lanes_used": lanes_used,
        "domain": domain,
        "candidate_type": before.get("candidate_type"),
        "relevance_score": review["relevance_score"],
        "source_quality_score": review["source_quality_score"],
        "novelty_score": review["novelty_score"],
        "risk_score": review["risk_score"],
        "hallucination_risk": review["hallucination_risk"],
        "duplicate_risk": review["duplicate_risk"],
        "legal_tax_sensitive": review["legal_tax_sensitive"],
        "needs_professional_review": review["needs_professional_review"],
        "recommended_action": review["recommended_action"],
        "reasoning_summary": review["reasoning_summary"],
        "evidence_gaps": review["evidence_gaps"],
        "required_citations": review["required_citations"],
        "confidence": review["confidence"],
        "advisory_only": True,
    }

    # risk_flags: review metadata only, append-merge, no dupes.
    risk_flags = list(before.get("risk_flags") or [])
    additions = list(cloud_flags)
    if review["risk_score"] >= 0.7:
        additions.append("llm_flagged_high_risk")
    for flag in additions:
        if flag not in risk_flags:
            risk_flags.append(flag)

    new_meta = dict(meta)
    new_meta["llm_review_json"] = llm_review_json  # ONLY key this lane writes

    updated = _write_review(candidate_id, new_meta, risk_flags)
    if updated.get("status") != before_status:  # no-promotion invariant
        raise LLMReviewError(
            f"invariant violated: review changed status "
            f"{before_status!r} -> {updated.get('status')!r} for candidate {candidate_id}")

    notes = (f"lanes={','.join(lanes_used)} domain={domain} "
             f"action={review['recommended_action']} "
             f"confidence={review['confidence']}; escalation={escalation['reason']}")
    if rule_notes:
        notes += "; " + "; ".join(rule_notes)
    _audit_review(candidate_id, "LLM_REVIEW", actor, before, updated, notes[:900])

    return {"ok": True, "candidate_id": candidate_id, "status": updated.get("status"),
            "llm_review_json": llm_review_json, "lanes_used": lanes_used,
            "escalation": escalation}


# ── batch selection (CLI --review-ready) ─────────────────────────────────────

def select_review_batch(limit: int = 20, *, include_reviewed: bool = False
                        ) -> dict[str, Any]:
    """Pick READY_FOR_REVIEW + NEEDS_VALIDATION candidates for review, capped
    by llm_review_daily_cap minus today's attempts (LLM_REVIEW +
    LLM_REVIEW_FAILED audit rows). Highest discovery_score first; already
    reviewed candidates skipped unless include_reviewed."""
    caps = _schedule_caps()
    used = _count_llm_reviews_today()
    remaining = max(0, caps["llm_review_daily_cap"] - used)
    take = max(0, min(int(limit), remaining))
    rows: list[dict[str, Any]] = []
    if take:
        skip = "" if include_reviewed \
            else "AND (meta_json -> 'llm_review_json') IS NULL"
        fetched = inbox._exec(
            f"""SELECT * FROM hermes_discovery_candidates
                WHERE status IN %s {skip}
                ORDER BY discovery_score DESC NULLS LAST, id ASC
                LIMIT %s""",
            (REVIEWABLE_STATUSES, take), fetch="all") or []
        rows = [dict(r) for r in fetched]
    return {"daily_cap": caps["llm_review_daily_cap"],
            "cloud_lane_daily_cap": caps["cloud_lane_daily_cap"],
            "used_today": used, "remaining_today": remaining,
            "selected": rows}
