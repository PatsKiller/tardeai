"""Acquisition-owner link from an exact published thesis to existing CIO memory.

No judgment is minted. Missing/facts-only prospects stay explicitly pending.
The only write path is the existing InstrumentRecord facade, including its PG
authority and concurrency checks. Readers never invoke this module.
"""

from __future__ import annotations

from copy import deepcopy
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


def link_publication(root, request, result, *, store=None, backend=None, registry=None, env=None):
    """Called only after the existing acquisition owner published and read back."""
    from scripts.lib import cio_instrument_record as ir
    from scripts.lib.identity_carriage import resolve_security_identity

    root = Path(root)
    pending = {"ok": False, "reason": "canonical_link_pending"}
    if not request or result.get("status") not in {"PUBLISHED", "SYNTHESIZED_NO_MATERIAL_CHANGE"}:
        return {**pending, "reason": "no_linkable_publication"}
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
    pending["publication"] = publication
    store = store or ir._store_for_root(root)
    records = [r for r in store.all() if r.get("security_guid") == guid]
    if len(records) != 1 or not ir.is_prospect_record(records[0]):
        return {**pending, "reason": "valid_cio_prospect_needed_for_review_link"}
    record = records[0]
    lifecycle = {
        "status": "ANSWERED_PENDING_CIO",
        "request_id": request["request_id"],
        "requested_at": request.get("requested_at"),
        "answered_at": thesis["published_ts"],
        "research_id": version,
        "evidence_refs": [version],
        "reason": str(thesis.get("summary") or "Research published; CIO decision pending")[:1200],
    }
    research = {**deepcopy(record.get("research") or {}), "review_lifecycle": lifecycle}
    pg_requested = str((os.environ if env is None else env).get(ir.PROSPECT_DUAL_WRITE_ENV) or "") == "1"
    if record.get("research", {}).get("review_lifecycle") == lifecycle:
        if pg_requested:
            return {**pending, "reason": "canonical_pg_readback_pending"}
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
        updated, _ = ir.apply_prospect(record, prospect={"research": research})
        receipt = store.upsert_prospect(updated, backend=backend, registry=registry, env=env)
        pg = receipt.get("pg") or {}
        if pg.get("live") and pg.get("ok") is not True:
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
