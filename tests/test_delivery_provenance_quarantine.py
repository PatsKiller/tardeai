"""Lane E — provenance quarantine (not channel-wide)."""
from __future__ import annotations

from scripts.lib.delivery_provenance_quarantine import (
    detect_synthetic_provider_ids,
    exclude_quarantined,
    is_quarantined_delivery,
    maturity_sql_exclusion_predicate,
)


WAMID = {
    "delivery_id": "dlv_01a06fc8-1567-7034-bdfc-ba46bf3dea8b",
    "provider_message_id": "wamid.test_1",
    "row_sha256": "006cc07c2a37a4ab997e32fc805dd181acedbdeee32e6dda3f7859b551945ce4",
    "channel": "whatsapp_meta",
}


def test_exact_delivery_quarantined():
    ok, entry = is_quarantined_delivery(
        delivery_id=WAMID["delivery_id"],
        row_sha256=WAMID["row_sha256"],
        provider_message_id=WAMID["provider_message_id"],
    )
    assert ok is True
    assert entry["provenance_class"] == "SYNTHETIC_TEST_PROVIDER_ID"
    assert entry["rewrite_or_delete"] is False


def test_wrong_hash_does_not_quarantine():
    ok, _ = is_quarantined_delivery(
        delivery_id=WAMID["delivery_id"],
        row_sha256="0" * 64,
        provider_message_id=WAMID["provider_message_id"],
    )
    assert ok is False


def test_exclude_does_not_drop_whole_channel():
    other_wa = {
        "delivery_id": "dlv_real_whatsapp_001",
        "provider_message_id": "wamid.REAL_PROVIDER_ID",
        "row_sha256": "aa" * 32,
        "channel": "whatsapp_meta",
    }
    tg = {
        "delivery_id": "dlv_tg_001",
        "provider_message_id": "12345",
        "row_sha256": "bb" * 32,
        "channel": "telegram",
    }
    kept = exclude_quarantined([WAMID, other_wa, tg])
    ids = {r["delivery_id"] for r in kept}
    assert WAMID["delivery_id"] not in ids
    assert other_wa["delivery_id"] in ids
    assert tg["delivery_id"] in ids
    # Prove we did not channel-ban whatsapp_meta
    assert any(r["channel"] == "whatsapp_meta" for r in kept)


def test_contamination_detector_flags_synthetic():
    hits = detect_synthetic_provider_ids([WAMID, {"delivery_id": "x", "provider_message_id": "ok"}])
    assert len(hits) == 1
    assert hits[0]["already_quarantined"] is True


def test_sql_predicate_is_id_based_not_channel():
    pred = maturity_sql_exclusion_predicate("d")
    assert "whatsapp_meta" not in pred
    assert WAMID["delivery_id"] in pred
    assert "NOT IN" in pred
