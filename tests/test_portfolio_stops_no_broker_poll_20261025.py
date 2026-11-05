"""Portfolio page views never trigger a broker read (page audit 2026-10-25).

Portfolio polled /api/v2/holdings/live-stops every 60 s and /api/v2/portfolio/llm-coverage every 120 s; both read
Schwab on a cache miss, as does the Stop Management mount load through /api/v2/stops/management. Page views now
pass ``stops=stored`` and get the stored read model; the operator Refresh (``refresh=1``) is unchanged.
Synthetic inputs only; the broker reader is replaced by a tripwire.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "scripts"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class BrokerTouched(AssertionError):
    pass


@pytest.fixture
def api(monkeypatch):
    if "api_v2" not in sys.modules:
        fake_dotenv = types.ModuleType("dotenv")
        fake_dotenv.load_dotenv = lambda *a, **k: False  # never load host credentials into the test
        monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)
    import api_v2

    calls = []

    def _tripwire(*a, **k):
        calls.append("broker")
        raise BrokerTouched("a page view reached the broker reader")

    fake_oti = types.ModuleType("open_trades_intelligence")
    fake_oti._broker_protective_stops = _tripwire
    fake_oti._norm_acct = lambda a: str(a or "").lower()
    fake_oti.broker_stops_fetched_at = lambda: "2026-10-24T20:00:00Z"
    fake_oti.broker_stop_read_ok = lambda: {"fixture_account"}
    monkeypatch.setitem(sys.modules, "open_trades_intelligence", fake_oti)
    monkeypatch.setattr(api_v2, "_holdings_live_stops", lambda *a, **k: _tripwire())
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: [])
    monkeypatch.setattr(api_v2, "_load_json", lambda *a, **k: {"holdings": [{"account": "schwab_fixture", "symbol": "FIXA"}]})
    api_v2._STOPS_MGMT_CACHE.update(ts=0.0, data=None)
    api_v2._STOPS_MGMT_STORED_CACHE.update(ts=0.0, data=None)
    api_v2._broker_calls = calls
    yield api_v2
    api_v2._STOPS_MGMT_CACHE.update(ts=0.0, data=None)
    api_v2._STOPS_MGMT_STORED_CACHE.update(ts=0.0, data=None)


@pytest.mark.parametrize("q", [{"stops": "stored"}, {"stops": ["stored"]}])
def test_stored_flag_parses_both_query_shapes(api, q):
    assert api._stored_stops_only(q) is True
    assert api._stored_stops_only({}) is False and api._stored_stops_only(None) is False


def test_llm_coverage_stored_never_reads_broker(api):
    out = api._portfolio_llm_coverage({"stops": ["stored"]})
    assert api._broker_calls == []
    assert out["broker_stop_read_ok_accounts"] == []  # no live read → nothing verified by one
    assert out["broker_stops_fetched_at"] is None


def test_llm_coverage_default_still_has_live_overlay(api):
    # unchanged for other callers: the default path still asks the broker reader (here: the tripwire)
    api._portfolio_llm_coverage({})
    assert api._broker_calls == ["broker"]


def test_stops_management_stored_never_reads_broker(api):
    try:
        out = api._stops_management_api({"stops": ["stored"]})
    except BrokerTouched:  # pragma: no cover - the assertion below names it
        pytest.fail("stops/management?stops=stored reached the broker")
    except Exception:
        out = None  # downstream synthetic gaps are fine; only the broker read matters here
    assert api._broker_calls == []
    if isinstance(out, dict) and isinstance(out.get("live_stops"), dict):
        assert out["live_stops"].get("stored_only") is True


def test_stops_management_operator_refresh_unchanged(api):
    # refresh=1 (the existing operator Refresh) keeps its live read, even with stops=stored
    try:
        api._stops_management_api({"refresh": ["1"], "stops": ["stored"]})
    except Exception:
        pass
    assert api._broker_calls == ["broker"]


def test_portfolio_page_has_no_live_stops_poll():
    hub = (ROOT / "apps/command-center-v3/src/pages/PortfolioHub.tsx").read_text()
    assert "/api/v2/holdings/live-stops" not in hub
    assert "'/api/v2/portfolio/llm-coverage?stops=stored'" in hub
    sm = (ROOT / "apps/command-center-v3/src/components/StopManagement.tsx").read_text()
    assert "'/api/v2/stops/management?stops=stored'" in sm
    assert "'/api/v2/stops/management?refresh=1'" in sm  # operator refresh unchanged
    for src in (hub, sm):
        assert "/api/v2/stops/lifecycle" not in src


def test_cio_truth_stop_rows_carry_the_stored_order_id():
    from scripts.lib import cio_truth
    src = Path(cio_truth.__file__).read_text()
    assert '"stop_order_id": p.get("order_id")' in src


def test_cio_truth_stop_rows_carry_the_stored_order_kind():
    from scripts.lib import cio_truth
    src = Path(cio_truth.__file__).read_text()
    assert '"stop_history", "stop_order_type")}' in src


def test_an_active_trailing_observation_keeps_its_kind_and_never_invents_a_price():
    """A trailing stop has no fixed trigger price. Its stored observation stays ACTIVE with the price UNKNOWN and
    the broker order KIND intact, so a page view can show the order without inventing a level or dropping it."""
    from datetime import datetime, timezone

    from scripts.lib import cio_truth

    now = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)
    rows = [{"account": "schwab_roth", "symbol": "SPCX", "order_id": "fixture-order",
             "order_type": "TRAILING_STOP", "stop_price": None, "status": "WORKING",
             "captured_at": "2026-10-24T20:00:00Z"}]
    stop = cio_truth.stop_for("schwab_roth", "SPCX", broker_rows=rows, now=now)
    assert (stop["stop_state"], stop["stop_price"], stop["stop_order_type"]) == ("active", None, "TRAILING_STOP")
    # No fixed level was recorded, so priced protection is not claimed — the level stays unknown, never zero.
    assert stop["broker_protected"] is False


def test_a_terminal_snapshot_stop_is_never_promoted_to_protection(api):
    """A cancelled/filled persisted row cannot fire; treating it as protection hides the missing-stop action."""
    row = {"account": "schwab_fixture", "symbol": "FIXA", "broker": "schwab", "status": "WORKING",
           "order_type": "STOP", "stop_price": 40, "qty": 10, "coverage": "full"}
    for status in ("CANCELED", "cancelled", "FILLED", "expired", "rejected", "replaced", "not_in_read", "triggered"):
        assert api._stored_lifecycle_stop({**row, "status": status}) is None, status
    working = api._stored_lifecycle_stop(row)
    assert working is not None and working["stop_source"] == "broker_snapshot"


def test_a_stored_snapshot_stop_carries_its_order_size(api):
    """Without qty the downstream coverage check keeps the snapshot's stale 'full' after a size-up."""
    row = {"account": "schwab_fixture", "symbol": "FIXA", "broker": "schwab", "status": "WORKING",
           "order_type": "STOP", "stop_price": 40, "qty": 10, "coverage": "full"}
    entry = api._stored_lifecycle_stop(row)
    assert entry["stop_qty"] == 10
    assert api._stored_lifecycle_stop({**row, "qty": "bad"})["stop_qty"] is None
