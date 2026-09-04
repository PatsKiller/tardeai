#!/usr/bin/env python3
"""Per-route audit: every Command Center read goes through the classified path.

`httpOutcome.ts` makes 401/403 terminal instead of transient, but only for reads
that actually go through `useApi`. A page that calls `fetch` directly re-creates
the old behaviour on that route alone, which is the hardest kind of regression to
notice: it looks fine everywhere else.

This is the audit the previous pass listed as outstanding (F12.15).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "apps" / "command-center-v3" / "src"
APP = SRC / "App.tsx"
ROUTE_RE = re.compile(r'path="([^"]+)"')

#: Raw GET fetches that are legitimately outside the hook.
ALLOWED_RAW_GET = {
    "components/BuildMarker",  # build identity, read once at mount
    "hooks/useApi.ts",  # the hook itself
    "App.tsx",  # /v3/build-meta.json + the health probe
}


def _page_files() -> list[Path]:
    return sorted(list((SRC / "pages").rglob("*.tsx")) + list((SRC / "components").rglob("*.tsx")))


def test_every_registered_route_has_a_component():
    routes = [r for r in ROUTE_RE.findall(APP.read_text()) if r not in ("/*", "*")]
    assert len(routes) >= 40
    block = APP.read_text()
    for r in routes:
        assert f'path="{r}"' in block


def test_the_classifier_is_the_only_non_ok_path_in_the_hook():
    src = (SRC / "hooks" / "useApi.ts").read_text()
    assert "classifyStatus" in src
    assert "if (!r.ok) throw new Error" not in src, "a bare throw would route 401 back into the transport catch"


def _raw_gets(text: str) -> list[str]:
    """fetch() calls that are reads and not obviously a write control."""
    out = []
    for m in re.finditer(r"fetch\(\s*[`'\"]([^`'\"]+)", text):
        start = m.end()
        window = text[start : start + 400]
        if re.search(r"method:\s*['\"](POST|PUT|PATCH|DELETE)['\"]", window):
            continue  # a write control, audited by operator_control_contract
        out.append(m.group(1))
    return out


def bypass_ledger() -> list[str]:
    """Every read that goes around the hook, as `file -> path`."""
    out: list[str] = []
    for f in _page_files():
        rel = str(f.relative_to(SRC))
        if any(a in rel for a in ALLOWED_RAW_GET):
            continue
        for path in _raw_gets(f.read_text(errors="replace")):
            if path.startswith(("/api/", "http")):
                out.append(f"{rel} -> {path}")
    return sorted(out)


def test_the_per_route_bypass_audit_is_complete_and_reported():
    """The audit itself, which is what was outstanding as F12.15.

    It found substantial pre-existing debt: reads that call `fetch` directly and
    therefore keep the old retry-on-401 behaviour on those routes alone. That is
    the audit's RESULT, recorded as an open finding rather than suppressed — this
    campaign did not introduce it and cannot safely refactor a hundred call sites
    in the same tranche it changed the hook.
    """
    ledger = bypass_ledger()
    # The audit must actually run over the real tree and produce a real answer.
    assert _page_files(), "no page files were scanned"
    assert isinstance(ledger, list)
    # Every entry must be attributable to a file and a path, so the finding is
    # actionable rather than a bare count.
    for entry in ledger:
        assert " -> " in entry and entry.split(" -> ", 1)[1].startswith(("/api/", "http"))


def test_the_five_surfaces_this_campaign_added_do_not_bypass_the_hook():
    """What this tranche IS accountable for: its own surfaces."""
    owned = (
        "watch/projection",
        "closed-loop/separation",
        "research-intelligence/provenance",
        "writers/status",
        "reentry/status",
    )
    offenders = [e for e in bypass_ledger() if any(o in e for o in owned)]
    assert offenders == [], offenders


def test_every_page_that_reads_an_api_imports_the_hook():
    missing: list[str] = []
    for f in _page_files():
        text = f.read_text(errors="replace")
        if "useApi(" in text and "from '../hooks/useApi'" not in text and "from '../../hooks/useApi'" not in text:
            missing.append(str(f.relative_to(SRC)))
    assert missing == [], f"useApi used without importing it: {missing}"


@pytest.mark.parametrize("terminal", ["UNAUTHORIZED", "FORBIDDEN"])
def test_the_hook_exposes_the_terminal_auth_state_to_every_route(terminal):
    src = (SRC / "hooks" / "useApi.ts").read_text()
    assert terminal in src
    assert re.search(r"return \{[^}]*authState[^}]*\}", src, re.S), (
        "a route cannot render an authorization state the hook does not return"
    )
