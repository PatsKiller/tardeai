"""Governed research quality / critique. No future outcomes as inputs."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
VERDICTS = ("VALID", "PARTIAL", "STALE", "CONFLICTED", "INSUFFICIENT", "FAILED")

# The tighter imperative gate (execution_language.find_imperative) applies to
# results completed from here on. Artifacts already in the store keep the verdict
# they were admitted under: re-running critique must not silently detach research
# a plan is already relying on. Exactly one stored result would have flipped, an
# SRNE artifact reading "exit the position" whose plan is already cancelled — the
# grandfather is a rule, not a rescue.
#
# The legacy floor below still applies to every result, new or old, so nothing is
# loosened for the grandfathered set.
IMPERATIVE_GATE_EFFECTIVE = datetime(2026, 8, 29, 5, 0, tzinfo=timezone.utc)
LEGACY_FORBIDDEN = ("ignore all rules", "place an order")


def _completed_at(result: dict[str, Any]) -> Any:
    for key in ("completed_ts", "as_of", "created_ts", "freshness_date"):
        raw = str(result.get(key) or "").strip()
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def imperative_gate_applies(result: dict[str, Any]) -> bool:
    """New completes only. An undated artifact is treated as pre-existing."""
    at = _completed_at(result)
    return at is not None and at >= IMPERATIVE_GATE_EFFECTIVE


def critique(result: dict[str, Any], *, backend: str = "lint",
             plan_id: Any = None, research_id: Any = None,
             question_ids: Any = None, generate: Any = None) -> dict[str, Any]:
    """Deterministic lint by default; a live Grok critique only on request.

    `backend` defaults to "lint", so every existing caller, dry run, stub run
    and test path behaves exactly as before — this function has no network in
    its default mode and never acquires one implicitly.

    `backend="live"` routes to cio_grok_critique, which is the call site
    specified in docs/ops/CIO_GROK_CRITIQUE_CONTRACT_2026-08-29.md. The live
    path still runs the local lint first and returns the lint verdict when it
    already fails: there is nothing to ask a model about an artifact our own
    matcher has already rejected, and spending a call to be told so twice is
    just spending a call.
    """
    lint = _critique_lint(result)
    if str(backend or "lint").lower() != "live":
        return lint
    if lint.get("verdict") in {"FAILED", "INSUFFICIENT"}:
        lint["backend"] = "lint"
        lint["live_skipped"] = "local_lint_already_failed"
        lint["calls_made"] = 0
        return lint
    try:
        from scripts.lib.cio_grok_critique import critique_live
    except Exception as exc:                                    # noqa: BLE001
        lint["backend"] = "lint"
        lint["live_error"] = str(exc)[:120]
        lint["calls_made"] = 0
        return lint
    live = critique_live(result, plan_id=plan_id, research_id=research_id,
                         question_ids=question_ids, generate=generate)
    live["backend"] = "live"
    live["lint_verdict"] = lint.get("verdict")
    live["lint_reasons"] = lint.get("reasons")
    try:
        from scripts.lib.cio_operator_artifacts import record_grok_critique

        record_grok_critique(live, producer="research_quality.critique_live",
                             artifact_id=f"{research_id}:{plan_id}" if research_id else None,
                             links={"research_id": research_id, "plan_id": plan_id})
    except Exception:
        pass
    return live


def _critique_lint(result: dict[str, Any]) -> dict[str, Any]:
    sources = result.get("sources") or result.get("source_urls") or []
    if isinstance(sources, str):
        sources = [sources]
    claims = result.get("claims") or result.get("summary") or ""
    text = str(claims).lower()
    as_of = str(result.get("as_of") or result.get("freshness_date") or "")
    symbol = str(result.get("symbol") or "")
    reasons: list[str] = []
    if not text or text.strip() in {"", "n/a", "todo"}:
        reasons.append("empty_summary")
    if not sources:
        reasons.append("no_sources")
    if any(p in text for p in LEGACY_FORBIDDEN):
        # Legacy floor — applies to every result, new or grandfathered.
        reasons.append("forbidden_authority")
    elif imperative_gate_applies(result):
        # One shared matcher with the ingest gate; grammatical, not a word list.
        try:
            from scripts.lib.execution_language import (
                find_field_directive, find_imperative,
            )
        except Exception:
            find_imperative = None      # fail open to the legacy floor
            find_field_directive = None
        # Both are computed, not short-circuited: the shared matcher decides
        # PASS/FAIL, and the field lint supplies the field name for the
        # receipt. Running only the first would fail an artifact without ever
        # saying which field carried the instruction.
        _imp = find_imperative(result) if find_imperative is not None else None
        _fd = (find_field_directive(result)
               if find_field_directive is not None else None)
        if _imp or _fd:
            reasons.append("forbidden_authority")
        if _fd:
            # Field-scoped, stricter: `desk_implications.notes` and
            # `recommendation` exist to direct the operator, so a prohibition
            # counts there even when it carries a settlement qualifier that
            # would keep it admitted in free prose ("do not sell shares before
            # the ex-date"). Location decides. Same gate date, nothing is
            # retro-detached.
            reasons.append(
                "instruction_in_" + str(_fd.get("field") or "field"))
    if symbol and symbol.lower() not in text and symbol not in str(result):
        reasons.append("symbol_not_grounded")
    if "as of 20" not in text and not as_of:
        reasons.append("no_as_of")
    if "however" in text and "contradict" in text:
        reasons.append("unresolved_contradiction")
    if "forbidden_authority" in reasons:
        verdict = "FAILED"
    elif "empty_summary" in reasons:
        verdict = "INSUFFICIENT"
    elif "no_sources" in reasons:
        verdict = "PARTIAL"
    elif "unresolved_contradiction" in reasons:
        verdict = "CONFLICTED"
    elif reasons:
        verdict = "PARTIAL"
    else:
        verdict = "VALID"
    return {
        "schema": "ResearchCritique@v1",
        "verdict": verdict,
        "reasons": reasons,
        "source_count": len(sources),
        "authority": AUTHORITY,
        "financial_action": False,
        "research_id": result.get("research_id") or result.get("result_id"),
        "symbol": symbol,
    }


def evidence_eligibility(request: dict, result: dict, critique: dict | None, *, now=None) -> dict:
    """Validate subject and freshness before research may change advisory state."""
    from scripts.lib.intelligence_client import DEFAULT_ANSWER_SLA_HOURS, EVIDENCE_SLA_HOURS

    now = now or datetime.now(timezone.utc)
    reasons = []
    meta = request.get("metadata") or {}
    identities = {}
    for field in ("symbol", "subject_guid", "issuer_guid"):
        expected = request.get(field) or meta.get(field)
        actual = result.get(field)
        if field == "symbol":
            expected, actual = str(expected or "").upper(), str(actual or "").upper()
        if expected and actual and str(expected) != str(actual):
            reasons.append("subject_mismatch:" + field)
        identities[field] = actual or expected or None
    if not (result.get("result_id") or result.get("research_id")):
        reasons.append("research_identity_missing")
    expected_research = request.get("research_id") or meta.get("research_id")
    if expected_research and result.get("research_id") and str(expected_research) != str(result["research_id"]):
        reasons.append("research_request_mismatch")
    if str(result.get("status") or "completed").lower() not in {"completed", "sent", "success", "succeeded", "ok"}:
        reasons.append("research_not_completed")
    if not (identities["symbol"] or identities["subject_guid"]):
        reasons.append("subject_missing")
    verdict = str((critique or {}).get("verdict") or "").upper()
    if verdict not in {"VALID", "PARTIAL", "CONFLICTED"}:
        reasons.append("quality_" + (verdict.lower() or "unvalidated"))
    sources = result.get("sources") or result.get("source_urls") or result.get("source_refs") or []
    if isinstance(sources, str):
        sources = [sources]
    refs = []
    for source in sources:
        ref = (source.get("evidence_id") or source.get("source_id") or source.get("url") or source.get("id")) if isinstance(source, dict) else source
        if ref:
            refs.append(str(ref))
    if not refs:
        reasons.append("insufficient_sources")
    freshness = result.get("freshness") if isinstance(result.get("freshness"), dict) else {}
    raw = result.get("evidence_as_of") or freshness.get("evidence_as_of") or result.get("as_of") or result.get("completed_ts")
    def parse(value):
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt if dt.tzinfo else None
        except (ValueError, TypeError):
            return None
    at = parse(raw)
    qclass = str(request.get("question_class") or "thesis").lower()
    sla = DEFAULT_ANSWER_SLA_HOURS.get(qclass, EVIDENCE_SLA_HOURS)
    if at is None:
        reasons.append("evidence_time_missing_or_ambiguous")
    elif at > now:
        reasons.append("evidence_from_future")
    elif (now - at).total_seconds() > sla * 3600:
        reasons.append("stale_evidence")
    expiry = result.get("expires_at") or result.get("valid_until") or freshness.get("expires_at")
    if expiry and (parse(expiry) is None or parse(expiry) <= now):
        reasons.append("expired_evidence")
    if str(freshness.get("state") or "").upper() in {"STALE", "EXPIRED", "UNKNOWN"}:
        reasons.append("freshness_" + freshness["state"].lower())
    return {"eligible": not reasons, "reasons": reasons, "evidence_refs": sorted(set(refs)),
            "evidence_as_of": raw, "freshness_sla_hours": sla, **identities}


def grounded_premise_conflicts(result: dict, prior_thesis: dict, *, evidence_refs: list[str]) -> list[dict]:
    """Only cited conflicts against an identified prior premise require review.

    A model classification or a generic bear case is not a verified transition.
    Existing evidence identities must support the cited claim and the prior premise.
    """
    premises = prior_thesis.get("invalidation_conditions") or prior_thesis.get("premises") or []
    known = set()
    if not isinstance(premises, list):
        premises = [premises]
    for premise in premises:
        if isinstance(premise, dict):
            known.update(str(premise[k]) for k in ("premise_id", "id", "text") if premise.get(k))
        else:
            known.add(str(premise))
    known.update(str(prior_thesis[k]) for k in ("summary", "thesis", "recommendation") if prior_thesis.get(k))
    refs = set(evidence_refs)
    out = []
    rows = []
    for key in ("contradictory_evidence", "invalidation_evidence"):
        values = result.get(key) or []
        rows.extend(values if isinstance(values, list) else [values])
    for row in rows:
        if not isinstance(row, dict):
            continue
        premise = str(row.get("premise_id") or row.get("premise") or "")
        cited = row.get("evidence_refs") or row.get("source_refs") or [row.get("source_id") or row.get("url")]
        if isinstance(cited, str):
            cited = [cited]
        cited = [str(r) for r in cited if r]
        # Verify the premise and source join, not the truth of a model label.
        # This opens a review; it never ratifies an invalidation or changes stance.
        if row.get("validated") is not False and premise in known and cited and set(cited) <= refs:
            out.append({"premise": premise, "evidence_refs": cited,
                        "kind": "INVALIDATION" if row.get("invalidates") is True else "CONFLICT"})
    return out
