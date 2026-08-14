"""cio_research_registry.py — Phases 11–16 research source registry.

Catalog of research sources and evidence grades A/B/C/D/X.

READ_ONLY_ADVISORY. Context / risk-modifier only. Never autonomous execution.
Never full-text republication of copyrighted books.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

RESEARCH_REGISTRY_VERSION = "research_registry_1.0.0"
AUTHORITY = "READ_ONLY_ADVISORY"

# A robust / B useful / C exploratory / D source claim / X invalidated
EVIDENCE_GRADES: dict[str, dict[str, str]] = {
    "A": {
        "code": "A",
        "label": "robust",
        "meaning": (
            "Independently reproduced with adequate N, mean/win-rate agreement, "
            "and out-of-sample directional support. Still not a trade instruction."
        ),
    },
    "B": {
        "code": "B",
        "label": "useful",
        "meaning": (
            "Independently reproduced with usable N and consistent direction. "
            "Sample-dependent; risk-modifier only."
        ),
    },
    "C": {
        "code": "C",
        "label": "exploratory",
        "meaning": (
            "Computed but small N, mixed signals, or weak effect size. "
            "Challenge-prompt / context only."
        ),
    },
    "D": {
        "code": "D",
        "label": "source_claim",
        "meaning": (
            "Source claim recorded with citation. Not independently reproduced "
            "by Trade AI. Must not be treated as a Trade AI fact."
        ),
    },
    "X": {
        "code": "X",
        "label": "invalidated",
        "meaning": (
            "Reproduction contradicts the source claim's stated direction "
            "on the available sample. Do not apply."
        ),
    },
}

GRADE_CODES = frozenset(EVIDENCE_GRADES)
FAMILY_IDS = (
    "seasonality",
    "trend",
    "value",
    "risk",
    "breadth",
    "macro",
    "wealth_tax",
)

# Official public STA investor-alert citations (title / URL / date only).
# Operator-structured summaries — not book extracts, not full text.
STA_PUBLIC_ALERTS: dict[str, dict[str, str]] = {
    "august_general": {
        "source_id": "sta_august_general_public_alert",
        "title": "August Almanac & Vital Stats: Stronger in Election Years",
        "url": "https://www.stocktradersalmanac.com/Alert/20240718_2.aspx",
        "date": "2024-07-18",
        "family": "seasonality",
        "license_class": "public_alert_citation_title_url_date_only",
    },
    "august_midterm": {
        "source_id": "sta_august_midterm_public_alert",
        "title": "August Almanac & Vital Stats: No Reprieve in Midterm Years",
        "url": "https://www.stocktradersalmanac.com/Alert/20260716_1.aspx",
        "date": "2026-07-16",
        "family": "seasonality",
        "license_class": "public_alert_citation_title_url_date_only",
    },
    "september_general": {
        "source_id": "sta_september_general_public_alert",
        "title": "September Almanac & Vital Stats: Worst Month of the Year 1950-2023",
        "url": "https://www.stocktradersalmanac.com/Alert/20240815_1.aspx",
        "date": "2024-08-15",
        "family": "seasonality",
        "license_class": "public_alert_citation_title_url_date_only",
    },
    "september_midterm": {
        "source_id": "sta_september_midterm_public_alert",
        "title": "September Almanac: Worst Month Modestly Better in Midterm Years",
        "url": "https://www.stocktradersalmanac.com/Alert/20220818_1.aspx",
        "date": "2022-08-18",
        "family": "seasonality",
        "license_class": "public_alert_citation_title_url_date_only",
    },
}


def normalize_grade(code: Any) -> str:
    """Return a canonical grade letter or '' if unknown."""
    c = str(code or "").strip().upper()
    if c in GRADE_CODES:
        return c
    return ""


def grade_label(code: Any) -> str:
    g = EVIDENCE_GRADES.get(normalize_grade(code) or "")
    return g["label"] if g else "unknown"


def grade_record(code: Any) -> dict[str, str]:
    key = normalize_grade(code)
    if not key:
        return {"code": "", "label": "unknown", "meaning": "unrecognized grade"}
    return dict(EVIDENCE_GRADES[key])


class ResearchSourceRegistry:
    """In-memory registry of research sources (citations, not full text)."""

    def __init__(self) -> None:
        self.version = RESEARCH_REGISTRY_VERSION
        self.authority = AUTHORITY
        self._sources: dict[str, dict[str, Any]] = {}

    def register(self, source: dict[str, Any]) -> dict[str, Any]:
        sid = str(source.get("source_id") or "").strip()
        if not sid:
            raise ValueError("source_id required")
        rec = {
            "source_id": sid,
            "family": source.get("family") or "unspecified",
            "title": source.get("title") or "",
            "url": source.get("url") or "",
            "date": source.get("date") or source.get("publication_date") or "",
            "source_type": source.get("source_type") or "official_research",
            "license_class": source.get("license_class") or "citation_only",
            "evidence_grade": normalize_grade(source.get("evidence_grade")) or "D",
            "claim_layer": "source_claim",
            "fulltext": False,
            "authority": AUTHORITY,
        }
        extra = {
            k: v
            for k, v in source.items()
            if k not in rec and k not in {"full_text", "body", "extract"}
        }
        rec.update(extra)
        rec["fulltext"] = False
        self._sources[sid] = rec
        return rec

    def get(self, source_id: str) -> Optional[dict[str, Any]]:
        return self._sources.get(source_id)

    def by_family(self, family: str) -> list[dict[str, Any]]:
        fam = "wealth_tax" if family in ("wealth/tax", "wealth", "tax") else family
        return [s for s in self._sources.values() if s.get("family") == fam]

    def all_sources(self) -> list[dict[str, Any]]:
        return list(self._sources.values())

    def grade_counts(self) -> dict[str, int]:
        counts = {g: 0 for g in ("A", "B", "C", "D", "X")}
        for s in self._sources.values():
            g = normalize_grade(s.get("evidence_grade")) or "D"
            counts[g] = counts.get(g, 0) + 1
        return counts

    def seed_public_sta_alerts(self) -> list[dict[str, Any]]:
        out = []
        for key, meta in STA_PUBLIC_ALERTS.items():
            rec = self.register(
                {
                    **meta,
                    "claim_key": key,
                    "source_type": "official_research",
                    "evidence_grade": "D",  # citation layer; reproduction is separate
                    "note": "Title/URL/date citation only. Not a book extract.",
                }
            )
            out.append(rec)
        return out


def default_registry() -> ResearchSourceRegistry:
    reg = ResearchSourceRegistry()
    reg.seed_public_sta_alerts()
    return reg


def iter_grade_codes() -> Iterable[str]:
    return ("A", "B", "C", "D", "X")
