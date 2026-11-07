"""Incident fan-in closure path (LQ-20261107-116, 2026-11-07): a finding that closes and comes back the same
UTC day used to be republished under its old key, which the gateway holds CONSUMED — a terminal state with no
edge out of it. The receipt then said "open" and the ledger said "closed" for the rest of the day, and the
finding could never be closed again (``recovered`` could never name it). Measured live on 2026-11-07: 102 of
the 256 open incidents were already CONSUMED, two of them detected after their own closure.

These tests drive ``main()`` against an in-memory gateway that models the real transition table
(EDGES: ARTIFACT_WRITTEN -> CONSUMED, CONSUMED terminal). Synthetic fixtures only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_incident_fanin as fanin  # noqa: E402

FINDING = {
    "source": "dlq",
    "item": "dlq:recovery:0123456789abcdef",
    "severity": "P3",
    "detail": "synthetic dead-letter group",
    "artifact_rel": "data/governance/n8n_coordination_ledger.sqlite",
    "store": "persistent-state",
    "detected_at": "2026-11-07T00:00:00+00:00",
}


class FakeGateway:
    """The gateway's event table, in memory: unknown keys are refused, CONSUMED is terminal."""

    url, has_key = "http://127.0.0.1:0", True

    def __init__(self, *, caller_id: str):
        self.states: dict[str, dict] = {}
        self.accepted: list[str] = []
        self.acked: list[str] = []
        self.status_calls: list[str] = []

    def healthz(self):
        return {"ok": True}

    def status(self, key):
        self.status_calls.append(key)
        row = self.states.get(key)
        if row is None:
            return {"state": "REFUSED", "reason": "unknown_event"}
        return {**row, "duplicate": False}

    def accept_event(self, ev):
        self.accepted.append(ev["idempotency_key"])
        self.states[ev["idempotency_key"]] = {"state": "ARTIFACT_WRITTEN"}
        return {"state": "ACCEPTED"}

    def transition(self, operation, key, **fields):
        if operation != "consumer_ack":
            return {"state": "REFUSED", "reason": f"unsupported:{operation}"}
        row = self.states.get(key) or {}
        if row.get("state") != "ARTIFACT_WRITTEN":
            return {"state": "REFUSED", "reason": f"illegal_transition:{row.get('state')}->CONSUMED"}
        self.states[key] = {"state": "CONSUMED", "consumer": fields["consumer_receipt"]["consumer"]}
        self.acked.append(key)
        return {"state": "CONSUMED"}


def _wire(monkeypatch, tmp_path, gateway, findings=None):
    monkeypatch.setattr(fanin, "state_root", lambda: tmp_path)
    monkeypatch.setattr(fanin, "served_sha", lambda: "b" * 40)
    monkeypatch.setattr(fanin, "_outbox_findings", lambda now: [])
    monkeypatch.setattr(fanin, "collect", lambda root, now, _f=list(findings or [FINDING]): [dict(x) for x in _f])
    monkeypatch.setattr(fanin, "GatewayClient", lambda *, caller_id: gateway)
    # walk_to_artifact is the gateway's own ladder; the row's state is what these tests are about.
    monkeypatch.setattr(fanin, "walk_to_artifact", lambda client, key, ref: [{"op": "status", "state": "ARTIFACT_WRITTEN"}])
    receipt = tmp_path / "data/runtime/n8n_incident_fanin_last.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    return receipt


def _run(gateway, receipt):
    assert fanin.main(["--apply", "--receipt", str(receipt)]) == 0
    return json.loads(receipt.read_text())


def _close(gateway, key, consumer="recovery-observer"):
    gateway.states[key] = {"state": "CONSUMED", "consumer": consumer}


def _first(gateway, receipt):
    doc = _run(gateway, receipt)
    assert len(doc["incidents"]) == 1
    return doc["incidents"][0]


