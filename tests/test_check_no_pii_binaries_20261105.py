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


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _register(
    repo: Path,
    *,
    reviewed: dict | None = None,
    grandfathered=None,
    count=None,
    sha=None,
    mutate=None,
) -> None:
    """Write the register in its canonical v2 shape. Each record's ``sha256`` is the digest of the file as it is in
    the working tree right now, unless ``mutate`` changes the built records (for malformed-register tests)."""
    grand = sorted(grandfathered if grandfathered is not None else [])
    files = {}
    for p, rec in (reviewed or {}).items():
        rec = dict(rec)
        rec.setdefault("sha256", _sha((repo / p).read_bytes()))
        files[p] = rec
    entries = {p: {"reason": "grandfathered, unreviewed", "sha256": _sha((repo / p).read_bytes())} for p in grand}
    if mutate:
        mutate(entries)
    doc = {
        "schema": C.SCHEMA_BINARY_REVIEW,
        "files": files,
        "grandfathered": entries,
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


REVIEWED = {
    TARGET: {
        "reason": "synthetic placeholder: no page, person or account",
        "reviewed_by": "cc-deepseek-3",
        "reviewed_at": "2026-11-05T14:00:00Z",
    }
}


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
        capture_output=True,
        text=True,
        timeout=120,
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
        capture_output=True,
        text=True,
        timeout=120,
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
        capture_output=True,
        text=True,
        timeout=120,
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
        capture_output=True,
        text=True,
        timeout=120,
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


# ── codex-cloud BLOCK at 73a3eccea: the register is evidence, not a path allowlist ────────────────
#
# CX1 the frozen enumeration is judged against a trusted ref (range base / HEAD / the gate-landing commit)
# CX2 every record pins the reviewed blob's sha256; a different blob is a finding
# CX3 a --staged scan reads the register from the index, never from the working tree


def _run_staged(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_no_pii.py"), "--repo", str(repo), "--staged"],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _run_range(repo: Path, rng: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_no_pii.py"), "--repo", str(repo), "--range", rng],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _head(repo: Path) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()


# ── CX1: a grandfathered addition must exist in the trusted ref ───────────────────────────────────


def test_a_grandfathered_path_absent_from_the_gate_landing_commit_is_refused(tmp_path):
    """codex-cloud P1 on #2691: adding a binary, its register record and an updated count/digest in one go must not
    authorize itself. The frozen enumeration is judged against the commit that landed the register, not itself."""
    repo = _repo(tmp_path, register=lambda r: _register(r, grandfathered=[TARGET]))
    new = "assets/example-capture.png"  # never in the tree when the gate landed
    (repo / new).write_bytes(PNG + b"a new capture")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add a capture")
    # Re-enumerate with the new path and a recomputed count/digest: internally consistent, still unauthorized.
    _register(repo, grandfathered=[TARGET, new])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "enumerate it")
    with pytest.raises(C.ScanError, match="cannot admit a path"):
        C.scan_tree(repo, deny=[])
    proc = _run(repo)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "cannot admit a path" in proc.stderr, proc.stderr


def test_the_gate_landing_enumeration_is_still_green(tmp_path):
    """Negative control for CX1: a path that WAS in the tree when the gate landed keeps its silence."""
    repo = _repo(tmp_path, register=lambda r: _register(r, grandfathered=[TARGET]))
    assert not [f for f in C.scan_tree(repo, deny=[]) if f.category.startswith("binary")]
    proc = _run(repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_an_unresolvable_trusted_grandfather_ref_refuses(tmp_path):
    """Fail closed: without the trusted ref the enumeration cannot be judged, so the scan is an error, not a pass."""
    repo = _repo(tmp_path, register=lambda r: _register(r, grandfathered=[TARGET]))
    with pytest.raises(C.ScanError, match="cannot be resolved"):
        C.scan_tree(repo, deny=[], trusted_ref="refs/heads/no-such-ref")


def test_range_mode_judges_grandfathering_against_the_range_base(tmp_path):
    """The range base is the trusted ref in --range mode: a path added after it cannot join the enumeration."""
    repo = _repo(tmp_path, register=lambda r: _register(r, grandfathered=[TARGET]))
    landing = _head(repo)
    new = "assets/example-capture.png"
    (repo / new).write_bytes(PNG + b"a new capture")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add a capture")
    _register(repo, grandfathered=[TARGET, new])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "enumerate it")
    with pytest.raises(C.ScanError, match="cannot admit a path"):
        C.scan_range(repo, f"{landing}..HEAD", deny=[])


