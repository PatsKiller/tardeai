"""Lane A — poller CURRENT identity regression gate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.poller_release_identity import (
    assert_running_from_current,
    identity_report,
    read_source_commit,
    resolve_current_release,
)


def test_read_source_commit_from_file(tmp_path: Path):
    (tmp_path / "SOURCE_COMMIT").write_text("abc123deadbeef\n", encoding="utf-8")
    assert read_source_commit(tmp_path) == "abc123deadbeef"


def test_identity_mismatch_self_exits(tmp_path: Path, monkeypatch):
    current = tmp_path / "current_rel"
    other = tmp_path / "other_rel"
    current.mkdir()
    other.mkdir()
    (current / "SOURCE_COMMIT").write_text("currsha\n", encoding="utf-8")
    (other / "SOURCE_COMMIT").write_text("othersha\n", encoding="utf-8")
    link = tmp_path / "CURRENT"
    link.symlink_to(current)

    monkeypatch.chdir(other)
    monkeypatch.setenv("TRADEAI_PORTFOLIO_CURRENT_LINK", str(link))

    with pytest.raises(SystemExit) as ei:
        assert_running_from_current(current_link=link, exit_on_mismatch=True)
    assert ei.value.code == 0

    report = identity_report(current_link=link)
    assert report["matches_current"] is False
    assert report["mismatch_reason"] == "cwd_ne_current"


def test_identity_ok_when_cwd_is_current(tmp_path: Path, monkeypatch):
    current = tmp_path / "rel"
    current.mkdir()
    (current / "SOURCE_COMMIT").write_text("oksha\n", encoding="utf-8")
    link = tmp_path / "CURRENT"
    link.symlink_to(current)
    monkeypatch.chdir(current)
    report = assert_running_from_current(current_link=link, exit_on_mismatch=True)
    assert report["matches_current"] is True
    assert resolve_current_release(link) == current.resolve()


def test_deleted_interpreter_simulation_is_mismatch_shape(tmp_path: Path, monkeypatch):
    """Regression shape: cwd ≠ CURRENT must fail the gate (stale release class)."""
    current = tmp_path / "845ce5d88-main"
    stale = tmp_path / "340aaf831-main"
    current.mkdir()
    stale.mkdir()
    (current / "SOURCE_COMMIT").write_text("845ce5d88\n", encoding="utf-8")
    (stale / "SOURCE_COMMIT").write_text("340aaf831\n", encoding="utf-8")
    link = tmp_path / "CURRENT"
    link.symlink_to(current)
    monkeypatch.chdir(stale)
    report = identity_report(current_link=link)
    assert report["matches_current"] is False
    assert "340aaf831" in (report["process_cwd_basename"] or "")
    # Ensure report is JSON-serializable for log parsers.
    json.dumps(report)
