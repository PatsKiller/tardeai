"""n8n_broker_read_carveout — the n8n read-only broker carve-out (AGENTS.md 19.0.0 §27.1; PROPOSED).

Operator, 2026-10-22 (verbatim): "N8N can read the broker because right now we're only doing reading of the broker.
We're not doing any trading. So I want to amendment."

AGENTS.md §23.14 keeps broker, order, secret and daemon lanes off the n8n dispatcher. 19.0.0 adds ONE exception: n8n
may schedule and trigger the closed set of read lanes below, executed on the host through the allowlisted executor,
only while every broker trading lock is LOCKED and the Schwab access mode is ``read_only``. This module is the single
place that says which commands that covers and which preconditions must hold. It reuses the 14.0.0 read-only sync
(§24.11) wholesale: the same closed step set (``broker_read_sync_policy.STEPS``), the same exclusions
(``excluded_family`` / ``runtime_denied``), the same static capability audit (``audit()``), and the same lock and
access-mode readers (``scripts/ops/broker_read_sync.py`` ``lock_states()`` / ``resolved_child_mode()``).

Status. ``CARVEOUT_STATUS`` is ``"PROPOSED"`` and only the 19.0.0 ratifying edit (the operator's
``build_ratify19.py``) sets it to ``"ACTIVE"``. While it is not ``ACTIVE`` every admission refuses with
``carveout_not_active`` BEFORE any audit runs, so ``pipeline_manifest.forbidden_command_tokens`` behaves exactly as
it did before this module existed.

What it never admits, whatever the status: an order, a stop write, cancel, replace, order preflight, 2FA,
``place_order``, a live or paper flag, paper execution, a sender, re-auth or token refresh, any
``broker_read_sync_policy.EXCLUDED`` family, a wrapper, an extra argument, a pipe or a second command
(``NEVER_TOKENS`` and the exact-argv match). Changing a read lane into one that writes is an operator-only decision
(AGENTS.md §17); adding a lane is a reviewed PR to ``READ_LANES``.

Pure of brokers: reads repository source (the audit) and, for ``runtime_refusals``, the trading-lock files and the
access-mode switch. Never imports a step, a broker module or a credential; never opens ``.env``.
"""

from __future__ import annotations

import functools
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence, Union

# One module object whichever way it is imported (``lib.…`` from scripts/ on sys.path, ``scripts.lib.…`` from the
# repo root), so pipeline_manifest and a test seam see the same CARVEOUT_STATUS (the scripts/lib/trading_lock.py idiom).
for _alias in ("lib.n8n_broker_read_carveout", "scripts.lib.n8n_broker_read_carveout"):
    sys.modules.setdefault(_alias, sys.modules[__name__])

try:  # scripts/ on sys.path (lanes, tests)
    from lib import broker_read_sync_policy as policy
except ImportError:  # repo root on sys.path
    from scripts.lib import broker_read_sync_policy as policy  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[2]

#: Set to "ACTIVE" only by the AGENTS.md 19.0.0 ratifying edit. Anything else refuses every admission.
CARVEOUT_STATUS = "PROPOSED"
POLICY_VERSION = "19.0.0"
POLICY_TOKEN = "APPROVE_AGENTS_POLICY_19_0_0"
SCHEMA_ADMISSION = "N8nBrokerReadAdmission@v1"
SCHWAB_MODE = policy.SCHWAB_MODE  # "read_only"
LOCK_BROKERS = policy.LOCK_BROKERS  # schwab, alpaca, moomoo, snaptrade

#: Market-data reads admitted on the same audit as the §24.11 steps (measured clean 2026-10-22 on 2d8fc9574).
MARKET_DATA_READS: tuple[policy.Step, ...] = (
    policy.Step("options_chain_snapshot", "Options chain snapshot (market data)", "scripts/options_chain_snapshot.py",
                ("--dry-run",), (), "schwab"),
    policy.Step("schwab_instrument_sweep", "Schwab instrument sweep (market data)",
                "scripts/sweep_schwab_instruments.py", (), ("--apply",), "schwab"),
)

#: THE CLOSED SET. The §24.11 steps exactly as broker_read_sync_policy.STEPS pins them, then the market-data reads.
READ_LANES: tuple[policy.Step, ...] = tuple(policy.STEPS) + MARKET_DATA_READS

