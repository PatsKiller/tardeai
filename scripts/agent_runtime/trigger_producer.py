#!/usr/bin/env python3
"""Deterministic trigger producer — polls read-only sources and enqueues real evidence.

Fail-closed: empty or blocked sources enqueue zero jobs. Never emits fixtures or
lab-seed fallbacks.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from agent_runtime.agents.definitions import FLEET  # noqa: E402
from agent_runtime.trigger_intake import (  # noqa: E402
    EnqueueOutcome,
    InMemoryTriggerIntakeStore,
    PostgresTriggerIntakeStore,
    TriggerIntakeStore,
)
from agent_runtime.trigger_sources import ADAPTERS, ADAPTER_CURSOR_KEYS, SWEEP_AGENTS, run_adapter  # noqa: E402

DISPATCH_DSN_ENV = "AGENT_RUNTIME_DISPATCH_DSN"
PRODUCER_SOURCES_ENV = "AGENT_RUNTIME_PRODUCER_SOURCES"
DEFAULT_SOURCES = ",".join(list(ADAPTERS.keys()) + [f"sweep:{agent}" for agent in SWEEP_AGENTS])


def _build_store() -> TriggerIntakeStore:
    dsn = os.environ.get(DISPATCH_DSN_ENV, "").strip()
    if not dsn:
        raise RuntimeError(f"{DISPATCH_DSN_ENV} is required for trigger producer")
    import importlib

    psycopg2 = importlib.import_module("psycopg2")

    def factory() -> Any:
        conn = psycopg2.connect(dsn)
        conn.autocommit = False
        return conn

    return PostgresTriggerIntakeStore(factory)


def _configured_sources(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def produce_once(store: TriggerIntakeStore, *, sources: list[str] | None = None) -> dict[str, Any]:
    selected = sources or _configured_sources(os.environ.get(PRODUCER_SOURCES_ENV, DEFAULT_SOURCES))
    enqueued = duplicates = 0
    blocked: list[str] = []
    per_agent_depth: dict[str, int] = {}
    details: list[dict[str, Any]] = []

    for source_id in selected:
        cursor_key = ADAPTER_CURSOR_KEYS.get(source_id, "high_water")
        cursor_value = store.get_cursor(source_id, cursor_key)
        result = run_adapter(source_id, cursor_value)
        if result.probe.state.value != "READY" and source_id in ADAPTERS:
            blocked.append(source_id)
        accepted = 0
        for candidate in result.candidates:
            agent = FLEET.get(candidate.agent_id)
            if agent is None:
                continue
            stats = store.queue_stats(candidate.agent_id)
            queued = int(stats.get("queued") or 0)
            if queued >= agent.max_queue_depth:
                continue
            outcome = store.enqueue(candidate)
            if outcome == EnqueueOutcome.ENQUEUED:
                enqueued += 1
                accepted += 1
                per_agent_depth[candidate.agent_id] = queued + 1
            else:
                duplicates += 1
        for sid, cursor_key, cursor_value_new in result.cursor_updates:
            store.set_cursor(sid, cursor_key, cursor_value_new)
        details.append(
            {
                "source_id": source_id,
                "probe": result.probe.state.value,
                "candidates": len(result.candidates),
                "accepted": accepted,
            }
        )

    expired = store.return_expired_leases()
    return {
        "contract": "agent-runtime-trigger-producer-v1",
        "enqueued": enqueued,
        "duplicates": duplicates,
        "blocked_sources": blocked,
        "expired_leases_returned": expired,
        "per_agent_depth": per_agent_depth,
        "sources": details,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Governed SHADOW trigger producer")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    parser.add_argument("--sources", default="", help="Comma-separated source ids")
    parser.add_argument("--dry-run", action="store_true", help="Use in-memory store (tests only)")
    args = parser.parse_args(argv)

    if args.dry_run:
        store: TriggerIntakeStore = InMemoryTriggerIntakeStore()
    else:
        try:
            store = _build_store()
        except Exception as exc:  # fail-soft: no DSN / driver → zero jobs, exit 0
            payload = {
                "contract": "agent-runtime-trigger-producer-v1",
                "enqueued": 0,
                "duplicates": 0,
                "blocked_sources": ["NOT_CONFIGURED"],
                "expired_leases_returned": 0,
                "per_agent_depth": {},
                "sources": [],
                "fail_soft": True,
                "detail": f"{type(exc).__name__}: store unavailable",
            }
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(f"producer fail-soft: {payload['detail']}")
            return 0

    sources = _configured_sources(args.sources) if args.sources else None
    payload = produce_once(store, sources=sources)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"producer enqueued={payload['enqueued']} duplicates={payload['duplicates']} "
            f"blocked={len(payload['blocked_sources'])} expired={payload['expired_leases_returned']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
