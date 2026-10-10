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

2026-10-09 (n8n maturity B5.5, design 02 §5): executor v2 — ``ExecutorV2`` below. N worker threads
(``--workers`` / ``TRADEAI_N8N_EXECUTOR_WORKERS`` >= 2, max 8; OPT-IN, the default is 1) with a per-lane lock in the
ledger claim,
class caps, a reserved priority worker, a stale-RUNNING reaper, verdict/DLQ/breaker via
``n8n_retry_policy.finalize_outcome``, RunReceipt@v2 per run and ExecutorStatus@v1 as the last file.
Unset, ``1`` or an invalid value (``abc``, ``""``, ``2.5``: logged) is the v1 serial ``drain`` and RunReceipt@v1,
unchanged, so an installed unit with no env stays v1 until the operator opts in. Intervals and limits:
config/n8n_executor.json (N8nExecutorConfig@v1), read only on the v2 path.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
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
    DEFAULT_RUN_PRIORITY,
    RUN_FINISHED_STATES,
    CoordinationLedger,
    LedgerError,
    LedgerRunStore,
)
from scripts.lib.n8n_retry_policy import RetryPolicyError, class_verdict, finalize_outcome, load_policies  # noqa: E402
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
# Bounded retry (2026-10-09 audit: RUN_FAILED / RUN_TIMEOUT were terminal and no workflow had retryOnFail).
# Opt-in per allowlist entry: "retry": {"max": 1, "backoff_s": 60, "on": ["RUN_FAILED", "RUN_TIMEOUT"]}.
# Off by default: only an entry whose command is safe to re-run (idempotent, same lock) may set it.
RETRY_MAX_CAP = 3
RETRY_BACKOFF_CAP_S = 300.0
RETRYABLE_STATES = ("RUN_FAILED", "RUN_TIMEOUT")


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
    if entry.get("retry") is not None and retry_policy(entry) is None:
        return "bad_retry"
    return None


def retry_policy(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    """The entry's validated retry policy, {"max": 0, ...} when absent, None when malformed. Pure."""
    raw = entry.get("retry")
    if raw is None:
        return {"max": 0, "backoff_s": 0.0, "on": RETRYABLE_STATES}
    if not isinstance(raw, Mapping):
        return None
    n, backoff = raw.get("max", 0), raw.get("backoff_s", 0)
    on = raw.get("on", list(RETRYABLE_STATES))
    if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= RETRY_MAX_CAP:
        return None
    if not isinstance(backoff, (int, float)) or isinstance(backoff, bool) or not 0 <= backoff <= RETRY_BACKOFF_CAP_S:
        return None
    if not isinstance(on, list) or not on or any(st not in RETRYABLE_STATES for st in on):
        return None
    return {"max": n, "backoff_s": float(backoff), "on": tuple(on)}


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
    sleeper=time.sleep,
    v2: bool = False,
) -> dict[str, Any]:
    """Run one claimed row (plus the entry's opt-in bounded retries) and return its RunReceipt@v1.

    ``runner`` / ``sleeper`` are injected by tests. The receipt is the LAST attempt's, with ``attempts`` and
    ``attempt_states`` recording every try; ``started_at`` and ``output_signal_mtime_before`` stay the first's.

    ``v2`` (executor v2 workers only): typed spawn reasons, and NO in-process allowlist ``retry`` loop — under v2
    the ledger retry policy (verdict -> coordination/due mints attempt + 1) is the single retry layer; a second,
    in-worker layer would sleep without heartbeats and outlive the reaper's overdue bound. An entry that declares
    ``retry`` gets ``allowlist_retry: "ignored_v2"`` on its receipt. The v1 path (``v2=False``) is unchanged.
    """
    receipt = _execute_once(row, entry, env=env, state_root=state_root, code_root=code_root, runner=runner, typed=v2)
    policy = retry_policy(entry) if entry is not None and not v2 else None
    states = [str(receipt["state"])]
    first = receipt
    while policy and len(states) <= policy["max"] and states[-1] in policy["on"]:
        sleeper(policy["backoff_s"])
        receipt = _execute_once(row, entry, env=env, state_root=state_root, code_root=code_root, runner=runner,
                                typed=v2)
        states.append(str(receipt["state"]))
    if len(states) > 1:
        receipt["started_at"] = first["started_at"]
        receipt["output_signal_mtime_before"] = first["output_signal_mtime_before"]
    receipt["attempts"] = len(states)
    receipt["attempt_states"] = states
    if v2 and entry is not None and entry.get("retry") is not None:
        receipt["allowlist_retry"] = "ignored_v2"
    return receipt


def _execute_once(
    row: Mapping[str, Any],
    entry: Mapping[str, Any] | None,
    *,
    env: Mapping[str, str],
    state_root: Path,
    code_root: Path,
    runner=None,
    typed: bool = False,
) -> dict[str, Any]:
    """One attempt: run the claimed row and return its RunReceipt@v1. ``typed`` (executor v2 only) adds the errno
    name to a spawn failure's reason (``spawn:OSError:ENOMEM``) so the retry policy can match it."""
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
        reason = f"spawn:{type(exc).__name__}"
        if typed and exc.errno in errno.errorcode:
            reason = f"{reason}:{errno.errorcode[exc.errno]}"
        return _finish(receipt, "RUN_FAILED", reason=reason, started=started)
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


