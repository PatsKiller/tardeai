"""A file the PII scanner cannot read is never clean (FQ-154).

Claude-lead, 2026-11-05: `_decode` returned None for any file with a NUL byte in its first 8 KiB and every caller
treated None as "nothing found", so every PNG, JPEG, PDF and archive was reported clean without being read — and two
live-page captures reached a public branch through it.

The gate lands as a FROZEN BASELINE so main stays green, following scripts/check_test_coverage.py's UNLISTED_BASELINE
pattern:

1. an unreadable file is a `binary_unreadable` FINDING unless it is in one of two registers;
2. `files` is a person's review (reason + reviewer + date); `grandfathered` is the frozen enumeration of the 150 files
   already in the tree on 2026-11-05, kept green without claiming review and admitting nothing new;
3. the enumeration states its own size and digest, so a deleted file, a smuggled path or a quietly enlarged list is a
   scan error or a `binary_baseline_drift` finding — never a silent pass;
4. the count prints on every run, and the category is not ratcheted, so a baseline number can never become permission.

Hermetic: temporary git repositories, no network, no real repository files.
"""
from __future__ import annotations

import hashlib
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
TARGET = "assets/synthetic-logo.png"


def _digest(paths) -> str:
    return hashlib.sha256("\n".join(sorted(paths)).encode("utf-8")).hexdigest()


def _register(repo: Path, *, reviewed: dict | None = None, grandfathered=None, count=None, sha=None) -> None:
    grand = sorted(grandfathered if grandfathered is not None else [])
    doc = {
        "schema": C.SCHEMA_BINARY_REVIEW,
        "files": reviewed or {},
        "grandfathered": {p: {"reason": "grandfathered, unreviewed"} for p in grand},
        "grandfathered_count": len(grand) if count is None else count,
        "grandfathered_sha256": _digest(grand) if sha is None else sha,
    }
    (repo / "config" / "pii_binary_review.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo(tmp_path: Path, *, register=None, with_png: bool = True) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "synthetic@example.com")
    _git(repo, "config", "user.name", "synthetic")
    (repo / "README.md").write_text("synthetic text, nothing personal\n", encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "pii_baseline.json").write_text(
        json.dumps({"schema": C.SCHEMA, "counts": {k: 0 for k in C.RATCHETED}}) + "\n", encoding="utf-8"
    )
    if with_png:
        (repo / "assets").mkdir()
        (repo / TARGET).write_bytes(PNG)
    if register:
        register(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "synthetic")
    return repo


REVIEWED = {TARGET: {"reason": "synthetic placeholder: no page, person or account", "reviewed_by": "cc-deepseek-3",
                     "reviewed_at": "2026-11-05T14:00:00Z"}}


def test_an_unreadable_file_is_a_finding_not_a_pass(tmp_path):
    repo = _repo(tmp_path)
    bins = [f for f in C.scan_tree(repo, deny=[], binary_review=C.EMPTY_REVIEW) if f.category == "binary_unreadable"]
    assert [f.path for f in bins] == [TARGET], bins
    assert "not registered" in bins[0].detail


def test_a_reviewed_file_is_silent(tmp_path):
    repo = _repo(tmp_path, register=lambda r: _register(r, reviewed=REVIEWED))
    assert not [f for f in C.scan_tree(repo, deny=[]) if f.category == "binary_unreadable"]


def test_a_grandfathered_file_is_silent_without_claiming_review(tmp_path):
    repo = _repo(tmp_path, register=lambda r: _register(r, grandfathered=[TARGET]))
    assert not [f for f in C.scan_tree(repo, deny=[]) if f.category == "binary_unreadable"]


def test_a_path_cannot_be_both_reviewed_and_grandfathered(tmp_path):
    repo = _repo(tmp_path, register=lambda r: _register(r, reviewed=REVIEWED, grandfathered=[TARGET]))
    with pytest.raises(C.ScanError, match="one-way"):
        C.scan_tree(repo, deny=[])


def test_the_enumeration_asserts_its_own_size_and_digest(tmp_path):
    repo = _repo(tmp_path, register=lambda r: _register(r, grandfathered=[TARGET], count=99))
    with pytest.raises(C.ScanError, match="states its own size"):
        C.scan_tree(repo, deny=[])
    (tmp_path / "b").mkdir()
    repo2 = _repo(tmp_path / "b", register=lambda r: _register(r, grandfathered=[TARGET], sha="0" * 64))
    with pytest.raises(C.ScanError, match="sha256"):
        C.scan_tree(repo2, deny=[])


def test_a_grandfathered_path_that_left_the_tree_is_drift_not_a_pass(tmp_path):
    repo = _repo(tmp_path, register=lambda r: _register(r, grandfathered=[TARGET]))
    (repo / TARGET).unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "delete the binary")
    drift = [f for f in C.scan_tree(repo, deny=[]) if f.category == "binary_baseline_drift"]
    assert [f.path for f in drift] == [TARGET]


