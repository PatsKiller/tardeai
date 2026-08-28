"""Guards for two failure modes that have each cost real time repeatedly.

Line endings, in order of appearance:
  * write_text() on a CRLF file converts the whole file to LF (3 incidents;
    diffs of 264 / 2451 / 1498 lines for a few real edits)
  * the obvious defence -- conditionally replacing \\n with \\r\\n -- applied to a
    file that ALREADY has CRLF produces \\r\\r\\n. 783 line endings, 2026-08-27.
    Python parsed it, tests passed, CI would have taken it. The only symptom was
    an implausible insertion count.
  * two attempts to measure that damage were themselves wrong: b'\\r\\n' inside a
    shell heredoc counts a literal backslash, reporting zero of everything.

sys.path: measurements run from a worktree read a data/ directory that does not
exist there, so every collector reports DATA_UNAVAILABLE. Twice.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.safe_text_edit import (  # noqa: E402
    CRLF, LF, LineEndingError, counts, detect, edit_text,
)


# ── detect ─────────────────────────────────────────────────────────────────

def test_detect_distinguishes_the_styles():
    assert detect(b"a\r\nb\r\n") == CRLF
    assert detect(b"a\nb\n") == LF
    assert detect(b"a\rb\r") == "cr"
    assert detect(b"a\r\nb\n") == "mixed"


def test_counts_are_not_confused_by_crlf_containing_both_bytes():
    """The measurement bug: \\r\\n contains \\r AND \\n, so naive counts double."""
    c = counts(b"a\r\nb\r\n")
    assert c == {"crlf": 2, "lone_cr": 0, "lone_lf": 0}


# ── the incident, prevented ────────────────────────────────────────────────

def test_editing_a_crlf_file_keeps_it_crlf(tmp_path):
    p = tmp_path / "f.py"
    p.write_bytes(b"x = 1\r\ny = 2\r\n")
    edit_text(p, [("x = 1", "x = 11")])
    raw = p.read_bytes()
    assert raw == b"x = 11\r\ny = 2\r\n"
    assert counts(raw)["lone_cr"] == 0, "no \\r\\r\\n"
    assert counts(raw)["lone_lf"] == 0, "not converted to LF"


def test_editing_an_lf_file_keeps_it_lf(tmp_path):
    p = tmp_path / "f.py"
    p.write_bytes(b"x = 1\ny = 2\n")
    edit_text(p, [("y = 2", "y = 3")])
    assert p.read_bytes() == b"x = 1\ny = 3\n"


def test_callers_write_plain_newlines_whatever_the_file_uses(tmp_path):
    """The ergonomic point: a caller must not have to know the file's style,
    because that is precisely the knowledge that keeps being got wrong."""
    p = tmp_path / "f.py"
    p.write_bytes(b"a = 1\r\nb = 2\r\n")
    edit_text(p, [("a = 1\nb = 2", "a = 1\nmid = 0\nb = 2")])
    assert p.read_bytes() == b"a = 1\r\nmid = 0\r\nb = 2\r\n"


def test_a_multiline_insertion_does_not_leak_lone_lf_into_a_crlf_file(tmp_path):
    p = tmp_path / "f.py"
    p.write_bytes(b"start\r\nend\r\n")
    edit_text(p, [("start", "start\nadded one\nadded two")])
    assert counts(p.read_bytes())["lone_lf"] == 0


# ── it refuses rather than guessing ────────────────────────────────────────

def test_a_mixed_file_is_refused(tmp_path):
    p = tmp_path / "f.py"
    p.write_bytes(b"a\r\nb\n")
    with pytest.raises(LineEndingError, match="mixed"):
        edit_text(p, [("a", "c")])


def test_a_non_unique_match_is_refused(tmp_path):
    """Silently editing the first of several occurrences is its own bug class."""
    p = tmp_path / "f.py"
    p.write_bytes(b"dup\ndup\n")
    with pytest.raises(LineEndingError, match="expected exactly 1"):
        edit_text(p, [("dup", "x")])


def test_a_missing_match_is_refused(tmp_path):
    p = tmp_path / "f.py"
    p.write_bytes(b"a\n")
    with pytest.raises(LineEndingError, match="found 0"):
        edit_text(p, [("nope", "x")])


def test_the_file_is_untouched_when_an_edit_is_refused(tmp_path):
    p = tmp_path / "f.py"
    p.write_bytes(b"a\r\nb\r\n")
    before = p.read_bytes()
    with pytest.raises(LineEndingError):
        edit_text(p, [("a", "c"), ("missing", "x")])
    assert p.read_bytes() == before, "a refused edit must not partially apply"


# ── the CI gate ────────────────────────────────────────────────────────────

def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _repo(tmp_path):
    _git("init", "-q", cwd=tmp_path)
    _git("config", "user.email", "t@t", cwd=tmp_path)
    _git("config", "user.name", "t", cwd=tmp_path)
    _git("config", "core.autocrlf", "false", cwd=tmp_path)
    return tmp_path


def _run_gate(cwd):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_line_endings.py")],
        cwd=cwd, capture_output=True, text=True)


def test_the_gate_fails_on_a_reconverted_file(tmp_path):
    """Mutation test: reproduce the incident and require a non-zero exit.

    The exit status is read directly. A prior gate in this repo reported a false
    pass because its command was piped into `tail`, so $? was tail's.
    """
    repo = _repo(tmp_path)
    f = repo / "big.py"
    f.write_bytes(b"".join(b"line_%d = %d\r\n" % (i, i) for i in range(300)))
    _git("add", "-A", cwd=repo); _git("commit", "-qm", "base", cwd=repo)

    raw = f.read_bytes()
    f.write_bytes(raw.replace(b"\n", b"\r\n"))      # the exact 08-27 bug
    _git("add", "-A", cwd=repo)
    assert _run_gate(repo).returncode == 1


def test_the_gate_passes_on_a_normal_edit(tmp_path):
    repo = _repo(tmp_path)
    f = repo / "big.py"
    f.write_bytes(b"".join(b"line_%d = %d\r\n" % (i, i) for i in range(300)))
    _git("add", "-A", cwd=repo); _git("commit", "-qm", "base", cwd=repo)

    edit_text(f, [("line_7 = 7", "line_7 = 70")])
    _git("add", "-A", cwd=repo)
    assert _run_gate(repo).returncode == 0


def test_the_gate_also_catches_crlf_collapsed_to_lf(tmp_path):
    """The write_text() failure mode, not just the double-conversion one."""
    repo = _repo(tmp_path)
    f = repo / "big.py"
    f.write_bytes(b"".join(b"line_%d = %d\r\n" % (i, i) for i in range(300)))
    _git("add", "-A", cwd=repo); _git("commit", "-qm", "base", cwd=repo)

    f.write_bytes(f.read_bytes().replace(b"\r\n", b"\n"))
    _git("add", "-A", cwd=repo)
    assert _run_gate(repo).returncode == 1


def test_a_small_whitespace_change_is_not_flagged(tmp_path):
    """Blank lines and reindents are legitimate; the floor keeps them quiet."""
    repo = _repo(tmp_path)
    f = repo / "small.py"
    f.write_bytes(b"a = 1\nb = 2\n")
    _git("add", "-A", cwd=repo); _git("commit", "-qm", "base", cwd=repo)
    f.write_bytes(b"a = 1\n\n\nb = 2\n")
    _git("add", "-A", cwd=repo)
    assert _run_gate(repo).returncode == 0


# ── the live-measurement runner ────────────────────────────────────────────

def test_measure_live_puts_the_release_first_not_the_worktree():
    src = (ROOT / "scripts/measure_live.py").read_text(encoding="utf-8")
    assert "CURRENT" in src
    assert "cwd=str(root)" in src, "the child must run from the live release"
    assert "sys.path.insert" in src


def test_measure_live_restores_and_verifies_swapped_files():
    src = (ROOT / "scripts/measure_live.py").read_text(encoding="utf-8")
    assert "finally:" in src, "a failed measurement must still restore"
    assert "_sha(dest)" in src and "RESTORE MISMATCH" in src, (
        "byte-identity after restore must be asserted, not assumed")
