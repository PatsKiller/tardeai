from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "apps" / "command-center-v3" / "src" / "hooks" / "useReEntryExitEvidence.ts"
WATCH = ROOT / "apps" / "command-center-v3" / "src" / "components" / "WatchTruthAuditPanel.tsx"
REENTRY_PANEL = ROOT / "apps" / "command-center-v3" / "src" / "components" / "reentry" / "ReEntryEvidenceContractPanel.tsx"
REENTRY_CURRENT = ROOT / "apps" / "command-center-v3" / "src" / "components" / "reentry" / "ReEntryCurrentIntelligence.tsx"
REENTRY_PAGE = ROOT / "apps" / "command-center-v3" / "src" / "pages" / "ReEntryPageV4.tsx"


def test_reentry_evidence_contract_covers_real_broker_aliases() -> None:
    source = EVIDENCE.read_text(encoding="utf-8")
    assert "reentry-evidence-v3" in source
    for field in [
        "filled_quantity",
        "shares_closed",
        "quantity_sold",
        "execution_price",
        "avg_fill_price",
        "net_amount_usd",
        "settlement_amount",
        "transaction_id",
        "execution_id",
        "activity_id",
        "settlement_date",
    ]:
        assert field in source


def test_reentry_reconciler_normalizes_account_aliases_and_preserves_truth() -> None:
    source = EVIDENCE.read_text(encoding="utf-8")
    assert "function accountIdentity" in source
    assert "rolloverira" in source
    assert "function accountsCompatible" in source
    assert "sameSymbolDayAccount" in source
    assert "no compatible event or aggregate supplied" in source
    assert "price = proceeds ÷ shares" in source
    assert "shares = proceeds ÷ price" in source
    assert "proceeds = shares × price" in source


def test_reentry_ui_exposes_and_mounts_contract_source_coverage() -> None:
    panel = REENTRY_PANEL.read_text(encoding="utf-8")
    page = REENTRY_PAGE.read_text(encoding="utf-8")
    current = REENTRY_CURRENT.read_text(encoding="utf-8")
    assert "DATA CONTRACT {evidence.contractVersion}" in panel
    assert "quantity-bearing source rows" in panel
    assert "sourceFieldCoverage" in panel
    assert "SHOW SOURCE MATRIX" in panel
    assert "ReEntryEvidenceContractPanel" in page
    assert "OPEN EVIDENCE" in current
    assert "FIELD-BY-FIELD AUDIT" in current


def test_watch_queue_is_explicit_keyboard_accessible_and_paginated() -> None:
    source = WATCH.read_text(encoding="utf-8")
    assert "watch-operator-v2" in source
    assert "Watch Operator Queue" in source
    assert "Click a row or OPEN REVIEW" in source
    assert 'role="button"' in source
    assert "event.key === 'Enter' || event.key === ' '" in source
    assert "PREVIOUS" in source and "NEXT" in source
    assert "PAGE_SIZE = 20" in source


def test_watch_queue_has_truthful_state_filters_and_operator_actions() -> None:
    source = WATCH.read_text(encoding="utf-8")
    for value in ["needs_review", "deterministic_fail", "data_gaps", "actionable"]:
        assert value in source
    for action in [
        "RUN LOCAL",
        "RUN GROK OAUTH",
        "RUN CHATGPT OAUTH",
        "RUN ALL FREE",
        "CLASSIFY RE-ENTRY",
        "OPEN ROTATION",
        "PAID EXPERT…",
    ]:
        assert action in source
    assert "Deterministic arithmetic, freshness, validation and release remain authoritative" in source
