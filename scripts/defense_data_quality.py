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
import math
from statistics import median, pstdev
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


# ---------------------------------------------------------------------------
# Additive support for the DISABLED account-specific launcher
# (scripts/defense_recommendations_v10.py). Reconciled from the holdings-lane
# data-quality contract so the v10 producer imports coherently. These helpers
# are pure/read-only and remain unused until an operator switches the host
# invocation to the v10 producer. They never place orders, change permissions
# or promote configuration.
# ---------------------------------------------------------------------------

def _daily_returns(series: "list[tuple[Any, float]]") -> dict[Any, float]:
    dedup: dict[Any, float] = {}
    for d, px in series:
        if px is not None:
            dedup[d] = float(px)
    ordered = sorted(dedup.items())
    out: dict[Any, float] = {}
    for (d0, p0), (d1, p1) in zip(ordered, ordered[1:]):
        if p0:
            out[d1] = p1 / p0 - 1.0
    return out


def realized_vol_corr(cur, symbol: str, benchmark: str = "SPY", sessions: int = 60) -> dict:
    """Read-only realized annualized vol and correlation from distinct daily closes."""
    cur.execute(
        """SELECT symbol, price_date, max(close_price) AS close_price
           FROM ticker_prices
           WHERE symbol = ANY(%s) AND price_date > CURRENT_DATE - 220
           GROUP BY symbol, price_date ORDER BY symbol, price_date""",
        ([symbol, benchmark],),
    )
    rows: dict[str, list[tuple[Any, float]]] = {symbol: [], benchmark: []}
    for sym, d, px in cur.fetchall():
        if sym in rows and px is not None:
            rows[sym].append((d, float(px)))
    a, b = _daily_returns(rows[symbol]), _daily_returns(rows[benchmark])
    common = sorted(set(a).intersection(b))[-sessions:]
    if len(common) < 20:
        return {"quality": "insufficient_history", "sessions": len(common),
                "annualized_vol_pct": None, "correlation": None}
    av, bv = [a[d] for d in common], [b[d] for d in common]
    vol = pstdev(av) * math.sqrt(252) * 100
    ma, mb = sum(av) / len(av), sum(bv) / len(bv)
    num = sum((x - ma) * (y - mb) for x, y in zip(av, bv))
    den = math.sqrt(sum((x - ma) ** 2 for x in av) * sum((y - mb) ** 2 for y in bv))
    corr = num / den if den else None
    return {"quality": "ok" if corr is not None else "zero_variance",
            "sessions": len(common), "annualized_vol_pct": round(vol, 2),
            "correlation": round(corr, 3) if corr is not None else None}


def allocation_decision(cfg: dict, *, sector: str, current_weight_pct: float | None,
                        risk_context: dict, account: str | None = None) -> dict:
    """Account-specific benchmark/mandate/risk capacity with a hard policy ceiling.

    A missing account exposure is not silently replaced with the total-book weight. The
    caller must provide the target account's effective sector weight or the decision fails
    closed. ``max_active_tilt_pct`` is a ceiling, not a free amount added after scaling.
    """
    policy = cfg.get("allocation_policy") or {}
    benchmark_name = policy.get("default_benchmark", "equal_sector")
    benchmark = (policy.get("benchmarks") or {}).get(benchmark_name, {})
    base_target = float(benchmark.get(sector, cfg.get("neutral_sector_weight_pct", 9.1)))
    mandate_name = (policy.get("account_mandates") or {}).get(account, "total_return")
    mandate = (policy.get("mandates") or {}).get(mandate_name, {})
    tilt = float((mandate.get("sector_tilts_pct") or {}).get(sector, 0.0))
    mandate_target = base_target + tilt

    base_out = {
        "benchmark": benchmark_name,
        "mandate": mandate_name,
        "base_target_pct": round(base_target, 2),
        "mandate_tilt_pct": round(tilt, 2),
        "mandate_target_pct": round(mandate_target, 2),
        "risk_context": risk_context,
    }
    if current_weight_pct is None:
        return {**base_out, "eligible": False, "quality": "missing_account_exposure",
                "current_account_weight_pct": None, "current_weight_pct": None,
                "capacity_pct": 0.0}

    vol = risk_context.get("annualized_vol_pct")
    corr = risk_context.get("correlation")
    if risk_context.get("quality") != "ok" or vol is None or corr is None:
        return {**base_out, "eligible": False, "quality": "missing_risk_context",
                "current_account_weight_pct": round(float(current_weight_pct), 2),
                "current_weight_pct": round(float(current_weight_pct), 2),
                "capacity_pct": 0.0}

    target_vol = float(policy.get("target_annualized_vol_pct", 22.0))
    vol_floor = float(policy.get("vol_scalar_floor", 0.45))
    vol_cap = float(policy.get("vol_scalar_cap", 1.20))
    vol_scalar = min(vol_cap, max(vol_floor, target_vol / max(float(vol), 1.0)))
    corr_soft = float(policy.get("correlation_soft_limit", 0.85))
    corr_penalty = float(policy.get("correlation_penalty", 0.75))
    corr_scalar = max(0.50, 1.0 - max(0.0, float(corr) - corr_soft) * corr_penalty)

    max_tilt = float(policy.get("max_active_tilt_pct", 4.0))
    sector_cap = float(policy.get("sector_cap_pct", 25.0))
    scaled_target = max(0.0, mandate_target * vol_scalar * corr_scalar)
    policy_ceiling = min(sector_cap, mandate_target + max_tilt)
    risk_target = min(policy_ceiling, scaled_target)
    capacity = max(0.0, risk_target - float(current_weight_pct))
    minimum = float(policy.get("min_capacity_pct", 1.0))
    return {
        **base_out,
        "eligible": capacity >= minimum,
        "quality": "ok",
        "risk_scaled_target_pct": round(scaled_target, 2),
        "policy_target_ceiling_pct": round(policy_ceiling, 2),
        "risk_target_pct": round(risk_target, 2),
        "current_account_weight_pct": round(float(current_weight_pct), 2),
        "current_weight_pct": round(float(current_weight_pct), 2),
        "capacity_pct": round(capacity, 2),
        "vol_scalar": round(vol_scalar, 3),
        "correlation_scalar": round(corr_scalar, 3),
    }


