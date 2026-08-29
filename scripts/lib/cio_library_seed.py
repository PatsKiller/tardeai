"""Wave 3A.2 seed rows for the institutional library. One index, not a store.

Consumed by `cio_corpus_index.registry()`. Nothing here is a parallel corpus:
these are registry rows describing sources, with a path when the file is on
disk and `official_url` + identifier when it is not.

Grade law (pinned, and enforced by `cio_corpus_index.CLOSING_GRADES`):

    A  independently reproduced, adequate N, out-of-sample support.
       Risk-modifier / context only. Never a standalone sell.
    B  independently reproduced, usable N, consistent direction. Same limits.
    C  challenge-prompt / context only.        Cannot corpus_hit.
    D  must not be treated as a Trade AI fact. Cannot corpus_hit.
    X  reproduction contradicts the claim.     Do not apply.

`corpus_hit` requires grade A/B AND `dimension_scope == "context"`. Entity-level
questions — bear_case, what_is_priced_in, a ticker thesis — are never closed by
an almanac, a war study, a tariff event, a month-of-year effect or an options
textbook. That is enforced in `cio_corpus_index.ENTITY_ONLY_DIMENSIONS`.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

LIBRARY_SEED_VERSION = "library_seed_1.0.0"
AUTHORITY = "READ_ONLY_ADVISORY"

_LIB = Path(__file__).resolve().parents[2] / "reference" / "library"
_SERIES = _LIB / "series"

CONTEXT = "context"
STATIC, WEEKLY, EVENT = "static", "weekly", "event"

MISSING = "MISSING"
ON_DISK = "FOUND_ON_DISK"
URL_ONLY = "OFFICIAL_URL_ONLY"

# Application law strings, kept short and reused so the wording cannot drift.
LAW_CONTEXT = ("context / risk-modifier only; max 10% conviction language; "
               "never a standalone sell; never creates TRIM")
LAW_CITATION = ("citation only — no lawful full text on disk; must not be "
                "treated as a Trade AI fact")
LAW_PRIMARY = ("primary document — factual record; an event may override "
               "SKIP_FRESH but never mints an order")


def _hash(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:32]
    except Exception:
        return None


def _row(source_id: str, family: str, title: str, *, authors: str = "",
         year: Any = None, isbn_or_doi: str = "", official_url: str = "",
         path: Path | None = None, grade: str = "D",
         law: str = LAW_CITATION, scope: str = CONTEXT,
         refresh: str = STATIC, notes: str = "") -> dict[str, Any]:
    on_disk = bool(path and path.exists())
    return {
        "source_id": source_id,
        "family": family,
        "title": title,
        "authors": authors,
        "year": year,
        "isbn_or_doi": isbn_or_doi,
        "official_url": official_url,
        "path_or_MISSING": (str(path.relative_to(_LIB.parents[1]))
                            if on_disk else MISSING),
        "content_hash": _hash(path) if on_disk else None,
        "as_of": None,
        "evidence_grade": grade,
        "application_law": law,
        "dimension_scope": scope,
        "refresh": refresh,
        "status": ON_DISK if on_disk else (URL_ONLY if official_url else MISSING),
        "notes": notes,
        "library_seed_version": LIBRARY_SEED_VERSION,
        "authority": AUTHORITY,
    }


def seed_rows() -> list[dict[str, Any]]:
    ff = _SERIES / "ff_research_data_factors_monthly.csv"
    return [
        # -- Family A: calendar / election / month ---------------------------
        _row("hirsch_stock_traders_almanac_2026", "seasonality",
             "Stock Trader's Almanac 2026", authors="Hirsch", year=2026,
             isbn_or_doi="978-1-394-36268-4",
             official_url="https://www.stocktradersalmanac.com/AboutUs.aspx",
             grade="C", law=LAW_CONTEXT,
             notes=("C until OUR series reproduces a named effect; then B for "
                    "that named effect only — see cio_calendar_facts")),
        _row("bouman_jacobsen_2002_halloween", "seasonality",
             "The Halloween Indicator, 'Sell in May and Go Away'",
             authors="Bouman & Jacobsen", year=2002,
             isbn_or_doi="10.1257/000282802762024683",
             official_url="https://www.aeaweb.org/articles?id=10.1257/000282802762024683",
             grade="B", law=LAW_CONTEXT,
             notes="reproduced on Ken French monthly; effect is a differential"),
        _row("plastun_halloween_us_history", "seasonality",
             "Halloween Effect in US markets: a historical view",
             year=2019, isbn_or_doi="SSRN 3362154",
             official_url="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3362154",
             grade="C", law=LAW_CONTEXT),
        _row("mohamed_2024_time_based_patterns", "seasonality",
             "Time-Based Trading Patterns", year=2024,
             isbn_or_doi="SSRN 5101935",
             official_url="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5101935",
             grade="C", law=LAW_CONTEXT),

        # -- Family B: index level / breadth / regime -------------------------
        _row("ken_french_data_library", "trend",
             "Ken French Data Library — research factors, monthly",
             authors="Fama & French", official_url=(
                 "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/"
                 "data_library.html"),
             path=ff, grade="A", law=LAW_CONTEXT, refresh=WEEKLY,
             notes=("public and redistributable; 1926-07 onward; the grading "
                    "series for every reproduced calendar fact")),
        _row("fama_french_1993", "value",
             "Common risk factors in the returns on stocks and bonds",
             authors="Fama & French", year=1993,
             isbn_or_doi="10.1016/0304-405X(93)90023-5", grade="A",
             law=LAW_CONTEXT,
             official_url="https://doi.org/10.1016/0304-405X(93)90023-5"),
        _row("fama_french_2015_five_factor", "value",
             "A five-factor asset pricing model", authors="Fama & French",
             year=2015, isbn_or_doi="10.1016/j.jfineco.2014.10.010", grade="A",
             law=LAW_CONTEXT,
             official_url="https://doi.org/10.1016/j.jfineco.2014.10.010"),
        _row("carhart_1997", "trend", "On Persistence in Mutual Fund Performance",
             authors="Carhart", year=1997, isbn_or_doi="10.1111/j.1540-6261.1997.tb03808.x",
             grade="A", law=LAW_CONTEXT,
             official_url="https://doi.org/10.1111/j.1540-6261.1997.tb03808.x"),
        _row("baker_bloom_davis_epu", "macro",
             "Economic Policy Uncertainty Index",
             authors="Baker, Bloom & Davis", year=2016,
             official_url="https://www.policyuncertainty.com", grade="B",
             law=LAW_CONTEXT, refresh=WEEKLY),
        _row("cboe_vix_white_paper", "risk", "CBOE Volatility Index white paper",
             official_url="https://www.cboe.com/tradable_products/vix/",
             grade="B", law=LAW_CONTEXT),

        # -- Family C: war / tariffs / geopolitics ---------------------------
        _row("nber_event_studies_geopolitical", "macro",
             "NBER event studies — wars, embargoes, tariff shocks",
             official_url="https://www.nber.org/papers", grade="B",
             law=LAW_CONTEXT, refresh=EVENT,
             notes=("event-study papers B; primary Fed/Treasury/USTR documents A; "
                    "op-eds D. A tariff headline is an EVENT that overrides "
                    "SKIP_FRESH and never mints a TRIM")),

        # -- Family D: options / hedging -------------------------------------
        _row("natenberg_option_volatility", "risk",
             "Option Volatility and Pricing", authors="Natenberg",
             isbn_or_doi="978-0071818773", grade="C", law=LAW_CITATION,
             official_url="https://www.mhprofessional.com"),
        _row("hull_options_futures", "risk",
             "Options, Futures, and Other Derivatives", authors="Hull",
             isbn_or_doi="978-0136939917", grade="C", law=LAW_CITATION,
             official_url="https://www.pearson.com"),
        _row("gatheral_volatility_surface", "risk", "The Volatility Surface",
             authors="Gatheral", year=2006, isbn_or_doi="978-0471792512",
             grade="C", law=LAW_CITATION, official_url="https://www.wiley.com"),
        _row("bollen_whaley_demand_pressure", "risk",
             "Does Net Buying Pressure Affect the Shape of Implied Volatility?",
             authors="Bollen & Whaley", year=2004,
             isbn_or_doi="10.1111/j.1540-6261.2004.00647.x", grade="B",
             law=LAW_CONTEXT,
             official_url="https://doi.org/10.1111/j.1540-6261.2004.00647.x"),

        # -- Family E: long-run / valuation / income -------------------------
        _row("jorda_knoll_schularick_taylor_rore", "macro",
             "The Rate of Return on Everything, 1870-2015", year=2019,
             isbn_or_doi="10.1093/qje/qjz012", grade="A", law=LAW_CONTEXT,
             official_url="https://doi.org/10.1093/qje/qjz012"),
        _row("goyal_welch_equity_premium", "value",
             "A Comprehensive Look at the Empirical Performance of Equity "
             "Premium Prediction", authors="Goyal & Welch", year=2008,
             isbn_or_doi="10.1093/rfs/hhm014", grade="A", law=LAW_CONTEXT,
             official_url="https://doi.org/10.1093/rfs/hhm014"),
        _row("bessembinder_stocks_vs_tbills", "breadth",
             "Do Stocks Outperform Treasury Bills?", authors="Bessembinder",
             year=2018, isbn_or_doi="10.1016/j.jfineco.2018.06.004", grade="B",
             law=LAW_CONTEXT,
             official_url="https://doi.org/10.1016/j.jfineco.2018.06.004",
             notes="concentration / S6 context — never a position instruction"),
        _row("dimson_marsh_staunton_yearbook", "value",
             "Triumph of the Optimists / DMS Yearbook",
             authors="Dimson, Marsh & Staunton", grade="B", law=LAW_CITATION,
             official_url="https://www.ubs.com/global/en/investment-bank/"
                          "global-investment-returns-yearbook.html"),
        _row("damodaran_implied_erp", "value",
             "Damodaran implied equity risk premium series",
             authors="Damodaran",
             official_url="https://pages.stern.nyu.edu/~adamodar/", grade="B",
             law=LAW_CONTEXT, refresh=WEEKLY,
             notes="free public series from an author whose books are grade D"),

        # -- Family F: Fed / macro cadence -----------------------------------
        _row("fomc_statements_minutes_sep", "macro",
             "FOMC statements, minutes and SEP",
             official_url="https://www.federalreserve.gov/monetarypolicy/"
                          "fomccalendars.htm",
             grade="A", law=LAW_PRIMARY, refresh=EVENT,
             notes="hash change on new minutes = EVENT override of SKIP_FRESH"),
        _row("fed_beige_book", "macro", "Beige Book",
             official_url="https://www.federalreserve.gov/monetarypolicy/"
                          "beige-book-default.htm",
             grade="A", law=LAW_PRIMARY, refresh=EVENT),
        _row("frbsf_wp_2025_30_usmpd", "macro",
             "US Monetary Policy Database — FOMC event study (FRBSF WP 2025-30)",
             year=2025,
             official_url="https://www.frbsf.org/wp-content/uploads/wp2025-30.pdf",
             grade="B", law=LAW_CONTEXT, refresh=EVENT),
        _row("nakamura_steinsson_2018", "macro",
             "High-Frequency Identification of Monetary Non-Neutrality",
             authors="Nakamura & Steinsson", year=2018,
             isbn_or_doi="10.1093/qje/qjy004", grade="B", law=LAW_CONTEXT,
             official_url="https://doi.org/10.1093/qje/qjy004"),

        # -- Family G: liquidity / crash / intermediary ----------------------
        _row("brunnermeier_pedersen_liquidity", "risk",
             "Market Liquidity and Funding Liquidity",
             authors="Brunnermeier & Pedersen", year=2009,
             isbn_or_doi="10.1093/rfs/hhn098", grade="A", law=LAW_CONTEXT,
             official_url="https://doi.org/10.1093/rfs/hhn098"),
        _row("adrian_etula_muir_intermediary", "risk",
             "Financial Intermediaries and the Cross-Section of Asset Returns",
             year=2014, isbn_or_doi="10.1111/jofi.12189", grade="B",
             law=LAW_CONTEXT, official_url="https://doi.org/10.1111/jofi.12189"),
        _row("moreira_muir_volatility_managed", "risk",
             "Volatility-Managed Portfolios", authors="Moreira & Muir",
             year=2017, isbn_or_doi="10.1111/jofi.12513", grade="B",
             law=LAW_CONTEXT, official_url="https://doi.org/10.1111/jofi.12513"),
    ]


def wave3a3_series_rows() -> list[dict[str, Any]]:
    """Series added in Wave 3A.3. French factors on disk; xls sources URL-only."""
    return [
        _row("ken_french_ff5_monthly", "value",
             "Ken French — 5 research factors, monthly",
             authors="Fama & French",
             official_url=("https://mba.tuck.dartmouth.edu/pages/faculty/"
                           "ken.french/data_library.html"),
             path=_SERIES / "ff_research_data_5_factors_monthly.csv",
             grade="A", law=LAW_CONTEXT, refresh=WEEKLY),
        _row("ken_french_momentum_monthly", "trend",
             "Ken French — momentum factor, monthly", authors="Carhart/French",
             official_url=("https://mba.tuck.dartmouth.edu/pages/faculty/"
                           "ken.french/data_library.html"),
             path=_SERIES / "ff_momentum_factor_monthly.csv",
             grade="A", law=LAW_CONTEXT, refresh=WEEKLY),
        _row("us_equity_monthly_french_normalized", "seasonality",
             "US equity monthly total return, normalised from Ken French",
             official_url=("https://mba.tuck.dartmouth.edu/pages/faculty/"
                           "ken.french/data_library.html"),
             path=_SERIES / "us_equity_monthly_french_1926.csv",
             grade="A", law=LAW_CONTEXT,
             notes=("THE operator grading series — every operator-visible "
                    "seasonality number resolves here; regenerate with "
                    "scripts/build_french_monthly_normalized.py")),
        _row("shiller_us_stock_market_data", "value",
             "Shiller US Stock Market Data, monthly 1871-", authors="Shiller",
             official_url="http://www.econ.yale.edu/~shiller/data.htm",
             grade="B", law=LAW_CONTEXT, refresh=WEEKLY,
             notes=("URL-only: the source is a legacy .xls and parsing it "
                    "needs an xlrd dependency this PR does not add. Intended "
                    "as the SECOND series for OOS_START_YEAR=2000 checks, "
                    "never as a replacement for French as primary")),
        _row("damodaran_implied_erp_series", "value",
             "Damodaran implied ERP — official NYU data page",
             authors="Damodaran",
             official_url="https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datacurrent.html",
             grade="B", law=LAW_CONTEXT, refresh=WEEKLY,
             notes=("URL-only: the series itself is an .xls behind the page; "
                    "the free public series, not the copyright book")),
    ]


def fred_series_rows() -> list[dict[str, Any]]:
    """The seven ingested FRED series. Primary public data — grade A."""
    ids = ["sp500", "nasdaqcom", "fedfunds", "t10y2y", "cpiaucsl", "unrate",
           "vixcls"]
    out = []
    for sid in ids:
        p = _SERIES / f"fred_{sid}.csv"
        out.append(_row(f"fred_{sid}", "macro", f"FRED {sid.upper()}",
                        official_url=f"https://fred.stlouisfed.org/series/{sid.upper()}",
                        path=p, grade="A", law=LAW_CONTEXT, refresh=WEEKLY,
                        notes="public primary series"))
    return out
