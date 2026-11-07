"""Incident fan-in artifact digests: one read per distinct file per run, and none when the walk never sends them.

ANCHOR: N8N_INCIDENT_FANIN_ARTIFACT_DIGEST_20261107 (LQ-20261107-260).

Measured live 2026-11-07: the 5-minute lane ran 124-180 s against a 180 s timeout. The receipt's 264
findings were 144 ``dlq`` findings that all share ``data/governance/n8n_coordination_ledger.sqlite``
(597 MB), and the apply path re-read and re-hashed that file once per finding — 88.5 GB, 101 s. The
gateway calls were 363 gaps under 50 ms; the 144 gaps of 0.7-1.2 s are exactly the 144 DLQ findings.

These tests use synthetic trees only; nothing here reads a real store or a real receipt.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_incident_fanin as fanin  # noqa: E402
from scripts.lib.n8n_gateway_client import walk_to_artifact  # noqa: E402

ANCHOR = "N8N_INCIDENT_FANIN_ARTIFACT_DIGEST_20261107"


def _findings(n: int, artifact_rel: str) -> list[dict]:
    return [
        {
            "source": "dlq",
            "item": f"dlq:synthetic:{i:04d}",
            "severity": "P3",
            "detail": "synthetic dead-letter group",
            "artifact_rel": artifact_rel,
            "store": "persistent-state",
            "detected_at": "2026-11-07T00:00:00+00:00",
        }
        for i in range(n)
    ]


class CountingReads:
    """Counts ``Path.read_bytes`` calls for one path, leaving every other path untouched."""

    def __init__(self, monkeypatch, path: Path):
        self.path = path.resolve()
        self.calls = 0
        real = Path.read_bytes

        def read_bytes(self, *a, **kw):
            if self.resolve() == _counted.path:
                _counted.calls += 1
            return real(self, *a, **kw)

        _counted = self
        monkeypatch.setattr(Path, "read_bytes", read_bytes)


class FakeGateway:
    """Just enough of GatewayClient for ``walk_to_artifact``: a state, and the transitions it accepts."""

    url, has_key = "http://127.0.0.1:0", True

    def __init__(self, state: str):
        self.state = state
        self.transitions: list[tuple[str, dict]] = []

    def status(self, key):
        return {"state": self.state, "durable": True}

    def transition(self, operation, key, **fields):
        self.transitions.append((operation, fields))
        self.state = {"claim": "CLAIMED", "start": "STARTED", "artifact": "ARTIFACT_WRITTEN"}[operation]
        return {"state": self.state, "durable": True}


class FakeClient:
    """The fan-in's own client: every key already sits at ARTIFACT_WRITTEN in the ledger."""

    url, has_key = "http://127.0.0.1:0", True

    def __init__(self, *, caller_id):
        self.status_calls: list[str] = []

    def healthz(self):
        return {"ok": True}

    def status(self, key):
        self.status_calls.append(key)
        return {"state": "ARTIFACT_WRITTEN", "duplicate": False}

    def accept_event(self, ev):  # pragma: no cover - a closed key never needs an accept
        raise AssertionError("accept_event must not be called for a key the ledger already holds")

    def transition(self, operation, key, **fields):  # pragma: no cover - nothing moves
        raise AssertionError("transition must not be called for a key at ARTIFACT_WRITTEN")


def _wire(monkeypatch, tmp_path, findings):
    monkeypatch.setattr(fanin, "state_root", lambda: tmp_path)
    monkeypatch.setattr(fanin, "served_sha", lambda: "b" * 40)
    monkeypatch.setattr(fanin, "_outbox_findings", lambda now: [])
    monkeypatch.setattr(fanin, "collect", lambda root, now, _f=findings: [dict(x) for x in _f])
    monkeypatch.setattr(fanin, "GatewayClient", FakeClient)
    monkeypatch.setattr(fanin, "_write_lane_receipt", lambda *a, **kw: None)
    receipt = tmp_path / "data/runtime/n8n_incident_fanin_last.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    return receipt


def test_a_shared_artifact_is_read_once_per_run(tmp_path, monkeypatch):
    artifact = tmp_path / "data/governance/ledger.sqlite"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"synthetic-ledger" * 1000)
    reads = CountingReads(monkeypatch, artifact)
    digests: dict = {}

    seen = {fanin.sha256_once(artifact, digests) for _ in range(50)}

    assert reads.calls == 1, f"the same file was read {reads.calls} times in one run"
    assert seen == {hashlib.sha256(artifact.read_bytes()).hexdigest()}
    assert len(digests) == 1


