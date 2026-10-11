#!/usr/bin/env python3
"""broker_env_audit — LOG which process/module reads each broker env NAME (step 1 of 3, operator 2026-10-11).

Operator ruling 2026-10-11 ~10:55 ET: for one week, record which process and which module reads each broker
env name, block nothing, change no behaviour. The result is the exact list of jobs that truly need broker names,
so a deny-by-default loader (step 3) can follow. Plan: docs/implementation/n8n-maturity/BROKER_ENV_AUDIT.md.

Off unless ``TRADEAI_BROKER_ENV_AUDIT=1``. ``env_bootstrap`` calls :func:`maybe_install` at import and after every
``load_env``; with the flag unset that is one dict lookup and nothing else.

When on, ``os.environ`` keeps its identity (``from os import environ`` aliases, ``putenv`` and child processes are
unaffected) and only its class is swapped for :class:`_AuditEnviron`, a subclass of ``os._Environ`` that, on a read
of a broker name (``env_bootstrap.is_broker_name``) through ``[]`` / ``get`` / ``in`` / ``os.getenv``, appends ONE
JSON line to ``$TRADEAI_STATE_ROOT/data/runtime/broker_env_audit/<UTC date>.jsonl``:

    ts, host, pid, ppid, name, access (getitem|get|contains|bulk), script (argv[0]), arg1 (argv[1], flag-shaped
    only), lane (env TRADEAI_LANE / TRADEAI_LANE_ID / N8N_LANE_ID when set), unit (systemd unit from
    /proc/self/cgroup), caller (module:function:line, the first frame outside the stdlib), caller_file, via (the
    next frame out), mode="audit".

Never the VALUE, never its length, never its presence (AGENTS §0): the record path does not touch the value.
``bulk`` marks a whole-mapping copy (``dict(os.environ)``, ``{**os.environ}``, ``os.environ.copy()``, iterating
``items()``/``values()``): the process passes broker names on without naming one. Reads made by env_bootstrap
itself (the loader's own ``k not in os.environ``) are not recorded.

Throttle: one line per (pid, name, caller) per process, at most ``MAX_LINES_PER_PROCESS``. Never raises: every
failure inside the recorder is swallowed and the env read proceeds exactly as without the audit.
"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
import sysconfig
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

FLAG_ENV = "TRADEAI_BROKER_ENV_AUDIT"
SCHEMA = "BrokerEnvAudit@v1"
AUDIT_SUBDIR = ("data", "runtime", "broker_env_audit")
DEFAULT_STATE_ROOT = Path.home() / "trade-ai-releases" / "persistent-state"
# The flag itself matches the *_BROKER_* infix; it is plumbing, not a credential.
_NOT_AUDITED = frozenset({FLAG_ENV})
LANE_ENV_NAMES = ("TRADEAI_LANE", "TRADEAI_LANE_ID", "N8N_LANE_ID")
MAX_LINES_PER_PROCESS = 1000
# Frames in these files are infrastructure, not the reader: the loader's own reads are not a "need".
_SELF_FILES = ("broker_env_audit.py", "env_bootstrap.py")
_BULK_OPS = frozenset({"CALL", "CALL_KW", "CALL_FUNCTION_EX", "DICT_UPDATE", "DICT_MERGE"})

# Broker execution processes are EXCLUDED by design (AGENTS §0 rule 2: out of scope; they obviously need broker
# names): install() is a no-op in a process whose script is under one of these dirs, or whose script (path after the
# last scripts/, else basename) or systemd unit matches BROKER_TOKEN_PATTERN. ONE list, shared with the systemd
# packet (packets/broker-env-audit/systemd/build.sh reads it via `python3 broker_env_audit.py --broker-tokens`) and
# the report's source scan.
BROKER_SCRIPT_DIRS = ("scripts/active_trader/", "scripts/brokers/", "scripts/moomoo/")
BROKER_TOKEN_PATTERN = (r"active_trader|active-trader|/brokers/|moomoo|opend|alpaca|schwab|snaptrade|ibkr|broker|order"
                        r"|stop_manager|paper_trade|trade_closer")
_BROKER_TOKEN_RE = re.compile(BROKER_TOKEN_PATTERN, re.IGNORECASE)

_ORIG_CLASS = os._Environ
_ORIG_GETITEM = os._Environ.__getitem__

_classifier: Callable[[str], bool] | None = None
_class_cache: dict[str, bool] = {}
_seen: set[tuple[int, str, str]] = set()
_fast_seen: set[tuple] = set()
_lines_by_pid: dict[int, int] = {}
_guard = threading.local()
_proc_cache: dict[str, object] = {}
_stats = {"swallowed": 0}


def _stdlib_prefixes() -> tuple[str, ...]:
    out = set()
    for key in ("stdlib", "platstdlib"):
        try:
            p = sysconfig.get_paths().get(key)
        except Exception:  # noqa: BLE001
            p = None
        if p:
            out.add(os.path.realpath(p) + os.sep)
            out.add(p.rstrip(os.sep) + os.sep)
    return tuple(out)


_STDLIB = _stdlib_prefixes()


def enabled() -> bool:
    """True when the audit flag is exactly "1". Reads the underlying mapping, so it never records itself."""
    return _raw_get(FLAG_ENV) == "1"


def _raw_get(name: str) -> str | None:
    """os.environ[name] without going through the audit class (no recording, no recursion)."""
    try:
        v = os.environ._data.get(os.environ.encodekey(name))
        return None if v is None else os.environ.decodevalue(v)
    except Exception:  # noqa: BLE001
        return None


def _is_broker(key) -> bool:
    try:
        b = _class_cache.get(key)
    except TypeError:  # unhashable key: the stock read raises its own TypeError
        return False
    if b is None:
        try:
            b = bool(isinstance(key, str) and key not in _NOT_AUDITED and _classifier is not None and _classifier(key))
        except Exception:  # noqa: BLE001
            b = False
        if len(_class_cache) < 50000:
            _class_cache[key] = b
    return b


_infra_cache: dict[str, bool] = {}


def _is_infra(filename: str) -> bool:
    b = _infra_cache.get(filename)
    if b is None:
        b = _infra_cache[filename] = _is_infra_uncached(filename)
    return b


def _is_infra_uncached(filename: str) -> bool:
    if not filename or filename.startswith("<frozen"):
        return True
    if "site-packages" in filename or "dist-packages" in filename:
        return False
    return filename.startswith(_STDLIB)


def _frame_label(f) -> tuple[str, str]:
    code = f.f_code
    mod = f.f_globals.get("__name__") or "?"
    fname = code.co_filename or "?"
    if mod == "__main__":
        mod = os.path.basename(fname)
    qual = getattr(code, "co_qualname", code.co_name)
    return f"{mod}:{qual}:{f.f_lineno}", fname


def _first_outside(frame):
    f = frame
    while f is not None and _is_infra(f.f_code.co_filename):
        f = f.f_back
    return f


def _callers(f) -> tuple[str | None, str | None, str | None]:
    """(caller, caller_file, via) for ``f``, the first frame outside the stdlib, and the next one out.
    caller None = a read made by env_bootstrap / this module itself (the loader), not a consumer."""
    if f is None:
        return "?", None, None
    if os.path.basename(f.f_code.co_filename) in _SELF_FILES:
        return None, None, None
    caller, cfile = _frame_label(f)
    g = _first_outside(f.f_back)
    via = _frame_label(g)[0] if g is not None else None
    return caller, cfile, via


def _bulk_from(direct) -> bool:
    """True when ``direct`` (the frame that called __getitem__) copies the whole mapping."""
    code = direct.f_code
    if code.co_filename.startswith("<frozen") and code.co_name in ("__iter__", "copy", "__eq__"):
        return code.co_name != "__iter__" or "ItemsView" in getattr(code, "co_qualname", "") \
            or "ValuesView" in getattr(code, "co_qualname", "")
    try:
        import dis
        return dis.opname[code.co_code[direct.f_lasti]] in _BULK_OPS
    except Exception:  # noqa: BLE001
        return False


def _arg1() -> str | None:
    if len(sys.argv) < 2:
        return None
    a = str(sys.argv[1])
    if (a.startswith("-") and "=" not in a and len(a) <= 64) or a.endswith((".py", ".sh")):
        return a
    return "<arg>"  # a positional could be anything; never logged


def _unit() -> str | None:
    try:
        text = Path("/proc/self/cgroup").read_text()
    except OSError:
        return None
    for line in text.splitlines():
        path = line.rpartition(":")[2]
        for part in reversed(path.split("/")):
            if part.endswith((".service", ".scope", ".timer")):
                return part
    return None


def _proc_info() -> dict:
    pid = os.getpid()
    if _proc_cache.get("pid") != pid:
        _proc_cache.clear()
        root = _raw_get("TRADEAI_STATE_ROOT") or str(DEFAULT_STATE_ROOT)
        lane = next((v for v in (_raw_get(n) for n in LANE_ENV_NAMES) if v), None)
        try:
            host = socket.gethostname()
        except Exception:  # noqa: BLE001
            host = None
        _proc_cache.update({"pid": pid, "root": root, "lane": lane, "unit": _unit(), "host": host})
    return _proc_cache


def audit_dir(root: str | os.PathLike | None = None) -> Path:
    base = Path(root) if root else Path(_raw_get("TRADEAI_STATE_ROOT") or DEFAULT_STATE_ROOT)
    return base.joinpath(*AUDIT_SUBDIR)


def _record(name: str, access: str, depth: int) -> None:
    """Append one line for a broker-name read. Swallows every failure."""
    if getattr(_guard, "on", False):
        return
    _guard.on = True
    try:
        pid = os.getpid()
        n = _lines_by_pid.get(pid, 0)
        if n >= MAX_LINES_PER_PROCESS:
            return
        frame = sys._getframe(depth)
        outer = _first_outside(frame)
        # Fast throttle on (pid, name, code, line) before any formatting: a hot loop re-reading a broker name
        # costs one frame walk and a set lookup (benchmark in tests/test_broker_env_audit_20261011.py).
        fast = (pid, name, outer.f_code if outer is not None else None, outer.f_lineno if outer is not None else -1)
        if fast in _fast_seen:
            return
        _fast_seen.add(fast)
        if access == "getitem" and _bulk_from(frame):
            access = "bulk"
        caller, cfile, via = _callers(outer)
        if caller is None:
            return  # env_bootstrap's own read (the loader), not a consumer
        key = (pid, name, caller)
        if key in _seen:
            return
        _seen.add(key)
        _lines_by_pid[pid] = n + 1
        info = _proc_info()
        now = datetime.now(timezone.utc)
        rec = {
            "schema": SCHEMA, "ts": now.isoformat(timespec="seconds"), "host": info["host"], "pid": pid,
            "ppid": os.getppid(), "name": name, "access": access,
            "script": str(sys.argv[0]) if sys.argv else None, "arg1": _arg1(),
            "lane": info["lane"], "unit": info["unit"], "caller": caller, "caller_file": cfile, "via": via,
            "mode": "audit",
        }
        d = audit_dir(info["root"])
        d.mkdir(parents=True, exist_ok=True)
        line = (json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        fd = os.open(str(d / f"{now.date().isoformat()}.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
        try:
            os.write(fd, line)  # one write < PIPE_BUF: concurrent appenders do not interleave
        finally:
            os.close(fd)
    except Exception:  # noqa: BLE001 — the audit must never change the caller's behaviour
        _stats["swallowed"] += 1
    finally:
        _guard.on = False


class _AuditEnviron(os._Environ):
    """os._Environ that records broker-name reads. Same data, same putenv; installed by class swap."""

    _broker_env_audit = True

    def __getitem__(self, key):
        if _is_broker(key):
            _record(key, "getitem", 2)
        return _ORIG_GETITEM(self, key)

    def get(self, key, default=None):
        if _is_broker(key):
            _record(key, "get", 2)
        try:
            return _ORIG_GETITEM(self, key)
        except KeyError:
            return default

    def __contains__(self, key):
        if _is_broker(key):
            _record(key, "contains", 2)
        try:
            _ORIG_GETITEM(self, key)
        except KeyError:
            return False
        return True


def broker_process_reason(argv0: str | None = None, unit: str | None = None) -> str | None:
    """Why this process is a broker execution process (excluded from the audit), or None. Pure over its inputs;
    defaults read sys.argv[0] (resolved) and the systemd unit from /proc/self/cgroup."""
    if argv0 is None:
        argv0 = sys.argv[0] if sys.argv else ""
    path = str(argv0 or "")
    if path and not path.startswith("-"):
        try:
            path = os.path.realpath(path)
        except Exception:  # noqa: BLE001
            pass
    path = path.replace(os.sep, "/")
    for d in BROKER_SCRIPT_DIRS:
        if "/" + d in path or path.startswith(d):
            return f"dir:{d}"
    rel = path.rsplit("/scripts/", 1)[1] if "/scripts/" in path else path.rsplit("/", 1)[-1]
    m = _BROKER_TOKEN_RE.search(rel)
    if m:
        return f"script_token:{m.group(0).lower()}"
    if unit is None:
        unit = _unit()
    m = _BROKER_TOKEN_RE.search(str(unit or ""))
    if m:
        return f"unit_token:{m.group(0).lower()}"
    return None


def installed() -> bool:
    return type(os.environ) is _AuditEnviron or bool(getattr(type(os.environ), "_broker_env_audit", False))


def install(classifier: Callable[[str], bool]) -> bool:
    """Swap os.environ's class (idempotent across duplicate module imports). True when the audit is active."""
    global _classifier
    try:
        if _classifier is None:
            _classifier = classifier
        if installed():
            return True
        if broker_process_reason() is not None:
            return False  # broker execution process: excluded by design (AGENTS §0 rule 2)
        if type(os.environ) is not _ORIG_CLASS:
            return False  # someone else replaced os.environ; do not stack on it
        os.environ.__class__ = _AuditEnviron
        return True
    except Exception:  # noqa: BLE001
        return False


def uninstall() -> None:
    """Restore the stock class (tests; a process that wants the audit off)."""
    try:
        if type(os.environ) is _AuditEnviron:
            os.environ.__class__ = _ORIG_CLASS
    except Exception:  # noqa: BLE001
        pass


def maybe_install(classifier: Callable[[str], bool]) -> bool:
    """Install when ``TRADEAI_BROKER_ENV_AUDIT=1``; otherwise do nothing. Never raises."""
    try:
        if installed():
            return True
        if not enabled():
            return False
        return install(classifier)
    except Exception:  # noqa: BLE001
        return False


def _reset_for_tests() -> None:
    _seen.clear()
    _fast_seen.clear()
    _lines_by_pid.clear()
    _proc_cache.clear()
    _class_cache.clear()
    _stats["swallowed"] = 0


if __name__ == "__main__":  # `--broker-tokens`: the shared exclusion list, for the systemd packet's build.sh
    if sys.argv[1:] == ["--broker-tokens"]:
        print(BROKER_TOKEN_PATTERN)
        sys.exit(0)
    print("usage: broker_env_audit.py --broker-tokens", file=sys.stderr)
    sys.exit(2)