def write_receipt(receipt: Mapping[str, Any], *, state_root: Path, write_last: bool = True) -> Path:
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
    if not write_last:  # executor v2: n8n_run_executor_last.json holds ExecutorStatus@v1 instead
        return out
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
        try:
            store.finish(str(row["run_id"]), state=str(receipt["state"]), receipt=receipt)
        except LedgerError as exc:  # B2: another executor finished (reaped) the row meanwhile; keep draining
            print(json.dumps({"run_id": row["run_id"], "finish_error": exc.reason}), flush=True)
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


# ── Executor v2 (n8n maturity B5.5, design 02 §5, §3.4, F4/F10/F19) ─────────────────────────────────────────────
# One process: a scheduler loop plus N worker threads, each running one subprocess (the unchanged build_argv
# result). N = --workers / TRADEAI_N8N_EXECUTOR_WORKERS (default 1, max 8). OPT-IN: N == 1 (unset, invalid) runs the
# v1 serial ``drain`` above, byte-for-byte the old behaviour and RunReceipt@v1. N >= 2: per-lane exclusivity in the
# ledger claim (claim_next_v2), a global cap of min(N, class_caps.global), class caps from
# config/n8n_retry_policies.json#class_caps, one
# worker reserved for priority <= reserved_priority_max, a stale-RUNNING reaper (RUN_TIMEOUT executor_lost), the
# verdict / dead letter / breaker through n8n_retry_policy.finalize_outcome, RunReceipt@v2 per run and
# ExecutorStatus@v1 in n8n_run_executor_last.json every loop. Still never authenticates, binds or sends.

RECEIPT_SCHEMA_V2 = "RunReceipt@v2"
STATUS_SCHEMA = "ExecutorStatus@v1"
EXECUTOR_CONFIG_SCHEMA = "N8nExecutorConfig@v1"
WORKERS_ENV = "TRADEAI_N8N_EXECUTOR_WORKERS"
#: B3 (review #1598): v2 is OPT-IN. The installed unit carries no workers env, so a restart after promote stays on
#: the v1 serial drain until the operator sets TRADEAI_N8N_EXECUTOR_WORKERS >= 2 for the load test.
DEFAULT_WORKERS = 1
MAX_WORKERS = 8  # hard ceiling; config max_workers may lower it, never raise it
DEFAULT_CLASS = "report"
NON_CLASS_CAP_KEYS = frozenset({"global", "reserved_priority_max"})
LOST_REASON = "executor_lost"
RETRY_POLICIES_REL = Path("config") / "n8n_retry_policies.json"
EXECUTOR_CONFIG_REL = Path("config") / "n8n_executor.json"
#: Fallbacks for config/n8n_executor.json (the values in that file today). Name -> (default, min, max).
EXECUTOR_DEFAULTS: dict[str, tuple[float, float, float]] = {
    "max_workers": (8, 2, MAX_WORKERS),
    "heartbeat_s": (30.0, 1.0, 600.0),
    "stale_heartbeat_s": (90.0, 3.0, 3600.0),
    "reap_every_s": (60.0, 1.0, 3600.0),
    "lost_grace_s": (120.0, 0.0, 3600.0),
    "heavy_timeout_s": (1800, 1, 86400),  # an allowlist timeout_s at or above this derives class "heavy"
    "unknown_lane_timeout_s": (3600, 1, 86400),
    "dlq_window_s": (86400.0, 60.0, 30 * 86400.0),
    "poll_s": (2.0, 0.05, 60.0),
    "finish_retry_attempts": (5, 1, 20),
    "finish_retry_backoff_s": (0.5, 0.0, 30.0),
    "finish_retry_backoff_max_s": (8.0, 0.0, 120.0),
    "status_queue_limit": (5000, 10, 100000),
    "receipt_history": (200, 1, 10000),
}
_INT_KEYS = frozenset({"max_workers", "heavy_timeout_s", "unknown_lane_timeout_s", "finish_retry_attempts",
                       "status_queue_limit", "receipt_history"})
#: A failed run whose output tail matches one of these gets the typed reason ``<TYPE>:<old reason>`` (the retry
#: rails match COST_CAP / PEAK_SKIP on the reason text; llm-class lanes are terminal on them whatever the policy).
TYPED_REASON_MARKERS: dict[str, str] = {"COST_CAP": r"(?i)cost_cap|skipped_budget", "PEAK_SKIP": r"(?i)peak_skip"}


def _warn(doc: Mapping[str, Any]) -> None:
    print(json.dumps(dict(doc), default=str), file=sys.stderr, flush=True)


