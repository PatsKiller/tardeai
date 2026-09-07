"""Provider capacity is what the provider said. Local policy is what we chose.

The defect: `brave_search.py` asserted a 1,000/month Brave plan in a docstring
and a constant comment ("850 ... out of 1000"), while discarding the
X-RateLimit-* headers that would have said what the plan actually is. A number
we picked was rendered as a number they impose, and the only authority that
could settle it was received and dropped on every call.

Most of these tests are about what the module REFUSES to do, because a contract
that separates two authorities is only useful if it cannot be talked into
merging them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.research_provider_truth import (  # noqa: E402
    BRAVE_LOCAL_COST_POLICY,
    LocalCostPolicy,
    ProviderCapacity,
    parse_provider_capacity,
    reconcile,
)

REAL = {
    "X-RateLimit-Limit": "1, 15000",
    "X-RateLimit-Remaining": "1, 14999",
    "X-RateLimit-Reset": "1, 1419704",
    "X-RateLimit-Policy": "1;w=1, 15000;w=2592000",
}


# ── the refusals ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "headers,why",
    [
        (None, "no headers at all"),
        ({}, "empty header map"),
        ({"Content-Type": "application/json"}, "headers present, no rate-limit header"),
        ({"X-RateLimit-Limit": "unparseable"}, "header present but no window parses"),
    ],
)
def test_unobserved_capacity_never_invents_a_number(headers, why):
    """An unobserved provider has NOT told us its limit, and must say so."""
    cap = parse_provider_capacity("brave", headers)
    assert cap.observed is False, why
    assert cap.monthly_limit() is None, "a limit appeared from nowhere"
    assert cap.reason, "a refusal with no reason gets deleted by the next reader"
    assert "NOT OBSERVED" in cap.describe()


def test_the_capacity_record_has_no_field_an_assumption_could_live_in():
    """There is deliberately no `assumed_limit` / `default_limit` key.

    A field like that is exactly how "1,000/month free tier" became a fact: give
    an assumption somewhere to sit and it will be read as measurement.
    """
    d = parse_provider_capacity("brave", None).to_dict()
    for k in d:
        assert "assum" not in k.lower(), k
        assert "default" not in k.lower(), k
        assert "estimat" not in k.lower(), k


def test_local_policy_cannot_be_built_without_an_owner_and_reason():
    """A budget nobody owns outlives the reason for it — which is what happened."""
    with pytest.raises(TypeError):
        LocalCostPolicy(name="X")  # type: ignore[call-arg]


def test_local_policy_declares_itself_local():
    d = BRAVE_LOCAL_COST_POLICY.to_dict()
    assert d["authority"].startswith("LOCAL")
    assert d["owner"]
    assert "NOT a provider plan" in d["rationale"]
    assert "local policy" in BRAVE_LOCAL_COST_POLICY.describe()


# ── the observation ──────────────────────────────────────────────────────────


def test_a_real_response_is_parsed_per_window():
    cap = parse_provider_capacity("brave", REAL)
    assert cap.observed is True
    assert cap.windows["per_second"] == {"limit": 1, "remaining": 1, "reset_seconds": 1}
    assert cap.windows["per_month"]["limit"] == 15000
    assert cap.windows["per_month"]["remaining"] == 14999
    assert cap.monthly_limit() == 15000
    assert cap.observed_at


def test_unknown_and_exhausted_do_not_collapse():
    """`remaining: 0` and `remaining: unknown` are different answers."""
    exhausted = parse_provider_capacity("brave", {"X-RateLimit-Limit": "1, 15000", "X-RateLimit-Remaining": "1, 0"})
    unknown = parse_provider_capacity("brave", {"X-RateLimit-Limit": "1, 15000"})
    assert exhausted.windows["per_month"]["remaining"] == 0
    assert unknown.windows["per_month"]["remaining"] is None


def test_header_casing_does_not_defeat_observation():
    lower = {k.lower(): v for k, v in REAL.items()}
    assert parse_provider_capacity("brave", lower).monthly_limit() == 15000


# ── reconciliation, which must never merge the two ───────────────────────────


def test_unobserved_provider_binds_to_local_policy_for_the_honest_reason():
    r = reconcile(parse_provider_capacity("brave", None), BRAVE_LOCAL_COST_POLICY)
    assert r["binding_ceiling"] == "local_policy"
    assert "unobserved" in r["binding_reason"]
    assert r["conflict"] is None
    # both authorities survive the reconcile, separately
    assert r["provider_capacity"]["observed"] is False
    assert r["local_policy"]["monthly_calls"] == BRAVE_LOCAL_COST_POLICY.monthly_calls


def test_provider_stricter_than_policy_is_reported_as_a_conflict():
    """The case that matters: we would otherwise overspend against a real limit."""
    r = reconcile(parse_provider_capacity("brave", {"X-RateLimit-Limit": "1, 500"}), BRAVE_LOCAL_COST_POLICY)
    assert r["binding_ceiling"] == "provider"
    assert r["conflict"] is not None
    assert "1500" in r["conflict"] and "500" in r["conflict"]


def test_policy_stricter_than_provider_is_not_a_conflict():
    r = reconcile(parse_provider_capacity("brave", REAL), BRAVE_LOCAL_COST_POLICY)
    assert r["binding_ceiling"] == "local_policy"
    assert r["conflict"] is None
    # and the observed provider figure is still published, not hidden by ours
    assert r["provider_capacity"]["windows"]["per_month"]["limit"] == 15000


def test_summary_states_both_authorities_and_never_one_number():
    r = reconcile(parse_provider_capacity("brave", REAL), BRAVE_LOCAL_COST_POLICY)
    s = r["summary"]
    assert "15000" in s, "provider capacity missing from the summary"
    assert "1500" in s, "local policy missing from the summary"
    assert "binding" in s


# ── the source itself must not re-acquire the claim ──────────────────────────


def test_brave_search_states_no_provider_plan_it_has_not_observed():
    src = (ROOT / "scripts" / "brave_search.py").read_text(encoding="utf-8")
    for claim in ("out of 1000", "1,000/month free tier", "1000/month free"):
        assert claim not in src, f"provider-plan claim reintroduced: {claim!r}"


def test_brave_search_observes_the_headers_it_used_to_discard():
    src = (ROOT / "scripts" / "brave_search.py").read_text(encoding="utf-8")
    assert "_observe_capacity(resp" in src, "response headers are being dropped again"
    # Both CALL sites — web and news. Counting the bare name also matches the
    # `def` line, which would let one call site go missing and still pass.
    calls = [ln for ln in src.splitlines() if "_observe_capacity(resp" in ln and not ln.lstrip().startswith("def ")]
    assert len(calls) == 2, f"expected 2 call sites, found {len(calls)}: {calls}"
    # and each must sit before the body is read, or the response may be consumed
    for ln in calls:
        assert ln.strip().startswith("_observe_capacity("), ln


def test_the_three_copies_of_the_ceiling_agree():
    """The ceiling is written in THREE places. They must never drift apart.

    Raised 2026-09-05 on explicit operator instruction, from 25/850 to 120/1500,
    for the Hermes research ramp. The previous version of this test pinned the
    literals 25 and 850 and failed on that change — which is the behaviour I
    wanted from it: a budget change must be deliberate and visible, never
    smuggled in under a refactor. It is updated here, not deleted.

    What it now pins is the property that actually matters and was previously
    untested: lib/search_budget.DEFAULT_LIMITS is the BINDING ceiling — the
    shared check runs first, ahead of brave_search's own — and nothing asserted
    it agreed with the other two. A drift there would mean the documented policy
    and the enforced policy were different numbers.
    """
    import brave_search as b
    from lib.search_budget import DEFAULT_LIMITS

    binding = DEFAULT_LIMITS["brave"]
    assert BRAVE_LOCAL_COST_POLICY.daily_calls == b.DAILY_BUDGET == binding["daily"]
    assert BRAVE_LOCAL_COST_POLICY.monthly_calls == b.MONTHLY_BUDGET == binding["monthly"]
    # And the reserve must leave a real bulk allowance, not swallow the budget.
    from lib.search_budget import MONTHLY_RESERVE
    assert 0 < MONTHLY_RESERVE["brave"] < binding["monthly"] // 2


# ── Regression: the real headers Brave returned on 2026-09-05 ────────────────
# Measured live against the configured key. HTTP 200, request served.
# The first version of reconcile() read the trailing 0 as a ceiling of zero and
# announced "the local ceiling cannot be honoured" about a working key. A module
# whose whole purpose is refusing to invent provider limits invented one.
BRAVE_OBSERVED_20260905 = {
    "x-ratelimit-limit": "50, 0",
    "x-ratelimit-remaining": "49, 0",
    "x-ratelimit-reset": "1, 2175273",
    "x-ratelimit-policy": "50;w=1, 0;w=2592000",
}


def test_real_brave_headers_parse_both_windows():
    cap = parse_provider_capacity("brave", BRAVE_OBSERVED_20260905)
    assert cap.observed is True
    assert cap.windows["per_second"]["limit"] == 50
    assert cap.windows["per_second"]["remaining"] == 49
    # The raw window is preserved verbatim — we do not rewrite what they said.
    assert cap.windows["per_month"]["limit"] == 0


def test_zero_monthly_window_is_not_a_ceiling_of_zero():
    """0 with a live 200 means 'unmetered', not 'you may make no requests'."""
    cap = parse_provider_capacity("brave", BRAVE_OBSERVED_20260905)
    assert cap.monthly_limit() is None
    assert cap.monthly_metered() is False


def test_unmetered_month_does_not_fabricate_a_conflict():
    cap = parse_provider_capacity("brave", BRAVE_OBSERVED_20260905)
    rec = reconcile(cap, BRAVE_LOCAL_COST_POLICY)
    assert rec["conflict"] is None, "a working key must not be reported as over its limit"
    assert rec["binding_ceiling"] == "local_policy"
    assert "not a ceiling of zero" in rec["binding_reason"].lower()


def test_unmetered_is_distinguishable_from_never_observed():
    """Both bind to local policy, but for different reasons, and must say so."""
    observed = reconcile(parse_provider_capacity("brave", BRAVE_OBSERVED_20260905),
                         BRAVE_LOCAL_COST_POLICY)
    never = reconcile(ProviderCapacity(provider="brave"), BRAVE_LOCAL_COST_POLICY)
    assert observed["binding_ceiling"] == never["binding_ceiling"] == "local_policy"
    assert observed["binding_reason"] != never["binding_reason"]
    assert "unobserved" in never["binding_reason"]
    assert "unobserved" not in observed["binding_reason"]


def test_a_real_positive_monthly_limit_still_binds_and_still_conflicts():
    """The zero-guard must not swallow a genuine provider ceiling."""
    cap = parse_provider_capacity("brave", {"x-ratelimit-limit": "50, 500"})
    assert cap.monthly_limit() == 500
    rec = reconcile(cap, BRAVE_LOCAL_COST_POLICY)   # local 850 > provider 500
    assert rec["binding_ceiling"] == "provider"
    assert rec["conflict"] is not None
