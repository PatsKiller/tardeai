"""The automatic pre-upload check (operator D50 item 4): one refusal per readiness property.

Every test is hermetic. ``git`` runs against a brand-new temporary repository; ``gh_run`` and
``test_runner`` are replaced in-process, so no test reaches GitHub or starts pytest. The module is
loaded from ``scripts/preflight_upload.py`` exactly as an agent runs it.

Each test names the production mutation that makes it go red (the three-state proof is recorded in
the PR body): break only that property, watch this test fail, restore, watch it pass.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GOOD_BODY = """## In plain English
**What changes:** The upload check refuses a branch that is not ready instead of failing later.
**Why:** D50 item 4 asked for one local gate before an agent uploads a branch.
**Who / what it affects:** Only agents uploading from their own worktree; nothing the operator sees changes.
**When it takes effect:** The next upload after merge.
**Approval:** Digest tap.
**Risk and fallback:** A false refusal costs one fix; revert the PR to undo.

## Technical detail
- Files: scripts/preflight_upload.py
"""
TITLE = "Pre-upload check refuses incomplete uploads"

GATE = {
    "schema": "CiGate@v1",
    "name": "demo_20261105",
    "files": ["tests/test_demo.py"],
}
PACKAGE = {"name": "command-center-v3", "scripts": {"build": "tsc && vite build"}}


def _mod():
    spec = importlib.util.spec_from_file_location("preflight_upload_t", ROOT / "scripts/preflight_upload.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def _git(root: Path, *args: str, check: bool = True):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=check, timeout=60)


def _commit(root: Path, message: str = "change") -> None:
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "-A")
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", message)


def _write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path, branch_files: dict[str, str], base_files: dict[str, str] | None = None) -> Path:
    """A real git repo on ``wt/test`` with ``origin/main`` at its base commit."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    base = {
        "README.md": "base\n",
        "config/ci_gates/demo_20261105.json": json.dumps(GATE),
        "apps/command-center-v3/package.json": json.dumps(PACKAGE),
    }
    base.update(base_files or {})
    for rel, text in base.items():
        _write(root, rel, text)
    _commit(root, "base")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(root, "checkout", "-qb", "wt/test")
    for rel, text in branch_files.items():
        _write(root, rel, text)
    _commit(root, "branch")
    return root


def _fake_gh(body: str = GOOD_BODY, title: str = TITLE, prs: list | None = None, view_rc: int = 0):
    def fake(args, cwd=None):
        if args[:2] == ["pr", "view"]:
            if view_rc != 0:
                return subprocess.CompletedProcess(args, view_rc, "", "no pull requests found for branch")
            return subprocess.CompletedProcess(args, 0, json.dumps({"number": 1, "title": title, "body": body}), "")
        if args[:2] == ["pr", "list"]:
            return subprocess.CompletedProcess(args, 0, json.dumps(prs if prs is not None else []), "")
        return subprocess.CompletedProcess(args, 1, "", "unexpected gh call")

    return fake


def _install(monkeypatch, mod, root: Path, gh=None, test_rc: int = 0) -> None:
    monkeypatch.chdir(root)
    monkeypatch.setattr(mod, "gh_run", gh or _fake_gh())
    monkeypatch.setattr(mod, "test_runner", lambda cmd, cwd: test_rc)


def _record(mod, monkeypatch, root: Path) -> None:
    monkeypatch.chdir(root)
    monkeypatch.setattr(mod, "test_runner", lambda cmd, cwd: 0)
    assert mod.main(["--record-tests"]) == 0


# ── one passing case ────────────────────────────────────────────────────────────────────


def test_a_fully_ready_branch_passes_and_prints_nothing(tmp_path, monkeypatch, capsys):
    """Mutation: make check_plain_english return one refusal for this body -> this test goes red.

    (That is the only property claimed: a branch whose six answers are complete passes; a
    production edit that refuses a complete description makes the empty-output assertion fail.)
    """
    root = _repo(tmp_path, {"tests/test_demo.py": "def test_ok():\n    assert True\n"})
    mod = _mod()
    _install(monkeypatch, mod, root)
    _record(mod, monkeypatch, root)
    capsys.readouterr()
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == ""
    head = mod.head_sha(root)
    receipt = json.loads((root / ".git" / "preflight" / f"{head}.json").read_text(encoding="utf-8"))
    assert receipt["head_sha"] == head
    assert receipt["files"] == ["tests/test_demo.py"]
    assert receipt["results"][0]["exit_code"] == 0


