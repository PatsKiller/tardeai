"""Hermes Discovery Inbox — idempotent candidate intake, state machine, audit trail.

Design rules (Stage 1):
  * ADVISORY-ONLY: this package never imports broker/execution modules.
  * Idempotent intake: same (candidate_type, normalized_key) → seen_count bump
    + evidence merge, never a duplicate row (unique index enforces it).
  * Every mutation appends a hermes_discovery_audit row with before/after json.
  * All DB work goes through db_adapter._execute — one statement per call,
    committed immediately, so no transaction is ever held open across slow
    work (the 120s idle-in-transaction guard can't bite us).
  * Operator-created candidates are NEVER auto-merged (see dedupe.py).

Universal Research Discovery Layer enrichment (Stage 1, no migration —
everything lives in meta_json). upsert_candidate stamps these keys on EVERY
candidate (new rows and re-sighting bumps alike):

  meta_json.research_domain        domain name from config/hermes_research_domains.yaml
                                   (+ hermes_custom_research_domains.yaml), via
                                   domains.classify_domain; sticky once set
  meta_json.domain_risk_level      the domain's risk_level (financial|tax|planning|
                                   legal|operational|general|variable|medical)
  meta_json.subject_json           subject envelope built by subjects.build_subject
                                   (subject_id, canonical_label, tickers, holdings
                                   join for TICKER candidates, source refs, …)
  meta_json.advisory_label         always present — advisory-only framing text
  meta_json.required_review_label  ONLY for professional-review domains (taxes /
                                   retirement / legal / medical): the
                                   "consult a qualified professional/clinician"
                                   label. These candidates are also forced to
                                   safe_action_level=OPERATOR_REVIEW_REQUIRED.

Domain registry failures (missing/invalid yaml, unknown domain) fail CLOSED:
intake raises rather than writing unclassified candidates.
"""
from __future__ import annotations

import json
from typing import Any

from . import dedupe, domains, scoring, subjects
from .symbol_validation import (VERDICT_VALID, validate_ticker)

CANDIDATE_TYPES = frozenset({
    "SOURCE_CANDIDATE", "TREND_CANDIDATE", "TICKER_CANDIDATE",
    "TOPIC_CANDIDATE", "CONNECTOR_CANDIDATE",
})

STATUSES = frozenset({
    "DISCOVERED", "CLUSTERED", "NEEDS_VALIDATION", "NEEDS_MORE_DATA",
    "READY_FOR_REVIEW", "APPROVED_RESEARCH_ONLY", "APPROVED_SOURCE",
    "APPROVED_WATCH_DIRECTIVE", "STAGED_TICKER_REVIEW",
    "PROMOTED_TO_WATCH_EVALUATION", "REJECTED", "MERGED_DUPLICATE",
    "BLOCKED", "ARCHIVED_COLD",
})

SAFE_ACTION_LEVELS = frozenset({
    "OBSERVE_ONLY", "RESEARCH_ONLY", "OPERATOR_REVIEW_REQUIRED",
    "AUTO_STAGE_INSIDE_RAILS", "BLOCKED",
})

