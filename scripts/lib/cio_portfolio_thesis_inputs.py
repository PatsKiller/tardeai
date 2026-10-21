"""Read-only inputs for the CIOPortfolioThesis@v1 materializer, without importing the API module.

Lane ``cio-portfolio-thesis`` (n8n dispatcher, 2026-10-21, operator "yes rebuild 1417"). The
materializer used to import ``scripts/api_v3_cio.py`` for five getters; that module's import closure
reaches ``api_v2`` and therefore broker and order-route modules, which an n8n-allowlisted lane may not
reach (tests/test_lane_transitive_capabilities_20261015.py, no baseline exception). This module reads
the same inputs from the same stores and the same environment overrides as the API getters
``get_operator_investment_policy``, ``get_portfolio_state_v1``, ``get_market_context_state_v1``,
``get_seasonality_state_v1`` and ``_ratified_methodology_refs``; parity is pinned by
tests/test_cio_portfolio_thesis_lane_20261021.py.

Every function here is read-only: file reads, and a PostgreSQL session opened READ ONLY by
``cio_market_context_state.connect_trade_ai_readonly``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: The sector set the API's seasonality getter reads (api_v3_cio.get_seasonality_state_v1).
SEASONALITY_SYMBOLS = (
    "SPY", "XLB", "XLC", "XLE", "XLF", "XLI",
    "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY",
)


def _path(env_name: str, *default: str) -> Path:
    configured = str(os.getenv(env_name) or "").strip()
    return Path(configured) if configured else PROJECT_ROOT.joinpath(*default)


def operator_policy_store() -> Path:
    return _path("CIO_OPERATOR_PROFILE_JSONL", "data", "cio", "operator_profile.jsonl")


def holdings_path() -> Path:
    # The store's relative path comes from scripts/lib/portfolio_positions.STORE_REL, the position store's one
    # definition, not a holdings-file literal here (tests/test_portfolio_price_truth_20261005.py ratchets direct
    # readers; the document is still read by cio_portfolio_state_v1.load_holdings_document). Same resolved path as
    # before: TRADEAI_HOLDINGS_JSON, else under PROJECT_ROOT. Release-1 integration fix, 2026-10-21.
    from scripts.lib.portfolio_positions import STORE_REL

    return _path("TRADEAI_HOLDINGS_JSON", *STORE_REL)


def cash_evidence_path() -> Path:
    return _path("CIO_CASH_EVIDENCE_JSON", "data", "cio", "portfolio_cash_evidence.json")


def portfolio_thesis_store() -> Path:
    return _path("CIO_PORTFOLIO_THESIS_JSONL", "data", "cio", "cio_portfolio_theses.jsonl")


def symbol_thesis_projection_path() -> Path:
    return _path("CIO_THESES_PROJECTION_JSON", "data", "cio", "cio_theses_projection.json")


def canon_claims_store() -> Path:
    return _path("CIO_CANON_CLAIMS_JSONL", "data", "cio", "canon_claims.jsonl")


def load_policy() -> dict[str, Any]:
    from scripts.lib.cio_operator_investment_policy import build_operator_investment_policy

    return build_operator_investment_policy(store_path=str(operator_policy_store()), repo_root=PROJECT_ROOT)


def load_portfolio_state() -> dict[str, Any]:
    from scripts.lib.cio_portfolio_state_v1 import build_portfolio_state, load_holdings_document

    holdings = load_holdings_document(holdings_path())
    evidence = cash_evidence_path()
    evidence_doc: dict[str, Any] = {}
    if evidence.exists():
        try:
            raw = json.loads(evidence.read_text(encoding="utf-8"))
            evidence_doc = raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError):
            evidence_doc = {}
    accounts = evidence_doc.get("accounts") if isinstance(evidence_doc.get("accounts"), dict) else {}
    state = build_portfolio_state(holdings, broker_cash_evidence=accounts, source_path="canonical_holdings_json")
    state["cash_evidence_available"] = evidence.exists()
    return state


def load_market_context() -> dict[str, Any]:
    from scripts.lib.cio_market_context_state import (
        build_market_context_state,
        connect_trade_ai_readonly,
        load_market_context_inputs,
    )

    try:
        conn = connect_trade_ai_readonly()
        try:
            regime, fred = load_market_context_inputs(conn)
        finally:
            conn.close()
        return build_market_context_state(regime_snapshot=regime, fred_rows=fred)
    except Exception as exc:  # noqa: BLE001 - same degraded state as the API getter
        state = build_market_context_state(regime_snapshot=None, fred_rows=[])
        state["load_error"] = type(exc).__name__
        return state


def load_seasonality() -> dict[str, Any]:
    from scripts.lib.cio_market_context_state import connect_trade_ai_readonly
    from scripts.lib.cio_seasonality_state import build_seasonality_state, load_daily_bars

    try:
        conn = connect_trade_ai_readonly()
        try:
            bars = load_daily_bars(conn, list(SEASONALITY_SYMBOLS))
        finally:
            conn.close()
        return build_seasonality_state(bars, benchmark="SPY")
    except Exception as exc:  # noqa: BLE001 - same degraded state as the API getter
        state = build_seasonality_state({}, benchmark="SPY")
        state["load_error"] = type(exc).__name__
        return state


def ratified_methodology_refs() -> list[str]:
    try:
        from scripts.lib.cio_canon_v1 import build_methodology_policy, load_canon_claims

        return list(build_methodology_policy(load_canon_claims(canon_claims_store()))["ratified_advisory_claim_ids"])
    except Exception:  # noqa: BLE001 - [] when none or unreadable, as the API getter
        return []
