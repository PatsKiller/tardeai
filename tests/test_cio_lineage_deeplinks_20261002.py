"""Router-relative CIO links and lineage deep-link handling (review gaps 3, 4).

BrowserRouter owns basename="/v3": a router target that starts with "/v3/"
resolves to /v3/v3/... .  Plain <a href> anchors bypass the router and are
out of scope here.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "command-center-v3"
SRC = APP / "src"

# <Link to="/v3/..."> / to={`/v3/...`} / navigate('/v3/...') / navigate({ pathname: '/v3/...' })
_ROUTER_TARGET = re.compile(
    r"""(?:\bto\s*=\s*\{?\s*|\bnavigate\(\s*(?:\{\s*pathname\s*:\s*)?|\bpathname\s*:\s*)[`'"]/v3(?:/|\?|[`'"])"""
)


def _router_violations(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if _ROUTER_TARGET.search(line)]


def test_scanner_detects_doubled_basename_shapes():
    assert _router_violations('<Link to="/v3/cio?tab=x">')
    assert _router_violations("<Link to={`/v3/cio?tab=${t}`}>")
    assert _router_violations("navigate('/v3/cio')")
    assert _router_violations("navigate({ pathname: '/v3/cio' })")
    assert not _router_violations('<Link to="/cio?tab=x">')
    assert not _router_violations('<a href="/v3/portfolio">')


def test_no_router_link_or_navigate_target_doubles_the_v3_basename():
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.ts*")):
        if path.suffix not in {".ts", ".tsx"} or ".test." in path.name:
            continue
        for line in _router_violations(path.read_text(encoding="utf-8", errors="replace")):
            offenders.append(f"{path.relative_to(APP)}: {line[:160]}")
    assert offenders == [], "router targets must be basename-relative:\n" + "\n".join(offenders)


def test_basename_is_still_v3_so_the_scan_is_meaningful():
    assert 'basename="/v3"' in (SRC / "App.tsx").read_text(encoding="utf-8")


def test_cio_hub_decisions_tab_opens_lineage_for_decision_param():
    hub = (SRC / "pages" / "CioHub.tsx").read_text(encoding="utf-8")
    decisions = hub[hub.index("{tab === 'decisions' && ("):hub.index("{tab === 'research' && (")]
    assert "cioDeepLinkFocus(sp)" in hub
    assert "focus.decision &&" in decisions
    assert "<CioDecisionLineagePanel decisionId={focus.decision} />" in decisions
    assert "scrollIntoView" in hub


def test_cio_hub_research_tab_honours_decision_artifact_and_research_params():
    hub = (SRC / "pages" / "CioHub.tsx").read_text(encoding="utf-8")
    research = hub[hub.index("{tab === 'research' && ("):hub.index("{tab === 'capital-policy' && (")]
    assert "focus.artifact" in research and "focus.research" in research and "focus.decision" in research
    # The research evidence panel reads decision= from the URL itself.
    assert '<CioOperatorEvidencePanel section="research" />' in research
    # Tab switches copy every search param, so decision= survives navigation.
    select = hub[hub.index("const selectTab"):hub.index("const clearDecisionFocus")]
    assert "new URLSearchParams(sp)" in select
    assert "delete('decision')" not in select


def test_lineage_panel_renders_backend_state_reason_verbatim():
    panel = (SRC / "components" / "cio" / "CioDecisionLineagePanel.tsx").read_text(encoding="utf-8")
    assert "stage?.state_reason" in panel
    assert "source not exposed" not in panel
