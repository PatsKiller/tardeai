"""Wave 3C — delivery receipts, lesson binding, the spine, 1-hop, EDGAR proof.

The pins matter most: 3C records that decisions were made and that nothing was
sent. If any of that machinery could send, the record would be worthless.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import cio_delivery_receipt as receipt
from scripts.lib import cio_lesson_bind as lesson
from scripts.lib.canonical_store_registry import (
    CANONICAL_ID_FIELDS, STORES, stores_minting,
)
from scripts.lib.cio_edgar_proof import MAX_FETCHES, build_proof, resolve_issuer
from scripts.lib.cio_graph_impact_held import build as graph_build

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)

WAVE3C_MODULES = [
    "scripts/lib/cio_delivery_receipt.py",
    "scripts/lib/cio_lesson_bind.py",
    "scripts/lib/cio_graph_impact_held.py",
]


def _code(rel: str) -> str:
    txt = (REPO / rel).read_text(encoding="utf-8", errors="replace")
    return re.sub(r"#.*", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", txt))


# ==================================================================== PINS

def test_pin_no_send_call_site_anywhere_in_3c():
    for rel in WAVE3C_MODULES + ["scripts/lib/cio_edgar_proof.py"]:
        code = _code(rel)
        for bad in ("send_cio_message", "sendMessage", "api.telegram.org",
                    "RealTelegramAdapter", "cio_telegram_transport", "whatsapp"):
            assert bad not in code, (rel, bad)


def test_pin_mbi_zero_and_rotate_absent():
    for rel in WAVE3C_MODULES:
        code = (REPO / rel).read_text(encoding="utf-8")
        assert "ROTATE" not in code, rel
    for mod in (receipt, lesson):
        assert getattr(mod, "MBI", None) == 0


def test_pin_would_send_is_a_constant_not_a_computation():
    """`would_send` must never be derived from state that could flip it."""
    code = _code("scripts/lib/cio_delivery_receipt.py")
    assert '"would_send": False' in code
    assert "would_send\": True" not in code


def test_pin_receipt_never_reports_a_send():
    for decision in ("SUPPRESSED", "DIGEST", "COMMAND_CENTER_ONLY", "IMMEDIATE"):
        r = receipt.build({"notification_id": "n1", "decision": decision},
                          now=NOW)
        assert r["would_send"] is False
        assert receipt.validate(r) == []


def test_pin_edgar_fetch_is_capped_at_one_and_off_by_default():
    assert MAX_FETCHES == 1
    p = build_proof("V", repo_root=REPO)          # fetch defaults to False
    assert p["fetches_performed"] == 0
    assert p["status"] == "RESOLVED_NOT_FETCHED"


# ======================================================= DeliveryReceipt

def test_channel_mapping_is_explicit():
    m = {d: receipt.build({"notification_id": "n", "decision": d},
                          now=NOW)["would_channel"]
         for d in ("SUPPRESSED", "DIGEST", "COMMAND_CENTER_ONLY", "IMMEDIATE")}
    assert m == {"SUPPRESSED": "none", "DIGEST": "digest",
                 "COMMAND_CENTER_ONLY": "cc", "IMMEDIATE": "telegram"}


def test_suppressed_maps_to_none_not_a_silent_channel():
    """A suppressed decision has no destination, not a quiet one."""
    r = receipt.build({"notification_id": "n", "decision": "SUPPRESSED"}, now=NOW)
    assert r["would_channel"] == "none"


def test_unknown_decision_raises():
    with pytest.raises(ValueError):
        receipt.build({"notification_id": "n", "decision": "SHOUT"}, now=NOW)


def test_dedupe_prevents_a_second_receipt(tmp_path):
    r = receipt.build({"notification_id": "n1", "decision": "SUPPRESSED"}, now=NOW)
    assert receipt.persist(tmp_path, r)["wrote"] is True
    again = receipt.persist(tmp_path, r)
    assert again["wrote"] is False and again["duplicate"] is True


def test_receipt_with_would_send_true_is_refused(tmp_path):
    r = receipt.build({"notification_id": "n1", "decision": "DIGEST"}, now=NOW)
    r["would_send"] = True
    assert "would_send_must_be_false" in receipt.validate(r)
    assert receipt.persist(tmp_path, r)["wrote"] is False


# =========================================================== lesson bind

def test_bound_checkpoint_mints_a_lesson():
    b = lesson.bind({"checkpoint_id": "c1", "plan_id": "p1",
                     "plan_binding": "bound", "horizon": "30d"}, now=NOW)
    assert b["bound"] is True
    assert b["lesson_id"].startswith("lsn_")
    assert b["review_flag"] == "REVIEW_READY"
    assert lesson.validate(b) == []


def test_unbound_checkpoint_does_not_mint_a_lesson():
    """The rule the brief names explicitly."""
    for cp in ({"checkpoint_id": "c2", "plan_id": None,
                "plan_binding": "unbound_cash"},
               {"checkpoint_id": "c3", "plan_id": "", "plan_binding": "unbound"},
               {"checkpoint_id": "c4"}):
        b = lesson.bind(cp, now=NOW)
        assert b["bound"] is False
        assert b["lesson_id"] is None
        assert b["skip_reason"] == "checkpoint_not_plan_bound"
        assert lesson.validate(b) == []


def test_hypothesis_is_support_only_and_never_a_commitment():
    b = lesson.bind({"checkpoint_id": "c1", "plan_id": "p1",
                     "plan_binding": "bound"}, now=NOW)
    h = b["hypothesis"]
    assert h["support_only"] is True
    assert h["requires_human_review"] is True
    assert h["status"] not in lesson.FORBIDDEN_STATUSES
    assert h["status"] == "REVIEW_READY"


def test_a_commitment_status_is_rejected_by_validate():
    b = lesson.bind({"checkpoint_id": "c1", "plan_id": "p1",
                     "plan_binding": "bound"}, now=NOW)
    b["hypothesis"]["status"] = "AGENT_COMMITMENT"
    assert "forbidden_status" in lesson.validate(b)


def test_lesson_carries_no_imperative():
    from scripts.lib.execution_language import find_imperative

    b = lesson.bind({"checkpoint_id": "c1", "plan_id": "p1",
                     "plan_binding": "bound", "horizon": "30d"}, now=NOW)
    assert not find_imperative(b["hypothesis"]["claim"])


def test_lesson_id_is_deterministic():
    a = lesson.bind({"checkpoint_id": "c1", "plan_id": "p1",
                     "plan_binding": "bound"}, now=NOW)
    b = lesson.bind({"checkpoint_id": "c1", "plan_id": "p1",
                     "plan_binding": "bound"}, now=NOW)
    assert a["lesson_id"] == b["lesson_id"]


def test_skip_records_are_persisted_too(tmp_path):
    """"We looked and found nothing to bind" is evidence, not noise."""
    u = lesson.bind({"checkpoint_id": "c9", "plan_id": None,
                     "plan_binding": "unbound_cash"}, now=NOW)
    assert lesson.persist(tmp_path, u)["wrote"] is True


# ================================================== CanonicalStoreRegistry

@pytest.mark.parametrize("store_id,schema", [
    ("cio.specialist_artifacts", "SpecialistArtifact@v1-lite"),
    ("cio.notification_policy", "NotificationPolicy@v1"),
    ("cio.delivery_receipts", "DeliveryReceipt@v1"),
    ("cio.lesson_binds", "LessonBind@v1"),
])
def test_every_new_write_is_registered(store_id, schema):
    assert store_id in STORES
    assert STORES[store_id]["schema"] == schema
    assert STORES[store_id]["append_only"] is True
    assert STORES[store_id]["id_fields"]


def test_every_minted_id_has_a_registered_home():
    """An id nothing registers is either unregistered or a second spine."""
    for field in ("artifact_id", "notification_id", "dedupe_key", "lesson_id",
                  "checkpoint_id"):
        assert stores_minting(field), f"{field} has no registered store"


def test_id_namespace_is_declared_in_one_place():
    for field in ("workflow_id", "event_id", "research_id", "artifact_id",
                  "generation_id", "notification_id", "checkpoint_id",
                  "outcome_id", "lesson_id"):
        assert field in CANONICAL_ID_FIELDS


def test_registry_paths_match_the_writers():
    assert receipt.STORE_REL == STORES["cio.delivery_receipts"]["path"]
    assert lesson.STORE_REL == STORES["cio.lesson_binds"]["path"]


def test_no_second_spine_was_created():
    """Item 3 says point at existing stores, not mint a second index.

    Code only. Other modules legitimately *reference* the spine in prose —
    identity_registry's docstring explains that `identity.registry` is declared
    in CanonicalStoreRegistry@v1, which makes it a consumer, not a rival.
    """
    others = [p for p in (REPO / "scripts" / "lib").glob("*registry*.py")
              if p.name != "canonical_store_registry.py"]
    for p in others:
        code = _code(str(p.relative_to(REPO)))
        assert 'SCHEMA = "CanonicalStoreRegistry@v1"' not in code, p.name
        assert "STORES: dict" not in code, p.name


# ============================================================ graph 1-hop

def _book():
    return {"resolved_sector_contributors": {
        "Industrials": [{"symbol": "XLI", "market_value": 36268},
                        {"symbol": "XAR", "market_value": 26770}],
        "Financials": [{"symbol": "V", "market_value": 77122}]}}


def test_cash_dust_and_test_are_skipped_with_a_reason():
    r = graph_build(symbols=["XLI", "CASH", "NOC", "TEST1", "12507E201"],
                    holdings=_book(), held={"XLI", "XAR", "V", "NOC"},
                    dust={"NOC"})
    reasons = {s["symbol"]: s["skip_reason"] for s in r["skipped"]}
    assert reasons["CASH"] == "cash_or_non_entity"
    assert reasons["NOC"] == "dust_residual"
    assert reasons["TEST1"] == "test_symbol"
    assert reasons["12507E201"] == "not_a_ticker"


def test_skips_are_explicit_not_empty_neighbour_lists():
    """An empty list and "not eligible" must not look identical."""
    r = graph_build(symbols=["CASH"], holdings=_book(), held={"XLI"})
    assert r["impacts"] == []
    assert r["skipped"][0]["graph_impact"] is None


def test_held_non_dust_gets_one_hop():
    r = graph_build(symbols=["XLI"], holdings=_book(),
                    held={"XLI", "XAR"}, dust=set())
    assert r["counts"]["with_impact"] == 1
    assert r["impacts"][0]["hop"] == 1


def test_graph_mints_no_watch_identity():
    r = graph_build(symbols=["XLI"], holdings=_book(), held={"XLI"})
    assert r["mints_watch_identity"] is False
    assert r["memory_behavior_influence"] == 0


# ================================================================== EDGAR

def test_an_etf_resolves_unavailable_and_is_not_guessed():
    """SCHD has no issuer. Inventing one would attach a fabricated identity."""
    from scripts.lib.cio_edgar_proof import load_ticker_map

    tm = load_ticker_map(REPO)
    if not tm:
        pytest.skip("ticker map not present")
    r = resolve_issuer("SCHD", tm)
    assert r["resolved"] is False
    assert r["status"] == "UNAVAILABLE"
    assert "not guessed" in r["reason"]


def test_an_operating_company_resolves():
    from scripts.lib.cio_edgar_proof import load_ticker_map

    tm = load_ticker_map(REPO)
    if not tm:
        pytest.skip("ticker map not present")
    r = resolve_issuer("V", tm)
    assert r["resolved"] is True
    assert r["cik"] == 1403161


def test_edgar_artifact_cannot_corpus_hit():
    p = build_proof("V", repo_root=REPO)
    assert p["dimension_scope"] == "entity"
    assert p["evidence_grade"] == "C"
    assert p["can_corpus_hit"] is False


def test_edgar_is_a_declared_provider():
    from scripts.lib.cio_specialist_artifact import PROVIDERS

    assert "edgar" in PROVIDERS
