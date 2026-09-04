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


# ═══════════════════════════════════════════════════════════════════════════
# The research truth operator surface
# ═══════════════════════════════════════════════════════════════════════════

TRUTH_ROUTE = "/api/v2/research-intelligence/truth"


def _api():
    import importlib

    scripts_dir = str(REPO / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    return importlib.import_module("api_v2")


def _truth():
    return _api().ROUTES[TRUTH_ROUTE]()


def test_the_truth_route_is_registered():
    assert TRUTH_ROUTE in _api().ROUTES


def test_provider_policy_and_local_cost_policy_are_separate_blocks():
    """The whole point: 850/month is not a Brave quota, and must not read as one."""
    p = _truth()
    assert "brave_provider_policy" in p and "brave_local_cost_policy" in p
    local = p["brave_local_cost_policy"]
    assert local["is_provider_quota"] is False
    assert "LOCAL COST POLICY" in local["label"]
    assert local["monthly_ceiling"] == 850
    claimed = {a["claimed"] for a in local["superseded_assumptions"]}
    assert claimed == {"1000/month", "2000/month"}
    assert all(a["verdict"] == "never measured" for a in local["superseded_assumptions"])


def test_provider_policy_reports_its_own_measurement_state():
    p = _truth()["brave_provider_policy"]
    assert p["state"] in ("MEASURED", "MEASURED_UNMETERED", "CONFIGURED_NOT_PROVEN")
    if p["state"] == "CONFIGURED_NOT_PROVEN":
        assert p["measured_monthly_limit"] is None, "an unmeasured plan must not publish a limit"


def test_the_surface_exposes_every_required_dimension():
    p = _truth()
    for k in (
        "brave_provider_policy",
        "brave_local_cost_policy",
        "brave_usage",
        "brave_reservations",
        "brave_cache_and_dedup",
        "bypass_detection",
        "lane_health",
        "provenance_coverage",
        "last_successful_observation",
        "degraded",
        "brave_adoption",
    ):
        assert k in p, f"operator surface is missing {k}"


def test_bypass_detection_is_clean_and_does_not_report_itself():
    b = _truth()["bypass_detection"]
    assert b["bypass_offenders"] == [], f"bypass offenders: {b['bypass_offenders']}"
    assert b["clean"] is True
    # The detector names the host as a needle; it must exempt itself explicitly.
    assert "scripts/api_v2.py" in b["exempt_detectors"]


def test_lane_health_uses_the_closed_vocabulary_and_does_not_inflate():
    lh = _truth()["lane_health"]
    assert lh["row_count"] >= 39
    assert set(lh["summary"]) <= set(lh["vocabulary"])
    for row in lh["docker"] + lh["hermes"]:
        assert row["classification"] != "WIRED_AND_WORKING", (
            f"{row['component']} promoted to WIRED_AND_WORKING on container/timer state alone"
        )


def test_adoption_state_admits_no_production_history():
    a = _truth()["brave_adoption"]
    assert a["state"] in ("NO_PRODUCTION_HISTORY", "PRODUCING_NOT_ADOPTED", "ADOPTED")
    if not a["adopted"]:
        assert a["state"] != "ADOPTED"


def test_four_clocks_not_one_last_run():
    c = _truth()["last_successful_observation"]
    for k in ("last_attempt", "last_success", "last_nonempty", "last_adopted"):
        assert k in c


def test_provenance_coverage_names_its_gaps_rather_than_claiming_completeness():
    pc = _truth()["provenance_coverage"]
    assert pc["decision_eligible"] is False
    assert pc["quality_status_for_search_discovery"] == "UNVERIFIED"
    gaps = {g["field"] for g in pc["known_gaps"]}
    assert "author" in gaps
    assert "never invented" in " ".join(g["reason"] for g in pc["known_gaps"])


def test_the_truth_surface_makes_no_provider_call(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key-not-real")

    def forbidden(*a, **k):
        raise AssertionError("the truth surface reached the Brave provider")

    monkeypatch.setattr(R.urllib.request, "urlopen", forbidden)
    p = _truth()
    assert p["provider_call_on_page_load"] is False
    assert p["authority"] == "READ_ONLY_ADVISORY"
