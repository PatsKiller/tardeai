"""Hermetic coverage for the release pin check. No production tree."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_release_pin_integrity.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _init(tmp: Path) -> str:
    _git(tmp, "init", "-q")
    _git(tmp, "config", "user.email", "pin-check@example.com")
    _git(tmp, "config", "user.name", "pin-check")
    rel = tmp / "scripts" / "lib"
    rel.mkdir(parents=True)
    target = rel / "buy_ready_options_alternatives.py"
    target.write_text("stamp_v1\n", encoding="utf-8")
    _git(tmp, "add", "scripts/lib/buy_ready_options_alternatives.py")
    _git(tmp, "commit", "-q", "-m", "stamp")
    sha = subprocess.check_output(["git", "-C", str(tmp), "rev-parse", "HEAD"], text=True).strip()
    meta = tmp / "dist"
    meta.mkdir()
    (meta / "build-meta.json").write_text(json.dumps({"git_sha": sha}), encoding="utf-8")
    return sha


def _run(tmp: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--release",
            str(tmp),
            "--path",
            "scripts/lib/buy_ready_options_alternatives.py",
            *extra,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_clean_stamp_matches(tmp_path: Path) -> None:
    _init(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["ok"] is True
    assert body["head_matches_stamp"] is True
    assert body["paths"][0]["match"] is True


def test_head_moved_files_kept(tmp_path: Path) -> None:
    stamp = _init(tmp_path)
    target = tmp_path / "scripts" / "lib" / "buy_ready_options_alternatives.py"
    target.write_text("later\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "scripts/lib/buy_ready_options_alternatives.py"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "later"],
        check=True,
        capture_output=True,
    )
    # Restore the stamp bytes without moving HEAD back. This is the live defect.
    target.write_text("stamp_v1\n", encoding="utf-8")
    result = _run(tmp_path, "--stamp", stamp)
    assert result.returncode == 2, result.stdout
    body = json.loads(result.stdout)
    assert body["head_matches_stamp"] is False
    assert body["paths"][0]["match"] is True


def test_file_disagrees_with_stamp(tmp_path: Path) -> None:
    _init(tmp_path)
    target = tmp_path / "scripts" / "lib" / "buy_ready_options_alternatives.py"
    target.write_text("tampered\n", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 3, result.stdout
    body = json.loads(result.stdout)
    assert body["paths"][0]["match"] is False
