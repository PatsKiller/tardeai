"""Fail-closed, prepare-only bounded runner entrypoint for one agent queue.

A deterministic, external scheduler (a systemd timer running this with
``--once``) is the ONLY thing permitted to invoke an agent. This module is that
invocation point, and it is deliberately inert until an operator wires a queue
backend and grants explicit authorization:

  * It refuses to run unless ``AGENT_RUNTIME_OPERATOR_AUTH=1`` is present.
  * It refuses to run unless a queue backend module is configured; none ships in
    this change, so the default behavior is to print the prepare-only banner and
    exit non-zero.
  * It NEVER schedules itself, opens a database or socket, spawns a process, or
    reads a secret. (No psycopg2 / subprocess / requests / keyring import.)

There is no code path here that can enable an agent, place an order, promote a
lesson, or change configuration.
"""
from __future__ import annotations

import argparse
import os
import sys

from .definitions import FLEET

BANNER = "AGENT RUNTIME BOUNDED RUNNER — PREPARE-ONLY / DEFAULT-DISABLED"
EX_CONFIG = 78
EX_NOPERM = 77
EX_OK = 0

# Timer inventory historically used watch-pipeline aliases. Map them to fleet ids
# so a scheduled oneshot is no-work rather than CONFIG failure.
AGENT_ALIASES = {
    "tax_agent": "ledger",
    "guardian": "risk_agent",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded, single-agent SHADOW queue runner (prepare-only).")
    parser.add_argument("--agent", required=True, help="agent id (e.g. sentinel)")
    parser.add_argument("--once", action="store_true", help="process at most one bounded batch and exit")
    parser.add_argument("--max-batch", type=int, default=8, help="maximum jobs admitted this invocation")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(BANNER)
    requested = str(args.agent or "").strip()
    resolved = AGENT_ALIASES.get(requested, requested)
    if resolved not in FLEET:
        # Timer fired for a name that is not in the governed fleet. That is
        # no-work, not a crash — systemd must not enter failed.
        print(
            f"no-work: unknown agent {requested!r} (not in fleet). "
            "Timer inventory exceeds FLEET; exit 0.",
            file=sys.stderr,
        )
        return EX_OK
    spec = FLEET[resolved]
    print(
        f"agent={spec.agent_id} requested={requested} "
        f"state={spec.definition.deployment_state.value} enabled={spec.definition.enabled}"
    )

    if os.environ.get("AGENT_RUNTIME_OPERATOR_AUTH") != "1":
        print(
            "refusing to run: AGENT_RUNTIME_OPERATOR_AUTH=1 is required (operator authorization).",
            file=sys.stderr,
        )
        return EX_NOPERM
    if not spec.is_operable_now:
        # DESIGNED / disabled wave-2 agents have timers. Expected no-work.
        print(
            f"no-work: {spec.agent_id} is disabled / not SHADOW-operable "
            f"(state={spec.definition.deployment_state.value}).",
            file=sys.stderr,
        )
        return EX_OK

    queue_backend = os.environ.get("AGENT_RUNTIME_QUEUE_MODULE")
    if not queue_backend:
        print(
            "refusing to run: no AGENT_RUNTIME_QUEUE_MODULE configured. This runner ships "
            "prepare-only; wire a governed queue + runtime backend before enabling any timer.",
            file=sys.stderr,
        )
        return EX_CONFIG

    # Dispatch to the operator-configured governed backend by NAME. This module
    # stays driver-free — the backend (out-of-package) owns the DB driver and the
    # governed MvlRuntime call. The backend is fail-closed: it refuses unless a LAB
    # writer DSN and a real provider module are configured (never fabricates work).
    import importlib

    try:
        backend = importlib.import_module(queue_backend)
    except Exception as exc:  # noqa: BLE001
        print(f"refusing to run: queue backend '{queue_backend}' failed to import: {exc}", file=sys.stderr)
        return EX_CONFIG
    entry = getattr(backend, "run_bounded_batch", None)
    if not callable(entry):
        print(f"refusing to run: queue backend '{queue_backend}' has no run_bounded_batch(agent_id, max_batch)", file=sys.stderr)
        return EX_CONFIG
    try:
        summary = entry(spec.agent_id, args.max_batch)
    except Exception as exc:  # noqa: BLE001 — a backend refusal/error is non-zero, never a crash-loop
        print(f"dispatch refused/failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EX_CONFIG
    print(f"dispatch summary: {summary}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI shim
    raise SystemExit(main())
