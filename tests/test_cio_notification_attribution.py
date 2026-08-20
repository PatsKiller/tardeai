"""P0.4 — CIO notification attribution (BOOK / NON_TICKER / AVOID demotion)."""
from __future__ import annotations

from scripts.lib.cio_product_reassessment import (
    diff_products,
    material_notification_items,
    notification_attribution_symbol,
    should_enqueue_product_notification,
)


def _reentry(names: list[tuple[str, str]]) -> dict:
    return {
        "reentry_book": {
            "names": [{"symbol": s, "status": st} for s, st in names],
        },
        "opportunity_book": {"top": []},
        "action_book": {},
        "temperament": {},
        "as_of": "2026-08-20T04:00:00+00:00",
    }


def test_book_label_when_trigger_row_unchanged():
    prior = _reentry([("AMD", "NEAR"), ("SCHD", "WAIT")])
    new = _reentry([("AMD", "AVOID"), ("SCHD", "WAIT")])  # SCHD unchanged
    changed = diff_products(prior, new)
    assert notification_attribution_symbol(changed, "SCHD") == "BOOK"
    assert notification_attribution_symbol(changed, "AMD") == "AMD"


def test_non_ticker_filtered_from_material_lines():
    prior = _reentry([("HEALTH", "WAIT"), ("AMD", "NEAR")])
    new = _reentry([("AMD", "AVOID")])  # HEALTH removed
    changed = diff_products(prior, new)
    symbols = {str(i.get("symbol") or "").upper() for i in changed["items"]}
    assert "HEALTH" not in symbols
    material_syms = {str(i.get("symbol") or "").upper() for i in material_notification_items(changed)}
    assert "HEALTH" not in material_syms
    assert "AMD" in material_syms


def test_reentry_added_to_avoid_demoted():
    prior = _reentry([("AMD", "NEAR")])
    new = _reentry([("AMD", "NEAR"), ("ACHV", "AVOID")])
    changed = diff_products(prior, new)
    added = [i for i in changed["items"] if i.get("kind") == "reentry_added" and i.get("symbol") == "ACHV"]
    assert added and added[0]["material"] is False
    assert added[0].get("demoted_reason") == "reentry_added_to_AVOID"
    # Only demoted noise → do not page
    assert should_enqueue_product_notification(changed) is False
    assert notification_attribution_symbol(changed, "SCHD") == "BOOK"


def test_material_downgrade_still_pages_with_book_label():
    prior = _reentry([("AMD", "NEAR"), ("SCHD", "WAIT")])
    new = _reentry([
        ("AMD", "AVOID"),
        ("SCHD", "WAIT"),
        ("ACHV", "AVOID"),  # demoted
        ("HEALTH", "WAIT"),  # filtered if removed later
    ])
    # Also remove HEALTH from prior-only via separate prior
    prior2 = _reentry([("AMD", "NEAR"), ("SCHD", "WAIT"), ("HEALTH", "WAIT")])
    changed = diff_products(prior2, new)
    assert should_enqueue_product_notification(changed) is True
    assert notification_attribution_symbol(changed, "SCHD") == "BOOK"
    body_items = material_notification_items(changed)
    assert all(str(i.get("symbol") or "").upper() != "HEALTH" for i in body_items)
    assert all(not (i.get("kind") == "reentry_added" and str(i.get("to") or "").upper() == "AVOID")
               for i in body_items)
