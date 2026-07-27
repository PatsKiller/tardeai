"""Packet D persists SHADOW acceptance evidence via agent_runtime persistence APIs."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MOD_PATH = ROOT / "scripts" / "operator_packets" / "packet_d_shadow_acceptance.py"
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location("packet_d_persist", MOD_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _stub(n_good: int = 100, n_bad: int = 20):
    def _src():
        rows = []
        for i in range(n_good):
            rows.append({
                "artifact_id": f"good-{i}",
                "symbol": f"G{i}",
                "producer_agent_id": mod.PRODUCER_AGENT_ID,
                "is_known_bad": False,
            })
        for i in range(n_bad):
            rows.append({
                "artifact_id": f"bad-{i}",
                "symbol": f"B{i}",
                "producer_agent_id": mod.PRODUCER_AGENT_ID,
                "is_known_bad": True,
            })
        return rows
    return _src


def test_persist_with_inmemory_store():
    from agent_runtime.persistence import InMemoryPersistence

    store = InMemoryPersistence()
    dsn = "postgresql://agentic_runtime_shadow_rw:pw@127.0.0.1:5433/trade_ai_agentic_lab"
    report = mod.run_shadow(dsn, source=_stub(100, 20), store=store, persist=True)
    assert report.agents_marked_operational == 0
    assert report.persisted.get("runs") == 1
    assert report.persisted.get("artifacts") == 120
    assert report.persisted.get("reviews") == 120
    assert report.persisted.get("scores") == 120
    assert report.run_id.startswith("shadow-d-")
    ok, fails = report.evaluate()
    assert ok, fails
    # reconstruct proves durable journal/control
    state = store.reconstruct(report.run_id)
    assert len(state.artifacts) == 120
    assert len(state.reviews) == 120
    assert len(state.scores) == 120


def test_persist_skipped_when_persist_false():
    dsn = "postgresql://agentic_runtime_shadow_rw:pw@127.0.0.1:5433/trade_ai_agentic_lab"
    report = mod.run_shadow(dsn, source=_stub(100, 20), persist=False)
    assert report.persisted.get("artifacts", 0) == 0
    ok, _ = report.evaluate()
    assert ok


def test_prod_dsn_still_refused_before_persist():
    from agent_runtime.persistence import InMemoryPersistence
    with pytest.raises(mod.ShadowGuardError):
        mod.run_shadow(
            "postgresql://agentic_runtime_shadow_rw:pw@127.0.0.1:5432/trade_ai",
            source=_stub(5, 2),
            store=InMemoryPersistence(),
        )
