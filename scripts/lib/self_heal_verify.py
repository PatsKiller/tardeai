#!/usr/bin/env python3
"""Best-practice verification for a self-heal fix (LQ-20261107-1234, 2026-11-08).

The fixer's acceptance rules say a fix is believed only when a harness-run regression test is RED on the
base commit and GREEN after it, and when the diff does not buy that green by masking the failure. This
module is that judgement, as four small functions:

* ``repro_reliable(cmd, n=3)`` -- every one of n runs on the BASE commit must exit non-zero.
* ``fixed_reliably(cmd, n=3)`` -- every one of n runs AFTER the fix must exit 0.
* ``lint_masking(unified_diff)`` -- line-level findings for a diff that hides the failure instead of
  fixing it: a new bare/broad ``except`` whose body is only ``pass``/``continue``, an early
  ``return []``/``None``/``{}``/``False`` on a failing path, a skip/xfail marker, a new ``conftest.py``,
  a deleted assertion, a forced exit code.
* ``full_suite_cmd(changed_files)`` -- the companion suite command for a diff. It never returns a
  command with no tests: when it cannot name a narrower set it returns the whole ``tests/`` tree.

``run_n`` is the raw observation the two verdicts are computed from (the fixer records the exit codes).

The run helpers take an injectable ``runner`` so tests never execute a real command; the default runner
is ``subprocess.run`` with a timeout. Nothing here writes state, opens a socket, reads a credential or
touches the DB.

The diff lint is textual over ADDED lines: a pattern that appears inside a string literal (a regex
source, a message, a test's own diff fixture) is flagged exactly like code, because a diff alone cannot
tell the two apart. It reports; the caller decides.
"""
from __future__ import annotations

import re
import shlex
import subprocess
from collections.abc import Callable, Iterable, Sequence

#: The plan's default: three runs on the base and three after.
DEFAULT_RUNS = 3
#: A single run may not run longer than this. A timed-out run has no verdict (neither red nor green).
DEFAULT_TIMEOUT_S = 300.0
#: The repo's pytest entry point when the caller does not name one. The fixer passes its own wrapper.
DEFAULT_PYTEST_CMD = "python -m pytest"
FINDING_SCHEMA = "SelfHealMaskingFinding@v1"

#: ``runner(argv, cwd=..., env=..., timeout_s=...) -> exit code``; ``None`` means "no verdict"
#: (timeout, spawn failure). A runner that raises is a bug in the runner, not a pass.
Runner = Callable[..., int | None]


def _argv(cmd: str | Sequence[str]) -> list[str]:
    argv = shlex.split(cmd) if isinstance(cmd, str) else [str(a) for a in cmd]
    if not argv:
        raise ValueError("empty command: there is nothing to run and no verdict to record")
    return argv


