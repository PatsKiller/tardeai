"""Memory retrieval receipts name the agent, wake, trace and decision a caller knew.

2026-10-03: aif_memory_retrievals.jsonl had 186,311 rows and none named an agent,
so /v3/agents showed memory retrieval NOT_EXPOSED for every agent. Operator
approved additive attribution: recorded only when the caller genuinely holds
the identity, never inferred, never backfilled.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import intelligence_client as ic  # noqa: E402  (the memory façade; no silo imports here)
from scripts.lib.memory_retrieval_attribution import clean, current, retrieval_attribution  # noqa: E402

LEGACY_KEYS = {"at", "query", "symbols", "memory_ids", "retrieval_status", "behavior_mode", "memory_behavior_influence"}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "registry.json"))


def _retrievals_path(root: Path) -> Path:
    return root / "data" / "cio" / "aif_memory_retrievals.jsonl"


def _receipts(root: Path) -> list[dict]:
    path = _retrievals_path(root)
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _facts(root: Path, actor: dict) -> None:
    """One facts read through the façade's default loaders: the real durable provider under ``root``."""
    loaders = ic.default_loaders(root)
    ic.open_context(actor, "RESEARCH", ["SCHD"], classes=["facts"], loaders=loaders, root=root, write_receipt=False)


def test_unattributed_retrieval_keeps_the_legacy_receipt_shape(tmp_path):
    _facts(tmp_path, {"lane_id": "advisory-desk-opinion"})
    rows = _receipts(tmp_path)
    assert rows, "the façade's facts read must write a retrieval receipt"
    assert set(rows[-1]) == LEGACY_KEYS, "a lane is not an agent; no identity is invented"


def test_declared_identities_are_stamped_and_only_those(tmp_path):
    _facts(tmp_path, {"lane_id": "persistent-wake", "agent_id": "maria", "wake_id": "wake_m", "trace_id": None,
                      "decision_id": ""})
    _facts(tmp_path, {"lane_id": "persistent-wake"})
    first, second = _receipts(tmp_path)
    assert first["agent_id"] == "maria" and first["wake_id"] == "wake_m"
    assert "trace_id" not in first and "decision_id" not in first
    assert set(second) == LEGACY_KEYS, "attribution must not leak past its block"
    assert current() == {}


def test_clean_drops_blank_placeholder_and_unknown_fields():
    assert clean({"agent_id": " none ", "wake_id": "None", "trace_id": "  ", "lane_id": "x", "decision_id": "dec_1"}) == {
        "decision_id": "dec_1"}


def test_attribution_is_one_variable_across_both_import_spellings():
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    import memory_retrieval_attribution as bare  # noqa: PLC0415
    from scripts.lib import memory_retrieval_attribution as canonical  # noqa: PLC0415

    with bare.retrieval_attribution(agent_id="hermes"):
        assert canonical.current() == {"agent_id": "hermes"}


class _RecordingProvider:
    """Stands in for the durable provider: records the attribution active when search runs."""

    name = "recording"

    def __init__(self) -> None:
        self.seen: list[dict] = []

    def health(self) -> dict:
        return {"status": "OK"}

    def search(self, **_kw) -> dict:
        self.seen.append(current())
        return {"records": [], "memory_ids": [], "retrieval_status": "EMPTY"}


def test_context_envelope_attributes_its_agent_wake_trace_and_decision():
    from scripts.lib.agent_context_envelope import get_context_for_agent

    prov = _RecordingProvider()
    get_context_for_agent(agent="alex", wake={"wake_id": "wake_9", "trace_id": "tr_9"},
                          decision={"decision_id": "dec_9"}, symbols=None, memory_provider=prov)
    assert prov.seen == [{"agent_id": "alex", "wake_id": "wake_9", "trace_id": "tr_9", "decision_id": "dec_9"}]
    assert current() == {}


def test_shadow_open_passes_the_wake_it_was_given(tmp_path, monkeypatch):
    seen: list[dict] = []
    real = ic.open_context

    def spy(actor, *a, **k):
        seen.append(dict(actor))
        return real(actor, *a, **k)

    monkeypatch.setattr(ic, "open_context", spy)
    ic.shadow_open("persistent-wake", ["SCHD"], "DECIDE", agent_id="maria", wake_id="wake_p", root=tmp_path)
    assert seen and seen[0]["agent_id"] == "maria" and seen[0]["wake_id"] == "wake_p"
    assert "trace_id" not in seen[0] and "decision_id" not in seen[0]


def _write_retrievals(cio: Path, rows: list[dict]) -> None:
    cio.mkdir(parents=True, exist_ok=True)
    (cio / "aif_memory_retrievals.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_agents_proof_lists_each_agents_retrievals_and_counts_the_rest(tmp_path):
    from scripts.lib.cio_cross_surface_links import build_agent_runtime_proof

    cio = tmp_path / "cio"
    _write_retrievals(cio, [
        {"at": "2026-10-03T10:00:00+00:00", "query": "q", "memory_ids": ["m0"]},
        {"at": "2026-10-03T11:00:00+00:00", "query": "q", "memory_ids": ["m1"], "agent_id": "alex", "wake_id": "w1"},
        {"at": "2026-10-03T12:00:00+00:00", "query": "q", "memory_ids": ["m2", "m3"], "agent_id": "Alex", "wake_id": "w2"},
    ])
    proof = build_agent_runtime_proof(cio, agent_ids=["alex", "hermes"])
    alex = proof["agents"]["alex"]["last_memory_retrieval"]
    assert alex["state"] == "RECORDED" and alex["value"] == 2
    assert alex["at"].startswith("2026-10-03T12") and alex["recent_ids"] == ["m2", "m3"] and alex["wake_id"] == "w2"
    assert alex["unattributed_in_window"] == 1
    assert proof["agents"]["hermes"]["last_memory_retrieval"]["state"] == "NOT_RECORDED"


def test_agents_proof_stays_not_exposed_while_no_row_is_attributed(tmp_path):
    from scripts.lib.cio_cross_surface_links import build_agent_runtime_proof

    cio = tmp_path / "cio"
    _write_retrievals(cio, [{"at": "2026-10-03T10:00:00+00:00", "query": "q", "memory_ids": ["m0"]}])
    proof = build_agent_runtime_proof(cio, agent_ids=["alex"])
    assert proof["agents"]["alex"]["last_memory_retrieval"]["state"] == "NOT_EXPOSED"