# ── CX2: exemptions are bound to the blob, not the path ───────────────────────────────────────────


def test_replacing_a_reviewed_binary_is_a_content_mismatch(tmp_path):
    """codex-cloud P1 on #2691: a reviewed path is not a permanent allowlist; a different blob needs a review."""
    repo = _repo(tmp_path, register=lambda r: _register(r, reviewed=REVIEWED))
    (repo / TARGET).write_bytes(PNG + b"a live-page capture")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "replace the registered blob")
    mism = [f for f in C.scan_tree(repo, deny=[]) if f.category == "binary_review_mismatch"]
    assert [f.path for f in mism] == [TARGET], mism
    proc = _run(repo)
    assert proc.returncode == 1 and "content mismatch" in proc.stdout, proc.stdout + proc.stderr


def test_replacing_a_grandfathered_binary_is_a_content_mismatch(tmp_path):
    repo = _repo(tmp_path, register=lambda r: _register(r, grandfathered=[TARGET]))
    (repo / TARGET).write_bytes(PNG + b"a live-page capture")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "replace the grandfathered blob")
    mism = [f for f in C.scan_tree(repo, deny=[]) if f.category == "binary_review_mismatch"]
    assert [f.path for f in mism] == [TARGET], mism


def test_the_registered_blob_itself_stays_silent(tmp_path):
    """Negative control for CX2: the exact bytes a person registered are still exempt."""
    repo = _repo(tmp_path, register=lambda r: _register(r, reviewed=REVIEWED))
    assert not [f for f in C.scan_tree(repo, deny=[]) if f.category.startswith("binary")]


def test_a_register_record_without_a_digest_is_malformed(tmp_path):
    repo = _repo(
        tmp_path,
        register=lambda r: _register(r, grandfathered=[TARGET], mutate=lambda entries: entries[TARGET].pop("sha256")),
    )
    with pytest.raises(C.ScanError, match="sha256"):
        C.scan_tree(repo, deny=[])


def test_range_mode_sees_a_registered_binary_replaced_by_different_content(tmp_path):
    repo = _repo(tmp_path, register=lambda r: _register(r, grandfathered=[TARGET]))
    (repo / TARGET).write_bytes(PNG + b"a live-page capture")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "replace the registered blob")
    proc = _run_range(repo, "HEAD~1..HEAD")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "binary_review_mismatch" in proc.stdout and TARGET in proc.stdout


# ── CX3: a staged scan reads the register from the index ──────────────────────────────────────────


def _staged_review(repo: Path, data: bytes) -> None:
    _register(
        repo,
        reviewed={
            TARGET: {
                "reason": "synthetic placeholder; no page, person or account",
                "reviewed_by": "cc-deepseek-4-pii",
                "reviewed_at": "2026-11-05T22:00:00Z",
                "sha256": _sha(data),
            }
        },
    )


def test_staged_scan_ignores_a_review_record_that_is_not_staged(tmp_path):
    """codex-cloud P2 on #2691: exemptions for the staged snapshot come from the index. A review record left in the
    working tree must not authorize a commit that does not contain it."""
    repo = _repo(tmp_path)  # TARGET is committed, unregistered
    replacement = PNG + b"staged replacement"
    (repo / TARGET).write_bytes(replacement)
    _staged_review(repo, replacement)  # matches the staged blob, but the register is NOT staged
    _git(repo, "add", TARGET)  # stage only the binary
    proc = _run_staged(repo)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "binary_unreadable" in proc.stdout and TARGET in proc.stdout


def test_a_register_staged_with_the_binary_still_exempts_it(tmp_path):
    """Negative control for CX3: the same record, staged together with the blob, is a valid staged exemption."""
    repo = _repo(tmp_path)
    replacement = PNG + b"staged replacement"
    (repo / TARGET).write_bytes(replacement)
    _staged_review(repo, replacement)
    _git(repo, "add", "-A")
    proc = _run_staged(repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
