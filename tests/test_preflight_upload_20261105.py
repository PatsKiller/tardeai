"""The automatic pre-upload check (operator D50 item 4): one refusal per readiness property.

Every test is hermetic. ``git`` runs against a brand-new temporary repository; ``gh_run`` is
replaced in-process, so no test reaches GitHub. Most tests also replace ``test_runner``; the
receipt/recorder controls for the per-file evidence and clean-source rules deliberately run the
real recorder and real ``pytest`` subprocesses inside their own temporary repository. The module is
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


def _repo(
    tmp_path: Path,
    branch_files: dict[str, str],
    base_files: dict[str, str] | None = None,
    branch: str = "wt/test",
) -> Path:
    """A real git repo on ``wt/test`` (or ``branch``) with ``origin/main`` at its base commit."""
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
    _git(root, "checkout", "-qb", branch)
    for rel, text in branch_files.items():
        _write(root, rel, text)
    _commit(root, "branch")
    return root


def _fake_gh(
    body: str = GOOD_BODY,
    title: str = TITLE,
    account_prs: list | None = None,
    branch_prs: dict[str, list] | None = None,
    view_rc: int = 0,
    list_rc: int = 0,
):
    def fake(args, cwd=None):
        if args[:2] == ["pr", "view"]:
            if view_rc != 0:
                return subprocess.CompletedProcess(args, view_rc, "", "no pull requests found for branch")
            return subprocess.CompletedProcess(args, 0, json.dumps({"number": 1, "title": title, "body": body}), "")
        if args[:2] == ["pr", "list"]:
            if list_rc != 0:
                return subprocess.CompletedProcess(args, list_rc, "", "github unavailable")
            if "--head" in args:
                branch = args[args.index("--head") + 1]
                rows = (branch_prs or {}).get(branch, [])
            else:
                rows = account_prs if account_prs is not None else []
            return subprocess.CompletedProcess(args, 0, json.dumps(rows), "")
        return subprocess.CompletedProcess(args, 1, "", "unexpected gh call")

    return fake


def _install(monkeypatch, mod, root: Path, gh=None, test_rc: int = 0, claims=None) -> None:
    monkeypatch.chdir(root)
    monkeypatch.setattr(mod, "gh_run", gh or _fake_gh())
    monkeypatch.setattr(mod, "test_runner", lambda cmd, cwd: test_rc)
    monkeypatch.setattr(
        mod,
        "claim_board_reader",
        lambda root, session: claims if claims is not None else ({"wt/test"}, ""),
    )


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


# ── (f) the WIP cap: drafts count, stale ownership counts, repairs are allowed ──────────


def _prs(numbers, draft=False):
    return [{"number": number, "isDraft": draft} for number in numbers]


def _three_owned(prefix=""):
    """Three claimed branches, each with one open PR (draft unless asked otherwise)."""
    return {branch: _prs((number,)) for number, branch in enumerate(("wt/a", "wt/b", "wt/c"), 1)}


def _all_rows(by_branch: dict[str, list]) -> list:
    return [row for rows in by_branch.values() for row in rows]


def _claim_script(board: dict) -> str:
    """A real ``scripts/agent_claim.py`` stand-in that prints exactly this status JSON."""
    return "import json\nprint(json.dumps(%s))\n" % json.dumps(board)


def test_three_owned_drafts_and_a_new_branch_refuse(tmp_path, monkeypatch, capsys):
    """Mutation: filter drafts out of this session's count -> the drafts read as zero, red."""
    root = _repo(tmp_path, {"docs/note.md": "note\n"})
    own = {branch: _prs((number,), draft=True) for number, branch in enumerate(("wt/a", "wt/b", "wt/c"), 1)}
    mod = _mod()
    _install(
        monkeypatch,
        mod,
        root,
        gh=_fake_gh(account_prs=_all_rows(own), branch_prs=own),
        claims=(set(own), ""),
    )
    rc = mod.main([])  # current branch wt/test would be a fourth
    out = capsys.readouterr().out
    assert rc == 1
    assert "would make 4 open pull requests" in out
    assert "drafts and stale-owned claims included" in out


def test_two_owned_drafts_plus_a_new_third_pass(tmp_path, monkeypatch, capsys):
    """Mutation: refuse at two own PRs -> this legitimate third upload goes red."""
    root = _repo(tmp_path, {"docs/note.md": "note\n"})
    own = {branch: _prs((number,), draft=True) for number, branch in enumerate(("wt/a", "wt/b"), 1)}
    mod = _mod()
    _install(
        monkeypatch,
        mod,
        root,
        gh=_fake_gh(account_prs=_all_rows(own), branch_prs=own),
        claims=(set(own), ""),
    )
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == ""