# Legal state machine. Anything not listed raises IllegalTransitionError.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "DISCOVERED": frozenset({"CLUSTERED", "NEEDS_VALIDATION", "NEEDS_MORE_DATA",
                             "READY_FOR_REVIEW", "REJECTED", "MERGED_DUPLICATE",
                             "BLOCKED", "ARCHIVED_COLD"}),
    "CLUSTERED": frozenset({"NEEDS_VALIDATION", "NEEDS_MORE_DATA", "READY_FOR_REVIEW",
                            "REJECTED", "MERGED_DUPLICATE", "BLOCKED", "ARCHIVED_COLD"}),
    "NEEDS_VALIDATION": frozenset({"NEEDS_MORE_DATA", "READY_FOR_REVIEW",
                                   "REJECTED", "BLOCKED", "ARCHIVED_COLD"}),
    "NEEDS_MORE_DATA": frozenset({"NEEDS_VALIDATION", "READY_FOR_REVIEW",
                                  "REJECTED", "BLOCKED", "ARCHIVED_COLD"}),
    "READY_FOR_REVIEW": frozenset({"APPROVED_RESEARCH_ONLY", "APPROVED_SOURCE",
                                   "APPROVED_WATCH_DIRECTIVE", "STAGED_TICKER_REVIEW",
                                   "NEEDS_MORE_DATA", "REJECTED", "MERGED_DUPLICATE",
                                   "BLOCKED", "ARCHIVED_COLD"}),
    "APPROVED_RESEARCH_ONLY": frozenset({"READY_FOR_REVIEW", "BLOCKED", "ARCHIVED_COLD"}),
    "APPROVED_SOURCE": frozenset({"BLOCKED", "ARCHIVED_COLD"}),
    "APPROVED_WATCH_DIRECTIVE": frozenset({"PROMOTED_TO_WATCH_EVALUATION",
                                           "BLOCKED", "ARCHIVED_COLD"}),
    "STAGED_TICKER_REVIEW": frozenset({"PROMOTED_TO_WATCH_EVALUATION", "REJECTED",
                                       "BLOCKED", "ARCHIVED_COLD"}),
    "PROMOTED_TO_WATCH_EVALUATION": frozenset({"ARCHIVED_COLD"}),
    "REJECTED": frozenset({"ARCHIVED_COLD"}),
    "MERGED_DUPLICATE": frozenset({"ARCHIVED_COLD"}),
    "BLOCKED": frozenset({"ARCHIVED_COLD"}),
    "ARCHIVED_COLD": frozenset({"DISCOVERED"}),  # explicit revive only
}

# Operator decisions accepted by decide_candidate(); each is just a guarded transition.
DECISIONS = frozenset({
    "APPROVED_RESEARCH_ONLY", "APPROVED_SOURCE", "APPROVED_WATCH_DIRECTIVE",
    "STAGED_TICKER_REVIEW", "PROMOTED_TO_WATCH_EVALUATION",
    "REJECTED", "BLOCKED", "ARCHIVED_COLD", "NEEDS_MORE_DATA", "READY_FOR_REVIEW",
})


class DiscoveryInboxError(Exception):
    """Base error for the discovery inbox."""


class IllegalTransitionError(DiscoveryInboxError):
    """Raised on a state transition not present in ALLOWED_TRANSITIONS."""


class CandidateNotFoundError(DiscoveryInboxError):
    """Raised when a candidate id does not exist."""


class DBUnavailableError(DiscoveryInboxError):
    """Raised when db_adapter has no working PostgreSQL connection."""


# ── low-level helpers ────────────────────────────────────────────────────────

def _exec(sql: str, params=None, fetch: str | None = None):
    from db_adapter import _execute
    result = _execute(sql, params, fetch=fetch)
    if result is None and fetch != "one":
        # _execute returns None on connection failure/SQL error ([] for empty fetch=all).
        raise DBUnavailableError("db_adapter._execute failed (no DB or SQL error — see log)")
    return result


def _row_dict(row) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _audit(candidate_id: int | None, action: str, actor: str,
           before: dict | None, after: dict | None, notes: str | None = None) -> None:
    _exec(
        """INSERT INTO hermes_discovery_audit (candidate_id, action, actor, before_json, after_json, notes)
           VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)""",
        (candidate_id, action, actor,
         json.dumps(before, default=str) if before is not None else None,
         json.dumps(after, default=str) if after is not None else None,
         notes))


def _merge_evidence(existing: Any, new: list | None) -> list:
    """Append-merge evidence lists, dropping exact-duplicate entries."""
    merged: list = list(existing) if isinstance(existing, list) else []
    seen = {json.dumps(e, sort_keys=True, default=str) for e in merged}
    for item in (new or []):
        key = json.dumps(item, sort_keys=True, default=str)
        if key not in seen:
            merged.append(item)
            seen.add(key)
    return merged


def _persist_score(candidate: dict[str, Any], signals: dict | None = None) -> dict[str, Any]:
    """Compute + persist discovery_score/score_json; returns the updated row."""
    result = scoring.discovery_score(candidate, signals)
    row = _exec(
        """UPDATE hermes_discovery_candidates
           SET discovery_score = %s, score_json = %s::jsonb, updated_at = NOW()
           WHERE id = %s RETURNING *""",
        (result["total"], json.dumps({"total": result["total"], "parts": result["parts"]},
                                     default=str),
         candidate["id"]), fetch="one")
    if row is None:
        raise DBUnavailableError("score persist failed")
    return dict(row)


