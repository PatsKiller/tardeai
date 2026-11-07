"""LQ-109: the gate measurements live in persistent state, not in the release tree the cron runs from."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts import cio_gate_measurement_bridge as bridge  # noqa: E402
from scripts.agent_runtime import gate_status as gs  # noqa: E402
from scripts.lib import canonical_store_registry as csr  # noqa: E402


def _world(tmp_path, monkeypatch):
    releases = tmp_path / "releases"
    release = releases / "abc1234-main-exact-1"
    (release / "data" / "cio").mkdir(parents=True)
    state = tmp_path / "state"
    (state / "data" / "cio").mkdir(parents=True)
    import lib.canonical_store_registry as csr_flat  # the ROOT/scripts import path loads a second module object

    for mod in (csr, csr_flat):
        monkeypatch.setattr(mod, "_release_tree", lambda: releases)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    return release, state


def test_bridge_writes_the_measurements_to_persistent_state(tmp_path, monkeypatch):
    release, state = _world(tmp_path, monkeypatch)
    monkeypatch.setattr(bridge, "PROJECT_ROOT", release)
    args = argparse.Namespace(agent="alex", root=None, json=True, write_measurements="", update_catalog=False)
    assert bridge._run(args) == 0
    assert (state / "data" / "cio" / "agent_gate_measurements.json").is_file()
    assert not (release / "data" / "cio" / "agent_gate_measurements.json").exists()


def test_reader_follows_a_release_root_to_persistent_state(tmp_path, monkeypatch):
    release, state = _world(tmp_path, monkeypatch)
    assert gs.measurements_path(release) == state / "data" / "cio" / "agent_gate_measurements.json"
    assert gs.measurements_path(None) == gs.measurements_path(release)
    dev = tmp_path / "dev"
    assert gs.measurements_path(dev) == dev / "data" / "cio" / "agent_gate_measurements.json"
    doc = {"schema": "AgentGateMeasurement@v1", "measured_at": "2026-11-07T15:00:00+00:00",
           "agents": {"alex": {"gates": {"g1": {"status": "FAIL"}}}}}
    (state / "data" / "cio" / "agent_gate_measurements.json").write_text(json.dumps(doc))
    out = gs.gate_status(release, "alex")
    assert out["failing"] == 1 and out["source"].startswith(str(state))