def load_executor_config(path: Path | None) -> dict[str, Any]:
    """config/n8n_executor.json merged over EXECUTOR_DEFAULTS. A missing/unreadable file, a wrong schema or a
    missing/non-numeric/out-of-range key keeps the code default and logs one warning; never raises."""
    cfg: dict[str, Any] = {k: (int(v[0]) if k in _INT_KEYS else float(v[0])) for k, v in EXECUTOR_DEFAULTS.items()}
    cfg["typed_reason_markers"] = dict(TYPED_REASON_MARKERS)
    doc: Any = None
    if path is not None:
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _warn({"executor": "config_default", "path": str(path), "reason": type(exc).__name__})
    if not isinstance(doc, Mapping) or doc.get("schema") != EXECUTOR_CONFIG_SCHEMA:
        if doc is not None:
            _warn({"executor": "config_default", "path": str(path), "reason": "bad_schema"})
        return cfg
    for key, (_default, lo, hi) in EXECUTOR_DEFAULTS.items():
        if key not in doc:
            _warn({"executor": "config_default", "key": key, "reason": "missing"})
            continue
        v = doc[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi \
                or (key in _INT_KEYS and int(v) != v):
            _warn({"executor": "config_default", "key": key, "reason": "out_of_range"})
            continue
        cfg[key] = int(v) if key in _INT_KEYS else float(v)
    markers = doc.get("typed_reason_markers")
    if isinstance(markers, Mapping):
        good: dict[str, str] = {}
        for name, pat in markers.items():
            try:
                if isinstance(name, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,40}", name) and isinstance(pat, str):
                    re.compile(pat)
                    good[name] = pat
                    continue
            except re.error:
                pass
            _warn({"executor": "config_default", "key": f"typed_reason_markers.{name}", "reason": "bad_pattern"})
        cfg["typed_reason_markers"] = good
    return cfg


def resolve_workers(cli_value: int | None, env: Mapping[str, str], max_workers: int = MAX_WORKERS) -> int:
    """--workers, else TRADEAI_N8N_EXECUTOR_WORKERS, else 1; clamped to 1..max_workers. v2 is opt-in: an
    invalid env value (``abc``, ``""``, ``2.5``) is 1 (the v1 path) with a logged warning, never v2."""
    if cli_value is not None:
        raw: Any = cli_value
    elif WORKERS_ENV in env:
        raw = env[WORKERS_ENV]
    else:
        return DEFAULT_WORKERS
    text = str(raw).strip()
    if not re.fullmatch(r"-?\d+", text):
        _warn({"executor": "workers_invalid", "value": text[:16], "workers": DEFAULT_WORKERS})
        return DEFAULT_WORKERS
    n = int(text)
    if not 1 <= n <= max_workers:
        _warn({"executor": "workers_clamped", "value": n, "workers": max(1, min(max_workers, n))})
    return max(1, min(max_workers, n))


def derived_class(entry: Mapping[str, Any] | None,
                  heavy_timeout_s: float = EXECUTOR_DEFAULTS["heavy_timeout_s"][0]) -> str:
    """Class for a run whose ``runs.class`` is NULL: heavy when the allowlist timeout_s >= heavy_timeout_s
    (config, 1800), else report."""
    t = (entry or {}).get("timeout_s")
    return "heavy" if isinstance(t, (int, float)) and not isinstance(t, bool) and t >= heavy_timeout_s \
        else DEFAULT_CLASS


def typed_reason(receipt: Mapping[str, Any], markers: Mapping[str, str] = TYPED_REASON_MARKERS) -> str | None:
    """The receipt's reason, prefixed ``<TYPE>:`` when a RUN_FAILED / RUN_TIMEOUT run's stdout/stderr tail carries
    a typed marker (COST_CAP, PEAK_SKIP). Other states and unmarked runs keep their reason. Pure."""
    reason = receipt.get("reason")
    if receipt.get("state") not in ("RUN_FAILED", "RUN_TIMEOUT") or reason == LOST_REASON:
        return reason
    text = f"{receipt.get('stdout_tail') or ''}\n{receipt.get('stderr_tail') or ''}"
    for name, pat in markers.items():
        if re.search(pat, text) and not str(reason or "").startswith(f"{name}:"):
            return f"{name}:{reason}" if reason else name
    return reason


def _dispatch_loader():
    """The B5.2 registry dispatch-block parser when it has merged, else None."""
    try:
        from scripts.lib import lane_dispatch  # type: ignore[attr-defined]

        fn = getattr(lane_dispatch, "parse_dispatch_block", None)
        if callable(fn):
            return fn
    except ImportError:
        pass
    try:
        from scripts.lib import lane_registry

        fn = getattr(lane_registry, "parse_dispatch_block", None)
        return fn if callable(fn) else None
    except ImportError:
        return None


def _registry_row(lane_id: str, registry_rows) -> Mapping[str, Any] | None:
    for row in registry_rows or ():
        if isinstance(row, Mapping) and row.get("lane_id") == lane_id:
            return row
    return None


def resolve_retry_policy(lane_id: str, policies, registry_rows=None):
    """The lane's RetryPolicy: ``policies.get(<registry dispatch.retry_policy>)`` (the B5.2 loader when importable,
    else the row's raw ``dispatch`` block). A lane with no row, no block or an unknown name gets
    ``policies.get(None|name)`` = UNRESOLVED_POLICY (#1594: single attempt, every failure terminal), never the
    file's default_policy."""
    row = _registry_row(lane_id, registry_rows)
    name: Any = None
    if row is not None:
        loader = _dispatch_loader()
        block: Any = None
        if loader is not None:
            try:
                block = loader(row)
            except Exception:  # noqa: BLE001 — a bad dispatch block resolves to UNRESOLVED, never crashes a run
                block = None
        if not isinstance(block, Mapping):
            block = row.get("dispatch") if isinstance(row.get("dispatch"), Mapping) else {}
        name = block.get("retry_policy") if isinstance(block, Mapping) else None
    return policies.get(name if isinstance(name, str) and name else None)


def _lane_severity(lane_id: str, registry_rows) -> str | None:
    watch = (_registry_row(lane_id, registry_rows) or {}).get("watch")
    sev = watch.get("severity") if isinstance(watch, Mapping) else None
    return sev if sev in ("P1", "P2", "P3") else None


def pid_alive(pid: int | None) -> bool:
    if not pid or int(pid) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _ts(value: Any) -> float | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def heartbeat_runner(on_spawn, on_beat, heartbeat_s: float = EXECUTOR_DEFAULTS["heartbeat_s"][0]):
    """A runner (same contract as ``_subprocess_runner``) that reports the child pid on spawn and every
    ``heartbeat_s`` while it runs, so the ledger row's heartbeat_at/pid stay fresh for the reaper."""

    def run(argv: list[str], *, timeout: float, env: dict[str, str], cwd: Path):
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=str(cwd))
        on_spawn(proc.pid)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                proc.communicate()
                raise subprocess.TimeoutExpired(argv, timeout)
            try:
                out, err = proc.communicate(timeout=min(heartbeat_s, remaining))
                return subprocess.CompletedProcess(argv, proc.returncode, out, err)
            except subprocess.TimeoutExpired:
                on_beat(proc.pid)

    return run


