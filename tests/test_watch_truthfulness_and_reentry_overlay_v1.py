from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_reentry_classification_is_body_level_and_deep_linkable():
    src = read("apps/command-center-v3/src/components/reentry/ReEntryClassificationOverlay.tsx")
    page = read("apps/command-center-v3/src/pages/ReEntryPageV4.tsx")
    assert "createPortal" in src
    assert "document.body" in src
    assert "searchParams.get('classify')" in src
    assert "reentry:classify-symbol" in src
    assert "stopImmediatePropagation" in src
    assert "<ReEntryClassificationOverlay />" in page


def test_reentry_never_silently_classifies_unresolved_identifiers():
    src = read("apps/command-center-v3/src/components/reentry/ReEntryClassificationOverlay.tsx")
    assert "UNRESOLVED IDENTITY" in src
    assert "resembles a CUSIP/account identifier" in src
    assert "excluded from classification and actionable counts" in src
    assert "disabled={busy || unresolved.length > 0}" in src


def test_empty_classification_fields_are_explicit_not_fabricated():
    src = read("apps/command-center-v3/src/components/reentry/ReEntryClassificationOverlay.tsx")
    assert "No full-fidelity exit row is available" in src
    assert "event-specific fields will not fabricate a transaction" in src
    assert "Watch context unavailable" in src
    assert "UNAVAILABLE" in src


def test_pe_and_related_valuation_are_sourced_and_reused():
    overlay = read("apps/command-center-v3/src/components/reentry/ReEntryClassificationOverlay.tsx")
    watch = read("apps/command-center-v3/src/components/WatchTruthAuditPanel.tsx")
    for token in ("TRAILING P/E", "FORWARD P/E", "PEG", "fundamentals_as_of", "blind_facts"):
        assert token in overlay or token in watch
    assert "P/E is evidence, never an action or quality score" in overlay
    assert "valuation unavailable" in watch
    assert "valuation N/A for fund/ETF" in watch


def test_watch_separates_operator_priority_from_automated_origin():
    src = read("apps/command-center-v3/src/components/WatchTruthAuditPanel.tsx")
    page = read("apps/command-center-v3/src/pages/WatchHub.tsx")
    assert "OPERATOR FAVORITE" in src
    assert "AUTOMATED ·" in src
    assert "a star is not a quality score" in src
    assert "PROMOTE ★" in src
    assert "<WatchTruthAuditPanel />" in page


def test_all_review_lanes_are_explicit_and_deterministic_authority_is_preserved():
    src = read("apps/command-center-v3/src/components/WatchTruthAuditPanel.tsx")
    for token in ("RUN LOCAL", "RUN GROK OAUTH", "RUN CHATGPT OAUTH", "RUN ALL FREE", "PAID EXPERT"):
        assert token in src
    assert "local,grok,chatgpt" in src
    assert "/api/v2/watch/ticket-review/premium/estimate" in src
    assert "/api/v2/watch/ticket-review/premium/run" in src
    assert "Cost preview only" in src
    assert "model agreement cannot overturn a deterministic failure" in src


def test_paid_review_requires_exact_confirmation():
    src = read("apps/command-center-v3/src/components/WatchTruthAuditPanel.tsx")
    backend = read("scripts/premium_ticket_review.py")
    assert "confirmation !== premium.confirm_with" in src
    assert "TYPE EXACTLY" in src
    assert "est_cost_usd" in src
    assert "No paid call was made" in src
    assert "if confirmation != want" in backend


def test_new_surfaces_meet_minimum_label_size():
    import re
    for path in (
        "apps/command-center-v3/src/components/reentry/ReEntryClassificationOverlay.tsx",
        "apps/command-center-v3/src/components/WatchTruthAuditPanel.tsx",
    ):
        src = read(path)
        for match in re.finditer(r"fontSize:\s*([0-9.]+)", src):
            assert float(match.group(1)) >= 10, (path, match.group(0))


def test_no_order_or_approval_path_is_added():
    combined = read("apps/command-center-v3/src/components/reentry/ReEntryClassificationOverlay.tsx") + read("apps/command-center-v3/src/components/WatchTruthAuditPanel.tsx")
    for forbidden in ("/orders/submit", "/broker/submit", "approve-proposal", "request-2fa"):
        assert forbidden not in combined
