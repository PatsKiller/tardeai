"""LQ-20261107-2993b: watch-curation ``shape=list`` / ``symbols=`` / per-list ``as_of``.

The default curation body was ~400 KB (8.6 KB per row x 2 lists, 24 rows per page at the byte budget). List rows never
render the detail-only keys, so ``shape=list`` drops them, pages by row count (25 default) and ``symbols=`` returns the
full row for a name on demand. Every list carries its own ``as_of``. Synthetic fixtures only."""
import json
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from lib import site_payload_reads as reads  # noqa: E402
from lib.data_broker import watch_curation, watch_prospects  # noqa: E402

NOW = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)
HEAVY = "x" * 1500


def fixture_stance(guid, **kw):
    return {"stance": None, "conviction": None, "stale": True, "gap": {"reason": "fixture"}}


def _row(sym):
    r = watch_prospects.no_record_row(sym)
    r.update(lane="forming", conviction=70, starred=True)
    for k in reads.LIST_SHAPE_DROP:
        r[k] = {"detail": HEAVY}
    r["conflict_section_gap"] = None
    return r


@pytest.fixture
def curation(monkeypatch):
    syms = [f"T{i:03d}" for i in range(60)]
    rows = {s: _row(s) for s in syms}
    g = {
        "now": NOW,
        "payload": {},
        "row_for": rows.__getitem__,
        "opps": {s: {"rank": i + 1, "conviction": 70} for i, s in enumerate(syms)},
        "operator": {s: {} for s in syms},
        "held": set(),
        "proj_meta": {"as_of": "2026-11-13T14:50:00+00:00"},
    }
    monkeypatch.setattr(watch_prospects, "gather", lambda q: g)
    monkeypatch.setattr(watch_curation, "read_dismissed", lambda **k: ({}, "ok"))
    return syms


def _read(q):
    return reads.read_curation(q, stance_resolver=fixture_stance, stance_projection={}, section_reader=lambda r, g: {},
                               section_root="/nonexistent", review_reader=lambda s: {})


def _size(o):
    return len(json.dumps(o, default=str).encode())


# REVIEW-2993r R3: the pin is the LITERAL set. Looping over reads.LIST_SHAPE_DROP made a deleted key delete its own assertion.
EXPECTED_DROP = {"cio_truth", "surfaces", "company_facts", "whats_missing", "levels_ref", "next_trigger", "cio_stance_gap"}


def test_drop_set_is_the_literal_seven_and_keeps_conflict_gap():
    assert set(reads.LIST_SHAPE_DROP) == EXPECTED_DROP
    assert "conflict_section_gap" not in reads.LIST_SHAPE_DROP


def test_list_shape_rows_carry_none_of_the_literal_drop_set(curation):
    lst = _read({"view": "mine", "shape": "list"})
    for r in lst["my_watchlist"]["rows"]:
        assert not EXPECTED_DROP & set(r), sorted(EXPECTED_DROP & set(r))
        assert "conflict_section_gap" in r


def test_list_shape_drops_detail_keys_and_is_much_smaller(curation):
    full = _read({"view": "mine"})
    lst = _read({"view": "mine", "shape": "list"})
    assert lst["shape"] == "list" and full["shape"] == "full"
    for r in lst["my_watchlist"]["rows"]:
        assert not set(reads.LIST_SHAPE_DROP) & set(r)
        assert r["symbol"]
    assert _size(lst) < _size(full) * 0.6


def test_list_shape_pages_25_rows_by_count_not_bytes(curation):
    out = _read({"view": "mine", "shape": "list"})
    page = out["my_watchlist"]["pagination"]
    assert len(out["my_watchlist"]["rows"]) == 25 == page["limit"] == page["returned"]
    assert page["total"] == 60 and page["next_offset"] == 25 and page["has_more"] is True
    nxt = _read({"view": "mine", "shape": "list", "offset": 25})
    assert nxt["my_watchlist"]["rows"][0]["symbol"] != out["my_watchlist"]["rows"][0]["symbol"]


def test_full_shape_is_unchanged_default(curation):
    out = _read({"view": "mine"})
    assert all(k in out["my_watchlist"]["rows"][0] for k in reads.LIST_SHAPE_DROP)
    assert out["my_watchlist"]["pagination"]["limit"] == 50


def test_symbols_returns_full_row_for_named_names_only(curation):
    out = _read({"view": "mine", "shape": "full", "symbols": "t005, T007,t005"})
    assert [r["symbol"] for r in out["my_watchlist"]["rows"]] == ["T005", "T007"]
    assert all(k in out["my_watchlist"]["rows"][0] for k in reads.LIST_SHAPE_DROP)
    assert out["my_watchlist"]["pagination"]["total"] == 2


def test_symbols_capped_at_30():
    q = {"symbols": ",".join(f"S{i}" for i in range(80))}
    assert len(reads._curation_symbols(q)) == reads.SYMBOLS_MAX == 30


def test_every_list_carries_its_own_as_of(curation):
    out = _read({"view": "both", "shape": "list"})
    assert out["my_watchlist"]["as_of"] == out["generated_at"]
    assert out["my_watchlist"]["as_of_basis"] == "composed_at"
    assert out["suggests"]["as_of"] == "2026-11-13T14:50:00+00:00"
    assert out["suggests"]["as_of_basis"] == "ranking_projection"


def test_a_conflict_gap_survives_the_projection(curation, monkeypatch):
    """conflict_section_gap feeds conflict_count; dropping it would turn a gap into 'no flags'."""
    out = _read({"view": "mine", "shape": "list"})
    assert "conflict_section_gap" in out["my_watchlist"]["rows"][0]
    assert out["my_watchlist"]["conflict_count_scope"] == "flagged_names_on_page"
