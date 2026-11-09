"""ANCHOR: ROUTE_STATUS_TUPLE_LQ1300_20261108

LQ-20261107-1300. Live 2026-11-08 19:33 ET: GET /api/v2/finviz-chart answered
`HTTP 200 {"ok": true, "data": [502, {"error": "HTTP Error 302 … infinite loop"}]}` — the failure was
reported as a success.

Two defects, one visible body:

* the ROUTES dispatcher wrapped *every* handler return in the v2 envelope
  (`200, {"ok": True, "data": <return>}`), so the `(502, {...})` the chart proxy returns became JSON
  data. `/api/v2/finviz-chart` is the only one of 543 ROUTES entries that returns
  `(status, body)`; every other handler returns a payload and keeps the envelope unchanged.
* the chart proxy asked `elite.finviz.com/chart.ashx`, a 302 shim to `charts.finviz.com`, which
  answers a session-less client with a 302 back to the SAME URL — follow-redirect gives up and the
  operator saw a urlopen string.

LQ-20261107-1310 (addendum, measured 2026-11-08 20:05 ET): that loop is not evidence of an expired
cookie and not unique to us — it is what the host returns to a client it will not serve. The image
host the rest of this repo already uses, `charts2-node.finviz.com/chart.ashx?cs=l&t=…&tf=d&s=linear&ct=candle_stick`,
answered HTTP 200 image/png (29,441 bytes, 900x340) with NO cookie. The proxy now uses that form and
sends no cookie at all.

Pinned here: a tuple return is the response (status and body verbatim, never wrapped); a dict return
still gets the envelope; the shape test cannot mistake a payload for a status; and the chart route
names each failure as what was actually observed — a loop, a login bounce, a non-image body, a real
HTTP status — without claiming a cookie fault it cannot prove.

Hermetic: no network, no DB, no Finviz call — `urlopen` and the throttle are stubs.
"""

from __future__ import annotations

import io
import sys
import types
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

SYMBOL = "SYNTH"  # synthetic: this repository is public
PROBE_PATH = "/api/v2/__lq1300_status_tuple_probe__"
CHART_HOST = "charts2-node.finviz.com"


@pytest.fixture()
def api(monkeypatch):
    import api_v2

    # The chart proxy is throttled through finviz_throttle; the stub keeps the test off the network.
    stub = types.ModuleType("finviz_throttle")
    stub.acquire = lambda timeout=20: None
    monkeypatch.setitem(sys.modules, "finviz_throttle", stub)
    return api_v2


def _urlopen(monkeypatch, *, payload=b"", exc=None, seen=None):
    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _open(req, timeout=None):
        if seen is not None:
            seen.append(req)
        if exc is not None:
            raise exc
        return _Resp(payload)

    monkeypatch.setattr(urllib.request, "urlopen", _open)


def _redirect(url: str, location: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url,
        302,
        "The HTTP server returned a redirect error that would lead to an infinite loop",
        {"Location": location},
        None,
    )


# ── the dispatcher contract ────────────────────────────────────────────────────────────────────────


def test_a_handler_status_tuple_is_the_http_response(api, monkeypatch):
    body = {"ok": False, "error": "finviz proxy failed"}
    monkeypatch.setitem(api.ROUTES, PROBE_PATH, lambda: (502, body))
    status, out = api.handle(PROBE_PATH, method="GET", body=None, query={})
    assert status == 502
    assert out == body, "the tuple body must be the response body, not a field inside a 200 envelope"
    assert "data" not in out, "a wrapped body would read as success to every client"


def test_the_chart_route_carries_the_failure_status_end_to_end(api, monkeypatch):
    """The exact reported shape: 19:33 ET answered 200 with [502, {...}] inside data."""
    chart = f"https://{CHART_HOST}/chart.ashx?cs=l&t={SYMBOL}&tf=d&s=linear&ct=candle_stick"
    _urlopen(monkeypatch, exc=_redirect(chart, chart))
    status, out = api.handle("/api/v2/finviz-chart", method="GET", body=None, query={"symbol": [SYMBOL]})
    assert status == 502, f"a failed proxy must not answer {status}"
    assert out["ok"] is False
    assert "data" not in out


def test_a_plain_payload_still_gets_the_v2_envelope(api, monkeypatch):
    payload = {"rows": [1, 2]}
    monkeypatch.setitem(api.ROUTES, PROBE_PATH, lambda query=None: payload)
    status, out = api.handle(PROBE_PATH, method="GET", body=None, query={})
    assert (status, out) == (200, {"ok": True, "data": payload})


def test_a_handler_that_raises_is_still_a_500(api, monkeypatch):
    def boom():
        raise RuntimeError("lane reader unavailable")

    monkeypatch.setitem(api.ROUTES, PROBE_PATH, boom)
    status, out = api.handle(PROBE_PATH, method="GET", body=None, query={})
    assert status == 500 and out["ok"] is False


