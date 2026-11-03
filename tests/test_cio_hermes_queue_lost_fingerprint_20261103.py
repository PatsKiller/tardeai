"""`requests_lost` must not count a request whose question is already in the projection.

2026-11-03: `res_c30a22ae6af8` (13:56:56Z) was reported lost while `res_cfaa3b471ead`
(13:56:54Z) carried the SAME fingerprint in `by_research_id` as `running`. The restore path
dedups on fingerprint; the health check counted the duplicate as lost and pinned the lane
critical. Hermetic: tmp ledger/projection only.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_hermes_queue_health import collect_cio_hermes_queue_health  # noqa: E402

NOW = datetime(2026, 11, 3, 16, 30, tzinfo=timezone.utc)
FP = "sha256:5876094632ebee8ad3e5d576a0890ffc496af97a7b3a79dcd07173e1d4bc320f"


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv("CIO_HERMES_PROJECTION", raising=False)
    return None


def _ledger(tmp_path, projection, events):
    p = tmp_path / "hermes_research_requests.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    (tmp_path / "hermes_research_projection.json").write_text(json.dumps(projection))
    return p


def _requested(rid, fingerprint, *, minutes_ago=20):
    return {"event": "HERMES_RESEARCH_REQUESTED", "research_id": rid, "fingerprint": fingerprint,
            "ts": (NOW - timedelta(minutes=minutes_ago)).isoformat(), "status": "queued"}


def test_same_fingerprint_open_entry_is_not_lost(tmp_path):
    ledger = _ledger(
        tmp_path,
        {"by_research_id": {"res_open": {"status": "running", "fingerprint": FP}},
         "by_fingerprint_open": {FP: {"research_id": "res_open"}}},
        [_requested("res_dup", FP)],
    )
    row = collect_cio_hermes_queue_health(now=NOW, path=ledger)
    assert row["lost_n"] == 0 and row["lost"] == []
    assert "requests_lost:1" not in row["firing"]
    assert row["ok"] is True


def test_completed_fingerprint_is_not_lost(tmp_path):
    ledger = _ledger(
        tmp_path,
        {"by_research_id": {},
         "by_fingerprint_completed": {FP: {"research_id": "res_done"}}},
        [_requested("res_dup", FP)],
    )
    row = collect_cio_hermes_queue_health(now=NOW, path=ledger)
    assert row["lost_n"] == 0


def test_unowned_fingerprint_is_still_lost(tmp_path):
    ledger = _ledger(tmp_path, {"by_research_id": {}}, [_requested("res_lost", "sha256:deadbeef")])
    row = collect_cio_hermes_queue_health(now=NOW, path=ledger)
    assert row["lost_n"] == 1 and row["lost"] == ["res_lost"]
    assert "requests_lost:1" in row["firing"] and row["ok"] is False


def test_request_in_the_grace_window_is_not_lost(tmp_path):
    ledger = _ledger(tmp_path, {"by_research_id": {}}, [_requested("res_new", "sha256:cafe", minutes_ago=5)])
    row = collect_cio_hermes_queue_health(now=NOW, path=ledger)
    assert row["lost_n"] == 0
