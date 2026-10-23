"""Packet read-back verifies must not report FAILED on a crontab that is exactly right (2026-10-22).

The bug: incident-spcx-resume-20261022/{resume,double-run}-operator.sh verified each step with
``crontab -l | grep -qxF -- "$line"`` under ``set -euo pipefail``. ``grep -q`` exits at its first match;
``crontab -l`` then takes SIGPIPE writing the rest of the operator's ~174 KB crontab and exits 141; pipefail
makes the pipeline 141, so a line that IS present reads as missing. In the operator's 2026-10-22 run every
step applied and every verify printed FAILED. The fix captures ``crontab -l`` to a file (or a variable) and
greps that.

Hermetic: a fake ``crontab`` on PATH serves a >200 KB synthetic crontab from tmp_path and dies on SIGPIPE
exactly like the real one (C stdio, default SIGPIPE disposition). The scripts' real apply/verify blocks run
under ``set -euo pipefail``; no real crontab, broker, ledger or database is touched.
"""
from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKT = ROOT / "docs" / "ops" / "packets" / "incident-spcx-resume-20261022"
RESUME = PKT / "resume-operator.sh"
DOUBLE = PKT / "double-run-operator.sh"

FAKE_CRONTAB = r'''#!{py}
import signal, sys
signal.signal(signal.SIGPIPE, signal.SIG_DFL)   # like cronie's crontab: killed by SIGPIPE (exit 141 in bash)
state = {state!r}
if sys.argv[1:] == ["-l"]:
    data = open(state, "rb").read()
    out = sys.stdout.buffer
    for i in range(0, len(data), 4096):          # many small writes, as stdio does
        out.write(data[i:i + 4096]); out.flush()
elif sys.argv[1:] == ["-"]:
    open(state, "wb").write(sys.stdin.buffer.read())
else:
    sys.exit("fake crontab: unsupported args %r" % sys.argv[1:])
'''

PAD_LINE = "# padding: an unrelated comment line that makes the synthetic crontab as large as the operator's ----"


def _heredoc(text: str, tag: str) -> str:
    m = re.search(r"<<'%s'\n(.*?)\n%s\n" % (tag, tag), text, re.S)
    assert m, tag
    return m.group(1)


def _between(text: str, start: str, end: str) -> str:
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j]


def _install_fake(tmp_path: Path, content: str) -> tuple[Path, Path]:
    big = content + "\n".join([PAD_LINE] * 3000) + "\n"
    assert len(big.encode()) > 200_000
    state = tmp_path / "crontab.state"
    state.write_text(big)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "crontab"
    fake.write_text(FAKE_CRONTAB.format(py=sys.executable, state=str(state)))
    fake.chmod(0o755)
    return bindir, state