#: Refused in any command, even when ACTIVE (defence in depth under the exact-argv match). Lower-case substrings.
NEVER_TOKENS: tuple[str, ...] = (
    "place_order", "order", "cancel", "replace", "preflight", "2fa", "unlock", "--live", "live_flag", "paper",
    "send_telegram", "telegram", "sender", "stop_manager", "stop_sync", "stop_writer", "stop_pilot", "oco",
    "reauth", "exchange_code", "seed_token", "refresh_token", "token", "credential", "secret", ".env",
)

#: Interpreter tokens a command may start with ($PY is the allowlist's executor interpreter placeholder).
_INTERPRETER_RE = re.compile(r"^(?:\$PY|(?:.*/)?python(?:3(?:\.\d+)?)?)$")
_SHELL_META = frozenset(";|&$`<>(){}\\\n\r*?!'\"")

Command = Union[str, Sequence[str]]


def is_active(status: Optional[str] = None) -> bool:
    return (CARVEOUT_STATUS if status is None else status) == "ACTIVE"


def _argv(command: Command) -> Optional[list[str]]:
    """The command as argv, or None when it is not one plain command (shell syntax, unparsable)."""
    if isinstance(command, str):
        try:
            parts = shlex.split(command, posix=True)
        except ValueError:
            return None
    else:
        parts = [str(p) for p in command]
    if not parts:
        return None
    first = parts[0]
    rest = parts[1:]
    if _INTERPRETER_RE.match(first):
        if not rest:
            return None
        parts = rest
    if any(c in _SHELL_META for tok in parts for c in tok):
        return None
    return parts


def _text(command: Command) -> str:
    return command if isinstance(command, str) else " ".join(str(p) for p in command)


def never_hits(command: Command) -> list[str]:
    low = _text(command).lower()
    return [tok for tok in NEVER_TOKENS if tok in low]


def match_lane(command: Command) -> Optional[tuple[policy.Step, str]]:
    """(step, mode) when the command is exactly a READ_LANES script with one of its argv forms, else None."""
    argv = _argv(command)
    if not argv:
        return None
    script, args = argv[0], tuple(argv[1:])
    for step in READ_LANES:
        if script != step.script:
            continue
        for mode in ("dry_run", "apply"):
            want = step.argv(mode)
            if want is not None and args == tuple(want):
                return step, mode
    return None


@functools.lru_cache(maxsize=None)
def _audit_script(root: str, script: str) -> tuple[bool, tuple[str, ...]]:
    steps = tuple(s for s in READ_LANES if s.script == script)[:1]
    result = policy.audit(Path(root), steps)
    kinds = tuple(sorted({f"{f.get('kind')}:{f.get('module')}" for f in result.get("findings", [])}))
    return bool(result.get("ok")), kinds


def default_audit(step: policy.Step, root: Path = ROOT) -> dict[str, Any]:
    ok, kinds = _audit_script(str(root), step.script)
    return {"ok": ok, "findings": list(kinds)}


def static_refusals(command: Command, *, status: Optional[str] = None,
                    audit_fn: Optional[Callable[[policy.Step], dict[str, Any]]] = None) -> list[str]:
    """Every reason the command is not an admissible carve-out lane. Empty = admissible (statically).

    Not ACTIVE refuses first and alone: no audit runs while PROPOSED."""
    if not is_active(status):
        return ["carveout_not_active"]
    refusals = [f"never_list:{tok}" for tok in never_hits(command)]
    if _argv(command) is None:
        refusals.append("not_a_single_command")
    hit = match_lane(command)
    if hit is None:
        refusals.append("not_a_carveout_lane")
        return refusals
    step, _mode = hit
    fam = policy.excluded_family(step.script) or policy.runtime_denied(step.script)
    if fam:
        refusals.append(f"excluded_family:{fam}")
        return refusals
    result = (audit_fn or default_audit)(step)
    if not result.get("ok"):
        found = result.get("findings") or ["unknown"]
        refusals.extend(f"capability_found:{k if isinstance(k, str) else k.get('kind')}" for k in found)
    return refusals


# ------------------------------------------------------------------------------------------- runtime preconditions

