"""Router-relative links in the cross-surface files touched on 2026-10-02."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "apps/command-center-v3/src"
TOUCHED = [
    SRC / "pages/HermesHub.tsx",
    SRC / "pages/ResearchIntelligenceHub.tsx",
    SRC / "pages/AgentRuntimeHub.tsx",
    SRC / "components/HermesDecisionLinksPanel.tsx",
    SRC / "lib/hermesResearchLinks.ts",
]
V3_LINK = re.compile(r"""\b(?:to|href)=\{?\s*[`'"]/v3/|navigate\(\s*[`'"]/v3/|Href\([^)]*\)\s*[:=]\s*[`'"]/v3/|return\s+[`'"]/v3/""")


def test_no_basename_prefixed_internal_links_in_touched_files():
    offenders = []
    for path in TOUCHED:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if V3_LINK.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert offenders == []


def test_hermes_links_panel_targets_decision_lineage_and_research_intelligence():
    lib = (SRC / "lib/hermesResearchLinks.ts").read_text(encoding="utf-8")
    assert "`/cio?tab=evidence-comms&sub=decision-lineage&decision=" in lib
    assert "`/research-intelligence?symbol=" in lib
    hub = (SRC / "pages/HermesHub.tsx").read_text(encoding="utf-8")
    assert "HermesDecisionLinksPanel" in hub
    assert "searchParams.get('tab')" in hub  # /hermes?tab=Provenance deep links now land on the tab
    ri = (SRC / "pages/ResearchIntelligenceHub.tsx").read_text(encoding="utf-8")
    assert "HermesDecisionLinksPanel" in ri


def test_agent_proof_rows_are_no_longer_hardcoded_not_exposed():
    hub = (SRC / "pages/AgentRuntimeHub.tsx").read_text(encoding="utf-8")
    assert "'NOT EXPOSED BY READ CONTRACT', 'UNKNOWN']" not in hub
    for key in ("last_natural_wake", "last_research_action", "last_memory_retrieval", "decisions_contributed"):
        assert f"proofRow(proof, agent.agentId, '{key}')" in hub
