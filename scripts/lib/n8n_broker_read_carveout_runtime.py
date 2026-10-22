"""n8n_broker_read_carveout_runtime — the runtime readers of the n8n read-only broker carve-out (AGENTS.md 19.0.0 §27.1).

``scripts/lib/n8n_broker_read_carveout.py`` holds the closed lane set, the static admission and ``CARVEOUT_STATUS``;
``scripts/pipelines/pipeline_manifest.py`` consults it, so it is in the static import closure of every lane that
reaches lane_dispatch / n8n_process_keys. It therefore imports nothing broker-adjacent. The two preconditions that
need broker-adjacent readers live here instead:

  * every broker trading lock is LOCKED — ``scripts/ops/broker_read_sync.py`` ``lock_states()``;
  * the Schwab access mode the operator's switch resolves is ``read_only`` — ``broker_read_sync.resolved_child_mode()``
    WITHOUT the per-process ``read_only`` force the step processes get.

Only the host path that evaluates a carve-out lane immediately before running it imports this module (none exists yet:
§27.4). ``runtime_refusals`` / ``admit`` here are the carve-out's own functions with these readers supplied; the
carve-out refuses when a reader is missing, so forgetting this module fails closed.

Read-only: reads the trading-lock files and the access-mode switch through broker_read_sync. Never imports a step, a
broker transport or a credential; never opens ``.env``; never calls a broker.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Callable, Optional

try:  # scripts/ on sys.path (lanes, tests)
    from lib import n8n_broker_read_carveout as carve
except ImportError:  # repo root on sys.path
    from scripts.lib import n8n_broker_read_carveout as carve  # type: ignore[no-redef]


def _broker_read_sync():
    try:
        from ops import broker_read_sync as brs  # scripts/ on sys.path
    except ImportError:
        import importlib.util

        name = "_n8n_carveout_broker_read_sync"
        if name in sys.modules:
            return sys.modules[name]
        spec = importlib.util.spec_from_file_location(name, carve.ROOT / "scripts" / "ops" / "broker_read_sync.py")
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
    """``carve.runtime_refusals`` with the real readers as defaults. Fail closed."""
    return carve.runtime_refusals(status=status, lock_fn=lock_fn or default_lock_states,
                                  mode_fn=mode_fn or operator_access_mode)


def admit(command: carve.Command, *, status: Optional[str] = None, check_runtime: bool = True,
          audit_fn: Optional[Callable[[Any], dict[str, Any]]] = None,
          lock_fn: Optional[Callable[[], dict[str, dict[str, Any]]]] = None,
          mode_fn: Optional[Callable[[], dict[str, Any]]] = None) -> dict[str, Any]:
    """``carve.admit`` (N8nBrokerReadAdmission@v1) with the real readers as defaults."""
    return carve.admit(command, status=status, check_runtime=check_runtime, audit_fn=audit_fn,
                       lock_fn=lock_fn or default_lock_states, mode_fn=mode_fn or operator_access_mode)
