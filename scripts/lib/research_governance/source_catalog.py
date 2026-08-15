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
from typing import Any, Dict, List, Optional

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

FULL_TEXT_STATUSES = frozenset({
    "NOT_FOUND_IN_FILE_LIBRARY",
    "AVAILABLE_LAWFUL_PRIVATE",
    "AVAILABLE_PUBLIC_DOMAIN",
    "AVAILABLE_LICENSED",
})

# A permitted license class must be a specific, verifiable access class — never
# "UNKNOWN" — before a source may claim lawful full text is available.
PERMITTED_LICENSE_CLASSES = frozenset({
    "LAWFUL_PRIVATE", "PUBLIC_DOMAIN", "LICENSED",
})


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


def validate_source_provenance(s: Dict[str, Any]) -> list[str]:
    """Per-source full-text provenance validation (P1-3). Returns problems.

    * `full_text_status` must be a known enum value (unknown/malformed => FAIL).
    * `NOT_FOUND_IN_FILE_LIBRARY` must be `claim_status=SOURCE_CLAIM_INCOMPLETE`.
    * A source claiming lawful full text must provide EVERY field: location/reference,
      source hash, a PERMITTED (specific, non-UNKNOWN) license class, and verified_at.
    """
    problems: list[str] = []
    fts = s.get("full_text_status")
    cs = s.get("claim_status")
    if fts not in FULL_TEXT_STATUSES:
        problems.append("invalid full_text_status")
        return problems
    if fts == "NOT_FOUND_IN_FILE_LIBRARY":
        if cs != "SOURCE_CLAIM_INCOMPLETE":
            problems.append("missing full text but claim_status != SOURCE_CLAIM_INCOMPLETE")
    else:
        if not s.get("source_location"):
            problems.append("claims full text without source_location")
        if not s.get("source_hash"):
            problems.append("claims full text without source_hash")
        if not s.get("verified_at"):
            problems.append("claims full text without verified_at")
        if s.get("license_class", "UNKNOWN") not in PERMITTED_LICENSE_CLASSES:
            problems.append("claims full text without permitted license class")
    return problems