def test_repairing_the_third_open_pr_is_allowed(tmp_path, monkeypatch, capsys):
    """Mutation: count the candidate's own PR -> repairing the third is refused, red."""
    root = _repo(tmp_path, {"docs/note.md": "note\n"}, branch="wt/a")
    own = _three_owned()
    mod = _mod()
    _install(
        monkeypatch,
        mod,
        root,
        gh=_fake_gh(account_prs=_all_rows(own), branch_prs=own),
        claims=(set(own), ""),
    )
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == ""


def test_a_new_fourth_open_pr_is_refused(tmp_path, monkeypatch, capsys):
    """Mutation: change the limit from > to >= -> the fourth passes, red."""
    root = _repo(tmp_path, {"docs/note.md": "note\n"}, branch="wt/fourth")
    own = _three_owned()
    mod = _mod()
    _install(
        monkeypatch,
        mod,
        root,
        gh=_fake_gh(account_prs=_all_rows(own), branch_prs=own),
        claims=(set(own), ""),
    )
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "would make 4 open pull requests" in out
    assert "the limit is 3" in out


def test_stale_takeover_candidates_count_as_owned(tmp_path, monkeypatch, capsys):
    """Mutation: read only in_flight -> the stale-owned rows become zero, red.

    The claim reader is the real ``_read_claim_branches``; its subprocess prints a real
    ``AgentClaimStatus@v1`` document from a tracked stand-in script.
    """
    board = {
        "schema": "AgentClaimStatus@v1",
        "in_flight": [],
        "takeover_candidates": [
            {"session": "cc-test", "branch": branch, "state": "stale"} for branch in ("wt/a", "wt/b", "wt/c")
        ],
    }
    root = _repo(
        tmp_path,
        {"docs/note.md": "note\n"},
        base_files={"scripts/agent_claim.py": _claim_script(board)},
    )
    own = _three_owned()
    mod = _mod()
    monkeypatch.chdir(root)
    monkeypatch.setenv("AGENT_CLAIM_SESSION", "cc-test")
    monkeypatch.setattr(mod, "gh_run", _fake_gh(account_prs=_all_rows(own), branch_prs=own))
    monkeypatch.setattr(mod, "claim_board_reader", mod._read_claim_branches)
    assert mod._read_claim_branches(root, "cc-test") == ({"wt/a", "wt/b", "wt/c"}, "")
    rc = mod.main([])  # current branch wt/test would be a fourth
    out = capsys.readouterr().out
    assert rc == 1
    assert "would make 4 open pull requests" in out


def test_an_incomplete_claim_board_falls_back_instead_of_reading_zero(tmp_path, monkeypatch, capsys):
    """Mutation: treat a missing takeover_candidates list as empty -> zero ownership, red."""
    board = {"schema": "AgentClaimStatus@v1", "in_flight": []}  # no takeover_candidates
    root = _repo(
        tmp_path,
        {"docs/note.md": "note\n"},
        base_files={"scripts/agent_claim.py": _claim_script(board)},
    )
    fleet = _prs(range(100, 103))  # 3 open PRs, ownership unknown
    mod = _mod()
    monkeypatch.chdir(root)
    monkeypatch.setenv("AGENT_CLAIM_SESSION", "cc-test")
    monkeypatch.setattr(mod, "gh_run", _fake_gh(account_prs=fleet))
    monkeypatch.setattr(mod, "claim_board_reader", mod._read_claim_branches)
    branches, note = mod._read_claim_branches(root, "cc-test")
    assert branches is None
    assert "takeover_candidates" in note
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "could not be read completely" in out
    assert "this account has 3 open pull requests" in out
    assert "unknown" in out


def test_passes_when_the_account_has_many_but_none_are_this_sessions(tmp_path, monkeypatch, capsys):
    """Mutation: count the whole account instead of this session's branches -> this test goes red."""
    root = _repo(tmp_path, {"docs/note.md": "note\n"})
    fleet = _prs(range(100, 110))  # 10 open PRs across the shared account
    mod = _mod()
    _install(
        monkeypatch,
        mod,
        root,
        gh=_fake_gh(account_prs=fleet, branch_prs={"wt/mine": []}),
        claims=({"wt/mine"}, ""),
    )
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == ""


