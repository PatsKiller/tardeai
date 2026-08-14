"""P1-2 — CIO Drive manifest sync is dry-by-default and fail-closed.

Never performs a live Drive write. Apply is tested only with a fake gog runner.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.sync_cio_release_manifest_drive import (  # noqa: E402
    BLOCKED_SECRET,
    CANONICAL_DRIVE_FILE_ID,
    main,
    run_sync,
    sha256_bytes,
    sha256_file,
)

MAIN_SHA = "a" * 40
SECRET = "SUPER_SECRET_KEYRING_XYZ_DO_NOT_PRINT"


def _manifest_bytes(pin: str = MAIN_SHA) -> bytes:
    return json.dumps({
        "origin_main_sha": pin,
        "canonical_source_sha": pin,
        "status": "production",
    }, indent=2).encode("utf-8")


@pytest.fixture
def local_manifest(tmp_path):
    p = tmp_path / "RELEASE_MANIFEST.json"
    p.write_bytes(_manifest_bytes())
    return p


@pytest.fixture
def secret_env(monkeypatch):
    monkeypatch.setenv("GOG_KEYRING_PASSWORD", SECRET)


def test_missing_password_blocked(local_manifest, monkeypatch):
    monkeypatch.delenv("GOG_KEYRING_PASSWORD", raising=False)
    code, rec = run_sync(
        apply=False,
        file_id=CANONICAL_DRIVE_FILE_ID,
        expected_local_sha=sha256_file(local_manifest),
        expected_remote_main_sha=MAIN_SHA,
        local_path=local_manifest,
        origin_sha_fn=lambda _p: MAIN_SHA,
    )
    assert code != 0
    assert rec["error"] == BLOCKED_SECRET
    assert rec["wrote"] is False
    assert rec["ok"] is False


def test_wrong_file_id_rejected(local_manifest, secret_env):
    code, rec = run_sync(
        apply=False,
        file_id="not-the-canonical-id",
        expected_local_sha=sha256_file(local_manifest),
        expected_remote_main_sha=MAIN_SHA,
        local_path=local_manifest,
        origin_sha_fn=lambda _p: MAIN_SHA,
    )
    assert code != 0
    assert rec["error"] == "WRONG_FILE_ID"
    assert rec["wrote"] is False


def test_local_sha_mismatch(local_manifest, secret_env):
    code, rec = run_sync(
        apply=False,
        file_id=CANONICAL_DRIVE_FILE_ID,
        expected_local_sha="0" * 64,
        expected_remote_main_sha=MAIN_SHA,
        local_path=local_manifest,
        origin_sha_fn=lambda _p: MAIN_SHA,
    )
    assert code != 0
    assert rec["error"] == "LOCAL_SHA_MISMATCH"


def test_remote_main_sha_mismatch(local_manifest, secret_env):
    code, rec = run_sync(
        apply=False,
        file_id=CANONICAL_DRIVE_FILE_ID,
        expected_local_sha=sha256_file(local_manifest),
        expected_remote_main_sha="b" * 40,
        local_path=local_manifest,
        origin_sha_fn=lambda _p: MAIN_SHA,
    )
    assert code != 0
    assert rec["error"] == "REMOTE_MAIN_SHA_MISMATCH"


def test_dry_default_does_not_write(local_manifest, secret_env):
    calls = []

    def boom(argv, env):
        calls.append(argv)
        raise AssertionError("gog must not run on dry default")

    code, rec = run_sync(
        apply=False,
        file_id=CANONICAL_DRIVE_FILE_ID,
        expected_local_sha=sha256_file(local_manifest),
        expected_remote_main_sha=MAIN_SHA,
        local_path=local_manifest,
        origin_sha_fn=lambda _p: MAIN_SHA,
        gog_runner=boom,
    )
    assert code == 0
    assert rec["ok"] is True
    assert rec["dry_run"] is True
    assert rec["wrote"] is False
    assert rec["apply"] is False
    assert calls == []


def test_apply_replace_redownload_verify_with_fake_gog(local_manifest, secret_env, tmp_path):
    payload = local_manifest.read_bytes()
    calls = []

    def fake(argv, env):
        calls.append(list(argv))
        assert "--password" not in argv
        assert SECRET not in argv
        # Password may be in env for gog, never on the CLI.
        if "upload" in argv:
            assert "--replace" in argv
            assert CANONICAL_DRIVE_FILE_ID in argv
            return CompletedProcess(argv, 0, "ok", "")
        if "download" in argv:
            out = argv[argv.index("--out") + 1]
            Path(out).write_bytes(payload)
            return CompletedProcess(argv, 0, "ok", "")
        return CompletedProcess(argv, 1, "", "unexpected")

    code, rec = run_sync(
        apply=True,
        file_id=CANONICAL_DRIVE_FILE_ID,
        expected_local_sha=sha256_bytes(payload),
        expected_remote_main_sha=MAIN_SHA,
        local_path=local_manifest,
        origin_sha_fn=lambda _p: MAIN_SHA,
        gog_runner=fake,
    )
    assert code == 0
    assert rec["ok"] is True
    assert rec["wrote"] is True
    assert rec["verified"] is True
    assert rec["local_sha"] == rec["drive_sha"]
    assert any("upload" in c for c in calls)
    assert any("download" in c for c in calls)


def test_cli_password_forbidden(local_manifest, secret_env, capsys):
    rc = main([
        "--password", SECRET,
        "--expected-local-sha", sha256_file(local_manifest),
        "--expected-remote-main-sha", MAIN_SHA,
        "--local-path", str(local_manifest),
    ])
    assert rc != 0
    out = capsys.readouterr().out
    assert "CLI_PASSWORD_FORBIDDEN" in out
    assert SECRET not in out


def test_dry_cli_does_not_print_password(local_manifest, secret_env, capsys):
    rc = main([
        "--expected-local-sha", sha256_file(local_manifest),
        "--expected-remote-main-sha", MAIN_SHA,
        "--local-path", str(local_manifest),
        "--repo", str(ROOT),
    ])
    # origin/main in this repo is not MAIN_SHA, so this should fail closed
    # without printing the secret. (We are not passing origin_sha_fn via CLI.)
    out = capsys.readouterr().out
    assert SECRET not in out
    assert "GOG_KEYRING_PASSWORD=" not in out
    # Either mismatch (real origin/main) or blocked — never a write.
    data = json.loads(out)
    assert data.get("wrote") is False
    assert rc != 0 or data.get("dry_run") is True


def test_source_never_uses_cli_password():
    src = (ROOT / "scripts" / "sync_cio_release_manifest_drive.py").read_text(encoding="utf-8")
    assert "CLI_PASSWORD_FORBIDDEN" in src
    assert "GOG_KEYRING_PASSWORD" in src
    assert "password_present" in src
    # Must not interpolate the password into logs / argv construction.
    assert "os.environ.get(PASSWORD_ENV) or \"\"" in src or 'os.environ.get(PASSWORD_ENV)' in src
    assert "argv.append(os.environ" not in src
