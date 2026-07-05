#!/usr/bin/env python3
"""hermes_outcome_feedback_agent.py — Outcome & Feedback Agent (outcome-bus-v1).

Turns graded ledger outcomes into a structured, versioned outcome_bus.json that the Scope
Governor and Research Agent consume.

Cadence (nightly):
  02:50 hermes_outcome_grader.py
  03:05 hermes_tag_engine.py          # fresh tag_efficacy before bus
  03:25 hermes_outcome_feedback_agent.py  # THIS AGENT
  03:35 hermes_outcome_learning.py

Design law: outcome yield outranks throughput yield.

  python3 scripts/hermes_outcome_feedback_agent.py            # dry-run
  python3 scripts/hermes_outcome_feedback_agent.py --apply   # write outcome_bus.json
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

from lib.hermes_outcome_bus.alert_enrichment import enrich_alerts
from lib.hermes_outcome_bus.alert_notifications import dispatch_alert_notifications
from lib.hermes_outcome_bus.alerts import evaluate_alerts
from lib.hermes_outcome_bus.maturity import build_maturity_status, write_maturity_snapshot
from lib.hermes_outcome_bus.bus import (OUTCOME_BUS_VERSION, build_discovery_health_section,
                                        load_outcome_bus_trend, read_outcome_bus, write_outcome_bus)
from lib.hermes_outcome_bus.bus_traceability import enrich_bus_traceability
from lib.hermes_outcome_bus.metrics import build_stop_correlations, compute_resource_efficiency_score
from lib.hermes_logging.request_logger import aggregate_request_stats
from lib.hermes_scope_governor.scoring import outcome_gate
from lib.hermes_scope_governor.models import SymbolSignals

KILL_SWITCH = PROJECT_ROOT / "data" / "runtime" / "HERMES_DISABLED"
CFG_FILE = PROJECT_ROOT / "config" / "hermes_outcome_feedback.yaml"
ALERTS_CFG_FILE = PROJECT_ROOT / "config" / "hermes_alerts.yaml"

PRICE_SUBJECT_TYPES = ("promotion", "external_rec", "trade")


def _cfg() -> dict[str, Any]:
    import yaml
    cfg = yaml.safe_load(CFG_FILE.read_text()) or {}
    try:
        alert_cfg = yaml.safe_load(ALERTS_CFG_FILE.read_text()) or {}
        cfg["notifications"] = alert_cfg.get("notifications") or {}
    except Exception:
        cfg.setdefault("notifications", {})
    return cfg


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _round(v: float | None, n: int = 3) -> float | None:
    return round(float(v), n) if v is not None else None


def _hit_rate(hits: int, misses: int) -> float | None:
    d = hits + misses
    return _round(hits / d, 3) if d else None


def _tag_quality_multiplier(lift: float | None, flagged: bool, cfg: dict[str, Any]) -> float:
    tg = cfg.get("tag_gates") or {}
    floor = float(tg.get("floor_multiplier", 0.3))
    ceil = float(tg.get("ceiling_multiplier", 1.25))
    down = float(tg.get("downrank_multiplier", 0.6))
    boost = float(tg.get("boost_multiplier", 1.15))
    if lift is None:
        return 1.0
    if flagged or lift <= float(tg.get("negative_lift_downrank", 0.0)):
        return max(floor, down)
    if lift >= float(tg.get("positive_lift_boost", 0.02)):
        return min(ceil, boost)
    return 1.0


def _bad_dominant_tag(meta: dict[str, Any]) -> bool:
    lift = meta.get("lift")
    return bool(meta.get("tag_flagged")) or (lift is not None and float(lift) < 0)


def _symbol_poor_outcomes(meta: dict[str, Any], gates: dict[str, Any]) -> bool:
    """Poor symbol outcomes: price-graded n≥3 and low hit rate or demote/pause gate."""
    min_n = int(gates.get("min_graded_samples", 3))
    n = int(meta.get("n") or 0)
    if n < min_n:
        return False
    gate = meta.get("gate")
    if gate in ("demote_pressure", "pause_eligible", "pause"):
        return True
    hits = int(meta.get("outcome_hits") or 0)
    misses = int(meta.get("misses") or 0)
    if hits + misses < min_n:
        return False
    return (hits / (hits + misses)) < float(gates.get("promote_hit_rate", 0.5))


def _resolve_symbol_gate(raw_gate: str, meta: dict[str, Any]) -> str:
    """Block promotion when dominant tag has negative lift (design law at tag level)."""
    if raw_gate == "promote_eligible" and _bad_dominant_tag(meta):
        return "promote_blocked_bad_tag"
    return raw_gate


def fetch_global_metrics(cur, cfg: dict[str, Any]) -> dict[str, Any]:
    lookback = int(cfg.get("lookback_days", 90))
    tp_days = int(cfg.get("research_throughput_days", 7))

    # Split hit rates — never mix research action-hits with price-graded promotions/trades
    cur.execute("""SELECT
                     count(*) FILTER (WHERE subject_type IN ('promotion','external_rec')
                                        AND verdict='hit') AS promo_hits,
                     count(*) FILTER (WHERE subject_type IN ('promotion','external_rec')
                                        AND verdict='miss') AS promo_misses,
                     count(*) FILTER (WHERE subject_type='research_row' AND verdict='hit') AS res_hits,
                     count(*) FILTER (WHERE subject_type='research_row'
                                        AND verdict IN ('hit','miss','neutral')) AS res_graded,
                     count(*) FILTER (WHERE subject_type='trade' AND verdict='hit') AS trade_hits,
                     count(*) FILTER (WHERE subject_type='trade' AND verdict='miss') AS trade_misses,
                     count(*) FILTER (WHERE verdict IN ('hit','miss','neutral')) AS graded_total,
                     avg(realized_r) FILTER (WHERE subject_type='trade' AND realized_r IS NOT NULL) AS avg_r
                   FROM hermes_outcome_ledger
                   WHERE emitted_at > NOW() - make_interval(days => %s)""", (lookback,))
    row = cur.fetchone()
    promo_h, promo_m = int(row[0] or 0), int(row[1] or 0)
    res_h, res_graded = int(row[2] or 0), int(row[3] or 0)
    trade_h, trade_m = int(row[4] or 0), int(row[5] or 0)

    cur.execute("""SELECT count(*) FROM hermes_research_intelligence
                   WHERE created_at > NOW() - make_interval(days => %s)""", (tp_days,))
    research_rows = int(cur.fetchone()[0] or 0)
    cur.execute("""SELECT count(*) FROM hermes_score_history
                   WHERE scored_at > NOW() - make_interval(days => %s)""", (tp_days,))
    score_writes = int(cur.fetchone()[0] or 0)
    cur.execute("""SELECT count(*) FROM hermes_external_research
                   WHERE created_at > NOW() - make_interval(days => %s)
                     AND lane IN ('grok','chatgpt','claude','internal-deep')""", (tp_days,))
    ext_calls = int(cur.fetchone()[0] or 0)

    return {
        "graded_claims_90d": int(row[6] or 0),
        "hit_rate_promotions": _hit_rate(promo_h, promo_m),
        "hit_rate_research_actioned": _round(res_h / res_graded, 3) if res_graded else None,
        "hit_rate_trades": _hit_rate(trade_h, trade_m),
        "avg_realized_r_trades_90d": _round(row[7], 3),
        "throughput_research_rows_7d": research_rows,
        "throughput_score_writes_7d": score_writes,
        "throughput_external_calls_7d": ext_calls,
    }


def fetch_by_symbol(cur, cfg: dict[str, Any]) -> dict[str, Any]:
    lookback = int(cfg.get("lookback_days", 90))
    gates = cfg.get("outcome_gates") or {}
    scfg = {"outcome_gates": gates}
    demote_pen = int(gates.get("demote_score_penalty", -20))
    promote_boost = int(gates.get("promote_score_boost", 8))

    cur.execute("""SELECT UPPER(symbol),
                          count(*) FILTER (WHERE subject_type IN ('promotion','external_rec','trade')
                                           AND verdict='hit') AS price_hits,
                          count(*) FILTER (WHERE subject_type IN ('promotion','external_rec','trade')
                                           AND verdict='miss') AS price_misses,
                          count(*) FILTER (WHERE subject_type IN ('promotion','external_rec','trade')
                                           AND verdict='neutral') AS price_neutral,
                          avg(realized_r) FILTER (WHERE subject_type='trade'
                                                  AND realized_r IS NOT NULL) AS avg_r,
                          max(graded_at)::date AS last_graded
                   FROM hermes_outcome_ledger
                   WHERE symbol IS NOT NULL
                     AND emitted_at > NOW() - make_interval(days => %s)
                     AND verdict IN ('hit','miss','neutral')
                   GROUP BY UPPER(symbol)
                   HAVING count(*) FILTER (WHERE subject_type IN ('promotion','external_rec','trade')) >= 1""",
                (lookback,))
    rows = cur.fetchall()

    cur.execute("""SELECT UPPER(hri.symbol) sym, unnest(hri.strategy_tags) tag, count(*) c
                   FROM hermes_research_intelligence hri
                   WHERE hri.symbol IS NOT NULL AND hri.strategy_tags IS NOT NULL
                     AND hri.created_at > NOW() - make_interval(days => %s)
                   GROUP BY 1, 2""", (lookback,))
    tag_counts: dict[str, dict[str, int]] = {}
    for sym, tag, c in cur.fetchall():
        tag_counts.setdefault(sym, {})[tag] = int(c)

    tag_meta: dict[str, dict[str, Any]] = {}
    cur.execute("SELECT tag, lift, flagged, hit_rate FROM hermes_tag_efficacy")
    for tag, lift, flagged, hr in cur.fetchall():
        tag_meta[str(tag)] = {
            "lift": float(lift) if lift is not None else None,
            "flagged": bool(flagged),
            "precision": float(hr) if hr is not None else None,
        }

    out: dict[str, Any] = {}
    for sym, price_hits, price_misses, price_neutral, avg_r, last_graded in rows:
        sym = str(sym).upper()
        ph, pm, pn = int(price_hits or 0), int(price_misses or 0), int(price_neutral or 0)
        n = ph + pm + pn
        sig = SymbolSignals(
            symbol=sym,
            outcome_hits=ph,
            outcome_misses=pm,
            outcome_neutral=pn,
            avg_realized_r=float(avg_r) if avg_r is not None else None,
        )
        raw_gate = outcome_gate(sig, scfg)
        dom_tag = max(tag_counts[sym], key=tag_counts[sym].get) if sym in tag_counts else None
        tm = tag_meta.get(dom_tag or "", {})
        tag_slice = {"lift": tm.get("lift"), "tag_flagged": tm.get("flagged")}
        gate = _resolve_symbol_gate(raw_gate, tag_slice)
        meta = {
            "outcome_hits": ph,
            "misses": pm,
            "n": n,
            "avg_r": _round(avg_r, 3),
            "gate": gate,
            "dominant_tag": dom_tag,
            "lift": _round(tm.get("lift"), 3),
            "precision": _round(tm.get("precision"), 3),
            "tag_flagged": bool(tm.get("flagged")),
            "last_graded": str(last_graded) if last_graded else None,
            "edge_boost": promote_boost if gate == "promote_eligible" else None,
            "edge_penalty": demote_pen if gate in ("demote_pressure", "pause_eligible") else None,
        }
        out[sym] = meta
    return out


def fetch_by_tag(cur, cfg: dict[str, Any]) -> dict[str, Any]:
    cur.execute("""SELECT tag, n, hits, hit_rate, lift, flagged, trade_n, avg_realized_r
                   FROM hermes_tag_efficacy ORDER BY n DESC""")
    tg = cfg.get("tag_gates") or {}
    out: dict[str, Any] = {}
    for tag, n, hits, hr, lift, flagged, trade_n, avg_r in cur.fetchall():
        lift_f = float(lift) if lift is not None else None
        n_i = int(n or 0)
        mult = 1.0
        if n_i >= int(tg.get("min_samples_downrank", 15)):
            mult = _tag_quality_multiplier(lift_f, bool(flagged), cfg)
        out[str(tag)] = {
            "lift": _round(lift_f, 3),
            "precision": _round(hr, 3),
            "trade_n": int(trade_n or 0),
            "quality_multiplier": _round(mult, 3),
            "n": n_i,
            "flagged": bool(flagged),
        }
    return out


def _stop_metrics_from_row(row) -> dict[str, Any]:
    n = int(row[0] or 0)
    judged = int(row[3] or 0)
    confirmed = int(row[2] or 0)
    r_left = row[5]
    if r_left is not None:
        r_left_avg = float(r_left) / 100.0
    elif row[6] is not None:
        r_left_avg = float(row[6])
    else:
        r_left_avg = None
    return {
        "sample_n": n,
        "aligned_pct": _round((confirmed / judged) if judged else None, 3),
        "advisory_coverage_pct": _round(row[1], 3),
        "trail_activation_rate": _round(row[4], 3),
        "r_left_on_table_avg": _round(r_left_avg, 3),
        "mae_exceeded_planned_stop_pct": _round(row[7], 3),
        "capture_ratio_avg": _round(row[8], 3),
    }


def fetch_stop_quality(cur, cfg: dict[str, Any]) -> dict[str, Any]:
    sq = cfg.get("stop_quality") or {}
    days = int(sq.get("lookback_days", 90))
    min_n = int(sq.get("min_sample_n", 5))
    try:
        tier_map = _load_governed_tier_map()
    except Exception:
        tier_map = {}

    try:
        cur.execute(f"""SELECT
                         count(*) AS n,
                         avg(CASE WHEN pao.advisory_existed THEN 1.0 ELSE 0.0 END) AS coverage,
                         count(*) FILTER (WHERE pao.advisory_accuracy='confirmed') AS confirmed,
                         count(*) FILTER (WHERE pao.advisory_accuracy IN ('confirmed','contradicted')) AS judged,
                         avg(CASE WHEN pao.trailing_would_have_helped THEN 1.0
                                  WHEN pao.trailing_would_have_helped IS NOT NULL THEN 0.0
                                  ELSE NULL END) AS trail_rate,
                         avg(pao.profit_left_on_table_pct) FILTER (WHERE pao.profit_left_on_table_pct IS NOT NULL) AS r_left_pct,
                         avg(pao.r_multiple) FILTER (WHERE pao.r_multiple IS NOT NULL) AS avg_r,
                         avg(CASE WHEN m.stop_nearly_hit THEN 1.0
                                  WHEN m.stop_nearly_hit IS NOT NULL THEN 0.0
                                  ELSE NULL END) AS mae_exceeded,
                         avg(m.capture_ratio) FILTER (WHERE m.capture_ratio IS NOT NULL) AS capture_ratio
                       FROM protection_advisory_outcomes pao
                       LEFT JOIN trade_mfe_analysis m ON m.trade_id = pao.trade_id
                       LEFT JOIN watchlist_items wi ON UPPER(wi.symbol) = UPPER(pao.symbol)
                       WHERE pao.reconciled_at > NOW() - make_interval(days => %s)
                         AND pao.record_kind='final_closed'""", (days,))
        row = cur.fetchone()
        n = int(row[0] or 0)
        if n < min_n:
            return {
                "sample_n": n,
                "aligned_pct": None,
                "trail_activation_rate": None,
                "r_left_on_table_avg": None,
                "mae_exceeded_planned_stop_pct": None,
                "by_tier": {},
                "correlations": [],
                "notes": "insufficient_sample",
            }

        result = _stop_metrics_from_row(row)
        result["notes"] = "protection_advisory_outcomes + trade_mfe_analysis"

        # Per-tier breakdown (current tier at analysis time — v1 pragmatic)
        cur.execute(f"""SELECT UPPER(pao.symbol) AS sym,
                               avg(CASE WHEN pao.trailing_would_have_helped THEN 1.0
                                        WHEN pao.trailing_would_have_helped IS NOT NULL THEN 0.0
                                        ELSE NULL END) AS trail_rate,
                               count(*) FILTER (WHERE pao.advisory_accuracy='confirmed') AS confirmed,
                               count(*) FILTER (WHERE pao.advisory_accuracy IN ('confirmed','contradicted')) AS judged,
                               avg(pao.profit_left_on_table_pct) FILTER (WHERE pao.profit_left_on_table_pct IS NOT NULL) AS r_left_pct,
                               avg(pao.r_multiple) FILTER (WHERE pao.r_multiple IS NOT NULL) AS avg_r,
                               avg(CASE WHEN m.stop_nearly_hit THEN 1.0
                                        WHEN m.stop_nearly_hit IS NOT NULL THEN 0.0
                                        ELSE NULL END) AS mae_exceeded,
                               avg(m.capture_ratio) FILTER (WHERE m.capture_ratio IS NOT NULL) AS capture_ratio,
                               count(*) AS n
                        FROM protection_advisory_outcomes pao
                        LEFT JOIN trade_mfe_analysis m ON m.trade_id = pao.trade_id
                        WHERE pao.reconciled_at > NOW() - make_interval(days => %s)
                          AND pao.record_kind='final_closed'
                        GROUP BY UPPER(pao.symbol)""", (days,))
        tier_acc: dict[str, list] = {"hot": [], "warm": [], "cold": []}
        for sym, trail, confirmed, judged, r_left, avg_r, mae_ex, cap, sym_n in cur.fetchall():
            heat = _tier_to_heat(tier_map.get(str(sym).upper()))
            tier_acc[heat].append({
                "trail": trail, "confirmed": confirmed, "judged": judged,
                "r_left": r_left, "avg_r": avg_r, "mae": mae_ex, "cap": cap, "n": sym_n,
            })

        by_tier: dict[str, Any] = {}
        for heat, rows in tier_acc.items():
            if not rows:
                by_tier[heat] = {"sample_n": 0, "notes": "no_samples"}
                continue
            total_n = sum(int(r["n"] or 0) for r in rows)
            judged_sum = sum(int(r["judged"] or 0) for r in rows)
            confirmed_sum = sum(int(r["confirmed"] or 0) for r in rows)
            def _wavg(field: str, scale: float = 1.0) -> float | None:
                num = sum(float(r[field]) * int(r["n"] or 0) for r in rows if r.get(field) is not None)
                den = sum(int(r["n"] or 0) for r in rows if r.get(field) is not None)
                return (num / den / scale) if den else None

            by_tier[heat] = {
                "sample_n": total_n,
                "aligned_pct": _round((confirmed_sum / judged_sum) if judged_sum else None, 3),
                "trail_activation_rate": _round(_wavg("trail"), 3),
                "r_left_on_table_avg": _round(_wavg("r_left", 100.0), 3),
                "mae_exceeded_planned_stop_pct": _round(_wavg("mae"), 3),
                "capture_ratio_avg": _round(
                    sum(float(r["cap"]) for r in rows if r["cap"] is not None) /
                    max(1, sum(1 for r in rows if r["cap"] is not None)), 3
                ) if any(r["cap"] is not None for r in rows) else None,
            }

        result["by_tier"] = by_tier
        result["correlations"] = build_stop_correlations(by_tier)
        return result
    except Exception:
        try:
            cur.connection.rollback()
        except Exception:
            pass
        return {
            "sample_n": 0,
            "notes": "table_unavailable",
            "aligned_pct": None,
            "by_tier": {},
            "correlations": [],
        }


def _tier_to_heat(tier: str | None) -> str:
    t = str(tier or "S3").upper()
    if t in ("S0", "S1"):
        return "hot"
    if t == "S2":
        return "warm"
    return "cold"


def _load_governed_tier_map() -> dict[str, str]:
    path = PROJECT_ROOT / "data" / "runtime" / "hermes_governed_universe.json"
    if not path.exists():
        return {}
    feed = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(s.get("symbol", "")).upper(): str(s.get("scope_tier") or "S3")
        for s in (feed.get("symbols") or [])
        if s.get("symbol")
    }


def fetch_positive_outcomes_7d(cur) -> int:
    """Price-graded hits in 7d — denominator for research/LLM efficiency."""
    try:
        cur.execute("""SELECT count(*) FROM hermes_outcome_ledger
                       WHERE verdict='hit'
                         AND subject_type IN ('promotion','external_rec','trade')
                         AND emitted_at > NOW() - interval '7 days'""")
        return int(cur.fetchone()[0] or 0)
    except Exception:
        return 0


def _universe_change_pct_from_trend(days: int = 7) -> float:
    """Fractional change in symbols-in-bus over the trend window (scope churn signal)."""
    try:
        trend = load_outcome_bus_trend(days=days)
        series = trend.get("series") or []
        if len(series) < 2:
            return 0.0
        first = int(series[0].get("symbols_in_bus") or 0)
        last = int(series[-1].get("symbols_in_bus") or 0)
        if first <= 0:
            return 0.0
        return (last - first) / first
    except Exception:
        return 0.0


def _prior_efficiency_score_7d() -> float | None:
    """Score from ~7d ago in bus history for trend_7d label."""
    try:
        trend = load_outcome_bus_trend(days=7)
        series = trend.get("series") or []
        if len(series) < 2:
            return None
        prior = series[0]
        return prior.get("resource_efficiency_score") or prior.get("score")
    except Exception:
        return None


def fetch_resource_efficiency(cur, cfg: dict[str, Any], global_m: dict[str, Any]) -> dict[str, Any]:
    re_cfg = cfg.get("resource_efficiency") or {}
    days = int(cfg.get("resource_efficiency_days", 7))
    live = 0
    try:
        cur.execute("""SELECT count(DISTINCT UPPER(symbol)) FROM watchlist_items
                       WHERE scope_tier IN ('S0','S1','S2') AND status IN ('active','researched')""")
        live = int(cur.fetchone()[0] or 0)
    except Exception:
        pass
    score_writes = int(global_m.get("throughput_score_writes_7d") or 0)
    research_rows = int(global_m.get("throughput_research_rows_7d") or 0)
    baseline_writes = float(re_cfg.get("pre_governor_score_writes_per_day", 157000))
    daily_writes = score_writes / max(days, 1)
    est_comp = None
    try:
        feed = json.loads((PROJECT_ROOT / "data" / "runtime" / "hermes_governed_universe.json").read_text())
        est_comp = feed.get("estimated_score_computations_per_day")
        if feed.get("live_universe") is not None:
            live = int(feed["live_universe"])
    except Exception:
        pass
    err_rate = None
    try:
        cur.execute("""SELECT COALESCE(count(*) FILTER (WHERE status='error')::float / NULLIF(count(*),0), 0)
                       FROM hermes_external_research
                       WHERE created_at > NOW() - make_interval(days => %s)""", (days,))
        err_rate = _round(cur.fetchone()[0], 3)
    except Exception:
        pass

    api_stats = aggregate_request_stats(days=days)
    positive_outcomes = fetch_positive_outcomes_7d(cur)
    universe_change = _universe_change_pct_from_trend(days=7)
    prior_score = _prior_efficiency_score_7d()

    resource = {
        "measurement_window_days": days,
        "live_universe": live,
        "score_history_writes_7d": score_writes,
        "research_rows_7d": research_rows,
        "external_llm_calls_7d": int(global_m.get("throughput_external_calls_7d") or 0),
        "external_error_rate_7d": err_rate,
        "estimated_score_computations_per_day": est_comp,
        "write_reduction_vs_baseline_pct": _round(1.0 - (daily_writes / baseline_writes) if baseline_writes else None, 3),
        "hermes_api_calls_7d": api_stats.get("hermes_api_calls"),
        "hermes_api_estimated_tokens_7d": api_stats.get("hermes_api_estimated_tokens"),
        "hermes_api_endpoints_top": api_stats.get("endpoints_top") or [],
    }
    return compute_resource_efficiency_score(
        global_m,
        resource,
        cfg,
        positive_outcomes_7d=positive_outcomes,
        universe_size_change_pct=universe_change,
        prior_score_7d=prior_score,
    )


def fetch_discovery_health_extras(cur) -> dict[str, Any]:
    """DB-derived discovery_health extras: top/noisy sources, top trends,
    recurring duplicate clusters. Every query is defensive — a missing table or
    dead cursor returns {} and never crashes the bus build. Read-only."""
    extras: dict[str, Any] = {}

    def _q(key: str, sql: str, mapper) -> None:
        try:
            cur.execute(sql)
            rows = cur.fetchall() or []
            val = [mapper(r) for r in rows]
            if val:
                extras[key] = val
        except Exception:
            try:
                cur.connection.rollback()
            except Exception:
                pass

    _q("top_sources",
       """SELECT source_domain, count(*) AS n, round(avg(discovery_score)::numeric, 3)
          FROM hermes_discovery_candidates
          WHERE source_domain IS NOT NULL
            AND created_at > NOW() - interval '30 days'
            AND status NOT IN ('REJECTED','BLOCKED','MERGED_DUPLICATE','ARCHIVED_COLD')
          GROUP BY source_domain
          ORDER BY count(*) DESC, avg(discovery_score) DESC NULLS LAST LIMIT 5""",
       lambda r: {"source_domain": r[0], "candidates_30d": int(r[1] or 0),
                  "avg_score": float(r[2]) if r[2] is not None else None})

    _q("top_trends",
       """SELECT label, seen_count, discovery_score
          FROM hermes_discovery_candidates
          WHERE candidate_type = 'TREND_CANDIDATE'
            AND status NOT IN ('REJECTED','BLOCKED','MERGED_DUPLICATE','ARCHIVED_COLD')
          ORDER BY seen_count DESC, discovery_score DESC NULLS LAST LIMIT 5""",
       lambda r: {"label": r[0], "seen_count": int(r[1] or 0),
                  "score": float(r[2]) if r[2] is not None else None})

    _q("noisy_sources",
       """SELECT source_domain, count(*) AS total,
                 count(*) FILTER (WHERE status IN ('REJECTED','BLOCKED','MERGED_DUPLICATE')
                                    OR duplicate_cluster_id IS NOT NULL) AS noisy
          FROM hermes_discovery_candidates
          WHERE source_domain IS NOT NULL
            AND created_at > NOW() - interval '30 days'
          GROUP BY source_domain
          HAVING count(*) >= 3
             AND (count(*) FILTER (WHERE status IN ('REJECTED','BLOCKED','MERGED_DUPLICATE')
                                     OR duplicate_cluster_id IS NOT NULL))::float
                 / count(*) >= 0.5
          ORDER BY 3 DESC LIMIT 5""",
       lambda r: {"source_domain": r[0], "candidates_30d": int(r[1] or 0),
                  "noisy_count": int(r[2] or 0),
                  "noise_rate": round(int(r[2] or 0) / max(1, int(r[1] or 0)), 3)})

    _q("recurring_duplicate_clusters",
       """SELECT cluster_key, label, member_count
          FROM hermes_discovery_clusters
          WHERE member_count >= 2
          ORDER BY member_count DESC, updated_at DESC LIMIT 5""",
       lambda r: {"cluster_key": r[0], "label": r[1], "member_count": int(r[2] or 0)})

    return extras


def build_discovery_health(cur) -> dict[str, Any]:
    """discovery_health bus section (spec Part G): file-sourced core
    (build_discovery_health_section, stale/missing-safe) + best-effort DB
    extras. Never raises. Advisory-only — the bus takes no discovery actions."""
    section = build_discovery_health_section()
    try:
        for key, val in fetch_discovery_health_extras(cur).items():
            if not section.get(key):
                section[key] = val
    except Exception:
        pass
    return section


def build_feedback_to_governor(by_symbol: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Governor actions: price-graded gates + combined tag/symbol demotion only."""
    gates = cfg.get("outcome_gates") or {}
    min_n = int(gates.get("min_graded_samples", 3))
    demote_pen = int(gates.get("demote_score_penalty", -20))
    promote_boost = int(gates.get("promote_score_boost", 8))
    feedback: list[dict[str, Any]] = []
    priority_map = {"pause": 1, "demote_pressure": 2, "promote_eligible": 3}

    for sym, meta in sorted(by_symbol.items()):
        gate = meta.get("gate")
        n = int(meta.get("n") or 0)
        if n < min_n:
            continue

        if gate == "pause_eligible":
            feedback.append({
                "symbol": sym,
                "action": "pause",
                "reason": f"miss_rate>={gates.get('pause_miss_rate', 0.75):.0%},n={n}",
                "priority": priority_map["pause"],
                "edge_penalty": demote_pen,
                "evidence": meta,
            })
        elif gate == "demote_pressure":
            feedback.append({
                "symbol": sym,
                "action": "demote_pressure",
                "reason": f"miss_rate>={gates.get('demote_miss_rate', 0.60):.0%},n={n}",
                "priority": priority_map["demote_pressure"],
                "edge_penalty": demote_pen,
                "evidence": meta,
            })
        elif gate == "promote_eligible":
            feedback.append({
                "symbol": sym,
                "action": "promote_eligible",
                "reason": f"hit_rate>={gates.get('promote_hit_rate', 0.50):.0%},n={n}",
                "priority": priority_map["promote_eligible"],
                "edge_boost": promote_boost,
                "evidence": meta,
            })
        elif gate == "promote_blocked_bad_tag" and _symbol_poor_outcomes(meta, gates):
            feedback.append({
                "symbol": sym,
                "action": "demote_pressure",
                "reason": f"bad_tag_lift={meta.get('lift')},dominant_tag={meta.get('dominant_tag')}",
                "priority": priority_map["demote_pressure"],
                "edge_penalty": demote_pen,
                "evidence": meta,
            })
        elif _bad_dominant_tag(meta) and _symbol_poor_outcomes(meta, gates):
            if not any(f["symbol"] == sym and f["action"] in ("pause", "demote_pressure") for f in feedback):
                feedback.append({
                    "symbol": sym,
                    "action": "demote_pressure",
                    "reason": (
                        f"tag_lift={meta.get('lift')},dominant_tag={meta.get('dominant_tag')},symbol_n={n}"
                    ),
                    "priority": priority_map["demote_pressure"],
                    "edge_penalty": demote_pen,
                    "evidence": meta,
                })

    feedback.sort(key=lambda x: (x.get("priority", 9), x.get("symbol", "")))
    return feedback


