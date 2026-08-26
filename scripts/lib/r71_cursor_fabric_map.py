"""R7.1 integration map for Cursor Watchlist Gaps A–F (versioned dependency).

Does NOT import or merge Cursor producer scripts into #397.
Classifies each surface for consumption strategy.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEP_PATH = ROOT / "config" / "r71_cursor_dependency.json"

# Classifications
CONSUME_DIRECTLY = "CONSUME_DIRECTLY"
SHARED_DEPENDENCY = "SHARED_DEPENDENCY"
ACTIVE_TRADER_ONLY = "ACTIVE_TRADER_ONLY"
REDUNDANT_WITH_397 = "REDUNDANT_WITH_397"
NEEDS_INTERFACE_ADAPTER = "NEEDS_INTERFACE_ADAPTER"
DO_NOT_IMPORT = "DO_NOT_IMPORT"

FABRIC_MAP: list[dict[str, Any]] = [
    {
        "component": "sync_social_to_intelligence.py",
        "class": CONSUME_DIRECTLY,
        "via": "intelligence_entities.social_score (DERIVED) + social_sentiment_history rows (primary evidence)",
        "note": "Membership/score ≠ thesis evidence. Thesis cites history rows + provenance.",
    },
    {
        "component": "hermes_social_sentiment.py",
        "class": CONSUME_DIRECTLY,
        "via": "social_sentiment_history",
        "note": "Producer already live; thesis reads artifacts, does not re-ingest.",
    },
    {
        "component": "research_watchlist_discovery.py",
        "class": CONSUME_DIRECTLY,
        "via": "watchlist_items bucket=research_discovery status=researched source_tier=candidate",
        "note": "Universe signal only. Requires origin_system/origin_detail or PROVENANCE_INCOMPLETE.",
    },
    {
        "component": "candidate_discovery_orchestrator.py",
        "class": CONSUME_DIRECTLY,
        "via": "candidate_discovery_events",
        "note": "May wake coverage/materiality/RAG check — never auto thesis version.",
    },
    {
        "component": "drain_discovery_backlog.py",
        "class": DO_NOT_IMPORT,
        "via": None,
        "note": "Cursor cron lane; #397 does not drain discovery backlog.",
    },
    {
        "component": "desk_suggestions_digest.py",
        "class": NEEDS_INTERFACE_ADAPTER,
        "via": "optional read of digest artifacts for CC discovery surface",
        "note": "Operator transparency only; not thesis evidence.",
    },
    {
        "component": "install_watchlist_remediation_cron.py",
        "class": DO_NOT_IMPORT,
        "via": None,
        "note": "Do not install duplicate R7 crons.",
    },
    {
        "component": "cron_self_heal.py",
        "class": SHARED_DEPENDENCY,
        "via": "idempotent consumers must tolerate replay",
        "note": "Preserve; thesis pipeline must be replay-safe.",
    },
    {
        "component": "job_coverage_monitor.py",
        "class": SHARED_DEPENDENCY,
        "via": "health signals",
        "note": "rag_embeddings schedule_match bug is Cursor-owned false NOT_SCHEDULED.",
    },
    {
        "component": "health_agent_policy",
        "class": SHARED_DEPENDENCY,
        "via": "source-aware remediation model",
        "note": "Producer health ≠ evidence trustworthiness.",
    },
    {
        "component": "watchlist provenance (origin_system/origin_detail)",
        "class": CONSUME_DIRECTLY,
        "via": "watchlist_items columns",
        "note": "null origin → LEGACY_UNATTRIBUTED; do not invent writer.",
    },
    {
        "component": "source-health migration",
        "class": CONSUME_DIRECTLY,
        "via": "migrations/2026-08-19_watchlist_source_health.sql + report_source()",
        "note": "Expose HEALTHY/DEGRADED/AUTH_REQUIRED/STALE/UNKNOWN before acquisition.",
    },
    {
        "component": "SearXNG",
        "class": SHARED_DEPENDENCY,
        "via": "scripts/lib/searxng_client.py thin shared wrapper",
        "note": "One client; used by Cursor discovery and #397 acquisition plan.",
    },
    {
        "component": "rag_indexer / content_embeddings",
        "class": SHARED_DEPENDENCY,
        "via": "existing cron 0 */4 rag_indexer.py",
        "note": "Do not create duplicate embedding cron. Detection fix belongs on Cursor branch.",
    },
    {
        "component": "CURATION_AUTO_APPLY=1",
        "class": CONSUME_DIRECTLY,
        "via": "existing governor; observe soak metrics only",
        "note": "Promotion ≠ research confidence. Bootstrap floor 0.65 ≠ measured alpha.",
    },
    {
        "component": "two_way_curation",
        "class": DO_NOT_IMPORT,
        "via": None,
        "note": "Already live; #397 does not rebuild curation.",
    },
    {
        "component": "options_monitor / options_paper_lifecycle / protection_pipeline",
        "class": ACTIVE_TRADER_ONLY,
        "via": None,
        "note": "Not blockers for symbol-thesis PR unless release gates require.",
    },
]


def load_dependency() -> dict[str, Any]:
    if DEP_PATH.is_file():
        return json.loads(DEP_PATH.read_text(encoding="utf-8"))
    return {"cursor_remediation_versioned": False, "error": "missing_dependency_file"}


def fabric_map_report() -> dict[str, Any]:
    dep = load_dependency()
    by_class: dict[str, list[str]] = {}
    for row in FABRIC_MAP:
        by_class.setdefault(row["class"], []).append(row["component"])
    return {
        "schema": "R71CursorFabricMap@v1",
        "dependency": {
            "cursor_branch": dep.get("cursor_branch"),
            "cursor_head": dep.get("cursor_head"),
            "cursor_remediation_versioned": dep.get("cursor_remediation_versioned"),
            "cursor_pr": dep.get("cursor_pr"),
            "dependency_strategy": dep.get("dependency_strategy"),
            "on_main": dep.get("on_main"),
        },
        "map": FABRIC_MAP,
        "by_class": by_class,
        "hold_on_unversioned": not bool(dep.get("cursor_remediation_versioned")),
        "authority": "READ_ONLY_ADVISORY",
    }
