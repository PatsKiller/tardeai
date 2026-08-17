"""Dry financial-advisory replay.

Runs the read-only providers over deterministic fixture data (no network, no
live DB, no Telegram) and assembles a per-case evidence-enrichment report. The
providers enrich evidence; they never change live decisions and never suggest
actions. This module is the evidence for acceptance gate FS-26.
"""
from __future__ import annotations

from .identity import OpenFigiProvider, resolve_identity
from .stress_engine import PortfolioStressProvider, get_scenario
from .factor_exposure import overlap_report
from .evidence_graph import build_graph
from .critic import IndependentCriticProvider, review_decision
from .sec_filing_diff import compare_filing_facts
from .macro_provider import FredAlfredProvider

# Replay macro client: vintage-aware fixture. A later revision (5.9) must never
# leak into the 2024 decision snapshot (which knew 5.5).
class _ReplayMacro:
    _obs = [
        {"date": "2024-06-01", "value": 5.5},
        {"date": "2025-01-01", "value": 5.9},
    ]

    def observations(self, series_id, realtime_start=None, realtime_end=None):
        if realtime_end:
            return [o for o in self._obs if o["date"] <= realtime_end]
        return list(self._obs)

    def latest(self, series_id):
        return self._obs[-1]

    def value_as_of(self, series_id, decision_date):
        e = [o for o in self._obs if o["date"] <= decision_date]
        return e[-1] if e else None

    def vintage_dates(self, series_id, limit=10):
        return ["2024-06-01", "2025-01-01"]


def _identity(ticker, figi=None, ambiguous=False):
    if ambiguous:
        return {"identity_status": "AMBIGUOUS", "ticker": ticker}
    return {"identity_status": "RESOLVED", "figi": figi or f"BBG{ticker}", "ticker": ticker}


def _run_case(case: dict) -> dict:
    out = {"case": case["name"]}

    # Identity
    if "identity" in case:
        ident = case["identity"]
        out["identity"] = _identity(
            ident.get("ticker"), ident.get("figi"), ident.get("ambiguous", False)
        )

    # SEC company facts + filing diff (fixtures)
    if case.get("facts_a") and case.get("facts_b"):
        out["sec_filing_diff"] = compare_filing_facts(case["facts_a"], case["facts_b"])

    # Macro vintage (if requested)
    if case.get("macro_decision_date"):
        m = _ReplayMacro()
        prov = FredAlfredProvider(api_key="fixture", client=m)
        out["macro_vintage"] = prov.query(
            "macro.compare_vintages",
            {"series_id": "DFF", "decision_date": case["macro_decision_date"]},
        ).data

    # Stress
    if case.get("portfolio"):
        sp = PortfolioStressProvider()
        sc = get_scenario(case.get("scenario", "broad_equity_minus_10"))
        out["stress"] = sp.query(
            "risk.stress_portfolio",
            {"portfolio": case["portfolio"], "scenario": sc.to_dict() if sc else case.get("scenario", "broad_equity_minus_10")},
        ).data

    # Factor overlap
    if case.get("instrument_a") and case.get("instrument_b"):
        out["overlap"] = overlap_report(case["instrument_a"], case["instrument_b"])

    # Evidence graph
    if case.get("nodes"):
        g = build_graph(case["nodes"], case.get("edges", []))
        out["evidence_graph"] = g.to_dict()

    # Critic (shadow-only)
    crit = IndependentCriticProvider()
    review = review_decision(case.get("evidence", {}), case.get("proposed_action", {}))
    out["critic"] = crit.query(
        "critic.review",
        {"evidence": case.get("evidence", {}), "proposed_action": case.get("proposed_action", {})},
    ).data

    # Read-only guarantee: no tool may emit a trade/action instruction.
    out["suggested_action"] = False
    return out