def test_a_finding_that_returns_after_its_own_closure_opens_the_next_occurrence(monkeypatch, tmp_path):
    """The live defect: the day key is CONSUMED by the earlier occurrence, so it can be neither reopened nor
    closed again. The second occurrence must get ``-r1`` — accepted, open, and closable."""
    gw = FakeGateway(caller_id="x")
    receipt = _wire(monkeypatch, tmp_path, gw)

    first = _first(gw, receipt)
    base = first["idempotency_key"]
    assert first["state"] == "ARTIFACT_WRITTEN" and "occurrence" not in first

    _close(gw, base)  # the finding disappeared: this run's closure
    second = _first(gw, receipt)

    assert second["idempotency_key"] == f"{base}-r1"
    assert second["event_id"] == f"evt-incident-fanin-{base}-r1"
    assert second["state"] == "ARTIFACT_WRITTEN" and second["occurrence"] == 1
    assert gw.accepted == [base, f"{base}-r1"]
    assert base not in gw.acked  # this test closes by fixture, not by the recovery path


def test_the_second_occurrence_is_what_the_recovery_path_closes(monkeypatch, tmp_path):
    """Once the reopened occurrence disappears, the normal diff closes ``-r1`` — the closure the old code could
    never reach, because it had published the finding under a terminal key."""
    gw = FakeGateway(caller_id="x")
    receipt = _wire(monkeypatch, tmp_path, gw)
    first = _first(gw, receipt)
    base = first["idempotency_key"]
    _close(gw, base)
    assert _first(gw, receipt)["idempotency_key"] == f"{base}-r1"

    monkeypatch.setattr(fanin, "collect", lambda root, now: [])
    doc = _run(gw, receipt)
    assert doc["open"] == 0
    assert [r["idempotency_key"] for r in doc["recovered"]] == [f"{base}-r1"]
    assert gw.states[f"{base}-r1"]["state"] == "CONSUMED"


def test_each_return_mints_the_next_key_and_never_reuses_a_closed_one(monkeypatch, tmp_path):
    gw = FakeGateway(caller_id="x")
    receipt = _wire(monkeypatch, tmp_path, gw)
    base = _first(gw, receipt)["idempotency_key"]
    for n in (1, 2):
        _close(gw, base if n == 1 else f"{base}-r{n - 1}")
        assert _first(gw, receipt)["idempotency_key"] == f"{base}-r{n}"


def test_an_operator_ack_is_not_a_recurrence(monkeypatch, tmp_path):
    """A key CONSUMED by anyone other than the recovery observer is a decision to stop reporting today's
    occurrence; the fan-in keeps saying so and does not mint a new key behind the operator's back."""
    gw = FakeGateway(caller_id="x")
    receipt = _wire(monkeypatch, tmp_path, gw)
    base = _first(gw, receipt)["idempotency_key"]
    _close(gw, base, consumer="operator")

    row = _first(gw, receipt)
    assert row["idempotency_key"] == base and row["state"] == "CONSUMED"
    assert "occurrence" not in row
    assert gw.accepted == [base]


def test_the_cap_stops_the_walk_and_reports_what_the_gateway_says(monkeypatch, tmp_path):
    """A flapping source must not mint keys without end: after MAX_OCCURRENCES the row keeps the last key."""
    gw = FakeGateway(caller_id="x")
    receipt = _wire(monkeypatch, tmp_path, gw)
    base = _first(gw, receipt)["idempotency_key"]
    for n in range(0, fanin.MAX_OCCURRENCES + 1):  # every key of the day's ladder is closed
        gw.states[fanin.occurrence_key(base, n)] = {"state": "CONSUMED", "consumer": fanin.RECOVERY_CONSUMER}
    accepted_before = list(gw.accepted)

    row = _first(gw, receipt)
    assert row["idempotency_key"] == fanin.occurrence_key(base, fanin.MAX_OCCURRENCES)
    assert row["occurrence"] == fanin.MAX_OCCURRENCES and row["state"] == "CONSUMED"
    assert gw.accepted == accepted_before  # nothing minted past the cap


def test_occurrence_key_pure():
    assert fanin.occurrence_key("inc-abc", 0) == "inc-abc"
    assert fanin.occurrence_key("inc-abc", 3) == "inc-abc-r3"
