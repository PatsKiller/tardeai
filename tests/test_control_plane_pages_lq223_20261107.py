"""LQ-20261107-223: six /v3/control-plane pages, each traced to its endpoint and producer.

Live walk 2026-11-07 14:55 ET (GET only, 9aac539a1), and the cause of each defect:

* identity  UNAVAILABLE      data/runtime/identity_registry.json is ``IdentityRegistry@v1`` (a dict keyed by
                             ``entities``); the reader only knew items/rows/data/by_research_id and skipped it.
* workflows INVALID_SCHEMA   one torn line (two interleaved appends) in 267,583 lines of the append-only
                             lineage failed the whole read.
* learning  rows "undefined" ``OutcomeObservation@v1`` rows carry none of the LearningEvidenceStatus keys the
                             page renders (item_id, kind, status, ...).
* audit     rows "undefined" the store is a CIO office browser-audit run, not AuditCapabilityClaim rows.
* system    PREVIEW fixture  the surface map said the route had no domain, and runtime.state was a constant
                             UNKNOWN.
* maturity  EMPTY            fixed by the carried LQ-177 commit (relative store labels count as evidence).

Synthetic fixtures only. AUTHORITY: READ_ONLY_ADVISORY.

COVERS = ["scripts/control_plane_api.py", "scripts/lib/whole_site_truth.py"]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.control_plane_api as api  # noqa: E402


@pytest.fixture
def root(tmp_path, monkeypatch):
    for name in ("TRADEAI_STATE_ROOT", "TRADEAI_ROOT", "TRADEAI_PERSISTENT_STATE_ROOT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    api._jsonl_cache_clear()
    yield tmp_path
    api._jsonl_cache_clear()


def _get(domain: str, **query):
    status, body = api.handle(f"/api/v3/control-plane/{domain}", query=query or None)
    assert status == 200
    return body


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ── identity ────────────────────────────────────────────────────────────────────────────────────────────────────


def _entity(guid: str, status: str, **extra) -> dict:
    return {
        "subject_guid": guid,
        "identity_status": status,
        "issuer_guid": extra.get("issuer_guid"),
        "security_guid": extra.get("security_guid"),
        "listing_guid": None,
        "ticker_alias": extra.get("ticker", "ZZZT"),
        "aliases": [extra.get("ticker", "ZZZT")],
        "identifiers": extra.get("identifiers", {}),
        "unresolved_reason": extra.get("unresolved_reason"),
        "last_seen": "2026-01-02T00:00:00+00:00",
        "active": True,
        "schema": "RegisteredEntity@v1",
    }


def test_identity_registry_entities_are_served_as_rows(root):
    reg = {
        "schema": "IdentityRegistry@v1",
        "authority": "READ_ONLY_ADVISORY",
        "updated_at": "2026-01-02T00:00:00+00:00",
        "by_symbol": {"ZZZT": "g-1"},
        "events": {},
        "entities": {
            "g-1": _entity("g-1", "CONFIRMED", security_guid="s-1", issuer_guid="i-1", identifiers={"cik": "0"}),
            "g-2": _entity("g-2", "UNRESOLVED_WITH_REASON", ticker="QQQZ", unresolved_reason="no_card"),
        },
    }
    _write(root, "data/runtime/identity_registry.json", json.dumps(reg))
    body = _get("identity")
    assert body["data_quality"] == "AVAILABLE"
    rows = {r["entity_id"]: r for r in body["data"]["items"]}
    assert set(rows) == {"g-1", "g-2"}
    assert rows["g-1"]["state"] == "CONFIRMED" and rows["g-1"]["security"] == "s-1" and rows["g-1"]["issuer"] == "i-1"
    assert rows["g-2"]["unresolved_reason"] == "no_card"
    assert rows["g-2"]["security"] is None, "a security id is never minted from the ticker"
    assert rows["g-1"]["source"] == "identity.registry" and rows["g-1"]["as_of"] == "2026-01-02T00:00:00+00:00"
    assert body["data"]["pagination"]["total"] == 2


def test_identity_entity_without_a_subject_guid_keeps_its_key_never_the_ticker(root):
    ent = _entity("", "CANDIDATE", ticker="ABCZ")
    ent.pop("subject_guid")
    _write(root, "data/runtime/identity_registry.json", json.dumps({"entities": {"k-9": ent}}))
    (row,) = _get("identity")["data"]["items"]
    assert row["entity_id"] == "k-9"


# ── workflows ───────────────────────────────────────────────────────────────────────────────────────────────────


def _envelope_row(i: int) -> dict:
    return {"record_type": "envelope", "workflow_id": f"wf-{i}", "status": "COMPLETED", "as_of": f"t{i}"}


def _lines(rows) -> str:
    return "".join(json.dumps(r) + "\n" for r in rows)


def test_one_torn_lineage_line_does_not_fail_the_whole_workflow_list(root):
    good = _lines(_envelope_row(i) for i in range(40))
    torn = '{"record_type": "envelope", "workflow_id": "wf-x", "decision_i{"as_of": "t", "record_type": "node"}\n'
    _write(root, "data/cio/cio_workflow_lineage.jsonl", good + torn + _lines([_envelope_row(99)]))
    body = _get("workflows", limit=500)
    assert body["data_quality"] == "AVAILABLE"
    ids = {r["workflow_id"] for r in body["data"]["items"]}
    assert ids == {f"wf-{i}" for i in range(40)} | {"wf-99"}
    assert body["data"]["skipped_corrupt_lines"] == 1


def test_the_skipped_count_survives_a_resumed_read(root):
    path = _write(
        root, "data/cio/cio_workflow_lineage.jsonl", _lines(_envelope_row(i) for i in range(5)) + "{torn\n"
    )
    assert _get("workflows")["data"]["skipped_corrupt_lines"] == 1
    with path.open("a", encoding="utf-8") as fh:
        fh.write(_lines([_envelope_row(7)]) + "[1, 2]\n")
    body = _get("workflows", limit=500)
    assert body["data"]["skipped_corrupt_lines"] == 2
    assert "wf-7" in {r["workflow_id"] for r in body["data"]["items"]}


def test_a_lineage_that_is_mostly_corrupt_is_still_invalid(root):
    _write(root, "data/cio/cio_workflow_lineage.jsonl", _lines([_envelope_row(1)]) + "{bad\n" * 30)
    body = _get("workflows")
    assert body["data_quality"] == "INVALID_SCHEMA"


def test_a_clean_lineage_reports_no_skipped_lines(root):
    _write(root, "data/cio/cio_workflow_lineage.jsonl", _lines(_envelope_row(i) for i in range(3)))
    body = _get("workflows")
    assert body["data_quality"] == "AVAILABLE" and "skipped_corrupt_lines" not in body["data"]


def test_agent_traces_stay_strict(root):
    """The agents read pins a corrupt line as INVALID_SCHEMA (LQ-177); only the lineage history tolerates one."""
    trace = {"agent": "a", "trace_id": "t1", "status": "completed", "started_at": "2026-01-01T00:00:00Z"}
    _write(root, "data/cio/agent_run_traces.jsonl", json.dumps(trace) + "\n{bad\n")
    assert _get("agents")["data_quality"] == "INVALID_SCHEMA"


# ── learning ────────────────────────────────────────────────────────────────────────────────────────────────────

LEARNING_KEYS = {"item_id", "kind", "status", "score", "evidence_class", "proof_refs", "limiting_factor", "next_proof"}


def _outcome(i: int, linked: bool = True) -> dict:
    return {
        "schema": "OutcomeObservation@v1",
        "outcome_id": f"o-{i}",
        "decision_id": f"d-{i}",
        "horizon": "event-relative",
        "observed_at": "2026-01-03T00:00:00+00:00",
        "realized_state": {"linked": linked},
        "source_refs": ["cio_outcomes.jsonl"],
    }


def test_learning_outcomes_carry_every_rendered_key(root):
    _write(root, "data/cio/outcome_observations.jsonl", _lines([_outcome(1), _outcome(2, linked=False)]))
    body = _get("learning")
    assert body["data_quality"] == "AVAILABLE"
    rows = {r["item_id"]: r for r in body["data"]["items"]}
    assert set(rows) == {"o-1", "o-2"}
    for row in rows.values():
        assert LEARNING_KEYS <= set(row), set(row)
        assert row["kind"] == "outcome"
        assert row["decision_id"].startswith("d-"), "source fields are kept"
    assert rows["o-1"]["status"] == "LINKED" and rows["o-2"]["status"] == "UNLINKED"
    assert rows["o-1"]["proof_refs"] == ["cio_outcomes.jsonl"]
    assert rows["o-1"]["score"] is None, "no score is invented"


def test_learning_row_that_already_has_the_contract_keys_is_untouched(root):
    row = {"item_id": "x", "kind": "lesson", "status": "OPEN", "score": 0.5, "evidence_class": "UNIT",
           "proof_refs": [], "limiting_factor": "n", "next_proof": "m"}
    _write(root, "data/runtime/learning_evidence.json", json.dumps({"items": [row]}))
    (got,) = _get("learning")["data"]["items"]
    assert got == row


# ── audit ───────────────────────────────────────────────────────────────────────────────────────────────────────

CLAIM_KEYS = {"claim_id", "claim", "implementation_ref", "test_ref", "evidence_ref", "evidence_class",
              "limitations", "reproduction_command"}


def _office_audit(failed: int) -> dict:
    return {
        "audited_at": "2026-01-04T00:00:00Z",
        "target": "http://127.0.0.1:7777/v3/cio",
        "viewports": 2,
        "failed": failed,
        "results": [
            {"viewport": "desktop", "width": 1440, "ok": True, "issues": [], "sections": [{"section": "A", "ok": True}]},
            {"viewport": "narrow", "width": 390, "ok": failed == 0, "issues": ["overflow"] if failed else [],
             "sections": [{"section": "A", "ok": failed == 0}]},
        ],
    }


def test_office_audit_run_is_served_as_capability_claims(root):
    _write(root, "data/runtime/cc_v3_cio_office_audit.json", json.dumps(_office_audit(failed=1)))
    body = _get("audit")
    assert body["data_quality"] == "AVAILABLE"
    rows = body["data"]["items"]
    assert len(rows) == 2, "one claim per audited viewport"
    for row in rows:
        assert CLAIM_KEYS <= set(row), set(row)
        assert row["implementation_ref"] == "scripts/cc_v3_cio_office_audit.py"
        assert row["evidence_ref"] == "data/runtime/cc_v3_cio_office_audit.json"
        assert "2026-01-04T00:00:00Z" in row["limitations"], "the audit date is never hidden"
        assert row["section"] == "runtime"
    narrow = next(r for r in rows if "narrow" in r["claim_id"])
    assert narrow["status"] == "FAILED" and "overflow" in narrow["limitations"]


def test_a_real_claims_store_wins_over_the_office_audit(root):
    claim = {k: k for k in CLAIM_KEYS}
    _write(root, "data/runtime/audit_capability_claims.json", json.dumps({"items": [claim]}))
    _write(root, "data/runtime/cc_v3_cio_office_audit.json", json.dumps(_office_audit(failed=0)))
    assert _get("audit")["data"]["items"] == [claim]


# ── system ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_system_runtime_state_says_what_this_process_knows(root):
    (root / "data").mkdir()
    runtime = _get("system")["data"]["runtime"]
    assert runtime["state"] == "SERVING", "this process answered the GET; that much is known"
    assert runtime["state"] not in {"LIVE", "LIVE_EVENT_DRIVEN", "LIVE_SCHEDULED"}
    assert runtime["persistent_state"] == "PRESENT"
    assert runtime["state_root"] == str(root)


def test_system_reports_a_missing_state_root(root):
    body = _get("system")
    assert body["data"]["runtime"]["persistent_state"] == "MISSING"
    assert body["data_quality"] == "UNAVAILABLE", "an empty root must never back a LIVE banner"


def test_system_with_a_state_root_is_available(root):
    (root / "data").mkdir()
    assert _get("system")["data_quality"] == "AVAILABLE"


def test_system_surface_is_backed_by_the_system_domain():
    from scripts.lib import whole_site_truth as wst

    assert wst.CONTROL_PLANE_SURFACES["/v3/control-plane/system"]["domain"] == "system"
    assert wst.CONTROL_PLANE_SURFACES["/v3/control-plane"]["domain"] is None


# ── renderer ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_r24_renderer_never_prints_the_word_undefined():
    src = (ROOT / "apps/command-center-v3/src/pages/control-plane/r24/controlPlaneChrome.tsx").read_text()
    fn = src[src.index("export function renderField") :]
    fn = fn[: fn.index("\n}\n")]
    assert "'undefined'" not in fn and "'absent'" in fn