def build_feedback_to_research(by_tag: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    tg = cfg.get("tag_gates") or {}
    min_down = int(tg.get("min_samples_downrank", 15))
    min_boost = int(tg.get("min_samples_boost", 15))
    feedback: list[dict[str, Any]] = []
    for tag, meta in sorted(by_tag.items(), key=lambda x: -(x[1].get("n") or 0)):
        n = int(meta.get("n") or 0)
        lift = meta.get("lift")
        mult = float(meta.get("quality_multiplier") or 1.0)
        if lift is None or n < min_down:
            continue
        if meta.get("flagged") or float(lift) <= float(tg.get("negative_lift_downrank", 0)):
            feedback.append({
                "tag": tag,
                "action": "downrank",
                "quality_multiplier": mult,
                "reason": f"negative_lift={lift},n={n}",
                "trade_n": meta.get("trade_n"),
            })
        elif n >= min_boost and float(lift) >= float(tg.get("positive_lift_boost", 0.02)):
            feedback.append({
                "tag": tag,
                "action": "boost",
                "quality_multiplier": mult,
                "reason": f"positive_lift={lift},n={n}",
                "trade_n": meta.get("trade_n"),
            })
    return feedback


def build_bus(cur, cfg: dict[str, Any], run_id: str) -> dict[str, Any]:
    global_m = fetch_global_metrics(cur, cfg)
    by_symbol = fetch_by_symbol(cur, cfg)
    by_tag = fetch_by_tag(cur, cfg)
    stop_quality = fetch_stop_quality(cur, cfg)
    resource_efficiency = fetch_resource_efficiency(cur, cfg, global_m)
    global_m["hermes_api_calls_7d"] = resource_efficiency.get("hermes_api_calls_7d")
    discovery_health = build_discovery_health(cur)

    alert_window = int((cfg.get("alerts") or {}).get("history_window_days", 14))
    trend = load_outcome_bus_trend(days=alert_window)
    bus_shell = {
        "global": global_m,
        "by_symbol": by_symbol,
        "by_tag": by_tag,
        "stop_quality": stop_quality,
        "resource_efficiency": resource_efficiency,
        "feedback_to_governor": build_feedback_to_governor(by_symbol, cfg),
        "feedback_to_research": build_feedback_to_research(by_tag, cfg),
    }
    alerts = evaluate_alerts(bus_shell, trend, cfg)
    alerts = enrich_alerts(alerts, bus_shell, cfg)
    maturity = build_maturity_status(bus_shell, trend, alerts, cfg)

    bus = {
        "version": OUTCOME_BUS_VERSION,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "philosophy": "outcome_yield_outranks_throughput",
        "source_runs": {
            "lookback_days": int(cfg.get("lookback_days", 90)),
            "upstream": ["hermes_outcome_grader.py", "hermes_tag_engine.py"],
            "downstream": ["hermes_scope_governor.py", "research_scheduler.py", "hermes_outcome_learning.py"],
        },
        "global": global_m,
        "by_symbol": by_symbol,
        "by_tag": by_tag,
        "stop_quality": stop_quality,
        "resource_efficiency": resource_efficiency,
        "discovery_health": discovery_health,
        "alerts": alerts,
        "maturity": maturity,
        "s3_reactivation_policy": cfg.get("s3_reactivation") or {},
        "feedback_to_governor": bus_shell["feedback_to_governor"],
        "feedback_to_research": bus_shell["feedback_to_research"],
    }
    prior = read_outcome_bus()
    return enrich_bus_traceability(bus, trend=trend, prior_bus=prior)


def run(apply: bool = False) -> dict[str, Any]:
    if KILL_SWITCH.exists():
        out = {"ok": False, "reason": "HERMES_DISABLED kill switch present — feedback agent idle"}
        print(json.dumps(out))
        return out

    cfg = _cfg()
    run_id = f"ofb_{uuid.uuid4().hex[:10]}"
    conn = _conn()
    cur = conn.cursor()
    try:
        bus = build_bus(cur, cfg, run_id)
    finally:
        conn.close()

    g = bus.get("global") or {}
    out = {
        "ok": True,
        "apply": apply,
        "run_id": run_id,
        "symbols_in_bus": len(bus.get("by_symbol") or {}),
        "tags_in_bus": len(bus.get("by_tag") or {}),
        "governor_feedback_count": len(bus.get("feedback_to_governor") or []),
        "research_feedback_count": len(bus.get("feedback_to_research") or []),
        "hit_rate_promotions": g.get("hit_rate_promotions"),
        "hit_rate_trades": g.get("hit_rate_trades"),
        "active_alerts": len((bus.get("alerts") or {}).get("active") or []),
        "discovery_health_status": (bus.get("discovery_health") or {}).get("status"),
        "maturity_status": (bus.get("maturity") or {}).get("overall_status"),
        "maturity_tier": (bus.get("maturity") or {}).get("tier"),
        "maturity_composite_score": (bus.get("maturity") or {}).get("composite_score"),
    }

    if apply:
        path = write_outcome_bus(bus, apply=True)
        snap_path = write_maturity_snapshot(bus.get("maturity") or {}, apply=True)
        out["outcome_bus_path"] = str(path) if path else None
        out["maturity_snapshot_path"] = str(snap_path) if snap_path else None
        notify_cfg = cfg.get("notifications") or {}
        if notify_cfg.get("enabled", True) and (bus.get("alerts") or {}).get("active_count", 0) > 0:
            out["notifications"] = dispatch_alert_notifications(bus.get("alerts") or {}, cfg=notify_cfg)
        else:
            out["notifications"] = {"ok": True, "sent": 0, "skipped": "no_active_alerts_or_disabled"}
        _write_heartbeat(out)
    else:
        out["preview"] = {
            "feedback_to_governor": (bus.get("feedback_to_governor") or [])[:8],
            "feedback_to_research": (bus.get("feedback_to_research") or [])[:8],
            "global": g,
        }
        out["note"] = "dry-run: pass --apply to write outcome_bus.json"

    out["ts"] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(out, indent=2, default=str))
    return out


def _write_heartbeat(summary: dict[str, Any]) -> None:
    try:
        hb = PROJECT_ROOT / "data" / "runtime" / "hermes_outcome_feedback_heartbeat.json"
        hb.parent.mkdir(parents=True, exist_ok=True)
        hb.write_text(json.dumps({**summary, "ts": datetime.now(timezone.utc).isoformat()}, indent=2))
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="Hermes Outcome & Feedback Agent — outcome_bus.json v1")
    ap.add_argument("--apply", action="store_true", help="Write state/hermes/outcome_bus.json")
    run(apply=ap.parse_args().apply)


if __name__ == "__main__":
    main()