# ── the shape test ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "out,expected",
    [
        ((502, {"ok": False}), True),
        ((200, []), True),
        ((404, {"error": "x"}), True),
        ({"ok": True}, False),
        ([502, {"ok": False}], False),  # a JSON-shaped payload is not a status
        ((502, "text"), False),  # a body this API cannot serialize is not a status
        ((502,), False),
        ((502, {"a": 1}, 3), False),
        ((700, {"ok": False}), False),
        ((99, {"ok": False}), False),
        ((True, {"ok": False}), False),  # bool is an int subclass; it is never an HTTP status
        (("502", {"ok": False}), False),
    ],
)
def test_only_a_real_status_and_body_pair_is_a_response(api, out, expected):
    assert api._is_status_body(out) is expected


# ── the chart proxy's URL ─────────────────────────────────────────────────────────────────────────


def test_the_proxy_uses_the_public_chart_host_and_sends_no_cookie(api, monkeypatch):
    """The image host needs no session; forwarding FINVIZ_COOKIE to it would be exposure for nothing."""
    monkeypatch.setenv("FINVIZ_COOKIE", "synthetic-cookie-value")
    seen = []
    _urlopen(monkeypatch, payload=b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, seen=seen)
    api._finviz_chart({"symbol": [SYMBOL], "p": ["w"]})

    req = seen[0]
    parts = urllib.parse.urlsplit(req.full_url)
    assert parts.netloc == CHART_HOST
    assert parts.path == "/chart.ashx"
    query = urllib.parse.parse_qs(parts.query)
    assert query["t"] == [SYMBOL] and query["tf"] == ["w"]
    assert query["cs"] == ["l"] and query["ct"] == ["candle_stick"]
    assert "synthetic-cookie-value" not in str(req.header_items())


def test_an_unknown_timeframe_falls_back_to_daily_instead_of_reaching_the_url(api, monkeypatch):
    seen = []
    _urlopen(monkeypatch, payload=b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, seen=seen)
    api._finviz_chart({"symbol": [SYMBOL], "p": ["d&evil=1"]})
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(seen[0].full_url).query)
    assert query["tf"] == ["d"] and "evil" not in query


# ── the chart proxy's failure language ────────────────────────────────────────────────────────────


def test_a_self_redirect_is_named_as_a_loop_not_as_an_expired_cookie(api, monkeypatch):
    chart = f"https://{CHART_HOST}/chart.ashx?cs=l&t={SYMBOL}&tf=d&s=linear&ct=candle_stick"
    _urlopen(monkeypatch, exc=_redirect(chart, chart))
    out = api._finviz_chart({"symbol": [SYMBOL]})
    assert out[0] == 502
    assert out[1]["ok"] is False
    assert "redirected the request back to itself" in out[1]["error"], out[1]["error"]
    assert "cookie expired" not in out[1]["error"], "a loop cannot prove the cookie is the cause"


def test_a_redirect_to_the_login_page_is_named_as_an_expired_cookie(api, monkeypatch):
    chart = f"https://{CHART_HOST}/chart.ashx?cs=l&t={SYMBOL}"
    _urlopen(monkeypatch, exc=_redirect(chart, "https://finviz.com/login.ashx?redirect=chart"))
    out = api._finviz_chart({"symbol": [SYMBOL]})
    assert out[0] == 502
    assert "cookie expired" in out[1]["error"], out[1]["error"]


def test_a_non_redirect_http_error_stays_a_http_error(api, monkeypatch):
    _urlopen(
        monkeypatch,
        exc=urllib.error.HTTPError(f"https://{CHART_HOST}/chart.ashx", 503, "Service Unavailable", {}, None),
    )
    out = api._finviz_chart({"symbol": [SYMBOL]})
    assert out[0] == 502
    assert "cookie expired" not in out[1]["error"]
    assert "503" in out[1]["error"]


def test_a_login_page_instead_of_an_image_is_named_as_an_expired_cookie(api, monkeypatch):
    _urlopen(monkeypatch, payload=b"<html><body>Sign in to Finviz</body></html>")
    out = api._finviz_chart({"symbol": [SYMBOL]})
    assert out[0] == 502
    assert "cookie expired" in out[1]["error"]


def test_a_non_image_body_that_is_not_a_login_page_names_the_host(api, monkeypatch):
    _urlopen(monkeypatch, payload=b'{"error":"unknown symbol"}')
    out = api._finviz_chart({"symbol": [SYMBOL]})
    assert out[0] == 502
    assert "non-image" in out[1]["error"] and CHART_HOST in out[1]["error"]
    assert "cookie expired" not in out[1]["error"]


def test_a_png_is_returned_as_the_image_payload(api, monkeypatch):
    _urlopen(monkeypatch, payload=b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    out = api._finviz_chart({"symbol": [SYMBOL]})
    assert isinstance(out, dict), "a success keeps the payload shape, so the dispatcher wraps it"
    assert out["ok"] is True and out["symbol"] == SYMBOL
    assert out["image"].startswith("data:image/png;base64,")


def test_a_jpeg_is_returned_with_its_own_mime(api, monkeypatch):
    _urlopen(monkeypatch, payload=b"\xff\xd8\xff" + b"\x00" * 16)
    out = api._finviz_chart({"symbol": [SYMBOL]})
    assert out["image"].startswith("data:image/jpeg;base64,")


def test_a_malformed_symbol_is_rejected_before_any_request(api, monkeypatch):
    called = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: called.append(1))
    out = api._finviz_chart({"symbol": ["../etc"]})
    assert out == (400, {"ok": False, "error": "bad symbol"})
    assert not called
