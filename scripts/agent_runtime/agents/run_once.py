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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded, single-agent SHADOW queue runner (prepare-only).")
    parser.add_argument("--agent", required=True, help="agent id (e.g. sentinel)")
    parser.add_argument("--once", action="store_true", help="process at most one bounded batch and exit")
    parser.add_argument("--max-batch", type=int, default=8, help="maximum jobs admitted this invocation")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(BANNER)
    if args.agent not in FLEET:
        print(f"unknown agent: {args.agent}", file=sys.stderr)
        return EX_CONFIG
    spec = FLEET[args.agent]
    print(f"agent={spec.agent_id} state={spec.definition.deployment_state.value} enabled={spec.definition.enabled}")

    if os.environ.get("AGENT_RUNTIME_OPERATOR_AUTH") != "1":
        print(
            "refusing to run: AGENT_RUNTIME_OPERATOR_AUTH=1 is required (operator authorization).",
            file=sys.stderr,
        )
        return EX_NOPERM
    if not spec.is_operable_now:
        print(f"refusing to run: {spec.agent_id} is disabled / not SHADOW-operable.", file=sys.stderr)
        return EX_NOPERM

    queue_backend = os.environ.get("AGENT_RUNTIME_QUEUE_MODULE")
    if not queue_backend:
        print(
            "refusing to run: no AGENT_RUNTIME_QUEUE_MODULE configured. This runner ships "
            "prepare-only; wire a governed queue + runtime backend before enabling any timer.",
            file=sys.stderr,
        )
        return EX_CONFIG

    # A queue backend was named but is intentionally NOT imported/dispatched in this
    # change. Enabling real dispatch is a separate, operator-authorized step.
    print(
        f"queue backend '{queue_backend}' is named but dispatch is not enabled in this build; "
        "no work performed.",
        file=sys.stderr,
    )
    return EX_CONFIG


if __name__ == "__main__":  # pragma: no cover - CLI shim
    raise SystemExit(main())
