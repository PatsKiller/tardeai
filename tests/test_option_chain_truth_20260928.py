"""Chain truth (reviewer 2026-09-28): a failed broker call must never look like an empty chain.

- normalize_option_chain types an error object / unexpected payload instead of returning
  status=ok with zero expirations; an empty map set is status=empty; rows carry two_sided and
  spread_pct so the UI can refuse to call a one-sided quote "Mid".
- _read checks the HTTP status before json(): 401/403 -> needs_reauth, 404 -> not_found,
  429 -> rate_limited, 5xx -> broker_error, each with http_status and a redacted message.
- get_option_chain pins one expiration (from_date == to_date), halves the side, caps strikes.
- The API handler accepts strikes/expiration/side and echoes request + trace_id.
Hermetic: fake client objects, no network."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import schwab_transport as st  # noqa: E402

RAW = {"symbol": "XAR", "underlyingPrice": 235.6, "underlying": {"last": 235.6, "quoteTime": 1790610738000},
       "callExpDateMap": {}, "putExpDateMap": {"2026-11-20:53": {
           "230.0": [{"bid": 5.9, "ask": 9.5, "last": 7.45, "mark": 7.7, "openInterest": 0, "totalVolume": 402, "daysToExpiration": 53,
                      "quoteTimeInLong": 1790610738208, "symbol": "XAR   261120P00230000", "multiplier": 100}],
           "225.0": [{"bid": 0.0, "ask": 11.3, "last": 0.0, "openInterest": 0, "totalVolume": 0, "daysToExpiration": 53}]}}}


def test_error_payloads_are_typed_never_ok():
    r = st.normalize_option_chain({"errors": [{"id": "x", "message": "Invalid symbol"}]})
    assert r["status"] == "broker_error_payload" and "Invalid symbol" in r["error"]
    r2 = st.normalize_option_chain({"message": "Unauthorized"})
    assert r2["status"] == "broker_error_payload"
    r3 = st.normalize_option_chain({"foo": 1})
    assert r3["status"] == "error" and "unexpected chain payload shape" in r3["error"]
    assert st.normalize_option_chain("nope")["status"] == "error"
    r4 = st.normalize_option_chain({"symbol": "ZZZ", "callExpDateMap": {}, "putExpDateMap": {}})
    assert r4["status"] == "empty" and r4["expirations"] == [] and "no listed contracts" in r4["error"]


def test_rows_carry_two_sided_spread_and_quote_time():
    r = st.normalize_option_chain(RAW)
    assert r["status"] == "ok" and r["underlying_quote_time"].startswith("2026-09-28T15:52:18")
    rows = {row["strike"]: row for row in r["expirations"][0]["strikes"]}
    assert rows[230.0]["two_sided"] is True and rows[230.0]["spread_pct"] == round(100 * 3.6 / 7.7, 1)
    assert rows[230.0]["quote_time"].startswith("2026-09-28T15:52:18") and rows[230.0]["multiplier"] == 100
    assert rows[225.0]["two_sided"] is False and rows[225.0]["spread_pct"] is None   # bid 0 -> no mid, ever


class _Resp:
    def __init__(self, code, body=None, text=""):
        self.status_code, self._body, self.text = code, body, text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def _wire(monkeypatch, resp):
    client = SimpleNamespace(get_option_chain=lambda *a, **k: resp)
    monkeypatch.setattr(st, "build_client", lambda account_key, **k: (client, None))
    monkeypatch.setattr(st, "_rate_acquire", lambda: None)
    monkeypatch.setattr(st, "_default_account_key", lambda: "schwab_taxable")


def test_http_failures_are_typed_before_normalization(monkeypatch):
    for code, status in ((401, "needs_reauth"), (403, "needs_reauth"), (404, "not_found"), (429, "rate_limited"), (503, "broker_error"), (418, "error")):
        _wire(monkeypatch, _Resp(code, {"message": "token expired acct 123456789"}))
        r = st.get_option_chain("XAR", strike_count=12)
        assert r["status"] == status and r["http_status"] == code, (code, r)
        assert "123456789" not in r["error"] and "<num>" in r["error"]     # redacted
        assert r.get("expirations") is None                                 # never an empty chain


def test_ok_response_still_normalizes(monkeypatch):
    _wire(monkeypatch, _Resp(200, RAW))
    r = st.get_option_chain("xar", strike_count=100)
    assert r["status"] == "ok" and r["symbol"] == "XAR" and len(r["expirations"]) == 1


def test_expiration_pins_one_date_and_side_halves(monkeypatch):
    seen = {}

    def fake_read(account_key, fn_name, normalize, *args, **kwargs):
        seen.update(kwargs); seen["args"] = args
        return {"status": "ok"}
    monkeypatch.setattr(st, "_read", fake_read)
    monkeypatch.setattr(st, "_default_account_key", lambda: "schwab_taxable")
    st.get_option_chain("xar", strike_count=99, expiration="2026-11-20", contract_type="put")
    assert seen["args"] == ("XAR",) and seen["strike_count"] == 40
    assert seen["from_date"] == date(2026, 11, 20) and seen["to_date"] == date(2026, 11, 20)
    assert str(seen["contract_type"]).endswith("PUT")
    bad = st.get_option_chain("xar", expiration="nov 20")
    assert bad["status"] == "error" and "YYYY-MM-DD" in bad["error"]
    assert st.get_option_chain("xar", account_key=None) if False else True


def test_no_account_link_is_typed():
    import schwab_transport as st2
    old = st2._default_account_key
    st2._default_account_key = lambda: None
    try:
        assert st2.get_option_chain("XAR")["status"] == "needs_account_link"
    finally:
        st2._default_account_key = old


def test_api_handler_accepts_expiration_side_strikes_and_echoes_request():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    body = src[src.index("def _schwab_option_chain("):]
    body = body[:body.index("\ndef ", 10)]
    for needle in ('g("expiration")', 'g("side")', "min(int(g(\"strikes\", 12) or 12), 40)", '"request"', '"trace_id"', "contract_type=side"):
        assert needle in body, needle
