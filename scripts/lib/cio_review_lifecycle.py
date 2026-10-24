"""C3 review lifecycle on the existing CIO InstrumentRecord and shared spine.

No queue/store of its own, no provider, no sender, no stance mutation. Producer
hooks call observe only on their existing apply path. Readers never repair stores.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

SCHEMA = "CIOReviewLifecycle@v1"
PUBLIC = ("status", "request_id", "created_at", "requested_at", "researching_at", "started_at", "answered_at",
          "completed_at", "conflict_resolved_at", "updated_at", "research_id", "old_stance", "new_stance",
          "reason", "evidence_refs", "conflict_id")
CLOCKS = {"REQUESTED": "created_at", "RESEARCHING": "researching_at", "ANSWERED_PENDING_CIO": "answered_at",
          "CONFLICT_RESOLVED": "conflict_resolved_at", "FAILED": "completed_at", "BLOCKED": "updated_at"}
TERMINAL = {"CONFLICT_RESOLVED"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ts(value: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else None
    except (ValueError, TypeError):
        return None


def request_id(symbol: str, source: str, at: str, *, legacy=False) -> str:
    raw = json.dumps([symbol.upper(), source, at], separators=(",", ":"))
    return ("legacy-review-" if legacy else "review-") + hashlib.sha256(raw.encode()).hexdigest()[:24]


def identity(symbol: str, root=None) -> dict:
    from scripts.lib.identity_carriage import resolve_security_identity
    try:
        out = resolve_security_identity(symbol, root=root)
        return out if out.get("identity_status") == "CONFIRMED" else {}
    except Exception:
        return {}


def _store(root=None):
    from scripts.lib.cio_instrument_record import _store_for_root
    return _store_for_root(root)


def _matches(records, guid):
    return [r for r in records if guid and str(r.get("security_guid") or r.get("subject_guid")) == str(guid)]


def read(symbol: str, *, root=None, security_guid=None, store=None, records=None) -> dict:
    """Canonical saved review summary only; no queue inference becomes CIO truth."""
    ident = identity(symbol, root)
    guid = security_guid or ident.get("security_guid")
    matches = _matches(records if records is not None else (store or _store(root)).all(), guid)
    if len(matches) != 1:
        return {"status": "MISSING", "reason": "identity_unresolved" if not guid else (
            "cio_record_missing" if not matches else "multiple_cio_records_for_guid"), "security_guid": guid}
    rec = matches[0]
    from scripts.lib.cio_instrument_record import is_prospect_record
    if not is_prospect_record(rec):
        return {"status": "MISSING", "reason": "legacy_record_needs_cio_promotion", "security_guid": guid}
    summary = (rec.get("research") or {}).get("review_lifecycle")
    return {**{k: deepcopy(summary[k]) for k in PUBLIC if k in summary}, "security_guid": guid} if isinstance(summary, dict) else {
        "status": "MISSING", "reason": "review_not_on_cio_record", "security_guid": guid}


def research_for_symbols(symbols, *, root=None, at=None) -> dict:
    """The real quick-Ask model adapter. Whitelist record facts, never other research."""
    store = _store(root)
    records = store.all()
    out = {}
    for sym in list(dict.fromkeys(symbols))[:12]:
        ident = identity(sym, root)
        guid = ident.get("security_guid")
        matches = _matches(records, guid)
        company = {}
        if len(matches) == 1:
            f = (matches[0].get("research") or {}).get("company_facts") or {}
            if f.get("schema") == "CIOCompanyFacts@v1" and f.get("security_guid") == guid:
                company = {k: deepcopy(f[k]) for k in ("schema", "security_guid", "company", "description", "sector",
                                                      "industry", "catalyst", "missing_reason") if k in f}
        cat = company.get("catalyst") or {}
        original_at = ts(cat.get("published_at")) or ts(cat.get("observed_at"))
        ref = at or ts(now())
        if cat.get("status") == "CURRENT" and (not original_at or not ref-timedelta(days=30) <= original_at <= ref):
            cat.update(status="STALE", missing_reason="catalyst_outside_30_day_window")
        out[sym] = {"security_guid": guid, "company_facts": company or {"status": "MISSING"},
                    "review_lifecycle": read(sym, root=root, security_guid=guid, store=store, records=records)}
    return out


def answer_note(research: dict) -> str:
    lines = []
    for sym, data in research.items():
        r = data.get("review_lifecycle") or {}
        if r.get("request_id"):
            lines.append(f"CIO review {sym}: {r.get('status')} — {r.get('reason') or 'reason unavailable'} "
                         f"CIO stance {r.get('old_stance') or 'unknown'} → {r.get('new_stance') or 'pending'}. "
                         f"[request {r['request_id']}; research {r.get('research_id') or 'not linked'}].")
        else:
            lines.append(f"CIO review {sym} unavailable — {r.get('reason') or 'canonical review missing'}; no authoritative outcome proven.")
    return "\n".join(lines)


def observe(request: dict, status: str, *, root=None, at=None, reason=None, research_id=None, evidence_refs=(),
            apply=False, store=None, backend=None, registry=None, env=None, memory_writer=None, publication=None) -> dict:
    """Append this factual transition through existing validated writer; never promotes a stance.

    Missing/legacy canonical coverage is reported. No helper ever mints a record
    or copies the proposed research stance into it. Research completion is pending.
    """
    from scripts.lib import cio_instrument_record as ir
    rid = request.get("review_request_id") or request.get("request_id")
    sym = str(request.get("symbol") or (request.get("symbols") or [""])[0]).upper()
    guid = request.get("security_guid") or (request.get("subject_guid") if request.get("identity_status") == "CONFIRMED" else None)
    if not rid or str(rid).startswith("legacy-"):
        return {"ok": False, "reason": "causal_request_id_unproven"}
    if status not in CLOCKS or status == "CONFLICT_RESOLVED":
        return {"ok": False, "reason": "resolution_requires_authoritative_readback"}
    if not guid or request.get("identity_status") != "CONFIRMED":
        return {"ok": False, "reason": "identity_not_confirmed"}
    st = store or _store(root)
    matches = _matches(st.all(), guid)
    if len(matches) != 1:
        return {"ok": False, "reason": "identity_or_canonical_record_unavailable"}
    record = matches[0]
    if not ir.is_prospect_record(record):
        return {"ok": False, "reason": "legacy_record_needs_cio_promotion"}
    when = at or now()
    if not ts(when):
        return {"ok": False, "reason": "event_clock_unavailable"}
    research = deepcopy(record.get("research") or {})
    prior = research.get("review_lifecycle") or {}
    requested = request.get("requested_at") or request.get("as_of") or request.get("created_ts") or when
    if prior.get("request_id") != rid and ts(prior.get("created_at")) and ts(requested) and ts(prior["created_at"]) > ts(requested):
        return {"ok": False, "reason": "older_request_event_held"}
    if prior.get("request_id") == rid:
        order = {"REQUESTED": 0, "RESEARCHING": 1, "BLOCKED": 1, "FAILED": 2, "ANSWERED_PENDING_CIO": 3, "CONFLICT_RESOLVED": 4}
        if order.get(status, 0) < order.get(prior.get("status"), 0):
            return {"ok": False, "reason": "delayed_event_ignored_consumer_ack_not_measured"}
        if prior.get(CLOCKS[status]) == when and prior.get("status") == status:
            return {"ok": False, "reason": "event_already_recorded_consumer_ack_not_measured"}
    summary = deepcopy(prior) if prior.get("request_id") == rid else {"schema": SCHEMA, "request_id": rid,
        "created_at": requested, "requested_at": requested, "old_stance": record.get("stance"), "new_stance": None}
    if summary.get("status") in TERMINAL:
        return {"ok": False, "reason": "terminal_event_recorded_consumer_ack_not_measured"}
    summary.update(status=status, updated_at=when, reason=str(reason or status)[:700])
    summary[CLOCKS[status]] = when
    if status == "RESEARCHING": summary["started_at"] = when
    if status == "ANSWERED_PENDING_CIO": summary["completed_at"] = when
    if research_id or request.get("research_id"):
        summary["research_id"] = research_id or request.get("research_id")
    summary["evidence_refs"] = list(dict.fromkeys([*(summary.get("evidence_refs") or []), *evidence_refs]))
    if publication:
        summary["publication"] = deepcopy(publication)
    if summary == prior:
        return {"ok": False, "reason": "event_already_recorded_consumer_ack_not_measured"}
    research["review_lifecycle"] = summary
    return _persist(record, research, root=root, apply=apply, st=st, backend=backend, registry=registry, env=env,
                    memory_writer=memory_writer)


def _persist(record, research, *, root, apply, st, backend=None, registry=None, env=None, memory_writer=None):
    from scripts.lib import cio_instrument_record as ir
    try:
        updated, _ = ir.apply_prospect(record, prospect={"research": research})
    except (ValueError, ir.BehaviorWriteRefused) as exc:
        return {"ok": False, "reason": f"record_validation_failed:{type(exc).__name__}"}
    if not apply:
        return {"ok": True, "mode": "dry_run", "would_write": True}
    if backend is None:
        def connect():
            from scripts.session13_db import get_conn
            return get_conn()
        backend = ir.ProspectPgBackend(connect)
    receipt = st.upsert_prospect(updated, backend=backend, registry=registry, env=env)
    pg = receipt["pg"]
    summary = research["review_lifecycle"]
    if memory_writer is None:
        from scripts.lib.cross_asset.security_research_spine import upsert_research_memory
        memory_writer = upsert_research_memory
    mem = memory_writer(str((record.get("symbols") or [record.get("symbol") or ""])[0]), silo="cio",
        kind="cio_review_lifecycle", summary=answer_note({"security": {"review_lifecycle": summary}}),
        artifact_id=f"{summary['request_id']}:{summary['status']}:{summary.get('updated_at')}",
        refs=[summary["request_id"], *(summary.get("evidence_refs") or [])], tags=["cio_review_lifecycle"],
        thesis_patch=None, subject_guid=record["security_guid"], issuer_guid=record.get("issuer_guid"), root=root)
    return {"ok": bool(mem.get("ok")) and pg.get("mode") == "dual_write" and pg.get("ok") is True,
            "record_written": True, "memory_ok": bool(mem.get("ok")), "pg_mode": pg.get("mode"),
            "pg_ok": pg.get("ok"), "pg_error": str(pg.get("error") or "").split(":", 1)[0] or None,
            "reason": "memory_write_failed" if not mem.get("ok") else ("pg_write_failed" if pg.get("ok") is False else (
                "pg_write_inert" if pg.get("mode") != "dual_write" else "record_and_memory_acknowledged"))}


def observe_cio_readback(request: dict, *, root=None, store=None, thesis_reader=None, apply=False, **write_options) -> dict:
    """Only actual, causally linked CIO publication + clean canonical readback resolves.

    This observer never changes stance or clears a conflict. Called after the
    acquisition owner publishes; later runs revisit still-pending saved summaries.
    """
    st = store or _store(root)
    rid = request.get("review_request_id") or request.get("request_id")
    guid = request.get("security_guid")
    rows = _matches(st.all(), guid)
    if len(rows) != 1:
        return {"ok": False, "reason": "canonical_readback_unavailable"}
    rec = rows[0]
    summary = ((rec.get("research") or {}).get("review_lifecycle") or {})
    version = request.get("published_version")
    thesis_id = request.get("thesis_id")
    if request.get("identity_status") != "CONFIRMED" or summary.get("request_id") != rid or not version or not thesis_id:
        return {"ok": False, "reason": "publication_lineage_unproven"}
    if thesis_reader is None:
        # Pure projection read: CIOThesisStore construction can rebuild/write.
        def thesis_reader(key):
            try:
                return (json.loads(st.path.with_name("cio_theses_projection.json").read_text()).get("current") or {}).get(key)
            except (OSError, ValueError):
                return None
    thesis = thesis_reader(thesis_id) or {}
    provenance = (thesis.get("extra") or {}).get("write_provenance") or thesis.get("write_provenance") or {}
    linked = rid in (provenance.get("review_request_ids") or [])
    if summary.get("research_id"):
        linked = linked and summary["research_id"] in (provenance.get("source_research_ids") or [])
    source_at = ts(thesis.get("published_ts") or thesis.get("updated_ts"))
    requested_at = ts(summary.get("created_at"))
    observed_at = ts(now())
    same_security = bool(provenance.get("security_guid") or thesis.get("security_guid")) and all(str(v) == str(guid) for v in (provenance.get("security_guid"), thesis.get("security_guid")) if v)
    same_symbol = str(thesis.get("symbol") or ((thesis.get("extra") or {}).get("symbol")) or "").upper() == str(request.get("symbol") or "").upper()
    if (thesis.get("thesis_version") != version or thesis.get("owner_agent") != "alex" or not linked
            or not source_at or not requested_at or source_at < requested_at or source_at > observed_at or requested_at > observed_at or not same_security or not same_symbol):
        return {"ok": False, "reason": "cio_publication_readback_unproven"}
    stance = str(thesis.get("stance") or "").upper()
    if not stance or str(rec.get("stance") or "").upper() != stance or any(not c.get("resolved") for c in rec.get("conflicts") or []):
        return {"ok": False, "reason": "canonical_stance_or_conflicts_still_pending"}
    # A result/publication's draft stance is never assigned to rec['stance'].
    research = deepcopy(rec.get("research") or {})
    summary = deepcopy(summary)
    when = now()
    summary.update(status="CONFLICT_RESOLVED", new_stance=rec["stance"], conflict_resolved_at=when,
                   updated_at=when, reason=str(provenance.get("reason_for_change") or thesis.get("change_note") or "CIO outcome rationale unavailable")[:700],
                   readback_verification="CIO-owned linked publication and canonical record agree")
    summary["evidence_refs"] = list(dict.fromkeys([*(summary.get("evidence_refs") or []), thesis_id, version]))
    research["review_lifecycle"] = summary
    return _persist(rec, research, root=root, apply=apply, st=st, **write_options)


def rows(path: Path) -> list[dict]:
    try:
        out = []
        for line in path.read_text().splitlines():
            try: out.append(json.loads(line))
            except ValueError: continue
        return [r for r in out if isinstance(r, dict)]
    except OSError:
        return []


def aging(root: Path, *, requests=(), at=None, overdue_hours=24) -> dict:
    ref = at or datetime.now(timezone.utc)
    findings = []
    store = _store(root)
    records = store.all()
    for req in requests:
        sym = str(req.get("symbol") or "")
        guid = req.get("security_guid") or (req.get("subject_guid") if req.get("identity_status") == "CONFIRMED" else None)
        rid = req.get("request_id") or req.get("review_request_id")
        receipt = req.get("lifecycle_persist") or {}
        if receipt and receipt.get("ok") is False:
            findings.append({"symbol": sym, "status": "CONSUMER_WRITE_INCOMPLETE", "reason": receipt.get("reason"),
                             "pg_mode": receipt.get("pg_mode"), "memory_ok": receipt.get("memory_ok")})
        saved = read(sym, root=root, security_guid=guid, store=store, records=records)
        requested = ts(req.get("requested_at") or req.get("as_of"))
        if not rid or str(rid).startswith("legacy-") or not requested or not guid:
            findings.append({"symbol": sym, "status": "NOT_MEASURED", "reason": "request_lineage_clock_or_identity_unproven"})
            continue
        if saved.get("request_id") != rid:
            findings.append({"symbol": sym, "request_id": rid, "status": "NOT_MEASURED",
                             "reason": "exact_request_outcome_not_on_cio_record"})
            continue
        if saved.get("status") in TERMINAL:
            continue
        phase = saved.get("status")
        clock = "answered_at" if phase == "ANSWERED_PENDING_CIO" else "researching_at" if phase == "RESEARCHING" else "created_at"
        since = ts(saved.get(clock))
        if phase == "FAILED":
            findings.append({"symbol": sym, "request_id": rid, "status": "FAILED", "reason": saved.get("reason")})
        elif since and (ref-since).total_seconds() > overdue_hours*3600:
            findings.append({"symbol": sym, "request_id": rid, "status": "OVERDUE", "phase": phase,
                             "age_basis": clock, "age_hours": round((ref-since).total_seconds()/3600, 2),
                             "reason": "CIO decision pending" if phase == "ANSWERED_PENDING_CIO" else "exact phase overdue"})
    return {"schema": "CIOReviewAging@v1", "contract_status": "DRAFT", "as_of": ref.isoformat(),
            "findings": findings, "requests": len(requests), "alert_delivery": "NOT_MEASURED", "writes": 0}


def safe_observe(request, status, *, root=None, **kwargs):
    """A metadata failure must not break an existing enqueue/publisher owner."""
    if os.environ.get("PYTEST_CURRENT_TEST") and root is None:
        return {"ok": False, "reason": "fixture_root_required"}
    try:
        members = request.get("review_requests") or []
        if members:
            receipts = [observe({**member, "research_id": request.get("research_id")}, status, root=root, apply=True, **kwargs) for member in members]
            return {"ok": all(r.get("ok") for r in receipts), "requests": receipts}
        return observe(request, status, root=root, apply=True, **kwargs)
    except Exception as exc:
        return {"ok": False, "reason": f"lifecycle_write_failed:{type(exc).__name__}"}


def refresh_pending(root, *, apply=False, store=None, **write_options):
    """Existing acquisition pass revisits saved answers after their CIO owner acts.

    Reads only existing record and thesis projections. No new research or schedule.
    """
    st = store or _store(root)
    results = []
    for r in st.all():
        saved = ((r.get("research") or {}).get("review_lifecycle") or {})
        pub = saved.get("publication") or {}
        if saved.get("status") == "ANSWERED_PENDING_CIO" and pub:
            try:
                results.append(observe_cio_readback({**pub, "symbol": (r.get("symbols") or [r.get("symbol") or ""])[0],
                    "security_guid": r.get("security_guid"), "identity_status": "CONFIRMED",
                    "review_request_id": saved.get("request_id")}, root=root, store=st, apply=apply, **write_options))
            except Exception as exc:
                results.append({"ok": False, "reason": f"readback_failed:{type(exc).__name__}"})
    return results
