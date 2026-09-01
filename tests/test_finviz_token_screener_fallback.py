"""Finviz screener CSV auth: cookie first, FINVIZ_API_TOKEN &auth= fallback."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# finviz_ingestion imports pandas/yaml/requests at module load — stub for unit tests.
for _mod in ("pandas", "yaml", "requests"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

import finviz_ingestion as fi  # noqa: E402
import finviz_screener_runner as fsr  # noqa: E402


class _Resp:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.headers = {}


CSV_BODY = "No.,Ticker,Price\n1,AAA,10.00\n2,BBB,20.00\n"
LOGIN_BODY = "<html><body>Please sign in to continue</body></html>"


def test_append_auth_token_appends_once():
    url = "https://elite.finviz.com/export?v=152&f=fa_pe_u25"
    out = fi._append_auth_token(url, "tok123")
    assert out.endswith("auth=tok123")
    assert fi._append_auth_token(out, "tok123") == out


def test_download_screener_csvs_falls_back_to_token(monkeypatch, tmp_path):
    screeners = {"test_screener": {"finviz_url": "https://elite.finviz.com/screener.ashx?v=152&f=fa_pe_u25"}}

    def fake_optional(name, default=""):
        if name == "FINVIZ_COOKIE":
            return "stale=1"
        if name == "FINVIZ_API_TOKEN":
            return "elite_token"
        if name == "FINVIZ_USER_AGENT":
            return "pytest"
        return default

    monkeypatch.setattr(fi, "optional_env", fake_optional)

    calls: list[tuple[bool, str | None]] = []

    def fake_fetch(export_url, name, *, use_cookie, token):
        calls.append((use_cookie, token))
        if use_cookie:
            return _Resp(LOGIN_BODY), "v=152", False, False
        return _Resp(CSV_BODY), "v=152", True, False

    monkeypatch.setattr(fi, "_fetch_screener_export", fake_fetch)

    rows = fi.download_screener_csvs(screeners, tmp_path)
    assert len(rows) == 1
    assert calls[0][0] is True
    assert calls[1] == (False, "elite_token")
    assert (tmp_path / rows[0]["path"].name).exists() or rows[0]["path"].exists()


def test_download_screener_csvs_uses_token_when_no_cookie(monkeypatch, tmp_path):
    screeners = {"solo": {"finviz_url": "https://elite.finviz.com/screener.ashx?v=152"}}

    def fake_optional(name, default=""):
        if name == "FINVIZ_API_TOKEN":
            return "only_token"
        if name == "FINVIZ_USER_AGENT":
            return "pytest"
        return ""

    monkeypatch.setattr(fi, "optional_env", fake_optional)
    seen: list[bool] = []

    def fake_fetch(export_url, name, *, use_cookie, token):
        seen.append(use_cookie)
        assert token == "only_token"
        return _Resp(CSV_BODY), "v=152", True, False

    monkeypatch.setattr(fi, "_fetch_screener_export", fake_fetch)
    rows = fi.download_screener_csvs(screeners, tmp_path)
    assert len(rows) == 1
    assert seen == [False]


def test_screener_runner_token_fallback():
    with patch.object(fsr, "_http_get") as mock_get:
        mock_get.side_effect = [
            LOGIN_BODY,
            CSV_BODY,
        ]

        tickers = fsr._fetch_screener_tickers(
            "https://elite.finviz.com/screener.ashx?v=152",
            cookie="stale=1",
            token="elite_token",
        )
        assert tickers == ["AAA", "BBB"]
        assert mock_get.call_count == 2
        token_url = mock_get.call_args_list[1][0][0]
        assert "auth=elite_token" in token_url


def test_screener_runner_token_only(monkeypatch):
    with patch.object(fsr, "_http_get", return_value=CSV_BODY) as mock_get:
        tickers = fsr._fetch_screener_tickers(
            "https://elite.finviz.com/screener.ashx?v=152",
            cookie="",
            token="elite_token",
        )
        assert tickers == ["AAA", "BBB"]
        assert "auth=elite_token" in mock_get.call_args[0][0]
