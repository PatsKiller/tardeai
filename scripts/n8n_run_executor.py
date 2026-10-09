#!/usr/bin/env python3
"""n8n run executor: drains REQUESTED rows from the coordination ledger ``runs`` table.

2026-10-08 (n8n scheduler-of-record, tranche N1). The gateway records a run
request and nothing else; this process, in its own cgroup, claims the oldest
REQUESTED row (RUNNING, one transaction), looks the lane up in
config/n8n_run_allowlist.json and runs the lane's OWN command under the lane's
OWN lock::

    bash scripts/safe_flock.sh <lock> timeout -k 30 <timeout_s> [bash scripts/market_day_gate.sh] <command...> <mode arg>

The allowlist is data: a lane missing from it at execution time is RUN_REFUSED,
a mode whose argument is ``null`` is RUN_REFUSED, and nothing here can name a
command that is not in that file. The lock is the lane's existing lock so a cron
line and an n8n fire cannot double-run (``lock_kind: flock`` reuses a cron
``flock -n`` file; the default reuses safe_flock's pid file).

Evidence (rail 8): every claim ends in a RunReceipt@v1 on the ledger row, under
``$TRADEAI_STATE_ROOT/data/runtime/n8n_runs/<run_id>.json`` and as
``n8n_run_executor_last.json``. The receipt carries the exit code, the lock-skip
and timeout verdicts and the output_signal mtime before/after, so an exit 0 that
moved nothing is visible as exactly that.

This process never authenticates a caller, never binds a socket, never sends.
Dry-run before live: the gateway's ``mode`` is passed through verbatim.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

NO_CONSUMER_REASON = (
    "Entrypoint of config/systemd/user/tradeai-n8n-run-executor.service; the unit is committed but not installed "
    "until the operator's config-write grant (plan streamed-humming-wolf, Day 0). Nothing imports this module."
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.n8n_coordination_ledger import (  # noqa: E402
    RUN_FINISHED_STATES,
    CoordinationLedger,
    LedgerRunStore,
)
from scripts.n8n_coordination_gateway import default_ledger_path  # noqa: E402

RECEIPT_SCHEMA = "RunReceipt@v1"
ALLOWLIST_SCHEMA = "N8nRunAllowlist@v1"
RUN_MODES = ("dry_run", "live")
LOCK_KINDS = ("safe_flock", "flock")
FLOCK_CONFLICT_EXIT = 75
TIMEOUT_EXITS = frozenset({124, 137})
KILL_AFTER_S = 30
DEFAULT_INTERVAL_S = 5.0
RUNS_REL = Path("data") / "runtime" / "n8n_runs"
LAST_REL = Path("data") / "runtime" / "n8n_run_executor_last.json"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")
SAFE_FLOCK_SKIP = "safe_flock: skipped"
TAIL_CHARS = 800


#: 2026-10-09 (guardrail audit B, M2): the executor's own env holds the n8n gateway keys, the relay run-scope
#: key and the relay bearer (EnvironmentFile %t/tradeai/env + n8n-gateway.env). A lane gets none of them by
#: default: every name under these prefixes is dropped from the child env before the lane is spawned.
CHILD_ENV_STRIP_PREFIXES = ("TRADEAI_N8N_", "N8N_")
#: Non-secret routing values a lane may still read (where the gateway is, which ledger file).
CHILD_ENV_N8N_NON_SECRET = frozenset({"TRADEAI_N8N_GATEWAY_URL", "TRADEAI_N8N_COORDINATION_LEDGER"})
#: The source-side dispatch key (read scope, caller ``tradeai-*``) is re-admitted ONLY for the lanes whose code
#: signs gateway claims with it (scripts/lib/n8n_gateway_client.py KEY_ENV) and that held it under cron
#: (their retired cron lines sourced %t/tradeai/env). Never the relay key, the relay bearer or any _PREVIOUS key.
GATEWAY_DISPATCH_KEY_ENV = "TRADEAI_N8N_GATEWAY_HMAC_KEY"
CHILD_ENV_LANE_PASSTHROUGH: dict[str, frozenset[str]] = {
    "n8n-pilot-dispatch": frozenset({GATEWAY_DISPATCH_KEY_ENV}),
    "n8n-incident-fanin": frozenset({GATEWAY_DISPATCH_KEY_ENV}),
    "n8n-research-intake-consumer": frozenset({GATEWAY_DISPATCH_KEY_ENV}),
}


class AllowlistError(ValueError):
    pass


def child_env(env: Mapping[str, str], lane_id: str) -> dict[str, str]:
    """The env a lane is spawned with: ``env`` minus every n8n secret, plus only that lane's declared passthrough."""
    keep = CHILD_ENV_N8N_NON_SECRET | CHILD_ENV_LANE_PASSTHROUGH.get(lane_id, frozenset())
    return {k: v for k, v in env.items() if k in keep or not k.startswith(CHILD_ENV_STRIP_PREFIXES)}


