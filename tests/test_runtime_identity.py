"""runtime_identity — exact SHA resolution and fail-closed guards."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from scripts.lib.runtime_identity import (  # noqa: E402
    require_source_sha,
    resolve_source_sha,
)


def test_env_wins(tmp_path):
    sha = resolve_source_sha(
        {"BUILD_SHA": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
        project_root=tmp_path,
        current_release=tmp_path / "missing",
        allow_git=False,
    )
    assert sha == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def test_reads_current_build_sha(tmp_path):
    cur = tmp_path / "CURRENT"
    cur.mkdir()
    (cur / "BUILD_SHA").write_text("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n")
    sha = resolve_source_sha(
        {},
        project_root=tmp_path,
        current_release=cur,
        allow_git=False,
    )
    assert sha == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def test_reads_build_stamp_json(tmp_path):
    cur = tmp_path / "CURRENT"
    cur.mkdir()
    (cur / "BUILD_STAMP.json").write_text(json.dumps({"build_sha": "c" * 40}))
    sha = resolve_source_sha(
        {},
        project_root=tmp_path,
        current_release=cur,
        allow_git=False,
    )
    assert sha == "c" * 40


def test_unknown_when_nothing_available(tmp_path):
    sha = resolve_source_sha(
        {},
        project_root=tmp_path,
        current_release=tmp_path / "nope",
        allow_git=False,
    )
    assert sha == "unknown"


def test_ignores_env_unknown_literal(tmp_path):
    cur = tmp_path / "CURRENT"
    cur.mkdir()
    (cur / "SOURCE_COMMIT").write_text("d" * 40)
    sha = resolve_source_sha(
        {"BUILD_SHA": "unknown"},
        project_root=tmp_path,
        current_release=cur,
        allow_git=False,
    )
    assert sha == "d" * 40


def test_require_refuses_unknown():
    with pytest.raises(ValueError, match="unresolved"):
        require_source_sha(
            {},
            project_root=Path("/nonexistent-root-for-identity"),
            current_release=Path("/nonexistent-current-for-identity"),
        )


def test_require_refuses_mismatched_supplied(tmp_path):
    cur = tmp_path / "CURRENT"
    cur.mkdir()
    (cur / "BUILD_SHA").write_text("e" * 40)
    with pytest.raises(ValueError, match="mismatches"):
        require_source_sha(
            {},
            project_root=tmp_path,
            current_release=cur,
            supplied="f" * 40,
        )


def test_require_refuses_supplied_unknown(tmp_path):
    cur = tmp_path / "CURRENT"
    cur.mkdir()
    (cur / "BUILD_SHA").write_text("e" * 40)
    with pytest.raises(ValueError, match="unknown"):
        require_source_sha(
            {},
            project_root=tmp_path,
            current_release=cur,
            supplied="unknown",
        )


def test_producers_delegate_to_runtime_identity():
    """The four env-only fallthroughs must not remain as the only path."""
    from scripts.lib import persistent_agent_wake as paw
    from scripts.lib import governed_research_producer as grp
    from scripts.lib import cortex_shadow_pipeline as csp

    assert "resolve_source_sha" in Path(paw.__file__).read_text(encoding="utf-8")
    assert "resolve_source_sha" in Path(grp.__file__).read_text(encoding="utf-8")
    assert "resolve_source_sha" in Path(csp.__file__).read_text(encoding="utf-8")
    shadow = ROOT / "scripts" / "run_governed_commitment_shadow.py"
    assert "resolve_source_sha" in shadow.read_text(encoding="utf-8")
