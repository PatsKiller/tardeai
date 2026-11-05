"""A file the PII scanner cannot read is never clean (FQ-154).

Claude-lead, 2026-11-05: `_decode` returned None for any file with a NUL byte in its first 8 KiB and every caller
treated None as "nothing found", so every PNG, JPEG, PDF and archive was reported clean without being read — and two
live-page captures reached a public branch through it. This suite pins the new contract:

1. an unreadable file is a `binary_unreadable` FINDING, not a pass;
2. the only silence is a reviewed registration in `config/pii_binary_review.json` (reason + reviewer + date);
3. the count is not ratcheted, so a baseline number can never be the permission;
4. `--tree` fails on the existing tree when an unreadable file is unregistered, and passes when it is registered;
5. the register file is its canonical rendering.

Hermetic: a temporary git repository, no network, no real repository files.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_no_pii as C  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01" + b"\x00" * 64


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo(tmp_path: Path, *, register: dict | None = None, baseline: bool = True) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "synthetic@example.com")
    _git(repo, "config", "user.name", "synthetic")
    (repo / "README.md").write_text("synthetic text, nothing personal\n", encoding="utf-8")
    (repo / "assets").mkdir()
    (repo / "assets" / "synthetic-logo.png").write_bytes(PNG)
    if baseline:
        (repo / "config").mkdir()
        (repo / "config" / "pii_baseline.json").write_text(
            json.dumps({"schema": C.SCHEMA, "counts": {k: 0 for k in C.RATCHETED}}) + "\n", encoding="utf-8"
        )
    if register is not None:
        (repo / "config" / "pii_binary_review.json").write_text(
            json.dumps({"schema": C.SCHEMA_BINARY_REVIEW, "files": register}, indent=2) + "\n",
            encoding="utf-8",
        )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "synthetic")
    return repo


REGISTERED = {
    "assets/synthetic-logo.png": {
        "reason": "synthetic placeholder drawn by the test; no page, person or account in it",
        "reviewed_by": "cc-deepseek-3",
        "reviewed_at": "2026-11-05T14:00:00Z",
    }
}


def test_an_unreadable_file_is_a_finding_not_a_pass(tmp_path):
    repo = _repo(tmp_path)
    findings = C.scan_tree(repo, deny=[], binary_review={})
    bins = [f for f in findings if f.category == "binary_unreadable"]
    assert [f.path for f in bins] == ["assets/synthetic-logo.png"], findings
    assert "not registered" in bins[0].detail


def test_a_registered_file_is_the_only_silence(tmp_path):
    repo = _repo(tmp_path, register=REGISTERED)
    findings = C.scan_tree(repo, deny=[])
    assert not [f for f in findings if f.category == "binary_unreadable"]


def test_a_registration_without_a_reason_fails_closed(tmp_path):
    repo = _repo(tmp_path, register={"assets/synthetic-logo.png": {"reviewed_by": "someone", "reviewed_at": "x"}})
    with pytest.raises(C.ScanError, match="missing reason"):
        C.scan_tree(repo, deny=[], binary_review=None)


def test_the_count_is_not_ratcheted_so_a_baseline_cannot_swallow_it(tmp_path):
    assert "binary_unreadable" in C.CATEGORIES
    assert "binary_unreadable" not in C.RATCHETED


def _run(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_no_pii.py"), "--repo", str(repo), "--tree", *extra],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_tree_fails_on_an_unregistered_binary_and_passes_once_registered(tmp_path):
    repo = _repo(tmp_path)
    red = _run(repo)
    assert red.returncode == 1, red.stdout + red.stderr
    assert "binary_unreadable" in red.stdout
    assert "assets/synthetic-logo.png" in red.stdout
    # The remedy is a reviewed entry, not a baseline number.
    refused = _run(repo, "--write-baseline")
    assert refused.returncode == 1 and "REFUSED" in refused.stderr
    (repo / "config" / "pii_binary_review.json").write_text(
        json.dumps({"schema": C.SCHEMA_BINARY_REVIEW, "files": REGISTERED}, indent=2) + "\n", encoding="utf-8"
    )
    green = _run(repo)
    assert green.returncode == 0, green.stdout + green.stderr


def test_range_mode_sees_a_binary_added_by_the_change(tmp_path):
    repo = _repo(tmp_path)
    (repo / "assets" / "synthetic-second.png").write_bytes(PNG + b"x")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add another synthetic image")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_no_pii.py"), "--repo", str(repo), "--range", "HEAD~1..HEAD"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "assets/synthetic-second.png" in proc.stdout
    assert "binary_unreadable" in proc.stdout


def test_the_register_is_its_canonical_rendering():
    from scripts.lib.ci_gates import render

    path = ROOT / C.BINARY_REVIEW_REL
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc.get("schema") == C.SCHEMA_BINARY_REVIEW
    assert path.read_text(encoding="utf-8") == render(doc), (
        "config/pii_binary_review.json is not its canonical rendering; write it with scripts/lib/ci_gates.render()"
    )
