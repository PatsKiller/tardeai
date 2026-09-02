"""Canonical SOP toolchain discovery + attestation tool-version enforcement."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from scripts.lib import sop_toolchain as tc
from scripts.lib.sop_evidence_integrity import (
    EXPECTED_CORE_TESTS,
    RUNTIME_ATTESTATION_SCHEMA,
    control_surface_digest,
    validate_runtime_attestation,
    workflow_facts,
)

ROOT = Path(__file__).resolve().parents[1]


def test_ruff_found_via_repo_venv_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When PATH has no ruff, hub/repo .venv fallback still resolves."""
    monkeypatch.setattr(tc.shutil, "which", lambda _name: None)
    # Point hub constant at a real binary if present, else synthesize under tmp
    real = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/ruff")
    if real.is_file():
        monkeypatch.setattr(tc, "_HUB_RUFF", real)
        got = tc.resolve_ruff_bin(root=tmp_path)  # no local .venv
        assert got == real
    else:
        fake = tmp_path / ".venv" / "bin" / "ruff"
        fake.parent.mkdir(parents=True)
        fake.write_text("#!/bin/sh\necho ruff 0.16.2\n", encoding="utf-8")
        fake.chmod(0o755)
        got = tc.resolve_ruff_bin(root=tmp_path)
        assert got == fake


def test_ruff_found_directly_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake = tmp_path / "bin" / "ruff"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\necho ruff 0.16.2\n", encoding="utf-8")
    fake.chmod(0o755)
    # Isolate every candidate above PATH so only shutil.which can win.
    monkeypatch.setattr(tc, "_HUB_RUFF", tmp_path / "missing-hub-ruff")
    monkeypatch.setattr(tc.sys, "executable", str(tmp_path / "missing-python"))
    monkeypatch.setattr(tc.shutil, "which", lambda _name: str(fake))
    # No root .venv
    got = tc.resolve_ruff_bin(root=tmp_path / "empty-root")
    assert got == fake


def test_ruff_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(tc.shutil, "which", lambda _name: None)
    monkeypatch.setattr(tc, "_HUB_RUFF", tmp_path / "nope")
    monkeypatch.setattr(tc.sys, "executable", str(tmp_path / "python"))
    assert tc.resolve_ruff_bin(root=tmp_path) is None


def test_collect_tool_versions_records_pinned_ruff(monkeypatch: pytest.MonkeyPatch):
    # Use live resolver; environment has hub ruff even if PATH empty
    vers = tc.collect_tool_versions(root=ROOT)
    assert vers["pinned_ruff"] == "0.16.2"
    assert vers["ruff"] != "MISSING"
    assert tc.parse_ruff_version(str(vers["ruff_raw"])) == "0.16.2" or vers["ruff"] == "0.16.2"
    assert vers["python"]
    assert vers["shellcheck"] != "MISSING"
    # Must be an exact version, not the `shellcheck --version` banner line.
    assert re.fullmatch(r"\d+\.\d+(?:\.\d+)?", vers["shellcheck"]), vers["shellcheck"]
    assert "shell script analysis tool" not in vers["shellcheck"]
    assert tc.parse_shellcheck_version(vers["shellcheck_raw"]) == vers["shellcheck"]


def _base_att(*, ruff: str = "0.16.2") -> dict:
    digest = control_surface_digest(ROOT)["digest"]
    wf = workflow_facts(ROOT)
    return {
        "schema": RUNTIME_ATTESTATION_SCHEMA,
        "schema_version": "1.0.0",
        "head_sha": "a" * 40,
        "base_sha": "b" * 40,
        "control_surface_digest": digest,
        "policy_version": "1.2.0",
        "policy_status": "PROPOSED",
        "workflow_blob_sha256": wf["blob_sha256"],
        "commands": [{"name": "pytest_core", "exit": 0}],
        "test_counts": {"core": EXPECTED_CORE_TESTS},
        "docs_index_fingerprint": "deadbeef",
        "tool_versions": {
            "python": "3.14.4",
            "pinned_ruff": "0.16.2",
            "ruff": ruff,
            "ruff_raw": f"ruff {ruff}" if ruff != "MISSING" else "MISSING",
            # Live value: the recorded ShellCheck version must match the tool.
            "shellcheck": tc.collect_tool_versions(root=ROOT)["shellcheck"],
        },
        "clean_state": True,
        "authority_non_regression": "PASS",
    }


def test_attestation_valid_pinned_ruff():
    att = _base_att(ruff="0.16.2")
    assert validate_runtime_attestation(att, root=ROOT) == []


