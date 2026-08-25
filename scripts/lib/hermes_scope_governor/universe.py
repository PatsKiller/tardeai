"""Versioned governed-universe feed for Hermes consumers."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import GovernedUniverse, ScopeDecision, TIER_FREQUENCY, heat_of

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
UNIVERSE_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_governed_universe.json"
HISTORY_DIR = PROJECT_ROOT / "data" / "runtime" / "hermes_governed_universe_history"


def estimate_daily_computations(counts: dict[str, int]) -> int:
    """Rough score-computation budget from tier counts (matches HERMES_INTELLIGENCE_ENGINE math)."""
    s0 = counts.get("S0", 0)
    s1 = counts.get("S1", 0)
    s2 = counts.get("S2", 0)
    # market day: S0 ~26, S1 ~13, S2 ~1, plus ~500 events (conservative flat add)
    return int(s0 * 26 + s1 * 13 + s2 * 1 + 500)


def build_governed_universe(
    run_id: str,
    regime_label: str | None,
    total_cap: int,
    post_tiers: dict[str, str],
    edge_scores: dict[str, float],
    decisions: list[ScopeDecision],
    cfg: dict[str, Any],
) -> GovernedUniverse:
    counts = {"S0": 0, "S1": 0, "S2": 0, "S3": 0}
    for t in post_tiers.values():
        counts[t] = counts.get(t, 0) + 1
    heat_counts = {"hot": counts["S0"] + counts["S1"], "warm": counts["S2"], "cold": counts["S3"]}

    symbols = []
    for sym, tier in sorted(post_tiers.items(), key=lambda x: ({"S0": 0, "S1": 1, "S2": 2, "S3": 3}[x[1]], -edge_scores.get(x[0], 0))):
        h = heat_of(tier)
        freq_key = (cfg.get("tiers") or {}).get(tier.lower(), {}).get("scored") if tier != "S0" else "every_run"
        if tier == "S0":
            freq_key = "every_run"
        symbols.append({
            "symbol": sym,
            "scope_tier": tier,
            "heat": h,
            "edge_score": edge_scores.get(sym),
            "monitoring_frequency": TIER_FREQUENCY.get(tier, str(freq_key)),
        })

    recent = [
        {
            "symbol": d.symbol,
            "action": d.action,
            "from_tier": d.from_tier,
            "to_tier": d.to_tier,
            "heat": d.heat,
            "reason": d.reason,
            "edge_score": d.edge_score,
            "evidence": d.evidence,
        }
        for d in decisions[:50]
    ]

    return GovernedUniverse(
        version="hermes-scope-governor-v2",
        run_id=run_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        regime_label=regime_label,
        total_cap=total_cap,
        counts_by_tier=counts,
        counts_by_heat=heat_counts,
        live_universe=counts["S0"] + counts["S1"] + counts["S2"],
        estimated_score_computations_per_day=estimate_daily_computations(counts),
        symbols=symbols,
        recent_decisions=recent,
    )


def write_universe_feed(gov: GovernedUniverse, apply: bool = True) -> Path | None:
    if not apply:
        return None
    UNIVERSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": gov.version,
        "run_id": gov.run_id,
        "generated_at": gov.generated_at,
        "regime_label": gov.regime_label,
        "total_cap": gov.total_cap,
        "counts_by_tier": gov.counts_by_tier,
        "counts_by_heat": gov.counts_by_heat,
        "live_universe": gov.live_universe,
        "live_universe_is_not_canonical": True,
        "not_the_canonical_universe": True,
        "cohort": "hermes_scope_scored_s0_s2",
        "canonical_contract": "TransfersonUniverseManifest@v1",
        "estimated_score_computations_per_day": gov.estimated_score_computations_per_day,
        "symbols": gov.symbols,
        "recent_decisions": gov.recent_decisions,
    }
    UNIVERSE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = gov.generated_at.replace(":", "").replace("+", "")[:15]
    hist = HISTORY_DIR / f"universe_{stamp}_{gov.run_id}.json"
    hist.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return UNIVERSE_PATH


def read_universe_feed() -> dict[str, Any] | None:
    if not UNIVERSE_PATH.exists():
        return None
    try:
        return json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_generated_at(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except Exception:
        return None


def load_universe_trend(days: int = 30) -> dict[str, Any]:
    """Daily Hot/Warm/Cold trend from governed-universe history (latest per UTC day)."""
    days = max(1, min(int(days), 90))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    snapshots: list[tuple[datetime, dict[str, Any]]] = []
    current = read_universe_feed()
    if current:
        ts = _parse_generated_at(current.get("generated_at"))
        if ts and ts >= cutoff:
            snapshots.append((ts, current))

    if HISTORY_DIR.exists():
        for path in HISTORY_DIR.glob("universe_*.json"):
            try:
                snap = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            ts = _parse_generated_at(snap.get("generated_at"))
            if ts and ts >= cutoff:
                snapshots.append((ts, snap))

    by_day: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for ts, snap in snapshots:
        day = ts.strftime("%Y-%m-%d")
        cur = by_day.get(day)
        if cur is None or ts > cur[0]:
            by_day[day] = (ts, snap)

    series = []
    for _day, (ts, snap) in sorted(by_day.items()):
        heat = snap.get("counts_by_heat") or {}
        series.append({
            "at": ts.isoformat(),
            "day": ts.strftime("%Y-%m-%d"),
            "run_id": snap.get("run_id"),
            "hot": heat.get("hot"),
            "warm": heat.get("warm"),
            "cold": heat.get("cold"),
            "live_universe": snap.get("live_universe"),
        })

    hot = [s["hot"] for s in series if s.get("hot") is not None]
    return {
        "days": days,
        "count": len(series),
        "series": series,
        "summary": {
            "current_hot": hot[-1] if hot else None,
            "delta_hot": (hot[-1] - hot[0]) if len(hot) >= 2 else None,
            "first_at": series[0]["at"] if series else None,
            "last_at": series[-1]["at"] if series else None,
        },
    }