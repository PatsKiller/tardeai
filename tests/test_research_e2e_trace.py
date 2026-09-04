#!/usr/bin/env python3
"""The three end-to-end symbol traces, asserted stage by stage.

Every other suite in this campaign tests one stage. This one asserts the chain:
producer/query -> Brave router -> durable store -> provenance -> domain contract
-> API projection -> operator surface.

Deterministic: fixture transports, an isolated state root, a pinned clock. No
test here spends a Brave call, and the last test proves that structurally.
"""

from __future__ import annotations

import ast
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import research_e2e_trace as T  # noqa: E402
from scripts.lib import brave_research_router as R  # noqa: E402

NOW = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "fixture-key-not-real")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "25")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "850")
    (tmp_path / "data" / "runtime").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _stage(trace_dict, name):
    return next(s for s in trace_dict["stages"] if s["name"] == name)


# ── Trace 1: held capital, evidence available ───────────────────────────────


def test_trace_1_walks_all_seven_stages(root):
    d = T.run_all(root=root, now=NOW)
    t = d["traces"][0]
    assert t["symbol"] == "AAPL"
    assert t["stages_reached"] == 7
    assert t["terminal_stage"] == "operator_surface"
    assert [s["name"] for s in t["stages"]] == list(T.STAGES)


def test_trace_1_produced_a_durable_artifact(root):
    t = T.run_all(root=root, now=NOW)["traces"][0]
    store = _stage(t, "durable_store")
    assert store["reached"] is True
    assert store["detail"]["exists"] is True
    assert store["detail"]["cached_results"] == 2
    assert Path(store["detail"]["path"]).is_file()


def test_trace_1_provenance_is_fresh_but_unverified(root):
    t = T.run_all(root=root, now=NOW)["traces"][0]
    prov = _stage(t, "provenance_record")["detail"]
    assert prov["freshness_status"] == "FRESH"
    assert prov["quality_status"] == "UNVERIFIED"
    assert prov["durable_output_present"] is True
    assert "SEARCH_DISCOVERY" in prov["degraded_label"]


def test_trace_1_is_displayable_but_never_decision_eligible(root):
    """A primary-source hit is still a snippet until the source is ingested."""
    t = T.run_all(root=root, now=NOW)["traces"][0]
    dom = _stage(t, "domain_contract")["detail"]
    assert dom["display_accepted"] is True
    assert dom["proposal_accepted"] is False
    assert dom["proposal_decision"] == "INELIGIBLE"
    assert any("QUALITY_FAILURE" in r for r in dom["proposal_reasons"])


# ── Trace 2: provider served nothing ────────────────────────────────────────


def test_trace_2_empty_result_is_a_gap_not_fresh(root):
    t = T.run_all(root=root, now=NOW)["traces"][1]
    assert t["symbol"] == "SCHD"
    assert _stage(t, "brave_router")["detail"]["status"] == "EMPTY"
    prov = _stage(t, "provenance_record")["detail"]
    assert prov["freshness_status"] == "GAP"
    assert prov["durable_output_present"] is False, "an empty answer must not claim a durable research output"


def test_trace_2_surfaces_an_honest_state_not_a_blank(root):
    t = T.run_all(root=root, now=NOW)["traces"][1]
    surf = _stage(t, "operator_surface")["detail"]
    assert surf["raw_DATA_UNAVAILABLE_shown"] is False
    assert surf["symbol_state"]
    assert surf["decision_eligible"] is False


# ── Trace 3: negative control, refused before spending ──────────────────────


def test_trace_3_is_refused_before_the_provider_is_reached(root):
    t = T.run_all(root=root, now=NOW)["traces"][2]
    assert t["symbol"] == "TSLA"
    rt = _stage(t, "brave_router")["detail"]
    assert rt["status"] == "DENIED_NO_EVIDENCE_GAP"
    assert rt["provider_billed"] is False


def test_trace_3_produces_no_durable_artifact_and_says_so(root):
    t = T.run_all(root=root, now=NOW)["traces"][2]
    store = _stage(t, "durable_store")
    assert store["reached"] is False
    assert store["detail"]["exists"] is False
    assert "DENIED_NO_EVIDENCE_GAP" in store["reason"]
    assert "Stopped producing a durable artifact" in t["note"]


def test_trace_3_denial_is_ineligible_not_absence(root):
    t = T.run_all(root=root, now=NOW)["traces"][2]
    prov = _stage(t, "provenance_record")["detail"]
    assert prov["freshness_status"] == "INELIGIBLE"
    assert prov["freshness_status"] != "NO_DATA"


def test_trace_3_still_reaches_the_operator_surface(root):
    """A refusal must be *shown*, not swallowed."""
    t = T.run_all(root=root, now=NOW)["traces"][2]
    assert _stage(t, "operator_surface")["reached"] is True
    assert t["terminal_stage"] == "operator_surface"


