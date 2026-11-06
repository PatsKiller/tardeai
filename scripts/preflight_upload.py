#!/usr/bin/env python3
"""The automatic pre-upload check (operator D50 item 4).

Run this from a branch's own worktree before ``bin/agent-push``. A clean branch prints nothing and
exits 0. A branch that is not ready prints one plain-English reason per line and exits 1, so an
upload is refused locally instead of failing in review or in CI.

What it refuses, in operator language:

* **tests-not-run** — the test files this branch adds or changes were not run green at this exact
  commit in this exact checkout. ``--record-tests`` runs them with ``TRADE_AI_CI=1`` forced on
  every test child, against the committed source, and writes a receipt under the worktree's git
  dir (``preflight/<full-head-sha>.json``). The default mode accepts only a validated receipt for
  the current head that carries a successful execution row for every touched test file. Execution
  is read from a structured runner result (pytest's ``--junitxml`` report, else its final summary
  line), never from prose. A receipt for another head, a missing or empty result list, an unsafe
  path alias, an unrelated result, a nonzero exit, or a run where nothing executed (all skipped /
  no tests ran, including a Node runner that selected zero tests) is refused. Recording refuses
  dirty tracked source, untracked source or config that could change execution (ignored files
  included, anywhere in the worktree, because the repository root and ``scripts`` are import
  roots), and a head that moves during the run, so the receipt can never bind the committed head
  to different working files. A zero-assertion run is tolerated only for a file the reviewed
  project list ``config/ci_skip_tolerant_units.json`` names with a reason; the list's provenance
  is bound to ``origin/main``, so a branch that edits it gets no tolerance. There is no
  caller-selected waiver.
* **test-not-registered** — a new or renamed test would never run. A Python test must be named in
  some ``config/ci_gates/*.json``; a UI test must be the executable input of a ``node ...`` step
  of ``apps/command-center-v3``'s ``package.json`` ``scripts.build`` (the string runs from the app
  directory, so it names ``src/lib/x.test.ts``, not the repository path). A test that appears only
  as an argument to another script (``node driver.cjs x.test.ts``), as a post-script
  ``--test``/script argv, or under a non-executing mode (``--check``, ``--version``) is not
  registered.
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
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

BASE_REF = "origin/main"
UI_APP = "apps/command-center-v3"
EVIDENCE_PREFIX = "docs/evidence/"
MAX_OPEN_PRS = 3
RECEIPT_SCHEMA = "PreflightTestReceipt@v1"
RESULT_SCHEMA = "PreflightUpload@v1"
SKIP_TOLERANT_REL = "config/ci_skip_tolerant_units.json"
CI_ENV = {"TRADE_AI_CI": "1"}

UI_TEST_RE = re.compile(r"\.(test|spec)\.(ts|tsx|js|jsx|mjs|cjs)$")

# Pytest's OWN final summary line. Only the last non-empty line is parsed, so a warning or prose
# line that happens to quote a passing count can never be read as a test outcome.
_PYTEST_SUMMARY_LINE_RE = re.compile(r"\bin \d+(?:\.\d+)?s\b")
_PYTEST_SUMMARY_COUNT_RE = re.compile(r"\b(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b")

# Untracked files that cannot change what a test execution does. Anything else untracked (a
# module, conftest, pytest config or fixture) is refused: it can make a committed test pass.
# Only CACHED bytecode is inert. A ``.pyc`` inside ``__pycache__`` is used only when the source it
# was compiled from is present and matches, so it cannot satisfy an import by itself. A sourceless
# ``.pyc`` placed where a module would live (the legacy location outside ``__pycache__``) IS
# importable, and ``.pyd``/``.so`` extension modules are importable anywhere: those are source.
_INERT_UNTRACKED_RE = re.compile(
    r"(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.hypothesis|htmlcov)(/|$)"
    r"|\.(coverage|log)$"
    r"|(^|/)coverage\.(xml|json)$"
    r"|(^|/)\.coverage(\..*)?$"
)

HELP_TEXT = """\
Each refusal is one plain-English line and exit code 1; a clean run prints nothing and exits 0.

  tests-not-run        The test files this branch adds or changes were not run green at this
                       exact commit. Fix: run
                       `python3 scripts/preflight_upload.py --record-tests`
                       from this worktree at this head. Every test child runs with TRADE_AI_CI=1.
                       The receipt must carry a successful execution row for every touched file;
                       a receipt for another head is refused by name and is never accepted.
                       Recording refuses dirty tracked source, untracked source or config that
                       could change execution (gitignored files included, anywhere in the
                       worktree), and a head that moves during the run. An all-skipped run is
                       tolerated only for a file listed with a reason in
                       config/ci_skip_tolerant_units.json, and only when this branch does not
                       change that list; there is no caller waiver.
  test-not-registered  A new or renamed test would never run in CI. Fix: name a Python test in a
                       config/ci_gates/<gate>.json file, or add a UI test as an app-relative path
                       (src/lib/x.test.ts) to a `node ...` step in the apps/command-center-v3
                       package.json "scripts.build" string. It must be the file node really
                       executes: a `--check`/`--version` mode or a `--test` after the script
                       itself does not count.
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


