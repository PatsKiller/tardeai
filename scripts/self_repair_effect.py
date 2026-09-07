"""Bounded diagnostics: emit repair proposals, never perform repairs."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

SCHEMA = "SelfRepairProposal@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

# Declared for scripts/check_dark_contracts.py. The guard's rule is not "wire a
# consumer" — it is "do not be silent about not having one":
#
#     "A module may legitimately have no consumer yet. What it may not do is be
#      silent about it."
#
# Zero consumers is the CORRECT state here and wiring one would be the wrong
# fix. Self-repair is shadow-only by mandate: it emits proposals for operator
# review and never performs a repair (AUTHORITY = READ_ONLY_ADVISORY above, and
# AGENTS.md §0.1 MBI_BEHAVIOR=0). An autonomous consumer of SelfRepairProposal@v1
# would turn a proposal into an action, which is exactly what this module exists
# not to do.
#
# Authored by the INTEGRATION OWNER, not by lane D — the lane D session had
# exited before this regression was found, so this is not lane testimony. See
# returns/LANE_D_FINDINGS_R2.md and control/CAMPAIGN_MANIFEST.json.
NO_CONSUMER_REASON = (
    "shadow-only self-repair; proposals await operator review, no autonomous "
    "consumer by design (campaign m2-canary-20260907)"
)
MAX_EDGES = 100


def diagnose_and_propose(edges: list[dict[str, Any]], *, source_sha: str = "lane-d",
                         max_edges: int = MAX_EDGES) -> list[dict[str, Any]]:
    """Diagnose missing/broken edges and return bounded, non-executable proposals."""
    out = []
    for edge in sorted(edges, key=lambda x: str(x.get("edge_id", "")))[:max_edges]:
        if edge.get("healthy") is True:
            continue
        edge_id = str(edge.get("edge_id") or "")
        if not edge_id or not edge.get("source") or not edge.get("target"):
            continue
        digest = hashlib.sha256(json.dumps(edge, sort_keys=True, default=str).encode()).hexdigest()
        out.append({"schema_version": SCHEMA, "source_sha": source_sha,
                    "produced_at": datetime.now(timezone.utc).isoformat(),
                    "correlation_id": edge_id, "idempotency_key": "repair:" + digest,
                    "retention_class": "evidence_2y", "lifecycle_state": "PROPOSED",
                    "provenance": {"producer": "lane_d.diagnostics", "inputs": [edge_id],
                                   "reason": edge.get("reason", "broken_edge")},
                    "edge_id": edge_id, "recommended_action": edge.get("recommendation", "inspect edge"),
                    "executable": False, "production_mutation": False,
                    "financial_surface_reachable": False})
    return out