def test_a_rewritten_artifact_is_hashed_again(tmp_path, monkeypatch):
    artifact = tmp_path / "artifact.json"
    artifact.write_text("first", encoding="utf-8")
    digests: dict = {}
    first = fanin.sha256_once(artifact, digests)

    artifact.write_text("second", encoding="utf-8")

    assert fanin.sha256_once(artifact, digests) == hashlib.sha256(b"second").hexdigest()
    assert first == hashlib.sha256(b"first").hexdigest()


def test_an_unreadable_artifact_is_not_an_error(tmp_path):
    digests: dict = {}
    missing = tmp_path / "absent.sqlite"

    assert fanin.sha256_once(missing, digests) is None
    assert fanin.sha256_once(missing, digests) is None  # cached as a miss, still no raise


def test_a_closed_key_never_reads_the_artifact(tmp_path, monkeypatch):
    """The regression: 144 already-closed findings must not read the 597 MB ledger even once."""
    artifact = tmp_path / "data/governance/ledger.sqlite"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"x" * 4096)
    reads = CountingReads(monkeypatch, artifact)
    findings = _findings(20, "data/governance/ledger.sqlite")
    receipt = _wire(monkeypatch, tmp_path, findings)

    fanin.main(["--apply", "--receipt", str(receipt)])

    after = json.loads(receipt.read_text())
    assert len(after["incidents"]) == 20
    assert {r["state"] for r in after["incidents"]} == {"ARTIFACT_WRITTEN"}
    assert reads.calls == 0, f"a closed key read the artifact {reads.calls} times"


def test_an_open_key_reads_the_artifact_once_for_many_findings(tmp_path, monkeypatch):
    artifact = tmp_path / "data/governance/ledger.sqlite"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"y" * 4096)
    reads = CountingReads(monkeypatch, artifact)
    findings = _findings(10, "data/governance/ledger.sqlite")

    class AcceptingClient(FakeClient):
        """An empty ledger: the first status refuses, the accept opens the key, the walk then moves it."""

        def __init__(self, *, caller_id):
            super().__init__(caller_id=caller_id)
            self.accepted: set[str] = set()

        def status(self, key):
            self.status_calls.append(key)
            if key in self.accepted:
                return {"state": "ACCEPTED", "duplicate": False}
            return {"state": "REFUSED", "reason": "unknown_event"}

        def accept_event(self, ev):
            self.accepted.add(ev["idempotency_key"])
            return {"state": "ACCEPTED", "duplicate": False}

        def transition(self, operation, key, **fields):
            return {"state": {"claim": "CLAIMED", "start": "STARTED", "artifact": "ARTIFACT_WRITTEN"}[operation]}

    receipt = _wire(monkeypatch, tmp_path, findings)
    monkeypatch.setattr(fanin, "GatewayClient", AcceptingClient)

    fanin.main(["--apply", "--receipt", str(receipt)])

    assert reads.calls == 1, f"10 findings on one artifact read it {reads.calls} times"


def test_walk_to_artifact_resolves_the_ref_only_at_the_artifact_step():
    client = FakeGateway("ACCEPTED")
    resolved: list[int] = []

    def ref():
        resolved.append(1)
        return {"store": "persistent-state", "ref": "x.json", "sha256": "0" * 64, "as_of": "2026-11-07T00:00:00+00:00"}

    walk_to_artifact(client, "inc-x", ref)

    assert [op for op, _ in client.transitions] == ["claim", "start", "artifact"]
    assert len(resolved) == 1
    assert client.transitions[-1][1]["artifact_ref"]["ref"] == "x.json"


def test_walk_to_artifact_ignores_the_ref_for_a_closed_key():
    client = FakeGateway("ARTIFACT_WRITTEN")
    resolved: list[int] = []

    def ref():  # pragma: no cover - must never run
        resolved.append(1)
        raise AssertionError("the ref was built for a key that is already closed")

    walk_to_artifact(client, "inc-x", ref)

    assert resolved == []
    assert client.transitions == []


def test_walk_to_artifact_still_accepts_a_plain_mapping():
    client = FakeGateway("STARTED")

    walk_to_artifact(client, "inc-x", {"store": "persistent-state", "ref": "m.json", "as_of": "2026-11-07T00:00:00+00:00"})

    assert client.transitions == [
        ("artifact", {"artifact_ref": {"store": "persistent-state", "ref": "m.json", "as_of": "2026-11-07T00:00:00+00:00"}})
    ]
