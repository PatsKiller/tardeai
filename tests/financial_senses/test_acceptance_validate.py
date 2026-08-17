"""Provider-wide acceptance: every supported capability must validate cleanly.

This is the enforcement half of the FACT/CLAIM/MODEL_ESTIMATE boundary. If any
provider returns an internally invalid envelope, BaseProvider.query() downgrades
it to PARTIAL — but the canonical fixtures here must all return validate() == []
so we know the providers themselves are correct, not merely downgraded.
"""
from __future__ import annotations

from financial_senses.sec_provider import SecEdgarProvider
from financial_senses.macro_provider import FredAlfredProvider
from financial_senses.identity import OpenFigiProvider, ID_BB_GLOBAL
from financial_senses.stress_engine import PortfolioStressProvider
from financial_senses.factor_exposure import FactorOverlapProvider
from financial_senses.evidence_graph import ClaimEvidenceProvider
from financial_senses.critic import IndependentCriticProvider


class _Cursor:
    def __init__(self, rows, cols):
        self._rows = rows
        self.description = [(c,) for c in cols]

    def execute(self, q, p):
        return None

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows, cols):
        self._rows = rows
        self._cols = cols

    def cursor(self):
        return _Cursor(self._rows, self._cols)

    def close(self):
        pass


def _sec_fetcher(url: str) -> dict:
    if "company_tickers" in url:
        return {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
    if "/submissions/" in url:
        return {
            "name": "Apple Inc.",
            "tickers": ["AAPL"],
            "cik": "320193",
            "filings": {"recent": {"form": ["10-K", "10-Q", "4"], "filingDate": ["2024-11-01", "2024-08-01", "2024-09-10"],
                                    "accessionNumber": ["a", "b", "c"], "primaryDocument": ["x", "y", "z"]}},
        }
    if "/companyfacts/" in url:
        return {
            "facts": {
                "us-gaap": {
                    "Revenues": {"units": {"USD": [
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 100.0, "fp": "FY", "form": "10-K", "filed": "2024-02-01"},
                        {"start": "2024-01-01", "end": "2024-12-31", "val": 110.0, "fp": "FY", "form": "10-K", "filed": "2025-02-01"},
                    ]}},
                }
            }
        }
    return {}


class _Macro:
    def observations(self, *a, **k):
        return [{"date": "2024-06-01", "value": 5.5}]

    def latest(self, sid):
        return {"date": "2024-06-01", "value": 5.5}

    def latest_as_of(self, sid, ddate):
        return {"date": "2024-06-01", "value": 5.5}

    def observation_value(self, sid, obs, realtime_end=None):
        return 5.5

    def vintage_dates(self, sid, limit=10):
        return ["2024-06-01"]


def _identity_resolver(query):
    cand = {"figi": "BBG000B9XRY4", "ticker": "AAPL", "name": "Apple Inc.", "exchange": "XNAS", "security_type": "Common Stock", "currency": "USD"}
    jobs = []
    if query.get("ticker"):
        jobs.append({"identifier": "ticker", "id_type": "TICKER", "id_value": query["ticker"], "candidates": [cand], "warning": None})
    if query.get("figi"):
        jobs.append({"identifier": "figi", "id_type": ID_BB_GLOBAL, "id_value": query["figi"], "candidates": [cand], "warning": None})
    return jobs


def _sec():
    return SecEdgarProvider(
        conn_factory=lambda: _Conn([], ["filer_name", "transaction_type", "filing_date", "sec_url"]),
        cik_resolver=lambda s: "0000320193" if s == "AAPL" else "",
        fetcher=_sec_fetcher,
    )


def test_all_sec_capabilities_validate():
    p = _sec()
    checks = [
        p.query("sec.resolve_cik", {"symbol": "AAPL"}),
        p.query("sec.get_recent_filings", {"symbol": "AAPL"}),
        p.query("sec.get_form4_context", {"symbol": "AAPL"}),
        p.query("sec.get_company_facts", {"symbol": "AAPL"}),
        p.query("sec.get_filing_metadata", {"symbol": "AAPL"}),
        p.query("sec.compare_filing_facts", {"cik": "0000320193", "period_a": "2023-12-31", "period_b": "2024-12-31"}),
        p.query("sec.get_decision_evidence", {"symbol": "AAPL"}),
    ]
    for r in checks:
        assert r.validate() == [], (r.capability, r.validate())


def test_all_macro_capabilities_validate():
    p = FredAlfredProvider(api_key="k", client=_Macro())
    checks = [
        p.query("macro.get_series", {"series_id": "DFF"}),
        p.query("macro.get_latest_observation", {"series_id": "DFF"}),
        p.query("macro.get_vintage_dates", {"series_id": "DFF"}),
        p.query("macro.get_vintage", {"series_id": "DFF", "decision_date": "2024-12-31"}),
        p.query("macro.compare_vintages", {"series_id": "DFF", "decision_date": "2024-12-31"}),
        p.query("macro.get_decision_time_snapshot", {"series_ids": ["DFF"], "decision_date": "2024-12-31"}),
        p.query("macro.get_series_snapshot", {"series_ids": ["DFF"]}),
        p.query("macro.regime_inputs", {}),
    ]
    for r in checks:
        assert r.validate() == [], (r.capability, r.validate())


def test_identity_capability_validates():
    p = OpenFigiProvider(resolver=_identity_resolver)
    r = p.query("identity.resolve", {"ticker": "AAPL"})
    assert r.status == "OK"
    assert r.validate() == []


def test_stress_capability_validates():
    p = PortfolioStressProvider()
    r = p.query(
        "risk.stress_portfolio",
        {"portfolio": {"positions": [{"symbol": "AAPL", "market_value": 100000, "sector": "technology"}]},
         "scenario": {"scenario_id": "x", "shocks": {"sector_shocks": {"technology": -0.10}}}},
    )
    assert r.validate() == []


def test_factor_capability_validates():
    p = FactorOverlapProvider()
    r = p.query("factor.overlap", {
        "instrument_a": {"holdings": [{"symbol": "AAPL", "weight": 0.1}]},
        "instrument_b": {"holdings": [{"symbol": "AAPL", "weight": 0.08}]},
    })
    assert r.validate() == []


def test_evidence_capability_validates():
    p = ClaimEvidenceProvider()
    r = p.query("evidence.build_graph", {
        "nodes": [
            {"id": "f1", "type": "FACT", "text": "revenue grew", "source": "PRIMARY_REGULATORY", "observed_at": "2024-12-31", "quality": "HIGH", "freshness": "FRESH"},
            {"id": "c1", "type": "CLAIM", "text": "growing", "claim_type": "thesis"},
        ],
        "edges": [{"id": "e1", "from_id": "f1", "to_id": "c1", "relation": "SUPPORTS"}],
    })
    assert r.validate() == []


def test_critic_capability_validates():
    p = IndependentCriticProvider()
    r = p.query("critic.review", {
        "evidence": {"identity_status": "RESOLVED", "facts": []},
        "proposed_action": {"action": "hold"},
    })
    assert r.validate() == []