def _run(tmp_path: Path, bindir: Path, script: str) -> subprocess.CompletedProcess:
    path = tmp_path / "harness.sh"
    path.write_text(script)
    env = {"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(tmp_path), "LC_ALL": "C"}
    return subprocess.run(["bash", str(path)], capture_output=True, text=True, env=env, timeout=120)


def test_fake_crontab_reproduces_the_false_failure(tmp_path):
    """Control: the shim must reproduce the bug, or the tests below prove nothing."""
    bindir, _ = _install_fake(tmp_path, "SHELL=/bin/bash\nTARGET LINE\n")
    r = _run(tmp_path, bindir, 'set -euo pipefail\n'
             'crontab -l | grep -qxF -- "TARGET LINE" && echo "OLD-PATTERN-OK" || echo "OLD-PATTERN-FAILED ${PIPESTATUS[*]}"\n'
             'crontab -l > "$HOME/snap"; grep -qxF -- "TARGET LINE" "$HOME/snap" && echo "CAPTURED-OK"\n')
    assert r.returncode == 0, r.stderr
    assert "OLD-PATTERN-FAILED" in r.stdout, r.stdout  # the line IS present; the pipe says it is not
    assert "CAPTURED-OK" in r.stdout


# ── resume-operator.sh: the real step-5 apply/verify block ────────────────────────────────────────────────────


def _resume_harness(tmp_path: Path) -> tuple[Path, Path, list[str], str]:
    src = RESUME.read_text()
    targets = _heredoc(src, "TARGETS")
    steps = list(dict.fromkeys(l.split("\t", 1)[0] for l in targets.splitlines()))
    paused = [l.split("\t", 1)[1] for l in targets.splitlines()]
    keep = [
        "# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) */10 9-16 * * 1-5 cd /x && flock -n /tmp/defense_fills.lock true",
        "# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) */20 9-16 * * 1-5 cd /x && flock -n /tmp/options_lifecycle.lock true",
        "# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) 0 18 * * 1-5 cd /x && flock -n /tmp/options_lc_digest.lock true",
        "# PAUSED 2026-10-14 WS7-02 coder-agent autolaunch (grant a67b8f21) 0 9-18/3 * * 1-5 flock -n /tmp/tradeai_coder_dispatch.lock true",
    ]
    # the target lines sit near the top, so grep -q matches in its first read and stops reading
    bindir, state = _install_fake(tmp_path, "\n".join(["SHELL=/bin/bash", "PROJ=/x", "PY=/y"] + paused + keep) + "\n")
    work = tmp_path / "work"
    work.mkdir()
    (work / "targets.tsv").write_text(targets + "\n")
    (work / "keep.txt").write_text(_heredoc(src, "KEEP") + "\n")
    (work / "edit.py").write_text(_heredoc(src, "PYEOF") + "\n")
    check_keep = _between(src, "check_keep() {", "\ncheck_keep \"$WORK/crontab.live\"")
    block = _between(src, "# ── 5. apply step by step", 'echo "DONE.')
    script = "\n".join([
        "set -euo pipefail", "set -f",
        f"WORK={shlex.quote(str(work))}", f"BACKUP={shlex.quote(str(tmp_path / 'backup'))}",
        f"PY={shlex.quote(sys.executable)}",
        'rollback_hint() { echo "ROLLBACK" >&2; }',
        check_keep,
        "RUN_STEPS=(" + " ".join(steps) + ")",
        block,
        'echo "HARNESS-DONE"',
    ])
    return bindir, state, steps, script


def test_resume_verify_passes_on_a_large_crontab_under_pipefail(tmp_path):
    bindir, state, steps, script = _resume_harness(tmp_path)
    r = _run(tmp_path, bindir, script)
    assert "FAILED" not in r.stdout + r.stderr, r.stdout + r.stderr
    assert r.returncode == 0, r.stdout + r.stderr
    assert "HARNESS-DONE" in r.stdout
    for s in steps:
        assert f"[{s}] active and verified" in r.stdout
    final = state.read_text().splitlines()
    assert sum(1 for l in final if l.startswith("# RETIRED 2026-10-22 superseded-by drive-syncs-hourly")) == 1


def test_resume_verify_still_fails_when_a_line_is_really_missing(tmp_path):
    """The fix must not turn the verify into a no-op: a line the install did not activate still fails."""
    bindir, state, _, script = _resume_harness(tmp_path)
    # sabotage step a's install: the fake drops the first un-paused line on write
    fake = bindir / "crontab"
    fake.write_text(fake.read_text().replace(
        'open(state, "wb").write(sys.stdin.buffer.read())',
        'd = sys.stdin.buffer.read().split(b"\\n"); '
        'd = [l for l in d if b"schwab_position_sync.py --apply" not in l or l.startswith(b"#")]; '
        'open(state, "wb").write(b"\\n".join(d))'))
    r = _run(tmp_path, bindir, script)
    assert r.returncode == 5, r.stdout + r.stderr
    assert "FAILED at step a" in r.stdout


# ── double-run-operator.sh: the real apply-with-read-back block ──────────────────────────────────────────────


def test_double_run_verify_passes_on_a_large_crontab_under_pipefail(tmp_path):
    src = DOUBLE.read_text()
    plan = _heredoc(src, "PLAN")
    prefix = re.search(r"^PREFIX='(.*)'$", src, re.M).group(1)
    olds = [l.split("\t", 1)[1] for l in plan.splitlines()]
    bindir, state = _install_fake(tmp_path, "\n".join(["SHELL=/bin/bash", "PROJ=/x", "PY=/y"] + olds) + "\n")
    work = tmp_path / "work"
    work.mkdir()
    (work / "plan.tsv").write_text(plan + "\n")
    # the second PYEOF heredoc (edit.py) is the transform; the first is the ledger check
    (work / "edit.py").write_text(re.findall(r"<<'PYEOF'\n(.*?)\nPYEOF\n", src, re.S)[1] + "\n")
    (work / "crontab.live").write_bytes(state.read_bytes())
    r = subprocess.run([sys.executable, str(work / "edit.py"), str(work / "crontab.live"), str(work / "plan.tsv"),
                        prefix, str(work / "candidate")], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == str(len(olds)), r.stderr
    block = _between(src, "# ── apply with read-back", 'echo "DONE.')
    script = "\n".join([
        "set -euo pipefail", "set -f",
        f"WORK={shlex.quote(str(work))}", f"PREFIX={shlex.quote(prefix)}",
        'rollback_hint() { echo "ROLLBACK" >&2; }',
        block,
        'echo "HARNESS-DONE"',
    ])
    r = _run(tmp_path, bindir, script)
    assert "FAILED" not in r.stdout + r.stderr, r.stdout + r.stderr
    assert r.returncode == 0 and "HARNESS-DONE" in r.stdout, r.stdout + r.stderr
    assert r.stdout.count("cron line commented, verified") == len(olds)
    assert state.read_bytes() == (work / "candidate").read_bytes()


# ── lint: no crontab -l piped into an early-exit reader, in any pipefail packet or ops script ────────────────

_CRONTAB_L = re.compile(r'(?:\bcrontab|"\$CRONTAB_BIN"|\$CRONTAB_BIN)\s+-l\b')
_EARLY_EXIT = re.compile(r"^\s*(?:grep|egrep|fgrep)\b(?=.*\s-[A-Za-z]*[qm])|^\s*head\b")
_AGGREGATE = re.compile(r"^\s*(?:grep\b(?=.*\s-[A-Za-z]*c)|wc\b|sort\b)")


def _sigpipe_hazards(text: str) -> list[str]:
    joined = re.sub(r"\\\n\s*", " ", text)
    hits = []
    for line in joined.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for m in _CRONTAB_L.finditer(line):
            rest = line[m.end():]
            rest = re.split(r"\|\||&&|;|\)\s|$", rest, maxsplit=1)[0]
            stages = re.split(r"(?<!\|)\|(?!\|)", rest)[1:]
            for stage in stages:
                if _AGGREGATE.match(stage):
                    break  # reads all of its input; whatever follows cannot SIGPIPE crontab
                if _EARLY_EXIT.match(stage):
                    hits.append(line.strip())
                    break
    return hits


def _pipefail_scripts():
    files = sorted((ROOT / "docs" / "ops" / "packets").glob("*/*.sh")) + sorted((ROOT / "scripts" / "ops").glob("*.sh"))
    return [f for f in files if re.search(r"^\s*set -[a-z]*o pipefail", f.read_text(errors="replace"), re.M)]


def test_lint_detects_the_original_pattern():
    assert _sigpipe_hazards('crontab -l | grep -qxF -- "$active" || { echo FAILED; }')
    assert _sigpipe_hazards('"$CRONTAB_BIN" -l | grep -qF -- "$NEW_LINE" || fail x')
    assert _sigpipe_hazards("if crontab -l | grep -v '^#' | grep -q 'x'; then")
    assert _sigpipe_hazards("crontab -l | head -1")
    assert not _sigpipe_hazards('crontab -l > "$WORK/after-installed.$s"')
    assert not _sigpipe_hazards('crontab -l | grep -c "x" | grep -qx 1')
    assert not _sigpipe_hazards('crontab -l | cmp - "$W/cand"')


@pytest.mark.parametrize("script", _pipefail_scripts(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_crontab_pipe_into_early_exit_reader(script):
    assert _sigpipe_hazards(script.read_text(errors="replace")) == []


def test_incident_packet_readme_records_the_false_failed_run():
    readme = (PKT / "README.md").read_text()
    assert "2026-10-22 operator run: steps applied but verify falsely reported FAILED (SIGPIPE under pipefail)" in readme
