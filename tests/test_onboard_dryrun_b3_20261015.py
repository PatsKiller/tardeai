"""n8n onboarding batch B3 (lane disposition 2026-10-15, MIGRATE_N8N, no allowlist entry, no --dry-run before):
an offline ``--dry-run`` for 4 lane(s). Risk tier 2 (ingest appenders: news, YouTube transcripts / discovery) plus three shell lanes (drive-syncs-hourly precedence fix, run-profit-capture-refresh, portfolio-server-watchdog).

COVERS = ["scripts/hermes_youtube_discovery.py", "scripts/news_ingestion.py", "scripts/youtube_transcript_ingest.py",
    "scripts/run_drive_syncs.sh", "scripts/run_profit_capture_refresh.sh", "scripts/portfolio_server_watchdog.sh"]

Proof (hermetic, in-process): each script runs as ``__main__`` (runpy) with the LIVE cron argv plus ``--dry-run`` in
both orders ("--dry-run wins over --apply/--send"), while every write/send/network/subprocess primitive is replaced by
a recorder that raises: ``open`` in a write mode, ``os.open`` with a write flag, mkdir/makedirs/remove/unlink/rename/
replace/rmdir/rmtree/kill/system, ``subprocess.Popen``, ``socket.socket.connect``, a fake psycopg2 module (connect recorded) and a fake
``telegram_alert.send_telegram``. The run must exit 0, print ``DRY-RUN <lane>``, emit exactly one ``LANE_OUTPUT``
line (produced_count 0, attempted_count 0, empty_reason dry_run), record ZERO calls, and import no project module
other than ``lib`` / ``lib.lane_output`` (so no .env load, DB, LLM bridge or sender module ran).
No DB, no network, no repo write; repo files read only.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
import runpy
import shutil
import socket
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: lane_id -> (script, live cron argv)
LANES = {
    "news-ingestion": ("scripts/news_ingestion.py", ["--priority"]),
    "news-ingestion-tail": ("scripts/news_ingestion.py", ["--tail-rotate"]),
    "hermes-youtube-discovery": ("scripts/hermes_youtube_discovery.py", ["--apply", "--limit", "8", "--videos", "2"]),
    "youtube-transcript-ingest": ("scripts/youtube_transcript_ingest.py", ["--all-channels"]),
}

ALLOWED_NEW_MODULES = {"lib", "lib.lane_output", "scripts", "scripts.lib", "scripts.lib.lane_output"}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


class _Blocked(RuntimeError):
    pass


@contextlib.contextmanager
def _recorders(calls: list):
    real_open, real_os_open = builtins.open, os.open

    def rec(name):
        def _f(*a, **k):
            calls.append((name, repr(a)[:200]))
            raise _Blocked(name)

        return _f

    def guarded_open(file, mode="r", *a, **k):
        if any(c in str(mode) for c in "wax+"):
            calls.append(("open", f"{file} {mode}"))
            raise _Blocked("open")
        return real_open(file, mode, *a, **k)

    def guarded_os_open(path, flags, *a, **k):
        if flags & _WRITE_FLAGS:
            calls.append(("os.open", str(path)))
            raise _Blocked("os.open")
        return real_os_open(path, flags, *a, **k)

    fake_pg = types.ModuleType("psycopg2")
    fake_pg.connect = rec(fake_pg.__name__ + ".connect")
    fake_tg = types.ModuleType("telegram_alert")
    fake_tg.send_telegram = rec("send_telegram")
    patches = [(builtins, "open", guarded_open), (io, "open", guarded_open), (os, "open", guarded_os_open)]
    for mod, names in ((os, ("mkdir", "makedirs", "remove", "unlink", "rename", "replace", "rmdir", "kill",
                             "system")),
                       (shutil, ("rmtree", "move", "copy", "copy2", "copyfile")),
                       (subprocess, ("Popen", "run", "call", "check_call", "check_output")),
                       (socket.socket, ("connect", "connect_ex"))):
        for n in names:
            patches.append((mod, n, rec(f"{getattr(mod, '__name__', mod)}.{n}")))
    saved = [(m, n, getattr(m, n)) for m, n, _ in patches]
    saved_mods = {k: sys.modules.get(k) for k in ("psycopg2", "telegram_alert", "lib.telegram_alert")}
    try:
        for m, n, f in patches:
            setattr(m, n, f)
        sys.modules["psycopg2"] = fake_pg
        sys.modules["telegram_alert"] = fake_tg
        sys.modules["lib.telegram_alert"] = fake_tg
        yield
    finally:
        for m, n, f in saved:
            setattr(m, n, f)
        for k, v in saved_mods.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _run_dry(script: str, argv: list[str]) -> tuple[int, str, str, list, set]:
    calls: list = []
    out, err = io.StringIO(), io.StringIO()
    before = set(sys.modules)
    saved_argv, saved_path, saved_bc = sys.argv[:], sys.path[:], sys.dont_write_bytecode
    sys.argv = [str(ROOT / script), *argv]
    sys.dont_write_bytecode = True
    code = None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), _recorders(calls):
            try:
                runpy.run_path(str(ROOT / script), run_name="__main__")
            except SystemExit as exc:
                code = exc.code
    finally:
        sys.argv, sys.path[:], sys.dont_write_bytecode = saved_argv, saved_path, saved_bc
    new = {m for m in set(sys.modules) - before if m.split(".")[0] not in sys.stdlib_module_names}
    return code, out.getvalue(), err.getvalue(), calls, new


@pytest.mark.parametrize("lane", sorted(LANES))
@pytest.mark.parametrize("order", ["dry_first", "dry_last"])
def test_dry_run_is_offline_and_wins(lane, order):
    script, live = LANES[lane]
    argv = ["--dry-run", *live] if order == "dry_first" else [*live, "--dry-run"]
    code, out, err, calls, new = _run_dry(script, argv)
    assert code in (0, None), (lane, code, out, err)
    assert calls == [], (lane, calls)
    assert f"DRY-RUN {lane}:" in out, out
    assert new <= ALLOWED_NEW_MODULES, (lane, sorted(new - ALLOWED_NEW_MODULES))
    lines = [ln for ln in err.splitlines() if ln.startswith("LANE_OUTPUT ")]
    assert len(lines) == 1, err
    doc = json.loads(lines[0][len("LANE_OUTPUT "):])
    assert doc["lane_id"] == lane and doc["mode"] == "dry_run" and doc["schema"] == "LaneOutput@v1"
    assert doc["produced_count"] == 0 and doc["attempted_count"] == 0 and doc["empty_reason"] == "dry_run"


@pytest.mark.parametrize("lane", sorted(LANES))
def test_guard_precedes_every_project_import(lane):
    """Static: the guard is the first non-stdlib statement, so no module-level .env/DB/log side effect runs first."""
    import ast

    script, _ = LANES[lane]
    tree = ast.parse((ROOT / script).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.If) and "--dry-run" in ast.unparse(node.test):
            break
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            assert all(m.split(".")[0] in sys.stdlib_module_names for m in mods), (lane, mods)
            continue
        if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant):
            continue
        raise AssertionError(f"{lane}: statement before the dry-run guard: {ast.unparse(node)[:120]}")
    else:
        raise AssertionError(f"{lane}: no dry-run guard")


# --------------------------------------------------------------------------------------------------------------------
# Shell lanes: the dry run is proven the same way, out of process. PATH holds ONLY recording stubs for every external
# command the scripts use (mkdir, touch, git, psql, curl, kill, systemctl, flock, timeout, python, ...), so any
# external action is either recorded or "command not found"; HOME / state / log roots point into tmp_path.
# --------------------------------------------------------------------------------------------------------------------

#: lane_id -> (script, live cron argv, the line that starts the dry-run exit)
SHELL_LANES = {
    "drive-syncs-hourly": ("scripts/run_drive_syncs.sh", ["--apply"], 'if [ "$MODE" = "dry-run" ]; then'),
    "run-profit-capture-refresh": ("scripts/run_profit_capture_refresh.sh", [], 'for _dr_a in "$@"; do'),
    "portfolio-server-watchdog": ("scripts/portfolio_server_watchdog.sh", [], 'for _dr_a in "$@"; do'),
}
STUBS = ("mkdir", "touch", "git", "psql", "curl", "kill", "pkill", "pgrep", "systemctl", "flock", "timeout", "python3",
         "python", "sleep", "bash", "seq", "grep", "cut", "tee", "rm", "mv", "cp", "date", "id", "head", "tr", "sed",
         "readlink", "dirname", "gog", "rclone", "tar")


def _shell_dry(tmp_path: Path, script: str, argv: list[str]):
    stub = tmp_path / "bin"
    stub.mkdir()
    rec = tmp_path / "calls.log"
    for name in STUBS:
        p = stub / name
        p.write_text(f'#!/bin/sh\necho "{name} $*" >> "{rec}"\nexit 97\n')
        p.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    env = {"PATH": str(stub), "HOME": str(home), "TRADEAI_STATE_ROOT": str(tmp_path / "state"),
           "DRIVE_SYNCS_LOG_DIR": str(tmp_path / "logs"), "DRIVE_SYNCS_LOCK_DIR": str(tmp_path / "locks"),
           "DRIVE_SYNCS_CURRENT": str(tmp_path / "cur")}
    cp = subprocess.run(["/bin/bash", str(ROOT / script), *argv], capture_output=True, text=True, env=env,
                        cwd=str(tmp_path), timeout=60)
    calls = rec.read_text().splitlines() if rec.exists() else []
    created = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")
                     if not str(p.relative_to(tmp_path)).startswith(("bin", "home")) and p.name != "calls.log")
    return cp, calls, created + sorted(str(p) for p in home.rglob("*"))


@pytest.mark.parametrize("lane", sorted(SHELL_LANES))
@pytest.mark.parametrize("order", ["dry_first", "dry_last"])
def test_shell_dry_run_is_offline_and_wins(lane, order, tmp_path):
    script, live, _ = SHELL_LANES[lane]
    argv = ["--dry-run", *live] if order == "dry_first" else [*live, "--dry-run"]
    cp, calls, created = _shell_dry(tmp_path, script, argv)
    assert cp.returncode == 0, (lane, cp.stdout, cp.stderr)
    assert calls == [] and created == [], (lane, calls, created)
    assert "command not found" not in cp.stderr, cp.stderr
    assert f"DRY-RUN {lane}:" in cp.stdout, cp.stdout
    lines = [ln for ln in cp.stderr.splitlines() if ln.startswith("LANE_OUTPUT ")]
    assert len(lines) == 1, cp.stderr
    doc = json.loads(lines[0][len("LANE_OUTPUT "):])
    assert doc["lane_id"] == lane and doc["mode"] == "dry_run" and doc["schema"] == "LaneOutput@v1"
    assert doc["produced_count"] == 0 and doc["attempted_count"] == 0 and doc["empty_reason"] == "dry_run"


@pytest.mark.parametrize("lane", sorted(SHELL_LANES))
def test_shell_guard_precedes_every_side_effect(lane):
    import re

    script, _, marker = SHELL_LANES[lane]
    lines = (ROOT / script).read_text(encoding="utf-8").splitlines()
    g = lines.index(marker)
    effect = re.compile(r"^\s*(mkdir|touch|cd |rm |git |curl |psql |kill |systemctl |log \"|run \")|>>")
    first = next(i for i, ln in enumerate(lines) if not ln.lstrip().startswith("#") and effect.search(ln))
    assert g < first, (lane, g, first, lines[first])


def test_drive_syncs_apply_alone_still_selects_apply():
    """Precedence fix only: --apply without --dry-run is still the live mode (the arg loop, not a run)."""
    text = (ROOT / "scripts/run_drive_syncs.sh").read_text(encoding="utf-8")
    assert '--apply)   [ "$MODE" = "dry-run" ] || MODE="apply" ;;' in text
    assert '--dry-run) MODE="dry-run" ;;' in text
