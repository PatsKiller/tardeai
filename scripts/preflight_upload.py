#!/usr/bin/env python3
"""The automatic pre-upload check (operator D50 item 4).

Run this from a branch's own worktree before ``bin/agent-push``. A clean branch prints nothing and
exits 0. A branch that is not ready prints one plain-English reason per line and exits 1, so an
upload is refused locally instead of failing in review or in CI.

What it refuses, in operator language:

* **tests-not-run** — the test files this branch adds or changes were not run green at this exact
  commit in this exact checkout. ``--record-tests`` runs them against the committed source and
  writes a receipt under the worktree's git dir (``preflight/<full-head-sha>.json``). The default
  mode accepts only a validated receipt for the current head that carries a successful execution
  row for every touched test file; a receipt for another head, a missing or empty result list, an
  unrelated result, a nonzero exit, or a run where nothing executed (all skipped / no tests ran)
  is refused. Recording refuses a dirty tracked source tree or a head that moves during the run, so
  the receipt can never bind the committed head to different working files.
* **test-not-registered** — a new or renamed test would never run. A Python test must be named in
  some ``config/ci_gates/*.json``; a UI test must be named as an app-relative command token in a
  ``node ...`` step of ``apps/command-center-v3``'s ``package.json`` ``scripts.build`` (the string
  runs from the app directory, so it names ``src/lib/x.test.ts``, not the repository path).
* **plain-english** — the pull request description lacks its plain-English answers. This reuses the
  repository's own ``scripts/check_pr_plain_english.py`` (the six answers under
  ``## In plain English``); a draft is not exempt here because this runs before upload.
* **merge-conflict** — merging ``origin/main`` into this branch would conflict. The conflicted
  files are named.
* **binary-evidence** — a binary file was added under ``docs/evidence/``. Evidence must stay
  readable (text, JSON, Markdown, CSV).
* **wip-cap** — this upload would make a fourth open pull request for this session, counting drafts
  and stale-but-owned claims too (operator D50: at most three PRs at a time, sub-agents included).
  The session's branches come from the claim board (``agent_claim.py status --json``, both the
  ``in_flight`` and ``takeover_candidates`` rows, matched by ``AGENT_CLAIM_SESSION``); the
  candidate's own open PR is excluded, so repairing the third PR is allowed while a fourth new one
  is refused. The whole-account count is reported alongside so fleet noise is visible. If the claim
  board cannot be read completely, the check falls back to the whole account and says so. The
  threshold is ``MAX_OPEN_PRS``; ``--skip-wip-cap`` overrides it once and prints a warning.

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
import posixpath
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

BASE_REF = "origin/main"
UI_APP = "apps/command-center-v3"
EVIDENCE_PREFIX = "docs/evidence/"
MAX_OPEN_PRS = 3
RECEIPT_SCHEMA = "PreflightTestReceipt@v1"
RESULT_SCHEMA = "PreflightUpload@v1"

UI_TEST_RE = re.compile(r"\.(test|spec)\.(ts|tsx|js|jsx|mjs|cjs)$")

# Pytest's own summary, used to tell "one test executed" from "the run exited 0 without running a
# test" (all skipped, or no tests collected). Any command that prints no recognisable summary (a
# UI test run by node) is treated as having executed; the per-file receipt still has to say so.
_PYTEST_NO_TESTS_RE = re.compile(r"\bno tests ran\b", re.IGNORECASE)
_PYTEST_COLLECTED_ZERO_RE = re.compile(r"\bcollected 0 items\b", re.IGNORECASE)
_PYTEST_PASSED_RE = re.compile(r"\b(\d+) passed\b")
_PYTEST_FAILED_RE = re.compile(r"\b(\d+) failed\b")
_PYTEST_ERROR_RE = re.compile(r"\b(\d+) errors?\b")
_PYTEST_SKIPPED_RE = re.compile(r"\b(\d+) skipped\b")

HELP_TEXT = """\
Each refusal is one plain-English line and exit code 1; a clean run prints nothing and exits 0.

  tests-not-run        The test files this branch adds or changes were not run green at this
                       exact commit. Fix: run
                       `python3 scripts/preflight_upload.py --record-tests`
                       from this worktree at this head. The receipt must carry a successful
                       execution row for every touched file; a receipt for another head is refused
                       by name and is never accepted. Recording refuses a dirty tracked source
                       tree or a head that moves during the run.
  test-not-registered  A new or renamed test would never run in CI. Fix: name a Python test in a
                       config/ci_gates/<gate>.json file, or add a UI test as an app-relative path
                       (src/lib/x.test.ts) to a `node ...` step in the apps/command-center-v3
                       package.json "scripts.build" string.
  plain-english        The pull request lacks its plain-English answers. Fix: fill the six answers
                       under "## In plain English" in the PR description (the same rule as
                       scripts/check_pr_plain_english.py). A draft is not exempt.
  merge-conflict       origin/main can no longer be merged into this branch without a conflict.
                       Fix: `git merge origin/main`, resolve the named files, and commit.
  binary-evidence      A binary file was added under docs/evidence/. Fix: add readable text
                       (JSON, Markdown, CSV) instead.
  wip-cap              This upload would make a fourth open pull request for this session.
                       Drafts and stale-but-owned claims count; repairing one of the existing
                       three is allowed. Fix: finish or close one. The message also names the
                       whole-account count so fleet noise is visible. If the claim board cannot be
                       read completely, the whole account is counted and the message says so.
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


