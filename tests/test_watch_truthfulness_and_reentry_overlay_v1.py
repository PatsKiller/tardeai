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
    """An identifier that is not a resolvable ticker must be flagged and excluded
    from actionable classification — never silently classified. Re-pinned
    2026-07-26 to the production overlay's real unresolved-identity guard."""
    src = read("apps/command-center-v3/src/components/reentry/ReEntryClassificationOverlay.tsx")
    assert "UNRESOLVED IDENTITY" in src
    # a non-ticker identifier is detected, not silently accepted
    assert "tickerLike" in src and "!tickerLike" in src
    assert "is not treated as an actionable ticker until symbol resolution is explicit" in src
    # save is hard-blocked while any unresolved identifier is present
    assert "disabled={busy || unresolved.length > 0}" in src
    assert "if (unresolved.length) return" in src


def test_empty_classification_fields_are_explicit_not_fabricated():
    """Missing exit evidence is stated explicitly; the persistent mandate may still
    save, but no transaction is invented. Re-pinned 2026-07-26 to the production
    overlay's real no-fabrication language."""
    src = read("apps/command-center-v3/src/components/reentry/ReEntryClassificationOverlay.tsx")
    assert "No event-level exit evidence is available" in src
    assert "no transaction will be fabricated" in src
    # event fields stay unavailable until real broker/journal evidence exists
    assert "Unavailable until broker/journal evidence exists" in src
    # source coverage marks each field available / unavailable / missing explicitly
    assert "unavailable" in src and "missing" in src


def test_pe_and_related_valuation_are_sourced_and_reused():
    """Valuation ratios are sourced from stored enrichment / blind facts and reused
    across surfaces, labelled as evidence — never an action or quality score.
    Re-pinned 2026-07-26 to the production overlay/panel valuation contract."""
    overlay = read("apps/command-center-v3/src/components/reentry/ReEntryClassificationOverlay.tsx")
    watch = read("apps/command-center-v3/src/components/WatchTruthAuditPanel.tsx")
    for token in ("TRAILING P/E", "FORWARD P/E", "PEG", "fundamentals_as_of", "blind_facts"):
        assert token in overlay or token in watch
    # valuation is labelled evidence, never an action or quality score
    assert "Valuation is evidence, not an action or quality score" in overlay
    # sourced from stored enrichment / blind facts and reused across surfaces
    assert "stored enrichment / blind facts" in overlay
    # funds/ETFs are legitimately N/A, not a false valuation gap
    assert "notApplicable" in overlay and "valuation unavailable" in watch


def test_watch_separates_operator_priority_from_automated_origin():
    """A starred symbol is an operator favorite (priority); everything else carries
    its automated origin. Priority (the star) is a separate axis from ticket/quality
    state. Re-pinned 2026-07-26 to the production Watch Operator Queue."""
    src = read("apps/command-center-v3/src/components/WatchTruthAuditPanel.tsx")
    page = read("apps/command-center-v3/src/pages/WatchHub.tsx")
    # operator favorite vs automated origin are distinct labels
    assert "Operator favorite" in src and "'Automated'" in src
    assert "★ Favorites" in src and "Automated ${automated.length}" in src
    # the star (operator priority) is promoted/unstarred, separate from origin
    assert "PROMOTE ★" in src and "originLabel" in src
    # ticket/quality state is a separate axis, not conflated with the star
    assert "DETERMINISTIC" in src and "RECONCILED" in src
    assert "<WatchTruthAuditPanel />" in page


def test_all_review_lanes_are_explicit_and_deterministic_authority_is_preserved():
    """Every free and paid review lane is explicit, the paid lane previews cost and
    demands an exact typed confirmation, and deterministic validation stays
    authoritative over any model review. Re-pinned 2026-07-26 to the production
    panel's real review lanes and authority language."""
    src = read("apps/command-center-v3/src/components/WatchTruthAuditPanel.tsx")
    for token in ("RUN LOCAL", "RUN GROK OAUTH", "RUN CHATGPT OAUTH", "RUN ALL FREE", "PAID EXPERT"):
        assert token in src
    assert "local,grok,chatgpt" in src
    assert "/api/v2/watch/ticket-review/premium/estimate" in src
    assert "/api/v2/watch/ticket-review/premium/run" in src
    # the paid lane previews cost and requires an exact typed confirmation before spend
    assert "review cost and type the exact confirmation" in src
    assert "est_cost_usd" in src and "confirmation !== premium.confirm_with" in src
    # deterministic validation remains authoritative over any model agreement
    assert "Deterministic validation remains authoritative" in src
    assert "validation and release remain authoritative" in src


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
