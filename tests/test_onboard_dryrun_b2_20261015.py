"""n8n onboarding batch B2 (lane disposition 2026-10-15, MIGRATE_N8N, no allowlist entry, no --dry-run before):
an offline ``--dry-run`` for 7 lane(s). Risk tier 2 (appenders / overwrite writers without a send or model call: balance history, plan re-plans, Finviz technicals, label fixes, Active Trader review + calibration, proposal-lifecycle telemetry).

COVERS = ["scripts/active_trader/session_review.py", "scripts/active_trader/signal_calibration.py",
    "scripts/deepseek_balance_snapshot.py", "scripts/enrich_proposal_technicals.py",
    "scripts/plan_drift_revalidator.py", "scripts/proposal_lifecycle.py", "scripts/reclassify_momentum_proposals.py"]

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
    "deepseek-balance-snapshot": ("scripts/deepseek_balance_snapshot.py", ["--apply"]),
    "plan-drift-revalidator": ("scripts/plan_drift_revalidator.py", ["--apply"]),
    "enrich-proposal-technicals": ("scripts/enrich_proposal_technicals.py", []),
    "reclassify-momentum-proposals": ("scripts/reclassify_momentum_proposals.py", ["--apply"]),
    "active-trader-session-review": ("scripts/active_trader/session_review.py", ["--apply"]),
    "active-trader-signal-calibration": ("scripts/active_trader/signal_calibration.py", ["--apply"]),
    "proposal-lifecycle": ("scripts/proposal_lifecycle.py", []),
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