# ── Cross-cutting invariants ────────────────────────────────────────────────


def test_no_trace_is_ever_decision_eligible(root):
    d = T.run_all(root=root, now=NOW)
    assert d["any_decision_eligible"] is False
    for t in d["traces"]:
        assert t["decision_eligible"] is False


def test_the_api_projection_never_calls_the_provider(root):
    d = T.run_all(root=root, now=NOW)
    for t in d["traces"]:
        assert _stage(t, "api_projection")["detail"]["provider_call_on_page_load"] is False


def test_stale_evidence_is_detected_and_labelled_at_gate_time(root):
    """Re-gating stored evidence days later must change what the gate says.

    The eligibility policy decides staleness from `freshness_age_seconds` and
    nothing else recomputes it — `_clock_reasons` checks future skew and clock
    regression, never age. An observation stamped once at ingest therefore
    stayed permanently "fresh" however old it got, so the trace now re-derives
    age with `age_at()` before gating.

    Display is *not* revoked: the contract deliberately permits stale research
    to remain visible **with an explicit degraded label**. What must change is
    that staleness is named in the reasons, and that it is never proposal-
    eligible.
    """
    later = NOW + timedelta(days=5)
    tr = T._fixture_transport(T._web([{"title": "t", "url": "https://www.sec.gov/x", "description": "d"}]))
    fresh = T.trace_symbol(
        "AAPL", scenario="fresh", query="AAPL 8-K material event filing", root=root, now=NOW, transport=tr
    )
    stale = T.trace_symbol(
        "AAPL",
        scenario="stale",
        query="AAPL 8-K material event filing",
        root=root,
        now=NOW,
        eligibility_now=later,
        transport=tr,
    )

    f_dom = _stage(fresh.to_dict(), "domain_contract")["detail"]
    s_dom = _stage(stale.to_dict(), "domain_contract")["detail"]

    assert f_dom["age_seconds_at_gate"] < 60
    assert s_dom["age_seconds_at_gate"] >= 5 * 86400 - 60

    assert not any("STALE_AGE" in r for r in f_dom["display_reasons"])
    assert any("STALE_AGE" in r for r in s_dom["display_reasons"]), "5-day-old evidence was not reported as stale"

    # Visible, but labelled — and never decision-grade either way.
    assert stale.display_eligible is True
    assert s_dom["display_decision"] == "DISPLAY_ONLY"
    assert fresh.decision_eligible is False
    assert stale.decision_eligible is False


def test_age_at_never_mutates_the_original_observation(root):
    from scripts.lib.research_observation.brave_adapter import age_at, wrap_brave_outcome

    out = R.Outcome(
        status=R.Status.OK,
        query="q",
        fingerprint="f",
        as_of=NOW.isoformat(),
        results=[R.Result(title="t", url="https://e.com/1", description="d", source_domain="e.com")],
    )
    obs = wrap_brave_outcome(out, run_id="r", trace_id="t", now=NOW)
    aged = age_at(obs, NOW + timedelta(days=3))
    assert obs.freshness_age_seconds < 60, "the ingest-time age was overwritten"
    assert aged.freshness_age_seconds >= 3 * 86400 - 60
    assert aged is not obs


def test_the_traces_are_deterministic(root, tmp_path):
    a = T.run_all(root=root, now=NOW)
    b = T.run_all(root=tmp_path / "second", now=NOW)
    strip = lambda d: [  # noqa: E731
        {k: v for k, v in t.items() if k not in ("stages",)} for t in d["traces"]
    ]
    assert strip(a) == strip(b)


def test_the_trace_module_makes_no_unfixtured_provider_call():
    """Structural: the only network path is the router, and tests pass a fixture."""
    src = (REPO / "scripts" / "research_e2e_trace.py").read_text()
    tree = ast.parse(src)
    urls = {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("http")
    }
    assert urls <= {"https://www.sec.gov/Archives/edgar/x.htm", "https://reuters.com/a", "https://x/1"}, (
        f"trace module names unexpected network targets: {urls}"
    )
    calls = {
        getattr(n.func, "attr", None) or getattr(n.func, "id", None) for n in ast.walk(tree) if isinstance(n, ast.Call)
    }
    assert "urlopen" not in calls, "the trace module opens its own connection"


def test_run_all_covers_three_distinct_chain_outcomes(root):
    """Three traces of the same happy path would prove very little."""
    d = T.run_all(root=root, now=NOW)
    statuses = {_stage(t, "brave_router")["detail"]["status"] for t in d["traces"]}
    assert len(statuses) == 3, f"traces are not distinct: {statuses}"
    freshness = {_stage(t, "provenance_record")["detail"]["freshness_status"] for t in d["traces"]}
    assert freshness == {"FRESH", "GAP", "INELIGIBLE"}
