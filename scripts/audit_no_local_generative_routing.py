#!/usr/bin/env python3
"""Fail CI if an automatic Trade AI path can reach local generation."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PRODUCTION_FILES = (
    "scripts/api_v2.py",
    "scripts/llm_lane.py",
    "scripts/llm_router.py",
    "scripts/local_llm.py",
    "scripts/process_watchlist_agent_jobs.py",
    "scripts/research_scheduler.py",
    "scripts/hermes_llm_failover.py",
    "scripts/hermes_autonomous_loop.py",
    "scripts/hermes_deep_research_local.py",
    "scripts/hermes_external_feedback_loop.py",
    "scripts/hermes_coordinator.py",
    "scripts/multi_tier_trade_reviewer.py",
    "scripts/incubator_llm_screener.py",
    "scripts/strategy_planner.py",
    "scripts/hermes_browse_proxy.py",
    "scripts/check_local_model_fleet.py",
)

PRODUCTION_CONFIG_FILES = (
    "config/hermes_research_budget.yaml",
    "config/hermes_research_worker_lanes.yaml",
    "config/inference_layers.yaml",
    "config/phase2g_hybrid_canary.yaml",
    "config/phase2h_bounded_hybrid_rag_policy.yaml",
    "config/phase3_media_prose_routing.yaml",
    "config/llm_fleet_alert_rules.yaml",
)

ENDPOINT_RE = re.compile(r"/api/(?:chat|generate)(?:\b|[\"'])")
LOCAL_LANE_RE = re.compile(r"lane\s*=\s*[\"']local[\"']")
GEN_MODEL_RE = re.compile(
    r"(?:gemma(?:3|4)[-:]|qwen3:(?:1\.7b|4b|8b|12b|14b|27b))",
    re.IGNORECASE,
)
REENABLE_RE = re.compile(
    r"(?:RESEARCH_ALLOW_LOCAL_LLM|LLM_ALLOW_LOCAL_JUDGMENT|HERMES_OLLAMA_FAILOVER)"
)


def audit() -> dict:
    violations: list[dict[str, object]] = []
    for rel in PRODUCTION_FILES:
        path = ROOT / rel
        source = path.read_text(encoding="utf-8")
        for number, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            checks = (
                ("generative_endpoint", ENDPOINT_RE),
                ("local_lane", LOCAL_LANE_RE),
                ("generative_model", GEN_MODEL_RE),
                ("runtime_reenable_flag", REENABLE_RE),
            )
            for kind, pattern in checks:
                if pattern.search(line):
                    violations.append({
                        "file": rel,
                        "line": number,
                        "kind": kind,
                        "text": stripped[:180],
                    })

    for rel in PRODUCTION_CONFIG_FILES:
        source = (ROOT / rel).read_text(encoding="utf-8")
        for number, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if GEN_MODEL_RE.search(line) or REENABLE_RE.search(line):
                violations.append({
                    "file": rel, "line": number, "kind": "config_local_generation",
                    "text": stripped[:180],
                })

    for rel in (
        "config/systemd/user/hermes-autonomous-loop.service",
        "config/systemd/user/hermes-deep-research-local.service",
        "config/systemd/user/hermes-external-feedback.service",
    ):
        source = (ROOT / rel).read_text(encoding="utf-8")
        for number, line in enumerate(source.splitlines(), 1):
            if REENABLE_RE.search(line) or GEN_MODEL_RE.search(line):
                violations.append({
                    "file": rel, "line": number, "kind": "service_local_generation",
                    "text": line.strip()[:180],
                })

    return {
        "schema": "LocalGenerativeRoutingAudit@v1",
        "production_files": list(PRODUCTION_FILES),
        "production_config_files": list(PRODUCTION_CONFIG_FILES),
        "violations": violations,
        "violation_count": len(violations),
        "compliant": not violations,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = audit()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["compliant"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
