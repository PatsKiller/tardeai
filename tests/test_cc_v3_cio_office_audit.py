"""Unit tests for G9 office-home audit selectors/expectations (no live browser)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from cc_v3_cio_office_audit import (  # noqa: E402
    ADVISORY_REQUIRED_PHRASES,
    CIO_ATTENTION_KPI_LABELS,
    MAX_DECISION_CARDS,
    audit_office_sources,
    evaluate_g9_office_audit,
    g9_office_audit_contract,
)


def _good_hub() -> str:
    return (
        'label="Investment decisions"\n'
        'label="Workflow actions"\n'
        'label="Open plans"\n'
        'label="Material Today"\n'
        'help="Cards show at most 5."\n'
        'help="Prospective raise = future trims/exits not yet cash. '
        'Earmarked redeploy already in cash is not new capital."\n'
        '"Earmarked redeploy (already in cash)"\n'
        'data-testid="cio-decision-card"\n'
    )


def _good_advisory() -> str:
    return (
        'label="Current mark"\n'
        'label="Upside vs canonical current"\n'
        'label="Upside vs provider snapshot"\n'
        ' · canonical : · provider snapshot\n'
    )


def test_contract_lists_four_kpi_labels_and_selectors():
    c = g9_office_audit_contract()
    assert tuple(c["kpi_labels"]) == CIO_ATTENTION_KPI_LABELS
    assert c["kpi_labels"] == [
        "Investment decisions",
        "Workflow actions",
        "Open plans",
        "Material Today",
    ]
    assert "Decisions needing you" in c["forbidden_labels"]
    assert c["max_decision_cards"] == 5
    assert c["selectors"]["decision_card"] == '[data-testid="cio-decision-card"]'
    assert c["selectors"]["hub"] == '[data-testid="cio-hub"]'
    assert set(ADVISORY_REQUIRED_PHRASES) <= set(c["advisory_required_phrases"])


def test_good_fixture_passes():
    r = evaluate_g9_office_audit(
        cio_hub_source=_good_hub(),
        advisory_source=_good_advisory(),
        command_center_source="cards = needing[:5]  # cap",
        decision_card_count=3,
    )
    assert r["ok"] is True, r
    assert r["gate"] == "G9_advisory_ui_provenance_live"
    assert r["authority"] == "READ_ONLY_ADVISORY"


def test_legacy_decisions_needing_you_fails():
    r = evaluate_g9_office_audit(
        cio_hub_source=_good_hub() + '\nStat label="Decisions needing you"\n',
        advisory_source=_good_advisory(),
        decision_card_count=1,
    )
    assert r["ok"] is False
    assert any("forbidden_attention_label" in i for i in r["issues"])


def test_missing_kpi_label_fails():
    hub = _good_hub().replace('label="Open plans"', "")
    r = evaluate_g9_office_audit(
        cio_hub_source=hub,
        advisory_source=_good_advisory(),
        decision_card_count=1,
    )
    assert r["ok"] is False
    assert any("missing_kpi_labels" in i and "Open plans" in i for i in r["issues"])


def test_more_than_five_decision_cards_fails():
    r = evaluate_g9_office_audit(
        cio_hub_source=_good_hub(),
        advisory_source=_good_advisory(),
        decision_card_count=6,
    )
    assert r["ok"] is False
    assert any("decision_card_count:6>5" in i for i in r["issues"])
    assert MAX_DECISION_CARDS == 5


def test_missing_current_mark_and_upside_wording_fails():
    r = evaluate_g9_office_audit(
        cio_hub_source=_good_hub(),
        advisory_source='label="Upside vs current"\n',
        decision_card_count=1,
    )
    assert r["ok"] is False
    assert any("missing_advisory_phrases" in i for i in r["issues"])
    assert any("blind_vs_current_label" in i or "missing_advisory" in i for i in r["issues"])


def test_earmarked_cash_called_new_raise_fails():
    hub = (
        _good_hub()
        + "\nEarmarked redeploy is a new raise from settled cash.\n"
    )
    r = evaluate_g9_office_audit(
        cio_hub_source=hub,
        advisory_source=_good_advisory(),
        decision_card_count=1,
    )
    assert r["ok"] is False
    assert any("earmarked_cash_called_new_raise" in i for i in r["issues"])


def test_honest_not_new_capital_copy_is_not_a_false_positive():
    r = evaluate_g9_office_audit(
        cio_hub_source=_good_hub(),
        advisory_source=_good_advisory(),
        decision_card_count=0,
    )
    assert r["ok"] is True, r


def test_audit_office_sources_passes_checked_in_ui():
    """Live product source must already satisfy the G9 office contract."""
    r = audit_office_sources()
    assert r["mode"] == "sources_only"
    assert r["ok"] is True, r
    assert r["source_paths"]["cio_hub_present"] is True
    assert r["source_paths"]["advisory_present"] is True


def test_sources_only_cli_does_not_launch_browser(monkeypatch):
    import cc_v3_cio_office_audit as mod

    called = {"browser": False}

    def _boom():
        called["browser"] = True
        raise AssertionError("browser must not run")

    monkeypatch.setattr(mod, "run_browser_audit", _boom)
    rc = mod.main(["--sources-only", "--json"])
    assert rc == 0
    assert called["browser"] is False
