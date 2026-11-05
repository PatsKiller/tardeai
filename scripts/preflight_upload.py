#!/usr/bin/env python3
"""The automatic pre-upload check (operator D50 item 4).

Run this from a branch's own worktree before ``bin/agent-push``. A clean branch prints nothing and
exits 0. A branch that is not ready prints one plain-English reason per line and exits 1, so an
upload is refused locally instead of failing in review or in CI.

What it refuses, in operator language:

* **tests-not-run** — the test files this branch adds or changes were not run green at this exact
  commit in this exact checkout. ``--record-tests`` runs them and writes a receipt under the
  worktree's git dir (``preflight/<full-head-sha>.json``). The default mode accepts only a receipt
  for the current head that covers every touched test file; a receipt for another head is named
  and refused.
* **test-not-registered** — a new or renamed test would never run. A Python test must be named in
  some ``config/ci_gates/*.json``; a UI test must be named in ``apps/command-center-v3``'s
  ``package.json`` ``scripts.build``.
* **plain-english** — the pull request description lacks its plain-English answers. This reuses the
  repository's own ``scripts/check_pr_plain_english.py`` (the six answers under
  ``## In plain English``); a draft is not exempt here because this runs before upload.
* **merge-conflict** — merging ``origin/main`` into this branch would conflict. The conflicted
  files are named.
* **binary-evidence** — a binary file was added under ``docs/evidence/``. Evidence must stay
  readable (text, JSON, Markdown, CSV).
* **wip-cap** — this session already has three open non-draft pull requests. The session's branches
  come from the claim board (``agent_claim.py status --json``, matched by ``AGENT_CLAIM_SESSION``);
  the whole-account count is reported alongside so fleet noise is visible. If the claim board cannot
  be read, the check falls back to the whole account and says so. The threshold is
  ``MAX_OPEN_NON_DRAFT_PRS``; ``--skip-wip-cap`` overrides it once and prints a warning.

Inputs are read with ``git``, the ``gh`` CLI and the claim board only. ``--json`` prints a
machine-readable result. Hermetic tests replace ``gh_run``, ``test_runner`` and
``claim_board_reader``; ``git`` runs against a temporary repository.

AUTHORITY: READ_ONLY_ADVISORY (local upload gate; no broker, no DB, no write beyond its own receipt).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_REF = "origin/main"
UI_APP = "apps/command-center-v3"
EVIDENCE_PREFIX = "docs/evidence/"
MAX_OPEN_NON_DRAFT_PRS = 3
RECEIPT_SCHEMA = "PreflightTestReceipt@v1"
RESULT_SCHEMA = "PreflightUpload@v1"

UI_TEST_RE = re.compile(r"\.(test|spec)\.(ts|tsx|js|jsx|mjs|cjs)$")

HELP_TEXT = """\
Each refusal is one plain-English line and exit code 1; a clean run prints nothing and exits 0.

  tests-not-run        The test files this branch adds or changes were not run green at this
                       exact commit. Fix: run
                       `python3 scripts/preflight_upload.py --record-tests`
                       from this worktree at this head. A receipt for another head is refused by
                       name and is never accepted.
  test-not-registered  A new or renamed test would never run in CI. Fix: name a Python test in a
                       config/ci_gates/<gate>.json file, or add a UI test to the
                       apps/command-center-v3 package.json "scripts.build" string.
  plain-english        The pull request lacks its plain-English answers. Fix: fill the six answers
                       under "## In plain English" in the PR description (the same rule as
                       scripts/check_pr_plain_english.py). A draft is not exempt.
  merge-conflict       origin/main can no longer be merged into this branch without a conflict.
                       Fix: `git merge origin/main`, resolve the named files, and commit.
  binary-evidence      A binary file was added under docs/evidence/. Fix: add readable text
                       (JSON, Markdown, CSV) instead.
  wip-cap              This session already has MAX_OPEN_NON_DRAFT_PRS (3) open non-draft pull
                       requests on its claimed branches. Fix: finish or close one. The message
                       also names the whole-account count so fleet noise is visible. If the claim
                       board cannot be read, the whole account is counted and the message says so.
                       --skip-wip-cap overrides this one check and prints a warning; it is for the
                       check's own PR.
