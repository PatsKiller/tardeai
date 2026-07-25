from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANALYST = (ROOT / "apps/command-center-v3/src/components/ProAnalystPill.tsx").read_text()
DECISION = (ROOT / "apps/command-center-v3/src/components/DecisionPacketBand.tsx").read_text()
SELECTOR = (ROOT / "apps/command-center-v3/src/lib/watchPacketQuality.ts").read_text()


def test_analyst_staleness_is_explicitly_scoped_to_street_data():
    assert "STREET DATA &gt;7D" in ANALYST
    assert "Street consensus data is older than 7 days" in ANALYST
    assert "stale &gt;7d ⚠" not in ANALYST
    assert "never affects READY/WAIT, quality admission" in ANALYST


def test_non_primary_family_cannot_compete_with_sovereign_ready_word():
    assert "OWNERSHIP ELIGIBLE" in DECISION
    assert "MECHANICS VALID" in DECISION
    assert "One operator state governs" in DECISION
    assert "Non-primary horizons are evidence, not simultaneous actions" in DECISION
    assert "preferred && operatorState === 'READY'" in DECISION


def test_ticket_panel_exposes_quality_and_honest_review_states():
    for marker in (
        "DETERMINISTIC_REVIEW_REQUIRED",
        "DETERMINISTIC_PASS_REVIEW_NOT_RUN",
        "DETERMINISTIC_NOT_RUN",
        "QUALITY_NOT_ASSESSED",
        "Quality",
        "quality_admission",
        "premium_recommended",
        "RECOMMENDED · NOT RUN",
        "Fix deterministic gate first",
        "watch-quality-governance-v1",
    ):
        assert marker in DECISION


def test_free_review_is_disabled_before_deterministic_and_quality_gates():
    assert "mayRunReview" in DECISION
    assert "qualityAdmitted" in DECISION
    assert "disabled={busy || !mayRunReview}" in DECISION
    assert "Complete deterministic validation and quality admission first" in DECISION


def test_ui_scans_retained_family_validations_after_current_mechanics_are_stripped():
    assert "selectPacketValidation" in DECISION
    assert "selected.source" in DECISION
    assert "plan_families" in SELECTOR
    assert "structures[${index}]" in SELECTOR
    assert "VALIDATION_SEVERITY" in SELECTOR
    assert "QUALITY_SEVERITY" in SELECTOR
    assert "current_actionable_plan" in SELECTOR
