"""Factor / overlap intelligence.

Detects when several holdings may represent essentially the same economic bet.
Factor loadings are never fabricated: every loading must carry factor, loading,
method, window, as_of, quality, and a governed source. Similarity is reported as
transparent components (holdings overlap, return correlation, sector overlap,
factor-vector similarity) — never collapsed into a single magic score. Pure
module: no network, no database.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Optional

from .provider import BaseProvider, Capability
from .result import Fact, FinancialSenseResult, Quality, STATUS_OK
from .source_governance import SOURCE_APPROVED_MARKET_DATA, grade_for_source

UNAVAILABLE = "UNAVAILABLE"

VALID_FACTOR_SOURCES = frozenset(
    {
        "verified_regression",
        "approved_vendor",
        "explicit_etf_lookthrough",
        "sector_industry_mapping",
        "duration_credit_characteristics",
    }
)


@dataclass
class FactorExposure:
    factor: str
    loading: Optional[float] = None
    method: Optional[str] = None
    window: Optional[str] = None
    as_of: Optional[str] = None
    quality: str = "UNKNOWN"
    source: Optional[str] = None

    def is_sourced(self) -> bool:
        return bool(self.source) and str(self.source).strip().lower() in VALID_FACTOR_SOURCES

    def to_dict(self) -> dict:
        return asdict(self)


def _coerce_loading(entry) -> Optional[dict]:
    """Normalize a loading spec into {loading, source, method, window, as_of}.

    Returns None when the loading is unsourced (so it is UNAVAILABLE, not
    fabricated).
    """
    if isinstance(entry, dict):
        src = str(entry.get("source") or "").strip().lower()
        if src not in VALID_FACTOR_SOURCES:
            return None
        try:
            loading = float(entry["loading"])
        except (KeyError, TypeError, ValueError):
            return None
        return {
            "loading": loading,
            "source": entry.get("source"),
            "method": entry.get("method"),
            "window": entry.get("window"),
            "as_of": entry.get("as_of"),
        }
    return None


def _pearson(a: list, b: list) -> Optional[float]:
    if a is None or b is None:
        return None
    if len(a) != len(b) or len(a) < 2:
        return None
    n = len(a)
    try:
        a = [float(x) for x in a]
        b = [float(x) for x in b]
    except (TypeError, ValueError):
        return None
    ma = sum(a) / n
    mb = sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va == 0 or vb == 0:
        return None
    return cov / math.sqrt(va * vb)


def holdings_overlap(a: list, b: list) -> dict:
    """Holdings overlap between two funds (list of {symbol, weight})."""
    wa = {h.get("symbol"): float(h.get("weight") or 0.0) for h in (a or []) if h.get("symbol")}
    wb = {h.get("symbol"): float(h.get("weight") or 0.0) for h in (b or []) if h.get("symbol")}
    common = set(wa) & set(wb)
    union = set(wa) | set(wb)
    jaccard = len(common) / len(union) if union else 0.0
    overlap_by_weight = sum(min(wa[s], wb[s]) for s in common)
    return {
        "jaccard": round(jaccard, 4),
        "overlap_by_weight": round(overlap_by_weight, 4),
        "common_symbols": sorted(common),
    }


def return_correlation(a: list, b: list) -> dict:
    corr = _pearson(a, b)
    if corr is None:
        return {"correlation": None, "state": UNAVAILABLE, "reason": "insufficient history"}
    return {"correlation": round(corr, 4), "state": "OK"}


def sector_overlap(a: dict, b: dict) -> dict:
    """Sector overlap between two {sector: weight} maps."""
    a = a or {}
    b = b or {}
    common = set(a) & set(b)
    overlap = sum(min(float(a[s]), float(b[s])) for s in common)
    return {
        "overlap_by_weight": round(overlap, 4),
        "common_sectors": sorted(common),
    }


def factor_similarity(a: dict, b: dict) -> dict:
    """Cosine similarity over shared factor loadings (sourced loadings only)."""
    ca = {}
    for f, entry in (a or {}).items():
        spec = _coerce_loading(entry)
        if spec is not None:
            ca[f] = spec["loading"]
    cb = {}
    for f, entry in (b or {}).items():
        spec = _coerce_loading(entry)
        if spec is not None:
            cb[f] = spec["loading"]
    shared = set(ca) & set(cb)
    if not shared:
        return {"cosine_similarity": None, "state": UNAVAILABLE, "shared_factors": []}
    dot = sum(ca[f] * cb[f] for f in shared)
    na = math.sqrt(sum(ca[f] ** 2 for f in shared))
    nb = math.sqrt(sum(cb[f] ** 2 for f in shared))
    if na == 0 or nb == 0:
        return {"cosine_similarity": None, "state": UNAVAILABLE, "shared_factors": sorted(shared)}
    return {
        "cosine_similarity": round(dot / (na * nb), 4),
        "state": "OK",
        "shared_factors": sorted(shared),
    }


def overlap_report(instrument_a: dict, instrument_b: dict) -> dict:
    """Composite overlap report with transparent components (no magic score)."""
    return {
        "holdings_overlap": holdings_overlap(
            instrument_a.get("holdings"), instrument_b.get("holdings")
        ),
        "return_correlation": return_correlation(
            instrument_a.get("returns"), instrument_b.get("returns")
        ),
        "sector_overlap": sector_overlap(
            instrument_a.get("sectors"), instrument_b.get("sectors")
        ),
        "factor_similarity": factor_similarity(
            instrument_a.get("factors"), instrument_b.get("factors")
        ),
    }


class FactorOverlapProvider(BaseProvider):
    name = "factor"
    version = "1.0.0"
    source_type = SOURCE_APPROVED_MARKET_DATA

    def _capabilities(self) -> list[Capability]:
        return [
            Capability(
                "factor.overlap",
                "READ_ONLY",
                input_schema={"instrument_a": "object", "instrument_b": "object"},
            )
        ]

    def _query(self, capability: str, request: dict) -> FinancialSenseResult:
        if capability != "factor.overlap":
            return self._unavailable(capability, "unknown capability")
        a = request.get("instrument_a")
        b = request.get("instrument_b")
        if not isinstance(a, dict) or not isinstance(b, dict):
            return self._invalid("factor.overlap", "instrument_a and instrument_b required")
        report = overlap_report(a, b)
        r = self._ok("factor.overlap")
        r.data = report
        r.quality = Quality(grade=grade_for_source(SOURCE_APPROVED_MARKET_DATA))
        r.facts.append(
            Fact(
                key="holdings_jaccard",
                value=report["holdings_overlap"]["jaccard"],
                source_type=SOURCE_APPROVED_MARKET_DATA,
                source_ids=["holdings_overlap"],
                as_of=r.requested_at,
                quality=grade_for_source(SOURCE_APPROVED_MARKET_DATA),
            )
        )
        return r
