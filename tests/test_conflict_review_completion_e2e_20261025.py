"""EXCEPTIONS_MATRIX prerequisite 6, end to end on fixtures: a stance conflict opens, the CIO watch-review worker
completes a review (the producer of the compared input "watchlist CIO review"), the owner hook records the CIO
decision and writes the linkage into that artifact with exact readback, and the next engine run clears the flag.
The durable artifacts are the ledger rows and the rewritten review artifact. Disposable roots; no provider call."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.conflict_resolver import run  # noqa: E402
from scripts.lib.conflicts.adapters import security_inputs  # noqa: E402
from scripts.lib.conflicts.engine import Input  # noqa: E402
from scripts.lib.conflicts.ledger import ConflictLedger  # noqa: E402
from scripts.lib.conflicts.review import complete_from_watch_review  # noqa: E402

NOW = datetime(2026, 10, 23, 19, tzinfo=timezone.utc)
GUID = "fixture-guid-dxcm"
IDENT = {"security_guid": GUID, "identity_status": "CONFIRMED"}


def _bundle(review=None, desk="ADD"):
    card = {"symbol": "DXCM", "security_guid": GUID}
    if review:
        card["cio_review"] = {"verdict": review["verdict"], "completed_at": review["completed_at"],
                              "status": "COMPLETE", "security_guid": GUID}
    return security_inputs(security_guid=GUID, symbol="DXCM", held=False,
                           canonical={"stance": "WATCH", "as_of": NOW.isoformat()}, card=card,
                           extras=[Input("desk", desk, NOW)])


def _engine(root, run_id, at, bundle, monkeypatch):
    monkeypatch.setenv("TRADEAI_RUN_ID", run_id)
    run(root, [bundle], now=at, shadow=True, run_id=run_id, memory_writer=lambda e: True)


def _artifact(tmp_path, verdict="WATCH", status="COMPLETE"):
    path = tmp_path / "artifacts" / "DXCM_cio.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"agent_id": "cio", "status": status, "verdict": verdict,
                                "completed_at": (NOW + timedelta(minutes=20)).isoformat(),
                                "summary": "CIO: desk ADD is not supported; stay WATCH",
                                "execution_authorization_id": "exec-fixture", "input_hash": "h1"}))
    return path


def test_review_completion_writes_the_compared_input_and_the_next_run_clears(tmp_path, monkeypatch):
    _engine(tmp_path, "r1", NOW, _bundle(), monkeypatch)
    _engine(tmp_path, "r2", NOW + timedelta(minutes=15), _bundle(), monkeypatch)
    (key, record), = ConflictLedger(tmp_path).records().items()
    assert record["state"] == "OPEN" and record["kind"] == "CONFLICT"

    path = _artifact(tmp_path)
    at = NOW + timedelta(minutes=25)
    results = complete_from_watch_review(tmp_path, symbol="DXCM", artifact_path=path, now=at,
                                         resolve_identity=lambda s: IDENT, memory_writer=lambda e: True)
    assert results == [{"key": key, "applied": True, "resolution_proven": True, "reason": None}]
    saved = json.loads(path.read_text())
    assert saved["conflict_key"] == key and saved["request_id"] == "exec-fixture"
    assert saved["conflict_resolutions"][key]["verdict"] == "WATCH"
    decided = ConflictLedger(tmp_path).records()[key]
    assert decided["state"] == "DECIDED" and decided["decision"]["actor_kind"] == "cio"

    # The desk producer updates on its own cadence; the review input + the CIO decision now agree -> CLEARED.
    _engine(tmp_path, "r3", NOW + timedelta(minutes=30), _bundle(review=saved, desk="WATCH"), monkeypatch)
    cleared = ConflictLedger(tmp_path).records()[key]
    assert cleared["state"] == "CLEARED"
    assert cleared["decision"]["request_id"] == "exec-fixture"


def test_hook_refuses_unconfirmed_identity_incomplete_review_and_missing_ledger(tmp_path):
    path = _artifact(tmp_path)
    assert complete_from_watch_review(tmp_path, symbol="DXCM", artifact_path=path, now=NOW,
                                      resolve_identity=lambda s: IDENT)[0]["reason"] == "ledger_not_produced"
    assert complete_from_watch_review(tmp_path, symbol="DXCM", artifact_path=path, now=NOW,
                                      resolve_identity=lambda s: {"identity_status": "UNRESOLVED"}
                                      )[0]["reason"] == "identity_unconfirmed"
    failed = _artifact(tmp_path, status="FAILED")
    assert complete_from_watch_review(tmp_path, symbol="DXCM", artifact_path=failed, now=NOW,
                                      resolve_identity=lambda s: IDENT)[0]["reason"] == "review_not_complete"


def test_worker_calls_the_hook_after_a_complete_cio_artifact():
    src = (ROOT / "scripts/run_watch_review_workers.py").read_text()
    write = src.index('base["completed"].append({"symbol": sym, "agent_id": "cio"')
    hook = src.index("complete_from_watch_review(", write)
    assert hook > write and "except Exception" in src[hook:hook + 900]
