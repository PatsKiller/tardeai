"""Finviz cookie / export body classification (credential_monitor + health_agent)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from credential_monitor import (  # noqa: E402
    classify_finviz_export_body,
    is_finviz_cookie_failure_text,
)
from health_agent import _CTA_BY_TYPE, _data_source_retry_cmd  # noqa: E402

POLICY = json.loads((ROOT / "config" / "health_agent_policy.json").read_text())

CSV_OK = "No.,Ticker,Company,Price\n1,AAA,Acme,10.00\n2,BBB,Beta,20.00\n"
LOGIN_HTML = (
    "<!DOCTYPE html><html><head><title>Finviz</title></head>"
    "<body>Please sign in to continue. <a href='/login'>Login</a></body></html>"
)
# HTML shell that mentions Ticker later — previously false-positived as OK.
HTML_WITH_TICKER_LATER = (
    "<html><body>" + ("x" * 480) + "Ticker is a column name in the export</body></html>"
)


def test_classify_accepts_csv_with_ticker_header():
    r = classify_finviz_export_body(CSV_OK)
    assert r["status"] == "ok"


def test_classify_rejects_login_html():
    r = classify_finviz_export_body(LOGIN_HTML)
    assert r["status"] == "expired"
    assert "login" in (r.get("error") or "").lower() or "Cookie" in (r.get("error") or "")


def test_classify_rejects_html_shell_even_if_ticker_appears_late():
    r = classify_finviz_export_body(HTML_WITH_TICKER_LATER)
    assert r["status"] != "ok"
    assert "Ticker" in HTML_WITH_TICKER_LATER  # would have fooled the old anywhere-match


def test_classify_rejects_missing_ticker_in_head():
    body = "No.,Symbol,Price\n1,AAA,1\n" + ("pad," * 100)
    r = classify_finviz_export_body(body)
    assert r["status"] == "error"
    assert "Ticker" in (r.get("error") or "")


def test_cookie_failure_text_markers():
    assert is_finviz_cookie_failure_text("cookie expired — login page")
    assert is_finviz_cookie_failure_text("screener returned zero rows")
    assert is_finviz_cookie_failure_text("0 tickers after download")
    assert not is_finviz_cookie_failure_text("rate limit 429 retry later")


def test_finviz_cookie_error_skips_quotes_auto_retry():
    cmd = _data_source_retry_cmd(
        POLICY,
        "data_source_stale",
        {"type": "data_source_stale", "source": "finviz",
         "last_error": "FINVIZ_COOKIE expired — login page returned"},
    )
    assert cmd is None


def test_finviz_transient_stale_still_allows_quotes_retry():
    cmd = _data_source_retry_cmd(
        POLICY,
        "data_source_stale",
        {"type": "data_source_stale", "source": "finviz",
         "last_error": "timeout contacting elite.finviz.com"},
    )
    assert cmd == ".venv/bin/python scripts/external_market_data_ingest.py --quotes"


def test_finviz_cookie_expired_cta_points_at_admin_secrets():
    cta = _CTA_BY_TYPE["finviz_cookie_expired"]
    assert "Admin" in cta["route"] or "admin" in cta["route"].lower()
    assert "system" in cta["route"]
