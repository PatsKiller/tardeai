#!/usr/bin/env python3
"""Phase A repair: it may remove exact-duplicate CLOSED lots and nothing else.

The dangerous version of this tool is one line shorter: dedupe every duplicate. That
would have changed share counts in fifteen records by up to 100x — ARKQ 11,300 to 100 —
for securities the broker no longer holds, so nothing could confirm the new number. The
whole design is the refusal to do that.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "scripts"))

from repair_tax_lot_duplicates import (  # noqa: E402
    dedupe_record,
    is_closed,
    open_total,
    repair,
    verify_invariants,
)

CLOSED = {
    "symbol": "AMD",
    "account": "a",
    "lot_date": "2025-09-30",
    "shares": 100.0,
    "shares_remaining": 0,
    "cost_per_share": 160.63,
    "total_cost": 16063.0,
    "action": "buy",
    "closed": True,
}
OPEN = {
    "symbol": "AMD",
    "account": "a",
    "lot_date": "2025-10-15",
    "shares": 50.0,
    "shares_remaining": 50.0,
    "cost_per_share": 170.0,
    "total_cost": 8500.0,
    "action": "buy",
    "closed": False,
}


class TestOnlyClosedDuplicatesGo:
    def test_repeated_closed_lots_collapse_to_one(self):
        kept, stats = dedupe_record([dict(CLOSED)] * 113)
        assert len(kept) == 1
        assert stats["removed"] == 112

    def test_repeated_open_lots_are_kept(self):
        """The refusal this tool exists for."""
        kept, stats = dedupe_record([dict(OPEN)] * 5)
        assert len(kept) == 5, "an open duplicate must never be removed"
        assert stats["removed"] == 0
        assert stats["skipped_open_duplicates"] == 4

    def test_open_total_never_moves(self):
        lots = [dict(CLOSED)] * 50 + [dict(OPEN)] * 3
        before = open_total(lots)
        kept, _ = dedupe_record(lots)
        assert open_total(kept) == before == 150.0

    def test_distinct_closed_lots_all_survive(self):
        a = dict(CLOSED, lot_date="2025-01-01")
        b = dict(CLOSED, lot_date="2025-02-01")
        kept, stats = dedupe_record([a, b, dict(a), dict(b)])
        assert stats["removed"] == 2
        assert {json.dumps(x, sort_keys=True) for x in kept} == {
            json.dumps(a, sort_keys=True),
            json.dumps(b, sort_keys=True),
        }

    def test_order_is_preserved(self):
        lots = [dict(OPEN), dict(CLOSED), dict(CLOSED), dict(OPEN, lot_date="2025-12-01")]
        kept, _ = dedupe_record(lots)
        assert [x["lot_date"] for x in kept] == ["2025-10-15", "2025-09-30", "2025-12-01"]


class TestClosedMeansBothConditions:
    def test_a_lot_flagged_closed_but_holding_shares_is_not_closed(self):
        """A contradictory row is not something to quietly delete a copy of."""
        weird = dict(CLOSED, closed=True, shares_remaining=25.0)
        assert not is_closed(weird)
        kept, stats = dedupe_record([weird, dict(weird)])
        assert len(kept) == 2 and stats["removed"] == 0

    def test_zero_remaining_without_the_flag_is_not_closed(self):
        assert not is_closed(dict(OPEN, shares_remaining=0, closed=False))


class TestInvariants:
    def test_a_moved_open_total_is_caught(self):
        before = {"A:a": [dict(OPEN), dict(OPEN)]}
        after = {"A:a": [dict(OPEN)]}  # an open duplicate silently dropped
        v = verify_invariants(before, after)
        assert not v["ok"] and any("open-lot total moved" in p for p in v["problems"])

    def test_a_lost_key_is_caught(self):
        v = verify_invariants({"A:a": [dict(CLOSED)], "B:b": []}, {"A:a": [dict(CLOSED)]})
        assert not v["ok"] and any("key set changed" in p for p in v["problems"])

    def test_a_lost_distinct_closed_lot_is_caught(self):
        a, b = dict(CLOSED, lot_date="2025-01-01"), dict(CLOSED, lot_date="2025-02-01")
        v = verify_invariants({"A:a": [a, b]}, {"A:a": [a]})
        assert not v["ok"]

    def test_an_invented_lot_is_caught(self):
        v = verify_invariants({"A:a": [dict(CLOSED)]}, {"A:a": [dict(CLOSED), dict(OPEN)]})
        assert not v["ok"]

    def test_a_correct_repair_passes(self):
        before = {"A:a": [dict(CLOSED)] * 10 + [dict(OPEN)]}
        after, _ = repair(before)
        assert verify_invariants(before, after)["ok"]


class TestWholeDocument:
    def test_envelope_keys_pass_through_untouched(self):
        doc = {"_agent_metadata": {"x": 1}, "generated_at": "now", "A:a": [dict(CLOSED)] * 3}
        out, _ = repair(doc)
        assert out["_agent_metadata"] == {"x": 1}
        assert out["generated_at"] == "now"
        assert len(out["A:a"]) == 1

    def test_repair_is_idempotent(self):
        doc = {"A:a": [dict(CLOSED)] * 40 + [dict(OPEN)] * 2}
        once, s1 = repair(doc)
        twice, s2 = repair(once)
        assert once == twice
        assert s2["closed_duplicates_removed"] == 0

    def test_open_duplicates_are_reported_not_removed(self):
        doc = {"A:a": [dict(OPEN)] * 4}
        out, summary = repair(doc)
        assert len(out["A:a"]) == 4
        assert summary["closed_duplicates_removed"] == 0
        assert summary["open_duplicates_left_alone"] == 3
