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
from .result import Fact, FinancialSenseResult, ModelEstimate, Quality, STATUS_OK
from .source_governance import (
    SOURCE_APPROVED_MARKET_DATA,
    VALID_QUALITY,
    best_source,
    can_back_fact,
    grade_for_source,
)

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
    """Normalize a loading spec into the full governed record.

    A loading is usable only when it carries the complete contract: factor key
    (the mapping key), a numeric loading, method, window, as_of, a validated
    quality, and a governed source. A record missing any required metadata is
    returned as None so the factor-vector calculation treats it as UNAVAILABLE
    rather than fabricating a partial loading.
    """
    if isinstance(entry, dict):
        src = str(entry.get("source") or "").strip().lower()
        if src not in VALID_FACTOR_SOURCES:
            return None
        try:
            loading = float(entry["loading"])
        except (KeyError, TypeError, ValueError):
            return None
        method = entry.get("method")
        window = entry.get("window")
        as_of = entry.get("as_of")
        quality = entry.get("quality")
        if not method or not window or not as_of:
            return None
        if quality not in VALID_QUALITY:
            return None
        return {
            "loading": loading,
            "source": entry.get("source"),
            "method": method,
            "window": window,
            "as_of": as_of,
            "quality": quality,
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
    """Holdings overlap between two funds (list of {symbol, weight}).

    Missing holdings data (None or empty) is DATA_UNAVAILABLE — never a false
    zero. A measured 0.0 is only reported when both sides actually carried
    holdings and none overlapped.
    """
    if not a or not b:
        return {"state": UNAVAILABLE, "reason": "holdings missing on one or both sides"}
    wa = {h.get("symbol"): float(h.get("weight") or 0.0) for h in a if h.get("symbol")}
    wb = {h.get("symbol"): float(h.get("weight") or 0.0) for h in b if h.get("symbol")}
    if not wa or not wb:
        return {"state": UNAVAILABLE, "reason": "no usable holdings symbols"}
    common = set(wa) & set(wb)
    union = set(wa) | set(wb)
    jaccard = len(common) / len(union) if union else 0.0
    overlap_by_weight = sum(min(wa[s], wb[s]) for s in common)
    return {
        "jaccard": round(jaccard, 4),
        "overlap_by_weight": round(overlap_by_weight, 4),
        "common_symbols": sorted(common),
        "state": "OK",
    }


def return_correlation(a: list, b: list) -> dict:
    corr = _pearson(a, b)
    if corr is None:
        return {"correlation": None, "state": UNAVAILABLE, "reason": "insufficient history"}
    return {"correlation": round(corr, 4), "state": "OK"}


def sector_overlap(a: dict, b: dict) -> dict:
    """Sector overlap between two {sector: weight} maps.

    Missing sector data is DATA_UNAVAILABLE, not a false zero.
    """
    if not a or not b:
        return {"state": UNAVAILABLE, "reason": "sector data missing on one or both sides"}
    common = set(a) & set(b)
    overlap = sum(min(float(a[s]), float(b[s])) for s in common)
    return {
        "overlap_by_weight": round(overlap, 4),
        "common_sectors": sorted(common),
        "state": "OK",
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


def _validated_upstream_provenance(instrument: dict):
    """Return (source_type, source_ids, as_of, quality) if `instrument` carries a
    governed, validated upstream provenance envelope, else None.

    A raw caller dict's bare `source_type`/`as_of`/`quality` strings are asserted
    metadata, NOT demonstrated governance, and can never mint a Fact. Fact
    promotion requires a structured `provenance` envelope carrying immutable
    source references (`source_ids`), `READ_ONLY_ADVISORY` authority, a
    fact-capable `source_type`, and validated `quality` + `as_of`.
    """
    if not isinstance(instrument, dict):
        return None
    prov = instrument.get("provenance")
    if not isinstance(prov, dict):
        return None
    src = prov.get("source_type") or prov.get("source")
    if not src:
        return None
    src = str(src)
    if not can_back_fact(src):
        return None
    source_ids = prov.get("source_ids")
    if not source_ids or not isinstance(source_ids, list):
        return None
    if prov.get("authority") != "READ_ONLY_ADVISORY":
        return None
    as_of = prov.get("as_of")
    quality = prov.get("quality")
    if not as_of:
        return None
    if quality not in VALID_QUALITY:
        return None
    return src, list(source_ids), as_of, quality


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

        ho = report["holdings_overlap"]
        prov_a = _validated_upstream_provenance(a)
        prov_b = _validated_upstream_provenance(b)

        # Missing holdings data is honest UNAVAILABLE, never a fabricated zero.
        if ho.get("state") == UNAVAILABLE:
            r.set_status("PARTIAL")
            r.add_warning(f"holdings overlap unavailable: {ho.get('reason')}")
            r.quality = Quality(grade="UNKNOWN", completeness="UNKNOWN")
            return r

        jaccard = ho.get("jaccard")
        if jaccard is None:
            r.set_status("PARTIAL")
            r.add_warning("holdings overlap produced no measurable value")
            return r

        if prov_a and prov_b:
            # Both inputs carry a governed, validated upstream provenance
            # envelope (immutable source_ids + READ_ONLY_ADVISORY authority) —
            # propagate the real source and the later as_of; emit a governed FACT.
            src = best_source([prov_a[0], prov_b[0]], "portfolio_holding")
            as_of = prov_a[2] if (prov_b[2] or "") <= (prov_a[2] or "") else prov_b[2]
            source_ids = sorted(set(prov_a[1]) | set(prov_b[1]))
            r.quality = Quality(grade=grade_for_source(src))
            r.facts.append(
                Fact(
                    key="holdings_jaccard",
                    value=jaccard,
                    source_type=src,
                    source_ids=source_ids,
                    as_of=as_of,
                    quality=grade_for_source(src),
                )
            )
        else:
            # Caller-supplied overlap is deterministic derived data; it is NOT an
            # APPROVED_MARKET_DATA world FACT unless inputs carry a validated
            # upstream governed provenance envelope.
            r.quality = Quality(grade="UNKNOWN")
            r.estimates.append(
                ModelEstimate(
                    key="holdings_jaccard",
                    value=jaccard,
                    method="holdings_overlap",
                    as_of=r.requested_at,
                    quality="UNKNOWN",
                    notes="derived from caller inputs without governed provenance",
                )
            )
            r.add_warning(
                "overlap is derived data; inputs lack a validated upstream "
                "provenance envelope and are not emitted as an APPROVED_MARKET_DATA fact"
            )
        return r