# ── (a) tests not run green at this head ───────────────────────────────────────────────


def test_refuses_when_the_tests_were_not_run_at_this_head(tmp_path, monkeypatch, capsys):
    """Mutation: make check_tests return [] without reading the receipt -> this test goes red."""
    root = _repo(tmp_path, {"tests/test_demo.py": "def test_ok():\n    assert True\n"})
    mod = _mod()
    _install(monkeypatch, mod, root)
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert f"no test receipt for the current head {mod.head_sha(root)}" in out
    assert "--record-tests" in out


def test_a_receipt_for_a_different_head_is_refused_by_name(tmp_path, monkeypatch, capsys):
    """Mutation: drop the head_sha comparison in check_tests -> the old receipt is accepted, red."""
    root = _repo(tmp_path, {"tests/test_demo.py": "def test_ok():\n    assert True\n"})
    mod = _mod()
    other = "a" * 40
    folder = root / ".git" / "preflight"
    folder.mkdir(parents=True)
    # A receipt exists at this head's path but claims another head: it must be named and refused.
    (folder / f"{mod.head_sha(root)}.json").write_text(
        json.dumps({"schema": "PreflightTestReceipt@v1", "head_sha": other, "files": ["tests/test_demo.py"]}),
        encoding="utf-8",
    )
    _install(monkeypatch, mod, root)
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert other in out
    assert "a receipt for a different head is worthless" in out


def test_no_receipt_names_an_older_receipt(tmp_path, monkeypatch, capsys):
    """Mutation: do not list older receipts when this head has none -> the old head is unnamed, red."""
    root = _repo(tmp_path, {"tests/test_demo.py": "def test_ok():\n    assert True\n"})
    mod = _mod()
    other = "b" * 40
    folder = root / ".git" / "preflight"
    folder.mkdir(parents=True)
    (folder / f"{other}.json").write_text(
        json.dumps({"schema": "PreflightTestReceipt@v1", "head_sha": other, "files": ["tests/test_demo.py"]}),
        encoding="utf-8",
    )
    _install(monkeypatch, mod, root)
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert other in out
    assert "different head" in out


