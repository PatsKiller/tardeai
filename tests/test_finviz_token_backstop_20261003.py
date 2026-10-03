"""Finviz Elite API token backstop for every cookie-only path. Pure: no network, no DB.

2026-10-03: the site banner said "cookie expired — screener and social scalp empty"
while all 45 screeners were returning rows through FINVIZ_API_TOKEN. The health
check, banner, movers, industry groups, filter validator and preflights only knew
the cookie. A dead cookie with a working token is now healthy with a rotation note;
degraded only when both fail; no secret value ever reaches a recorded string.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import finviz_auth  # noqa: E402
import finviz_health_check as fhc  # noqa: E402

COOKIE = "c.ASPXAUTH=cookie-secret-value-xyz"
TOKEN = "token-secret-value-abc123"
CSV = "No.,Ticker,Company,Price,Change,Volume\n1,AAA,A Co,10,5.0%,100\n2,BBB,B Co,20,-1.0%,200\n"


def _secrets(monkeypatch, module, cookie=COOKIE, token=TOKEN):
    values = {"FINVIZ_COOKIE": cookie, "FINVIZ_API_TOKEN": token}
    monkeypatch.setattr(finviz_auth, "finviz_secret", lambda name: values.get(name, ""))
    if hasattr(module, "_env"):
        monkeypatch.setattr(module, "_env", lambda key, default="": values.get(key, default or ""))


def _no_secret(*texts):
    for text in texts:
        assert COOKIE not in str(text) and TOKEN not in str(text), f"secret leaked into: {text!r}"


class _Cur:
    def __init__(self, sink):
        self.sink = sink

    def execute(self, sql, params=()):
        self.sink.append((sql, params))


class _Conn:
    def __init__(self, sink):
        self.sink = sink

    def cursor(self):
        return _Cur(self.sink)

    def commit(self):
        pass

    def close(self):
        pass


def _health(monkeypatch, outcomes):
    """Run check() with a fake probe; outcomes maps 'cookie'/'token' to (rows, err) or an exception."""
    seen, writes = [], []
    _secrets(monkeypatch, fhc)
    monkeypatch.setattr(fhc, "_get_conn", lambda: _Conn(writes))

    def probe(url, headers):
        kind = "token" if "auth=" in url else "cookie"
        seen.append((kind, url, dict(headers)))
        out = outcomes[kind]
        if isinstance(out, Exception):
            raise out
        return out

    return fhc.check(probe=probe), seen, writes


def test_cookie_expired_token_ok_is_healthy_with_a_rotation_note(monkeypatch):
    result, seen, writes = _health(monkeypatch, {"cookie": (0, "zero rows / login page"), "token": (42, None)})
    assert result["status"] == "healthy" and result["credential"] == "token" and result["row_count"] == 42
    assert "cookie failed" in result["error"] and "token OK" in result["error"]
    (sql, params), = writes
    assert "status='healthy'" in sql and "degraded=false" in sql
    assert params[1] == result["error"], "the note is recorded, not cleared"
    _no_secret(result["error"], params)


def test_both_failing_is_degraded_and_redacted(monkeypatch):
    leak = RuntimeError(f"HTTPSConnectionPool: Max retries for url /export?v=152&auth={TOKEN}&o=-price")
    result, _, writes = _health(monkeypatch, {"cookie": (0, "zero rows / login page"), "token": leak})
    assert result["status"] == "degraded"
    assert "cookie failed" in result["error"] and "token failed" in result["error"]
    assert "auth=<redacted>" in result["error"]
    (sql, params), = writes
    assert "degraded=true" in sql
    _no_secret(result["error"], params)


def test_working_cookie_never_spends_a_token_request(monkeypatch):
    result, seen, _ = _health(monkeypatch, {"cookie": (30, None), "token": (99, None)})
    assert result["credential"] == "cookie" and result["error"] is None
    assert [k for k, _, _ in seen] == ["cookie"]


def test_token_only_on_the_token_attempt(monkeypatch):
    _, seen, _ = _health(monkeypatch, {"cookie": (0, "x"), "token": (5, None)})
    (k1, u1, h1), (k2, u2, h2) = seen
    assert "auth=" not in u1 and h1.get("Cookie") == COOKIE
    assert u2.endswith(f"auth={TOKEN}") and "Cookie" not in h2


def test_redact_strips_auth_params_and_named_secrets():
    text = f"GET https://elite.finviz.com/export?v=1&auth={TOKEN}&o=2 cookie={COOKIE}"
    out = finviz_auth.redact(text, COOKIE, TOKEN)
    _no_secret(out)
    assert "auth=<redacted>&o=2" in out
    assert finviz_auth.with_auth_token("https://e/x?v=1", "t") == "https://e/x?v=1&auth=t"
    assert finviz_auth.with_auth_token("https://e/x?auth=t", "t") == "https://e/x?auth=t"


def test_market_movers_fall_back_to_token_on_empty_cookie_export(monkeypatch):
    import finviz_market_movers as fmm

    _secrets(monkeypatch, fmm)
    calls = []

    def get_csv(url, headers):
        calls.append((url, dict(headers)))
        return "" if "Cookie" in headers else CSV

    monkeypatch.setattr(fmm, "_get_csv", get_csv)
    rows = fmm._fetch_signal("ta_topgainers", COOKIE, TOKEN)
    assert [r["symbol"] for r in rows] == ["AAA", "BBB"]
    (u1, h1), (u2, h2) = calls
    assert "auth=" not in u1 and h1["Cookie"] == COOKIE
    assert "/export?" in u2 and u2.endswith(f"auth={TOKEN}") and "Cookie" not in h2

    calls.clear()
    monkeypatch.setattr(fmm, "_get_csv", lambda url, headers: (calls.append(url), CSV)[1])
    assert len(fmm._fetch_signal("ta_topgainers", COOKIE, TOKEN)) == 2
    assert len(calls) == 1, "a working cookie export must not also spend a token request"


def test_industry_groups_fall_back_to_token(monkeypatch):
    import finviz_industry_groups as fig

    _secrets(monkeypatch, fig)
    monkeypatch.setattr(fig, "_cookie", lambda: COOKIE)
    groups_csv = "No.,Name,Performance (Week),Change,Stocks\n1,Semiconductors,2.0%,1.0%,40\n"
    calls = []

    def get_csv(url, headers):
        calls.append(url)
        return "" if "Cookie" in headers else groups_csv

    monkeypatch.setattr(fig, "_get_csv", get_csv)
    rows = fig.fetch_groups()
    assert rows and rows[0]["industry"] == "Semiconductors"
    assert calls == [fig.URL, f"{fig.URL}&auth={TOKEN}"]


def test_filter_validator_uses_one_credential_for_baseline_and_tokens(monkeypatch):
    import finviz_filter_validator as fv

    _secrets(monkeypatch, fv)
    seen = []

    def rows(url, cookie, token=""):
        seen.append(bool(token))
        if not token:
            raise RuntimeError("non-CSV response: '<html>login'")
        return 100 if "&f=" not in url else 40

    monkeypatch.setattr(fv, "_rows", rows)
    rep = fv.validate(["cap_mega"], cookie=COOKIE, api_token=TOKEN)
    assert rep["ok"] is True and rep["credential"] == "token"
    assert rep["results"]["cap_mega"]["state"] == fv.APPLIED
    assert seen == [False, True, True], "baseline and token row counts must share the token credential"


def test_banner_cookie_dead_token_ok_is_informational(monkeypatch):
    import api_v2
    import secret_validators as sv

    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: {"last_error": "cookie failed: zero rows / login page; token OK"})
    values = {"FINVIZ_COOKIE": COOKIE, "FINVIZ_API_TOKEN": TOKEN}
    monkeypatch.setattr(sv, "_key", lambda name: values.get(name))
    monkeypatch.setattr(sv, "_finviz_cookie", lambda k: (False, "login page or empty export — cookie expired"))
    monkeypatch.setattr(sv, "_finviz_token", lambda k: (True, "37 screener rows"))
    out = api_v2._finviz_credential_health()
    assert out["ok"] is True and out["status"] == "token_ok" and out["show_banner"] is False
    assert "token OK" in out["message"] and "empty" not in out["message"]
    _no_secret(out)

    monkeypatch.setattr(sv, "_finviz_token", lambda k: (False, "token rejected or empty export"))
    out = api_v2._finviz_credential_health()
    assert out["ok"] is False and out["show_banner"] is True
    assert "both failing" in out["message"]
    _no_secret(out)


def test_token_validator_probes_with_auth_and_never_echoes_it(monkeypatch):
    import secret_validators as sv

    seen = {}

    class Resp:
        status_code = 200
        text = CSV

    def probe(url, headers):
        seen.update(url=url, headers=headers)
        return Resp()

    monkeypatch.setattr(sv, "finviz_probe", probe)
    monkeypatch.setattr(sv, "_key", lambda name: None)
    ok, detail = sv._finviz_token(TOKEN)
    assert ok is True and detail == "2 screener rows"
    assert seen["url"].endswith(f"auth={TOKEN}") and "Cookie" not in seen["headers"]
    _no_secret(detail)
