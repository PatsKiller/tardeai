"""CIOHealthBoundary must actually implement the interface its callers use.

CL-61. Observed 2026-09-12 on the first completed wake-dispatch cycle in four
and a half days:

    [tradeai.cio_run_worker] Health boundary check failed:
    'CIOHealthBoundary' object has no attribute 'current_advisory_state'

cio_run_worker._check_health() called that method unguarded inside a try, so
every call raised, was swallowed, and left `blocked=False`. The boundary had
never gated a single run. Worse, the run store still recorded a `health_checked`
receipt with a freshly minted `health-<uuid>`, naming a health decision that was
never made.

It survived because the only tests covering that path build their own fake
boundaries which DO define the method (tests/test_p26_shadow_autonomy.py). The
suite was green against a duck-type the real class never implemented, which is
why this needs a test against the REAL class, not another fake.
"""

from __future__ import annotations

import pytest

from scripts.lib.cio_health_boundary import (
    ADVISORY_STATE,
    CIOHealthBoundary,
)


def test_real_class_implements_the_interface_callers_use():
    """NEGATIVE CONTROL: AttributeError on the real class before the fix."""
    b = CIOHealthBoundary()
    assert hasattr(b, "current_advisory_state"), (
        "cio_run_worker calls this unguarded; without it every health check "
        "raises and the boundary silently gates nothing"
    )
    assert hasattr(b, "latest_decision_id")


def test_state_is_a_real_advisory_state():
    assert CIOHealthBoundary().current_advisory_state() in ADVISORY_STATE


def test_no_snapshot_is_unknown_not_ready():
    """Fail closed to UNKNOWN. A boundary with no evidence must not say READY."""
    assert CIOHealthBoundary().current_advisory_state() == "UNKNOWN"


def test_decision_id_is_none_before_any_evaluation():
    """None is honest. The worker used to substitute a minted id here."""
    assert CIOHealthBoundary().latest_decision_id() is None


def test_decision_id_names_the_evaluation_that_produced_the_state():
    """The id must identify the actual decision, not an unrelated one."""
    b = CIOHealthBoundary()
    b.current_advisory_state()
    first = b.latest_decision_id()
    assert first is not None
    assert b._last_decision.state == "UNKNOWN"

    b.current_advisory_state()
    assert b.latest_decision_id() != first, "each evaluation is its own decision"


def test_default_domains_are_empty_not_all_domains():
    """Defaulting to every CIO domain would turn one bad source into a global
    block on all runs. That is a policy change, not a bug fix."""
    b = CIOHealthBoundary()
    b.current_advisory_state()
    assert b._last_decision.required_domains == []


def test_declared_domains_are_carried_into_the_decision():
    b = CIOHealthBoundary()
    b.current_advisory_state(required_domains=["portfolio"])
    assert b._last_decision.required_domains == ["portfolio"]


def test_unknown_domain_still_rejected():
    """evaluate() validates domains; the wrapper must not bypass that."""
    with pytest.raises(ValueError):
        CIOHealthBoundary().current_advisory_state(required_domains=["not_a_domain"])