def _enrich_domain_meta(meta: dict, candidate_view: dict[str, Any],
                        safe_action_level: str) -> tuple[dict, str, str]:
    """Universal Research Discovery Layer enrichment (see module docstring).

    Classifies the candidate into a research domain, stamps
    research_domain / domain_risk_level / advisory_label / subject_json into
    meta, and — for professional-review domains (taxes/retirement/legal/
    medical) — adds required_review_label and FORCES
    safe_action_level=OPERATOR_REVIEW_REQUIRED. Fails closed on a broken or
    unknown domain registry (domains.DomainConfigError propagates).
    """
    domain = domains.classify_domain(candidate_view)
    policy = domains.domain_policy(domain)
    meta["research_domain"] = domain
    meta["domain_risk_level"] = policy["risk_level"]
    meta["advisory_label"] = policy["advisory_label"]
    if policy.get("requires_professional_review_label"):
        meta["required_review_label"] = policy["professional_review_label"]
        safe_action_level = "OPERATOR_REVIEW_REQUIRED"
    view = dict(candidate_view)
    view["meta"] = meta
    view["safe_action_level"] = safe_action_level
    meta["subject_json"] = subjects.build_subject(view, domain)
    return meta, safe_action_level, domain


# ── clustering (TREND_CANDIDATE near-duplicates) ─────────────────────────────

def _assign_trend_cluster(row: dict[str, Any], actor: str) -> dict[str, Any]:
    """Near-duplicate clustering for a freshly inserted trend candidate.

    Token-Jaccard >= dedupe.NEAR_DUP_JACCARD against existing trend labels →
    joins that candidate's cluster (creating the cluster row if needed) and
    moves to CLUSTERED. Operator rows are never merged in either direction.
    """
    if row.get("is_operator"):
        return row
    peers = _exec(
        """SELECT id, label, normalized_key, is_operator, duplicate_cluster_id
           FROM hermes_discovery_candidates
           WHERE candidate_type = 'TREND_CANDIDATE' AND id <> %s
             AND status NOT IN ('REJECTED', 'BLOCKED', 'ARCHIVED_COLD')""",
        (row["id"],), fetch="all") or []
    match = dedupe.find_near_duplicate(row["label"], [dict(p) for p in peers],
                                       is_operator=bool(row.get("is_operator")))
    if not match:
        return row

    cluster_id = match.get("duplicate_cluster_id")
    if not cluster_id:
        cluster = _exec(
            """INSERT INTO hermes_discovery_clusters
                   (candidate_type, cluster_key, label, anchor_candidate_id,
                    member_count, centroid_tokens)
               VALUES ('TREND_CANDIDATE', %s, %s, %s, 1, %s)
               ON CONFLICT (cluster_key) DO UPDATE SET updated_at = NOW()
               RETURNING id""",
            (match["normalized_key"], match["label"], match["id"],
             sorted(dedupe.tokenize(str(match["label"])))), fetch="one")
        if cluster is None:
            raise DBUnavailableError("cluster insert failed")
        cluster_id = cluster["id"]
        _exec("""UPDATE hermes_discovery_candidates
                 SET duplicate_cluster_id = %s, updated_at = NOW() WHERE id = %s""",
              (cluster_id, match["id"]))

    before = dict(row)
    updated = _exec(
        """UPDATE hermes_discovery_candidates
           SET duplicate_cluster_id = %s, status = 'CLUSTERED', updated_at = NOW()
           WHERE id = %s RETURNING *""",
        (cluster_id, row["id"]), fetch="one")
    if updated is None:
        raise DBUnavailableError("cluster assign failed")
    _exec("""UPDATE hermes_discovery_clusters
             SET member_count = member_count + 1, updated_at = NOW() WHERE id = %s""",
          (cluster_id,))
    updated = dict(updated)
    _audit(row["id"], "CLUSTER_ASSIGN", actor, before, updated,
           f"near-dup of candidate {match['id']} (jaccard {match.get('_similarity')})")
    return updated


