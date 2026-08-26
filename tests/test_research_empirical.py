"""R8 empirical factor / strategy family — fixture-first, no winner-only."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.research_governance import acceptance  # noqa: E402
from scripts.lib.research_governance.empirical import (  # noqa: E402
    AUTHORITY,
    FAMILY_DEFINITION_HASH,
    MAX_INFLUENCE_PCT,
    N_VARIANTS,
    as_research_evidence,
    attempt_winner_only,
    run_family,
    variant_returns,
)
from scripts.lib.research_governance.enums import (  # noqa: E402
    EvidenceGrade,
    EvidenceType,
    InfluenceClass,
    ResearchStatus,
)
from scripts.lib.research_governance.r8_acceptance import check_empirical_family  # noqa: E402
from scripts.lib.research_governance.trial_registry import TrialRegistry  # noqa: E402


def test_twelve_variants_recorded_including_losers():
    pack = run_family()
    trials = pack["trials"]
    assert len(trials) == 12
    assert {t["month"] for t in trials} == set(range(1, 13))
    losers = [t for t in trials if t["mean"] is not None and t["mean"] < 0]
    assert losers, "negative-mean losers must be recorded, not dropped"
    assert all(t["n"] and t["n"] > 1 for t in trials)


def test_family_complete():
    pack = run_family()
    assert pack["family_complete"] is True
    assert pack["n_variants"] == N_VARIANTS
    assert pack["whole_family"] is True


def test_winner_only_false_selected_winner_none():
    pack = run_family()
    assert pack["winner_only"] is False
    assert pack["selected_winner"] is None


def test_attempt_winner_without_complete_family_fails():
    pack = run_family()
    incomplete = dict(pack, family_complete=False, trials=pack["trials"][:3])
    with pytest.raises(ValueError, match="incomplete family"):
        attempt_winner_only(incomplete)
    with pytest.raises(ValueError):
        attempt_winner_only(pack)
    assert pack["selected_winner"] is None


def test_authority_no_trim_no_sell():
    pack = run_family()
    assert pack["authority"] == AUTHORITY
    assert pack["standalone_sell"] is False
    assert pack["creates_trim"] is False
    assert pack["max_influence_pct"] <= MAX_INFLUENCE_PCT
    assert pack["influence_class"] == InfluenceClass.CONTEXT_MODIFIER.value
    assert pack["oos_claimed"] is False


def test_variant_returns_equal_length_complete_years():
    lengths = [len(variant_returns(m)) for m in range(1, 13)]
    assert len(set(lengths)) == 1
    assert lengths[0] >= 8


def test_confirmatory_requires_family_definition_hash():
    with pytest.raises(ValueError, match="family_definition_hash"):
        run_family(confirmatory=True)
    pack = run_family(confirmatory=True, family_definition_hash=FAMILY_DEFINITION_HASH)
    assert pack["family_complete"] is True
    assert pack["selected_winner"] is None
    assert pack["oos_claimed"] is False


def test_unplanned_trial_rejected():
    reg = TrialRegistry()
    reg.freeze_family(
        "r8-unplanned",
        "h",
        protocol_hash="ph",
        planned_trials=[("month_01", "cfg1")],
    )
    with pytest.raises(ValueError, match="unplanned"):
        reg.record_trial("r8-unplanned", "month_99", config_hash="x",
                         result_payload={"month": 99, "n": 0, "mean": 0})


def test_as_research_evidence_grade_c_context_only():
    pack = run_family()
    ev = as_research_evidence(pack)
    assert ev
    assert ev[0].evidence_type == EvidenceType.EMPIRICAL_STRATEGY
    for item in ev:
        assert item.evidence_grade in {EvidenceGrade.C, EvidenceGrade.D}
        assert item.evidence_grade not in {EvidenceGrade.A, EvidenceGrade.B}
        assert item.influence_class == InfluenceClass.CONTEXT_MODIFIER
        assert item.research_status != ResearchStatus.OOS_SUPPORTED
        assert item.role_in_decision == "risk_modifier_or_context"


def test_r8a1_check_passes():
    state, detail = check_empirical_family()
    assert state == "PASS", detail


def test_r8_empirical_profile_includes_r8a1():
    rep = acceptance.run_acceptance("R8_empirical")
    assert "R8A-1" in acceptance.PHASE_PROFILES["R8_empirical"]["required_runtime"]
    assert rep["results"].get("R8A-1") == "PASS", rep
