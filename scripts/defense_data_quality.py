#!/usr/bin/env python3
"""Deterministic quality, provenance and risk contracts for Defense/Sectors.

This module is intentionally advisory and side-effect free except for read-only SQL in
``realized_vol_corr``.  It never places orders, changes permissions, or promotes rules.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median, pstdev
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_VERSION = "defense-data-quality-v1"
SECTOR_CALC_VERSION = "sector-rs-v3-exact20"
INDUSTRY_CALC_VERSION = "industry-rs-v3-finviz-aligned"
RECOMMENDATION_CALC_VERSION = "defense-recommendations-v9-risk-aware"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def snapshot_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def truth_ref(*, source: str, as_of: Any, calculation_version: str,
              cadence: str, quality: str = "ok", coverage_n: int | None = None,
              coverage_total: int | None = None, notes: list[str] | None = None) -> dict:
    out = {
        "source": source,
        "source_as_of": str(as_of) if as_of is not None else None,
        "calculation_version": calculation_version,
        "cadence": cadence,
        "quality": quality,
    }
    if coverage_n is not None:
        out["coverage_n"] = int(coverage_n)
    if coverage_total is not None:
        out["coverage_total"] = int(coverage_total)
    if notes:
        out["notes"] = list(notes)
    return out


def _date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except Exception:
        return None


def staleness(as_of: Any, reference_as_of: Any, max_calendar_days: int = 4) -> dict:
    a, ref = _date(as_of), _date(reference_as_of)
    if not a or not ref:
        return {"stale": True, "age_days": None, "quality": "unknown_date"}
    age = max(0, (ref - a).days)
    return {"stale": age > max_calendar_days, "age_days": age,
            "quality": "quarantined_stale" if age > max_calendar_days else "ok"}


def load_industry_map(root: Path = ROOT) -> dict:
    return json.loads((root / "config" / "industry_sector_map.json").read_text())


def canonical_industry_sector(industry: str, cfg: dict | None = None) -> dict:
    """Return a deterministic, versioned industry→sector result.

    Exact overrides win. Regex rules are reviewed configuration, not a database-mode
    inference. Unknown industries remain explicitly unmapped.
    """
    cfg = cfg or load_industry_map()
    name = (industry or "").strip()
    exact = cfg.get("exact", {}).get(name)
    if exact:
        return {"sector": exact, "mapping_quality": "exact",
                "mapping_version": cfg.get("version")}
    for rule in cfg.get("rules", []):
        if re.search(rule["pattern"], name, flags=re.I):
            return {"sector": rule["sector"], "mapping_quality": "rule",
                    "mapping_rule": rule.get("id"), "mapping_version": cfg.get("version")}
    return {"sector": None, "mapping_quality": "unmapped",
            "mapping_version": cfg.get("version")}


def _daily_returns(series: list[tuple[Any, float]]) -> dict[Any, float]:
    dedup: dict[Any, float] = {}
    for d, px in series:
        if px is not None:
            dedup[d] = float(px)
    ordered = sorted(dedup.items())
    out = {}
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


def allocation_decision(cfg: dict, *, sector: str, current_weight_pct: float,
                        risk_context: dict, account: str | None = None) -> dict:
    """Benchmark/mandate/volatility/correlation-aware active-weight capacity."""
    policy = cfg.get("allocation_policy") or {}
    benchmark_name = policy.get("default_benchmark", "equal_sector")
    benchmark = (policy.get("benchmarks") or {}).get(benchmark_name, {})
    base_target = float(benchmark.get(sector, cfg.get("neutral_sector_weight_pct", 9.1)))
    mandate_name = (policy.get("account_mandates") or {}).get(account, "total_return")
    mandate = (policy.get("mandates") or {}).get(mandate_name, {})
    tilt = float((mandate.get("sector_tilts_pct") or {}).get(sector, 0.0))
    raw_target = base_target + tilt
    vol = risk_context.get("annualized_vol_pct")
    corr = risk_context.get("correlation")
    if risk_context.get("quality") != "ok" or vol is None or corr is None:
        return {"eligible": False, "quality": "missing_risk_context", "benchmark": benchmark_name,
                "mandate": mandate_name, "base_target_pct": round(base_target, 2),
                "target_pct": round(raw_target, 2), "capacity_pct": 0.0,
                "risk_context": risk_context}
    target_vol = float(policy.get("target_annualized_vol_pct", 22.0))
    vol_floor = float(policy.get("vol_scalar_floor", 0.45))
    vol_cap = float(policy.get("vol_scalar_cap", 1.20))
    vol_scalar = min(vol_cap, max(vol_floor, target_vol / max(float(vol), 1.0)))
    corr_soft = float(policy.get("correlation_soft_limit", 0.85))
    corr_penalty = float(policy.get("correlation_penalty", 0.75))
    corr_scalar = max(0.50, 1.0 - max(0.0, float(corr) - corr_soft) * corr_penalty)
    max_tilt = float(policy.get("max_active_tilt_pct", 4.0))
    sector_cap = float(policy.get("sector_cap_pct", 25.0))
    risk_target = min(sector_cap, raw_target * vol_scalar * corr_scalar + max_tilt)
    capacity = max(0.0, risk_target - float(current_weight_pct or 0.0))
    minimum = float(policy.get("min_capacity_pct", 1.0))
    return {
        "eligible": capacity >= minimum,
        "quality": "ok",
        "benchmark": benchmark_name,
        "mandate": mandate_name,
        "base_target_pct": round(base_target, 2),
        "mandate_tilt_pct": round(tilt, 2),
        "risk_target_pct": round(risk_target, 2),
        "current_weight_pct": round(float(current_weight_pct or 0.0), 2),
        "capacity_pct": round(capacity, 2),
        "vol_scalar": round(vol_scalar, 3),
        "correlation_scalar": round(corr_scalar, 3),
        "risk_context": risk_context,
    }


def peer_medians(records: Iterable[dict]) -> dict:
    keys = ("forward_pe", "pfcf", "roic_pct", "profit_margin_pct", "total_debt_equity")
    out = {}
    records = list(records)
    for key in keys:
        vals = [float(r[key]) for r in records if r.get(key) is not None and float(r[key]) > 0]
        out[key] = median(vals) if vals else None
    return out


def stock_quality_assessment(record: dict, peers: dict, cfg: dict) -> dict:
    """Transparent quality gate using available valuation, growth and balance-sheet data."""
    qcfg = cfg.get("stock_quality") or {}
    required = ("forward_pe", "pfcf", "eps_next_y", "eps_qoq", "sales_qoq", "roic_pct",
                "profit_margin_pct", "total_debt_equity", "short_float_pct", "beta", "sma50_pct")
    present = [k for k in required if record.get(k) is not None]
    coverage = len(present) / len(required)
    score, factors, hard_fail = 0.0, [], []

    def add(name: str, ok: bool, points: float, value: Any):
        nonlocal score
        if ok:
            score += points
        factors.append({"name": name, "value": value, "passed": bool(ok), "points": points if ok else 0})

    fpe, pfcf = record.get("forward_pe"), record.get("pfcf")
    add("forward valuation", fpe is not None and fpe > 0 and (peers.get("forward_pe") is None or fpe <= peers["forward_pe"] * 1.25), 10, fpe)
    add("FCF valuation", pfcf is not None and pfcf > 0 and (peers.get("pfcf") is None or pfcf <= peers["pfcf"] * 1.25), 10, pfcf)
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
    return {"passed": coverage >= min_coverage and score >= min_score and not hard_fail,
            "score": round(score, 1), "coverage": round(coverage, 3),
            "missing": [k for k in required if k not in present], "hard_fail": hard_fail,
            "factors": factors, "version": "institutional-stock-gate-v1"}


def directive_review_status(lean_cfg: dict, sectors: list[dict], now: date | None = None) -> dict:
    now = now or datetime.now(timezone.utc).date()
    set_at = _date(lean_cfg.get("set_at"))
    review_after = int(lean_cfg.get("review_after_days", 5))
    age = (now - set_at).days if set_at else None
    defensive = set(lean_cfg.get("defensive_sectors") or [])
    conflicts = [r.get("sector") for r in sectors
                 if r.get("sector") not in defensive and r.get("state") in ("LEADING", "IMPROVING")
                 and not r.get("quarantined")]
    due = bool(lean_cfg.get("enabled")) and ((age is None or age >= review_after) or bool(conflicts))
    return {"enabled": bool(lean_cfg.get("enabled")), "requires_review": due,
            "set_at": str(set_at) if set_at else None, "age_days": age,
            "review_after_days": review_after, "conflicting_sectors": conflicts,
            "instruction": "retain until operator adjudication; never auto-revoke" if due else "retain"}