def _run(
    cmd: list[str],
    cwd: Path | None = None,
    *,
    timeout: int = 120,
    text: bool = True,
    env: dict[str, str] | None = None,
):
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=text,
        timeout=timeout,
        env=env,
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
    """The one test runner. Tests replace this function; the receipt is still real.

    Every real test child is forced into the required CI safety mode (AGENTS.md §24.6,
    ``TRADE_AI_CI=1``). The parent value is overridden, so an unset or explicitly unsafe caller
    environment cannot reach a test that reads production state.
    """
    env = dict(os.environ, **CI_ENV)
    try:
        proc = _run(cmd, cwd, env=env)
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


def _pytest_summary_counts(output: str) -> dict[str, int] | None:
    """Counts from pytest's final summary line, or ``None`` when there is no such line.

    Only the last non-empty line is considered. Pytest prints its summary last ("1 skipped, 1
    warning in 0.02s"); an earlier warning or prose line that quotes a passing count is not a
    runner result and must never be read as one.
    """
    lines = [line for line in (output or "").strip().splitlines() if line.strip()]
    if not lines:
        return None
    last = lines[-1]
    if "no tests ran" in last.lower():
        return {}
    if not _PYTEST_SUMMARY_LINE_RE.search(last):
        return None
    counts: dict[str, int] = {}
    for number, kind in _PYTEST_SUMMARY_COUNT_RE.findall(last):
        kind = "errors" if kind.startswith("error") else kind
        counts[kind] = counts.get(kind, 0) + int(number)
    return counts or None


def _counts_executed(counts: dict | None) -> bool | None:
    """True when the structured result says at least one test executed; None when unknown."""
    if not isinstance(counts, dict):
        return None
    ran = 0
    for kind in ("passed", "failed", "errors", "xfailed", "xpassed"):
        value = counts.get(kind, 0)
        if isinstance(value, int):
            ran += value
    return ran > 0


#: Node's TAP summary counters (``# tests 1`` / ``# pass 0`` / ...) and its plan line (``1..0``).
_NODE_TAP_COUNTER_RE = re.compile(r"^# (tests|pass|fail|skipped|todo|cancelled)\s+(\d+)$")
_NODE_TAP_PLAN_RE = re.compile(r"^1\.\.(\d+)$")


