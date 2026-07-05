"""Daily Hermes Learning Scorecard — measurable closed-loop maturity proof."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCORECARD_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_learning_scorecard.json"


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _count_since(rows: list[dict[str, Any]], ts_key: str, since: datetime) -> int:
    n = 0
    for r in rows:
        raw = r.get(ts_key)
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt >= since:
                n += 1
        except Exception:
            continue
    return n


def _query_scope_governor_24h() -> dict[str, Any]:
    out = {"promoted": 0, "demoted": 0, "total_changes": 0, "by_tier": {}}
    try:
        from db_adapter import USE_DB, _db_query
        if not USE_DB:
            return out
        rows = _db_query(
            """SELECT action, from_tier, to_tier, COUNT(*) AS n
               FROM scope_governor_audit
               WHERE created_at > NOW() - interval '24 hours'
                 AND symbol <> '__BUS__'
               GROUP BY action, from_tier, to_tier""",
        ) or []
        for r in rows:
            act = str(r.get("action") or "")
            n = int(r.get("n") or 0)
            out["total_changes"] += n
            if act in ("promote", "promoted", "tier_up"):
                out["promoted"] += n
            elif act in ("demote", "demoted", "tier_down"):
                out["demoted"] += n
        tier_rows = _db_query(
            """SELECT scope_tier, COUNT(*) AS n FROM watchlist_items
               WHERE scope_tier IN ('S0','S1','S2','S3','S4')
                 AND status IN ('active','researched')
               GROUP BY scope_tier""",
        ) or []
        out["by_tier"] = {str(r.get("scope_tier")): int(r.get("n") or 0) for r in tier_rows}
    except Exception:
        pass
    return out


def _query_research_24h() -> dict[str, Any]:
    out = {"rows_generated": 0, "useful_rows": 0, "hit_rate": None}
    try:
        from db_adapter import USE_DB, _db_query
        if not USE_DB:
            return out
        rows = _db_query(
            """SELECT count(*) AS total,
                      count(*) FILTER (WHERE recommendation IS NOT NULL
                                       AND recommendation NOT LIKE '[%%') AS useful
               FROM hermes_external_research
               WHERE created_at > NOW() - interval '24 hours'""",
        ) or []
        if rows:
            total = int((rows[0] or {}).get("total") or 0)
            useful = int((rows[0] or {}).get("useful") or 0)
            out["rows_generated"] = total
            out["useful_rows"] = useful
            out["hit_rate"] = round(useful / max(total, 1), 3)
    except Exception:
        pass
    return out


def _threshold_proposal_counts(proposals: dict[str, Any], since: datetime) -> dict[str, int]:
    counts = {
        "pending": len(proposals.get("pending") or []),
        "approved": 0,
        "rejected": 0,
        "reverted": 0,
    }
    for p in proposals.get("decided") or []:
        try:
            dt = datetime.fromisoformat(str(p.get("decided_at") or "").replace("Z", "+00:00"))
            if dt < since:
                continue
        except Exception:
            continue
        st = str(p.get("status") or "")
        if st == "approved":
            counts["approved"] += 1
        elif st == "rejected":
            counts["rejected"] += 1
    try:
        from lib.hermes_thresholds.store import load_active_thresholds
        active = load_active_thresholds()
        for h in active.get("history") or []:
            if str(h.get("action")) != "rollback":
                continue
            try:
                dt = datetime.fromisoformat(str(h.get("at") or "").replace("Z", "+00:00"))
                if dt >= since:
                    counts["reverted"] += 1
            except Exception:
                continue
    except Exception:
        pass
    return counts


def _learned_vs_static(threshold_status: dict[str, Any] | None) -> dict[str, Any]:
    rows = (threshold_status or {}).get("thresholds") or []
    learned = [r for r in rows if r.get("is_learned") or r.get("status") == "learned"]
    static = [r for r in rows if r.get("status") == "static"]
    pending = [r for r in rows if r.get("status") == "pending_review"]
    sample_sizes: dict[str, Any] = {}
    for r in learned + pending:
        tid = r.get("threshold_id")
        ev = r.get("evidence") or {}
        sample_sizes[str(tid)] = {
            "sample_size": ev.get("sample_days") or ev.get("sample_size"),
            "confidence": ev.get("confidence"),
            "status": r.get("status"),
        }
    return {
        "learned_count": len(learned),
        "static_count": len(static),
        "pending_review_count": len(pending),
        "sample_size_by_threshold": sample_sizes,
    }


def _subsystem_maturity(bus: dict[str, Any], threshold_status: dict[str, Any] | None) -> dict[str, Any]:
    maturity = bus.get("maturity") or {}
    components = maturity.get("components") or {}
    readiness = (threshold_status or {}).get("learning_ready")
    return {
        "composite_score": maturity.get("composite_score"),
        "maturity_score": maturity.get("maturity_score"),
        "tier": maturity.get("tier"),
        "trend": maturity.get("trend"),
        "outcome_yield": (components.get("outcome_yield") or {}).get("score"),
        "scope_discipline": (components.get("scope_discipline") or {}).get("score"),
        "stop_quality": (components.get("stop_quality") or {}).get("score"),
        "feedback_loop": (components.get("feedback_loop") or {}).get("score"),
        "research_actionability": (components.get("research_actionability") or {}).get("score"),
        "threshold_learning_ready": readiness,
        "threshold_learning_status": (threshold_status or {}).get("learning_status"),
    }


def _false_positive_negative(bus: dict[str, Any], trend: dict[str, Any]) -> dict[str, Any]:
    """Proxy FP/FN from outcome bus global + trend where measurable."""
    g = bus.get("global") or {}
    series = trend.get("series") or []
    hr_vals = [_num(s.get("hit_rate_promotions")) for s in series if _num(s.get("hit_rate_promotions")) is not None]
    fp_proxy = None
    if hr_vals and len(hr_vals) >= 2:
        recent = hr_vals[-1]
        peak = max(hr_vals)
        if peak and recent is not None:
            fp_proxy = round(max(0.0, peak - recent), 3)

    graded = int(g.get("graded_claims_90d") or 0)
    hits = int(g.get("positive_outcomes_90d") or g.get("hits_90d") or 0)
    fn_proxy = None
    if graded > 0 and g.get("hit_rate_promotions") is not None:
        hr = float(g["hit_rate_promotions"])
        fn_proxy = round(max(0.0, 1.0 - hr), 3)

    return {
        "false_positive_rate_proxy": fp_proxy,
        "false_negative_rate_proxy": fn_proxy,
        "measurable": fp_proxy is not None or fn_proxy is not None,
        "note": "Proxy metrics from hit-rate trend; not execution-grade precision",
    }


def build_learning_scorecard(
    *,
    lookback_hours: int = 24,
    persist: bool = True,
) -> dict[str, Any]:
    """Assemble daily learning scorecard from closed-loop sources."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=lookback_hours)
    day = now.strftime("%Y-%m-%d")

    from lib.hermes_outcome_bus.bus import load_outcome_bus, load_outcome_bus_trend, read_outcome_bus
    from lib.hermes_thresholds.store import load_proposals

    bus = read_outcome_bus() or load_outcome_bus()
    trend = load_outcome_bus_trend(days=30)
    proposals = load_proposals()

    threshold_status: dict[str, Any] = {}
    try:
        from lib.hermes_thresholds.workflow import threshold_status
        threshold_status = threshold_status()
    except Exception:
        pass

    g = bus.get("global") or {}
    resource = bus.get("resource_efficiency") or {}
    scope = _query_scope_governor_24h()
    research = _query_research_24h()
    proposal_counts = _threshold_proposal_counts(proposals, since)
    learned_static = _learned_vs_static(threshold_status)
    fp_fn = _false_positive_negative(bus, trend)

    signals_reviewed = int(g.get("graded_claims_90d") or g.get("signals_reviewed_90d") or 0)
    operator_accepted = proposal_counts["approved"]
    operator_rejected = proposal_counts["rejected"]

    maturity_before = None
    series = trend.get("series") or []
    if len(series) >= 2:
        prior = _num(series[0].get("maturity_composite_score"))
        current = _num(series[-1].get("maturity_composite_score"))
        if prior is not None and current is not None:
            maturity_before = round(prior / 20.0, 2)

    maturity_after = (bus.get("maturity") or {}).get("maturity_score")
    if maturity_after is None:
        comp = (bus.get("maturity") or {}).get("composite_score")
        if comp is not None:
            maturity_after = round(float(comp) / 20.0, 2)

    payload = {
        "version": "hermes-learning-scorecard-v1",
        "day": day,
        "generated_at": now.isoformat(),
        "lookback_hours": lookback_hours,
        "advisory_only": True,
        "signals_reviewed": signals_reviewed,
        "symbols_monitored_by_tier": scope.get("by_tier") or {},
        "symbols_promoted": scope.get("promoted", 0),
        "symbols_demoted": scope.get("demoted", 0),
        "scope_changes_24h": scope.get("total_changes", 0),
        "research_rows_generated": research.get("rows_generated", 0),
        "useful_research_hit_rate": research.get("hit_rate"),
        "operator_accepted": operator_accepted,
        "operator_rejected": operator_rejected,
        "outcome_hit_rate": g.get("hit_rate_promotions"),
        "outcome_yield_trades": g.get("hit_rate_trades"),
        "false_positive_rate": fp_fn.get("false_positive_rate_proxy"),
        "false_negative_rate": fp_fn.get("false_negative_rate_proxy"),
        "avg_time_to_useful_signal_hours": g.get("avg_time_to_useful_signal_hours"),
        "resource_efficiency_score": resource.get("score") or resource.get("resource_efficiency_score"),
        "threshold_proposals_pending": proposal_counts["pending"],
        "threshold_proposals_approved": proposal_counts["approved"],
        "threshold_proposals_rejected": proposal_counts["rejected"],
        "threshold_proposals_reverted": proposal_counts["reverted"],
        "thresholds_learned_vs_static": learned_static,
        "maturity_score_by_subsystem": _subsystem_maturity(bus, threshold_status),
        "maturity_score_before": maturity_before,
        "maturity_score_after": maturity_after,
        "outcome_bus_run_id": bus.get("run_id"),
        "outcome_bus_generated_at": bus.get("generated_at"),
        "note": "Advisory-only scorecard — no execution or broker writes",
    }

    if persist:
        SCORECARD_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = SCORECARD_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        tmp.replace(SCORECARD_PATH)

    return payload


def load_learning_scorecard() -> dict[str, Any]:
    if not SCORECARD_PATH.exists():
        return build_learning_scorecard(persist=True)
    try:
        return json.loads(SCORECARD_PATH.read_text(encoding="utf-8"))
    except Exception:
        return build_learning_scorecard(persist=True)