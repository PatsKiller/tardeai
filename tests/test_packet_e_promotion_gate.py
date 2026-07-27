"""Packet E Phase 10 promotion gate: prepare-only, never OPERATIONAL."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MOD_PATH = ROOT / "scripts" / "operator_packets" / "packet_e_promotion_gate.py"
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location("packet_e_gate", MOD_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _lab_counts(tmp_path: Path, **overrides):
    body = {
        "reviews": 120,
        "self_review": 0,
        "kb_lessons_candidate": 20,
        "agents_marked_operational": 0,
        "read_only_api": True,
        "accepted_thresholds": True,
    }
    body.update(overrides)
    p = tmp_path / "lab_counts.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def _packet_d_report(tmp_path: Path, **metric_overrides):
    metrics = {
        "reviewer_independence": 1.0,
        "scorer_independence": 1.0,
        "agents_marked_operational": 0,
        "candidate_lessons": 20,
        "persisted": {"reviews": 120, "kb_lessons": 20, "kb_cases": 20, "kb_chunks": 20},
    }
    metrics.update(metric_overrides)
    body = {
        "accepted_thresholds": True,
        "metrics": metrics,
        "persisted": metrics.get("persisted"),
        "threshold_failures": [],
    }
    p = tmp_path / "packet_d.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def test_default_disabled_no_action_exits_prepare_only():
    rc = mod.main([])
    assert rc == 3


def test_missing_ack_refuses():
    rc = mod.main(["--preflight", "--agent-id", "sentinel"])
    assert rc == 2


def test_wrong_ack_refuses():
    rc = mod.main([
        "--preflight", "--agent-id", "sentinel",
        "--ack", "WRONG-TOKEN",
    ])
    assert rc == 2


def test_missing_agent_id_refuses():
    rc = mod.main([
        "--preflight",
        "--ack", mod.ACK_TOKEN,
    ])
    assert rc == 2


def test_self_check_ok():
    rc = mod.main(["--self-check"])
    assert rc == 0
    out = mod.self_check()
    assert out["self_check"] == "OK"
    assert out["agents_marked_operational"] == 0


def test_preflight_passes_with_evidence(tmp_path):
    pd = _packet_d_report(tmp_path)
    lab = _lab_counts(tmp_path)
    result = mod.run_preflight(
        ["sentinel", "darwin"],
        packet_d_report=pd,
        lab_counts_path=lab,
    )
    assert result["ok"] is True
    assert result["invariants"]["agents_marked_operational"] == 0
    assert result["evidence"]["reviews"] > 0
    assert result["evidence"]["self_review"] == 0
    assert result["evidence"]["kb_lessons_candidate"] > 0
    assert result["evidence"]["read_only_api"] is True


def test_preflight_fails_when_reviews_zero(tmp_path):
    lab = _lab_counts(tmp_path, reviews=0)
    with pytest.raises(mod.PreflightFailed, match="reviews"):
        mod.run_preflight(["sentinel"], lab_counts_path=lab)


def test_preflight_fails_on_self_review(tmp_path):
    lab = _lab_counts(tmp_path, self_review=2)
    with pytest.raises(mod.PreflightFailed, match="self_review"):
        mod.run_preflight(["iris"], lab_counts_path=lab)


def test_preflight_fails_without_kb_candidate(tmp_path):
    lab = _lab_counts(tmp_path, kb_lessons_candidate=0)
    with pytest.raises(mod.PreflightFailed, match="kb_candidate"):
        mod.run_preflight(["reflection"], lab_counts_path=lab)


def test_execute_refuses_without_write_intent_and_never_operational(tmp_path, capsys):
    pd = _packet_d_report(tmp_path)
    lab = _lab_counts(tmp_path)
    rc = mod.main([
        "--execute",
        "--agent-id", "sentinel",
        "--ack", mod.ACK_TOKEN,
        "--packet-d-report", str(pd),
        "--lab-counts", str(lab),
    ])
    assert rc == 2  # Phase 11 refusal
    # Catalog unchanged
    catalog = json.loads((ROOT / "config" / "agent_runtime_mvl.json").read_text())
    for entry in (catalog.get("agents") or {}).values():
        if isinstance(entry, dict):
            assert entry.get("deployment_state") != "OPERATIONAL"


def test_execute_write_intent_never_sets_operational(tmp_path):
    pd = _packet_d_report(tmp_path)
    lab = _lab_counts(tmp_path)
    intent_dir = tmp_path / "intents"
    out = mod.run_execute(
        ["sentinel", "darwin"],
        packet_d_report=pd,
        lab_counts_path=lab,
        write_intent=True,
        intent_dir=intent_dir,
    )
    assert out["agents_marked_operational"] == 0
    assert out["operational_mutation"] is False
    assert mod.PHASE11_REFUSAL in out["message"]
    files = list(intent_dir.glob("INTENT_*.json"))
    assert len(files) == 1
    body = json.loads(files[0].read_text(encoding="utf-8"))
    assert body["agents_marked_operational"] == 0
    assert body["not_operational"] is True
    assert body["phase11_required"] is True
    assert body.get("kind") == "PROMOTION_INTENT_ONLY"
    # No catalog mutation
    catalog = json.loads((ROOT / "config" / "agent_runtime_mvl.json").read_text())
    for aid in ("sentinel", "darwin", "iris", "reflection"):
        entry = (catalog.get("agents") or {}).get(aid) or {}
        assert entry.get("deployment_state") != "OPERATIONAL"


def test_cli_execute_write_intent_exit_0(tmp_path):
    pd = _packet_d_report(tmp_path)
    lab = _lab_counts(tmp_path)
    intent_dir = tmp_path / "intents"
    rc = mod.main([
        "--execute",
        "--write-intent",
        "--agent-id", "sentinel",
        "--ack", mod.ACK_TOKEN,
        "--packet-d-report", str(pd),
        "--lab-counts", str(lab),
        "--intent-dir", str(intent_dir),
    ])
    assert rc == 0
    assert list(intent_dir.glob("INTENT_*.json"))


def test_shell_wrapper_default_disabled():
    import subprocess
    sh = ROOT / "scripts" / "operator_packets" / "packet_e_promotion_gate.sh"
    assert sh.is_file()
    proc = subprocess.run(
        ["bash", str(sh)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 2
    assert "PREPARE-ONLY" in (proc.stdout + proc.stderr)
    assert "OPERATIONAL" in (proc.stdout + proc.stderr)


def test_shell_wrapper_self_check():
    import subprocess
    sh = ROOT / "scripts" / "operator_packets" / "packet_e_promotion_gate.sh"
    py = ROOT / ".venv" / "bin" / "python"
    env = {"VENV_PYTHON": str(py) if py.is_file() else "python3"}
    proc = subprocess.run(
        ["bash", str(sh), "--self-check"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env={**dict(**__import__("os").environ), **env},
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "self_check" in proc.stdout