def upgrade_receipt(receipt: Mapping[str, Any], row: Mapping[str, Any], *, klass: str, priority: int,
                    worker_id: str | None, verdict: str, retry_policy: str) -> dict[str, Any]:
    """RunReceipt@v1 fields + the v2 dispatch fields. Pure."""
    started, requested = _ts(row.get("started_at")), _ts(row.get("requested_at"))
    out = dict(receipt)
    out.update({
        "schema": RECEIPT_SCHEMA_V2,
        "slot_key": row.get("slot_key"),
        "attempt": int(row.get("attempt") or 1),
        "parent_run_id": row.get("parent_run_id"),
        "class": klass,
        "priority": int(priority),
        "worker_id": worker_id,
        "queue_wait_s": None if started is None or requested is None else round(max(0.0, started - requested), 3),
        "verdict": verdict,
        "retry_policy": retry_policy,
    })
    return out


class ExecutorV2:
    """Scheduler loop + N worker threads over one LedgerRunStore (design 02 §5). ``clock``, ``runner_factory``,
    ``pid_alive``, ``sleeper`` and every interval are injectable so tests run on a fake clock with fake runners.
    Intervals and limits come from ``config`` (``load_executor_config``); an explicit keyword overrides it."""

    def __init__(self, store: LedgerRunStore, allowlist: Mapping[str, Mapping[str, Any]], *, env: Mapping[str, str],
                 state_root: Path, code_root: Path, workers: int, policies, registry_rows=None, clock=time.time,
                 runner_factory=None, pid_alive=pid_alive, config: Mapping[str, Any] | None = None,
                 heartbeat_s: float | None = None, stale_heartbeat_s: float | None = None,
                 reap_every_s: float | None = None, lost_grace_s: float | None = None,
                 worker_prefix: str | None = None, quiet: bool = False, sleeper=time.sleep) -> None:
        cfg = dict(load_executor_config(None))
        cfg.update(config or {})
        if not 2 <= int(workers) <= min(MAX_WORKERS, int(cfg["max_workers"])):
            raise ValueError("ExecutorV2 needs 2..max_workers workers; 1 is the v1 serial drain")
        self.cfg = cfg
        self.store, self.allowlist, self.env = store, allowlist, env
        self.state_root, self.code_root = state_root, code_root
        self.workers, self.policies, self.registry_rows = int(workers), policies, registry_rows
        self.clock, self.runner_factory, self.pid_alive, self.sleeper = clock, runner_factory, pid_alive, sleeper
        self.heartbeat_s = float(cfg["heartbeat_s"] if heartbeat_s is None else heartbeat_s)
        self.stale_heartbeat_s = float(cfg["stale_heartbeat_s"] if stale_heartbeat_s is None else stale_heartbeat_s)
        self.reap_every_s = float(cfg["reap_every_s"] if reap_every_s is None else reap_every_s)
        self.lost_grace_s = float(cfg["lost_grace_s"] if lost_grace_s is None else lost_grace_s)
        self.quiet = quiet
        self.caps = {k: int(v) for k, v in policies.class_caps.items() if k not in NON_CLASS_CAP_KEYS}
        self.reserved_priority_max = int(policies.class_caps.get("reserved_priority_max", 1))
        # class_caps.global bounds every RUNNING row in the ledger (all executors); the workers bound this process
        glob = policies.class_caps.get("global")
        self.capacity = min(self.workers, int(glob)) if isinstance(glob, int) and glob >= 1 else self.workers
        heavy = cfg["heavy_timeout_s"]
        self.default_classes = {lane: derived_class(e, heavy) for lane, e in allowlist.items()}
        self.worker_prefix = worker_prefix or f"{os.uname().nodename}:{os.getpid()}"
        self._lock = threading.Lock()
        self._slots: list[dict[str, Any] | None] = [None] * self.workers
        self._threads: list[threading.Thread | None] = [None] * self.workers
        self._wake = threading.Event()
        self._last_reap: float | None = None
        self.reaped_total = 0
        self.receipts: list[dict[str, Any]] = []
        self._findings: dict[str, dict[str, Any]] = {}
        self._last_receipt: dict[str, Any] | None = None
        # B1: runs whose finish / finalize_outcome exhausted the bounded retry; retried every step, never reaped
        self._pending: dict[str, dict[str, Any]] = {}

    # -- helpers --
    def worker_id(self, i: int) -> str:
        return f"{self.worker_prefix}:w{i}"

    def class_of(self, row: Mapping[str, Any]) -> str:
        return str(row.get("effective_class") or row.get("class") or self.default_classes.get(str(row["lane_id"]))
                   or DEFAULT_CLASS)

    def busy(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(s) for s in self._slots if s is not None]

    def pending(self) -> list[str]:
        with self._lock:
            return sorted(self._pending)

    def _log(self, doc: Mapping[str, Any]) -> None:
        if not self.quiet:
            print(json.dumps(dict(doc), default=str), flush=True)

    # -- scheduler --
    def step(self) -> int:
        """One scheduler iteration: retry pending completions, reap when due, fill free workers, write
        ExecutorStatus@v1. Returns runs started."""
        self.retry_pending()
        now = self.clock()
        if self._last_reap is None or now - self._last_reap >= self.reap_every_s:
            self.reap(now)
            self._last_reap = now
        started = self.fill(self.clock())
        self.write_status(self.clock())
        return started

    def fill(self, now: float) -> int:
        started = 0
        while True:
            with self._lock:
                free = [i for i, s in enumerate(self._slots) if s is None]
            if not free:
                return started
            busy = self.workers - len(free)
            running = self.store.list_running()
            used = max(busy, len(running))
            if used >= self.capacity:            # class_caps.global (or N) RUNNING rows: nothing more starts
                return started
            counts: dict[str, int] = {}
            for r in running:
                k = self.class_of(r)
                counts[k] = counts.get(k, 0) + 1
            exclude = sorted(c for c, cap in self.caps.items() if counts.get(c, 0) >= cap)
            # the last free unit of capacity is the reserved one: it only takes priority <= reserved_priority_max
            max_p = self.reserved_priority_max if self.capacity >= 2 and used >= self.capacity - 1 else None
            i = free[0]
            row = self.store.claim_next_v2(worker_id=self.worker_id(i), exclude_classes=exclude, max_priority=max_p,
                                           now=now, default_classes=self.default_classes)
            if row is None:
                return started
            self._start(i, row)
            started += 1

    def _start(self, i: int, row: dict[str, Any]) -> None:
        slot = {"worker_id": self.worker_id(i), "run_id": str(row["run_id"]), "lane_id": str(row["lane_id"]),
                "class": self.class_of(row), "priority": int(row.get("effective_priority") or 0),
                "started_at": row.get("started_at")}
        with self._lock:
            self._slots[i] = slot
        t = threading.Thread(target=self._work, args=(i, row, slot), name=f"n8n-exec-w{i}", daemon=True)
        self._threads[i] = t
        t.start()

    def _work(self, i: int, row: dict[str, Any], slot: Mapping[str, Any]) -> None:
        run_id = str(row["run_id"])
        try:
            def beat(pid: int | None) -> None:
                try:
                    self.store.touch_heartbeat(run_id, pid, self.clock())
                except Exception:  # noqa: BLE001 — a missed beat is survivable; the reaper allows 3
                    pass

            factory = self.runner_factory or (lambda on_spawn, on_beat: heartbeat_runner(on_spawn, on_beat,
                                                                                          self.heartbeat_s))
            receipt = execute(row, self.allowlist.get(str(row["lane_id"])), env=self.env, state_root=self.state_root,
                              code_root=self.code_root, runner=factory(beat, beat), v2=True)
            self.complete(row, receipt, klass=str(slot["class"]), priority=int(slot["priority"]),
                          worker_id=str(slot["worker_id"]))
        except Exception as exc:  # noqa: BLE001 — never lose a worker; the row stays RUNNING for the reaper
            self._log({"run_id": run_id, "worker_error": f"{type(exc).__name__}:{str(exc)[:120]}"})
        finally:
            with self._lock:
                self._slots[i] = None
            self._wake.set()

    def _retry(self, fn, what: str, run_id: str, attempts: int | None = None):
        """``fn()`` with bounded exponential backoff on a transient ledger error (sqlite ``database is locked``
        past the 5 s busy timeout, an I/O hiccup). Re-raises the last error once ``attempts`` are spent."""
        n = int(self.cfg["finish_retry_attempts"] if attempts is None else attempts)
        delay, cap = float(self.cfg["finish_retry_backoff_s"]), float(self.cfg["finish_retry_backoff_max_s"])
        for k in range(1, n + 1):
            try:
                return fn()
            except (sqlite3.OperationalError, OSError) as exc:
                self._log({"run_id": run_id, "retry": what, "attempt": k, "of": n,
                           "error": f"{type(exc).__name__}:{str(exc)[:120]}"})
                if k >= n:
                    raise
                self.sleeper(min(delay, cap))
                delay = delay * 2 if delay > 0 else 0.0
        raise AssertionError("unreachable")

    def _finish_row(self, run_id: str, out: Mapping[str, Any]) -> dict[str, Any] | None:
        """store.finish, idempotent: a LedgerError on a row that already holds THIS receipt (an earlier try that
        committed before its error surfaced) is success. None when someone else finished the row (reaped)."""
        try:
            return self.store.finish(run_id, state=str(out["state"]), receipt=out, now=self.clock())
        except LedgerError:
            cur = self.store.get(run_id)
            rec = (cur or {}).get("receipt")
            if cur is not None and cur.get("state") == out["state"] and isinstance(rec, Mapping) \
                    and rec.get("worker_id") == out.get("worker_id") and rec.get("finished_at") == out.get("finished_at"):
                return cur
            raise

    def _finalize(self, finished: Mapping[str, Any], job: Mapping[str, Any]) -> bool:
        """finalize_outcome (idempotent: verdict set, dead letter upserted by slot key, breaker opened only when
        closed). True when a dead letter was written."""
        outcome = finalize_outcome(self.store, finished, job["policy"], breaker_threshold=self.policies.breaker_threshold,
                                   now=self.clock(), severity=job["severity"], klass=job["klass"])
        with self._lock:
            for f in outcome.findings:
                self._findings[str(f["item"])] = dict(f)
        return outcome.dead_letter is not None

    def _advance(self, job: dict[str, Any], *, attempts: int | None = None) -> str:
        """Drive one completion through finish -> finalize. Returns "done", "lost" (finished elsewhere) or
        "pending" (a transient ledger error outlasted the bounded retry)."""
        run_id, out = job["run_id"], job["out"]
        out.pop("complete_pending", None)       # never stored on the ledger row: it only marks a parked run
        try:
            if job["stage"] == "finish":
                try:
                    finished = self._retry(lambda: self._finish_row(run_id, out), "finish", run_id, attempts)
                except LedgerError as exc:  # reaped (or finished) meanwhile: the ledger row already holds a verdict
                    out["finish_error"] = exc.reason
                    return "lost"
                job["finished"], job["stage"] = finished, "finalize"
            job["dead"] = self._retry(lambda: self._finalize(job["finished"], job), "finalize", run_id, attempts)
            return "done"
        except (sqlite3.OperationalError, OSError) as exc:
            out["complete_pending"] = f"{job['stage']}:{type(exc).__name__}"
            return "pending"

    def retry_pending(self) -> None:
        """One try (no backoff) per pending completion; a run stays owned (never reaped) until it lands."""
        with self._lock:
            jobs = list(self._pending.values())
        for job in jobs:
            state = self._advance(job, attempts=1)
            if state != "pending":
                with self._lock:
                    self._pending.pop(job["run_id"], None)
                self._record(job)

    def complete(self, row: Mapping[str, Any], receipt: Mapping[str, Any], *, klass: str, priority: int,
                 worker_id: str | None) -> dict[str, Any]:
        """finish + verdict + finalize_outcome + receipt file for one executed (or reaped) run. B1: finish and
        finalize_outcome retry with bounded backoff; past that the run is parked in ``_pending`` (still owned by
        this process, so the reaper never turns an exit-0 run into executor_lost) and retried every step."""
        lane = str(row["lane_id"])
        policy = resolve_retry_policy(lane, self.policies, self.registry_rows)
        rec = dict(receipt)
        rec["reason"] = typed_reason(rec, self.cfg["typed_reason_markers"])
        exit_code = rec.get("exit_code")
        v = class_verdict(str(rec["state"]), exit_code if isinstance(exit_code, int) else None, rec.get("reason"),
                          policy, klass)
        out = upgrade_receipt(rec, row, klass=klass, priority=priority, worker_id=worker_id, verdict=v,
                              retry_policy=policy.name)
        job = {"run_id": str(row["run_id"]), "out": out, "policy": policy, "klass": klass, "stage": "finish",
               "severity": _lane_severity(lane, self.registry_rows), "dead": False, "finished": None}
        if self._advance(job) == "pending":
            with self._lock:
                self._pending[job["run_id"]] = job
            self._log({"run_id": job["run_id"], "complete_pending": out.get("complete_pending")})
            return out
        self._record(job)
        return out

    def _record(self, job: Mapping[str, Any]) -> None:
        out = job["out"]
        try:
            write_receipt(out, state_root=self.state_root, write_last=False)
        except OSError as exc:
            self._log({"run_id": out["run_id"], "receipt_file": f"failed:{type(exc).__name__}"})
        with self._lock:
            self._last_receipt = out
            self.receipts.append(out)
            del self.receipts[:-int(self.cfg["receipt_history"])]
        self._log({**{k: out.get(k) for k in ("run_id", "lane_id", "mode", "state", "exit_code", "duration_s",
                                             "lock_skipped", "timed_out", "class", "priority", "worker_id",
                                             "verdict", "reason")}, "dead_letter": bool(job["dead"])})

    # -- reaper (F4) --
    def _owner_live_elsewhere(self, worker_id: Any) -> bool:
        """B2: True when the row's worker_id does not name a dead executor of this host. NULL (a v1 executor's
        claim sets no worker_id, heartbeat or pid), unparseable, another host, or another live executor pid on
        this host all count as live elsewhere: such a row is reaped only once overdue by its lane timeout."""
        if not isinstance(worker_id, str) or not worker_id:
            return True
        if worker_id.startswith(f"{self.worker_prefix}:"):
            return False                              # ours, but no live slot or pending completion holds it
        parts = worker_id.rsplit(":", 2)
        if len(parts) != 3 or parts[0] != os.uname().nodename or not parts[1].isdigit():
            return True
        return bool(self.pid_alive(int(parts[1])))

    def reap(self, now: float) -> list[dict[str, Any]]:
        """RUNNING rows not owned here (live slot or pending completion) finish RUN_TIMEOUT / executor_lost when
        started_at + timeout_s + grace has passed, or — only for rows whose owning executor is known dead (this
        executor's id, or a dead executor pid of this host) — when the heartbeat is stale and the child pid dead."""
        with self._lock:
            own = {s["run_id"] for s in self._slots if s is not None} | set(self._pending)
        reaped: list[dict[str, Any]] = []
        for r in self.store.list_running():
            if str(r["run_id"]) in own:
                continue
            entry = self.allowlist.get(str(r["lane_id"])) or {}
            timeout_s = float(entry.get("timeout_s") or self.cfg["unknown_lane_timeout_s"])
            started = _ts(r.get("started_at"))
            hb = _ts(r.get("heartbeat_at")) or started
            stale = hb is None or now - hb > self.stale_heartbeat_s
            overdue = started is not None and started + timeout_s + self.lost_grace_s < now
            lost = stale and not self._owner_live_elsewhere(r.get("worker_id")) and not self.pid_alive(r.get("pid"))
            if not (lost or overdue):
                continue
            receipt = {
                "schema": RECEIPT_SCHEMA, "run_id": r["run_id"], "lane_id": r["lane_id"], "mode": r["mode"],
                "exit_code": None, "duration_s": None if started is None else round(max(0.0, now - started), 3),
                "lock_skipped": False, "timed_out": False, "output_signal": entry.get("output_signal"),
                "output_signal_mtime_before": None, "output_signal_mtime_after": None,
                "started_at": r.get("started_at"), "finished_at": _iso(now), "code_sha": _code_sha(self.code_root),
                "state": "RUN_TIMEOUT", "reason": LOST_REASON, "argv": None, "stdout_tail": None, "stderr_tail": None,
                "authority": "READ_ONLY_ADVISORY",
                "lost": {"pid": r.get("pid"), "heartbeat_at": r.get("heartbeat_at"), "overdue": overdue},
            }
            prio = r.get("priority")
            reaped.append(self.complete(r, receipt, klass=self.class_of(r),
                                        priority=int(prio) if prio is not None else DEFAULT_RUN_PRIORITY,
                                        worker_id=r.get("worker_id")))
        self.reaped_total += len(reaped)
        return reaped

    # -- status --
    def status(self, now: float) -> dict[str, Any]:
        queued = self.store.list(state="REQUESTED", limit=int(self.cfg["status_queue_limit"]))
        depth: dict[str, int] = {}
        oldest: float | None = None
        for r in queued:
            k = self.class_of(r)
            depth[k] = depth.get(k, 0) + 1
            t = _ts(r.get("requested_at"))
            if t is not None and (oldest is None or t < oldest):
                oldest = t
        dead = [d for d in self.store.list_dead_letters()
                if (_ts(d.get("dead_at")) or 0) >= now - self.cfg["dlq_window_s"]]
        dlq_24h = len([d for d in self.store.list_dead_letters(include_released=True)
                       if (_ts(d.get("dead_at")) or 0) >= now - self.cfg["dlq_window_s"]])
        breakers = self.store.list_breakers()
        open_items = {f"dlq:{d['lane_id']}" for d in dead} | {f"breaker:{b['lane_id']}" for b in breakers}
        with self._lock:
            for item in list(self._findings):
                if item not in open_items:
                    del self._findings[item]       # released / closed: the finding disappears, the fan-in closes it
            for d in dead:                          # seed after a restart: the ledger is the record of truth
                self._findings.setdefault(f"dlq:{d['lane_id']}", {
                    "source": "dlq", "item": f"dlq:{d['lane_id']}", "severity": "P2",
                    "detail": f"{d['slot_key']} {d['last_state']} {d['last_reason'] or ''} attempts {d['attempts']}"[:160],
                    "detected_at": d.get("dead_at")})
            for b in breakers:
                self._findings.setdefault(f"breaker:{b['lane_id']}", {
                    "source": "dlq", "item": f"breaker:{b['lane_id']}", "severity": "P2",
                    "detail": f"{b.get('consecutive')} consecutive dead slots; lane paused", "detected_at": b.get("opened_at")})
            findings = [dict(self._findings[k]) for k in sorted(self._findings)]
            busy = [dict(s) for s in self._slots if s is not None]
            pending = sorted(self._pending)
            last = self._last_receipt
        return {
            "schema": STATUS_SCHEMA,
            "as_of": _iso(now),
            "pid": os.getpid(),
            "code_sha": _code_sha(self.code_root),
            "workers": self.workers,
            "workers_busy": len(busy),
            "capacity": self.capacity,
            "pending_completions": pending,
            "busy": busy,
            "class_caps": dict(self.caps),
            "reserved_priority_max": self.reserved_priority_max,
            "queue_depth": dict(sorted(depth.items())),
            "queue_total": len(queued),
            "oldest_requested_age_s": None if oldest is None else round(max(0.0, now - oldest), 3),
            "reaped_total": self.reaped_total,
            "dlq_24h": dlq_24h,
            "breakers_open": sorted(b["lane_id"] for b in breakers),
            "findings": findings,
            "last_receipt": None if last is None else {k: last.get(k) for k in (
                "run_id", "lane_id", "mode", "state", "exit_code", "finished_at", "verdict", "worker_id")},
            "retry_policies_sha256": getattr(self.policies, "sha256", None),
            "authority": "READ_ONLY_ADVISORY",
        }

    def write_status(self, now: float) -> Path:
        last = self.state_root / LAST_REL
        last.parent.mkdir(parents=True, exist_ok=True)
        tmp = last.with_name(f"{last.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(self.status(now), indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, last)
        return last

    # -- loops --
    def wait(self, timeout: float) -> None:
        self._wake.wait(timeout)
        self._wake.clear()

    def drain_until_idle(self, *, poll_s: float = 0.05, deadline_s: float | None = None) -> None:
        """--once: dispatch until no worker is busy and nothing more can be claimed."""
        end = None if deadline_s is None else time.monotonic() + deadline_s
        while True:
            started = self.step()
            if not started and not self.busy():
                return
            if end is not None and time.monotonic() > end:
                return
            self.wait(poll_s)

    def serve(self, *, poll_s: float | None = None) -> None:
        """Daemon loop. A ledger / I/O / runtime error in one tick (F19: ``database is locked`` past the busy
        timeout; a LedgerError; an OSError writing status; a RuntimeError such as a thread that cannot start) is
        logged and retried next tick: exiting would let systemd kill the cgroup and every running lane with it."""
        poll = float(self.cfg["poll_s"] if poll_s is None else poll_s)
        while True:
            try:
                self.step()
            except (sqlite3.OperationalError, LedgerError, OSError, RuntimeError) as exc:
                self._log({"executor": "step_error", "error": f"{type(exc).__name__}:{str(exc)[:120]}"})
            self.wait(poll)


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
    ap.add_argument(
        "--workers",
        type=int,
        default=None,
        help=f"worker threads (default ${WORKERS_ENV} or {DEFAULT_WORKERS}, max {MAX_WORKERS}); 1 = v1 serial path; "
        ">= 2 opts in to executor v2",
    )
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
    workers = resolve_workers(args.workers, env)
    policies = None
    exec_cfg: dict[str, Any] = {}
    if workers > 1:  # v2 only: the v1 path never reads config/n8n_executor.json
        exec_cfg = load_executor_config(code_root / EXECUTOR_CONFIG_REL)
        workers = resolve_workers(workers, {}, max_workers=int(exec_cfg["max_workers"]))
    if workers > 1:
        try:
            policies = load_policies(code_root / RETRY_POLICIES_REL)
        except RetryPolicyError as exc:  # no caps/verdicts without policies: fall back to the v1 serial path
            print(json.dumps({"executor": "v2_unavailable", "reason": f"retry_policies:{exc}"[:300]}), flush=True)
            workers = 1
    registry_rows = None
    if workers > 1:
        try:
            from scripts.lib.lane_registry import load_registry

            registry_rows = load_registry(code_root / "config" / "lane_registry.json").get("lanes") or []
        except (OSError, ValueError, ImportError):
            registry_rows = None
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
                "workers": workers,
            }
        ),
        flush=True,
    )
    if workers > 1:
        ex = ExecutorV2(store, allowlist, env=env, state_root=state_root, code_root=code_root, workers=workers,
                        policies=policies, registry_rows=registry_rows, config=exec_cfg)
        try:
            if args.once:
                ex.drain_until_idle()
                return 0
            ex.serve(poll_s=max(0.5, min(float(args.interval), float(exec_cfg["poll_s"]))))
        except KeyboardInterrupt:
            return 0
        finally:
            ledger.close()
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
