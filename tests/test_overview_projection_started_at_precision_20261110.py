"""LQ-20261107-1795: an overview-projection run that starts in the same second as its executor attempt grades ``produced``.

The lane stamped its receipt ``started_at`` with ``strftime("%Y-%m-%dT%H:%M:%SZ")``, truncated to the second. The
executor's attempt start carries microseconds, so the receipt started "before" its own attempt
(``receipt_outside_attempt_window``) on nearly every run: RUN_FAILED output_unverifiable x3, then the breaker
paused the lane on its first live hour (2026-11-10 10:50-10:52 ET).

Synthetic: the api_v2 compute is stubbed, the projection goes to tmp_path, the receipt is built by the real
``build_receipt`` and captured instead of written, and the rule is the committed contract's ``expected_output``.
No DB, no state root.
"""

from __future__ import annotations

import fcntl
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

_spec = importlib.util.spec_from_file_location("build_overview_projection_1795",
                                               ROOT / "scripts/build_overview_projection.py")
bop = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bop)

import lib.lane_last_receipt as llr_lib  # noqa: E402 -- the module the builder imports first
import scripts.lib.lane_last_receipt as llr  # noqa: E402
from scripts.lib import n8n_output_verdict as ov  # noqa: E402

LANE = "overview-projection"
RUN_ID = "d:overview-projection:live:20261110T1052"
CODE_SHA = "0" * 40


def _rule() -> dict:
    doc = json.loads((ROOT / "config/n8n_health_contracts.json").read_text())
    contracts = doc.get("contracts", doc)
    rows = contracts.values() if isinstance(contracts, dict) else contracts
    for row in rows:
        if isinstance(row, dict) and LANE in (row.get("target"), row.get("lane_id"), row.get("id")) \
                and row.get("expected_output"):
            return row["expected_output"]
    raise AssertionError("no expected_output for overview-projection in config/n8n_health_contracts.json")


def _mid_second() -> datetime:
    """An attempt start well inside a second, as the executor's always is (15:52:01.424 in the incident)."""
    while not 200_000 <= datetime.now(timezone.utc).microsecond <= 700_000:
        time.sleep(0.01)
    return datetime.now(timezone.utc)


@pytest.fixture
def receipts(monkeypatch):
    captured: list[dict] = []

    def fake_write(lane_id, **kw):
        captured.append(llr.build_receipt(lane_id, **kw))
        return None

    # what the executor exports to the lane; build_receipt stamps run_id / attempt / run_mode / code_sha from it
    monkeypatch.setenv(llr.RUN_ID_ENV, RUN_ID)
    monkeypatch.setenv(llr.RUN_ATTEMPT_ENV, "1")
    monkeypatch.setenv(llr.RUN_MODE_ENV, "live")
    monkeypatch.setenv(llr.CODE_SHA_ENV, CODE_SHA)

    for mod in (llr, llr_lib):
        monkeypatch.setattr(mod, "write_lane_receipt", fake_write)
    monkeypatch.setattr(bop, "_compute", lambda: ({"ok": True, "synthetic": 1},
                                                  {"identity": "sha:synthetic", "state_dir": None}))
    return captured


def _attempt(tmp_path, receipts) -> tuple[dict, str, str]:
    lower = _mid_second()
    bop._write_receipt(bop.run(path=tmp_path / "overview_projection.json"))
    upper = datetime.now(timezone.utc)
    return receipts[-1], lower.isoformat(), upper.isoformat()


def test_a_run_started_in_the_attempts_second_grades_produced(tmp_path, receipts):
    doc, lower, upper = _attempt(tmp_path, receipts)
    assert doc["status"] == "ok" and doc["produced_count"] == 1
    v = ov.evaluate(_rule(), doc, run_id=RUN_ID, lane_id=LANE, mode="live", attempt=1,
                    code_sha=CODE_SHA, started_at=lower, finished_at=upper)
    assert v["verdict"] == "produced", v


def test_the_receipt_start_is_not_earlier_than_the_attempt(tmp_path, receipts):
    doc, lower, _ = _attempt(tmp_path, receipts)
    started = datetime.fromisoformat(doc["started_at"].replace("Z", "+00:00"))
    assert started >= datetime.fromisoformat(lower), (doc["started_at"], lower)
    assert started.tzinfo is not None and started.utcoffset().total_seconds() == 0


def test_a_failed_build_also_stamps_a_start_inside_the_attempt(tmp_path, receipts, monkeypatch):
    def boom():
        raise RuntimeError("synthetic compute failure")

    monkeypatch.setattr(bop, "_compute", boom)
    doc, lower, _ = _attempt(tmp_path, receipts)
    assert doc["status"] == "failed"
    assert datetime.fromisoformat(doc["started_at"].replace("Z", "+00:00")) >= datetime.fromisoformat(lower)


def test_a_refused_overlapping_tick_stamps_a_start_inside_the_attempt(tmp_path, receipts):
    """build_in_flight: op.build returns before stamping, so the lane's own ``started`` is the receipt start."""
    path = tmp_path / "overview_projection.json"
    with open(bop.op.lock_path(path), "a+") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        lower = _mid_second()
        bop._write_receipt(bop.run(path=path))
        upper = datetime.now(timezone.utc)
    doc = receipts[-1]
    assert doc["empty_reason"] == "build_in_flight" and doc["produced_count"] == 0
    v = ov.evaluate(_rule(), doc, run_id=RUN_ID, lane_id=LANE, mode="live", attempt=1, code_sha=CODE_SHA,
                    started_at=lower.isoformat(), finished_at=upper.isoformat())
    assert v["verdict"] == "empty_allowed", v