class RunResult(NamedTuple):
    """One executed test command: its exit code and the output that proves something ran."""

    exit_code: int
    output: str


def _run_test(cmd: list[str], cwd: Path) -> RunResult:
    """The one test runner. Tests replace this function; the receipt is still real."""
    try:
        proc = _run(cmd, cwd)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return RunResult(127, f"could not run: {exc}")
    output = (proc.stdout or "") + (proc.stderr or "")
    return RunResult(int(proc.returncode), output)


# Injectable boundary (tests replace this name only). It may return a RunResult, an exit-code int,
# a mapping with exit_code/returncode and output, or an object carrying those attributes.
test_runner = _run_test


def _normalise_run(raw) -> tuple[int, str]:
    """Read a runner answer from the real runner or one of the test doubles."""
    if isinstance(raw, bool):
        return int(raw), ""
    if isinstance(raw, int):
        return raw, ""
    if isinstance(raw, RunResult):
        return int(raw.exit_code), str(raw.output)
    if isinstance(raw, dict):
        code = raw.get("exit_code", raw.get("returncode", 1))
        return int(code), str(raw.get("output", ""))
    code = getattr(raw, "exit_code", getattr(raw, "returncode", raw))
    return int(code), str(getattr(raw, "output", ""))


def _executed_at_least_one(output: str) -> bool:
    """False when the command exited 0 without executing a single test.

    Pytest reports an all-skipped file as ``1 skipped in 0.02s`` and an empty collection as
    ``no tests ran`` — both exit 0. A command that prints no pytest-style summary at all (a node
    UI test) is treated as having executed: the evidence rule is per-file and the receipt must
    still claim so explicitly.
    """
    text = output or ""
    if _PYTEST_NO_TESTS_RE.search(text) or _PYTEST_COLLECTED_ZERO_RE.search(text):
        return False
    passed = sum(int(n) for n in _PYTEST_PASSED_RE.findall(text))
    failed = sum(int(n) for n in _PYTEST_FAILED_RE.findall(text))
    errors = sum(int(n) for n in _PYTEST_ERROR_RE.findall(text))
    skipped = sum(int(n) for n in _PYTEST_SKIPPED_RE.findall(text))
    if passed or failed or errors:
        return True
    if skipped:
        return False
    return True


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


def _normalise_test_path(value) -> str:
    """The one comparison form for a repository-relative path (exact after normalisation)."""
    text = str(value).replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return posixpath.normpath(text) if text else ""


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


