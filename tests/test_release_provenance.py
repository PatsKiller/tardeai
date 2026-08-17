"""Release-provenance hardening tests (P2).

Proves the exact-main deploy path stamps ONE authoritative 40-char source
commit across SOURCE_COMMIT, BUILD_SHA, GIT_SHA, BUILD_STAMP.json, and
build-meta.json — and that a fail-closed validator rejects any stale,
malformed, or disagreeing artifact.

No production mutation: the `stamp` subcommand is side-effect free (no npm,
network, systemd, Telegram, or broker), and the validator only reads.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh"
VALIDATOR_PATH = ROOT / "scripts" / "validate_release_provenance.py"

OLD_SHA = "0" * 40
NEW_SHA = "1" * 40


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_release_provenance", VALIDATOR_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


validator = _load_validator()


def _write_artifacts(release: Path, sha: str) -> None:
    release.mkdir(parents=True, exist_ok=True)
    (release / "SOURCE_COMMIT").write_text(sha + "\n", encoding="utf-8")
    (release / "BUILD_SHA").write_text(sha + "\n", encoding="utf-8")
    (release / "GIT_SHA").write_text(sha + "\n", encoding="utf-8")
    (release / "BUILD_STAMP.json").write_text(
        json.dumps(
            {
                "build_sha": sha,
                "source_sha": sha,
                "git_sha": sha,
                "branch": "main",
                "label": "main-exact-phase2",
                "stamped_at": "2026-01-01T00:00:00Z",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    for rel in (
        "apps/command-center-v3/build-meta.json",
        "apps/command-center-v3/dist/build-meta.json",
    ):
        p = release / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "git_sha": sha,
                    "source_sha": sha,
                    "source_commit": sha,
                    "build_sha": sha[:12],
                    "built_at": "2026-01-01T00:00:00Z",
                    "branch": "main",
                    "release_label": "main-exact-phase2",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def _stamp(release: Path, sha: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(DEPLOY), "stamp", str(release), sha],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _read_sha_artifacts(release: Path) -> dict[str, str]:
    out: dict[str, str] = {
        "SOURCE_COMMIT": (release / "SOURCE_COMMIT").read_text(encoding="utf-8").strip(),
        "BUILD_SHA": (release / "BUILD_SHA").read_text(encoding="utf-8").strip(),
        "GIT_SHA": (release / "GIT_SHA").read_text(encoding="utf-8").strip(),
    }
    stamp = json.loads((release / "BUILD_STAMP.json").read_text(encoding="utf-8"))
    out["BUILD_STAMP.build_sha"] = stamp["build_sha"]
    out["BUILD_STAMP.source_sha"] = stamp["source_sha"]
    out["BUILD_STAMP.git_sha"] = stamp["git_sha"]
    for rel, prefix in (
        ("apps/command-center-v3/build-meta.json", "build-meta"),
        ("apps/command-center-v3/dist/build-meta.json", "dist-build-meta"),
    ):
        meta = json.loads((release / rel).read_text(encoding="utf-8"))
        out[f"{prefix}.git_sha"] = meta["git_sha"]
        out[f"{prefix}.source_sha"] = meta["source_sha"]
        out[f"{prefix}.source_commit"] = meta["source_commit"]
    return out


# ---------------------------------------------------------------------------
# Validator: consistent release passes
# ---------------------------------------------------------------------------
def test_validator_passes_consistent_release(tmp_path):
    _write_artifacts(tmp_path / "rel", OLD_SHA)
    ok, errors = validator.validate(tmp_path / "rel")
    assert ok, f"expected PASS, got {errors}"


# ---------------------------------------------------------------------------
# Validator: fail-closed cases
# ---------------------------------------------------------------------------
def test_validator_fails_missing_source_commit(tmp_path):
    rel = tmp_path / "rel"
    _write_artifacts(rel, OLD_SHA)
    (rel / "SOURCE_COMMIT").unlink()
    ok, errors = validator.validate(rel)
    assert not ok
    assert any("SOURCE_COMMIT" in e and "missing" in e for e in errors)


def test_validator_fails_malformed_sha(tmp_path):
    rel = tmp_path / "rel"
    _write_artifacts(rel, OLD_SHA)
    (rel / "SOURCE_COMMIT").write_text("not-a-sha\n", encoding="utf-8")
    ok, errors = validator.validate(rel)
    assert not ok
    assert any("SOURCE_COMMIT" in e and "malformed" in e for e in errors)


def test_validator_fails_source_commit_build_sha_mismatch(tmp_path):
    rel = tmp_path / "rel"
    _write_artifacts(rel, OLD_SHA)
    (rel / "BUILD_SHA").write_text(NEW_SHA + "\n", encoding="utf-8")
    ok, errors = validator.validate(rel)
    assert not ok
    assert any("BUILD_SHA" in e and "canonical" in e for e in errors)


def test_validator_fails_git_sha_mismatch(tmp_path):
    rel = tmp_path / "rel"
    _write_artifacts(rel, OLD_SHA)
    (rel / "GIT_SHA").write_text(NEW_SHA + "\n", encoding="utf-8")
    ok, errors = validator.validate(rel)
    assert not ok
    assert any("GIT_SHA" in e and "canonical" in e for e in errors)


def test_validator_fails_build_stamp_mismatch(tmp_path):
    rel = tmp_path / "rel"
    _write_artifacts(rel, OLD_SHA)
    stamp = json.loads((rel / "BUILD_STAMP.json").read_text(encoding="utf-8"))
    stamp["build_sha"] = NEW_SHA
    (rel / "BUILD_STAMP.json").write_text(json.dumps(stamp), encoding="utf-8")
    ok, errors = validator.validate(rel)
    assert not ok
    assert any("BUILD_STAMP.json.build_sha" in e for e in errors)


def test_validator_fails_build_meta_mismatch(tmp_path):
    rel = tmp_path / "rel"
    _write_artifacts(rel, OLD_SHA)
    p = rel / "apps/command-center-v3/build-meta.json"
    meta = json.loads(p.read_text(encoding="utf-8"))
    meta["source_commit"] = NEW_SHA
    p.write_text(json.dumps(meta), encoding="utf-8")
    ok, errors = validator.validate(rel)
    assert not ok
    assert any("source_commit" in e and "canonical" in e for e in errors)


# ---------------------------------------------------------------------------
# Stale-clone scenario: re-stamp must overwrite every inherited old SHA
# ---------------------------------------------------------------------------
def test_stale_clone_scenario_stamps_new_sha(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    _write_artifacts(old, OLD_SHA)
    # Simulate `prepare` cloning the previous release: NEW inherits OLD stamps.
    shutil.copytree(old, new)

    proc = _stamp(new, NEW_SHA)
    assert proc.returncode == 0, f"stamp failed:\n{proc.stderr}"

    artifacts = _read_sha_artifacts(new)
    assert set(artifacts.values()) == {NEW_SHA}, f"stale SHA survived: {artifacts}"

    # The full validator must now agree the release is internally consistent.
    ok, errors = validator.validate(new)
    assert ok, f"expected PASS after stamp, got {errors}"


# ---------------------------------------------------------------------------
# Idempotency: re-stamping with the same SHA does not drift
# ---------------------------------------------------------------------------
def test_stamp_is_idempotent(tmp_path):
    new = tmp_path / "new"
    _write_artifacts(new, OLD_SHA)

    proc1 = _stamp(new, NEW_SHA)
    proc2 = _stamp(new, NEW_SHA)
    assert proc1.returncode == 0 and proc2.returncode == 0

    artifacts = _read_sha_artifacts(new)
    assert set(artifacts.values()) == {NEW_SHA}
    ok, _ = validator.validate(new)
    assert ok


# ---------------------------------------------------------------------------
# Deploy script still writes SOURCE_COMMIT and source_commit (regression)
# ---------------------------------------------------------------------------
def test_deploy_script_stamps_source_commit_and_build_meta_source_commit():
    src = DEPLOY.read_text(encoding="utf-8")
    assert 'printf \'%s\\n\' "$sha" >"${dir}/SOURCE_COMMIT"' in src
    assert '"source_commit": "${sha}"' in src
    assert "write_build_meta" in src
    assert "stamp)" in src