# ── public API ───────────────────────────────────────────────────────────────

def upsert_candidate(candidate_type: str, label: str, *,
                     summary: str | None = None,
                     source_domain: str | None = None,
                     source_url: str | None = None,
                     evidence: list | None = None,
                     seed_symbols: list[str] | None = None,
                     extracted_symbols: list[str] | None = None,
                     is_operator: bool = False,
                     actor: str = "system",
                     meta: dict | None = None,
                     risk_flags: list[str] | None = None,
                     safe_action_level: str = "OPERATOR_REVIEW_REQUIRED",
                     ttl_days: int = 30,
                     normalized_key: str | None = None,
                     signals: dict | None = None) -> dict[str, Any]:
    """Idempotent intake. Returns the persisted candidate row (dict).

    Same (candidate_type, normalized_key) → bumps seen_count / last_seen_at and
    merges evidence instead of inserting. New TICKER_CANDIDATEs are validated
    against symbol_profiles (valid → READY_FOR_REVIEW, else NEEDS_VALIDATION +
    risk flag). New TREND_CANDIDATEs get near-duplicate clustering (operator
    rows exempt). Score parts are always persisted to score_json.

    Every candidate (new or bump) is enriched with research_domain,
    domain_risk_level, subject_json, advisory_label (and, for taxes/
    retirement/legal/medical domains, required_review_label plus a forced
    safe_action_level=OPERATOR_REVIEW_REQUIRED) — see the module docstring
    for the meta_json key contract.
    """
    candidate_type = (candidate_type or "").strip().upper()
    if candidate_type not in CANDIDATE_TYPES:
        raise DiscoveryInboxError(f"unknown candidate_type: {candidate_type!r}")
    if safe_action_level not in SAFE_ACTION_LEVELS:
        raise DiscoveryInboxError(f"unknown safe_action_level: {safe_action_level!r}")
    label = (label or "").strip()
    if not label:
        raise DiscoveryInboxError("label is required")
    key = normalized_key or dedupe.normalize_key(label)
    if not key:
        raise DiscoveryInboxError(f"label normalizes to empty key: {label!r}")

    evidence = evidence or []
    risk_flags = list(risk_flags or [])
    meta = dict(meta or {})

    existing = _exec(
        """SELECT * FROM hermes_discovery_candidates
           WHERE candidate_type = %s AND normalized_key = %s""",
        (candidate_type, key), fetch="one")

    if existing:
        before = dict(existing)
        merged_evidence = _merge_evidence(existing.get("evidence_json"), evidence)
        # Re-enrich domain/subject on every re-sighting: existing meta wins
        # (research_domain is sticky via classify_domain's pin), new meta keys
        # fill gaps, subject_json refreshes recurrence/last_seen/evidence.
        bump_meta = dict(existing.get("meta_json") or {})
        for k, v in meta.items():
            bump_meta.setdefault(k, v)
        view = dict(before)
        view.update({
            "summary": summary or before.get("summary"),
            "source_url": source_url or before.get("source_url"),
            "evidence_json": merged_evidence,
            "seen_count": int(before.get("seen_count") or 1) + 1,
            "meta": bump_meta,
        })
        bump_meta, bump_level, _domain = _enrich_domain_meta(
            bump_meta, view, str(before.get("safe_action_level")
                                 or "OPERATOR_REVIEW_REQUIRED"))
        force_level = bump_level if bump_level != before.get("safe_action_level") else None
        row = _exec(
            """UPDATE hermes_discovery_candidates
               SET seen_count = seen_count + 1,
                   last_seen_at = NOW(),
                   updated_at = NOW(),
                   evidence_json = %s::jsonb,
                   meta_json = %s::jsonb,
                   safe_action_level = COALESCE(%s, safe_action_level),
                   summary = COALESCE(%s, summary),
                   source_url = COALESCE(%s, source_url)
               WHERE id = %s RETURNING *""",
            (json.dumps(merged_evidence, default=str),
             json.dumps(bump_meta, default=str), force_level, summary, source_url,
             existing["id"]), fetch="one")
        if row is None:
            raise DBUnavailableError("upsert bump failed")
        row = _persist_score(dict(row), signals)
        _audit(row["id"], "UPSERT_BUMP", actor, before, row,
               f"seen_count {before.get('seen_count')} -> {row.get('seen_count')}")
        return row

    # ── new row ──
    status = "DISCOVERED"
    if candidate_type == "TICKER_CANDIDATE":
        verdict = validate_ticker(label)
        meta["ticker_validation"] = verdict
        if verdict["verdict"] == VERDICT_VALID:
            status = "READY_FOR_REVIEW"
        else:
            status = "NEEDS_VALIDATION"
            if "ticker_unvalidated" not in risk_flags:
                risk_flags.append("ticker_unvalidated")

    # Universal Research Discovery Layer: domain + subject enrichment
    # (meta_json keys documented in the module docstring; fail-closed).
    meta, safe_action_level, _domain = _enrich_domain_meta(meta, {
        "candidate_type": candidate_type,
        "label": label,
        "summary": summary,
        "normalized_key": key,
        "source_domain": source_domain,
        "source_url": source_url,
        "evidence": evidence,
        "seed_symbols": seed_symbols or [],
        "extracted_symbols": extracted_symbols or [],
        "meta": meta,
        "is_operator": bool(is_operator),
        "seen_count": 1,
    }, safe_action_level)

    row = _exec(
        """INSERT INTO hermes_discovery_candidates
               (candidate_type, normalized_key, label, summary, status,
                safe_action_level, source_domain, source_url, seed_symbols,
                extracted_symbols, evidence_json, risk_flags, meta_json,
                is_operator, ttl_days)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)
           ON CONFLICT (candidate_type, normalized_key) DO UPDATE
               SET seen_count = hermes_discovery_candidates.seen_count + 1,
                   last_seen_at = NOW(), updated_at = NOW()
           RETURNING *""",
        (candidate_type, key, label, summary, status, safe_action_level,
         (source_domain or "").lower().strip() or None, source_url,
         [s.upper() for s in (seed_symbols or [])],
         [s.upper() for s in (extracted_symbols or [])],
         json.dumps(evidence, default=str), json.dumps(risk_flags),
         json.dumps(meta, default=str), bool(is_operator), int(ttl_days)),
        fetch="one")
    if row is None:
        raise DBUnavailableError("candidate insert failed")
    row = dict(row)
    _audit(row["id"], "CREATE", actor, None, row, f"status={row['status']}")

    if candidate_type == "TREND_CANDIDATE":
        row = _assign_trend_cluster(row, actor)

    row = _persist_score(row, signals)
    return row