def _subprocess_runner(
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> int | None:
    """Run one command to a verdict. No verdict on a timeout or on a spawn failure -- never a pass."""
    try:
        proc = subprocess.run(  # noqa: S603 -- argv is a list, the caller owns the command
            list(argv), cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout_s, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.returncode


def run_n(
    cmd: str | Sequence[str],
    n: int = DEFAULT_RUNS,
    *,
    runner: Runner | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> list[int | None]:
    """Run ``cmd`` exactly ``n`` times and return each exit code (``None`` = no verdict)."""
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError(f"n must be a positive integer, not {n!r}")
    argv = _argv(cmd)
    run = runner or _subprocess_runner
    return [run(argv, cwd=cwd, env=env, timeout_s=timeout_s) for _ in range(n)]


def repro_reliable(cmd: str | Sequence[str], n: int = DEFAULT_RUNS, **kw) -> bool:
    """True iff the regression test failed on the base commit in every one of ``n`` runs.

    A run with no verdict (timeout, spawn failure) is not a reliable red: the test did not demonstrate
    the defect, it failed to run.
    """
    codes = run_n(cmd, n, **kw)
    return all(code is not None and code != 0 for code in codes)


def fixed_reliably(cmd: str | Sequence[str], n: int = DEFAULT_RUNS, **kw) -> bool:
    """True iff the same test passed in every one of ``n`` runs after the fix."""
    codes = run_n(cmd, n, **kw)
    return all(code == 0 for code in codes)


# ------------------------------------------------------------------------------------------------ diff lint
_COMMENT = re.compile(r"^\s*#")
_EXCEPT_HDR = re.compile(r"^(\s*)except\b(.*)$")
_BROAD_TYPES = frozenset({"Exception", "BaseException"})
_SWALLOW = frozenset({"pass", "continue", "..."})
_EMPTY_VALUES = frozenset({"", "None", "[]", "{}", "False"})
_RETURN = re.compile(r"^(\s*)return\b(.*)$")
_ASSERT = re.compile(r"^\s*(?:assert\b|(?:self\.)?(?:assert[A-Z]\w*|fail)\s*\()")
_SUPPRESS = re.compile(
    r"@?pytest\.mark\.(skip|skipif|xfail)\b"
    r"|\bpytestmark\s*=\s*[^\n]*\b(skip|skipif|xfail)\b"
    r"|\.mark\.(skip|skipif|xfail)\b"
    r"|\bpytest\.(skip|xfail|importorskip)\s*\("
    r"|\bunittest\.skip\b"
    r"|@(skip|skipIf|skipUnless|expectedFailure)\b"
    r"|\bself\.skipTest\s*\("
    r"|\btest\.skip\s*\("
    r"|-{2}" r"deselect\b"
    r"""|-k\s+['"]?not\b"""
)
_FORCED_EXIT = re.compile(
    r"\bsys\.exit\(\s*0\s*\)"
    r"|\bos\._exit\(\s*0\s*\)"
    r"|(?<![\w.])exit\(\s*0\s*\)"
    r"|\braise\s+SystemExit\(\s*(?:0\s*)?\)"
    r"|\|\|\s*(?:true|:)\s*(?:$|[#;])"
    r"|\bset\s*\+e\b"
)
_HUNK_HDR = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_DIFF_HDR = re.compile(r"^diff --git a/(.+?) b/(.+)$")


class _Part:
    """One line of a diff, positioned in the NEW file."""

    __slots__ = ("hunk", "line", "text", "added")

    def __init__(self, line: int, text: str, *, added: bool, hunk: int) -> None:
        self.line = line
        self.text = text
        self.added = added
        self.hunk = hunk


class _FileDiff:
    """A file's diff: the new-file lines (context + added) plus the removed lines with their position."""

    __slots__ = ("created", "lines", "path", "removed")

    def __init__(self, path: str) -> None:
        self.path = path
        self.created = False
        self.lines: list[_Part] = []
        #: (hunk, new-file position of the deletion, removed text)
        self.removed: list[tuple[int, int, str]] = []


def _parse_diff(unified_diff: str) -> list[_FileDiff]:
    files: list[_FileDiff] = []
    cur: _FileDiff | None = None
    hunk = -1
    new_no = 0
    for raw in (unified_diff or "").splitlines():
        if raw.startswith("diff --git "):
            m = _DIFF_HDR.match(raw)
            cur = _FileDiff(m.group(2) if m else raw.rsplit(" ", 1)[-1])
            files.append(cur)
            hunk = -1
            continue
        if raw.startswith("new file mode"):
            if cur is not None:
                cur.created = True
            continue
        if raw.startswith("--- "):
            if raw.startswith("--- /dev/null") and cur is not None:
                cur.created = True
            continue
        if raw.startswith("+++ "):
            path = raw[4:].split("\t", 1)[0]
            path = path[2:] if path.startswith("b/") else path
            if cur is None:
                cur = _FileDiff(path)
                files.append(cur)
            elif path != "/dev/null":
                cur.path = path
            continue
        m = _HUNK_HDR.match(raw)
        if m:
            hunk += 1
            new_no = int(m.group(1))
            continue
        if cur is None or hunk < 0 or raw.startswith("\\"):
            continue
        if raw.startswith("+"):
            cur.lines.append(_Part(new_no, raw[1:], added=True, hunk=hunk))
            new_no += 1
        elif raw.startswith("-"):
            cur.removed.append((hunk, new_no, raw[1:]))
        else:
            cur.lines.append(_Part(new_no, raw[1:] if raw.startswith(" ") else raw, added=False, hunk=hunk))
            new_no += 1
    return files


def _indent(text: str) -> int:
    return len(text) - len(text.lstrip(" \t"))


def _significant(text: str) -> bool:
    return bool(text.strip()) and not _COMMENT.match(text)


def _headers(lines: Sequence[_Part], index: int) -> list[str]:
    """The enclosing block headers of ``lines[index]``, nearest first, by indentation."""
    out: list[str] = []
    limit = _indent(lines[index].text)
    for j in range(index - 1, -1, -1):
        text = lines[j].text
        if not _significant(text):
            continue
        ind = _indent(text)
        if ind < limit:
            out.append(text.strip())
            limit = ind
            if ind == 0:
                break
    return out


def _except_kind(header: str) -> str | None:
    """``"broad"`` for a bare or Exception/BaseException handler, ``"narrow"`` otherwise, ``None`` if not one."""
    m = _EXCEPT_HDR.match(header)
    if not m:
        return None
    rest = m.group(2)
    spec, sep, _inline = rest.partition(":")
    if not sep:
        return "narrow"
    spec = re.sub(r"\s+as\s+\w+\s*$", "", spec.strip()).strip("() ")
    if spec == "" or spec in _BROAD_TYPES:
        return "broad"
    return "narrow"


_DOCSTRING = re.compile(r'^\s*[rbuRBU]{0,2}("""|\'\'\'|"|\')')


def _first_statement_of_function(lines: Sequence[_Part], index: int) -> bool:
    """True iff ``lines[index]`` is the first statement of a function body (docstrings do not count)."""
    for j in range(index - 1, -1, -1):
        text = lines[j].text
        if not _significant(text):
            continue
        ind = _indent(text)
        if ind >= _indent(lines[index].text):
            continue
        if not text.strip().startswith(("def ", "async def ")):
            return False
        for k in range(j + 1, index):
            body = lines[k].text
            if _significant(body) and _indent(body) > ind and not _DOCSTRING.match(body):
                return False
        return True
    return False


def _finding(rule: str, path: str, line: int | None, text: str, message: str) -> dict:
    return {
        "schema": FINDING_SCHEMA,
        "rule": rule,
        "path": path,
        "line": line,
        "text": text.strip(),
        "message": message,
    }


def _lint_broad_except(fd: _FileDiff, index: int, out: list[dict]) -> None:
    part = fd.lines[index]
    if _except_kind(part.text) != "broad":
        return
    indent = _indent(part.text)
    rest = part.text.partition(":")[2].strip()
    if rest:
        body = [rest]
    else:
        body = []
        for j in range(index + 1, len(fd.lines)):
            text = fd.lines[j].text
            if not _significant(text):
                continue
            if _indent(text) <= indent:
                break
            body.append(text.strip())
    if body and all(stmt in _SWALLOW for stmt in body):
        out.append(
            _finding(
                "broad_except_swallow",
                fd.path,
                part.line,
                part.text,
                "a new bare/broad exception handler swallows the failure with pass/continue; re-raise, "
                "narrow the handler, or let it fail",
            )
        )


def _lint_empty_return(fd: _FileDiff, index: int, out: list[dict]) -> None:
    part = fd.lines[index]
    m = _RETURN.match(part.text)
    if not m:
        return
    value = re.sub(r"#.*$", "", m.group(2)).strip()
    if value not in _EMPTY_VALUES:
        return
    headers = _headers(fd.lines, index)
    broad = next((h for h in headers if _except_kind(h) == "broad"), None)
    stub = _first_statement_of_function(fd.lines, index)
    if broad is None and not stub:
        return
    where = "inside a new broad exception handler" if broad else "as the first statement of the function"
    out.append(
        _finding(
            "empty_return_stub",
            fd.path,
            part.line,
            part.text,
            f"a new early ``return`` of an empty value {where} turns a failure into a silent default",
        )
    )


def _lint_added_line(fd: _FileDiff, index: int, out: list[dict]) -> None:
    part = fd.lines[index]
    if _COMMENT.match(part.text):
        return
    if _SUPPRESS.search(part.text):
        out.append(
            _finding(
                "test_suppression",
                fd.path,
                part.line,
                part.text,
                "a new skip/xfail/deselect marker hides a test instead of fixing what it fails on",
            )
        )
    if _FORCED_EXIT.search(part.text):
        out.append(
            _finding(
                "forced_exit",
                fd.path,
                part.line,
                part.text,
                "a forced success exit code (an explicit zero exit, a shell or-true, disabling errexit) "
                "makes the failure invisible",
            )
        )


def _lint_asserts(fd: _FileDiff, out: list[dict]) -> None:
    """A hunk that removes as many assertions as it adds re-stated them (e.g. to add a message); a hunk
    that removes more than it adds weakened the test, and the surplus removals are findings."""
    removed: dict[int, list[tuple[int, str]]] = {}
    for hunk, line, text in fd.removed:
        if _ASSERT.match(text):
            removed.setdefault(hunk, []).append((line, text))
    if not removed:
        return
    added: dict[int, list[_Part]] = {}
    for part in fd.lines:
        if part.added and _ASSERT.match(part.text):
            added.setdefault(part.hunk, []).append(part)
    for hunk in sorted(removed):
        # The first removal per added assertion is a restatement; only the surplus weakened the test.
        for line, text in removed[hunk][len(added.get(hunk, ())) :]:
            out.append(
                _finding(
                    "deleted_assert",
                    fd.path,
                    line,
                    text,
                    "an assertion is deleted without an equivalent assertion added in the same hunk",
                )
            )


def lint_masking(unified_diff: str) -> list[dict]:
    """Findings for a diff that masks a failure instead of fixing it. Pure; stable order.

    An empty or non-diff string yields ``[]``: there is nothing to refuse, which is different from
    "clean" only in that the caller never inspects an empty diff as a fix.
    """
    out: list[dict] = []
    for fd in _parse_diff(unified_diff):
        if fd.created and fd.path.rsplit("/", 1)[-1] == "conftest.py":
            out.append(
                _finding(
                    "new_conftest",
                    fd.path,
                    1,
                    "conftest.py",
                    "a new conftest.py changes collection and fixtures for the whole tree",
                )
            )
        for index, part in enumerate(fd.lines):
            if not part.added:
                continue
            _lint_broad_except(fd, index, out)
            _lint_empty_return(fd, index, out)
            _lint_added_line(fd, index, out)
        _lint_asserts(fd, out)
    out.sort(key=lambda f: (f["path"], f["line"] if f["line"] is not None else 0, f["rule"]))
    return out


# --------------------------------------------------------------------------------------- suite selection
_TEST_NAME = re.compile(r"^(?:test_.*|.*_test)\.py$")


def _clean(path: object) -> str:
    return re.sub(r"^\.?/+", "", str(path).replace("\\", "/"))


def full_suite_cmd(
    changed_files: Iterable[object],
    *,
    pytest_cmd: str | Sequence[str] = DEFAULT_PYTEST_CMD,
    known_tests: Iterable[object] | None = None,
    tests_root: str = "tests",
) -> list[str]:
    """The companion suite for a diff, as argv.

    Every test file the diff touches is selected, plus every known test whose name carries a changed
    module's stem (``scripts/lib/foo.py`` -> ``tests/test_foo_*.py``). When a changed source module has
    no such test, or nothing in the diff resolves to a test, the command runs the whole ``tests/`` tree:
    a suite command with no tests would let a fix pass by running nothing.

    ``known_tests`` is the caller's listing (``git ls-files tests``). Without it only the diff's own test
    files can be named, so every changed source module falls back to the whole tree.
    """
    root = _clean(tests_root).rstrip("/")
    tests = [_clean(t) for t in (known_tests or ())]
    selected: set[str] = set()
    whole = False
    for raw in changed_files or ():
        path = _clean(raw)
        if not path.endswith(".py"):
            continue
        if path.startswith(f"{root}/") and _TEST_NAME.match(path.rsplit("/", 1)[-1]):
            selected.add(path)
            continue
        stem = path.rsplit("/", 1)[-1][:-3]
        if stem == "__init__":
            continue
        matches = [t for t in tests if stem in t.rsplit("/", 1)[-1][:-3]]
        if matches:
            selected.update(matches)
        else:
            whole = True
    if whole or not selected:
        selected = {root}
    argv = shlex.split(pytest_cmd) if isinstance(pytest_cmd, str) else [str(a) for a in pytest_cmd]
    return [*argv, "-q", *sorted(selected)]
