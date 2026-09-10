"""Phase 8 — GOVERNED_COMMITMENT_ENABLED shadow CLI (default OFF)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_governed_commitment_shadow as runner
from scripts.lib.governed_commitment import FEATURE_FLAG


def _run(argv, capsys):
    rc = runner.main(argv)
    out = capsys.readouterr().out.strip().splitlines()[-1]
    return rc, json.loads(out)


def test_flag_off_is_noop(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(FEATURE_FLAG, raising=False)
    rc, out = _run([
        "--state-root", str(tmp_path),
        "--subject-guid", "subj-1",
        "--claim", "quiet tape",
        "--falsifier", "unexpected move",
        "--execute",
    ], capsys)
    assert rc == 0
    assert out["outcome"] == "disabled"
    assert not (tmp_path / "commitments.jsonl").exists()


def test_flag_on_dry_run_default_writes_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(FEATURE_FLAG, "1")
    rc, out = _run([
        "--state-root", str(tmp_path),
        "--subject-guid", "subj-1",
        "--claim", "quiet tape",
        "--falsifier", "unexpected move",
    ], capsys)
    assert rc == 0
    assert out["outcome"] == "dry_run"
    assert out["commitment"]["mbi_behavior"] == 0
    assert not (tmp_path / "commitments.jsonl").exists()


def test_flag_on_execute_appends_jsonl(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(FEATURE_FLAG, "1")
    rc, out = _run([
        "--state-root", str(tmp_path),
        "--subject-guid", "subj-1",
        "--claim", "quiet tape",
        "--falsifier", "unexpected move",
        "--execute",
    ], capsys)
    assert rc == 0
    assert out["outcome"] == "appended"
    path = tmp_path / "commitments.jsonl"
    assert path.exists()
    row = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["commitment_id"].startswith("gcmt_")
    assert row["mbi_behavior"] == 0
