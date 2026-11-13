"""HOME_GATES_API_20261112 - GET /api/v2/home/gates read model + handler (LQ-20261107-2141)."""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from lib import home_v010_api as H  # noqa: E402
from lib import validation_gates as VG  # noqa: E402
from vg_fixtures_20261112 import NOW  # noqa: E402


def row(i, status="OPEN", bt=False, due=None):
    return {"gate_id": f"VG-{i}", "title": f"t{i}", "category": "c", "status": status, "blocks": "b",
            "blocks_trading": bt, "due_at": due, "owner": "o", "last_eval_result": "FAIL",
            "last_evaluated_at": (NOW - timedelta(minutes=2)).isoformat(), "last_eval_detail": '{"detail": "d"}',
            "evidence": "[]"}


def fresh(age_s=120, n=7):
    return {"computed_at": (NOW - timedelta(seconds=age_s)).isoformat(), "n": n}


def test_unreadable_store_is_unknown_with_null_counts_never_zero():
    m = VG.read_model(None, None, now=NOW)
    assert m["state"] == "UNKNOWN" and m["counts"] is None and m["items"] == [] and m["text"] == "not available"


def test_missing_table_through_the_handler_is_unknown_and_not_cached():
    H._CACHE.clear()
    m = H.home_gates(lambda *a, **k: None, now=NOW, receipt_ok_at=lambda l: None)
    assert m["state"] == "UNKNOWN" and m["counts"] is None and "gates" not in H._CACHE


def test_stale_snapshot_is_served_last_known_good_with_age_and_threshold():
    m = VG.read_model([row(1)], fresh(age_s=1200, n=1), now=NOW)
    assert m["state"] == "STALE" and m["snapshot"]["age_s"] == 1200 and m["snapshot"]["threshold_s"] == 900
    assert m["counts"]["open"] == 1 and len(m["items"]) == 1


def test_fresh_snapshot_is_ok():
    m = VG.read_model([row(1)], fresh(age_s=120, n=1), now=NOW)
    assert m["state"] == "OK" and m["snapshot"]["age_s"] == 120


def test_seven_gates_are_all_returned_never_truncated():
    m = VG.read_model([row(i) for i in range(7)], fresh(), now=NOW)
    assert len(m["items"]) == 7 and m["counts"]["open"] == 7


def test_order_blocks_trading_then_overdue_then_failed_then_due():
    rows = [row(1, "OPEN", due="2026-11-12T20:00:00+00:00"), row(2, "FAILED"), row(3, "OVERDUE"),
            row(4, "OPEN", bt=True), row(5, "OPEN", due="2026-11-12T11:00:00+00:00")]
    ids = [i["gate_id"] for i in VG.read_model(rows, fresh(), now=NOW)["items"]]
    assert ids == ["VG-4", "VG-3", "VG-2", "VG-5", "VG-1"]
    c = VG.read_model(rows, fresh(), now=NOW)["counts"]
    assert c == {"open": 5, "blocks_trading": 1, "blocks_trading_unknown": 0, "overdue": 1}  # 2692: tri-state


def test_empty_table_is_zero_only_when_the_writer_receipt_is_fresh():
    assert VG.read_model([], {"computed_at": None, "n": 0}, now=NOW)["state"] == "UNKNOWN"
    ok = VG.read_model([], {"computed_at": None, "n": 0}, now=NOW, receipt_ok_at=NOW - timedelta(minutes=3))
    assert ok["state"] == "OK" and ok["counts"]["open"] == 0
    stale = VG.read_model([], {"computed_at": None, "n": 0}, now=NOW, receipt_ok_at=NOW - timedelta(hours=2))
    assert stale["state"] == "STALE"


def test_rows_never_evaluated_are_unknown_not_ok():
    m = VG.read_model([row(1)], {"computed_at": None, "n": 1}, now=NOW)
    assert m["state"] == "UNKNOWN" and m["counts"] is None


def test_api_route_is_a_thin_delegation():
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    _assert_route_dispatches_legacy("/api/v2/home/gates", "_home_gates")
    start = src.index("def _home_gates():")
    body = src[start:src.index("\n\n\n", start)]
    assert "home_v010_api" in body and len(body.splitlines()) <= 10 and "read_model" not in body


def _assert_route_dispatches_legacy(path, legacy_name, product="home"):
    """The route is flag-dispatched (TRADEAI_CC_PRODUCT_READERS, home-products rework 13 Nov 2026): with the flag
    at its default (legacy) it delegates to ``legacy_name``; nothing else is called."""
    import scripts.api_v2 as api
    from scripts.lib.cc_products import reader_flag

    reader_flag.reload("")
    try:
        assert reader_flag.mode(product) == "legacy"
        sentinel = {"sentinel": legacy_name}
        orig = getattr(api, legacy_name)
        setattr(api, legacy_name, lambda *a, **k: sentinel)
        try:
            assert api.ROUTES[path]() is sentinel
        finally:
            setattr(api, legacy_name, orig)
    finally:
        reader_flag.reload()
