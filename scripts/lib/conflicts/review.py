"""Completion transaction for CIO-owner stance reviews, never an acquisition result.

Existing C3 publication/readback validation calls this only after proving the CIO
authored a new canonical stance. A durable decision alone never clears a finding.
"""
from __future__ import annotations

from .ledger import DECISION_SCHEMA
from .adapters import timestamp


def record_review_queued(ledger, key, *, request_id, queue_readback, at, apply=False):
    """Owner calls after enqueue; verify the persisted GUID-bound request first."""
    record = ledger.records().get(key)
    if not record:
        raise KeyError(key)
    saved = queue_readback(request_id) or {}
    if (saved.get("request_id") != request_id or saved.get("identity_status") != "CONFIRMED" or
            saved.get("security_guid") != record["subject"]["id"] or
            str(saved.get("symbol") or "").upper() != str(record["subject"]["label"]).upper()):
        raise ValueError("persisted review request identity/lineage unproven")
    return ledger.transition(key, "review_queued", at=at, expected_revision=record["revision"],
                             review_request_id=request_id, apply=apply)


def complete_review(ledger, key, *, request_id, canonical, reason, evidence_refs, producer_update,
                    producer_readback, at, expires_at, apply=False):
    record = ledger.records().get(key)
    if not record:
        raise KeyError(key)
    if record["subject"]["kind"] != "security" or record.get("kind") != "CONFLICT" or record.get("rule") not in {"U2", "U3", "U7", "R11"}:
        raise ValueError("review completion is limited to CIO stance conflicts")
    if not request_id or not reason or not evidence_refs:
        raise ValueError("linked request, reason and evidence are required")
    if canonical.get("security_guid") != record["subject"]["id"] or not canonical.get("stance") or not canonical.get("as_of"):
        raise ValueError("canonical publication identity/stance/time unproven")
    canonical_at = timestamp(canonical["as_of"])
    if canonical_at is None or canonical_at > at:
        raise ValueError("canonical publication timestamp unproven")
    patch = {"verdict": canonical["stance"], "completed_at": canonical["as_of"], "request_id": request_id,
             "conflict_key": key, "reason": reason, "evidence_refs": list(evidence_refs)}
    decision = {"schema": DECISION_SCHEMA, "actor_kind": "cio", "actor": "cio", "chosen_side": canonical["stance"],
                "reason": reason, "evidence_refs": list(evidence_refs), "request_id": request_id, "at": at.isoformat(),
                "expires_at": expires_at.isoformat(), "clears_when": record.get("clears_when"),
                "key": key, "subject": record["subject"]}
    # Validate transition without effects before any producer mutation.
    ledger.transition(key, "review_completed", at=at, decision=decision, apply=False)
    if not apply:
        return {"decision": decision, "producer_patch": patch, "applied": False, "resolution_proven": False}
    prior = record.get("decision") or {}
    if prior.get("request_id") != request_id:
        ledger.transition(key, "decided", at=at, decision=decision, expected_revision=record["revision"], apply=True)
    if producer_update(patch) is not True:
        return {"applied": False, "resolution_proven": False, "reason": "superseded_input_update_failed"}
    saved = producer_readback() or {}
    if any(saved.get(k) != v for k, v in patch.items()):
        return {"applied": False, "resolution_proven": False, "reason": "superseded_input_readback_failed"}
    # The owner records the completion; only the next engine evaluation clears.
    ledger.transition(key, "review_completed", at=at, decision=decision, apply=True)
    return {"applied": True, "resolution_proven": True, "decision": decision, "producer_patch": patch,
            "cleared": False, "next": "re-evaluate canonical and updated producer input"}


REVIEWABLE_RULES = {"U2", "U3", "U7", "R11"}
DECISION_TTL_DAYS = 7


