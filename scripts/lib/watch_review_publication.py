"""Acquisition-owner link from an exact published thesis to existing CIO memory.

No judgment is minted. Missing/facts-only prospects stay explicitly pending.
The only write path is the existing InstrumentRecord facade, including its PG
authority and concurrency checks. Readers never invoke this module.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path


def pending_request(root, symbol):
    from scripts.lib import symbol_thesis_priority as queue

    state = queue.review_states([symbol], root=root).get(symbol) or {}
    if not state.get("open") or not state.get("request_id"):
        return None
    rows = queue._rows(Path(root).joinpath(*queue.RELPATH))
    return next((r for r in reversed(rows) if r.get("request_id") == state["request_id"]), None)


def request_blocker(root, request, *, identity_resolver=None):
    """Identity quality gate before the owner can reach paid acquisition/synthesis."""
    if not request:
        return None
    if request.get("identity_status") != "CONFIRMED" or not request.get("security_guid"):
        return "REQUEST_IDENTITY_UNCONFIRMED"
    if identity_resolver is None:
        from scripts.lib.identity_carriage import resolve_security_identity

        identity_resolver = resolve_security_identity
    identity = identity_resolver(request["symbol"], root=root)
    if identity.get("identity_status") != "CONFIRMED" or identity.get("security_guid") != request["security_guid"]:
        return "REQUEST_IDENTITY_CHANGED"
    return None


def published_for_request(root, request):
    """Sink-only retry: never buy another synthesis to repair a memory receipt."""
    if not request:
        return None
    from scripts.lib import symbol_thesis_priority as queue

    rows = queue._rows(Path(root).joinpath(*queue.LEDGER_RELPATH))
    return next(
        (r for r in reversed(rows) if r.get("request_id") == request["request_id"] and r.get("status") in queue.DONE),
        None,
    )


def _pg_review(guid, status):
    """Read the acknowledged record through the existing CC data broker."""
    from scripts.lib.data_broker.cio_prospect import get_prospect
    from scripts.lib.data_broker.watch_prospects import _db_query

    return get_prospect(guid, db_query=_db_query(), status=status)


def link_publication(root, request, result, *, store=None, backend=None, registry=None, env=None, pg_reader=None):
    """Called only after the existing acquisition owner published and read back."""
    from scripts.lib import cio_instrument_record as ir
    from scripts.lib.identity_carriage import resolve_security_identity

    root = Path(root)
    pending = {"ok": False, "reason": "canonical_link_pending"}
    if not request or result.get("status") not in {"PUBLISHED", "SYNTHESIZED_NO_MATERIAL_CHANGE"}:
        return {**pending, "reason": "no_linkable_publication"}
    if result.get("status") == "SYNTHESIZED_NO_MATERIAL_CHANGE" and (
        result.get("review", {}).get("ok") is not True
        or result.get("review", {}).get("classification") != "NO_MATERIAL_CHANGE"
        or not result.get("review", {}).get("reviewed_at")
    ):
        return {**pending, "reason": "unchanged_review_not_proven"}
    guid = request.get("security_guid")
    symbol = request.get("symbol")
    identity = resolve_security_identity(symbol, root=root)
    if (
        not guid
        or request.get("identity_status") != "CONFIRMED"
        or identity.get("identity_status") != "CONFIRMED"
        or identity.get("security_guid") != guid
    ):
        return {**pending, "reason": "request_identity_unconfirmed_or_changed"}
    version = (result.get("review") or {}).get("new_version")
    try:
        projection = json.loads((root / "data/cio/cio_theses_projection.json").read_text())
        matches = [
            r
            for versions in projection.get("versions", {}).values()
            for r in versions.values()
            if r.get("thesis_version") == version and symbol in r.get("linked_symbols", [])
        ]
    except (OSError, ValueError, AttributeError):
        return {**pending, "reason": "published_thesis_readback_unavailable"}
    if not version or len(matches) != 1 or not matches[0].get("published_ts"):
        return {**pending, "reason": "exact_published_thesis_not_found"}
    thesis = matches[0]
    publication = {"store": "cio_theses", "thesis_version": version, "published_at": thesis["published_ts"]}
    if result.get("review", {}).get("reviewed_at"):
        publication["reviewed_at"] = result["review"]["reviewed_at"]
    pending["publication"] = publication
    store = store or ir._store_for_root(root)
    records = [r for r in store.all() if r.get("security_guid") == guid]
    if len(records) != 1 or not ir.is_prospect_record(records[0]):
        return {**pending, "reason": "valid_cio_prospect_needed_for_review_link"}
    record = records[0]
    current = (record.get("research") or {}).get("review_lifecycle") or {}
    if current.get("request_id") == request["request_id"] and str(current.get("status", "")).upper() in {
        "ANSWERED",
        "CONFLICT_RESOLVED",
    }:
        # A later CIO judgment owns its final result. A late research delivery
        # cannot downgrade it, even when it can still repair a publication sink.
        return {**pending, "reason": "canonical_review_finalized_owner_readback_required"}
    if current.get("request_id") and current["request_id"] != request["request_id"]:
        try:
            prior_at = datetime.fromisoformat(str(current.get("requested_at")).replace("Z", "+00:00"))
            incoming_at = datetime.fromisoformat(str(request.get("requested_at")).replace("Z", "+00:00"))
            if not prior_at.tzinfo or not incoming_at.tzinfo or incoming_at <= prior_at:
                return {**pending, "reason": "newer_canonical_review_preserved"}
        except (TypeError, ValueError):
            return {**pending, "reason": "canonical_review_order_unproven"}
    lifecycle = {
        "status": "ANSWERED_PENDING_CIO",
        "request_id": request["request_id"],
        "requested_at": request.get("requested_at"),
        "answered_at": thesis["published_ts"],
        "reviewed_at": result.get("review", {}).get("reviewed_at") or thesis["published_ts"],
        "research_id": version,
        "evidence_refs": [version],
        "reason": str(thesis.get("summary") or "Research published; CIO decision pending")[:1200],
    }
    research = {**deepcopy(record.get("research") or {}), "review_lifecycle": lifecycle}
    pg_requested = str((os.environ if env is None else env).get(ir.PROSPECT_DUAL_WRITE_ENV) or "").strip() == "1"
    same_lifecycle = record.get("research", {}).get("review_lifecycle") == lifecycle
    if same_lifecycle and not pg_requested:
        return {
            "ok": True,
            "state": "ANSWERED_PENDING_CIO",
            "publication": publication,
            "request_id": request["request_id"],
            "security_guid": guid,
            "answer_summary": lifecycle["reason"],
        }
    try:
        if pg_requested and backend is None:
            from scripts.session13_db import get_conn

            backend = ir.ProspectPgBackend(get_conn)
        if pg_requested:
            status = ir.prospect_store_status(
                registry=registry, env=env, table_probe=backend.table_present if backend else None
            )
            if not status["live"]:
                return {**pending, "reason": "canonical_pg_preflight_failed", "pg_reasons": status["reasons"]}
        # A sink-only retry uses the same revision through the single facade;
        # no synthesis, stance change or new research revision is manufactured.
        updated = record if same_lifecycle else ir.apply_prospect(record, prospect={"research": research})[0]
        receipt = store.upsert_prospect(updated, backend=backend, registry=registry, env=env)
        pg = receipt.get("pg") or {}
        if pg_requested:
            if not pg.get("live") or pg.get("ok") is not True:
                return {**pending, "reason": "canonical_pg_readback_pending"}
            projection = (pg_reader or _pg_review)(guid, status)
            pg_record = projection.get("prospect") or {}
            if (
                projection.get("ok") is not True
                or projection.get("source", {}).get("kind") != "store"
                or pg_record.get("security_guid") != guid
                or pg_record.get("research", {}).get("review_lifecycle") != lifecycle
            ):
                return {**pending, "reason": "canonical_pg_readback_pending"}
        readback = ir.InstrumentRecordStore(store.path).load(record["subject_key"])
        if (readback or {}).get("research", {}).get("review_lifecycle") != lifecycle:
            return {**pending, "reason": "canonical_review_readback_pending"}
    except Exception as exc:  # caller preserves publication and records a named gap
        return {**pending, "reason": "canonical_review_write_refused", "error": type(exc).__name__}
    return {
        "ok": True,
        "state": "ANSWERED_PENDING_CIO",
        "publication": publication,
        "request_id": request["request_id"],
        "security_guid": guid,
        "answer_summary": lifecycle["reason"],
    }
