#!/usr/bin/env python3
"""Every route is wrapped so one page's throw cannot blank the whole application.

Found by the browser/state matrix (cc-whole-site-residual-v1): `/v3/strategy` threw
`TypeError: m is not iterable` and the ENTIRE shell rendered zero elements. A blank
page is indistinguishable from "no data", from "still loading", and from "everything
is fine" — the least honest state a surface can be in.

Structural assertions over App.tsx. No network, no browser, no production path.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "apps" / "command-center-v3" / "src" / "App.tsx"
BOUNDARY = ROOT / "apps" / "command-center-v3" / "src" / "components" / "truth" / "RouteErrorBoundary.tsx"

ROUTE_RE = re.compile(r"<Route\s+((?:path=\"[^\"]+\"|index)[^>]*?)element=\{", re.S)


@pytest.fixture(scope="module")
def app_src() -> str:
    return APP.read_text()


def _shell_routes_block(src: str) -> str:
    start = src.index("          <Routes>")
    end = src.index("          </Routes>", start)
    return src[start:end]


def test_the_boundary_component_exists():
    assert BOUNDARY.is_file(), "RouteErrorBoundary.tsx is missing"
    src = BOUNDARY.read_text()
    assert "getDerivedStateFromError" in src, "not a React error boundary"
    assert "componentDidCatch" in src
    assert 'data-route-error="true"' in src, "the failure surface must be machine-detectable"


def test_every_shell_route_is_wrapped(app_src):
    block = _shell_routes_block(app_src)
    declared = ROUTE_RE.findall(block)
    assert len(declared) >= 40, f"expected the full route table, found {len(declared)}"
    wrapped = block.count("<RouteErrorBoundary route=")
    assert wrapped == len(declared), (
        f"{len(declared)} routes declared but only {wrapped} wrapped — an unwrapped route can "
        f"still blank the application"
    )


def test_each_boundary_names_its_own_route(app_src):
    """A boundary that cannot name the route it caught is half a message."""
    block = _shell_routes_block(app_src)
    routes = re.findall(r'<RouteErrorBoundary route="([^"]+)">', block)
    assert routes, "no boundaries found"
    assert all(r.startswith("/v3") for r in routes), routes
    assert len(set(routes)) == len(routes), "two boundaries claim the same route"


def test_the_boundary_does_not_swallow_the_failure(app_src):
    """Rendering nothing on catch would reproduce the defect it exists to fix."""
    src = BOUNDARY.read_text()
    assert "FAILED TO RENDER" in src
    assert "error.name" in src and "error.message" in src
    assert "return this.props.children" in src, "the happy path must pass through untouched"


def test_strategy_hub_narrows_wire_payloads_to_arrays():
    """The specific defect: `[...btResults]` when the endpoint answered an object."""
    src = (ROOT / "apps" / "command-center-v3" / "src" / "pages" / "StrategyHub.tsx").read_text()
    assert "const asRows" in src and "Array.isArray" in src
    assert "[...btData]" in src, "the spread is fine once btData is proven to be an array"
    assert "const btData = asRows(btResults)" in src
    assert "MALFORMED PAYLOAD" in src, "a bad shape must be disclosed, not absorbed as empty"
