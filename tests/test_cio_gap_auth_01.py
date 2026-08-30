"""G-AUTH-01: drop AVOID-contradicting rebalance orders; append refusal receipts.

RAILS: READ_ONLY_ADVISORY, MBI=0, no broker writes, no notify-on.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.cio_rebalancer_readonly import (
    AUTHORITY,
    MBI,
    REFUSAL_SCHEMA,
    append_avoid_refusal_receipt,
    drop_orders_against_avoid,
    flag_orders_against_avoid,
)


PRODUCT_AVOID_ARKG = {
    "action_book": {"AVOID": [{"symbol": "ARKG"}]},
    "recommendations": [{"symbol": "ARKG", "recommended_action": "AVOID"}],
}


def _orders():
    return [
        {
            "action": "BUY",
            "suggested_tickers": ["ARKG"],
            "current_tickers": [],
            "amount_usd": 500,
        },
        {
            "action": "BUY",
            "suggested_tickers": ["VTI"],
            "current_tickers": [],
            "amount_usd": 800,
        },
    ]


def test_drop_default_keeps_non_contradicted():
    kept, dropped = drop_orders_against_avoid(_orders(), PRODUCT_AVOID_ARKG)
    assert len(kept) == 1
    assert kept[0]["suggested_tickers"] == ["VTI"]
    assert kept[0]["cio_avoid_contradiction"] is False
    assert len(dropped) == 1
    assert dropped[0]["cio_avoid_contradiction"] is True
    assert "ARKG" in dropped[0]["cio_avoid_symbols"]
    assert dropped[0]["authority"] == AUTHORITY
    assert dropped[0]["memory_behavior_influence"] == MBI


def test_flag_orders_default_drops():
    out = flag_orders_against_avoid(_orders(), PRODUCT_AVOID_ARKG)
    assert len(out) == 1
    assert out[0]["suggested_tickers"] == ["VTI"]


def test_flag_only_when_drop_contradictions_false():
    kept, dropped = drop_orders_against_avoid(
        _orders(), PRODUCT_AVOID_ARKG, drop_contradictions=False
    )
    assert dropped == []
    assert len(kept) == 2
    assert kept[0]["cio_avoid_contradiction"] is True
    assert kept[1]["cio_avoid_contradiction"] is False
    flagged = flag_orders_against_avoid(
        _orders(), PRODUCT_AVOID_ARKG, drop_contradictions=False
    )
    assert len(flagged) == 2
    assert any(o.get("cio_avoid_contradiction") for o in flagged)


def test_append_avoid_refusal_receipt(tmp_path: Path):
    _kept, dropped = drop_orders_against_avoid(_orders(), PRODUCT_AVOID_ARKG)
    assert dropped
    path = append_avoid_refusal_receipt(dropped, root=tmp_path)
    assert path is not None
    assert path == tmp_path / "data" / "cio" / "cio_avoid_refusals.jsonl"
    assert path.is_file()
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["schema"] == REFUSAL_SCHEMA
    assert rec["authority"] == AUTHORITY
    assert rec["mbi"] == 0
    assert rec["memory_behavior_influence"] == 0
    assert "ARKG" in rec["symbols"]
    assert rec["dropped_count"] == 1
    assert rec["broker_write"] is False
    assert rec["financial_action"] is False
    assert "ts" in rec and rec["ts"]
    assert "note" in rec and "G-AUTH-01" in rec["note"]

    # append-only: second write adds a line
    append_avoid_refusal_receipt(dropped, root=tmp_path)
    lines2 = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines2) == 2


def test_append_refusal_noop_when_empty(tmp_path: Path):
    assert append_avoid_refusal_receipt([], root=tmp_path) is None
    assert not (tmp_path / "data" / "cio" / "cio_avoid_refusals.jsonl").exists()