def test_attestation_falsely_recording_missing():
    att = _base_att(ruff="MISSING")
    errs = validate_runtime_attestation(att, root=ROOT, changed_python=True)
    assert "ATTESTATION_RUFF_RECORDED_MISSING" in errs
    assert "ATTESTATION_CHANGED_PYTHON_REQUIRES_RUFF" in errs


def test_attestation_ruff_version_mismatch(monkeypatch: pytest.MonkeyPatch):
    att = _base_att(ruff="0.15.0")
    # Live tool is 0.16.2 — mismatch against recorded
    errs = validate_runtime_attestation(att, root=ROOT)
    assert "ATTESTATION_RUFF_PIN_MISMATCH" in errs or "ATTESTATION_RUFF_VERSION_MISMATCH" in errs


def test_attestation_pass_conflicts_with_missing_tool():
    att = _base_att(ruff="MISSING")
    att["commands"] = [{"name": "ruff_check", "exit": 0}, {"name": "quality", "exit": 0}]
    errs = validate_runtime_attestation(att, root=ROOT, changed_python=True)
    assert any(e.startswith("ATTESTATION_PASS_WITH_MISSING_TOOL:") for e in errs)


def test_attestation_ruff_missing_with_changed_python(monkeypatch: pytest.MonkeyPatch):
    # Capture live tool versions BEFORE patching, or the stub recurses into itself.
    live = tc.collect_tool_versions(root=ROOT)
    monkeypatch.setattr(tc, "resolve_ruff_bin", lambda root=None: None)
    monkeypatch.setattr(
        tc,
        "collect_tool_versions",
        lambda root=None: {
            "python": "3.14.4",
            "pinned_ruff": "0.16.2",
            "ruff": "MISSING",
            "ruff_raw": "MISSING",
            "shellcheck": live["shellcheck"],
            "shellcheck_raw": live["shellcheck_raw"],
        },
    )
    att = _base_att(ruff="MISSING")
    errs = validate_runtime_attestation(att, root=ROOT, changed_python=True, require_ruff=True)
    assert "ATTESTATION_RUFF_TOOL_MISSING" in errs
    assert "ATTESTATION_CHANGED_PYTHON_REQUIRES_RUFF" in errs


def test_parse_shellcheck_version_rejects_banner_only():
    """The banner line carries no version and must not read as 'present'."""
    assert tc.parse_shellcheck_version("ShellCheck - shell script analysis tool") is None
    assert tc.parse_shellcheck_version("MISSING") is None
    assert tc.parse_shellcheck_version("") is None
    assert tc.parse_shellcheck_version("version: 0.11.0") == "0.11.0"
    assert (
        tc.parse_shellcheck_version("ShellCheck - shell script analysis tool\nversion: 0.9.0\nlicense: GPLv3\n")
        == "0.9.0"
    )


def test_shellcheck_version_string_is_the_version_line():
    """Regression: line 0 is the banner; the version lives on a later line."""
    raw = tc.shellcheck_version_string()
    if raw == "MISSING":
        pytest.skip("shellcheck not installed")
    assert raw.lower().startswith("version:"), raw
    assert tc.parse_shellcheck_version(raw) is not None


def test_attestation_rejects_banner_only_shellcheck():
    att = _base_att()
    att["tool_versions"]["shellcheck"] = "ShellCheck - shell script analysis tool"
    errs = validate_runtime_attestation(att, root=ROOT)
    assert "ATTESTATION_SHELLCHECK_VERSION_UNPARSEABLE" in errs


def test_attestation_rejects_mismatched_shellcheck_version():
    live = tc.collect_tool_versions(root=ROOT)["shellcheck"]
    if live == "MISSING":
        pytest.skip("shellcheck not installed")
    att = _base_att()
    att["tool_versions"]["shellcheck"] = "9.9.9"
    errs = validate_runtime_attestation(att, root=ROOT)
    assert "ATTESTATION_SHELLCHECK_VERSION_MISMATCH" in errs


def test_attestation_rejects_falsely_missing_shellcheck():
    live = tc.collect_tool_versions(root=ROOT)["shellcheck"]
    if live == "MISSING":
        pytest.skip("shellcheck not installed")
    att = _base_att()
    att["tool_versions"]["shellcheck"] = "MISSING"
    errs = validate_runtime_attestation(att, root=ROOT)
    assert "ATTESTATION_SHELLCHECK_FALSE_MISSING" in errs


def test_attestation_accepts_live_shellcheck_version():
    att = _base_att()
    assert validate_runtime_attestation(att, root=ROOT) == []