def test_unreadable_claim_board_falls_back_to_the_account_and_says_so(tmp_path, monkeypatch, capsys):
    """Mutation: pass when the claim board is unreadable instead of counting the account -> red."""
    root = _repo(tmp_path, {"docs/note.md": "note\n"})
    fleet = _prs(range(100, 110))  # 10 open PRs across the shared account
    mod = _mod()
    _install(
        monkeypatch,
        mod,
        root,
        gh=_fake_gh(account_prs=fleet),
        claims=(None, "the claim board could not be read (test)"),
    )
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "the claim board could not be read (test)" in out
    assert "counts the whole account" in out
    assert "this account has 10 open pull requests" in out
    assert "unknown" in out


def test_skip_wip_cap_passes_with_a_printed_warning(tmp_path, monkeypatch, capsys):
    """Mutation: send the warning to stdout -> the warning assertion goes red (the pass still holds)."""
    root = _repo(tmp_path, {"docs/note.md": "note\n"}, branch="wt/fourth")
    own = _three_owned()
    mod = _mod()
    _install(
        monkeypatch,
        mod,
        root,
        gh=_fake_gh(account_prs=_all_rows(own), branch_prs=own),
        claims=(set(own), ""),
    )
    rc = mod.main(["--skip-wip-cap"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert "WARNING: --skip-wip-cap was used" in captured.err


# ── F1: a genuine app-relative UI build registration is recognised ──────────────────────

UI_TEST = "apps/command-center-v3/src/lib/zz.test.ts"


def _ui_pkg(build: str) -> dict:
    return {"name": "command-center-v3", "scripts": {"build": build}}


def test_a_genuine_app_relative_ui_build_registration_passes(tmp_path, monkeypatch, capsys):
    """CX3-F1 mutation: search the repo-relative path in the app-relative build -> red.

    The build string runs from the app directory and names ``src/lib/zz.test.ts``; the module's own
    ``test_command`` uses that same form. A correctly registered UI change must not be refused.
    """
    root = _repo(
        tmp_path,
        {UI_TEST: "// ui test\n"},
        base_files={"apps/command-center-v3/package.json": json.dumps(_ui_pkg("tsc && node src/lib/zz.test.ts"))},
    )
    mod = _mod()
    _install(monkeypatch, mod, root)
    _record(mod, monkeypatch, root)
    capsys.readouterr()
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == ""
    assert mod.test_command(root, UI_TEST) == (["node", "src/lib/zz.test.ts"], root / "apps/command-center-v3")


def test_a_dot_slash_app_relative_ui_registration_passes(tmp_path, monkeypatch, capsys):
    """CX3-F1 mutation: compare raw tokens instead of normalising a leading ./ -> red."""
    root = _repo(
        tmp_path,
        {UI_TEST: "// ui test\n"},
        base_files={"apps/command-center-v3/package.json": json.dumps(_ui_pkg("node ./src/lib/zz.test.ts"))},
    )
    mod = _mod()
    _install(monkeypatch, mod, root)
    _record(mod, monkeypatch, root)
    capsys.readouterr()
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == ""


def test_ui_registration_ignores_a_substring_of_unrelated_text(tmp_path, monkeypatch, capsys):
    """CX3-F1 mutation: use a substring test -> prose/a longer token registers the test, red."""
    build = "tsc && echo " + UI_TEST + " && node src/lib/zz.test.ts.bak"
    root = _repo(
        tmp_path,
        {UI_TEST: "// ui test\n"},
        base_files={"apps/command-center-v3/package.json": json.dumps(_ui_pkg(build))},
    )
    mod = _mod()
    _install(monkeypatch, mod, root)
    _record(mod, monkeypatch, root)
    capsys.readouterr()
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "is not run by any 'node ...' step" in out
    assert "src/lib/zz.test.ts" in out


def test_ui_registration_requires_the_test_in_a_node_step(tmp_path, monkeypatch, capsys):
    """CX3-F1 mutation: accept the path in any step -> a typecheck-only mention registers it, red."""
    root = _repo(
        tmp_path,
        {UI_TEST: "// ui test\n"},
        base_files={"apps/command-center-v3/package.json": json.dumps(_ui_pkg("tsc src/lib/zz.test.ts && vite build"))},
    )
    mod = _mod()
    _install(monkeypatch, mod, root)
    _record(mod, monkeypatch, root)
    capsys.readouterr()
    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "is not run by any 'node ...' step" in out


# ── F2: a receipt must carry per-file successful execution evidence ─────────────────────

PASSING_TEST = "def test_ok():\n    assert True\n"
SKIPPED_TEST = (
    "import pytest\n\n"
    "@pytest.mark.skip(reason='intentionally skipped in this environment')\n"
    "def test_skipped():\n"
    "    assert True\n"
)


def _read_receipt(mod, root: Path) -> dict:
    return json.loads(mod.receipt_path(root, mod.head_sha(root)).read_text(encoding="utf-8"))


def test_a_real_passing_pytest_file_gets_a_validated_receipt(tmp_path):
    """CX3-F2 positive control: the real recorder writes a receipt the checker accepts."""
    root = _repo(tmp_path, {"tests/test_demo.py": PASSING_TEST})
    mod = _mod()
    assert mod.record_tests(root, verbose=False) == 0
    receipt = _read_receipt(mod, root)
    assert receipt["schema"] == "PreflightTestReceipt@v1"
    assert receipt["source_clean"] is True
    assert receipt["files"] == ["tests/test_demo.py"]
    row = receipt["results"][0]
    assert row["path"] == "tests/test_demo.py"
    assert row["exit_code"] == 0
    assert row["ran"] is True
    assert "1 passed" in row["output_tail"]
    assert mod.check_tests(root) == []


def test_a_real_all_skipped_pytest_file_is_refused(tmp_path):
    """CX3-F2 mutation: trust the exit code only -> an all-skipped file is certified, red."""
    root = _repo(tmp_path, {"tests/test_skip.py": SKIPPED_TEST})
    mod = _mod()
    assert mod.record_tests(root, verbose=False) == 1
    assert not mod.receipt_path(root, mod.head_sha(root)).exists()
    refusals = mod.check_tests(root)
    assert refusals
    assert refusals[0]["code"] == "tests-not-run"


def test_all_skipped_is_accepted_only_with_an_explicit_skip_tolerant_contract(tmp_path):
    """CX3-F2 mutation: drop the skip-tolerant contract check -> a forged receipt passes, red."""
    root = _repo(tmp_path, {"tests/test_skip.py": SKIPPED_TEST})
    mod = _mod()
    assert mod.record_tests(root, verbose=False, allow_skip_only={"tests/test_skip.py"}) == 0
    receipt = _read_receipt(mod, root)
    assert receipt["skip_tolerant"] == ["tests/test_skip.py"]
    assert receipt["results"][0]["ran"] is False
    assert mod.check_tests(root) == []
    receipt.pop("skip_tolerant")
    mod.receipt_path(root, mod.head_sha(root)).write_text(json.dumps(receipt), encoding="utf-8")
    refusals = mod.check_tests(root)
    assert refusals
    assert "no test executed" in refusals[0]["message"]


def test_a_receipt_without_a_successful_row_for_every_touched_file_is_refused(tmp_path):
    """CX3-F2 mutation: only look for a nonzero among whatever rows exist -> every variant passes, red."""
    root = _repo(tmp_path, {"tests/test_demo.py": PASSING_TEST})
    mod = _mod()
    assert mod.record_tests(root, verbose=False) == 0
    path = mod.receipt_path(root, mod.head_sha(root))
    genuine = json.loads(path.read_text(encoding="utf-8"))
    row = genuine["results"][0]
    variants: dict[str, dict] = {}
    missing = dict(genuine)
    missing.pop("results")
    variants["missing results"] = missing
    empty = dict(genuine)
    empty["results"] = []
    variants["empty results"] = empty
    unrelated = dict(genuine)
    unrelated["results"] = [{"path": "tests/test_other.py", "exit_code": 0, "ran": True}]
    variants["unrelated result"] = unrelated
    nothing_ran = dict(genuine)
    nothing_ran["results"] = [dict(row, ran=False)]
    variants["nothing ran"] = nothing_ran
    nonzero = dict(genuine)
    nonzero["results"] = [dict(row, exit_code=1)]
    variants["nonzero result"] = nonzero
    no_ran_field = dict(genuine)
    no_ran_field["results"] = [{k: v for k, v in row.items() if k != "ran"}]
    variants["no ran field"] = no_ran_field
    for name, doc in variants.items():
        path.write_text(json.dumps(doc), encoding="utf-8")
        refusals = mod.check_tests(root)
        assert refusals, name
        assert refusals[0]["code"] == "tests-not-run", name
    path.write_text(json.dumps(genuine), encoding="utf-8")
    assert mod.check_tests(root) == []


def test_a_receipt_that_skips_one_of_two_touched_files_is_refused(tmp_path):
    """CX3-F2 mutation: accept a receipt that covers only some touched files -> red."""
    root = _repo(
        tmp_path,
        {"tests/test_a.py": PASSING_TEST, "tests/test_b.py": PASSING_TEST},
    )
    mod = _mod()
    assert mod.record_tests(root, verbose=False) == 0
    path = mod.receipt_path(root, mod.head_sha(root))
    doc = json.loads(path.read_text(encoding="utf-8"))
    # Keep the files list complete; only the per-file execution row is missing.
    doc["results"] = [r for r in doc["results"] if r["path"] == "tests/test_a.py"]
    path.write_text(json.dumps(doc), encoding="utf-8")
    refusals = mod.check_tests(root)
    assert refusals
    assert "tests/test_b.py" in refusals[0]["message"]


# ── F3: the recorder binds evidence to the committed source it actually tested ──────────


def test_committed_failing_source_cannot_be_certified_by_a_dirty_passing_edit(tmp_path):
    """CX3-F3 mutation: snapshot HEAD but run the mutable working tree -> a green receipt, red."""
    root = _repo(tmp_path, {"tests/test_demo.py": "def test_ok():\n    assert False\n"})
    mod = _mod()
    head = mod.head_sha(root)
    assert mod.record_tests(root, verbose=False) == 1  # the committed test really fails
    assert not mod.receipt_path(root, head).exists()
    (root / "tests/test_demo.py").write_text(PASSING_TEST, encoding="utf-8")
    assert mod.head_sha(root) == head  # only the working tree changed
    assert mod.record_tests(root, verbose=False) == 1  # must refuse the dirty source
    assert not mod.receipt_path(root, head).exists()
    assert mod.check_tests(root)[0]["code"] == "tests-not-run"


def test_head_movement_during_the_run_cannot_create_a_bound_receipt(tmp_path, monkeypatch):
    """CX3-F3 mutation: stamp the pre-run HEAD without re-reading it -> a misbound receipt, red."""
    root = _repo(tmp_path, {"tests/test_demo.py": PASSING_TEST})
    mod = _mod()
    head_before = mod.head_sha(root)

    def moving_runner(cmd, cwd):
        _git(
            root,
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=t",
            "commit",
            "--allow-empty",
            "-qm",
            "move head during the run",
        )
        return mod.RunResult(0, "1 passed in 0.01s\n")

    monkeypatch.setattr(mod, "test_runner", moving_runner)
    assert mod.record_tests(root, verbose=False) == 1
    head_after = mod.head_sha(root)
    assert head_after != head_before
    assert not mod.receipt_path(root, head_before).exists()
    assert not mod.receipt_path(root, head_after).exists()


def test_a_run_that_dirties_tracked_source_is_refused(tmp_path, monkeypatch):
    """CX3-F3 mutation: check only before the run -> a mid-run source change is certified, red."""
    root = _repo(tmp_path, {"tests/test_demo.py": PASSING_TEST})
    mod = _mod()

    def dirtying_runner(cmd, cwd):
        (root / "README.md").write_text("changed during the run\n", encoding="utf-8")
        return mod.RunResult(0, "1 passed in 0.01s\n")

    monkeypatch.setattr(mod, "test_runner", dirtying_runner)
    assert mod.record_tests(root, verbose=False) == 1
    assert not mod.receipt_path(root, mod.head_sha(root)).exists()


def test_untracked_test_artifacts_do_not_block_recording(tmp_path):
    """CX3-F3 mutation: refuse on any untracked file -> a normal pytest artifact, red."""
    root = _repo(tmp_path, {"tests/test_demo.py": PASSING_TEST})
    (root / "tests" / "__pycache__").mkdir(parents=True)
    (root / "tests" / "__pycache__" / "x.pyc").write_bytes(b"\x00\x01")
    (root / "pytest.log").write_text("log\n", encoding="utf-8")
    mod = _mod()
    assert mod.record_tests(root, verbose=False) == 0
    assert mod.check_tests(root) == []


# ── machine-readable mode ──────────────────────────────────────────────────────────────


def test_json_mode_is_machine_readable(tmp_path, monkeypatch, capsys):
    """Mutation: omit 'refusals' from the JSON document -> the key assertion goes red."""
    root = _repo(tmp_path, {"docs/note.md": "note\n"}, branch="wt/fourth")
    own = _three_owned()
    mod = _mod()
    _install(
        monkeypatch,
        mod,
        root,
        gh=_fake_gh(account_prs=_all_rows(own), branch_prs=own),
        claims=(set(own), ""),
    )
    rc = mod.main(["--json"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 1  # --json still exits 1 on a refusal
    assert doc["schema"] == "PreflightUpload@v1"
    assert doc["ok"] is False
    assert doc["head_sha"] == mod.head_sha(root)
    assert doc["refusals"][0]["code"] == "wip-cap"