def test_record_tests_writes_the_receipt_only_when_every_file_is_green(tmp_path, monkeypatch, capsys):
    """Mutation: write the receipt before the exit-code check -> the failing run leaves one, red."""
    root = _repo(tmp_path, {"tests/test_demo.py": "def test_ok():\n    assert True\n"})
    mod = _mod()
    monkeypatch.chdir(root)
    monkeypatch.setattr(mod, "test_runner", lambda cmd, cwd: 1)
    rc = mod.main(["--record-tests"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "NOT GREEN (exit 1)" in out
    assert not (root / ".git" / "preflight").exists()


# ── (b) a new or renamed test is registered nowhere ────────────────────────────────────


def test_refuses_a_python_test_that_no_ci_gate_names(tmp_path, monkeypatch, capsys):
    """Mutation: make registered_in_gate return True unconditionally -> this test goes red."""
    other_gate = {"schema": "CiGate@v1", "name": "demo_20261105", "files": ["tests/test_other.py"]}
    root = _repo(
        tmp_path,
        {"tests/test_demo.py": "def test_ok():\n    assert True\n"},
        base_files={"config/ci_gates/demo_20261105.json": json.dumps(other_gate)},
    )
    mod = _mod()
    _install(monkeypatch, mod, root)
    _record(mod, monkeypatch, root)
    capsys.readouterr()
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "tests/test_demo.py is registered in no config/ci_gates/*.json" in out
    assert "config/ci_gates/demo.json" in out


def test_refuses_a_ui_test_missing_from_the_build_string(tmp_path, monkeypatch, capsys):
    """Mutation: make is_ui_test return False -> the UI test is never checked, red."""
    root = _repo(
        tmp_path,
        {"apps/command-center-v3/src/lib/zz.test.ts": "// ui test\n"},
        base_files={
            "apps/command-center-v3/package.json": json.dumps(
                {"name": "command-center-v3", "scripts": {"build": "tsc"}}
            )
        },
    )
    mod = _mod()
    _install(monkeypatch, mod, root)
    _record(mod, monkeypatch, root)
    capsys.readouterr()
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "apps/command-center-v3/src/lib/zz.test.ts" in out
    assert "scripts.build" in out


# ── (c) the PR description lacks its plain-English answers ─────────────────────────────


def test_refuses_a_pr_body_without_the_plain_english_answers(tmp_path, monkeypatch, capsys):
    """Mutation: make check_plain_english return [] -> this test goes red."""
    root = _repo(tmp_path, {"docs/note.md": "note\n"})
    mod = _mod()
    _install(monkeypatch, mod, root, gh=_fake_gh(body="just a description"))
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "plain-English rule" in out
    assert "In plain English" in out


def test_refuses_when_no_pull_request_can_be_read(tmp_path, monkeypatch, capsys):
    """Mutation: ignore gh's return code in check_plain_english -> an unknown body passes, red."""
    root = _repo(tmp_path, {"docs/note.md": "note\n"})
    mod = _mod()
    _install(monkeypatch, mod, root, gh=_fake_gh(view_rc=1))
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "no pull request could be read" in out


# ── (d) origin/main would conflict ─────────────────────────────────────────────────────


def test_refuses_a_merge_that_would_conflict_and_names_the_file(tmp_path, monkeypatch, capsys):
    """Mutation: treat a non-zero merge-tree as mergeable -> this test goes red."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _write(root, "f.txt", "base\n")
    _commit(root, "base")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(root, "checkout", "-qb", "wt/test")
    _write(root, "f.txt", "branch\n")
    _commit(root, "branch side")
    _git(root, "checkout", "-q", "main")
    _write(root, "f.txt", "main\n")
    _commit(root, "main side")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(root, "checkout", "-q", "wt/test")
    mod = _mod()
    _install(monkeypatch, mod, root, gh=_fake_gh(body=GOOD_BODY))
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "would conflict" in out
    assert "f.txt" in out


# ── (e) a binary file under docs/evidence/ ─────────────────────────────────────────────


def test_refuses_a_binary_file_added_under_evidence(tmp_path, monkeypatch, capsys):
    """Mutation: skip the NUL/numstat test in _is_binary -> the binary passes, red."""
    root = _repo(tmp_path, {"docs/evidence/shot.png": ""})
    (root / "docs/evidence/shot.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00more")
    _commit(root, "evidence")
    mod = _mod()
    _install(monkeypatch, mod, root)
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "binary file docs/evidence/shot.png" in out
    assert "readable" in out


# ── (f) three open non-draft PRs ───────────────────────────────────────────────────────


def test_refuses_at_three_open_non_draft_prs(tmp_path, monkeypatch, capsys):
    """Mutation: change the threshold comparison from >= to > -> this test goes red."""
    root = _repo(tmp_path, {"docs/note.md": "note\n"})
    prs = [{"number": 1, "isDraft": False}, {"number": 2, "isDraft": False}, {"number": 3, "isDraft": False}]
    mod = _mod()
    _install(monkeypatch, mod, root, gh=_fake_gh(prs=prs))
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "3 open non-draft pull requests" in out
    assert "the limit is 3" in out


def test_skip_wip_cap_passes_with_a_printed_warning(tmp_path, monkeypatch, capsys):
    """Mutation: remove the WARNING print -> the warning assertion goes red (the pass still holds)."""
    root = _repo(tmp_path, {"docs/note.md": "note\n"})
    prs = [{"number": 1, "isDraft": False}, {"number": 2, "isDraft": False}, {"number": 3, "isDraft": False}]
    mod = _mod()
    _install(monkeypatch, mod, root, gh=_fake_gh(prs=prs))
    rc = mod.main(["--skip-wip-cap"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert "WARNING: --skip-wip-cap was used" in captured.err


# ── machine-readable mode ──────────────────────────────────────────────────────────────


def test_json_mode_is_machine_readable(tmp_path, monkeypatch, capsys):
    """Mutation: omit 'refusals' from the JSON document -> the key assertion goes red."""
    root = _repo(tmp_path, {"docs/note.md": "note\n"})
    prs = [{"number": 1, "isDraft": False}, {"number": 2, "isDraft": False}, {"number": 3, "isDraft": False}]
    mod = _mod()
    _install(monkeypatch, mod, root, gh=_fake_gh(prs=prs))
    rc = mod.main(["--json"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert doc["schema"] == "PreflightUpload@v1"
    assert doc["ok"] is False
    assert doc["head_sha"] == mod.head_sha(root)
    assert doc["refusals"][0]["code"] == "wip-cap"