"""


class PreflightError(RuntimeError):
    """A git/gh read failed in a way that makes the answer unknowable. Never a silent pass."""


def _run(cmd: list[str], cwd: Path | None = None, *, timeout: int = 120, text: bool = True):
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=text,
        timeout=timeout,
    )


def _git(args: list[str], root: Path, *, text: bool = True, what: str = "git"):
    try:
        proc = _run(["git", *args], root, text=text)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreflightError(f"{what} could not run: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or b"") if isinstance(proc.stderr, bytes) else (proc.stderr or "")
        detail = detail.decode("utf-8", "replace") if isinstance(detail, bytes) else detail
        detail = detail.strip().splitlines()[0] if detail.strip() else f"exit {proc.returncode}"
        raise PreflightError(f"{what} failed ({detail})")
    return proc


def gh_run(args: list[str], cwd: Path | None = None):
    """The one GitHub reader. Tests replace this function; no test reaches GitHub."""
    try:
        return _run(["gh", *args], cwd)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(["gh", *args], 127, "", str(exc))


def _run_test(cmd: list[str], cwd: Path) -> int:
    """The one test runner. Tests replace this function; the receipt is still real."""
    try:
        return _run(cmd, cwd).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 127


# Injectable boundaries (tests replace these two names only).
test_runner = _run_test


def repo_root() -> Path:
    proc = _run(["git", "rev-parse", "--show-toplevel"])
    if proc.returncode != 0:
        raise PreflightError("this is not a git worktree; run the check from the branch's own worktree")
    return Path(proc.stdout.strip())


def head_sha(root: Path) -> str:
    return _git(["rev-parse", "HEAD"], root, what="git rev-parse HEAD").stdout.strip()


def git_dir(root: Path) -> Path:
    raw = _git(["rev-parse", "--git-dir"], root, what="git rev-parse --git-dir").stdout.strip()
    path = Path(raw)
    return path if path.is_absolute() else (root / path)


def _changed(root: Path, diff_filter: str) -> list[str]:
    out = _git(
        ["diff", "--name-only", f"--diff-filter={diff_filter}", f"{BASE_REF}...HEAD"],
        root,
        what=f"git diff {BASE_REF}...HEAD",
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def is_python_test(path: str) -> bool:
    if path.startswith(UI_APP + "/") or not path.endswith(".py"):
        return False
    name = path.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py")


def is_ui_test(path: str) -> bool:
    return path.startswith(UI_APP + "/") and bool(UI_TEST_RE.search(path.rsplit("/", 1)[-1]))


def is_test_file(path: str) -> bool:
    return is_python_test(path) or is_ui_test(path)


def touched_test_files(root: Path) -> list[str]:
    """Test files this branch adds, changes, copies or renames (never deletes)."""
    return sorted(p for p in _changed(root, "ACMR") if is_test_file(p))


def new_or_renamed(root: Path) -> list[str]:
    out = _git(
        ["diff", "--name-status", "--diff-filter=AR", f"{BASE_REF}...HEAD"],
        root,
        what=f"git diff --name-status {BASE_REF}...HEAD",
    ).stdout
    paths: list[str] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if not parts:
            continue
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3:
            paths.append(parts[2])  # the new path is the one that must be registered
        elif status.startswith("A") and len(parts) >= 2:
            paths.append(parts[1])
    return paths


def receipt_path(root: Path, head: str) -> Path:
    return git_dir(root) / "preflight" / f"{head}.json"


def gate_name_for(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if name.endswith(".py"):
        name = name[:-3]
    if name.startswith("test_"):
        name = name[5:]
    elif name.endswith("_test"):
        name = name[:-5]
    return name or "new_gate"


def registered_in_gate(root: Path, path: str) -> bool:
    gates = root / "config" / "ci_gates"
    if not gates.is_dir():
        return False
    for gate in sorted(gates.glob("*.json")):
        try:
            doc = json.loads(gate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        files = doc.get("files") if isinstance(doc, dict) else None
        if isinstance(files, list) and path in files:
            return True
    return False


def ui_build_string(root: Path) -> str:
    pkg = root / UI_APP / "package.json"
    try:
        doc = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    scripts = doc.get("scripts") if isinstance(doc, dict) else None
    build = scripts.get("build") if isinstance(scripts, dict) else None
    return build if isinstance(build, str) else ""


def _refusal(code: str, message: str) -> dict:
    return {"code": code, "message": " ".join(message.split())}


def check_tests(root: Path) -> list[dict]:
    head = head_sha(root)
    touched = touched_test_files(root)
    if not touched:
        return []
    receipt_file = receipt_path(root, head)
    if not receipt_file.is_file():
        others = []
        folder = receipt_file.parent
        if folder.is_dir():
            others = sorted(p.stem for p in folder.glob("*.json") if p.stem != head)
        msg = (
            f"no test receipt for the current head {head}; run "
            f"'python3 scripts/preflight_upload.py --record-tests' at this head in this worktree"
        )
        if others:
            msg += (
                f" (a receipt exists for {', '.join(others)}, but a receipt for a different head "
                f"is worthless and is refused)"
            )
        return [_refusal("tests-not-run", msg)]
    try:
        receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [_refusal("tests-not-run", f"the test receipt {receipt_file} is unreadable ({exc})")]
    if not isinstance(receipt, dict) or receipt.get("head_sha") != head:
        recorded = receipt.get("head_sha") if isinstance(receipt, dict) else None
        return [
            _refusal(
                "tests-not-run",
                f"the test receipt {receipt_file} is for {recorded}, not the current head {head}; "
                f"a receipt for a different head is worthless",
            )
        ]
    ran = receipt.get("files")
    ran_set = set(ran) if isinstance(ran, list) else set()
    missing = [p for p in touched if p not in ran_set]
    if missing:
        return [
            _refusal(
                "tests-not-run",
                f"the test receipt {receipt_file} did not run every touched test file; missing: "
                f"{', '.join(missing)}; re-run --record-tests at this head",
            )
        ]
    results = receipt.get("results")
    failed = [
        str(row.get("path"))
        for row in (results if isinstance(results, list) else [])
        if isinstance(row, dict) and row.get("exit_code") != 0
    ]
    if failed:
        return [
            _refusal(
                "tests-not-run",
                f"the test receipt {receipt_file} records a non-zero exit for: {', '.join(failed)}",
            )
        ]
    return []


def check_registered(root: Path) -> list[dict]:
    refusals: list[dict] = []
    build = ui_build_string(root)
    for path in new_or_renamed(root):
        if not is_test_file(path):
            continue
        if is_ui_test(path):
            if path not in build:
                refusals.append(
                    _refusal(
                        "test-not-registered",
                        f"new UI test {path} is not in the {UI_APP}/package.json scripts.build string; "
                        f"add it to that build gate (the UI test registration) or it never runs",
                    )
                )
        elif not registered_in_gate(root, path):
            refusals.append(
                _refusal(
                    "test-not-registered",
                    f"new Python test {path} is registered in no config/ci_gates/*.json; add it to a "
                    f"gate, for example config/ci_gates/{gate_name_for(path)}.json",
                )
            )
    return refusals


def _plain_english_module():
    candidate = Path(__file__).resolve().parent / "check_pr_plain_english.py"
    if not candidate.is_file():
        return None
    spec = importlib.util.spec_from_file_location("preflight_pr_plain_english", candidate)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_plain_english(root: Path, body_file: str | None, title_arg: str | None) -> list[dict]:
    title = title_arg or ""
    body = ""
    if body_file:
        try:
            body = Path(body_file).read_text(encoding="utf-8")
        except OSError as exc:
            return [_refusal("plain-english", f"could not read the PR body file {body_file}: {exc}")]
    else:
        proc = gh_run(["pr", "view", "--json", "number,title,body"], root)
        if proc.returncode != 0:
            detail = (proc.stderr or "").strip().splitlines()
            why = detail[0] if detail else "no pull request was found"
            return [
                _refusal(
                    "plain-english",
                    f"no pull request could be read for this branch ({why}); open the draft PR with "
                    f"the '## In plain English' section, or pass --pr-body-file",
                )
            ]
        try:
            data = json.loads(proc.stdout or "{}")
        except ValueError:
            data = {}
        title = str(data.get("title") or "")
        body = str(data.get("body") or "")

    mod = _plain_english_module()
    if mod is not None:
        errors = mod.check(title, body)
    else:  # the repository checker is missing; keep its one binding rule
        errors = [] if "## In plain English" in body else ["description has no '## In plain English' section"]
    return [_refusal("plain-english", f"PR description fails the plain-English rule: {error}") for error in errors]


def check_merge(root: Path) -> list[dict]:
    proc = _run(["git", "merge-tree", "--write-tree", "--name-only", BASE_REF, "HEAD"], root)
    if proc.returncode == 0:
        return []
    conflicted: list[str] = []
    lines = (proc.stdout or "").splitlines()
    for line in lines[1:]:
        if not line.strip():
            break
        if line.startswith(("CONFLICT", "Auto-merging", "Auto-merging:")):
            break
        conflicted.append(line.strip())
    if not conflicted:
        for line in (proc.stdout or "").splitlines() + (proc.stderr or "").splitlines():
            m = re.search(r"(?:Merge conflict in|CONFLICT[^:]*:)\s*(.+)$", line)
            if m:
                conflicted.append(m.group(1).strip())
    files = ", ".join(sorted(set(conflicted)))
    msg = "merging origin/main into this branch would conflict"
    msg += f" in: {files}" if files else f" (git merge-tree exited {proc.returncode})"
    return [_refusal("merge-conflict", msg)]


def _added_evidence(root: Path) -> list[str]:
    return [p for p in _changed(root, "A") if p.startswith(EVIDENCE_PREFIX)]


def _is_binary(root: Path, path: str) -> bool:
    proc = _run(["git", "show", f"HEAD:{path}"], root, text=False)
    if proc.returncode == 0 and b"\x00" in (proc.stdout or b"")[:8000]:
        return True
    numstat = _run(["git", "diff", "--numstat", "--diff-filter=A", f"{BASE_REF}...HEAD", "--", path], root)
    return numstat.returncode == 0 and any(line.startswith("-\t-") for line in numstat.stdout.splitlines())


def check_evidence(root: Path) -> list[dict]:
    return [
        _refusal(
            "binary-evidence",
            f"binary file {path} was added under {EVIDENCE_PREFIX}; evidence must stay readable as "
            f"text (JSON, Markdown, CSV)",
        )
        for path in _added_evidence(root)
        if _is_binary(root, path)
    ]


def _read_claim_branches(root: Path, session: str) -> tuple[set[str] | None, str]:
    """The branches this session claims, from the claim board. ``None`` means unreadable."""
    if not session:
        return None, "AGENT_CLAIM_SESSION is not set, so this session's claims cannot be identified"
    script = root / "scripts" / "agent_claim.py"
    if not script.is_file():
        return None, f"{script} is missing from this worktree"
    try:
        proc = _run([sys.executable, str(script), "status", "--json"], root, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"the claim board could not be read ({exc})"
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        why = detail[0] if detail else f"exit {proc.returncode}"
        return None, f"the claim board could not be read ({why})"
    try:
        doc = json.loads(proc.stdout or "{}")
    except ValueError:
        return None, "the claim board returned unreadable JSON"
    rows = doc.get("in_flight") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return None, "the claim board JSON has no in_flight list"
    branches = {
        str(row.get("branch"))
        for row in rows
        if isinstance(row, dict) and row.get("session") == session and row.get("branch")
    }
    return branches, ""


# Injectable boundary (tests replace this name; no test reads the real claim board).
claim_board_reader = _read_claim_branches


def _non_draft(rows: list) -> list[dict]:
    return [row for row in rows if isinstance(row, dict) and not row.get("isDraft")]


def _pr_rows(proc) -> list | None:
    try:
        rows = json.loads(proc.stdout or "[]")
    except ValueError:
        return None
    return rows if isinstance(rows, list) else None


def check_wip_cap(root: Path, skip: bool) -> list[dict]:
    """Count only this session's non-draft PRs; report the account count for context.

    Every agent on this host shares one GitHub account, so ``gh pr list --author @me`` is the whole
    fleet. The session's branches come from the claim board; a PR is "this session's" when its head
    branch is one of those claims. If the claim board cannot be read, the whole account is counted
    and the refusal says so, so a reader can never mistake fleet noise for their own work.
    """
    if skip:
        return []
    proc = gh_run(["pr", "list", "--author", "@me", "--state", "open", "--json", "number,isDraft"], root)
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        why = detail[0] if detail else "no answer from GitHub"
        return [_refusal("wip-cap", f"could not read your open pull requests ({why})")]
    account_rows = _pr_rows(proc)
    if account_rows is None:
        return [_refusal("wip-cap", "GitHub returned an unreadable answer for your open pull requests")]
    account_count = len(_non_draft(account_rows))

    session = os.environ.get("AGENT_CLAIM_SESSION", "").strip()
    branches, note = claim_board_reader(root, session)
    if branches is not None:
        own: dict[object, dict] = {}
        for branch in sorted(branches):
            branch_proc = gh_run(["pr", "list", "--head", branch, "--state", "open", "--json", "number,isDraft"], root)
            rows = _pr_rows(branch_proc) if branch_proc.returncode == 0 else None
            if rows is None:
                branches, note = None, f"could not read open pull requests for claimed branch {branch}"
                break
            for row in _non_draft(rows):
                own[row.get("number")] = row
        if branches is not None:
            own_count = len(own)
            if own_count >= MAX_OPEN_NON_DRAFT_PRS:
                numbers = ", ".join(f"#{row.get('number')}" for row in own.values())
                branch_list = ", ".join(sorted(branches))
                return [
                    _refusal(
                        "wip-cap",
                        f"this account has {account_count} open non-draft pull requests, {own_count} of them "
                        f"on this session's claimed branches ({branch_list}: {numbers}); the limit is "
                        f"{MAX_OPEN_NON_DRAFT_PRS} for this session; finish or close one "
                        f"(--skip-wip-cap overrides this check with a warning)",
                    )
                ]
            return []

    # The claim board (or a per-branch read) failed: fall back to the whole account, and say so.
    if account_count >= MAX_OPEN_NON_DRAFT_PRS:
        return [
            _refusal(
                "wip-cap",
                f"the claim board could not be read ({note}), so this counts the whole account: this "
                f"account has {account_count} open non-draft pull requests, and the number on this "
                f"session's claimed branches is unknown; the limit is {MAX_OPEN_NON_DRAFT_PRS}; finish "
                f"or close one (--skip-wip-cap overrides this check with a warning)",
            )
        ]
    return []


def test_command(root: Path, path: str) -> tuple[list[str], Path]:
    """The command that runs one touched test file, and the directory it runs in."""
    if is_ui_test(path):
        rel = path[len(UI_APP) + 1 :]
        for segment in ui_build_string(root).split(" && "):
            try:
                tokens = shlex.split(segment.strip())
            except ValueError:
                continue
            if rel in tokens:
                return tokens, root / UI_APP
        return ["node", rel], root / UI_APP
    return [sys.executable, "-m", "pytest", "-q", path], root


def record_tests(root: Path, *, verbose: bool = True) -> int:
    head = head_sha(root)
    touched = touched_test_files(root)
    if not touched:
        if verbose:
            print("preflight: this branch changes no test files; no receipt needed")
        return 0
    results = []
    failed = []
    for path in touched:
        cmd, cwd = test_command(root, path)
        code = int(test_runner(cmd, cwd))
        results.append({"path": path, "command": cmd, "exit_code": code})
        if code != 0:
            failed.append((path, code))
    if failed:
        for path, code in failed:
            print(f"NOT GREEN (exit {code}): {path}")
        print("preflight: no receipt written because tests did not pass")
        return 1
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "head_sha": head,
        "base_ref": BASE_REF,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": [row["path"] for row in results],
        "results": results,
    }
    target = receipt_path(root, head)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if verbose:
        print(f"preflight: recorded {len(results)} test file(s) for {head} at {target}")
    return 0


def run_checks(root: Path, args) -> list[dict]:
    refusals: list[dict] = []
    refusals += check_tests(root)
    refusals += check_registered(root)
    refusals += check_plain_english(root, args.pr_body_file, args.pr_title)
    refusals += check_merge(root)
    refusals += check_evidence(root)
    refusals += check_wip_cap(root, args.skip_wip_cap)
    return refusals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refuse to upload a branch that is not ready (operator D50 item 4).",
        epilog=HELP_TEXT,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--record-tests",
        action="store_true",
        help="run the touched test files and write a receipt for the current head under the worktree's git dir",
    )
    parser.add_argument("--json", action="store_true", help="print a machine-readable result and nothing else")
    parser.add_argument(
        "--skip-wip-cap",
        action="store_true",
        help="skip the open-non-draft-PR limit (prints a warning; for this check's own PR)",
    )
    parser.add_argument(
        "--pr-body-file",
        help="read the PR description from this file instead of asking GitHub (offline and tests)",
    )
    parser.add_argument("--pr-title", help="the PR title to check with --pr-body-file")
    args = parser.parse_args(argv)

    try:
        root = repo_root()
        if args.record_tests:
            code = record_tests(root, verbose=not args.json)
            if args.json:
                doc = {
                    "schema": RECEIPT_SCHEMA,
                    "ok": code == 0,
                    "head_sha": head_sha(root),
                    "receipt": str(receipt_path(root, head_sha(root))),
                }
                print(json.dumps(doc, indent=2, sort_keys=True))
            return code
        head = head_sha(root)
        if args.skip_wip_cap:
            print(
                "WARNING: --skip-wip-cap was used; the open-non-draft-PR limit "
                f"({MAX_OPEN_NON_DRAFT_PRS}) was not checked",
                file=sys.stderr,
            )
        refusals = run_checks(root, args)
    except PreflightError as exc:
        refusals = [_refusal("repo-error", str(exc))]
        head = ""

    if args.json:
        doc = {
            "schema": RESULT_SCHEMA,
            "ok": not refusals,
            "head_sha": head,
            "base_ref": BASE_REF,
            "skipped": {"wip_cap": bool(args.skip_wip_cap)},
            "refusals": refusals,
        }
        print(json.dumps(doc, indent=2, sort_keys=True))
    else:
        for refusal in refusals:
            print(refusal["message"])
    return 0 if not refusals else 1


if __name__ == "__main__":
    raise SystemExit(main())
