"""Research governance — canonical source catalog (PR-R1).

Single source of truth: `config/cio_research_source_catalog.json`. This module
loads it and exposes parity/manifest helpers so the acceptance gate can assert
an EXACT expected-ID manifest (not merely "non-empty").

`full_text_status` records honestly whether a lawful full text is in the file
library; a source whose full text is missing must never be treated as read.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

_CATALOG_PATH = Path(__file__).resolve().parents[3] / "config" / "cio_research_source_catalog.json"

_EXPECTED_BOOK_IDS = [
    "malkiel_random_walk",
    "graham_zweig_intelligent_investor",
    "housel_psychology_of_money",
    "bogle_common_sense",
    "ferri_etf_book",
    "thau_bond_book",
    "harris_trading_exchanges",
    "mcmillan_options",
    "natenberg_option_volatility",
    "aronson_evidence_based_ta",
    "lopez_de_prado_afml",
    "ilmanen_expected_returns",
    "grinold_kahn_active_pm",
    "damodaran_on_valuation",
    "marks_most_important_thing",
    "stock_traders_almanac",
    "hull_options_futures_derivatives",
    "tuckman_serrat_fixed_income",
    "lo_adaptive_markets",
    "schilit_perler_financial_shenanigans",
]

_EXPECTED_PAPER_IDS = [
    "white_reality_check_2000",
    "sullivan_timmermann_white_1999",
    "bailey_lopez_de_prado_2014",
    "bailey_borwein_lopez_de_prado_zhu_2017",
    "harvey_liu_zhu_2016",
    "lopez_de_prado_cpcv_2017",
    "kyle_1985",
    "amihud_2002",
    "lee_ready_1991",
    "almgren_chriss_2001",
    "corwin_schultz_2012",
    "harvey_2017_p_hacking",
]


def _load() -> dict:
    raw = _CATALOG_PATH.read_text(encoding="utf-8")
    return json.loads(raw)


def catalog_json_bytes() -> bytes:
    return _CATALOG_PATH.read_bytes()


def catalog_json_hash() -> str:
    return hashlib.sha256(catalog_json_bytes()).hexdigest()


def load_sources() -> List[Dict[str, Any]]:
    return _load()["sources"]


def load_raw() -> dict:
    return _load()


def expected_required_ids() -> List[str]:
    return _EXPECTED_BOOK_IDS + _EXPECTED_PAPER_IDS


def manifest_report() -> dict:
    """Exact-manifest reconciliation for RGA evidence."""
    sources = load_sources()
    ids = [s["source_id"] for s in sources]
    expected = expected_required_ids()

    missing = [i for i in expected if i not in ids]
    duplicate = sorted({i for i in ids if ids.count(i) > 1})
    extra = [i for i in ids if i not in expected]

    books = [s for s in sources if s.get("source_type") == "book"]
    papers = [s for s in sources if s.get("source_type") == "paper"]
    # A book/paper whose full text is missing must remain SOURCE_CLAIM_INCOMPLETE.
    honest = all(s.get("full_text_status") == "NOT_FOUND_IN_FILE_LIBRARY" for s in sources)

    return {
        "catalog_json_hash": catalog_json_hash(),
        "catalog_loaded_count": len(sources),
        "expected_required_ids": expected,
        "expected_books": len(_EXPECTED_BOOK_IDS),
        "expected_primary_research": len(_EXPECTED_PAPER_IDS),
        "actual_books": len(books),
        "actual_primary_research": len(papers),
        "missing_ids": missing,
        "duplicate_ids": duplicate,
        "extra_ids": extra,
        "honest_full_text_status": honest,
        "manifest_ok": (not missing) and (not duplicate) and (not extra)
        and len(_EXPECTED_BOOK_IDS) == len(books) and len(_EXPECTED_PAPER_IDS) == len(papers),
    }


# Backward-compatible alias used by the previous acceptance checks.
SOURCES: List[Dict[str, Any]] = load_sources()
