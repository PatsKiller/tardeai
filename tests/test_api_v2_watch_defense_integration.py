"""RC-v1 cross-lane integration guard: Watch (Lane B) AND Defense/Sectors (Lane C)
must BOTH survive in the SAME scripts/api_v2.py after the release-candidate merge.

Lane B and Lane C both edit scripts/api_v2.py but in different functions
(_finviz_strip_map_compute vs _market_movers/_sectors_monitor). A whole-file
ours/theirs resolution — or a bad hand-merge — would silently drop one lane's
behavior while the module still imported and every other test still passed. These
tests fail closed if EITHER lane's response shape regresses, or if any of the three
routes is dropped from the ROUTES table.

Driven hermetically: a temp PROJECT_ROOT plus monkeypatched _db_query / _load_json,
so no real database or captured file is touched. Read-only throughout.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import api_v2  # noqa: E402  (import proves the merged module loads at all)


# ---------------------------------------------------------------------------
# 0. Coexistence + no-route-dropped
# ---------------------------------------------------------------------------

def test_all_three_lane_functions_coexist_in_one_module():
    """If the reconciliation dropped a lane, one of these attributes disappears."""
    assert callable(getattr(api_v2, "_finviz_strip_map_compute", None)), "Lane B Watch compute missing"
    assert callable(getattr(api_v2, "_market_movers", None)), "Lane C movers handler missing"
    assert callable(getattr(api_v2, "_sectors_monitor", None)), "Lane C sectors handler missing"


def test_no_route_dropped_from_routes_table():
    """The three endpoints must still be wired to their handlers in ROUTES."""
    routes = api_v2.ROUTES
    assert routes.get("/api/v2/finviz-strip-map") is api_v2._finviz_strip_map, "Watch strip route dropped"
    assert routes.get("/api/v2/market-movers") is api_v2._market_movers, "Defense movers route dropped"
    assert routes.get("/api/v2/sectors/monitor") is api_v2._sectors_monitor, "Sectors monitor route dropped"


# ---------------------------------------------------------------------------
# Hermetic harness
# ---------------------------------------------------------------------------

@pytest.fixture
def hermetic_root(tmp_path, monkeypatch):
    """Point PROJECT_ROOT/STATE_DIR at a temp tree and neutralize file caches."""
    monkeypatch.setattr(api_v2, "PROJECT_ROOT", tmp_path, raising=True)
    monkeypatch.setattr(api_v2, "STATE_DIR", tmp_path / "data" / "state", raising=True)
    # force cache reloads inside the handlers
    monkeypatch.setattr(api_v2, "_FINVIZ_ENRICH_CACHE", {"data": {}, "mtime": None}, raising=True)
    monkeypatch.setattr(api_v2, "_MOVERS_MEMO", {"etag": None, "data": None}, raising=True)
    monkeypatch.setattr(api_v2, "_load_json", lambda *a, **k: {}, raising=True)
    (tmp_path / "data" / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "runtime").mkdir(parents=True, exist_ok=True)
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Lane B — Watch valuation passthrough / source / as-of / no fabrication
# ---------------------------------------------------------------------------

def test_watch_strip_valuation_passthrough_shape(hermetic_root, monkeypatch):
    root = hermetic_root
    # Finviz enrichment cache: FVIZ carries its own valuation; CARR has none here.
    enrich = {
        "FVIZ": {"rsi": 55, "rsi_status": "neutral", "pe": 18.0, "forward_pe": 16.0,
                 "peg": 1.2, "pb": 3.1, "ps": 4.2, "cached_at": "2026-07-25T10:00:00Z"},
        "CARR": {"rsi": 60, "cached_at": "2026-07-25T09:00:00Z"},
        "MUTFD": {},  # no finviz metrics at all
    }
    (root / "data" / "state" / "ticker_enrichment_cache.json").write_text(json.dumps(enrich))
    # Supplement: CARR gets yfinance valuation; MUTFD negative-cached (non-equity).
    supp = {
        "CARR": {"pe": 22.5, "forward_pe": 20.0, "peg": 1.5, "pb": 5.0, "ps": 3.0,
                 "cached_at": "2026-07-26T02:00:00Z"},
        "MUTFD": {"no_valuation": True, "cached_at": "2026-07-26T02:00:00Z"},
    }
    (root / "data" / "state" / "valuation_supplement_cache.json").write_text(json.dumps(supp))

    def fake_db(sql, *a, **k):
        if "watchlist_items" in sql:
            return [{"symbol": "FVIZ"}, {"symbol": "CARR"}, {"symbol": "MUTFD"}]
        return []

    monkeypatch.setattr(api_v2, "_db_query", fake_db, raising=True)

    res = api_v2._finviz_strip_map_compute()
    assert res["ok"] is True
    m = res["map"]

    # every emitted row exposes the valuation passthrough fields the Watch panel reads
    for sym, row in m.items():
        for f in ("pe", "forward_pe", "peg", "pb", "ps", "valuation_source", "fundamentals_as_of"):
            assert f in row, f"{sym}: Watch valuation field '{f}' missing from strip row"

    # FVIZ: valuation came from the finviz row -> source labelled finviz, as-of = finviz cached_at
    assert m["FVIZ"]["pe"] == 18.0
    assert m["FVIZ"]["valuation_source"] == "finviz"
    assert m["FVIZ"]["fundamentals_as_of"] == "2026-07-25T10:00:00Z"

    # CARR: finviz row had no valuation -> supplement wins, provenance = yfinance, as-of = supp cached_at
    assert m["CARR"]["pe"] == 22.5
    assert m["CARR"]["valuation_source"] == "yfinance"
    assert m["CARR"]["fundamentals_as_of"] == "2026-07-26T02:00:00Z"

    # MUTFD: negative-cached non-equity -> NO fabricated valuation (all None); source None
    if "MUTFD" in m:
        assert m["MUTFD"]["pe"] is None and m["MUTFD"]["ps"] is None
        assert m["MUTFD"]["valuation_source"] is None


def test_watch_strip_compute_is_read_only_no_paid_review_autocall():
    """Lane B's Watch surfacing must not write, nor auto-invoke a paid reviewer /
    fabricate a validation PASS, inside the strip-compute path."""
    src = Path(api_v2.__file__).read_text()
    start = src.index("def _finviz_strip_map_compute")
    end = src.index("\ndef ", start + 1)
    body = src[start:end]
    lowered = body.lower()
    for forbidden in ("insert into", "update ", "delete from",
                      "run_models", "paid_review", "auto_review",
                      "validation_pass", "\"pass\"", "'pass'"):
        assert forbidden not in lowered, f"Watch strip compute must not contain {forbidden!r}"


# ---------------------------------------------------------------------------
# 2. Lane C — Sectors data-quality ledger / stale quarantine / coverage
# ---------------------------------------------------------------------------

def test_sectors_monitor_data_quality_ledger_and_quarantine(hermetic_root, monkeypatch):
    # Shrink the sector map so the test is fast and deterministic.
    monkeypatch.setattr(api_v2, "_SECTOR_ETF_MAP", {"Technology": "XLK", "Energy": "XLE"}, raising=True)

    def fake_db(sql, params=None, fetch=None):
        s = " ".join(sql.split())
        if "symbol='SPY'" in s:
            return {"day_change_pct": 0.5}
        if "watch_directives" in s:
            return []
        if "sector_rs_daily" in s:
            return []
        if "market_quotes WHERE symbol=%s" in s:
            return {"day_change_pct": 1.2}
        if "incubator_universe" in s and "count" in s.lower():
            return {"n": 7}
        if "watchlist_items wi" in s:
            return []
        return [] if fetch is None else {}

    monkeypatch.setattr(api_v2, "_db_query", fake_db, raising=True)

    res = api_v2._sectors_monitor()

    # pre-existing shape preserved
    assert "sectors" in res and "spy_change_pct" in res
    # Lane C data-quality block present and populated
    dq = res.get("data_quality")
    assert isinstance(dq, dict), "Defense/Sectors data_quality block missing"
    assert "error" not in dq, f"data_quality degraded: {dq.get('error')}"
    assert dq["sectors_total"] == len(res["sectors"])
    assert dq["stale_sla_days"] == 4
    assert "sectors_stale" in dq

    # the field-truth ledger carries scope/coverage/provider/as-of annotations
    ledger = dq["ledger"]
    for key in ("source", "provider", "coverage_n", "coverage_total", "quality"):
        assert key in ledger, f"ledger missing coverage/provenance field '{key}'"

    # every sector row keeps its numbers AND gains the quarantine truth fields
    for s in res["sectors"]:
        assert "recommendation_eligible" in s
        assert "stale" in s
        assert "stale_sla_days" in s
        assert "quarantine_reason" in s
        assert "source_age_days" in s
        # nothing deleted: the pre-existing momentum/etf numbers survive
        assert "etf" in s and "momentum" in s


# ---------------------------------------------------------------------------
# 3. Lane C — Market-movers scope-truth labelling (sample, not breadth)
# ---------------------------------------------------------------------------

def test_market_movers_scope_truth_labels(hermetic_root, monkeypatch):
    root = hermetic_root
    snap = {
        "captured_at": "2026-07-26T14:30:00Z",
        "signals": {
            "new_high": {"rows": [{"symbol": "AAA"}, {"symbol": "BBB"}]},
            "new_low": {"rows": [{"symbol": "CCC"}]},
        },
    }
    (root / "data" / "runtime" / "market_movers_latest.json").write_text(json.dumps(snap))
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: [], raising=True)

    res = api_v2._market_movers()
    assert res.get("ok") is True

    # top-level scope truth: this is a capped SAMPLE, never exchange-wide breadth
    scope = res.get("internals_scope")
    assert isinstance(scope, dict), "internals_scope scope-truth block missing"
    assert scope["scope"] == "top_movers_sample"
    assert scope["source_as_of"] == "2026-07-26T14:30:00Z"
    assert scope["sample_cap_per_signal"] == 2  # measured from the capture, not hardcoded

    # each breadth signal carries its own coverage annotations
    for name in ("new_high", "new_low"):
        block = res["signals"][name]
        assert block["source_as_of"] == "2026-07-26T14:30:00Z"
        assert "sample_cap_per_signal" in block
        assert "n_returned" in block


# ---------------------------------------------------------------------------
# 4. Union proof: both lanes' edits are present in the SAME source file
# ---------------------------------------------------------------------------

def test_both_lane_edits_present_in_same_source():
    src = Path(api_v2.__file__).read_text()
    # Lane B markers
    assert "valuation_supplement_cache.json" in src
    assert "val_from_supp" in src
    # Lane C markers
    assert "internals_scope" in src
    assert "quarantine_stale_rows" in src
    assert "recommendation_eligible" in src
