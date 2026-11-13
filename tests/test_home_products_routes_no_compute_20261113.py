"""home-products (operator 13 Nov 2026): every product route serves the STORED product and never computes.

For each route and each case the operator named - cold start / missing product, expired product, Valkey down,
store unreadable - every builder and every legacy request-time compute function is replaced by a tripwire that
raises. The route must answer (stored, last good greyed, or UNKNOWN) without tripping one.

Synthetic rows only. No DB, no Valkey, no server, no network.
"""
from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

NOW = datetime.now(timezone.utc)


class Tripwire(AssertionError):
    pass


def _trip(name):
    def _f(*a, **k):
        raise Tripwire(f"compute called in the web process: {name}")
    return _f


API_COMPUTE = ("_market_risk_latest_projection", "_home_cio_card", "_risk_payload_cached", "_reports_analyst_links",
               "_home_since_close", "_home_incidents", "_home_priorities_live", "_home_status", "_home_gates",
               "_shared_get_cached", "_fresh_price_batch", "_cio_truth_readers")
LIB_COMPUTE = {
    "w7_pages": ("page_payload",),
    "cio_truth": ("risk_payload", "resolve"),
    "home_incidents": ("build",),
    "home_status_live": ("serve",),
    "home_priorities_live": ("build",),
    "home_v010_api": ("home_gates",),
    "home_cio_card": ("build",),
    "market_risk_projection": ("build", "load_snapshot"),
    "cc_products.builders": ("build_market_risk", "build_risk", "build_analyst_links", "build_home",
                             "market_risk_projection", "home_cio_card", "fresh_price_batch"),
    "cc_products.product_builder": ("build_in_child", "run_once"),
    "cc_products.cio_pages": ("build_in_child", "build_payload", "run_once"),
}


@pytest.fixture
def api(monkeypatch):
    import scripts.api_v2 as api

    for name in API_COMPUTE:
        monkeypatch.setattr(api, name, _trip("api_v2." + name))
    for mod, fns in LIB_COMPUTE.items():
        for prefix in ("scripts.lib.", "lib."):
            try:
                m = importlib.import_module(prefix + mod)
            except Exception:  # noqa: BLE001 - "lib." alias may not resolve for cc_products
                continue
            for fn in fns:
                if hasattr(m, fn):
                    monkeypatch.setattr(m, fn, _trip(f"{prefix}{mod}.{fn}"))
    try:
        import reporting_engine

        monkeypatch.setattr(reporting_engine, "report_links_map", _trip("reporting_engine.report_links_map"))
    except Exception:  # noqa: BLE001
        pass
    return api


# ------------------------------------------------------------------------------------------------ synthetic rows

MR_BODY = {"projection": {"state": "evaluated", "tier": "T1", "as_of": "x"},
           "home_cio_card": {"schema": "HomeCioCard@v1", "state": "OK", "synthetic": True}}
RISK_BODY = {"positions": [{"symbol": "SYN1"}], "truth": {"source": "synthetic", "as_of": "x", "stale": False,
                                                         "gap": None}}
LINKS_BODY = {"links": {"SYNB": {"generated_at": "2026-11-13T02:00:00Z"}, "SYNA": {"generated_at": "2026-11-12"}},
              "count": 2, "updated_at": "2026-11-13T02:00:00Z"}
HOME_BODY = {"slices": {"since_close": {"status": "ok", "generated_at": "2026-11-13T06:00:00+00:00",
                                        "window": {"session_date": "2026-11-13"}},
                        "incidents": {"schema": "HomeIncidents@v1", "state": "OK", "synthetic": True},
                        "approvals_summary": {"state": "UNKNOWN", "scope_excluded": True},
                        "priorities_live": {"schema": "HomePrioritiesLive@v1", "state": "OK"},
                        "status": {"verdict": "YES", "trade_ready": {"verdict": "YES"}},
                        "gates": {"state": "OK"}},
             "slice_clocks": {}, "slice_stale_after_s": {"since_close": 10800, "incidents": 180}}
PAGES_BODY = {"portfolio": {"source": "CIO", "stored": True}}

BODIES = {"market_risk.latest": MR_BODY, "risk": RISK_BODY, "reports.analyst_links": LINKS_BODY, "home": HOME_BODY,
          "cio.pages": PAGES_BODY}


def make_row(product_id, *, age_s, hard=300, stale=180):
    as_of = NOW - timedelta(seconds=age_s)
    body = json.dumps(BODIES[product_id]).encode()
    return {"product_id": product_id, "scope_key": "global", "body": memoryview(body), "etag": "sha256:t", "seq": 3,
            "as_of": as_of, "built_at": NOW, "next_refresh_at": None, "stale_after_s": stale, "hard_expiry_s": hard,
            "purge_after_s": 604800, "status": "OK", "reason": None, "schema_version": 1, "source_watermarks": {},
            "builder_sha": "t", "bytes": len(body), "build_ms": 5}


class DownHot:
    def get(self, key):
        from scripts.lib.cc_products.hot_tier import HotTierDown

        raise HotTierDown("synthetic: valkey down")

    def set(self, *a, **k):
        from scripts.lib.cc_products.hot_tier import HotTierDown

        raise HotTierDown("synthetic: valkey down")


