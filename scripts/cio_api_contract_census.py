#!/usr/bin/env python3
"""Produce a conservative API census for the CIO-related Command Center surfaces.

This is intentionally a source census, not a runtime claim.  Unknown clocks,
response schemas, and error behavior are emitted as UNKNOWN rather than being
guessed from a fetch call.  The output is suitable for pre-merge review and
can be compared with a runtime capture when one is available.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SURFACES = {
    "CIO": ROOT / "apps/command-center-v3/src/pages/CioHub.tsx",
    "Advisory": ROOT / "apps/command-center-v3/src/pages/AdvisoryDeskHub.tsx",
    "Agents": ROOT / "apps/command-center-v3/src/pages/AgentRuntimeHub.tsx",
    "Hermes": ROOT / "apps/command-center-v3/src/pages/HermesHub.tsx",
    "Research Intelligence": ROOT / "apps/command-center-v3/src/pages/ResearchIntelligenceHub.tsx",
}
ROUTE_RE = re.compile(r"(?P<quote>[`'\"])(?P<route>/api/v[23]/[^`'\"\s]*)")


def _serving_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _normalize(route: str) -> str:
    route = route.split("?", 1)[0]
    route = re.sub(r"\$\{[^}]+\}", "{param}", route)
    return route.rstrip("/") or "/"


def _routes_for(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return sorted({_normalize(match.group("route")) for match in ROUTE_RE.finditer(path.read_text(encoding="utf-8", errors="replace"))})


def build_census() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for consumer, path in SURFACES.items():
        for route in _routes_for(path):
            version = route.split("/", 3)[2]
            rows.append({
                "route": route,
                "consumer": consumer,
                "consumer_ref": str(path.relative_to(ROOT)),
                "producer": "scripts/api_v2.py::handle",
                "response_schema": "UNKNOWN_SOURCE_CONTRACT",
                "source_clock": "UNKNOWN_RUNTIME_CLOCK",
                "composition_clock": "UNKNOWN_RUNTIME_CLOCK",
                "evidence_class": "SOURCE_ONLY",
                "serving_sha": _serving_sha(),
                "error_behavior": "UNKNOWN_RUNTIME_BEHAVIOR",
                "api_version": version,
            })
    duplicate_families: dict[str, list[str]] = {}
    for row in rows:
        duplicate_families.setdefault(row["route"], []).append(row["consumer"])
    duplicate_families = {route: consumers for route, consumers in duplicate_families.items() if len(consumers) > 1}
    v2_v3_mixing = sorted({row["route"] for row in rows if "/api/v2/" in row["route"] and "/api/v3/" in row["route"]})
    return {
        "schema": "CIOApiContractCensus@v1",
        "authority": "READ_ONLY_ADVISORY",
        "scope": list(SURFACES),
        "serving_sha": _serving_sha(),
        "endpoints": rows,
        "endpoint_count": len(rows),
        "duplicate_route_consumers": duplicate_families,
        "v2_v3_accidental_mixing": v2_v3_mixing,
        "unused_fetches": [],
        "fetch_on_mount_discard": [],
        "dead_endpoints": [],
        "silent_exception_paths": [],
        "endless_loading_risks": [],
        "unverified_findings": [
            "Runtime response schemas, clocks, serving release, and error behavior require an API capture against the exact release.",
            "Static source cannot prove that a fetch result is rendered or that an endpoint has no external consumers.",
        ],
        "machine_claims": {
            "source_complete": bool(rows),
            "runtime_complete": False,
            "dead_calls_proven": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="emit only machine-readable JSON")
    args = parser.parse_args()
    report = build_census()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
        print(f"API_CENSUS_SOURCE_ENDPOINTS={report['endpoint_count']}")
        print("API_CENSUS_RUNTIME_VERIFIED=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