def transition_candidate(candidate_id: int, new_status: str, *,
                         actor: str = "system",
                         notes: str | None = None) -> dict[str, Any]:
    """Move a candidate through the state machine; illegal moves raise."""
    new_status = (new_status or "").strip().upper()
    if new_status not in STATUSES:
        raise IllegalTransitionError(f"unknown status: {new_status!r}")
    current = _exec("SELECT * FROM hermes_discovery_candidates WHERE id = %s",
                    (candidate_id,), fetch="one")
    if not current:
        raise CandidateNotFoundError(f"candidate {candidate_id} not found")
    before = dict(current)
    cur_status = before["status"]
    if new_status == cur_status:
        return before  # no-op, no audit spam
    if new_status not in ALLOWED_TRANSITIONS.get(cur_status, frozenset()):
        raise IllegalTransitionError(
            f"illegal transition {cur_status} -> {new_status} for candidate {candidate_id}")
    row = _exec(
        """UPDATE hermes_discovery_candidates
           SET status = %s, updated_at = NOW() WHERE id = %s RETURNING *""",
        (new_status, candidate_id), fetch="one")
    if row is None:
        raise DBUnavailableError("transition update failed")
    row = dict(row)
    _audit(candidate_id, "TRANSITION", actor, before, row,
           notes or f"{cur_status} -> {new_status}")
    return row


