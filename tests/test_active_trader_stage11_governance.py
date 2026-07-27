"""Stage 11 tests — journal/replay catalog, Darwin/Hermes governance, controller."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from active_trader.governance import (  # noqa: E402
    BITWARDEN_REGISTRY, ControllerState, DarwinProposal, HERMES_TRANSITIONS,
    HermesGovernanceError, JOURNAL_EVENT_CATALOG, OvernightController, ReplayIndexEntry,
    ReviewState, SecretRegistryEntry, hermes_llm_allowed, hermes_transition,
    is_catalog_event,
)


# ---- journal / replay
def test_catalog_and_replay_reference_only():
    assert is_catalog_event("prime_evaluated") and not is_catalog_event("place_order")
    assert len(JOURNAL_EVENT_CATALOG) >= 20
    e = ReplayIndexEntry("s1", "TESTA", "dec-1", None, "SIMULATION", "HEALTHY", "replay://seg-1")
    assert e.replay_segment_ref.startswith("replay://")
    with pytest.raises(ValueError, match="replay://"):
        ReplayIndexEntry("s1", "TESTA", None, None, "LAB", "HEALTHY", "raw-inlined-data")


# ---- Darwin proposal-only
def good_proposal(**over):
    base = dict(proposal_id="p1", kind="threshold", statement="raise rvol gate",
                evidence_refs=("case:1", "case:2"), sample_size=120, period="2026-07",
                cohort={"float": "<20M"}, confounders=("regime",),
                replay_or_simulation_ref="sim://run-1", rollback_plan="revert threshold",
                expiry="2026-09-01")
    base.update(over)
    return DarwinProposal(**base)


def test_darwin_requires_full_evidence_and_never_applies():
    p = good_proposal()
    assert p.applies_directly() is False and p.review_state is ReviewState.DRAFT
    with pytest.raises(ValueError, match="evidence"):
        good_proposal(evidence_refs=())
    with pytest.raises(ValueError, match="sample size"):
        good_proposal(sample_size=0)
    with pytest.raises(ValueError, match="rollback"):
        good_proposal(rollback_plan="")
    with pytest.raises(ValueError, match="confounders"):
        good_proposal(confounders=())
    with pytest.raises(ValueError, match="kind"):
        good_proposal(kind="deploy_now")


# ---- Hermes governance
def test_hermes_transitions_and_no_auto_activation():
    s = ReviewState.DRAFT
    for nxt in (ReviewState.EVIDENCE_PENDING, ReviewState.SIMULATION_PENDING,
                ReviewState.ARCHITECT_REVIEW_PENDING, ReviewState.OPERATOR_REVIEW_PENDING,
                ReviewState.APPROVED_INACTIVE):
        s = hermes_transition(s, nxt)
    assert s is ReviewState.APPROVED_INACTIVE
    # approved is terminal + INACTIVE — cannot auto-activate to anything
    assert HERMES_TRANSITIONS[ReviewState.APPROVED_INACTIVE] == set()
    with pytest.raises(HermesGovernanceError):
        hermes_transition(ReviewState.DRAFT, ReviewState.APPROVED_INACTIVE)  # skip review


def test_hermes_llm_boundaries():
    for ok in ("summarize", "draft", "compare", "cluster", "explain"):
        assert hermes_llm_allowed(ok)
    for bad in ("authorize", "trade", "change_risk", "merge", "deploy", "activate",
                "place_order", "unlock"):
        assert not hermes_llm_allowed(bad)


# ---- Bitwarden registry (metadata only)
def test_bitwarden_registry_metadata_only():
    for e in BITWARDEN_REGISTRY:
        assert len(e.project_id_suffix) <= 12         # suffix only, never full id/value
        assert isinstance(e.required, bool)
    names = {e.secret_name for e in BITWARDEN_REGISTRY}
    assert "MOOMOO_DATA_LOGIN_PASSWORD" in names
    # no forbidden trade-unlock secret in the registry
    assert not any("TRADE_UNLOCK" in n or "LIVE_ORDER" in n for n in names)
    with pytest.raises(ValueError, match="SUFFIX"):
        SecretRegistryEntry("X", "this-is-a-full-project-id-not-suffix", True)


# ---- overnight controller (disabled by default, fail-stop)
def test_controller_disabled_by_default():
    c = OvernightController()
    assert c.state is ControllerState.DISABLED
    assert c.run_stage(lambda: True, stage_name="x") is ControllerState.DISABLED  # does nothing


def test_controller_fail_stop_and_prohibitions():
    c = OvernightController(enabled=True)
    assert c.run_stage(lambda: True, stage_name="ok") is ControllerState.STAGE_GREEN
    def boom():
        raise RuntimeError("stage failed")
    assert c.run_stage(boom, stage_name="bad") is ControllerState.FAILED  # fail-stop
    for prohibited in ("auto_merge", "activate_live_flag", "submit_broker_order", "retry_moomoo_login"):
        with pytest.raises(HermesGovernanceError):
            getattr(c, prohibited)()


def test_no_broker_or_activation_symbols_in_module():
    import active_trader.governance as g
    src = Path(g.__file__).read_text()
    # the module NAMES prohibitions (to forbid them) but must not call broker/network APIs
    for banned in ("requests.get", "requests.post", "OpenQuoteContext(", "place_order("):
        assert banned not in src
