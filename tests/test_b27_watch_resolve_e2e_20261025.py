"""Batch 27: Watch "Resolve conflict" works end to end on fixtures (AGENTS.md 28.10, watch-resolve-conflict-fix.md).

The operator's complaint (2026-10-24, phone): "Resolve still does nothing" and "a note on what the actual issue is".
This proves the whole backend path with disposable roots and fake sinks only:

  engine run (shadow, fixture inputs) -> ledger OPEN record -> Watch row carries the engine section (headline, rule)
  -> /api/v3/conflicts/{key} through the real api_v2 dispatcher -> CIO review completion writes ConflictDecision@v1
  -> DECIDED still flags -> next engine run with the recorded CIO decision -> CLEARED, the Watch line disappears
  -> the selected record still shows who decided, what and why.

No broker, model, notification, scheduler or production state is touched. The decision POST stays refused
until the operator activates the writer, and an agent caller is refused before that check.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.conflict_resolver import run  # noqa: E402
from scripts.lib.conflicts.adapters import security_inputs  # noqa: E402
from scripts.lib.conflicts.engine import Input  # noqa: E402
from scripts.lib.conflicts.ledger import ConflictLedger  # noqa: E402
from scripts.lib.conflicts.review import complete_review  # noqa: E402
from scripts.lib.site_payload_reads import attach_conflict_sections  # noqa: E402

NOW = datetime(2026, 10, 23, 19, tzinfo=timezone.utc)
GUID = "fixture-guid-schd"


def _bundle(canonical="WATCH", desk="ADD"):
    return security_inputs(security_guid=GUID, symbol="SCHD", held=False,
                           canonical={"stance": canonical, "as_of": NOW.isoformat()},
                           extras=[Input("desk", desk, NOW)])


def _shadow(root, run_id, at, bundle, monkeypatch):
    monkeypatch.setenv("TRADEAI_RUN_ID", run_id)
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")
    monkeypatch.setenv("TRADEAI_CODE_SHA", "fixture-sha")
    delivered = []
    report = run(root, [bundle], now=at, shadow=True, run_id=run_id, memory_writer=lambda event: delivered.append(event) or True)
    assert report["notifications"] == 0
    return report, delivered


@pytest.fixture()
def api(monkeypatch, tmp_path):
    import api_v2
    from scripts.lib.conflicts import api as conflicts_api

    monkeypatch.setattr(conflicts_api, "_root", lambda: tmp_path)
    return api_v2


def _watch_row():
    return {"symbol": "SCHD", "security_guid": GUID, "identity_status": "CONFIRMED",
            "next_action": {"kind": "resolve_conflict", "label": "Resolve conflict"}}


def test_resolve_conflict_end_to_end_on_fixtures(tmp_path, monkeypatch, api):
    # 1. Two distinct engine runs open the stance conflict (hysteresis R15: one run is only an observation).
    _shadow(tmp_path, "run-1", NOW, _bundle(), monkeypatch)
    _report, memory = _shadow(tmp_path, "run-2", NOW + timedelta(minutes=15), _bundle(), monkeypatch)
    records = ConflictLedger(tmp_path).records()
    assert len(records) == 1
    key, record = next(iter(records.items()))
    assert record["state"] == "OPEN" and record["kind"] == "CONFLICT" and record["subject"]["id"] == GUID
    assert memory, "the CIO is informed of every conflict state change (AGENTS.md 28.10)"

    # 2. The Watch row carries the engine section: a headline, the finding, its rule and what clears it.
    row = attach_conflict_sections([_watch_row()], root=tmp_path)[0]
    section = row["conflict_section"]
    assert section["headline"] and not section.get("gap")
    finding = section["findings"][0]
    assert finding["key"] == key and finding["rule"] == record["rule"]
    assert finding["clears_when"] and len(finding["sides"]) >= 2
    assert {s["value"] for s in finding["sides"]} >= {"WATCH", "ADD"}

    # 3. The selected record is served by the real api_v2 dispatcher (same envelope the sheet reads).
    url = "/api/v3/conflicts/" + quote(key, safe="")
    status, payload = api.handle(url, "GET")
    assert status == 200 and payload["ok"] is True
    assert payload["data"]["schema"] == "ConflictRecord@v1" and payload["data"]["state"] == "OPEN"
    assert payload["data"]["rule"] == record["rule"] and payload["data"]["history"]
    status, listing = api.handle("/api/v3/conflicts", "GET", query={"subject_id": [GUID]})
    assert status == 200 and listing["data"]["total"] == 1

    # 4. Agents can never decide; the operator writer stays off until the operator activates it.
    status, refused = api.handle(url + "/decision", "POST", body={"expected_revision": record["revision"]})
    assert status in (403, 503) and refused["ok"] is False
    assert ConflictLedger(tmp_path).records()[key]["state"] == "OPEN"

    # 5. The CIO's review completes: decision + superseded input update with exact readback. DECIDED still flags.
    saved = {}
    cio_memory = []
    result = complete_review(
        ConflictLedger(tmp_path, memory_writer=lambda event: cio_memory.append(event) or True), key, request_id="fixture-review",
        canonical={"security_guid": GUID, "stance": "WATCH", "as_of": NOW.isoformat()},
        reason="CIO reviewed the desk ADD against the canonical WATCH", evidence_refs=["cio:thesis:fixture"],
        producer_update=lambda patch: saved.update(patch) or True, producer_readback=lambda: saved,
        at=NOW + timedelta(minutes=20), expires_at=NOW + timedelta(days=7), apply=True)
    assert result["resolution_proven"] and result["cleared"] is False
    decided = ConflictLedger(tmp_path).records()[key]
    assert decided["state"] == "DECIDED" and decided["decision"]["actor_kind"] == "cio"
    assert cio_memory, "the decision is written to CIO memory"
    assert attach_conflict_sections([_watch_row()], root=tmp_path)[0]["conflict_section"]["headline"]

    # 6. The next engine run sees the updated input (desk now agrees) and the recorded CIO decision -> CLEARED.
    _shadow(tmp_path, "run-3", NOW + timedelta(minutes=30), _bundle(desk="WATCH"), monkeypatch)
    cleared = ConflictLedger(tmp_path).records()[key]
    assert cleared["state"] == "CLEARED"
    assert cleared["decision"]["chosen_side"] == "WATCH" and cleared["decision"]["request_id"] == "fixture-review"

    # 7. Watch no longer shows the line; the record still says who decided what and why.
    after = attach_conflict_sections([_watch_row()], root=tmp_path)[0]["conflict_section"]
    assert after["headline"] is None and after["findings"] == []
    status, payload = api.handle(url, "GET")
    assert status == 200 and payload["data"]["state"] == "CLEARED"
    assert payload["data"]["decision"]["reason"].startswith("CIO reviewed")
    assert [e["event"] for e in payload["data"]["history"]][-1] == "cleared"


def test_missing_ledger_keeps_the_gap_fallback(tmp_path):
    """Before the shadow lane has produced anything the row says why; the transition flags stay (AGENTS.md 28.11)."""
    section = attach_conflict_sections([_watch_row()], root=tmp_path)[0]["conflict_section"]
    assert section["headline"] is None and section["gap"]["reason"] == "conflict ledger not yet produced"
