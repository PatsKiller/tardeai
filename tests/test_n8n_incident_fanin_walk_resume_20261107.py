"""ANCHOR: N8N_INCIDENT_FANIN_WALK_RESUME_20261107 — the occurrence walk resumes where the last receipt stopped.

LQ-20261107-209. LQ-116 (2026-11-07) made a finding that returns after its own closure open the next occurrence
key (``-r1``, ``-r2``, ...), found by walking ``status`` from the day key upward on every run. That afternoon the
DLQ-recovery source flipped every tick, so 100 dead-letter groups were closed and reopened until they reached
``-r6``. From then on each run spent ``occurrence + 1`` status calls per finding (~880 per run). The 5-minute
lane went from ~40 s to ~110-180 s and hit its 180 s timeout, and a timed-out run writes no receipt.

Pinned here:
- a finding whose previous row is at ``-rN`` costs one status call, not N + 1, and keeps the same key;
- the resumed key is the key the full walk finds (keys below N are CONSUMED, which is terminal);
- a resumed key that has since been closed by recovery walks on to N + 1;
- an operator ack at the resumed key is still reported, never stepped over;
- a previous receipt from another UTC day, or a malformed row, resumes nothing.

Synthetic fixtures only; the in-memory gateway is the LQ-116 one (CONSUMED terminal).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_incident_fanin as fanin  # noqa: E402
from tests.test_n8n_incident_fanin_reopen_20261107 import FakeGateway, _close, _first, _wire  # noqa: E402


def _ladder(gw, receipt, rungs):
    """Open the finding, then close-and-return it ``rungs`` times; returns the base key."""
    base = _first(gw, receipt)["idempotency_key"]
    for n in range(1, rungs + 1):
        _close(gw, fanin.occurrence_key(base, n - 1))
        assert _first(gw, receipt)["idempotency_key"] == fanin.occurrence_key(base, n)
    return base


def test_a_reopened_finding_costs_one_status_call_and_keeps_its_key(monkeypatch, tmp_path):
    gw = FakeGateway(caller_id="x")
    receipt = _wire(monkeypatch, tmp_path, gw)
    base = _ladder(gw, receipt, 6)

    gw.status_calls.clear()
    row = _first(gw, receipt)
    assert row["idempotency_key"] == f"{base}-r6" and row["occurrence"] == 6
    assert row["state"] == "ARTIFACT_WRITTEN"
    assert gw.status_calls == [f"{base}-r6"]  # was r0..r6: seven calls


def test_the_resumed_key_is_the_key_the_full_walk_finds(monkeypatch, tmp_path):
    gw = FakeGateway(caller_id="x")
    receipt = _wire(monkeypatch, tmp_path, gw)
    base = _ladder(gw, receipt, 4)
    resumed = _first(gw, receipt)

    receipt.unlink()  # no previous receipt: the walk starts at the day key, as before this change
    gw.status_calls.clear()
    full = _first(gw, receipt)
    assert full["idempotency_key"] == resumed["idempotency_key"] == f"{base}-r4"
    assert gw.status_calls == [fanin.occurrence_key(base, n) for n in range(5)]


def test_a_resumed_key_closed_since_walks_on(monkeypatch, tmp_path):
    gw = FakeGateway(caller_id="x")
    receipt = _wire(monkeypatch, tmp_path, gw)
    base = _ladder(gw, receipt, 2)
    _close(gw, f"{base}-r2")  # closed after the receipt was written; the finding is back

    gw.status_calls.clear()
    row = _first(gw, receipt)
    assert row["idempotency_key"] == f"{base}-r3" and row["state"] == "ARTIFACT_WRITTEN"
    assert gw.status_calls == [f"{base}-r2", f"{base}-r3"]


def test_an_operator_ack_at_the_resumed_key_is_reported_not_stepped_over(monkeypatch, tmp_path):
    gw = FakeGateway(caller_id="x")
    receipt = _wire(monkeypatch, tmp_path, gw)
    base = _ladder(gw, receipt, 3)
    _close(gw, f"{base}-r3", consumer="operator")
    accepted = list(gw.accepted)

    row = _first(gw, receipt)
    assert row["idempotency_key"] == f"{base}-r3" and row["state"] == "CONSUMED"
    assert gw.accepted == accepted


def test_another_day_or_a_malformed_row_resumes_nothing():
    prev = {"incidents": [
        {"idempotency_key": "inc-aaa-r3", "occurrence": 3},
        {"idempotency_key": "inc-bbb-r2", "occurrence": 5},  # suffix and occurrence disagree
        {"idempotency_key": "inc-ccc-r1", "occurrence": True},
        {"idempotency_key": "inc-ddd-r2", "occurrence": "2"},
        {"idempotency_key": "inc-eee", "occurrence": 0},
        {"idempotency_key": None, "occurrence": 4},
        {"idempotency_key": f"inc-fff-r{fanin.MAX_OCCURRENCES + 5}", "occurrence": fanin.MAX_OCCURRENCES + 5},
    ]}
    assert fanin._resume_occurrences(prev) == {"inc-aaa": 3, "inc-fff": fanin.MAX_OCCURRENCES}
    assert fanin._resume_occurrences({}) == {} and fanin._resume_occurrences(None) == {}
    # The day is part of the base key: yesterday's ``-r3`` never matches today's finding.
    f = {"source": "dlq", "item": "dlq:recovery:x"}
    assert fanin.idem_key(f, "2026-11-06") != fanin.idem_key(f, "2026-11-07")


def test_a_dry_run_never_resumes(monkeypatch, tmp_path):
    gw = FakeGateway(caller_id="x")
    receipt = _wire(monkeypatch, tmp_path, gw)
    _ladder(gw, receipt, 2)
    assert fanin.main(["--dry-run", "--receipt", str(receipt)]) == 0
    doc = json.loads(receipt.read_text()) if receipt.exists() else {}
    for row in doc.get("incidents") or []:
        if row.get("state") == "DRY_RUN":
            assert "occurrence" not in row
