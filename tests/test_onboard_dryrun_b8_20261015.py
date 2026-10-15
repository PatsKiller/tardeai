"""n8n onboarding batch B8 (lane disposition 2026-10-15, MIGRATE_N8N, no allowlist entry, no --dry-run before):
an offline ``--dry-run`` for 4 lane(s). Risk tier 4 (LLM agents and the two deterministic CIO lanes, plus the two shell launchers of the LLM lanes).

COVERS = ["scripts/cio_entry_state_runner.py", "scripts/cio_opportunity_curator.py", "scripts/inference_ensemble_worker.py",
    "scripts/run_symbol_thesis_acquisition.py", "linux_launchers/run_ensemble_worker.sh",
    "scripts/run_governed_symbol_thesis_acquisition.sh"]

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
    "run-ensemble-worker": ("scripts/inference_ensemble_worker.py", ["--run", "--limit", "5"]),
    "run-governed-symbol-thesis-acquisition": ("scripts/run_symbol_thesis_acquisition.py", ["--apply"]),
    "cio-entry-state": ("scripts/cio_entry_state_runner.py", ["--apply"]),
    "cio-opportunity-curator": ("scripts/cio_opportunity_curator.py", ["--apply"]),
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
# Shell launchers of the two LLM lanes: proven out of process. PATH holds ONLY recording stubs for every external
# command, so any external action is recorded or "command not found"; HOME and the governed-thesis roots are tmp_path.
# --------------------------------------------------------------------------------------------------------------------

#: lane_id -> (launcher, live cron argv)
SHELL_LANES = {
    "run-ensemble-worker": ("linux_launchers/run_ensemble_worker.sh", []),
    "run-governed-symbol-thesis-acquisition": ("scripts/run_governed_symbol_thesis_acquisition.sh", []),
}
STUBS = ("mkdir", "touch", "git", "psql", "curl", "kill", "flock", "timeout", "python3", "python", "sleep", "bash",
         "grep", "cut", "tee", "rm", "mv", "cp", "date", "id", "head", "tr", "sed", "readlink", "dirname", "env", "cat")


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
    env = {"PATH": str(stub), "HOME": str(home), "TRADEAI_PROJ": str(tmp_path / "proj"),
           "TRADEAI_GOVERNED_THESIS_LOG": str(tmp_path / "logs" / "t.log"),
           "TRADEAI_THESIS_LOCK_PATH": str(tmp_path / "locks" / "t.lock")}
    cp = subprocess.run(["/bin/bash", str(ROOT / script), *argv], capture_output=True, text=True, env=env,
                        cwd=str(tmp_path), timeout=60)
    calls = rec.read_text().splitlines() if rec.exists() else []
    created = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")
                     if not str(p.relative_to(tmp_path)).startswith(("bin", "home")) and p.name != "calls.log")
    return cp, calls, created + sorted(str(p) for p in home.rglob("*"))


@pytest.mark.parametrize("lane", sorted(SHELL_LANES))
@pytest.mark.parametrize("order", ["dry_first", "dry_last"])
def test_shell_dry_run_is_offline_and_wins(lane, order, tmp_path):
    script, live = SHELL_LANES[lane]
    argv = ["--dry-run", *live, "--apply"] if order == "dry_first" else [*live, "--apply", "--dry-run"]
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

    script, _ = SHELL_LANES[lane]
    lines = (ROOT / script).read_text(encoding="utf-8").splitlines()
    g = lines.index('for _dr_a in "$@"; do')
    effect = re.compile(r"^\s*(mkdir|touch|cd |rm |git |\. |source |exec |log |[A-Z_]+=\"\$\()|>>")
    first = next(i for i, ln in enumerate(lines) if not ln.lstrip().startswith("#") and effect.search(ln))
    assert g < first, (lane, g, first, lines[first])


def test_senders_reach_telegram_only_through_the_chokepoint(tmp_path):
    """Static capability audit (scripts/audit_lane_transitive_capabilities.py) over each lane's import closure: the
    live path reaches the approved delivery chokepoint (chokepoint_send) and never a direct sender (direct_sender stays
    forbidden: no raw mail, SMS, chat-webhook or Bot API transport outside the chokepoint set)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import audit_lane_transitive_capabilities as A

    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps({"lanes": [{"lane_id": lane, "command": ["$PY", script]}
                                           for lane, (script, _) in LANES.items() if lane in SENDERS]}))
    res = A.audit(allow)
    assert set(res) == SENDERS
    for lane, row in res.items():
        caps = row["capabilities"]
        assert "direct_sender" not in caps, (lane, caps.get("direct_sender"))
        assert "chokepoint_send" in caps, lane

SENDERS = set(LANES)
