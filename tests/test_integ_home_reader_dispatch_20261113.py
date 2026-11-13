"""Integration fold (13 Nov 2026): every flag-dispatched route serves exactly the path its reader flag names.

legacy (the default, flag unset) -> the legacy function, never the stored reader; stored -> the stored reader, never
the legacy function. Behavioural replacement for the source-string pins the fold made stale.
"""
import pytest

import scripts.api_v2 as api
from scripts.lib.cc_products import reader_flag

HOME_SLICES = [
    ("/api/v2/home/since-close", "_home_since_close", "since_close"),
    ("/api/v2/home/gates", "_home_gates", "gates"),
    ("/api/v2/home/incidents", "_home_incidents", "incidents"),
    ("/api/v2/home/priorities-live", "_home_priorities_live", "priorities_live"),
    ("/api/v2/home/status", "_home_status", "status"),
]


@pytest.fixture
def flag():
    def set_(value):
        return reader_flag.reload(value)
    yield set_
    reader_flag.reload("")


def _trap(monkeypatch, *names):
    calls = []
    for n in names:
        monkeypatch.setattr(api, n, (lambda name: lambda *a, **k: calls.append(name) or {"from": name})(n))
    return calls


@pytest.mark.parametrize("path,legacy,slice_", HOME_SLICES)
def test_home_slice_legacy_by_default(monkeypatch, flag, path, legacy, slice_):
    flag("")
    calls = _trap(monkeypatch, legacy, "_stored_home_slice")
    assert api.ROUTES[path]() == {"from": legacy}
    assert calls == [legacy]


@pytest.mark.parametrize("path,legacy,slice_", HOME_SLICES)
def test_home_slice_stored_never_calls_legacy(monkeypatch, flag, path, legacy, slice_):
    flag("home=stored")
    calls = _trap(monkeypatch, legacy, "_stored_home_slice")
    assert api.ROUTES[path]() == {"from": "_stored_home_slice"}
    assert calls == ["_stored_home_slice"]


@pytest.mark.parametrize("value,expect", [("", "_home_cio_card"), ("market_risk.latest=stored", "_stored_home_cio_card")])
def test_cio_card_follows_market_risk_flag(monkeypatch, flag, value, expect):
    flag(value)
    calls = _trap(monkeypatch, "_home_cio_card", "_stored_home_cio_card")
    api.ROUTES["/api/v2/home/cio-card"]()
    assert calls == [expect]


@pytest.mark.parametrize("value,expect", [("", "_risk_payload_cached"), ("risk=stored", "_stored_risk")])
def test_risk_follows_flag(monkeypatch, flag, value, expect):
    flag(value)
    calls = _trap(monkeypatch, "_risk_payload_cached", "_stored_risk")
    api.ROUTES["/api/v2/risk"]()
    assert calls == [expect]


@pytest.mark.parametrize("value,expect", [("", "_reports_analyst_links_swr"),
                                          ("reports.analyst_links=stored", "_stored_analyst_links")])
def test_analyst_links_follow_flag_and_legacy_is_the_swr_path(monkeypatch, flag, value, expect):
    flag(value)
    calls = _trap(monkeypatch, "_reports_analyst_links_swr", "_stored_analyst_links", "_reports_analyst_links")
    api.ROUTES["/api/v2/reports/analyst/links"]({"q": "x"})
    assert calls == [expect]


@pytest.mark.parametrize("value,expect", [("", "_market_risk_latest_swr"),
                                          ("market_risk.latest=stored", "_stored_market_risk_latest")])
def test_market_risk_latest_follows_flag_and_legacy_is_the_swr_path(monkeypatch, flag, value, expect):
    flag(value)
    calls = _trap(monkeypatch, "_market_risk_latest_swr", "_stored_market_risk_latest", "_market_risk_latest_projection")
    status, body = api.handle("/api/v2/market-risk/latest", "GET")
    assert status == 200 and calls == [expect]


def test_malformed_flag_keeps_everything_legacy(monkeypatch, flag):
    st = flag("home=stored,bogus=stored")
    assert st["error"] and all(m == "legacy" for m in st["modes"].values())
    calls = _trap(monkeypatch, "_home_gates", "_stored_home_slice")
    api.ROUTES["/api/v2/home/gates"]()
    assert calls == ["_home_gates"]