def _receipt_results(receipt: dict) -> tuple[dict[str, list[dict]], str]:
    """Rows keyed by normalised path, or a plain-English reason the receipt is unvalidated."""
    results = receipt.get("results")
    if not isinstance(results, list) or not results:
        return {}, "it has no per-file results list"
    rows: dict[str, list[dict]] = {}
    for row in results:
        if not isinstance(row, dict):
            return {}, "a result row is not an object"
        path = row.get("path")
        if not isinstance(path, str) or not path.strip():
            return {}, "a result row names no path"
        rows.setdefault(_normalise_test_path(path), []).append(row)
    return rows, ""


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
    if receipt.get("schema") != RECEIPT_SCHEMA:
        return [
            _refusal(
                "tests-not-run",
                f"the test receipt {receipt_file} is not a validated {RECEIPT_SCHEMA} receipt; "
                f"re-run --record-tests at this head",
            )
        ]
    listed = receipt.get("files")
    if not isinstance(listed, list):
        return [
            _refusal(
                "tests-not-run",
                f"the test receipt {receipt_file} has no files list, so it cannot be validated; "
                f"re-run --record-tests at this head",
            )
        ]
    listed_set = {_normalise_test_path(p) for p in listed if isinstance(p, str)}
    missing = [p for p in touched if _normalise_test_path(p) not in listed_set]
    if missing:
        return [
            _refusal(
                "tests-not-run",
                f"the test receipt {receipt_file} did not run every touched test file; missing: "
                f"{', '.join(missing)}; re-run --record-tests at this head",
            )
        ]
    rows, invalid = _receipt_results(receipt)
    if invalid:
        return [
            _refusal(
                "tests-not-run",
                f"the test receipt {receipt_file} cannot be validated: {invalid}; "
                f"re-run --record-tests at this head",
            )
        ]
    tolerant = receipt.get("skip_tolerant")
    tolerant_set = (
        {_normalise_test_path(p) for p in tolerant if isinstance(p, str)}
        if isinstance(tolerant, list)
        else set()
    )
    problems: list[str] = []
    for path in touched:
        key = _normalise_test_path(path)
        entries = rows.get(key)
        if not entries:
            problems.append(f"{path} (no execution row)")
            continue
        if len(entries) != 1:
            problems.append(f"{path} ({len(entries)} execution rows)")
            continue
        row = entries[0]
        if row.get("exit_code") != 0:
            problems.append(f"{path} (exit {row.get('exit_code')})")
            continue
        allowed_skip = key in tolerant_set
        ran_flag = row.get("ran")
        tail = row.get("output_tail")
        derived = _executed_at_least_one(tail) if isinstance(tail, str) and tail else None
        if ran_flag is not True and not (ran_flag is False and allowed_skip):
            problems.append(f"{path} (no test executed)")
            continue
        if derived is False and not allowed_skip:
            problems.append(f"{path} (no test executed: all skipped or no tests ran)")
            continue
        if derived is False and allowed_skip and ran_flag is not False:
            problems.append(f"{path} (execution flag contradicts its output)")
    if problems:
        return [
            _refusal(
                "tests-not-run",
                f"the test receipt {receipt_file} lacks successful execution evidence for: "
                f"{'; '.join(problems)}; re-run --record-tests at this head",
            )
        ]
    return []


def ui_build_command(root: Path, path: str) -> list[str] | None:
    """The ``node ...`` build step that runs this UI test, or ``None``.

    ``scripts.build`` runs from ``apps/command-center-v3`` and names its files app-relatively
    (``src/lib/x.test.ts``). Match that exact command token — after normalising a leading ``./`` —
    never a substring of another token or of prose.
    """
    rel = _normalise_test_path(path[len(UI_APP) + 1 :])
    for segment in ui_build_string(root).split(" && "):
        try:
            tokens = shlex.split(segment.strip())
        except ValueError:
            continue
        if not tokens or Path(tokens[0]).name != "node":
            continue
        if any(_normalise_test_path(token) == rel for token in tokens[1:]):
            return tokens
    return None


