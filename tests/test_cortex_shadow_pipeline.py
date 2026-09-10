"""Phase 8 — AgentView + scoring cortex shadow (flags default OFF)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.cortex_shadow_pipeline import (
    AGENT_VIEW_FLAG,
    CORTEX_SHADOW_FLAG,
    enabled,
    run_cortex_shadow,
)
from scripts.lib.governed_commitment import FEATURE_FLAG as COMMITMENT_FLAG
from scripts import run_cortex_shadow_pipeline as cli


def test_flags_default_off(monkeypatch):
    monkeypatch.delenv(AGENT_VIEW_FLAG, raising=False)
    monkeypatch.delenv(CORTEX_SHADOW_FLAG, raising=False)
    assert enabled() is False


def test_flag_off_noop_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv(AGENT_VIEW_FLAG, raising=False)
    monkeypatch.delenv(CORTEX_SHADOW_FLAG, raising=False)
    r = run_cortex_shadow(
        subject="subj-1",
        summary="Evidence suggests quiet tape",
        citations=["src_1"],
        confidence=0.7,
        state_root=tmp_path,
        dry_run=False,
    )
    assert r.ok and r.disabled and r.outcome == "disabled"
    assert list(tmp_path.iterdir()) == []


def test_flag_on_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv(CORTEX_SHADOW_FLAG, "1")
    monkeypatch.delenv(COMMITMENT_FLAG, raising=False)
    r = run_cortex_shadow(
        subject="subj-1",
        summary="Evidence suggests quiet tape",
        citations=["src_1"],
        confidence=0.7,
        state_root=tmp_path,
        source_sha_value="sha-test",
        dry_run=True,
    )
    assert r.ok and r.outcome == "dry_run"
    assert r.view and r.view["critic_pass"] is True
    assert r.view["mbi_behavior"] == 0
    assert not (tmp_path / "agent_views.jsonl").exists()


def test_flag_on_execute_writes_agent_views(tmp_path, monkeypatch):
    monkeypatch.setenv(AGENT_VIEW_FLAG, "1")
    monkeypatch.delenv(COMMITMENT_FLAG, raising=False)
    r = run_cortex_shadow(
        subject="subj-1",
        summary="Evidence suggests quiet tape",
        citations=["src_1"],
        confidence=0.7,
        state_root=tmp_path,
        source_sha_value="sha-test",
        dry_run=False,
    )
    assert r.ok and r.outcome == "shadow_written"
    path = tmp_path / "agent_views.jsonl"
    assert path.exists()
    row = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["schema_version"] == "AgentView@v1"
    assert row["mbi_behavior"] == 0
    assert row["critic_pass"] is True
    assert not (tmp_path / "commitments.jsonl").exists()


def test_critic_refuses_trade_verbs(tmp_path, monkeypatch):
    monkeypatch.setenv(CORTEX_SHADOW_FLAG, "1")
    r = run_cortex_shadow(
        subject="subj-1",
        summary="buy shares now",
        citations=["src_1"],
        confidence=0.9,
        state_root=tmp_path,
        dry_run=False,
    )
    assert not r.ok and r.outcome == "critic_refused"
    assert "financial_action_language" in (r.reason or "")
    assert not (tmp_path / "agent_views.jsonl").exists()


def test_commitment_flag_mints_and_calibration_on_settled(tmp_path, monkeypatch):
    monkeypatch.setenv(CORTEX_SHADOW_FLAG, "1")
    monkeypatch.setenv(COMMITMENT_FLAG, "1")
    r = run_cortex_shadow(
        subject="subj-1",
        summary="Evidence suggests quiet tape",
        citations=["src_1"],
        confidence=0.7,
        state_root=tmp_path,
        source_sha_value="sha-test",
        observation={"confirmed": True},
        dry_run=False,
    )
    assert r.ok and r.commitment and r.evaluation
    assert r.evaluation["outcome"] == "CONFIRMED"
    assert (tmp_path / "commitments.jsonl").exists()
    assert (tmp_path / "calibration_shadow.json").exists()
    cal = json.loads((tmp_path / "calibration_shadow.json").read_text(encoding="utf-8"))
    assert cal["confirmed"] == 1
    assert cal["refuted_hidden"] is False
    assert r.mbi_behavior == 0


def test_cli_flag_off(capsys, tmp_path, monkeypatch):
    monkeypatch.delenv(AGENT_VIEW_FLAG, raising=False)
    monkeypatch.delenv(CORTEX_SHADOW_FLAG, raising=False)
    rc = cli.main([
        "--state-root", str(tmp_path),
        "--subject", "subj-1",
        "--summary", "quiet",
        "--execute",
    ])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 0 and out["outcome"] == "disabled"