def test_the_count_is_not_ratcheted(tmp_path):
    assert "binary_unreadable" in C.CATEGORIES
    assert "binary_unreadable" not in C.RATCHETED
    assert "binary_baseline_drift" not in C.RATCHETED


def _run(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_no_pii.py"), "--repo", str(repo), "--tree", *extra],
        capture_output=True, text=True, timeout=120,
    )


def test_the_three_directions(tmp_path):
    """unregistered -> 1; reviewed -> 0; grandfathered -> 0. This is the property main's green depends on."""
    plain = _repo(tmp_path / "a")
    red = _run(plain)
    assert red.returncode == 1 and TARGET in red.stdout, red.stdout + red.stderr
    assert "binaries: 1 unreadable not registered, 0 reviewed, 0 grandfathered, 0 baseline drift" in red.stdout

    reviewed = _repo(tmp_path / "b", register=lambda r: _register(r, reviewed=REVIEWED))
    green = _run(reviewed)
    assert green.returncode == 0, green.stdout + green.stderr
    assert "binaries: 0 unreadable not registered, 1 reviewed, 0 grandfathered, 0 baseline drift" in green.stdout

    grand = _repo(tmp_path / "c", register=lambda r: _register(r, grandfathered=[TARGET]))
    old = _run(grand)
    assert old.returncode == 0, old.stdout + old.stderr
    assert "binaries: 0 unreadable not registered, 0 reviewed, 1 grandfathered, 0 baseline drift" in old.stdout


def test_write_baseline_cannot_swallow_an_unreadable_file(tmp_path):
    repo = _repo(tmp_path)
    refused = _run(repo, "--write-baseline")
    assert refused.returncode == 1 and "REFUSED" in refused.stderr


def test_range_mode_sees_a_binary_added_by_the_change(tmp_path):
    repo = _repo(tmp_path, register=lambda r: _register(r, grandfathered=[TARGET]))
    (repo / "assets" / "synthetic-second.png").write_bytes(PNG + b"x")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add another synthetic image")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_no_pii.py"), "--repo", str(repo), "--range", "HEAD~1..HEAD"],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "assets/synthetic-second.png" in proc.stdout and "binary_unreadable" in proc.stdout


def test_range_mode_sees_a_text_file_replaced_with_binary(tmp_path):
    """A modification (status M) carries no text hunks once the content is binary: it must still be read."""
    repo = _repo(tmp_path, with_png=False)
    (repo / "notes.txt").write_text("plain text, nothing personal\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add a text file")
    (repo / "notes.txt").write_bytes(PNG)  # status M, and a binary diff carries no text hunks
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "replace it with binary content")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_no_pii.py"), "--repo", str(repo), "--range", "HEAD~1..HEAD"],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "notes.txt" in proc.stdout and "binary_unreadable" in proc.stdout


def test_staged_mode_sees_a_modified_unregistered_binary(tmp_path):
    """Modifying an already-unregistered binary was skipped: --staged reported the change clean."""
    repo = _repo(tmp_path)  # TARGET is committed unregistered
    (repo / TARGET).write_bytes(PNG + b"different")
    _git(repo, "add", "-A")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_no_pii.py"), "--repo", str(repo), "--staged"],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert TARGET in proc.stdout and "binary_unreadable" in proc.stdout


def test_a_nul_containing_text_file_is_unreadable_not_clean(tmp_path):
    """Named .txt with a NUL byte is still unreadable: the verdict is a finding, never a silent pass."""
    repo = _repo(tmp_path, with_png=False)
    (repo / "nul-notes.txt").write_bytes(b"plain text\nhidden\x00payload\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add a NUL-containing text file")
    findings = [f for f in C.scan_tree(repo, deny=[]) if f.path == "nul-notes.txt"]
    assert [f.category for f in findings] == ["binary_unreadable"], findings


def test_the_register_is_its_canonical_rendering():
    from scripts.lib.ci_gates import render

    path = ROOT / C.BINARY_REVIEW_REL
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc.get("schema") == C.SCHEMA_BINARY_REVIEW
    assert doc["grandfathered_count"] == len(doc["grandfathered"])
    assert doc["grandfathered_sha256"] == _digest(doc["grandfathered"])
    assert path.read_text(encoding="utf-8") == render(doc), (
        "config/pii_binary_review.json is not its canonical rendering; write it with scripts/lib/ci_gates.render()"
    )