def check_registered(root: Path) -> list[dict]:
    refusals: list[dict] = []
    for path in new_or_renamed(root):
        if not is_test_file(path):
            continue
        if is_ui_test(path):
            if ui_build_command(root, path) is None:
                rel = path[len(UI_APP) + 1 :]
                refusals.append(
                    _refusal(
                        "test-not-registered",
                        f"new UI test {path} is not run by any 'node ...' step in the {UI_APP}/"
                        f"package.json scripts.build string; add its app-relative path ({rel}) to "
                        f"that build gate (the UI test registration) or it never runs",
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
    """The branches this session owns, from the claim board. ``None`` means incomplete/unreadable.

    The board keeps live claims in ``in_flight`` and stale-but-owned (or done) claims in
    ``takeover_candidates``; a session's active work spans both. Both arrays must be present and
    every row of this session must name a branch, otherwise ownership is incomplete and this
    returns ``None`` so the caller falls back explicitly instead of reading an authoritative zero.
    """
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
    if not isinstance(doc, dict):
        return None, "the claim board returned no readable status object"
    rows: list = []
    for key in ("in_flight", "takeover_candidates"):
        value = doc.get(key)
        if not isinstance(value, list):
            return None, f"the claim board JSON has no {key} list, so this session's claims are incomplete"
        rows.extend(value)
    branches: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            return None, "the claim board JSON has a malformed claim row"
        if row.get("session") != session:
            continue
        branch = row.get("branch")
        if not isinstance(branch, str) or not branch.strip():
            return None, f"a claim for {session} names no branch, so this session's ownership is incomplete"
        branches.add(branch.strip())
    return branches, ""


# Injectable boundary (tests replace this name; no test reads the real claim board).
claim_board_reader = _read_claim_branches


def _pr_rows(proc) -> list | None:
    try:
        rows = json.loads(proc.stdout or "[]")
    except ValueError:
        return None
    return rows if isinstance(rows, list) else None


def _pr_objects(rows: list) -> list[dict]:
    return [row for row in rows if isinstance(row, dict)]


def _current_branch(root: Path) -> str:
    """The branch this upload updates, or "" when the checkout is detached/unknown."""
    try:
        name = _git(["rev-parse", "--abbrev-ref", "HEAD"], root, what="git rev-parse --abbrev-ref HEAD")
    except PreflightError:
        return ""
    name = name.stdout.strip()
    return "" if name == "HEAD" else name


def check_wip_cap(root: Path, skip: bool) -> list[dict]:
    """Refuse a fourth open PR for this session; report the account count for context.

    Every agent on this host shares one GitHub account, so ``gh pr list --author @me`` is the whole
    fleet. The session's branches come from the claim board (live and stale-but-owned rows); a PR is
    "this session's" when its head branch is one of those claims. Drafts count (D50 says at most
    three PRs, sub-agents included). The candidate's own open PR is excluded from the count so
    repairing the third existing PR is allowed; starting a fourth is not. If the claim board cannot
    be read completely, the whole account is counted and the refusal says so, so a reader can never
    mistake fleet noise or an unknown owner for their own work.
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
    account_count = len(_pr_objects(account_rows))

    session = os.environ.get("AGENT_CLAIM_SESSION", "").strip()
    branches, note = claim_board_reader(root, session)
    if branches is not None:
        own: dict[object, dict] = {}
        candidate_numbers: set[object] = set()
        current = _current_branch(root)
        complete = True
        for branch in sorted(branches):
            branch_proc = gh_run(["pr", "list", "--head", branch, "--state", "open", "--json", "number,isDraft"], root)
            rows = _pr_rows(branch_proc) if branch_proc.returncode == 0 else None
            if rows is None:
                note = f"could not read open pull requests for claimed branch {branch}"
                complete = False
                break
            for row in _pr_objects(rows):
                own[row.get("number")] = row
                if current and branch == current:
                    candidate_numbers.add(row.get("number"))
        if complete:
            other_count = len(set(own) - candidate_numbers)
            resulting = other_count + 1  # this upload creates exactly one PR, or updates the candidate
            if resulting > MAX_OPEN_PRS:
                numbers = ", ".join(f"#{row.get('number')}" for row in own.values())
                branch_list = ", ".join(sorted(branches)) or "(none)"
                return [
                    _refusal(
                        "wip-cap",
                        f"this upload would make {resulting} open pull requests for this session on its "
                        f"claimed branches ({branch_list}: {numbers}); the limit is {MAX_OPEN_PRS} at a "
                        f"time, drafts and stale-owned claims included (repairing one of the existing "
                        f"three is allowed); the whole account has {account_count} open pull requests; "
                        f"finish or close one (--skip-wip-cap overrides this check with a warning)",
                    )
                ]
            return []

    # The claim board (or a per-branch read) was incomplete: count the whole account and say so.
    if account_count >= MAX_OPEN_PRS:
        return [
            _refusal(
                "wip-cap",
                f"the claim board could not be read completely ({note}), so this counts the whole "
                f"account: this account has {account_count} open pull requests (drafts included), and "
                f"the number on this session's claimed branches is unknown; the limit is "
                f"{MAX_OPEN_PRS}; finish or close one (--skip-wip-cap overrides this check with a "
                f"warning)",
            )
        ]
    return []


def test_command(root: Path, path: str) -> tuple[list[str], Path]:
    """The command that runs one touched test file, and the directory it runs in."""
    if is_ui_test(path):
        rel = path[len(UI_APP) + 1 :]
        tokens = ui_build_command(root, path)
        if tokens is not None:
            return tokens, root / UI_APP
        return ["node", rel], root / UI_APP
    return [sys.executable, "-m", "pytest", "-q", path], root


def _tracked_source_changes(root: Path) -> list[str]:
    """Modified, staged or deleted *tracked* files. Untracked/ignored test artifacts are allowed."""
    out = _git(
        ["status", "--porcelain", "--untracked-files=no"],
        root,
        what="git status --porcelain --untracked-files=no",
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def _no_receipt_drift(root: Path, head: str, *, before: bool) -> int | None:
    """Refuse to write a receipt when the tested source is not the committed source."""
    label = "before" if before else "after"
    dirty = _tracked_source_changes(root)
    if dirty:
        print(
            f"preflight: refusing to record tests — tracked source is dirty {label} the run, so the "
            f"receipt would bind the committed head to different working files. Commit or stash these:"
        )
        for line in dirty:
            print(f"  {line}")
        return 1
    if not before:
        now = head_sha(root)
        if now != head:
            print(
                f"preflight: refusing to record tests — HEAD moved during the run ({head} -> {now}); "
                f"the evidence would be bound to the wrong commit. Re-run at the new head."
            )
            return 1
    return None


def record_tests(
    root: Path,
    *,
    verbose: bool = True,
    allow_skip_only: set[str] | None = None,
) -> int:
    allowed = {_normalise_test_path(p) for p in (allow_skip_only or set())}
    head = head_sha(root)
    touched = touched_test_files(root)
    if not touched:
        if verbose:
            print("preflight: this branch changes no test files; no receipt needed")
        return 0
    refused = _no_receipt_drift(root, head, before=True)
    if refused is not None:
        return refused
    results = []
    failed = []
    nothing_ran = []
    tolerated: set[str] = set()
    for path in touched:
        cmd, cwd = test_command(root, path)
        code, output = _normalise_run(test_runner(cmd, cwd))
        executed = _executed_at_least_one(output)
        key = _normalise_test_path(path)
        results.append(
            {
                "path": path,
                "command": cmd,
                "exit_code": code,
                "ran": executed,
                "output_tail": output[-4000:],
            }
        )
        if code != 0:
            failed.append((path, code))
        elif not executed:
            if key in allowed:
                tolerated.add(key)
            else:
                nothing_ran.append(path)
    refused = _no_receipt_drift(root, head, before=False)
    if refused is not None:
        return refused
    if failed:
        for path, code in failed:
            print(f"NOT GREEN (exit {code}): {path}")
        print("preflight: no receipt written because tests did not pass")
        return 1
    if nothing_ran:
        for path in nothing_ran:
            print(f"NOT RUN (no test executed, e.g. all skipped or no tests ran): {path}")
        print(
            "preflight: no receipt written because a touched test file did not execute a test; if it "
            "is intentionally skipped in this environment, re-run with --allow-skip-only <path> "
            "(recorded in the receipt as an explicit skip-tolerant contract)"
        )
        return 1
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "head_sha": head,
        "tree_sha": _git(["rev-parse", "HEAD^{tree}"], root, what="git rev-parse HEAD^{tree}").stdout.strip(),
        "base_ref": BASE_REF,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_clean": True,
        "files": [row["path"] for row in results],
        "results": results,
        "skip_tolerant": sorted(tolerated),
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
        help="skip the open-PR limit (prints a warning; for this check's own PR)",
    )
    parser.add_argument(
        "--allow-skip-only",
        action="append",
        default=[],
        metavar="PATH",
        help=(
            "with --record-tests, accept this touched test file when it executes nothing (all skipped) "
            "as an explicit skip-tolerant contract; repeatable, recorded in the receipt"
        ),
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
            code = record_tests(
                root,
                verbose=not args.json,
                allow_skip_only=set(args.allow_skip_only),
            )
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
                "WARNING: --skip-wip-cap was used; the open-PR limit "
                f"({MAX_OPEN_PRS}) was not checked",
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