def peer_medians(records: Iterable[dict]) -> dict:
    keys = ("forward_pe", "pfcf", "roic_pct", "profit_margin_pct", "total_debt_equity")
    out: dict[str, Any] = {}
    records = list(records)
    for key in keys:
        vals = [float(r[key]) for r in records if r.get(key) is not None and float(r[key]) > 0]
        out[key] = median(vals) if vals else None
    return out


def stock_quality_assessment(record: dict, peers: dict, cfg: dict) -> dict:
    """Transparent stock gate; required institutional evidence fails closed."""
    qcfg = cfg.get("stock_quality") or {}
    required = ("forward_pe", "pfcf", "eps_next_y", "eps_qoq", "sales_qoq", "roic_pct",
                "profit_margin_pct", "total_debt_equity", "short_float_pct", "beta", "sma50_pct")
    present = [k for k in required if record.get(k) is not None]
    missing = [k for k in required if k not in present]
    coverage = len(present) / len(required)
    score = 0.0
    factors: list[dict] = []
    hard_fail: list[str] = []

    def add(name: str, ok: bool, points: float, value: Any):
        nonlocal score
        if ok:
            score += points
        factors.append({"name": name, "value": value, "passed": bool(ok),
                        "points": points if ok else 0})

    fpe, pfcf = record.get("forward_pe"), record.get("pfcf")
    add("forward valuation", fpe is not None and fpe > 0 and
        (peers.get("forward_pe") is None or fpe <= peers["forward_pe"] * 1.25), 10, fpe)
    add("FCF valuation", pfcf is not None and pfcf > 0 and
        (peers.get("pfcf") is None or pfcf <= peers["pfcf"] * 1.25), 10, pfcf)
    add("next-year EPS", (record.get("eps_next_y") or 0) > 0, 10, record.get("eps_next_y"))
    add("EPS revisions/growth", (record.get("eps_qoq") or 0) > 0, 9, record.get("eps_qoq"))
    add("sales growth", (record.get("sales_qoq") or 0) > 0, 8, record.get("sales_qoq"))
    add("ROIC", (record.get("roic_pct") or -999) >= float(qcfg.get("min_roic_pct", 8)), 12, record.get("roic_pct"))
    add("profitability", (record.get("profit_margin_pct") or -999) > 0, 8, record.get("profit_margin_pct"))
    debt = record.get("total_debt_equity")
    add("leverage", debt is not None and debt <= float(qcfg.get("max_debt_equity", 2.0)), 10, debt)
    short = record.get("short_float_pct")
    add("crowding", short is not None and short <= float(qcfg.get("max_short_float_pct", 12.0)), 8, short)
    add("beta", record.get("beta") is not None and record["beta"] <= float(qcfg.get("max_beta", 1.7)), 7, record.get("beta"))
    ext = record.get("sma50_pct")
    add("non-extension", ext is not None and -20 <= ext <= float(qcfg.get("max_above_sma50_pct", 12.0)), 8, ext)

    if debt is not None and debt > float(qcfg.get("hard_fail_debt_equity", 4.0)):
        hard_fail.append("excess_leverage")
    if short is not None and short > float(qcfg.get("hard_fail_short_float_pct", 25.0)):
        hard_fail.append("extreme_crowding")

    min_coverage = float(qcfg.get("min_coverage", 0.60))
    min_score = float(qcfg.get("min_score", 60.0))
    require_all = bool(qcfg.get("require_all_fields", True))
    evidence_complete = not missing if require_all else coverage >= min_coverage
    return {
        "passed": evidence_complete and coverage >= min_coverage and score >= min_score and not hard_fail,
        "score": round(score, 1),
        "coverage": round(coverage, 3),
        "evidence_complete": evidence_complete,
        "missing": missing,
        "hard_fail": hard_fail,
        "factors": factors,
        "version": "institutional-stock-gate-v2",
    }
