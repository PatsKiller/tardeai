"""Optional, bounded, read-only live smoke harness for financial-senses providers.

This is deliberately separate from the unit-test PASS. It performs a small
number of read-only official API calls so an operator can confirm the adapters
work against the real services without running the full offline suite.

Policy:
  * SEC  — no credentials required; performs bounded read-only calls.
  * FRED — only if FRED_API_KEY is set.
  * OpenFIGI — only if OPENFIGI_API_KEY is set.
  * No production writes. No DB writes. No Telegram. No service restart.

Run:  python3 -m financial_senses.live_smoke
"""
from __future__ import annotations

import os
from typing import Any

from . import sec_companyfacts_reader as reader
from .macro_provider import FredClient
from .identity import OpenFigiProvider


def _sec_smoke() -> dict:
    out: dict = {"state": "OK", "checks": {}}
    try:
        ticks = reader._default_fetcher("https://www.sec.gov/files/company_tickers.json")
        out["checks"]["company_tickers"] = bool(ticks)
    except Exception as exc:  # noqa: BLE001
        out["checks"]["company_tickers"] = f"FAIL: {exc}"

    try:
        sub = reader.get_submissions("0000320193")
        out["checks"]["submissions"] = "OK" if sub else "EMPTY"
    except Exception as exc:  # noqa: BLE001
        out["checks"]["submissions"] = f"FAIL: {exc}"

    try:
        facts = reader.get_company_facts("0000320193")
        lv = reader.latest_values(facts)
        out["checks"]["companyfacts"] = f"OK ({len(lv)} tags)"
    except Exception as exc:  # noqa: BLE001
        out["checks"]["companyfacts"] = f"FAIL: {exc}"

    try:
        concept = reader.get_company_concept("0000320193", "AccountsPayableCurrent")
        out["checks"]["companyconcept_camelcase"] = "OK" if concept else "EMPTY"
    except Exception as exc:  # noqa: BLE001
        out["checks"]["companyconcept_camelcase"] = f"FAIL: {exc}"

    return out


def _fred_smoke() -> dict:
    key = os.environ.get("FRED_API_KEY") or ""
    if not key:
        return {"state": "NOT_CONFIGURED"}
    try:
        client = FredClient(key)
        latest = client.latest("DFF")
        vd = client.vintage_dates("DFF", limit=3)
        return {
            "state": "OK",
            "latest_dff": latest,
            "vintage_dates_sample": vd,
        }
    except Exception as exc:  # noqa: BLE001
        return {"state": "FAIL", "error": str(exc)}


def _figi_smoke() -> dict:
    key = os.environ.get("OPENFIGI_API_KEY") or ""
    if not key:
        return {"state": "NOT_CONFIGURED"}
    try:
        prov = OpenFigiProvider(api_key=key)
        jobs = prov._openfigi_resolve({"ticker": "AAPL"})
        return {"state": "OK", "jobs": jobs}
    except Exception as exc:  # noqa: BLE001
        return {"state": "FAIL", "error": str(exc)}


def run_live_smoke() -> dict:
    return {
        "authority": "READ_ONLY_ADVISORY",
        "production_mutations": 0,
        "telegram_sends": 0,
        "production_db_writes": 0,
        "SEC": _sec_smoke(),
        "FRED": _fred_smoke(),
        "OpenFIGI": _figi_smoke(),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_live_smoke(), indent=2, default=str))