def wire(monkeypatch, api, case):
    """Install a fake product store for one case. Returns the list of SQL statements the read issued."""
    from scripts.lib.cc_products import cio_pages_route as cpr

    issued = []

    def fake_raising(sql, params=None, fetch="all"):
        issued.append((sql, params))
        if case == "store_down":
            raise RuntimeError("synthetic: store down")
        if case == "missing":
            return []
        pid = params[0]
        age = 4000 if case == "expired" else 10
        return [make_row(pid, age_s=age)]

    hot = DownHot() if case == "valkey_down" else None
    monkeypatch.setattr(api, "_db_query_raising", fake_raising)
    monkeypatch.setattr(cpr, "_HOT", [hot])
    return issued


ROUTES = [
    ("/api/v2/home/cio-card", None),
    ("/api/v2/risk", None),
    ("/api/v2/reports/analyst/links", {}),
    ("/api/v2/products/home", {}),
    ("/api/v2/home/since-close", None),
    ("/api/v2/home/incidents", None),
    ("/api/v2/home/priorities-live", None),
    ("/api/v2/home/status", None),
    ("/api/v2/home/gates", None),
    ("/api/v2/cio/pages", None),
]
CASES = ("missing", "expired", "valkey_down", "store_down")


def call(api, path, query):
    h = api.ROUTES[path]
    return h(query) if query is not None else h()


def meta_of(out):
    return out.get("_product") or {}


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("path,query", ROUTES)
def test_route_never_computes(api, monkeypatch, path, query, case):
    issued = wire(monkeypatch, api, case)
    out = call(api, path, query)  # a Tripwire here is the failure
    assert isinstance(out, dict)
    assert issued, "the route must read the product store"
    assert all("cc_product_current" in sql for sql, _ in issued), "only the product store may be read"
    m = meta_of(out)
    if case == "missing":
        assert m.get("status") == "BUILDING"
    elif case == "store_down":
        assert m.get("status") == "UNKNOWN"
    elif case == "expired":
        assert m.get("status") == "UNKNOWN" and m.get("greyed") is True, m
    else:  # valkey down: Postgres serves the fresh row
        assert m.get("status") == "OK" and m.get("served_from") == "pg", m


def test_market_risk_latest_inline_route_never_computes(api, monkeypatch):
    for case in CASES:
        wire(monkeypatch, api, case)
        out = api._stored_market_risk_latest()
        assert out.get("state") in ("evaluated", "not_evaluated")
        if case in ("missing", "store_down"):
            assert out["state"] == "not_evaluated" and "unavailable" in out["reason"]
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    i = src.index('if base_path == "/api/v2/market-risk/latest" and method == "GET":')
    block = src[i:i + 600]
    assert "_stored_market_risk_latest()" in block and "_market_risk_latest_projection()" not in block


def test_unavailable_bodies_are_null_not_empty(api, monkeypatch):
    wire(monkeypatch, api, "missing")
    risk = api.ROUTES["/api/v2/risk"]()
    assert risk["positions"] is None and risk["truth"]["stale"] is True
    links = api.ROUTES["/api/v2/reports/analyst/links"]({})
    assert links["links"] is None and links["count"] is None


def test_analyst_links_filters_and_limits_the_stored_map(api, monkeypatch):
    wire(monkeypatch, api, "valkey_down")
    h = api.ROUTES["/api/v2/reports/analyst/links"]
    assert list(h({})["links"]) == ["SYNB", "SYNA"]
    assert list(h({"symbol": "syna"})["links"]) == ["SYNA"]
    assert h({"limit": "1"})["count"] == 1


def test_cio_pages_fallback_is_removed():
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    assert "def _cio_pages_build" not in src
    assert "_CIO_PAGES_COMPUTED_TTL_S" not in src


def test_per_product_hit_miss_is_counted_and_logged(api, monkeypatch, caplog):
    from scripts.lib.cc_products import product_route as pr

    wire(monkeypatch, api, "valkey_down")
    before = pr.counters().get("risk", {}).get("hit", 0)
    with caplog.at_level("INFO", logger="cc_products.read"):
        api.ROUTES["/api/v2/risk"]()
    assert pr.counters()["risk"]["hit"] == before + 1
    assert any("cc_product_read product=risk" in r.getMessage() and "hit=1" in r.getMessage()
               for r in caplog.records)
    wire(monkeypatch, api, "missing")
    m0 = pr.counters()["risk"].get("miss", 0)
    api.ROUTES["/api/v2/risk"]()
    assert pr.counters()["risk"]["miss"] == m0 + 1


def test_home_slice_with_an_old_clock_stays_stale_in_a_fresh_product(api, monkeypatch):
    """A fresh product build must not make a stale source look fresh: the slice is aged by its OWN clock."""
    from scripts.lib.cc_products import product_route as pr

    body = json.loads(json.dumps(HOME_BODY))
    body["slice_clocks"] = {"incidents": {"as_of": (NOW - timedelta(hours=2)).isoformat()},
                            "since_close": {"as_of": None}}
    row = make_row("home", age_s=5, hard=900)
    row["body"] = json.dumps(body).encode()

    def fetch(pid, scope="global"):
        return dict(row)

    out = pr.serve_home_slice("incidents", fetch_row=fetch, hot=None, now=NOW)
    assert out["_product"]["status"] == "OK"  # the product itself is fresh ...
    assert out["_product"]["slice_stale"] is True  # ... the slice is not
    assert out["_product"]["slice_age_s"] >= 7000
    sc = pr.serve_home_slice("since_close", fetch_row=fetch, hot=None, now=NOW)
    assert sc["_product"]["slice_stale"] is True  # no clock = stale, never fresh
