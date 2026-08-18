"""CC v3 gap-closure: maturity bound, account-scoped lots, payload batching."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

LIVE_LOTS = Path(
    "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state/tax_lots.json"
)


def test_run_bounded_does_not_wait_on_shutdown():
    from lib.cc_request_bound import run_bounded

    def hang():
        time.sleep(8)
        return "late"

    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        run_bounded(hang, timeout_s=0.25)
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, f"shutdown waited out the worker ({elapsed:.2f}s)"


def test_run_bounded_returns_value():
    from lib.cc_request_bound import run_bounded

    assert run_bounded(lambda x: x + 1, 3, timeout_s=1.0) == 4


def test_maturity_failsoft_also_bounded(monkeypatch):
    from agent_runtime import read_http as rh

    calls = {"n": 0}

    def hang(*_a, **_k):
        calls["n"] += 1
        time.sleep(5)
        return 200, {"ok": True}

    class FakeApi:
        reader = object()

    monkeypatch.setattr(rh, "_dispatch_maturity", hang)
    t0 = time.monotonic()
    status, body = rh._dispatch_maturity_bounded(
        "GET", "/api/v3/agent-maturity", FakeApi(), timeout_s=0.2,
    )
    elapsed = time.monotonic() - t0
    assert status == 503
    assert elapsed < 1.5, f"fail-soft hung ({elapsed:.2f}s)"
    assert calls["n"] >= 1
    assert "timeout" in json.dumps(body).lower() or body.get("kind") == "timeout"


def test_host_uses_run_bounded_and_exempts_maturity():
    src = (ROOT / "scripts/portfolio_server.py").read_text()
    assert "from lib.cc_request_bound import run_bounded" in src
    assert "agent-maturity exceeded 3s connect/read bound" in src
    assert "repository evidence only" in src
    assert "_dispatch_maturity" in src
    assert '"/api/v3/agent-maturity"' in src
    boot = (ROOT / "scripts/agent_runtime_read_boot.py").read_text()
    assert "connect_timeout=2" in boot


def test_evidence_bundle_uses_account_lot_key():
    from lib.data_broker.advisory_desk import _build_evidence_bundle

    all_data = {
        "lot_basis": {
            "SCHD:schwab_taxable": {
                "lot_count": 3, "lot_data_status": "VERIFIED",
                "open_lots_count": 3, "total_shares": 406.54,
            },
            "SCHD:schwab_rollover_ira": {
                "lot_count": 9, "lot_data_status": "VERIFIED",
                "open_lots_count": 9, "total_shares": 6155.25,
            },
        }
    }
    tax = _build_evidence_bundle("SCHD", "holding", all_data, account="schwab_taxable")
    types = [i.get("type") for i in tax["evidence_items"]]
    assert "lot_basis" in types
    lot_item = next(i for i in tax["evidence_items"] if i["type"] == "lot_basis")
    assert lot_item["lot_count"] == 3
    assert "lot_basis" not in tax["evidence_gaps"]


def test_lot_key_and_account_scoped_basis():
    from lib.data_broker.advisory_desk import _load_lot_basis, _lot_key

    assert _lot_key("SCHD", "schwab_taxable") == "SCHD:schwab_taxable"
    assert _lot_key("SCHD", None) == "SCHD"

    tax_lots = {
        "state": "AVAILABLE",
        "by_symbol": {
            "SCHD": [
                {"closed": False, "shares_remaining": 406.54, "cost_per_share": 20.0, "lot_date": "2020-01-02"},
                {"closed": False, "shares_remaining": 6155.25, "cost_per_share": 25.0, "lot_date": "2019-01-02"},
            ]
        },
        "by_account": {
            "SCHD:schwab_taxable": [
                {"closed": False, "shares_remaining": 406.54, "cost_per_share": 20.0, "lot_date": "2020-01-02"},
            ],
            "SCHD:schwab_rollover_ira": [
                {"closed": False, "shares_remaining": 6155.25, "cost_per_share": 25.0, "lot_date": "2019-01-02"},
            ],
        },
    }
    taxable = _load_lot_basis("SCHD", tax_lots, 34.0, None, account="schwab_taxable")
    ira = _load_lot_basis("SCHD", tax_lots, 34.0, None, account="schwab_rollover_ira")
    combined = _load_lot_basis("SCHD", tax_lots, 34.0, None)
    assert abs(taxable["total_shares"] - 406.54) < 0.02
    assert abs(ira["total_shares"] - 6155.25) < 0.02
    assert taxable["total_shares"] < 500
    assert combined["total_shares"] > 6500


def test_load_tax_lots_indexes_file_key_not_lot_account():
    from lib.data_broker import advisory_desk as ad

    raw = {
        "SCHD:schwab_taxable": [
            {"closed": False, "shares_remaining": 406.54, "account": "fidelity_rollover_ira"},
        ],
        "SCHD:schwab_rollover_ira": [
            {"closed": False, "shares_remaining": 6155.25, "account": "schwab_taxable"},
        ],
    }
    with patch.object(ad, "_load_json", return_value=raw):
        out = ad._load_tax_lots()
    taxable = out["by_account"]["SCHD:schwab_taxable"]
    assert abs(sum(float(l["shares_remaining"]) for l in taxable) - 406.54) < 0.02
    assert all(l["_bucket_account"] == "schwab_taxable" for l in taxable)
    assert abs(sum(float(l["shares_remaining"]) for l in out["by_symbol"]["SCHD"]) - 6561.79) < 0.02


@pytest.mark.skipif(not LIVE_LOTS.exists(), reason="live tax_lots.json not on this host")
def test_live_schd_taxable_not_combined():
    from lib.data_broker import advisory_desk as ad

    raw = json.loads(LIVE_LOTS.read_text())
    with patch.object(ad, "_load_json", return_value=raw):
        out = ad._load_tax_lots()
    taxable = ad._load_lot_basis("SCHD", out, 34.0, None, account="schwab_taxable")
    ira = ad._load_lot_basis("SCHD", out, 34.0, None, account="schwab_rollover_ira")
    assert abs(taxable["total_shares"] - 406.54) < 1.0
    assert ira["total_shares"] > 6000
    assert taxable["total_shares"] < ira["total_shares"]


def test_symbol_cards_query_filters_without_rebuild():
    from lib.cc_symbol_cards import apply_symbol_cards_query

    payload = {
        "cards": {"AAPL": {"d": 1}, "MSFT": {"d": 2}, "SCHD": {"d": 3}},
        "count": 3,
        "__etag__": 'W/"x"',
    }
    out = apply_symbol_cards_query(payload, {"symbols": ["AAPL,SCHD"]})
    assert set(out["cards"]) == {"AAPL", "SCHD"}
    assert out["count"] == 2
    assert payload["cards"]["MSFT"]["d"] == 2  # cache not mutated
    none = apply_symbol_cards_query(payload, {})
    assert none["count"] == 3 or len(none["cards"]) == 3


def test_reentry_batches_watchlist_and_filters_cards():
    intel = (ROOT / "apps/command-center-v3/src/components/reentry/ReEntryCurrentIntelligence.tsx").read_text()
    rot = (ROOT / "apps/command-center-v3/src/components/reentry/ReEntryRotationWorkspace.tsx").read_text()
    for src in (intel, rot):
        assert "watchlist/items?symbols=" in src
        assert "watchlist/items?symbol=${" not in src
        assert "symbol-cards?symbols=" in src
        assert "Math.min(8, symbols.length)" not in src
        assert "CHUNK = 80" in src


def test_metric_strip_stale_is_honest():
    src = (ROOT / "apps/command-center-v3/src/components/MetricStrip.tsx").read_text()
    assert "trade_closed last close" in src
    assert "Not a crashed page" in src
    assert "schwab journal ingest" in src