def decide_candidate(candidate_id: int, decision: str, *,
                     actor: str = "operator",
                     notes: str | None = None) -> dict[str, Any]:
    """Operator/agent decision — a guarded transition that also stamps
    decided_at/decided_by/decision_notes and audits as DECIDE."""
    decision = (decision or "").strip().upper()
    if decision not in DECISIONS:
        raise DiscoveryInboxError(f"unknown decision: {decision!r} (valid: {sorted(DECISIONS)})")
    current = _exec("SELECT * FROM hermes_discovery_candidates WHERE id = %s",
                    (candidate_id,), fetch="one")
    if not current:
        raise CandidateNotFoundError(f"candidate {candidate_id} not found")
    before = dict(current)
    if decision not in ALLOWED_TRANSITIONS.get(before["status"], frozenset()):
        raise IllegalTransitionError(
            f"illegal decision {before['status']} -> {decision} for candidate {candidate_id}")
    row = _exec(
        """UPDATE hermes_discovery_candidates
           SET status = %s, decided_at = NOW(), decided_by = %s,
               decision_notes = %s, updated_at = NOW()
           WHERE id = %s RETURNING *""",
        (decision, actor, notes, candidate_id), fetch="one")
    if row is None:
        raise DBUnavailableError("decide update failed")
    row = dict(row)
    _audit(candidate_id, "DECIDE", actor, before, row, notes or decision)
    return row


def get_candidate(candidate_id: int, *, with_audit: bool = False) -> dict[str, Any] | None:
    """Fetch one candidate (optionally with its audit trail, newest first)."""
    row = _exec("SELECT * FROM hermes_discovery_candidates WHERE id = %s",
                (candidate_id,), fetch="one")
    if not row:
        return None
    out = dict(row)
    if with_audit:
        audit = _exec(
            """SELECT id, action, actor, before_json, after_json, notes, created_at
               FROM hermes_discovery_audit WHERE candidate_id = %s
               ORDER BY id DESC LIMIT 100""",
            (candidate_id,), fetch="all") or []
        out["audit"] = [dict(a) for a in audit]
    return out


def list_candidates(*, candidate_type: str | None = None,
                    status: str | None = None,
                    source_domain: str | None = None,
                    limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    """List inbox candidates, newest-seen first. Used by the CLI and api_v2."""
    clauses, params = [], []
    if candidate_type:
        clauses.append("candidate_type = %s")
        params.append(candidate_type.upper())
    if status:
        clauses.append("status = %s")
        params.append(status.upper())
    if source_domain:
        clauses.append("source_domain = %s")
        params.append(source_domain.lower())
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.extend([int(limit), int(offset)])
    rows = _exec(
        f"""SELECT * FROM hermes_discovery_candidates {where}
            ORDER BY last_seen_at DESC, id DESC LIMIT %s OFFSET %s""",
        tuple(params), fetch="all") or []
    return [dict(r) for r in rows]


def inbox_stats() -> dict[str, Any]:
    """Aggregate counts for the CLI --stats and the scorecard."""
    by_status = _exec(
        """SELECT status, count(*) AS n FROM hermes_discovery_candidates
           GROUP BY status ORDER BY n DESC""", fetch="all") or []
    by_type = _exec(
        """SELECT candidate_type, count(*) AS n FROM hermes_discovery_candidates
           GROUP BY candidate_type ORDER BY n DESC""", fetch="all") or []
    totals = _exec(
        """SELECT count(*) AS candidates,
                  coalesce(avg(discovery_score), 0) AS avg_score,
                  count(*) FILTER (WHERE duplicate_cluster_id IS NOT NULL) AS clustered,
                  count(*) FILTER (WHERE is_operator) AS operator_created
           FROM hermes_discovery_candidates""", fetch="one") or {}
    audit_n = _exec("SELECT count(*) AS n FROM hermes_discovery_audit", fetch="one") or {}
    feedback_n = _exec("SELECT count(*) AS n FROM hermes_discovery_feedback", fetch="one") or {}
    return {
        "totals": {k: (float(v) if k == "avg_score" else int(v))
                   for k, v in dict(totals).items()},
        "by_status": {r["status"]: int(r["n"]) for r in by_status},
        "by_type": {r["candidate_type"]: int(r["n"]) for r in by_type},
        "audit_rows": int(dict(audit_n).get("n", 0)),
        "feedback_rows": int(dict(feedback_n).get("n", 0)),
    }