def load_allowlist(path: Path) -> dict[str, dict[str, Any]]:
    """lane_id -> entry. Malformed entries are dropped with their reason recorded, not guessed around."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("schema") != ALLOWLIST_SCHEMA:
        raise AllowlistError("bad_allowlist_schema")
    out: dict[str, dict[str, Any]] = {}
    for entry in doc.get("lanes") or []:
        if not isinstance(entry, Mapping):
            continue
        problem = validate_entry(entry)
        if problem is None:
            out[str(entry["lane_id"])] = dict(entry)
    return out


def validate_entry(entry: Mapping[str, Any]) -> str | None:
    """None when the entry is runnable; otherwise the first defect. Pure."""
    if not isinstance(entry.get("lane_id"), str) or not entry["lane_id"]:
        return "missing_lane_id"
    cmd = entry.get("command")
    if not isinstance(cmd, list) or not cmd or not all(isinstance(t, str) and t for t in cmd):
        return "bad_command"
    if not isinstance(entry.get("lock"), str) or not entry["lock"].startswith("/"):
        return "bad_lock"
    if entry.get("lock_kind", "safe_flock") not in LOCK_KINDS:
        return "bad_lock_kind"
    timeout_s = entry.get("timeout_s")
    if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool) or timeout_s <= 0:
        return "bad_timeout"
    modes = 0
    for mode in RUN_MODES:
        arg = entry.get(f"{mode}_arg")
        if arg is None:
            continue
        if not isinstance(arg, list) or not all(isinstance(t, str) for t in arg):
            return f"bad_{mode}_arg"
        modes += 1
    if modes == 0:
        return "no_mode_arg"
    if not isinstance(entry.get("market_gate", False), bool):
        return "bad_market_gate"
    sig = entry.get("output_signal")
    if sig is not None and (not isinstance(sig, str) or sig.startswith("/") or ".." in sig):
        return "bad_output_signal"
    return None


def resolve_token(token: str, *, env: Mapping[str, str], state_root: Path, code_root: Path) -> str:
    py = env.get("TRADEAI_VENV_PYTHON") or sys.executable
    return token.replace("$PY", py).replace("$STATE_ROOT", str(state_root)).replace("$CODE_ROOT", str(code_root))


def build_argv(
    entry: Mapping[str, Any], mode: str, *, env: Mapping[str, str], state_root: Path, code_root: Path
) -> list[str] | None:
    """The exact argv for one run, or None when the mode has no argument on this entry."""
    mode_arg = entry.get(f"{mode}_arg")
    if mode_arg is None:
        return None
    lock = str(entry["lock"])
    if entry.get("lock_kind", "safe_flock") == "flock":
        wrapper = ["flock", "-n", "-E", str(FLOCK_CONFLICT_EXIT), lock]
    else:
        wrapper = ["bash", "scripts/safe_flock.sh", lock]
    gate = ["bash", "scripts/market_day_gate.sh"] if entry.get("market_gate") else []
    cmd = [resolve_token(t, env=env, state_root=state_root, code_root=code_root) for t in entry["command"]]
    args = [resolve_token(t, env=env, state_root=state_root, code_root=code_root) for t in mode_arg]
    return [*wrapper, "timeout", "-k", str(KILL_AFTER_S), str(int(entry["timeout_s"])), *gate, *cmd, *args]


def _mtime(path: Path | None) -> float | None:
    if path is None:
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _code_sha(code_root: Path) -> str | None:
    try:
        text = (code_root / "GIT_SHA").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def execute(
    row: Mapping[str, Any],
    entry: Mapping[str, Any] | None,
    *,
    env: Mapping[str, str],
    state_root: Path,
    code_root: Path,
    runner=None,
) -> dict[str, Any]:
    """Run one claimed row and return its RunReceipt@v1. ``runner`` is injected by tests (argv, timeout -> result)."""
    run_id, lane_id, mode = str(row["run_id"]), str(row["lane_id"]), str(row["mode"])
    started = time.time()
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "run_id": run_id,
        "lane_id": lane_id,
        "mode": mode,
        "exit_code": None,
        "duration_s": None,
        "lock_skipped": False,
        "timed_out": False,
        "output_signal": None,
        "output_signal_mtime_before": None,
        "output_signal_mtime_after": None,
        "started_at": _iso(started),
        "finished_at": None,
        "code_sha": _code_sha(code_root),
        "state": None,
        "reason": None,
        "argv": None,
        "stdout_tail": None,
        "stderr_tail": None,
        "authority": "READ_ONLY_ADVISORY",
    }
    if entry is None:
        return _finish(receipt, "RUN_REFUSED", reason="lane_not_allowlisted", started=started)
    if mode not in RUN_MODES:
        return _finish(receipt, "RUN_REFUSED", reason="bad_mode", started=started)
    argv = build_argv(entry, mode, env=env, state_root=state_root, code_root=code_root)
    if argv is None:
        return _finish(receipt, "RUN_REFUSED", reason=f"mode_unavailable:{mode}", started=started)
    signal_rel = entry.get("output_signal")
    signal_path = (state_root / signal_rel) if isinstance(signal_rel, str) else None
    receipt["output_signal"] = signal_rel
    receipt["output_signal_mtime_before"] = _mtime(signal_path)
    receipt["argv"] = argv
    timeout_s = float(entry["timeout_s"])
    run = runner or _subprocess_runner
    try:
        result = run(argv, timeout=timeout_s + KILL_AFTER_S + 30, env=child_env(env, lane_id), cwd=code_root)
    except subprocess.TimeoutExpired:
        receipt["timed_out"] = True
        receipt["output_signal_mtime_after"] = _mtime(signal_path)
        return _finish(receipt, "RUN_TIMEOUT", reason="executor_deadline", started=started)
    except OSError as exc:
        receipt["output_signal_mtime_after"] = _mtime(signal_path)
        return _finish(receipt, "RUN_FAILED", reason=f"spawn:{type(exc).__name__}", started=started)
    receipt["exit_code"] = int(result.returncode)
    receipt["stdout_tail"] = (result.stdout or "")[-TAIL_CHARS:] or None
    receipt["stderr_tail"] = (result.stderr or "")[-TAIL_CHARS:] or None
    receipt["output_signal_mtime_after"] = _mtime(signal_path)
    lock_kind = entry.get("lock_kind", "safe_flock")
    if lock_kind == "flock" and result.returncode == FLOCK_CONFLICT_EXIT:
        receipt["lock_skipped"] = True
        return _finish(receipt, "RUN_SKIPPED_LOCK", reason="flock_held", started=started)
    if lock_kind == "safe_flock" and result.returncode == 0 and SAFE_FLOCK_SKIP in (result.stderr or ""):
        receipt["lock_skipped"] = True
        return _finish(receipt, "RUN_SKIPPED_LOCK", reason="safe_flock_pid_running", started=started)
    if result.returncode in TIMEOUT_EXITS:
        receipt["timed_out"] = True
        return _finish(receipt, "RUN_TIMEOUT", reason=f"timeout_exit_{result.returncode}", started=started)
    if result.returncode == 0:
        return _finish(receipt, "RUN_DONE", reason=None, started=started)
    return _finish(receipt, "RUN_FAILED", reason=f"exit_{result.returncode}", started=started)


def _subprocess_runner(
    argv: list[str], *, timeout: float, env: dict[str, str], cwd: Path
) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, cwd=str(cwd), check=False)


def _finish(receipt: dict[str, Any], state: str, *, reason: str | None, started: float) -> dict[str, Any]:
    assert state in RUN_FINISHED_STATES, state
    ended = time.time()
    receipt["state"] = state
    receipt["reason"] = reason
    receipt["duration_s"] = round(ended - started, 3)
    receipt["finished_at"] = _iso(ended)
    return receipt


def write_receipt(receipt: Mapping[str, Any], *, state_root: Path) -> Path:
    run_id = str(receipt["run_id"])
    if not RUN_ID_RE.fullmatch(run_id):
        run_id = re.sub(r"[^A-Za-z0-9._:-]", "_", run_id)[:128]
    runs_dir = state_root / RUNS_REL
    runs_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(dict(receipt), indent=1, sort_keys=True, default=str) + "\n"
    out = runs_dir / f"{run_id}.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, out)
    last = state_root / LAST_REL
    last.parent.mkdir(parents=True, exist_ok=True)
    tmp = last.with_suffix(".json.tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, last)
    return out


def drain(
    store: LedgerRunStore,
    allowlist: Mapping[str, Mapping[str, Any]],
    *,
    env: Mapping[str, str],
    state_root: Path,
    code_root: Path,
    runner=None,
    max_runs: int | None = None,
) -> list[dict[str, Any]]:
    """Claim and execute until the queue is empty (or max_runs). One receipt per claimed row, always."""
    out: list[dict[str, Any]] = []
    while max_runs is None or len(out) < max_runs:
        row = store.claim_next()
        if row is None:
            break
        receipt = execute(
            row, allowlist.get(str(row["lane_id"])), env=env, state_root=state_root, code_root=code_root, runner=runner
        )
        store.finish(str(row["run_id"]), state=str(receipt["state"]), receipt=receipt)
        try:
            write_receipt(receipt, state_root=state_root)
        except OSError as exc:  # the ledger row is the record of truth; the file is a convenience copy
            print(json.dumps({"run_id": row["run_id"], "receipt_file": f"failed:{type(exc).__name__}"}), flush=True)
        print(
            json.dumps(
                {
                    k: receipt.get(k)
                    for k in (
                        "run_id",
                        "lane_id",
                        "mode",
                        "state",
                        "exit_code",
                        "duration_s",
                        "lock_skipped",
                        "timed_out",
                    )
                }
            ),
            flush=True,
        )
        out.append(receipt)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="n8n run executor (drains the coordination ledger runs table)")
    ap.add_argument(
        "--ledger", default=None, help="SQLite coordination ledger (default: persistent-state governance dir)"
    )
    ap.add_argument(
        "--allowlist", default=None, help="N8nRunAllowlist@v1 (default: <code-root>/config/n8n_run_allowlist.json)"
    )
    ap.add_argument("--code-root", default=None, help="tree whose scripts/ are executed (default: this file's tree)")
    ap.add_argument("--state-root", default=None, help="TRADEAI_STATE_ROOT override")
    ap.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_S, help="poll interval seconds")
    ap.add_argument("--once", action="store_true", help="drain the queue once and exit (tests, manual fires)")
    args = ap.parse_args(argv)
    env = dict(os.environ)
    code_root = Path(args.code_root).resolve() if args.code_root else ROOT
    state_root = Path(
        args.state_root or env.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state")
    )
    env["TRADEAI_STATE_ROOT"] = str(state_root)
    allowlist_path = Path(args.allowlist) if args.allowlist else code_root / "config" / "n8n_run_allowlist.json"
    ledger_path = Path(args.ledger) if args.ledger else default_ledger_path(env)
    try:
        allowlist = load_allowlist(allowlist_path)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": f"allowlist:{type(exc).__name__}", "path": str(allowlist_path)}), file=sys.stderr)
        return 2
    (state_root / RUNS_REL / "shadow").mkdir(parents=True, exist_ok=True)
    ledger = CoordinationLedger(ledger_path)
    store = LedgerRunStore(ledger)
    print(
        json.dumps(
            {
                "executor": "started",
                "ledger": str(ledger_path),
                "allowlist": str(allowlist_path),
                "lanes": sorted(allowlist),
                "code_root": str(code_root),
                "once": bool(args.once),
            }
        ),
        flush=True,
    )
    try:
        while True:
            drain(store, allowlist, env=env, state_root=state_root, code_root=code_root)
            if args.once:
                return 0
            time.sleep(max(0.5, float(args.interval)))
    except KeyboardInterrupt:
        return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
