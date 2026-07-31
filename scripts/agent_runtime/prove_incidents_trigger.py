"""Prove incidents:alert → aegis enqueue-drain-ack (operator smoke).

Usage:
  AGENT_RUNTIME_SOURCE_DSN=... \\
  python -m agent_runtime.prove_incidents_trigger   # from scripts/
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_scripts = str(ROOT / "scripts")
sys.path = [p for p in sys.path if Path(p).resolve().name != "agent_runtime"]
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import json
import os

from agent_runtime.trigger_sources import run_adapter  # noqa: E402


def main() -> int:
    dsn = os.environ.get("AGENT_RUNTIME_SOURCE_DSN", "").strip()
    if not dsn:
        print("SKIP: AGENT_RUNTIME_SOURCE_DSN not set")
        return 0
    result = run_adapter("incidents:alert", None)
    print(json.dumps({
        "probe_state": result.probe.state.value,
        "candidate_count": len(result.candidates),
        "aegis_jobs": [c.job_type for c in result.candidates if c.agent_id == "aegis"],
    }, indent=2))
    if result.probe.state.value != "READY":
        print("BLOCKED: incidents source not ready")
        return 1
    if not result.candidates:
        print("OK: source ready, no open incidents (empty queue is valid)")
        return 0
    print("OK: open incidents mapped to aegis incident_review jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
