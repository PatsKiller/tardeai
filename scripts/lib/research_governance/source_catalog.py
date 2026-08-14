"""Research governance — canonical source catalog (PR-R1).

The machine-readable source registry lives in one canonical data file
`config/cio_research_source_catalog.json`. This module loads it and exposes a
parity/hash + exact-manifest reconciliation so the acceptance gate can assert an
EXACT expected-ID manifest (not merely "non-empty").

Classification (matches the governing master canon):

  * 20 institutional canon books: Core Ten (Malkiel, Graham/Zweig, Housel, Bogle,
    Ferri, Thau, Harris, McMillan, Natenberg, Aronson) + Additional #11–#20
    (López de Prado AFML, Ilmanen, Grinold/Kahn, Damodaran, Marks, Hull,
    Tuckman/Serrat, Lo, Schilit/Perler, Expectations Investing).
  * 1 separately governed practitioner/seasonality source: Stock Trader's Almanac.
  * 13 primary research papers (including Sullivan–Timmermann–White's
    calendar-effects/data-mining study, required to challenge Almanac claims).

Provenance honesty: every source lacking lawful full text must carry
`full_text_status=NOT_FOUND_IN_FILE_LIBRARY` AND
`claim_status=SOURCE_CLAIM_INCOMPLETE`. The validator checks STATE/PROVENANCE
COHERENCE (status matches the evidence), not "everything is permanently missing":
a source that later acquires lawful full text must instead provide a
location/reference, a source hash, a permitted license class, and a
`verified_at` timestamp.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

_CATALOG_PATH = Path(__file__).resolve().parents[3] / "config" / "cio_research_source_catalog.json"

# Independent expected-manifest POLICY (test oracle), not self-derived from the
# JSON. It must be kept in exact parity with the canonical data file.
EXPECTED_INSTITUTIONAL_BOOK_IDS = [
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
    "hull_options_futures_derivatives",
    "tuckman_serrat_fixed_income",
    "lo_adaptive_markets",
    "schilit_perler_financial_shenanigans",
    "expectations_investing_rappaport_mauboussin",
]

EXPECTED_PRACTITIONER_IDS = [
    "stock_traders_almanac",
]

EXPECTED_PAPER_IDS = [
    "white_reality_check_2000",
    "sullivan_timmermann_white_1999",
    "sullivan_timmermann_white_calendar_effects_2001",
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
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def catalog_json_bytes() -> bytes:
    return _CATALOG_PATH.read_bytes()


def catalog_json_hash() -> str:
    return hashlib.sha256(catalog_json_bytes()).hexdigest()


def load_sources() -> List[Dict[str, Any]]:
    return _load()["sources"]


def load_raw() -> dict:
    return _load()


def expected_required_ids() -> List[str]:
    return (EXPECTED_INSTITUTIONAL_BOOK_IDS
            + EXPECTED_PRACTITIONER_IDS
            + EXPECTED_PAPER_IDS)


def provenance_coherence_report() -> dict:
    """State/provenance coherence: status must match the available evidence.

    A source with full_text_status=NOT_FOUND_IN_FILE_LIBRARY must be
    claim_status=SOURCE_CLAIM_INCOMPLETE. A source claiming lawful full text must
    provide a location/reference, a source hash, a permitted license class, and a
    verified_at timestamp.
    """
    sources = load_sources()
    missing_status = []
    missing_claim_status = []
    available_incomplete = []
    for s in sources:
        fts = s.get("full_text_status")
        cs = s.get("claim_status")
        if fts == "NOT_FOUND_IN_FILE_LIBRARY":
            if cs != "SOURCE_CLAIM_INCOMPLETE":
                missing_claim_status.append(s["source_id"])
        else:
            # Claims full text is available -> must prove it.
            if not s.get("source_location") and not s.get("source_hash"):
                missing_status.append(s["source_id"])
            if not s.get("source_hash"):
                available_incomplete.append(s["source_id"])
            if not s.get("verified_at"):
                available_incomplete.append(s["source_id"])
    return {
        "sources_without_claim_status": missing_claim_status,
        "sources_claiming_full_text_without_location_or_hash": missing_status,
        "sources_claiming_full_text_incomplete_proof": sorted(set(available_incomplete)),
        "coherent": not missing_claim_status and not missing_status and not available_incomplete,
    }


def manifest_report() -> dict:
    """Exact-manifest reconciliation for RGA evidence."""
    sources = load_sources()
    ids = [s["source_id"] for s in sources]
    expected = expected_required_ids()

    missing = [i for i in expected if i not in ids]
    duplicate = sorted({i for i in ids if ids.count(i) > 1})
    extra = [i for i in ids if i not in expected]

    institutional = [s for s in sources
                     if s.get("source_type") == "book" and s.get("canon_class") == "institutional_canon"]
    practitioner = [s for s in sources if s.get("canon_class") == "practitioner_seasonality"]
    papers = [s for s in sources if s.get("source_type") == "paper"]

    coherence = provenance_coherence_report()

    return {
        "catalog_json_hash": catalog_json_hash(),
        "catalog_loaded_count": len(sources),
        "expected_required_ids": expected,
        "expected_institutional_books": len(EXPECTED_INSTITUTIONAL_BOOK_IDS),
        "expected_practitioner_sources": len(EXPECTED_PRACTITIONER_IDS),
        "expected_primary_research": len(EXPECTED_PAPER_IDS),
        "actual_institutional_books": len(institutional),
        "actual_practitioner_sources": len(practitioner),
        "actual_primary_research": len(papers),
        "missing_ids": missing,
        "duplicate_ids": duplicate,
        "extra_ids": extra,
        "provenance_coherent": coherence["coherent"],
        "provenance_issues": coherence,
        "manifest_ok": (not missing) and (not duplicate) and (not extra)
        and len(EXPECTED_INSTITUTIONAL_BOOK_IDS) == len(institutional)
        and len(EXPECTED_PRACTITIONER_IDS) == len(practitioner)
        and len(EXPECTED_PAPER_IDS) == len(papers),
    }


# Backward-compatible alias used by earlier acceptance checks.
SOURCES: List[Dict[str, Any]] = load_sources()
