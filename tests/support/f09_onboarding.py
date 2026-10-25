"""Shared proof harness for the F09 n8n onboarding batches (operator "N8N Cutover Decision" 2026-10-15).

F09 = broker / order / stop / protection / secret lanes (docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.csv).
Each batch test (tests/test_onboard_f09_b<N>_20261015.py) names its lanes; everything else is read from the lane's
registry row, whose ``f09_staged`` block is the single record of the onboarding:

* ``--dry-run`` is OFFLINE and wins over every live flag. It returns before any .env load, DB, broker, LLM, network or
  sender import and before any file write, and it makes NO broker call — not even a read. A lane that cannot plan
  without a broker read reports ``empty_reason dry_run_requires_broker_read`` and exits 0 having done nothing.
* The row is STAGED, not dispatched: AGENTS.md §23.14 (ACTIVE) keeps broker / order / stop lanes off the dispatcher
  until AGENTS.md 12.0.0 §23.25 (PROPOSED: "nothing here binds") is ratified. So ``dispatch.mode`` is ``off``, the lane
  has NO entry in config/n8n_run_allowlist.json ``lanes`` (the only list the gateway and executor read), and the
  activation allowlist entry (argv from the live cron line, ``dry_run_arg``, ``live_arg`` null, the cron line's lock,
  ``output_signal``) waits in ``f09_staged.activation_allowlist_entry``.
* The effect key is staged (``n8n_claim`` / ``cron_claim`` false: neither side claims), the health contract is
  REVIEWED (agent machine cross-check; operator REVIEW pass owed) with a declared ``expected_output`` rule and no
  ``output_receipt: v2`` opt-in.

Python proof (in-process, runpy as ``__main__``): every write/send/network/subprocess primitive is a recorder that
raises; every broker client and transport module name is pre-seeded in ``sys.modules`` as a module whose every
attribute access records and raises; psycopg2, dotenv, telegram_alert likewise. A run must exit 0, print
``DRY-RUN <lane>``, emit exactly one ``LANE_OUTPUT`` line with the staged ``empty_reason``, record ZERO calls, and
import no project module other than ``lib`` / ``lib.lane_output``.
Shell proof (subprocess of /bin/bash with PATH = a directory of recording stubs, HOME/cwd = tmp): exit 0, zero stub
calls, no "command not found", no file created; plus a static check that the guard precedes every command.
No DB, no network, no repo write.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import http.client
import io
import json
import os
import re
import runpy
import shutil
import socket
import subprocess
import sys
import types
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "config" / "lane_registry.json"
ALLOWLIST = ROOT / "config" / "n8n_run_allowlist.json"
EFFECT_KEYS = ROOT / "config" / "n8n_effect_keys.json"
CONTRACTS = ROOT / "config" / "n8n_health_contracts.json"

DRY_ARG = "--dry-run"
REASONS = ("dry_run", "dry_run_requires_broker_read")
ALLOWED_NEW_MODULES = {"lib", "lib.lane_output", "scripts", "scripts.lib", "scripts.lib.lane_output"}
#: Module names whose import or use would mean a broker / DB / sender / network client ran. Seeded as tripwires.
BROKER_TRIPWIRES = (
    "schwab_transport", "lib.schwab_transport", "schwab_position_sync", "schwab_api", "schwab", "brokers",
    "lib.brokers", "alpaca", "alpaca_trade_api", "alpaca_paper_adapter", "futu", "moomoo", "lib.moomoo",
    "snaptrade_client", "snaptrade_read", "tastytrade", "ib_insync", "robin_stocks",
    "requests", "httpx", "urllib3", "aiohttp",
    "psycopg2", "psycopg", "db_adapter", "session13_db", "dotenv",
    "telegram_alert", "lib.telegram_alert",
)
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


class Blocked(RuntimeError):
    """Raised by every recorder: the dry run reached a primitive it must never reach."""


def registry_rows() -> dict[str, dict[str, Any]]:
    return {str(r.get("lane_id")): r for r in json.loads(REGISTRY.read_text(encoding="utf-8"))["lanes"]}


def staged(lane: str) -> dict[str, Any]:
    row = registry_rows()[lane]
    block = row.get("f09_staged")
    assert isinstance(block, dict), f"{lane}: no f09_staged block"
    return block


def _tripwire(name: str, calls: list) -> types.ModuleType:
    class _Trip(types.ModuleType):
        def __getattr__(self, attr: str):  # noqa: D401 -- any use of the module is a call we must not make
            if attr.startswith("__") and attr.endswith("__"):
                raise AttributeError(attr)
            calls.append((f"{name}.{attr}", "broker/db/sender module used"))
            raise Blocked(f"{name}.{attr}")

    mod = _Trip(name)
    mod.__path__ = []  # a package, so `import name.sub` also lands on a tripwire instead of the real tree
    return mod


@contextlib.contextmanager
def recorders(calls: list):
    real_open, real_os_open = builtins.open, os.open

    def rec(name):
        def _f(*a, **k):
            calls.append((name, repr(a)[:200]))
            raise Blocked(name)

        return _f

    def guarded_open(file, mode="r", *a, **k):
        if any(c in str(mode) for c in "wax+"):
            calls.append(("open", f"{file} {mode}"))
            raise Blocked("open")
        return real_open(file, mode, *a, **k)

    def guarded_os_open(path, flags, *a, **k):
        if flags & _WRITE_FLAGS:
            calls.append(("os.open", str(path)))
            raise Blocked("os.open")
        return real_os_open(path, flags, *a, **k)

    patches = [(builtins, "open", guarded_open), (io, "open", guarded_open), (os, "open", guarded_os_open)]
    for mod, names in (
        (os, ("mkdir", "makedirs", "remove", "unlink", "rename", "replace", "rmdir", "kill", "system", "popen",
              "execv", "execve", "execvp", "spawnv", "fork")),
        (shutil, ("rmtree", "move", "copy", "copy2", "copyfile")),
        (subprocess, ("Popen", "run", "call", "check_call", "check_output")),
        (socket.socket, ("connect", "connect_ex", "sendto")),
        (socket, ("create_connection", "getaddrinfo")),
        (urllib.request, ("urlopen",)),
        (http.client.HTTPConnection, ("request", "connect")),
    ):
        for n in names:
            if hasattr(mod, n):
                patches.append((mod, n, rec(f"{getattr(mod, '__name__', mod)}.{n}")))
    saved = [(m, n, getattr(m, n)) for m, n, _ in patches]
    saved_mods = {k: sys.modules.get(k) for k in BROKER_TRIPWIRES}
    try:
        for m, n, f in patches:
            setattr(m, n, f)
        for k in BROKER_TRIPWIRES:
            sys.modules[k] = _tripwire(k, calls)
        yield
    finally:
        for m, n, f in saved:
            setattr(m, n, f)
        for k, v in saved_mods.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def run_py_dry(script: str, argv: list[str]) -> tuple[Any, str, str, list, set]:
    calls: list = []
    out, err = io.StringIO(), io.StringIO()
    before = set(sys.modules)
    saved_argv, saved_path, saved_bc = sys.argv[:], sys.path[:], sys.dont_write_bytecode
    sys.argv = [str(ROOT / script), *argv]
    sys.dont_write_bytecode = True
    code: Any = None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), recorders(calls):
            try:
                runpy.run_path(str(ROOT / script), run_name="__main__")
            except SystemExit as exc:
                code = exc.code
    finally:
        sys.argv, sys.path[:], sys.dont_write_bytecode = saved_argv, saved_path, saved_bc
    new = {m for m in set(sys.modules) - before if m.split(".")[0] not in sys.stdlib_module_names}
    for m in new - ALLOWED_NEW_MODULES:  # never leak a half-imported project module into later tests
        sys.modules.pop(m, None)
    return code, out.getvalue(), err.getvalue(), calls, new


#: External commands a launcher could reach before its guard; each is a recording stub that exits 97.
SHELL_STUBS = (
    "python", "python3", "flock", "timeout", "date", "mkdir", "cat", "tee", "env", "dirname", "basename", "readlink",
    "curl", "wget", "psql", "sqlite3", "bash", "sh", "nice", "id", "touch", "rm", "mv", "cp", "ln", "sed", "awk",
    "grep", "xargs", "jq", "git", "crontab", "systemctl", "pgrep", "pkill", "kill", "sleep", "realpath", "pwd",
)


def run_sh_dry(script: str, argv: list[str], tmp: Path) -> tuple[int, str, str, list[str], list[str]]:
    stubs = tmp / "stubs"
    stubs.mkdir()
    log = tmp / "stub_calls.log"
    for name in SHELL_STUBS:
        p = stubs / name
        p.write_text(f"#!/bin/bash\necho \"{name} $*\" >> {log}\nexit 97\n", encoding="utf-8")
        p.chmod(0o755)
    work = tmp / "work"
    work.mkdir()
    env = {"PATH": str(stubs), "HOME": str(work), "LANG": "C"}
    res = subprocess.run(["/bin/bash", str(ROOT / script), *argv], cwd=work, env=env, capture_output=True,
                         text=True, timeout=30, check=False)
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    created = sorted(str(p.relative_to(work)) for p in work.rglob("*"))
    return res.returncode, res.stdout, res.stderr, calls, created


def lane_output(err: str) -> list[dict[str, Any]]:
    return [json.loads(ln[len("LANE_OUTPUT "):]) for ln in err.splitlines() if ln.startswith("LANE_OUTPUT ")]


def assert_lane_output(lane: str, err: str, reason: str) -> None:
    lines = lane_output(err)
    assert len(lines) == 1, (lane, err)
    doc = lines[0]
    assert doc["schema"] == "LaneOutput@v1" and doc["mode"] == "dry_run", doc
    assert doc["produced_count"] == 0 and doc["attempted_count"] == 0 and doc["empty_reason"] == reason, doc
    assert doc["skipped_reasons"] == {}, doc


def assert_py_guard_first(script: str) -> None:
    """Static: only the docstring, ``from __future__`` and stdlib imports precede the dry-run guard."""
    tree = ast.parse((ROOT / script).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.If) and DRY_ARG in ast.unparse(node.test):
            body = ast.unparse(node)
            assert "raise SystemExit(0)" in body, script
            return
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            assert all(m.split(".")[0] in sys.stdlib_module_names for m in mods), (script, mods)
            continue
        if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant):
            continue
        raise AssertionError(f"{script}: statement before the dry-run guard: {ast.unparse(node)[:120]}")
    raise AssertionError(f"{script}: no dry-run guard")


def assert_sh_guard_first(script: str) -> None:
    """Static: the first non-comment, non-blank line opens the dry-run guard (nothing runs before it)."""
    for raw in (ROOT / script).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        assert line.startswith("if [[ \" $* \" == *\" --dry-run \"* ]]; then"), (script, line)
        return
    raise AssertionError(f"{script}: empty")


def dry_runs(lane: str) -> list[list[str]]:
    """Every live cron argv of the lane plus --dry-run, in both orders (the dry run must win either way)."""
    out = []
    for argv in staged(lane)["cron_argv"]:
        out.append([*argv, DRY_ARG])
        out.append([DRY_ARG, *argv])
    return out


def check_dry_run(lane: str, tmp: Path) -> None:
    block = staged(lane)
    script = block["entry_script"]
    reason = block["dry_run"]["empty_reason"]
    assert reason in REASONS
    for i, argv in enumerate(dry_runs(lane)):
        if script.endswith(".py"):
            code, out, err, calls, new = run_py_dry(script, argv)
            assert code in (0, None), (lane, argv, code, out, err)
            assert calls == [], (lane, argv, calls)
            assert new <= ALLOWED_NEW_MODULES, (lane, sorted(new - ALLOWED_NEW_MODULES))
        else:
            sub = tmp / f"run{i}"
            sub.mkdir()
            code, out, err, calls, created = run_sh_dry(script, argv, sub)
            assert code == 0, (lane, argv, code, out, err)
            assert calls == [], (lane, argv, calls)
            assert created == [], (lane, argv, created)
            assert "command not found" not in err, err
        assert f"DRY-RUN {block['dry_run']['lane_output_lane_id']}:" in out, (lane, out)
        assert_lane_output(block["dry_run"]["lane_output_lane_id"], err, reason)


def check_staged_registry(lane: str) -> None:
    """Staged and inert under ACTIVE §23.14; the activation shape is complete and passes the executor's own check."""
    sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
    try:
        from scripts.lib import lane_dispatch as LD  # noqa: PLC0415
        from n8n_run_executor import validate_entry  # noqa: PLC0415
    finally:
        del sys.path[:2]
    row = registry_rows()[lane]
    block = row["f09_staged"]
    disp = row.get("dispatch")
    assert isinstance(disp, dict) and disp["mode"] == "off", (lane, disp)
    assert disp["retry_policy"] == "none" and disp["class"] == "pipeline", disp
    assert LD.validate_dispatch_block(row) == [], LD.validate_dispatch_block(row)
    assert LD.dispatch_mode(row) == "off" and not LD.dispatchable(row)
    assert (row.get("scheduler") or {}).get("stage") is None, "staged rows carry no ladder stage until activation"
    assert "generated_by" not in row and row.get("adopted_from_generator") in (None, "reconcile_lane_registry@v1")
    al = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    lanes = al["lanes"]
    ids = set(lanes) if isinstance(lanes, dict) else {e.get("lane_id") for e in lanes}
    assert lane not in ids, f"{lane} must not be runnable before AGENTS 12.0.0 is ACTIVE"
    entry = block["activation_allowlist_entry"]
    assert entry["lane_id"] == lane
    assert validate_entry(entry) is None, validate_entry(entry)
    assert entry["dry_run_arg"] == [DRY_ARG] and entry["live_arg"] is None
    assert entry["env_names"] == [] and entry.get("env_allowlist_mode", "enforce") == "enforce"
    assert "output_receipt" not in entry
    assert block["dry_run"]["proof"].startswith("tests/test_onboard_f09_b")
    assert block["policy"].startswith("operator N8N Cutover Decision 2026-10-15")
    assert isinstance(block["order_path"], bool)
    # the entry's script, argv and lock are the live cron line's; the registry match names every recorded line
    lines = [str(x["text"]) for x in block["cron_lines"]]
    match = (row.get("scheduler") or {}).get("match")
    matches = match if isinstance(match, list) else [match]
    assert lines and all(any(m and m in ln for m in matches) for ln in lines), (lane, matches, lines)
    text = " ".join(lines)
    assert block["entry_script"] in text, (lane, text)
    for argv in block["cron_argv"]:
        assert " ".join(argv) in text, (lane, argv, text)
    cron_lock = block.get("cron_lock")
    if cron_lock:
        assert entry["lock"] == cron_lock and cron_lock in text
    else:
        assert any("no flock" in n or "lock" in n for n in block["activation_needs"]), block["activation_needs"]