def provenance_coherence_report() -> dict:
    """State/provenance coherence: status must match the available evidence.

    * `full_text_status` must be a known enum value (unknown/malformed => FAIL).
    * A source with full_text_status=NOT_FOUND_IN_FILE_LIBRARY must be
      claim_status=SOURCE_CLAIM_INCOMPLETE.
    * A source claiming lawful full text must provide a location/reference, a
      source hash, a PERMITTED (specific, non-UNKNOWN) license class, and a
      verified_at timestamp.
    """
    sources = load_sources()
    invalid_status = []
    missing_claim_status = []
    available_incomplete = []
    disallowed_license = []
    for s in sources:
        for p in validate_source_provenance(s):
            if p == "invalid full_text_status":
                invalid_status.append(s["source_id"])
            elif p == "missing full text but claim_status != SOURCE_CLAIM_INCOMPLETE":
                missing_claim_status.append(s["source_id"])
            elif p == "claims full text without permitted license class":
                disallowed_license.append(s["source_id"])
            else:
                available_incomplete.append(s["source_id"])
    return {
        "sources_with_invalid_full_text_status": invalid_status,
        "sources_without_claim_status": missing_claim_status,
        "sources_claiming_full_text_without_location_or_hash": available_incomplete,
        "sources_claiming_full_text_incomplete_proof": sorted(set(available_incomplete)),
        "sources_claiming_full_text_without_permitted_license": disallowed_license,
        "coherent": (not invalid_status and not missing_claim_status
                     and not available_incomplete and not disallowed_license),
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
    # Primary research = papers + book/chapter sources (e.g. AFML Chapter 12 CPCV).
    papers = [s for s in sources if s.get("source_type") in ("paper", "book_chapter")]

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


# Exact reference manifest for the CRITICAL statistical methods (P1-2). These
# are the version-of-record metadata, kept separate from working-paper metadata.
# The validator must check EXACT metadata, not merely reject one phantom title.
CRITICAL_METHOD_REFERENCES: Dict[str, Dict[str, Any]] = {
    "dsr": {
        "source_id": "bailey_lopez_de_prado_2014",
        "canonical_title": "The Deflated Sharpe Ratio: Correcting for Selection Bias, "
                           "Backtest Overfitting and Non-Normality",
        "authors": ["David H. Bailey", "Marcos López de Prado"],
        "publication_year": "2014",
        "source_type": "paper",
        "journal": "Journal of Portfolio Management",
        "doi": "10.3905/jpm.2014.40.5.094",
    },
    "pbo_cscv": {
        "source_id": "bailey_borwein_lopez_de_prado_zhu_2017",
        "canonical_title": "The Probability of Backtest Overfitting",
        "authors": ["David H. Bailey", "Jonathan Borwein", "Marcos López de Prado",
                    "Qiji Jim Zhu"],
        "publication_year": "2017",
        "source_type": "paper",
        "journal": "Journal of Computational Finance",
        "volume_issue": "Vol 20 No 4 (April 2017)",
        "doi": "10.21314/JCF.2016.322",
        "working_paper_id": "SSRN 2326253",
        "working_paper_year": "2015",
    },
    "white_reality_check": {
        "source_id": "white_reality_check_2000",
        "canonical_title": "A Reality Check for Data Snooping",
        "authors": ["Halbert White"],
        "publication_year": "2000",
        "source_type": "paper",
        "journal": "Econometrica",
    },
    "stw_trading_rule_bootstrap": {
        "source_id": "sullivan_timmermann_white_1999",
        "canonical_title": "Data-Snooping, Technical Trading Rule Performance, and the Bootstrap",
        "authors": ["Ryan Sullivan", "Allan Timmermann", "Halbert White"],
        "publication_year": "1999",
        "source_type": "paper",
        "journal": "Journal of Finance",
    },
    "stw_calendar_effects": {
        "source_id": "sullivan_timmermann_white_calendar_effects_2001",
        "canonical_title": "Dangers of Data Mining: The Case of Calendar Effects in Stock Returns",
        "authors": ["Ryan Sullivan", "Allan Timmermann", "Halbert White"],
        "publication_year": "2001",
        "source_type": "paper",
        "journal": "Journal of Econometrics",
    },
    "afml_cpcv": {
        "source_id": "lopez_de_prado_cpcv_2017",
        "canonical_title": "Combinatorial Purged Cross-Validation (CPCV)",
        "authors": ["Marcos López de Prado"],
        "publication_year": "2018",
        "source_type": "book_chapter",
        "book": "Advances in Financial Machine Learning, Wiley",
        "chapter": "12",
        "isbn": "9781119482089",
    },
}


def _by_id(sources: List[Dict[str, Any]], source_id: str) -> Optional[Dict[str, Any]]:
    for s in sources:
        if s.get("source_id") == source_id:
            return s
    return None


def critical_reference_report() -> dict:
    """Validate EXACT metadata for the critical statistical methods (P1-2).

    Returns {method: [problems]} — empty list means the catalog entry is correct.
    Also enforces that PBO/CSCV is NOT conflated with AFML CPCV: the PBO entry
    must be a journal paper (JCF) and the CPCV entry must be a book/chapter.
    """
    sources = load_sources()
    problems_by_method: Dict[str, List[str]] = {}
    for method, expected in CRITICAL_METHOD_REFERENCES.items():
        problems: List[str] = []
        rec = _by_id(sources, expected["source_id"])
        if rec is None:
            problems.append(f"missing source_id {expected['source_id']}")
        else:
            if rec.get("source_type") != expected.get("source_type"):
                problems.append(
                    f"source_type {rec.get('source_type')!r} != {expected.get('source_type')!r}")
            if expected.get("canonical_title") and rec.get("title") != expected["canonical_title"]:
                problems.append("title mismatch")
            if expected.get("authors") and rec.get("authors") != expected["authors"]:
                problems.append("authors mismatch")
            if expected.get("publication_year") and rec.get("publication_date") != expected["publication_year"]:
                problems.append(
                    f"publication_date {rec.get('publication_date')!r} != "
                    f"{expected['publication_year']!r}")
            if expected.get("journal") and rec.get("publisher_or_journal") != expected["journal"]:
                problems.append(
                    f"journal {rec.get('publisher_or_journal')!r} != {expected['journal']!r}")
            if expected.get("doi") and rec.get("doi_or_isbn") != expected["doi"]:
                problems.append(f"doi_or_isbn {rec.get('doi_or_isbn')!r} != {expected['doi']!r}")
            if expected.get("volume_issue") and rec.get("volume_issue") != expected["volume_issue"]:
                problems.append("volume_issue mismatch")
            if expected.get("working_paper_id") and rec.get("working_paper_id") != expected["working_paper_id"]:
                problems.append("working_paper_id mismatch")
            if expected.get("working_paper_year") and rec.get("working_paper_year") != expected["working_paper_year"]:
                problems.append("working_paper_year mismatch")
            if expected.get("book") and rec.get("publisher_or_journal") != expected["book"]:
                problems.append(
                    f"book {rec.get('publisher_or_journal')!r} != {expected['book']!r}")
            if expected.get("chapter") and rec.get("chapter") != expected["chapter"]:
                problems.append("chapter mismatch")
            if expected.get("isbn") and rec.get("doi_or_isbn") != expected["isbn"]:
                problems.append(f"isbn {rec.get('doi_or_isbn')!r} != {expected['isbn']!r}")
        problems_by_method[method] = problems
    return {
        "problems_by_method": problems_by_method,
        "coherent": all(not p for p in problems_by_method.values()),
    }


# Backward-compatible alias used by earlier acceptance checks.
SOURCES: List[Dict[str, Any]] = load_sources()
