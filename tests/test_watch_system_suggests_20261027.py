"""Synthetic Watch suggestions / CIO progress regressions.
ANCHOR: WATCH_SYSTEM_SUGGESTS_20261027. No live API, provider or credentials.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT / "scripts"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from lib import site_payload_reads as reads
from lib.data_broker import watch_prospects as prospects
from scripts.lib.data_broker import watch_review_status as progress

NOW = datetime(2026, 10, 27, 18, tzinfo=timezone.utc)
GUID = "12345678-1234-5234-8234-123456789001"


def test_review_failures_open_one_safe_incident_and_never_echo_exception_text(tmp_path):
    from scripts.lib.watch_review_incidents import record_failure
    from scripts.lib import incidents

    one = record_failure("progress", OSError("synthetic private exception text"), root=tmp_path)
    two = record_failure("progress", OSError("other private exception text"), root=tmp_path)
    assert one and one == two
    rows = incidents.load_records(incidents.incidents_dir(tmp_path))
    assert len(rows) == 1
    assert "private exception text" not in str(rows)


def test_queue_write_failure_is_visible_and_incident_traced(monkeypatch):
    from scripts import api_v3_opportunities as api
    from scripts.lib import watch_review_incidents

    monkeypatch.setattr(api, "review_state", lambda _s: {"open": False})
    monkeypatch.setattr(api, "request_state", lambda _s: None)

    class BrokenQueue:
        def request(self, *_a, **_k):
            raise OSError("synthetic private detail")

    monkeypatch.setattr(api, "_priority", lambda: BrokenQueue())
    monkeypatch.setattr(watch_review_incidents, "record_failure", lambda *_a, **_k: "INC-synthetic")
    code, body = api.request_review("ZZAA", identity=lambda *_a: {"identity_status": "UNRESOLVED"})
    assert code == 503 and not body["ok"] and body["incident_id"] == "INC-synthetic"
    assert "private detail" not in str(body)


def test_legacy_success_has_consistent_queue_and_display_state(tmp_path):
    import json
    from scripts.lib import symbol_thesis_priority as queue

    request = {"symbol": "ZZAA", "requested_at": (NOW - timedelta(hours=2)).isoformat()}
    attempt = {"symbol": "ZZAA", "status": "PUBLISHED", "as_of": (NOW - timedelta(hours=1)).isoformat()}
    for rel, row in ((queue.RELPATH, request), (queue.LEDGER_RELPATH, attempt)):
        path = tmp_path.joinpath(*rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row) + "\n")
    assert queue.open_requests(root=tmp_path, now=NOW) == []
    state = queue.review_states(["ZZAA"], root=tmp_path, now=NOW)["ZZAA"]
    assert state["status"] == "answered" and not state["open"]
    assert "cio_link" not in state["last_attempt"]


def source_row():
    row = prospects.no_record_row("ZZAA")
    return {
        **row,
        "security_guid": GUID,
        "identity_status": "CONFIRMED",
        "stance": "BUY",
        "conviction": 80,
        "next_action": {"kind": "set_alert"},
    }


def test_missing_or_partial_cio_record_never_mints_conviction_conflict():
    row = source_row()
    original = deepcopy(row)
    truth = {"stance": None, "conviction": 50, "gap": {"reason": "CIO record needed"}, "conflicts": []}
    result = reads.canonical_rows([row], resolver=lambda *_a, **_k: truth)[0]
    assert not result["conflicts"]
    assert result["next_action"]["kind"] == "cio_missing"
    assert row == original


def test_real_two_sided_conflict_preserves_both_values_and_times():
    truth = {"stance": "WATCH", "conviction": 50, "gap": None, "conflicts": [], "as_of": NOW.isoformat()}
    result = reads.canonical_rows([source_row()], resolver=lambda *_a, **_k: truth)[0]
    assert result["next_action"]["kind"] == "resolve_conflict"
    assert result["conflicts"][1]["a"]["value"] == 50
    assert result["conflicts"][1]["b"]["value"] == 80
    assert result["conflicts"][1]["a"]["at"] == NOW.isoformat()


def test_ranked_suggestion_without_card_is_not_reentry_only():
    missing = prospects.whats_missing(
        card=None,
        opp={"rank": 1},
        conv={"conviction": 70, "stale": False, "missing_components": []},
        lv={"entry_low_ref": None, "stop_ref": None},
        lane="forming",
        identity={"confirmed": True},
    )
    assert any("Ranked research universe" in value for value in missing)
    assert not any("seen only by the re-entry" in value for value in missing)


def answered():
    state = {
        "schema": "ReviewRequestState@v1",
        "symbol": "ZZAA",
        "status": "answered",
        "open": False,
        "label": "Answered",
        "request_id": "rr_synthetic",
        "queued_at": (NOW - timedelta(days=19)).isoformat(),
        "last_attempt": {"status": "PUBLISHED", "at": (NOW - timedelta(days=18)).isoformat()},
    }
    state["last_publication"] = {
        **state["last_attempt"],
        "request_id": "rr_synthetic",
        "security_guid": GUID,
        "publication": {"thesis_version": "research_fixture", "published_at": state["last_attempt"]["at"]},
    }
    return state


def test_old_publication_is_history_when_current_cio_link_missing():
    state = answered()
    result = progress.presentation_state(state, {"gap": {"reason": "missing"}}, now=NOW)
    assert "Previous research published" in result["label"]
    assert "18 d ago" in result["label"] and "refresh" in result["label"]
    assert result["publication_verified"] is False
    assert "answer_age_hours" not in state


@pytest.mark.parametrize("request_id", [None, "rr_other"])
def test_different_or_absent_request_cannot_claim_canonical_answer(request_id):
    truth = {
        "gap": None,
        "review": {"request_id": request_id, "research_id": "research_fixture", "answered_at": NOW.isoformat()},
    }
    assert not progress.presentation_state(answered(), truth, now=NOW)["publication_verified"]


def test_linked_cio_answer_and_original_publication_clock_are_exposed():
    truth = {
        "gap": None,
        "security_guid": GUID,
        "review": {
            "request_id": "rr_synthetic",
            "research_id": "research_fixture",
            "answered_at": answered()["last_attempt"]["at"],
            "resolution_proven": True,
            "reason": "Stored evidence reviewed; watch the recorded catalyst.",
        },
    }
    result = progress.presentation_state(answered(), truth, now=NOW)
    assert result["publication_verified"] and result["status"] == "answered"
    assert result["answered_at"] == answered()["last_attempt"]["at"]
    assert result["answer_summary"] == truth["review"]["reason"]


def test_request_id_alone_is_not_a_cio_publication_readback():
    truth = {
        "gap": None,
        "review": {"request_id": "rr_synthetic", "research_id": "research_fixture", "answered_at": NOW.isoformat()},
    }
    assert not progress.presentation_state(answered(), truth, now=NOW)["publication_verified"]


def test_later_failed_attempt_never_dates_an_older_success_as_current():
    state = answered()
    state["last_attempt"] = {"status": "SYNTHESIS_FAILED", "at": NOW.isoformat()}
    out = progress.presentation_state(state, {}, now=NOW)
    assert out["answered_at"] == (NOW - timedelta(days=18)).isoformat()
    assert "18 d ago" in out["label"]


def _seed_link_case(tmp_path, monkeypatch):
    import json
    from scripts.lib import cio_instrument_record as records, identity_carriage

    request = {
        "symbol": "ZZAA",
        "request_id": "rr_synthetic",
        "security_guid": GUID,
        "identity_status": "CONFIRMED",
        "requested_at": NOW.isoformat(),
    }
    monkeypatch.setattr(identity_carriage, "resolve_security_identity", lambda *a, **k: request)
    rec = records.new_record(
        "SECURITY",
        "ZZAA",
        symbols=["ZZAA"],
        security_guid=GUID,
        issuer_guid="12345678-1234-5234-8234-123456789002",
        identity_status="CONFIRMED",
    )
    rec, _ = records.apply_prospect(
        rec,
        prospect={
            "stage": "watching",
            "stance": "WATCH",
            "conviction": 60,
            "evidence_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(days=1)).isoformat(),
            "research": {"retained_fact": "KEEP"},
            "conflicts": [],
        },
    )
    store = records.InstrumentRecordStore(tmp_path / records.DEFAULT_PATH)
    store.upsert(rec)
    version = "symbol_zzaa@v1"
    path = tmp_path / "data/cio/cio_theses_projection.json"
    path.write_text(
        json.dumps(
            {
                "versions": {
                    "symbol_zzaa": {
                        "1": {
                            "thesis_version": version,
                            "linked_symbols": ["ZZAA"],
                            "published_ts": NOW.isoformat(),
                            "summary": "Fictional catalyst researched.",
                        }
                    }
                }
            }
        )
    )
    result = {"status": "PUBLISHED", "review": {"new_version": version}}
    return records, request, rec, store, version, result


def test_acquisition_publication_links_to_shared_cio_research_without_changing_judgment(tmp_path, monkeypatch):
    from scripts.lib.watch_review_publication import link_publication
    from scripts.lib.data_broker.cio_company_facts import load_snapshot

    records, request, rec, store, version, result = _seed_link_case(tmp_path, monkeypatch)
    out = link_publication(tmp_path, request, result, registry={}, env={})
    assert out["ok"] and out["state"] == "ANSWERED_PENDING_CIO"
    saved = records.InstrumentRecordStore(store.path).load(rec["subject_key"])
    assert saved["stance"] == rec["stance"] and saved["conviction"] == rec["conviction"]
    assert saved["research"]["retained_fact"] == "KEEP" and saved["conflicts"] == []
    lifecycle = load_snapshot(root=tmp_path)[GUID]["review_lifecycle"]
    assert lifecycle["request_id"] == request["request_id"] and lifecycle["research_id"] == version
    assert lifecycle["status"] == "ANSWERED_PENDING_CIO" and "readback_verification" not in lifecycle
    from scripts.lib import cio_ask_research as ask

    facts = ask._src_cio_record_research(
        ask.Entity("Fictional", "listed", symbol="ZZAA", security_guid=GUID),
        ask.ResearchContext("What happened to ZZAA review?", state_root=tmp_path, now=NOW),
    )
    assert any(version in f.claim for f in facts), "Ask the CIO reads the same saved review outcome"
    assert any("Fictional catalyst researched." in f.claim for f in facts)
    original = store.path.read_bytes()
    assert link_publication(
        tmp_path, request, {**result, "as_of": (NOW + timedelta(days=1)).isoformat()}, registry={}, env={}
    )["ok"]
    assert store.path.read_bytes() == original, "memory receipt retry is idempotent"


def test_requested_pg_unavailable_refuses_before_canonical_append(tmp_path, monkeypatch):
    from scripts.lib.watch_review_publication import link_publication

    ir, request, _, store, _, result = _seed_link_case(tmp_path, monkeypatch)

    class Backend:
        def table_present(self):
            return False

    original = store.path.read_bytes()
    out = link_publication(
        tmp_path, request, result, backend=Backend(), registry={}, env={ir.PROSPECT_DUAL_WRITE_ENV: "1"}
    )
    assert not out["ok"] and out["reason"] == "canonical_pg_preflight_failed"
    assert store.path.read_bytes() == original


@pytest.mark.parametrize("status,newer", [("CONFLICT_RESOLVED", False), ("RESEARCHING", True)])
def test_delayed_publication_cannot_downgrade_cio_lifecycle(tmp_path, monkeypatch, status, newer):
    from scripts.lib.watch_review_publication import link_publication

    ir, request, rec, store, version, result = _seed_link_case(tmp_path, monkeypatch)
    lifecycle = {
        "status": status,
        "request_id": "rr_newer" if newer else request["request_id"],
        "requested_at": (NOW + timedelta(hours=1)).isoformat() if newer else request["requested_at"],
        "research_id": version,
        "reason": "Later CIO outcome must survive",
    }
    updated, _ = ir.apply_prospect(rec, prospect={"research": {"review_lifecycle": lifecycle}})
    store.upsert_prospect(updated, registry={}, env={})
    before = store.path.read_bytes()
    out = link_publication(tmp_path, request, result, registry={}, env={})
    assert not out["ok"]
    assert out["reason"] == (
        "newer_canonical_review_preserved" if newer else "canonical_review_finalized_owner_readback_required"
    )
    assert store.path.read_bytes() == before


def test_pg_failure_repairs_same_published_result_without_new_research(tmp_path, monkeypatch):
    from scripts.lib.watch_review_publication import link_publication

    ir, request, rec, store, _, result = _seed_link_case(tmp_path, monkeypatch)
    registry = {"domains": [{"domain": "cio_prospect", "approval": {"approved_by": "synthetic operator"}}]}

    class Backend:
        calls, row = 0, None

        def table_present(self):
            return True

        def write(self, row, *_args):
            self.calls += 1
            if self.calls == 1:
                raise OSError("synthetic PG outage")
            self.row = row
            return {"ok": True, "upserted": 1}

    backend = Backend()
    reader = lambda *_a: {"ok": True, "source": {"kind": "store"}, "prospect": backend.row}
    options = {"backend": backend, "registry": registry, "env": {ir.PROSPECT_DUAL_WRITE_ENV: "1"}, "pg_reader": reader}
    assert not link_publication(tmp_path, request, result, **options)["ok"]
    saved = ir.InstrumentRecordStore(store.path).load(rec["subject_key"])
    repaired = link_publication(tmp_path, request, result, **options)
    assert repaired["ok"] and backend.calls == 2
    assert backend.row["revision"] == saved["prospect_revision"]
    assert backend.row["stance"] == rec["stance"] and backend.row["conviction"] == rec["conviction"]
    options["pg_reader"] = lambda *_a: {"ok": True, "source": {"kind": "store"}, "prospect": {}}
    assert link_publication(tmp_path, request, result, **options)["reason"] == "canonical_pg_readback_pending"


@pytest.mark.parametrize(
    "ok,classification,expected",
    [
        (False, None, "BLOCKED"),
        (True, "INSUFFICIENT_DATA", "BLOCKED"),
        (True, "NO_MATERIAL_CHANGE", "SYNTHESIZED_NO_MATERIAL_CHANGE"),
    ],
)
def test_real_acquisition_classification_does_not_answer_failed_review(
    tmp_path, monkeypatch, ok, classification, expected
):
    import scripts.run_symbol_thesis_acquisition as acq

    monkeypatch.setattr(acq, "thesis_fields_for_symbol", lambda *_a, **_k: {})
    monkeypatch.setattr(
        acq, "build_evidence_catalog", lambda *_a, **_k: {"sufficiency": {"sufficient_for_synthesis": True}}
    )
    monkeypatch.setattr(acq, "build_acquisition_plan", lambda *_a, **_k: {})
    monkeypatch.setattr(acq, "build_synthesis_packet", lambda *_a, **_k: {"gate": "READY_FOR_SYNTHESIS"})
    monkeypatch.setattr(acq, "offpeak_wait", lambda: None)
    monkeypatch.setattr(acq, "synthesize_thesis_via_flash", lambda *_a, **_k: {"ok": True, "synthesis_result": {}})
    monkeypatch.setattr(
        acq,
        "apply_synthesis_to_thesis",
        lambda *_a, **_k: {
            "ok": ok,
            "review": {"classification": classification, "version_published": False, "new_version": "old_fixture@v1"},
        },
    )
    out = acq._run_one_impl(
        "ZZAA",
        root=tmp_path,
        apply=True,
        skip_acquire=True,
        skip_embed=True,
        skip_synthesize=False,
        skip_publish=False,
        enqueue_refresh=False,
        llm_budget_left=[1],
    )
    assert out["status"] == expected
    if expected == "SYNTHESIZED_NO_MATERIAL_CHANGE":
        assert out["review"]["reviewed_at"] == out["as_of"]


def test_no_valid_cio_prospect_is_explicit_link_pending_not_a_minted_judgment(tmp_path, monkeypatch):
    import json
    from scripts.lib import identity_carriage
    from scripts.lib.watch_review_publication import link_publication

    request = {"symbol": "ZZAA", "request_id": "rr_synthetic", "security_guid": GUID, "identity_status": "CONFIRMED"}
    monkeypatch.setattr(identity_carriage, "resolve_security_identity", lambda *a, **k: request)
    p = tmp_path / "data/cio/cio_theses_projection.json"
    p.parent.mkdir(parents=True)
    p.write_text(
        json.dumps(
            {
                "versions": {
                    "symbol_zzaa": {
                        "1": {
                            "thesis_version": "symbol_zzaa@v1",
                            "linked_symbols": ["ZZAA"],
                            "published_ts": NOW.isoformat(),
                        }
                    }
                }
            }
        )
    )
    out = link_publication(tmp_path, request, {"status": "PUBLISHED", "review": {"new_version": "symbol_zzaa@v1"}})
    assert not out["ok"] and out["reason"] == "valid_cio_prospect_needed_for_review_link"
    assert not (tmp_path / "data/cio/cio_instrument_records.jsonl").exists()


def test_new_request_is_not_closed_by_an_unrelated_or_memory_pending_publication(tmp_path):
    import json
    from scripts.lib import symbol_thesis_priority as queue
    from scripts.lib.watch_review_publication import published_for_request

    request = queue.request(
        "ZZAA",
        reason="Synthetic operator request",
        source="operator_opportunity_view",
        root=tmp_path,
        now=NOW - timedelta(minutes=5),
        extra={"request_id": "rr_synthetic", "security_guid": GUID},
    )
    p = tmp_path.joinpath(*queue.LEDGER_RELPATH)
    wrong = {"symbol": "ZZAA", "status": "PUBLISHED", "as_of": NOW.isoformat(), "request_id": "rr_other"}
    p.write_text(json.dumps(wrong) + "\n")
    assert queue.open_requests(tmp_path, now=NOW) == ["ZZAA"]
    pending = {
        **wrong,
        "request_id": "rr_synthetic",
        "cio_link": {"ok": False, "reason": "canonical_link_pending"},
        "publication": {"thesis_version": "symbol_zzaa@v1", "published_at": NOW.isoformat()},
    }
    with p.open("a") as f:
        f.write(json.dumps(pending) + "\n")
    assert queue.open_requests(tmp_path, now=NOW) == ["ZZAA"]
    state = queue.review_states(["ZZAA"], tmp_path, now=NOW)["ZZAA"]
    assert state["status"] == "blocked" and "CIO memory link pending" in state["label"]
    assert published_for_request(tmp_path, request)["publication"] == pending["publication"]
    acknowledged = {**pending, "cio_link": {"ok": True, "state": "ANSWERED_PENDING_CIO"}}
    with p.open("a") as f:
        f.write(json.dumps(acknowledged) + "\n")
    assert queue.open_requests(tmp_path, now=NOW) == []


def test_watch_request_identity_is_checked_before_paid_owner_work(tmp_path):
    from scripts.lib.watch_review_publication import request_blocker

    assert request_blocker(tmp_path, None) is None  # unrelated legacy acquisition remains unchanged
    req = {"symbol": "ZZAA", "request_id": "rr_synthetic", "identity_status": "UNRESOLVED"}
    assert request_blocker(tmp_path, req) == "REQUEST_IDENTITY_UNCONFIRMED"
    req.update(identity_status="CONFIRMED", security_guid=GUID)
    assert (
        request_blocker(
            tmp_path, req, identity_resolver=lambda *a, **k: {"identity_status": "CONFIRMED", "security_guid": "other"}
        )
        == "REQUEST_IDENTITY_CHANGED"
    )
    assert request_blocker(tmp_path, req, identity_resolver=lambda *a, **k: req) is None


@pytest.mark.parametrize("status", ["queued", "blocked", "waiting_budget", "failed", "expired"])
def test_real_queue_blockers_are_preserved(status):
    state = {
        "status": status,
        "label": "Recorded evidence/cap reason",
        "open": True,
        "last_attempt": {"at": NOW.isoformat(), "block_reason": "PROCESS_CAP"},
    }
    result = progress.presentation_state(state, {}, now=NOW)
    assert result["status"] == status and result["last_attempt"] == state["last_attempt"]


@pytest.mark.parametrize("raw", ["", "ZZAA/../ZZBB", "ZZAA<script>", ",".join(f"ZZ{i}" for i in range(31))])
def test_invalid_status_queries_are_rejected_before_readers(raw):
    def forbidden(*_args):
        pytest.fail("invalid query reached a reader")

    assert progress.review_status({"symbols": raw}, priority_reader=forbidden, stance_reader=forbidden)["ok"] is False


def test_status_projection_batches_and_exposes_unreadable_source():
    calls = []

    def priority(names):
        calls.append(names)
        return {s: {"status": "queued", "open": True, "label": "Queued"} for s in names}

    out = progress.review_status(
        {"symbols": "ZZBB,ZZAA,ZZAA"}, priority_reader=priority, stance_reader=lambda names: {}, now=NOW
    )
    assert calls == [["ZZAA", "ZZBB"]] and out["provider_calls"] == 0 and out["read_only"]

    def broken(_names):
        raise OSError("synthetic sensitive error must not surface")

    out = progress.review_status({"symbols": "ZZAA"}, priority_reader=broken, stance_reader=lambda names: {}, now=NOW)
    assert out["error"] == "review_status_unavailable"
    assert "sensitive" not in str(out)


def test_progress_query_uses_broker_without_full_curator_or_per_row_reads(monkeypatch):
    from scripts import api_v3_data_broker_watch as api
    from lib.data_broker import watch_review_status as adapter

    monkeypatch.setattr(adapter, "review_status", lambda query: {"ok": True, "fixture": query["symbols"]})
    assert api.get_curation({"review_status": ["1"], "symbols": "ZZAA"}) == {"ok": True, "fixture": "ZZAA"}


def test_phone_state_order_does_not_restore_an_older_request_or_answer():
    node = shutil.which("node")
    assert node, "Node is required to verify the UI state model"
    module = (ROOT / "apps/command-center-v3/src/lib/watchReviewState.ts").as_uri()
    code = f"""import assert from 'node:assert/strict';
import {{newerReviewState}} from {module!r};
const queued = {{request_id:'rr_new',queued_at:'2026-10-27T18:00:00Z',status:'queued'}};
const old = {{request_id:'rr_old',queued_at:'2026-10-09T18:00:00Z',updated_at:'2026-10-27T18:01:00Z',status:'answered'}};
assert.equal(newerReviewState(old,queued),queued);
const answered = {{...queued,status:'answered',updated_at:'2026-10-27T18:02:00Z'}};
assert.equal(newerReviewState(queued,answered),answered);
assert.equal(newerReviewState(answered,queued),answered);
assert.equal(newerReviewState(null,queued),queued);
"""
    subprocess.run(
        [node, "--experimental-strip-types", "--input-type=module", "-e", code],
        check=True,
        capture_output=True,
        text=True,
    )
