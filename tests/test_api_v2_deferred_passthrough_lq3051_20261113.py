"""LQ-20261113-3051 (review 3034b C1), route half: api_v2 returns a stale_serve.Deferred's 503 as is.

Without it the trade-journeys route answered 200 (the status dropped) and watch-curation answered 500. Synthetic:
the two api_v3 functions are monkeypatched to raise the Deferred a refused StaleServe read raises. No DB, no HTTP.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import api_v2  # noqa: E402
import api_v3_data_broker_watch as dbw  # noqa: E402
import api_v3_trade_journey as tj  # noqa: E402
from lib import stale_serve as ss  # noqa: E402

BODY = {"ok": False, "status": "UNKNOWN", "state": "UNKNOWN", "error": "build_deferred",
        "reason": "REFUSED_CAP", "detail": "synthetic", "retry_after_sec": 5.0}


def _raise(*_a, **_k):
    raise ss.Deferred(503, dict(BODY))


def test_trade_journeys_list_route_answers_the_503(monkeypatch):
    monkeypatch.setattr(tj, "get_list", _raise)
    status, body = api_v2.handle("/api/v3/data-broker/trade-journeys", method="GET", body=None, query={})
    assert status == 503 and body["error"] == "build_deferred" and body["retry_after_sec"] == 5.0


def test_trade_journeys_detail_route_answers_the_503(monkeypatch):
    monkeypatch.setattr(tj, "get_detail", _raise)
    status, body = api_v2.handle("/api/v3/data-broker/trade-journeys/T-1", method="GET", body=None, query={})
    assert status == 503 and body["status"] == "UNKNOWN"


def test_watch_curation_route_answers_the_503_not_500(monkeypatch):
    monkeypatch.setattr(dbw, "get_curation", _raise)
    status, body = api_v2.handle("/api/v3/data-broker/watch-curation", method="GET", body=None, query={})
    assert status == 503 and body["error"] == "build_deferred"


def test_any_other_exception_is_still_a_500(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(dbw, "get_curation", boom)
    status, body = api_v2.handle("/api/v3/data-broker/watch-curation", method="GET", body=None, query={})
    assert status == 500 and body["error"] == "RuntimeError"