def _broker_read_sync():
    try:
        from ops import broker_read_sync as brs  # scripts/ on sys.path
    except ImportError:
        import importlib.util

        name = "_n8n_carveout_broker_read_sync"
        if name in sys.modules:
            return sys.modules[name]
        spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "ops" / "broker_read_sync.py")
        brs = importlib.util.module_from_spec(spec)
        sys.modules[name] = brs
        spec.loader.exec_module(brs)  # type: ignore[union-attr]
    return brs


def default_lock_states() -> dict[str, dict[str, Any]]:
    return _broker_read_sync().lock_states()


def operator_access_mode() -> dict[str, Any]:
    """The Schwab access mode the operator's switch resolves, WITHOUT the per-process read_only force the step
    processes get: the carve-out runs only while the operator's own switch says read_only."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("TRADEAI_SCHWAB_ACCESS_MODE", "TRADEAI_SCHWAB_ACCESS_MODE_PATH")}
    return _broker_read_sync().resolved_child_mode(env)


def runtime_refusals(*, status: Optional[str] = None,
                     lock_fn: Optional[Callable[[], dict[str, dict[str, Any]]]] = None,
                     mode_fn: Optional[Callable[[], dict[str, Any]]] = None) -> list[str]:
    """Preconditions checked immediately before a carve-out lane runs on the host. Fail closed."""
    if not is_active(status):
        return ["carveout_not_active"]
    refusals: list[str] = []
    try:
        locks = (lock_fn or default_lock_states)() or {}
    except Exception as exc:  # noqa: BLE001 — unreadable lock state refuses
        locks = {}
        refusals.append(f"trading_lock_unreadable:{type(exc).__name__}")
    for broker in LOCK_BROKERS:
        st = locks.get(broker)
        if not isinstance(st, dict) or st.get("locked") is not True:
            refusals.append(f"trading_lock_not_locked:{broker}")
    try:
        mode = (mode_fn or operator_access_mode)() or {}
    except Exception as exc:  # noqa: BLE001
        mode = {}
        refusals.append(f"schwab_access_mode_unreadable:{type(exc).__name__}")
    if mode.get("mode") != SCHWAB_MODE:
        refusals.append("schwab_access_mode_not_read_only")
    return refusals


# ------------------------------------------------------------------------------------------- admission

def admit(command: Command, *, status: Optional[str] = None, check_runtime: bool = True,
          audit_fn: Optional[Callable[[policy.Step], dict[str, Any]]] = None,
          lock_fn: Optional[Callable[[], dict[str, dict[str, Any]]]] = None,
          mode_fn: Optional[Callable[[], dict[str, Any]]] = None) -> dict[str, Any]:
    """N8nBrokerReadAdmission@v1: may n8n trigger this command now? ``admitted`` only when every check passes."""
    refusals = static_refusals(command, status=status, audit_fn=audit_fn)
    if check_runtime and refusals != ["carveout_not_active"]:
        refusals += [r for r in runtime_refusals(status=status, lock_fn=lock_fn, mode_fn=mode_fn)
                     if r not in refusals]
    hit = match_lane(command)
    return {
        "schema": SCHEMA_ADMISSION,
        "policy_version": POLICY_VERSION,
        "carveout_status": CARVEOUT_STATUS if status is None else status,
        "lane": hit[0].id if hit else None,
        "mode": hit[1] if hit else None,
        "admitted": not refusals,
        "refusals": refusals,
    }


def exempt_command_tokens(command: Command, *, forbidden: Iterable[str], status: Optional[str] = None,
                          audit_fn: Optional[Callable[[policy.Step], dict[str, Any]]] = None) -> frozenset[str]:
    """The forbidden tokens (pipeline_manifest.FORBIDDEN_COMMAND_TOKENS) this command is exempt from: only the ones
    naming its own admitted read script, and none unless the command passes ``static_refusals``."""
    if static_refusals(command, status=status, audit_fn=audit_fn):
        return frozenset()
    hit = match_lane(command)
    if hit is None:  # unreachable: static_refusals refuses a non-lane
        return frozenset()
    script = hit[0].script
    return frozenset(tok for tok in forbidden if tok in script and not never_hits(tok))