def complete_from_watch_review(root, *, symbol, artifact_path, now, resolve_identity=None, memory_writer=None,
                               ttl_days=DECISION_TTL_DAYS):
    """Owner hook: a COMPLETE CIO watch-review artifact closes the CIO stance conflicts open on that security.

    The CIO review worker (scripts/run_watch_review_workers.py, role cio) is the producer of the compared input
    "watchlist CIO review" (card.cio_review). After it writes ``<SYM>_cio.json`` this records the CIO decision
    (ConflictDecision@v1, actor cio) on every active CONFLICT of rule U2/U3/U7/R11 for the GUID-confirmed
    security, writes the conflict linkage into that same artifact and reads it back (exact patch). It never
    clears a flag: the next conflict-resolver run re-evaluates with the decision and the updated input.

    Identity is GUID-only: the symbol must resolve CONFIRMED to the record's security GUID. Returns one result
    per conflict; never raises into the caller.
    """
    import json
    import os
    from datetime import timedelta
    from pathlib import Path

    from .ledger import ACTIVE, ConflictLedger

    results = []
    try:
        artifact_path = Path(artifact_path)
        body = json.loads(artifact_path.read_text(encoding="utf-8"))
        if body.get("status") != "COMPLETE" or not body.get("verdict") or not body.get("completed_at"):
            return [{"applied": False, "reason": "review_not_complete"}]
        if resolve_identity is None:
            from scripts.lib.identity_carriage import resolve_security_identity as resolve_identity
        ident = resolve_identity(symbol) or {}
        guid = ident.get("security_guid")
        if ident.get("identity_status") != "CONFIRMED" or not guid:
            return [{"applied": False, "reason": "identity_unconfirmed"}]
        if memory_writer is None:
            from .cio import memory_writer as _mw
            memory_writer = _mw(root)
        ledger = ConflictLedger(root, memory_writer=memory_writer)
        if not ledger.path.exists():
            return [{"applied": False, "reason": "ledger_not_produced"}]
        keys = [k for k, r in ledger.records().items() if r["subject"]["kind"] == "security"
                and r["subject"]["id"] == guid and r["state"] in ACTIVE and r.get("kind") == "CONFLICT"
                and r.get("rule") in REVIEWABLE_RULES]
        request_id = body.get("execution_authorization_id") or body.get("input_snapshot_id")
        reason = str(body.get("summary") or f"CIO watch review verdict {body['verdict']}")[:4000]
        evidence = [f"watch_review_artifact:{artifact_path.name}"]
        if body.get("input_hash"):
            evidence.append(f"input_hash:{body['input_hash']}")
        canonical = {"security_guid": guid, "stance": body["verdict"], "as_of": body["completed_at"]}

        def update(patch):
            current = json.loads(artifact_path.read_text(encoding="utf-8"))
            links = dict(current.get("conflict_resolutions") or {})
            links[patch["conflict_key"]] = {k: v for k, v in patch.items() if k != "conflict_key"}
            current.update(patch)
            current["conflict_resolutions"] = links
            tmp = artifact_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(current, indent=2, default=str) + "\n", encoding="utf-8")
            os.replace(tmp, artifact_path)
            return True

        def readback():
            return json.loads(artifact_path.read_text(encoding="utf-8"))

        for key in keys:
            try:
                out = complete_review(ledger, key, request_id=request_id, canonical=canonical, reason=reason,
                                      evidence_refs=evidence, producer_update=update, producer_readback=readback,
                                      at=now, expires_at=now + timedelta(days=ttl_days), apply=True)
                results.append({"key": key, **{k: out.get(k) for k in ("applied", "resolution_proven", "reason")}})
            except (KeyError, ValueError, RuntimeError) as exc:
                results.append({"key": key, "applied": False, "reason": f"{type(exc).__name__}: {exc}"[:200]})
    except Exception as exc:  # noqa: BLE001 -- an owner hook never breaks the review worker
        results.append({"applied": False, "reason": f"{type(exc).__name__}: {exc}"[:200]})
    return results