def _node_tap_counts(output: str) -> dict[str, int] | None:
    """Per-outcome counts from a Node test-runner TAP report, or None when there is none.

    Node's test runner (direct or under ``--test``) prints a TAP summary. A run in which the
    runner selected nothing prints the plan ``1..0`` and can still exit 0 — an outer file wrapper
    may even report ``# pass 1`` — so a zero plan is treated as zero executed. ``pass`` + ``fail``
    are the tests that actually ran; ``skipped``/``todo`` did not.
    """
    counters: dict[str, int] = {}
    zero_plan = False
    for raw in (output or "").splitlines():
        line = raw.strip()
        counter = _NODE_TAP_COUNTER_RE.match(line)
        if counter:
            counters[counter.group(1)] = int(counter.group(2))
            continue
        plan = _NODE_TAP_PLAN_RE.match(line)
        if plan and int(plan.group(1)) == 0:
            zero_plan = True
    if not counters and not zero_plan:
        return None
    if zero_plan:
        return {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": counters.get("skipped", 0)}
    return {
        "total": counters.get("tests", 0),
        "passed": counters.get("pass", 0),
        "failed": counters.get("fail", 0),
        "errors": 0,
        "skipped": counters.get("skipped", 0),
    }


def _junit_counts(path: Path | None) -> dict[str, int] | None:
    """Per-outcome counts from a pytest ``--junitxml`` report, or None when it is unusable."""
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    total = skipped = failed = errors = 0
    for case in root.iter("testcase"):
        total += 1
        if case.find("skipped") is not None:
            skipped += 1
        elif case.find("failure") is not None:
            failed += 1
        elif case.find("error") is not None:
            errors += 1
    return {
        "total": total,
        "passed": total - skipped - failed - errors,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
    }


def _execution_evidence(path: str, output: str, junit_path: Path | None) -> tuple[bool | None, dict | None]:
    """Whether at least one test executed, from a structured result (never a prose match).

    A Python run is judged from its junit report, or, when the injected runner wrote none, from
    pytest's own final summary line. A UI test is judged from a Node TAP report when the run
    produced one (a test runner that selected nothing reports ``1..0`` / ``pass 0`` and must not
    certify); a plain assertion script that prints no TAP is executed by definition when it exits
    clean, so its exit code remains the evidence. ``(None, ...)`` means the result could not prove
    execution and the recorder must refuse it.
    """
    if is_ui_test(path):
        counts = _node_tap_counts(output)
        if counts is None:
            return True, None
        return _counts_executed(counts), counts
    counts = _junit_counts(junit_path) if junit_path is not None else None
    if counts is None:
        counts = _pytest_summary_counts(output)
    return _counts_executed(counts), counts


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
    """The one comparison form for a repository-relative path.

    A leading ``./`` is normalised (a valid positive). A ``..`` component is NOT collapsed
    lexically: ``link/../tests/x.py`` looks like ``tests/x.py`` but the kernel resolves ``link``
    (a symlink) first, so it can name a different physical file. Such an alias returns ``""`` and
    can never match the intended repository file.
    """
    text = str(value).replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    if not text:
        return ""
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        return ""
    return posixpath.normpath(text)


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


def _skip_list_is_a_branch_change(root: Path) -> bool:
    """True when this branch itself adds or edits the reviewed skip-tolerant list.

    Tolerance is project provenance, not a property a branch can grant itself: a branch that
    changes the list could name its own zero-execution file and get a receipt. Tolerance is
    therefore refused unless the list is unchanged relative to ``origin/main``. A provenance check
    that cannot run is also treated as a branch change (fail closed).
    """
    try:
        out = _git(
            ["diff", "--name-only", f"{BASE_REF}...HEAD", "--", SKIP_TOLERANT_REL],
            root,
            what=f"git diff {BASE_REF}...HEAD -- {SKIP_TOLERANT_REL}",
        ).stdout
    except PreflightError:
        return True
    return bool(out.strip())


def load_skip_tolerant(root: Path) -> set[str]:
    """Test files the reviewed project list tolerates running zero tests.

    The list is ``config/ci_skip_tolerant_units.json`` read from the committed HEAD tree, never
    from a caller argument and never from the receipt: a caller flag is not a project exception,
    and a receipt cannot declare its own tolerance. Every entry must carry a non-empty reason; a
    missing or malformed list tolerates nothing (fail closed). The list's provenance is bound to
    ``origin/main``: when this branch changes the list, tolerance is refused outright.
    """
    if _skip_list_is_a_branch_change(root):
        return set()
    try:
        proc = _git(
            ["show", f"HEAD:{SKIP_TOLERANT_REL}"],
            root,
            what=f"git show HEAD:{SKIP_TOLERANT_REL}",
        )
    except PreflightError:
        return set()
    try:
        doc = json.loads(proc.stdout or "")
    except ValueError:
        return set()
    if not isinstance(doc, dict) or doc.get("schema") != "CiSkipTolerantFiles@v1":
        return set()
    files = doc.get("files")
    if not isinstance(files, dict):
        return set()
    tolerated: set[str] = set()
    for path, entry in files.items():
        reason = entry.get("reason") if isinstance(entry, dict) else None
        if not isinstance(path, str) or not isinstance(reason, str) or not reason.strip():
            return set()  # one malformed entry makes the whole list unusable
        key = _normalise_test_path(path)
        if key:
            tolerated.add(key)
    return tolerated


def _same_repo_file(root: Path, first: str, second: str) -> bool:
    """True when both repository-relative names resolve to the same physical file."""
    try:
        return (root / first).resolve() == (root / second).resolve()
    except OSError:
        return False


def _receipt_results(receipt: dict, root: Path) -> tuple[dict[str, list[dict]], str]:
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
        key = _normalise_test_path(path)
        if not key:
            return {}, f"a result row names an unsafe path alias ({path}); it must name the repository file itself"
        rows.setdefault(key, []).append(row)
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
    rows, invalid = _receipt_results(receipt, root)
    if invalid:
        return [
            _refusal(
                "tests-not-run",
                f"the test receipt {receipt_file} cannot be validated: {invalid}; "
                f"re-run --record-tests at this head",
            )
        ]
    # Tolerance comes from the reviewed project list at HEAD, never from the receipt. A receipt
    # (or a caller) that declares its own skip tolerance proves nothing.
    tolerant_set = load_skip_tolerant(root)
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
        raw_path = row.get("path")
        if not isinstance(raw_path, str) or not _same_repo_file(root, path, raw_path):
            problems.append(f"{path} (execution row does not resolve to the same repository file)")
            continue
        if row.get("exit_code") != 0:
            problems.append(f"{path} (exit {row.get('exit_code')})")
            continue
        ran_flag = row.get("ran")
        if not isinstance(ran_flag, bool):
            problems.append(f"{path} (no execution flag in its result row)")
            continue
        if is_ui_test(path):
            # A Node TAP report proves what ran; a plain assertion script has no TAP and its
            # clean exit is the evidence. Never accept a report that says nothing executed.
            counts = row.get("counts")
            derived = _counts_executed(counts) if isinstance(counts, dict) else True
        else:
            counts = row.get("counts")
            derived = _counts_executed(counts) if isinstance(counts, dict) else None
            if derived is None:
                tail = row.get("output_tail")
                derived = _counts_executed(_pytest_summary_counts(tail)) if isinstance(tail, str) else None
        if derived is None:
            problems.append(f"{path} (no structured runner result proves a test ran)")
            continue
        allowed_skip = key in tolerant_set
        if derived:
            if ran_flag is not True:
                problems.append(f"{path} (no test executed)")
        elif not allowed_skip:
            problems.append(f"{path} (no test executed: all skipped or no tests ran)")
        elif ran_flag is not False:
            problems.append(f"{path} (execution flag contradicts its runner result)")
    if problems:
        return [
            _refusal(
                "tests-not-run",
                f"the test receipt {receipt_file} lacks successful execution evidence for: "
                f"{'; '.join(problems)}; re-run --record-tests at this head",
            )
        ]
    return []


#: Node options that consume the following argument. Their value is never the executable input,
#: so a test named as a required module or loader must not register.
_NODE_ARG_OPTS = frozenset(
    {
        "-e",
        "--eval",
        "-p",
        "--print",
        "-r",
        "--require",
        "--loader",
        "--experimental-loader",
        "--import",
        "--input-type",
        "--inspect-port",
        "--title",
        "--test-reporter",
        "--test-reporter-destination",
        "--test-name-pattern",
        "--test-skip-pattern",
        "--conditions",
        "-C",
        "--openssl-config",
        "--icu-data-dir",
    }
)
#: Node options whose input is inline code, so no file is the executable.
_NODE_INLINE_OPTS = frozenset({"-e", "--eval", "-p", "--print"})
#: Node modes that never execute their positional file: syntax check, version/help output and the
#: V8 option dump. A touched test named to one of these never runs, so it must not register or
#: certify.
_NODE_NONEXEC_MODES = frozenset(
    {
        "-c",
        "--check",
        "-v",
        "--version",
        "-h",
        "--help",
        "--v8-options",
        "--completion-bash",
    }
)


def _node_selection(tokens: list[str]) -> tuple[list[str], bool, bool, bool]:
    """``(positionals, inline_code, test_runner_mode, nonexecuting_mode)`` for a ``node`` argv.

    ``node`` parses its OWN options only up to the first positional: that token is the script, and
    everything after it is the script's argv. So ``--test`` before the script selects test inputs
    (``node --test x.test.ts``), while ``--test`` after the script is script argv
    (``node driver.cjs --test x.test.ts``) and selects nothing. ``--eval``/``--print`` execute
    inline code, ``--check``/``--version``/``--help`` never execute the file, and an option that
    takes a value is skipped with its value. None of those certify a touched file.
    """
    args = tokens[1:]
    positionals: list[str] = []
    inline = False
    test_mode = False
    nonexec = False
    options_open = True
    index = 0
    while index < len(args):
        token = args[index]
        if options_open and token == "--":
            options_open = False
            index += 1
            continue
        if options_open and token.startswith("-") and token != "-":
            name = token.split("=", 1)[0]
            if name in _NODE_INLINE_OPTS:
                inline = True
            if name == "--test":
                test_mode = True
            if name in _NODE_NONEXEC_MODES:
                nonexec = True
            if "=" not in token and token in _NODE_ARG_OPTS:
                index += 2
                continue
            index += 1
            continue
        positionals.append(token)
        options_open = False  # node stops parsing its own options at the script/input
        index += 1
    return positionals, inline, test_mode, nonexec


def ui_build_command(root: Path, path: str) -> list[str] | None:
    """The ``node ...`` build step that actually selects this UI test, or ``None``.

    ``scripts.build`` runs from ``apps/command-center-v3`` and names its files app-relatively
    (``src/lib/x.test.ts``). The test must be the command's executable input — the first
    positional after node's own options, or a positional selected by ``--test`` in the option
    position — never a substring, a later argument, an option value, or prose. A syntax-check,
    version, help or inline-eval mode never executes the file and never registers it.
    """
    rel = _normalise_test_path(path[len(UI_APP) + 1 :])
    if not rel:
        return None
    for segment in ui_build_string(root).split(" && "):
        try:
            tokens = shlex.split(segment.strip())
        except ValueError:
            continue
        if not tokens or Path(tokens[0]).name != "node":
            continue
        positionals, inline, test_mode, nonexec = _node_selection(tokens)
        if inline or nonexec:
            continue
        selected = [_normalise_test_path(token) for token in positionals]
        if test_mode:
            if rel in selected:
                return tokens
        elif selected and selected[0] == rel:
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


def test_command(root: Path, path: str, junit_path: Path | None = None) -> tuple[list[str], Path]:
    """The command that runs one touched test file, and the directory it runs in.

    A Python run is asked for a junit report when ``junit_path`` is given: that structured report
    is what proves whether a test actually executed, rather than a match on log text.
    """
    if is_ui_test(path):
        rel = path[len(UI_APP) + 1 :]
        tokens = ui_build_command(root, path)
        if tokens is not None:
            return tokens, root / UI_APP
        return ["node", rel], root / UI_APP
    cmd = [sys.executable, "-m", "pytest", "-q", path]
    if junit_path is not None:
        cmd.append(f"--junitxml={junit_path}")
    return cmd, root


def _tracked_source_changes(root: Path) -> list[str]:
    """Modified, staged or deleted *tracked* files."""
    out = _git(
        ["status", "--porcelain", "--untracked-files=no"],
        root,
        what="git status --porcelain --untracked-files=no",
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def _untracked_source_changes(root: Path) -> list[str]:
    """Untracked files that could change what the tests do.

    An untracked module, conftest, pytest config or fixture can make a committed test pass (or
    fail) differently, so it is refused before the run. That includes a GITIGNORED helper: Python
    and node imports do not consult ``.gitignore``, and the repository root plus ``scripts`` are
    on ``sys.path`` for every test run (``tests/conftest.py``), so an ignored file ANYWHERE — at
    the repo root as much as under ``tests`` — can satisfy an import. Ignored files are therefore
    scanned across the whole worktree, not just the usual source directories. Identified
    build/cache outputs (``__pycache__`` bytecode, coverage files, logs) are inert and allowed.
    """
    paths: list[str] = []
    proc = _git(
        ["ls-files", "--others", "--exclude-standard", "-z"],
        root,
        what="git ls-files --others --exclude-standard",
    )
    paths.extend(part for part in proc.stdout.split("\0") if part.strip())
    ignored = _git(
        ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"],
        root,
        what="git ls-files --others --ignored --exclude-standard",
    )
    paths.extend(part for part in ignored.stdout.split("\0") if part.strip())
    return sorted({path for path in paths if not _INERT_UNTRACKED_RE.search(path)})


def _no_receipt_drift(root: Path, head: str, *, before: bool) -> int | None:
    """Refuse to write a receipt when the tested source is not the committed source.

    Tracked changes and untracked source/config both qualify: either can make the receipt bind the
    committed head to code the upload does not contain. A test child may create inert artifacts
    (``__pycache__``, ``.pytest_cache``, coverage files, logs); those are allowed.
    """
    label = "before" if before else "after"
    dirty = _tracked_source_changes(root)
    untracked = _untracked_source_changes(root)
    if dirty or untracked:
        print(
            f"preflight: refusing to record tests — the source is not the committed tree {label} the "
            f"run, so the receipt would bind the committed head to different files. Commit or stash "
            f"these:",
            file=sys.stderr,
        )
        for line in dirty:
            print(f"  {line}", file=sys.stderr)
        for path in untracked:
            print(f"  untracked: {path}", file=sys.stderr)
        if untracked:
            print(
                "preflight: an untracked file that is not a known inert artifact can change what the "
                "tests do; commit it or remove it.",
                file=sys.stderr,
            )
        return 1
    if not before:
        now = head_sha(root)
        if now != head:
            print(
                f"preflight: refusing to record tests — HEAD moved during the run ({head} -> {now}); "
                f"the evidence would be bound to the wrong commit. Re-run at the new head.",
                file=sys.stderr,
            )
            return 1
    return None


def record_tests(root: Path, *, verbose: bool = True) -> int:
    head = head_sha(root)
    touched = touched_test_files(root)
    if not touched:
        if verbose:
            print("preflight: this branch changes no test files; no receipt needed", file=sys.stderr)
        return 0
    refused = _no_receipt_drift(root, head, before=True)
    if refused is not None:
        return refused
    # Tolerance comes only from the reviewed project list at the committed head. There is no
    # caller-selected waiver: an agent cannot certify a zero-assertion run by asking to.
    tolerant = load_skip_tolerant(root)
    results: list[dict] = []
    failed: list[tuple[str, int]] = []
    nothing_ran: list[str] = []
    unprovable: list[str] = []
    tolerated: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="preflight-junit-") as scratch:
        for index, path in enumerate(touched):
            junit_path = Path(scratch) / f"{index}.xml" if is_python_test(path) else None
            cmd, cwd = test_command(root, path, junit_path=junit_path)
            code, output = _normalise_run(test_runner(cmd, cwd))
            executed, counts = _execution_evidence(path, output, junit_path)
            key = _normalise_test_path(path)
            results.append(
                {
                    "path": path,
                    # The junit path is ephemeral; record the command a person can re-run.
                    "command": [part for part in cmd if not part.startswith("--junitxml=")],
                    "exit_code": code,
                    "ran": executed is True,
                    "counts": counts,
                    "output_tail": output[-4000:],
                }
            )
            if code != 0:
                failed.append((path, code))
            elif executed is None:
                unprovable.append(path)
            elif executed:
                continue
            elif key in tolerant:
                tolerated.add(key)
            else:
                nothing_ran.append(path)
    refused = _no_receipt_drift(root, head, before=False)
    if refused is not None:
        return refused
    if failed:
        for path, code in failed:
            print(f"NOT GREEN (exit {code}): {path}", file=sys.stderr)
        print("preflight: no receipt written because tests did not pass", file=sys.stderr)
        return 1
    if unprovable:
        for path in unprovable:
            print(f"NOT PROVEN (no structured runner result): {path}", file=sys.stderr)
        print(
            "preflight: no receipt written because the runner result could not prove a test ran",
            file=sys.stderr,
        )
        return 1
    if nothing_ran:
        for path in nothing_ran:
            print(f"NOT RUN (no test executed, e.g. all skipped or no tests ran): {path}", file=sys.stderr)
        print(
            "preflight: no receipt written because a touched test file executed no test. A zero-test "
            f"run is tolerated only for a file listed with a reason in {SKIP_TOLERANT_REL}.",
            file=sys.stderr,
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
        print(f"preflight: recorded {len(results)} test file(s) for {head} at {target}", file=sys.stderr)
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
