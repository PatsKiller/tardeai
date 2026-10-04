"""apply_operator_policy_proposal defaults to production state, not the running tree.

2026-10-04: the default store was <tree>/data/cio/operator_profile.jsonl. Inside a
release that is a symlink to persistent state; from a worktree it was a dead copy
the server never reads. Temp paths only: never touches the live store.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import apply_operator_policy_proposal as app  # noqa: E402


def test_default_store_follows_the_state_root(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    assert app.default_store() == tmp_path / "data" / "cio" / "operator_profile.jsonl"
    assert ROOT not in app.default_store().parents


def test_dry_run_reports_the_store_and_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    assert app.main([]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["applied"] is False
    assert out["store"] == str(tmp_path / "data" / "cio" / "operator_profile.jsonl")
    assert not (tmp_path / "data" / "cio" / "operator_profile.jsonl").exists()


def test_explicit_store_wins(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "ignored"))
    store = tmp_path / "explicit.jsonl"
    assert app.main(["--store", str(store)]) == 0
    assert json.loads(capsys.readouterr().out)["store"] == str(store)