CASES: list[dict] = [
    {
        "name": "SCHD concentration challenge",
        "identity": {"ticker": "SCHD", "figi": "BBG000C3V7P5"},
        "portfolio": {
            "positions": [
                {"symbol": "SCHD", "market_value": 150000, "sector": "equity_income"},
                {"symbol": "VYM", "market_value": 120000, "sector": "equity_income"},
                {"symbol": "CASH", "market_value": 30000, "cash_like": True},
            ]
        },
        "scenario": "broad_equity_minus_10",
        "instrument_a": {"holdings": [{"symbol": "AAPL", "weight": 0.1}, {"symbol": "JNJ", "weight": 0.1}], "sectors": {"equity_income": 1.0}},
        "instrument_b": {"holdings": [{"symbol": "AAPL", "weight": 0.08}, {"symbol": "JNJ", "weight": 0.09}], "sectors": {"equity_income": 1.0}},
        "proposed_action": {"action": "trim", "objective": "reduce concentration"},
        "evidence": {"identity_status": "RESOLVED", "facts": []},
    },
    {
        "name": "cash HOLD/WAIT",
        "portfolio": {"positions": [{"symbol": "CASH", "market_value": 50000, "cash_like": True}]},
        "scenario": "broad_equity_minus_20",
        "proposed_action": {"action": "hold"},
        "evidence": {"identity_status": "RESOLVED", "facts": []},
    },
    {
        "name": "one re-entry WAIT",
        "identity": {"ticker": "XYZ", "ambiguous": True},
        "proposed_action": {"action": "reentry"},
        "evidence": {"identity_status": "AMBIGUOUS", "facts": []},
    },
    {
        "name": "one new-position case",
        "identity": {"ticker": "AAPL", "figi": "BBG000B9XRY4"},
        "facts_a": {"Revenues": {"value": 383285000000, "units": "USD"}},
        "facts_b": {"Revenues": {"value": 391035000000, "units": "USD"}},
        "portfolio": {
            "positions": [
                {"symbol": "AAPL", "market_value": 50000, "sector": "technology"},
                {"symbol": "CASH", "market_value": 50000, "cash_like": True},
            ]
        },
        "scenario": "nasdaq_minus_25",
        "proposed_action": {"action": "hold"},
        "evidence": {"identity_status": "RESOLVED", "facts": []},
    },
    {
        "name": "one large ETF/fund holding",
        "identity": {"ticker": "VOO", "figi": "BBG000C3S3X0"},
        "instrument_a": {"holdings": [{"symbol": "AAPL", "weight": 0.07}, {"symbol": "MSFT", "weight": 0.06}]},
        "instrument_b": {"holdings": [{"symbol": "AAPL", "weight": 0.07}, {"symbol": "MSFT", "weight": 0.06}]},
        "proposed_action": {"action": "hold"},
        "evidence": {"identity_status": "RESOLVED", "facts": []},
    },
    {
        "name": "company with recent SEC filing",
        "identity": {"ticker": "AAPL", "figi": "BBG000B9XRY4"},
        "facts_a": {
            "Revenues": {"value": 383285000000, "units": "USD"},
            "NetIncomeLoss": {"value": 96995000000, "units": "USD"},
        },
        "facts_b": {
            "Revenues": {"value": 391035000000, "units": "USD"},
            "NetIncomeLoss": {"value": 93736000000, "units": "USD"},
        },
        "macro_decision_date": "2024-12-31",
        "nodes": [
            {"id": "f1", "type": "FACT", "text": "revenue grew", "source": "PRIMARY_REGULATORY", "observed_at": "2024-12-31", "quality": "HIGH"},
            {"id": "c1", "type": "CLAIM", "text": "company is growing", "claim_type": "thesis"},
        ],
        "edges": [{"id": "e1", "from_id": "f1", "to_id": "c1", "relation": "SUPPORTS"}],
        "proposed_action": {"action": "hold"},
        "evidence": {"identity_status": "RESOLVED", "facts": []},
    },
]


def run_dry_replay() -> dict:
    report = {"authority": "READ_ONLY_ADVISORY", "cases": []}
    for case in CASES:
        report["cases"].append(_run_case(case))
    report["summary"] = {
        "cases": len(report["cases"]),
        "suggested_actions": sum(1 for c in report["cases"] if c.get("suggested_action")),
        "production_mutations": 0,
        "telegram_sends": 0,
    }
    return report


if __name__ == "__main__":
    import json

    print(json.dumps(run_dry_replay(), indent=2, default=str))
