"""Refactor wave 1 (cron -> n8n, 2026-10-10): scripts/maturity_remeasure.py (n8n e18d7849b4142927 / cron L1000).

The lane already writes its durable signal (data/governance/maturity_latest.json under the state root)
only on --write. This adds an explicit --dry-run for the dispatcher contract: it scores, names the files
a --write would touch, and returns before any of them (it wins over --write). The double schedule
(cron L1000 + the live n8n workflow) is an operator/cron-grant item and is not touched here.
Hermetic: --root is a tmp dir; the heartbeat module is stubbed.
"""

from __future__ import annotations

import inspect
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import maturity_remeasure as mr  # noqa: E402


@pytest.fixture
def beats(monkeypatch):
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "supervisor_heartbeat",
        types.SimpleNamespace(beat=lambda *a, **k: calls.append(a) or {"pg": "stub"}),
    )
    return calls


@pytest.mark.parametrize("argv", [["--dry-run"], ["--dry-run", "--write"]])
def test_dry_run_writes_nothing_and_names_the_targets(tmp_path, beats, capsys, argv):
    assert mr.main(argv + ["--root", str(tmp_path)]) == 0
    text = capsys.readouterr().out
    report = json.loads(text[text.index('{\n "mode"') :])
    assert report["mode"] == "dry_run"
    assert report["would_replace"] == str(tmp_path / "data/governance/maturity_latest.json")
    assert not (tmp_path / "data").exists() and beats == []


def test_no_flag_is_still_a_silent_read_only_score(tmp_path, beats, capsys):
    assert mr.main(["--root", str(tmp_path)]) == 0
    assert not (tmp_path / "data").exists() and beats == []
    assert "dry_run" not in capsys.readouterr().out


def test_write_still_writes_the_signal_and_beats(tmp_path, beats):
    assert mr.main(["--write", "--root", str(tmp_path)]) == 0
    doc = json.loads((tmp_path / "data/governance/maturity_latest.json").read_text())
    assert doc["schema"] == "MaturityScore@v1" and len(beats) == 1


def test_source_order_dry_run_returns_before_any_write():
    src = inspect.getsource(mr.main)
    cut = src.index("# returns before any write is reachable")
    assert cut < src.index('maturity_scores.jsonl").open("a"') and cut < src.index("hb.beat(")
