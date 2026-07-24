#!/usr/bin/env python3
"""Deterministic quality and policy contract for Defense/Sectors data.

Pure helpers only: no broker/order/approval/config-promotion authority.  The module
centralizes the ten diligence corrections so producers can adopt them without
silently changing live allocation policy.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping, Sequence

CALC_VERSION = "defense-quality-v1"


@dataclass(frozen=True)
class Quality:
    state: str
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "reasons": list(self.reasons)}


def canonical_json_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(raw).hexdigest()


def field_ledger(*, source: str, source_as_of: str | None, cadence: str,
                 value: Any, coverage_n: int | None = None,
                 coverage_total: int | None = None, quality: Quality | None = None,
                 provider: str | None = None) -> dict[str, Any]:
    """Field-level truth ledger required by the frontend and Sentinel adapter."""
    return {
        "source": source,
        "provider": provider or source,
        "source_as_of": source_as_of,
        "calculation_version": CALC_VERSION,
        "snapshot_hash": canonical_json_hash(value),
        "cadence": cadence,
        "coverage_n": coverage_n,
        "coverage_total": coverage_total,
        "quality": (quality or Quality("ok")).to_dict(),
    }


def exact_session_breadth(rows: Iterable[tuple[str, Any, float]], *,
                          sessions: int = 20, min_members: int = 8) -> dict[str, Any]:
    """Calculate breadth from exactly N distinct dates per symbol.

    Input rows are ``(symbol, trading_date, close)`` and may contain duplicate
    same-day repricer writes.  The last supplied value wins deterministically.
    """
    by_symbol: dict[str, dict[str, float]] = {}
    duplicates = 0
    for symbol, d, close in rows:
        key = str(d)
        bucket = by_symbol.setdefault(str(symbol).upper(), {})
        if key in bucket:
            duplicates += 1
        bucket[key] = float(close)

    above = 0
    eligible = 0
    insufficient: list[str] = []
    for symbol, daily in sorted(by_symbol.items()):
        ordered = sorted(daily.items())
        if len(ordered) < sessions:
            insufficient.append(symbol)
            continue
        window = ordered[-sessions:]
        last = window[-1][1]
        dma = sum(v for _, v in window) / sessions
        eligible += 1
        above += int(last > dma)

    quality = Quality("ok")
    if eligible < min_members:
        quality = Quality("insufficient_coverage", (f"eligible_members={eligible}",))
    pct = round(above / eligible * 100) if eligible >= min_members else None
    return {
        "breadth_pct": pct,
        "coverage_n": eligible,
        "membership_n": len(by_symbol),
        "sessions": sessions,
        "duplicate_dates_removed": duplicates,
        "insufficient_symbols": insufficient,
        "quality": quality.to_dict(),
    }


def label_market_internals(internals: Mapping[str, Any]) -> dict[str, Any]:
    """Never represent the capped movers sample as exchange-wide breadth."""
    out = dict(internals)
    source = str(out.get("source") or "")
    capped = "top-15" in source.lower() or "market_movers" in source.lower()
    out["scope"] = "top_movers_sample" if capped else "comprehensive_universe"
    out["display_label"] = "top-movers NH/NL sample" if capped else "market NH/NL"
    out["quality"] = Quality("sample_only", ("not comprehensive breadth",)).to_dict() if capped else Quality("ok").to_dict()
    return out


def industry_window_quality(*, industry_provider: str, benchmark_provider: str,
                            industry_as_of: str | None, benchmark_as_of: str | None,
                            capture_kind: str | None) -> Quality:
    reasons: list[str] = []
    if industry_provider != benchmark_provider:
        reasons.append("mixed_provider")
    if industry_as_of and benchmark_as_of and industry_as_of[:10] != benchmark_as_of[:10]:
        reasons.append("timestamp_mismatch")
    if capture_kind != "close":
        reasons.append("intraday_refresh_not_close_confirmed")
    return Quality("approximate_mixed_windows" if reasons else "ok", tuple(reasons))


def canonical_industry_sector(industry: str, mapping: Mapping[str, str]) -> dict[str, Any]:
    sector = mapping.get(industry)
    return {
        "industry": industry,
        "sector": sector,
        "mapping_version": "gics-canonical-v1",
        "quality": Quality("ok" if sector else "unmapped").to_dict(),
    }


def target_gap(*, actual_pct: float, benchmark_pct: float,
               active_tilt_cap_pct: float, mandate: str,
               volatility_multiplier: float = 1.0,
               correlation_penalty: float = 0.0) -> dict[str, Any]:
    """Benchmark/mandate-aware active gap; does not authorize an order."""
    raw = benchmark_pct - actual_pct
    bounded = max(-active_tilt_cap_pct, min(active_tilt_cap_pct, raw))
    adjusted = bounded * max(0.0, volatility_multiplier) * max(0.0, 1.0 - correlation_penalty)
    return {
        "mandate": mandate,
        "actual_pct": round(actual_pct, 3),
        "benchmark_pct": round(benchmark_pct, 3),
        "raw_gap_pct": round(raw, 3),
        "bounded_gap_pct": round(bounded, 3),
        "risk_adjusted_gap_pct": round(adjusted, 3),
        "advisory_only": True,
    }


def stock_quality_gate(features: Mapping[str, Any]) -> dict[str, Any]:
    """Institutional quality gate beyond legacy screen scores.

    Missing inputs fail closed and are explicitly listed; no fabricated defaults.
    """
    required = (
        "earnings_revision_3m", "forward_pe_vs_sector", "fcf_margin",
        "roic", "net_debt_ebitda", "interest_coverage", "beta",
        "book_correlation", "short_interest_pct", "crowding_percentile",
        "catalyst_days", "dollar_volume_m", "extension_sma50_pct",
    )
    missing = [k for k in required if features.get(k) is None]
    failures: list[str] = []
    if not missing:
        if float(features["earnings_revision_3m"]) < 0: failures.append("negative_revisions")
        if float(features["fcf_margin"]) <= 0: failures.append("nonpositive_fcf")
        if float(features["roic"]) < 8: failures.append("low_roic")
        if float(features["net_debt_ebitda"]) > 4: failures.append("high_leverage")
        if float(features["interest_coverage"]) < 3: failures.append("weak_interest_coverage")
        if float(features["book_correlation"]) > 0.85: failures.append("high_book_overlap")
        if float(features["crowding_percentile"]) > 90: failures.append("crowded")
        if int(features["catalyst_days"]) <= 7: failures.append("near_catalyst")
        if float(features["dollar_volume_m"]) < 20: failures.append("illiquid")
        if float(features["extension_sma50_pct"]) > 12: failures.append("extended")
    return {
        "eligible": not missing and not failures,
        "missing": missing,
        "failures": failures,
        "legacy_screen_is_not_conviction": True,
        "quality": Quality("ok" if not missing and not failures else "withheld").to_dict(),
    }


def directive_review(*, set_date: str, evidence_as_of: str,
                     max_age_days: int = 5, conflicts: Sequence[str] = ()) -> dict[str, Any]:
    s = date.fromisoformat(set_date[:10])
    e = date.fromisoformat(evidence_as_of[:10])
    age = (e - s).days
    due = age > max_age_days or bool(conflicts)
    return {
        "review_due": due,
        "age_days": age,
        "conflicts": list(conflicts),
        "action": "operator_re_adjudication_required" if due else "retain",
        "auto_revoke": False,
    }


def fund_lookthrough_quality(*, provider: str | None, factsheet_date: str | None,
                             coverage_pct: float | None, unmapped_pct: float | None,
                             max_age_days: int = 120,
                             now: date | None = None) -> dict[str, Any]:
    reasons: list[str] = []
    today = now or datetime.now(timezone.utc).date()
    if not provider: reasons.append("provider_missing")
    if not factsheet_date: reasons.append("factsheet_date_missing")
    else:
        age = (today - date.fromisoformat(factsheet_date[:10])).days
        if age > max_age_days: reasons.append("factsheet_stale")
    if coverage_pct is None: reasons.append("coverage_missing")
    elif coverage_pct < 95: reasons.append("coverage_below_95pct")
    if unmapped_pct is None: reasons.append("unmapped_weight_missing")
    elif unmapped_pct > 5: reasons.append("unmapped_weight_above_5pct")
    return {
        "provider": provider,
        "factsheet_date": factsheet_date,
        "coverage_pct": coverage_pct,
        "unmapped_pct": unmapped_pct,
        "quality": Quality("ok" if not reasons else "review_required", tuple(reasons)).to_dict(),
    }


def quarantine_stale_rows(rows: Sequence[Mapping[str, Any]], *, as_of: date,
                          max_age_days: int = 4) -> dict[str, Any]:
    current, quarantined = [], []
    for row in rows:
        raw = row.get("as_of")
        age = None
        try:
            age = (as_of - date.fromisoformat(str(raw)[:10])).days
        except Exception:
            pass
        enriched = dict(row, age_days=age)
        if age is None or age > max_age_days:
            enriched["quality"] = Quality("stale", ("row excluded from recommendation inputs",)).to_dict()
            quarantined.append(enriched)
        else:
            enriched["quality"] = Quality("ok").to_dict()
            current.append(enriched)
    return {"current": current, "quarantined": quarantined}
