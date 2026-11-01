"""resolve_secret: Bitwarden SM tmpfs wins over disk .env (no network, no real secrets)."""
from __future__ import annotations

import sys
import os
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "secrets"))

from resolve_secret import (  # noqa: E402
    parse_env_file,
    resolve_secret,
    upsert_disk_env_key,
    validate_finviz_cookie_value,
)


def test_tmpfs_beats_disk_and_environ(tmp_path, monkeypatch):
    tmpfs = tmp_path / "tradeai_env"
    disk = tmp_path / ".env"
    # Quoted cookie-like values (semicolons) as render_env would write
    tmpfs.write_text(
        "FINVIZ_COOKIE='tmpfs_cookie_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA.ASPXAUTH=sm_token'\n"
        "FINVIZ_API_TOKEN=tmpfs_token_xyz\n"
    )
    disk.write_text(
        "FINVIZ_COOKIE='disk_cookie_truncated_short'\n"
        "FINVIZ_API_TOKEN=disk_token\n"
        "OTHER=keep\n"
    )
    monkeypatch.setenv("FINVIZ_COOKIE", "env_cookie_from_process_should_lose_to_tmpfs")
    monkeypatch.setenv("FINVIZ_API_TOKEN", "env_token_should_lose")

    cookie = resolve_secret(
        "FINVIZ_COOKIE",
        tmpfs_path=tmpfs,
        disk_env_path=disk,
        project_root=tmp_path,
        environ=dict(monkeypatch._environ) if hasattr(monkeypatch, "_environ") else None,
    )
    # Use real os.environ after monkeypatch
    cookie = resolve_secret(
        "FINVIZ_COOKIE",
        tmpfs_path=tmpfs,
        disk_env_path=disk,
        project_root=tmp_path,
    )
    assert cookie.startswith("tmpfs_cookie_")
    assert "sm_token" in cookie
    assert "disk_cookie" not in cookie
    assert "env_cookie" not in cookie

    token = resolve_secret(
        "FINVIZ_API_TOKEN",
        tmpfs_path=tmpfs,
        disk_env_path=disk,
        project_root=tmp_path,
    )
    assert token == "tmpfs_token_xyz"


def test_disk_when_tmpfs_missing(tmp_path, monkeypatch):
    disk = tmp_path / ".env"
    disk.write_text("FINVIZ_COOKIE='disk_only_cookie_BBBBBBBBBBBBBBBBBBBBBBBB.ASPXAUTH=x'\n")
    monkeypatch.delenv("FINVIZ_COOKIE", raising=False)
    missing = tmp_path / "no_such_tmpfs"
    v = resolve_secret(
        "FINVIZ_COOKIE",
        tmpfs_path=missing,
        disk_env_path=disk,
        project_root=tmp_path,
    )
    assert v.startswith("disk_only_cookie_")


def test_environ_when_tmpfs_empty_key(tmp_path, monkeypatch):
    tmpfs = tmp_path / "env"
    disk = tmp_path / ".env"
    tmpfs.write_text("OTHER=1\n")  # no FINVIZ_COOKIE
    disk.write_text("FINVIZ_COOKIE='disk_should_lose_to_environ'\n")
    monkeypatch.setenv("FINVIZ_COOKIE", "from_process_env_CCCCCCCCCCCCCCCCCCCCCCCC.ASPXAUTH=y")
    v = resolve_secret(
        "FINVIZ_COOKIE",
        tmpfs_path=tmpfs,
        disk_env_path=disk,
        project_root=tmp_path,
    )
    assert v.startswith("from_process_env_")


def test_validate_finviz_cookie_rejects_truncated():
    try:
        validate_finviz_cookie_value("short.ASPXAUTH=x")
        assert False, "expected ValueError"
    except ValueError as e:
        msg = str(e)
        assert "50" in msg or "short" in msg.lower() or "ASPXAUTH" in msg
        assert "short.ASPXAUTH" not in msg  # never echo full value in some cases — short is ok in msg? 
        # message must not contain a realistic secret; short test value may appear — ensure len note only
        assert "len=" in msg or "too short" in msg.lower() or "ASPXAUTH" in msg


def test_validate_finviz_cookie_rejects_missing_aspxauth():
    long_no_auth = "x" * 60
    try:
        validate_finviz_cookie_value(long_no_auth)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "ASPXAUTH" in str(e)


def test_validate_finviz_cookie_accepts_full():
    validate_finviz_cookie_value("a" * 40 + ".ASPXAUTH=" + "b" * 20)


def test_upsert_disk_only_if_exists(tmp_path):
    disk = tmp_path / ".env"
    disk.write_text("FINVIZ_COOKIE='old'\nKEEP=1\n")
    assert upsert_disk_env_key("FINVIZ_COOKIE", "new_value_here", disk_env_path=disk, only_if_exists=True)
    text = disk.read_text()
    assert "new_value_here" in text
    assert "KEEP=1" in text
    # New key not on disk → no invent
    assert not upsert_disk_env_key("BRAND_NEW_KEY", "secret", disk_env_path=disk, only_if_exists=True)
    assert "BRAND_NEW_KEY" not in disk.read_text()


def test_parse_env_quoted():
    p = Path(__file__).resolve()  # placeholder — use string parse via temp
    import tempfile
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".env") as f:
        f.write("FINVIZ_COOKIE='a;b=c'\n")
        path = Path(f.name)
    try:
        d = parse_env_file(path)
        assert d["FINVIZ_COOKIE"] == "a;b=c"
    finally:
        path.unlink(missing_ok=True)


def test_upsert_disk_env_key_is_atomic_and_skips_noop_rewrites(tmp_path, monkeypatch):
    import resolve_secret as RS

    env = tmp_path / ".env"
    env.write_text("A=1\nB=2\n")
    os.chmod(env, 0o600)
    inode = env.stat().st_ino
    assert RS.upsert_disk_env_key("A", "1", disk_env_path=env) is False  # unchanged: no rewrite
    assert env.stat().st_ino == inode
    assert RS.upsert_disk_env_key("A", "9", disk_env_path=env) is True
    assert env.read_text() == "A=9\nB=2\n" and (env.stat().st_mode & 0o777) == 0o600

    def full_disk(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(RS.os, "fsync", full_disk)
    with pytest.raises(OSError):
        RS.upsert_disk_env_key("B", "7", disk_env_path=env)
    assert env.read_text() == "A=9\nB=2\n"  # untouched, never truncated
    assert [p.name for p in tmp_path.iterdir()] == [".env"]  # no temp left behind


def test_upsert_disk_env_key_rewrites_the_symlink_target(tmp_path):
    import resolve_secret as RS

    real = tmp_path / "real.env"
    real.write_text("A=1\n")
    link = tmp_path / ".env"
    link.symlink_to(real)
    assert RS.upsert_disk_env_key("A", "2", disk_env_path=link) is True
    assert link.is_symlink() and real.read_text() == "A=2\n"