def check_effect_key(lane: str) -> None:
    spec = json.loads(EFFECT_KEYS.read_text(encoding="utf-8"))["lanes"].get(lane)
    assert spec is not None, f"{lane}: every F09 lane that writes or sends is effect-keyed"
    assert spec["process"] == lane and spec["input_version"] == "v1"
    assert spec["n8n_claim"] is False and spec["cron_claim"] is False, "staged only: neither side claims"
    assert spec["slot"] == "scheduled_minute" and spec["slot_tz"] == "America/New_York"
    assert spec["effects"] and spec["effects"] == staged(lane)["effects"]
    assert spec["wave"] == "F09-staged"


def check_contract(lane: str) -> None:
    sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
    try:
        from scripts.check_n8n_workflow_framework import _check_expected_output  # noqa: PLC0415
        from scripts.lib import n8n_health_contracts as H  # noqa: PLC0415
    finally:
        del sys.path[:2]
    doc = json.loads(CONTRACTS.read_text(encoding="utf-8"))
    c = next((x for x in doc["contracts"] if x.get("id") == lane), None)
    assert c is not None, f"{lane}: no health contract"
    assert H.validate_contract(c) == [], H.validate_contract(c)
    assert c["status"] == "REVIEWED" and "UNKNOWN" not in json.dumps(c)
    assert c["stage"] == "shadow" and c["target_reason"] == "f09_staged"
    res = _check_expected_output(c)
    assert res["status"] == "pass", res
    entry = staged(lane)["activation_allowlist_entry"]
    script = next(t for t in entry["command"] if t.endswith((".py", ".sh")))
    names = " ".join(str(e.get("name")) for e in c["connects_to"])
    assert script in names and entry["lock"] in names


ORDER_NOTE = re.compile(r"trading lock")
