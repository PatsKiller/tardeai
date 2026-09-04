#!/usr/bin/env python3
"""The Brave effectiveness surface: read-only, and it must stay that way.

This route was deferred for the whole campaign because `scripts/api_v2.py` was
leased by the unmerged cc-whole-site-residual-v1 campaign. That campaign merged
(PRs #850/#851), so the surface is now wired — and the property that made it
safe to defer is the one that most needs a test: **rendering must never reach a
paid provider.**

The library-level guarantee already exists (`Purpose.PAGE_LOAD` is
`DENIED_POLICY` before any budget or network work). These tests pin it *at the
route*, because a future handler could reasonably-looking call `search()` to
"refresh" the panel and nothing else would catch it.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

API_V2 = REPO / "scripts" / "api_v2.py"
ROUTE = "/api/v2/research-intelligence/brave"
HANDLER = "_brave_research_effectiveness"

from scripts.lib import brave_research_router as R  # noqa: E402


# ── wiring ──────────────────────────────────────────────────────────────────


def test_the_route_is_registered():
    src = API_V2.read_text(encoding="utf-8")
    assert f'"{ROUTE}"' in src, "the Brave effectiveness route is not registered"
    assert f"def {HANDLER}(" in src, "the handler is missing"


def test_the_route_maps_to_the_handler():
    """A route registered to the wrong handler is worse than an absent one."""
    src = API_V2.read_text(encoding="utf-8")
    line = next(ln for ln in src.splitlines() if f'"{ROUTE}"' in ln)
    assert HANDLER in line, f"route line does not call {HANDLER}: {line.strip()}"


# ── the load-bearing negative control ───────────────────────────────────────


def _handler_source() -> str:
    src = API_V2.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == HANDLER:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{HANDLER} not found")


def test_the_handler_makes_no_provider_call():
    """Static proof: the handler calls only read-only reporting functions."""
    tree = ast.parse(_handler_source())
    bare: set[str] = set()
    qualified: set[str] = set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Attribute):
            owner = getattr(f.value, "id", "")
            qualified.add(f"{owner}.{f.attr}" if owner else f.attr)
        elif isinstance(f, ast.Name):
            bare.add(f.id)

    # Bare names that would mean a provider or budget call.
    forbidden_bare = {"search", "try_consume", "reserve", "guard", "settle", "urlopen", "urlretrieve"}
    hits = bare & forbidden_bare

    # Qualified calls, owner-aware: `rep.get(...)` is a dict read; `requests.get`
    # is a fetch. Matching bare `get` conflates the two and fails on the former.
    NETWORK_OWNERS = {"requests", "session", "http", "httpx", "urllib", "client"}
    for q in qualified:
        if "." not in q:
            continue
        owner, attr = q.split(".", 1)
        if owner in NETWORK_OWNERS and attr in {"get", "post", "request", "urlopen"}:
            hits.add(q)
        if attr in {"search", "try_consume", "reserve", "guard", "settle"}:
            hits.add(q)

    assert not hits, f"the render path calls provider/budget functions: {sorted(hits)}"
    assert {"effectiveness_report", "health"} <= bare, "the handler no longer reads the canonical report"


def test_rendering_the_surface_never_reaches_the_network(monkeypatch, tmp_path):
    """Behavioural proof: run the handler with the transport booby-trapped."""
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key-not-real")

    def forbidden(*a, **k):
        raise AssertionError("a page load reached the Brave provider")

    monkeypatch.setattr(R.urllib.request, "urlopen", forbidden)

    # api_v2 uses flat imports (`import local_llm_config`), so scripts/ must be
    # on the path. Importing it as `scripts.api_v2` fails for that reason alone,
    # and skipping on that would retire the only behavioural proof this file has.
    import importlib

    scripts_dir = str(REPO / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    mod = importlib.import_module("api_v2")

    assert ROUTE in mod.ROUTES, "the route is not in the live ROUTES table"
    payload = getattr(mod, HANDLER)()
    assert payload["provider_call_on_page_load"] is False
    assert payload["authority"] == "READ_ONLY_ADVISORY"
    # And the route's own lambda resolves without touching the provider.
    via_route = mod.ROUTES[ROUTE]()
    assert via_route["provider_call_on_page_load"] is False


def test_page_load_purpose_is_still_denied_at_the_library(tmp_path, monkeypatch):
    """The library guarantee the route depends on."""
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "25")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "850")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key-not-real")

    def forbidden(*a, **k):
        raise AssertionError("PAGE_LOAD reached the provider")

    monkeypatch.setattr(R.urllib.request, "urlopen", forbidden)
    out = R.search("render", purpose=R.Purpose.PAGE_LOAD, priority=R.Priority.HELD_CAPITAL, caller="ui", root=tmp_path)
    assert out.status is R.Status.DENIED_POLICY


# ── the payload tells the truth ─────────────────────────────────────────────


def _payload(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_state_root", lambda root=None: tmp_path)
    from scripts.lib.brave_research_router import effectiveness_report, health

    rep, hb = effectiveness_report(root=tmp_path), health(root=tmp_path)
    return rep, hb


def test_an_unmeasured_allowance_is_reported_as_an_assumption(tmp_path, monkeypatch):
    rep, hb = _payload(tmp_path, monkeypatch)
    recon = rep["allowance_reconciliation"]
    assert recon["reconciled"] is False
    assert "assumption" in recon["note"].lower()
    assert "brave_allowance_never_measured" in hb["firing"], (
        "an unmeasured ceiling must surface as a firing condition, not be assumed"
    )


def test_the_surface_reports_four_separate_clocks(tmp_path, monkeypatch):
    _rep, hb = _payload(tmp_path, monkeypatch)
    for k in ("last_attempt", "last_success", "last_nonempty", "last_adopted"):
        assert k in hb, f"{k} is not reported; one clock cannot express adoption"


def test_the_handler_labels_producing_but_not_adopted(tmp_path, monkeypatch):
    """A lane that spends and is never cited must not read as healthy."""
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "25")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "850")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key-not-real")

    import json as _json

    class Resp:
        headers = {"x-ratelimit-policy": "1;w=1, 2000;w=2592000", "x-ratelimit-limit": "1, 2000"}
        status = 200

        def read(self):
            return _json.dumps(
                {"web": {"results": [{"title": "t", "url": "https://e.com/1", "description": "d"}]}}
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(R.urllib.request, "urlopen", lambda req, timeout=None: Resp())
    R.search("spend", caller="t", root=tmp_path)
    hb = R.health(root=tmp_path)
    assert "brave_producing_not_adopted" in hb["firing"]
    assert hb["ok"] is False


def test_the_route_is_read_only_advisory():
    src = _handler_source()
    assert "READ_ONLY_ADVISORY" in src
    for forbidden in ("place_order", "submit_order", "cancel_order", "broker_write"):
        assert forbidden not in src.lower()
