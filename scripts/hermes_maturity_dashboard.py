"""hermes_maturity_dashboard.py — Live Hermes autonomy maturity + gap analysis.

Powers GET /api/v2/hermes/maturity-dashboard (HermesHub Maturity tab).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Coordinator caps (keep in sync with hermes_coordinator.py)
CAP_LIBRARIAN = 10
CAP_AUTONOMOUS = 3
CAP_BACKLOG_DRAIN = 2
CAP_PROMOTE = 10
CAP_EMBED = 15
CAP_EMBED_RESET_FAILED = 20
COORDINATOR_INTERVAL_MIN = 15

MATURITY_COLOR = {
    "full": "#22c55e",
    "mostly": "#84cc16",
    "semi": "#f59e0b",
    "manual": "#ef4444",
}
MATURITY_LABEL = {
    "full": "Fully autonomous",
    "mostly": "Mostly autonomous",
    "semi": "Semi-autonomous",
    "manual": "Manual / policy-gated",
}


def _pct(num: float, den: float) -> float | None:
    if not den:
        return None
    return round(100.0 * float(num) / float(den), 1)


def _kill_switch_active() -> bool:
    try:
        from hermes_killswitch import is_hermes_disabled
        active, _ = is_hermes_disabled()
        return bool(active)
    except Exception:
        return (ROOT / "data" / "runtime" / "HERMES_DISABLED").exists()

def _directive_b_active() -> bool:
    # Directive B (2026-06-02): ungated auto-promote + live RAG embedding enabled.
    # This is the explicit "challenger wall open" mode. Reversible via kill-switch + rollback_sql.
    # We detect it as "active" when kill-switch is off and coordinator is promoting live.
    return not _kill_switch_active()


def _load_consciousness() -> dict:
    try:
        return json.loads((ROOT / "data" / "runtime" / "hermes_consciousness_latest.json").read_text())
    except Exception:
        return {}


def _scalar(cur, sql: str, args=None, default=0):
    try:
        cur.execute(sql, args or ())
        row = cur.fetchone()
        return row[0] if row else default
    except Exception:
        return default


def _gap_embedding_backlog(metrics: dict) -> dict:
    pending = metrics.get("embed_pending", 0)
    failed = metrics.get("embed_failed", 0)
    promoted_missing_embed = metrics.get("promoted_missing_embed", 0)
    daily_embed_capacity = CAP_EMBED * (24 * 60 // COORDINATOR_INTERVAL_MIN)
    daily_promote_capacity = CAP_PROMOTE * (24 * 60 // COORDINATOR_INTERVAL_MIN)

    policy_manual = False
    severity = "warning" if pending > 500 or failed > 50 else "info"
    if pending > 2000 or failed > 200:
        severity = "critical"

    return {
        "id": "embedding_backlog",
        "title": "Embedding backlog (promote outruns embed)",
        "severity": severity,
        "policy_manual": policy_manual,
        "policy_reason": None,
        "automatable": True,
        "metrics": {
            "queue_pending": pending,
            "queue_failed": failed,
            "promoted_missing_embed": promoted_missing_embed,
            "cap_embed_per_tick": CAP_EMBED,
            "cap_promote_per_tick": CAP_PROMOTE,
            "est_embed_per_day": daily_embed_capacity,
            "est_promote_per_day": daily_promote_capacity,
        },
        "why_not_autonomous_yet": (
            "Not blocked by operator policy — throughput mismatch. Auto-promote enqueues up to "
            f"{CAP_PROMOTE}/tick while the embed worker completes ~{CAP_EMBED}/tick; historical bursts "
            f"and {failed} failed rows widened the gap."
        ),
        "blockers": [b for b in [
            f"Coordinator embed cap {CAP_EMBED}/15min vs promote cap {CAP_PROMOTE}/15min",
            f"{failed} failed embedding_queue rows need retry or root-cause fix",
            "Ollama nomic-embed-text latency bounds ticks-per-day throughput",
            f"{promoted_missing_embed} promoted rows still missing from RAG" if promoted_missing_embed else None,
        ] if b],
        "recommended_fixes": [
            f"Raise CAP_EMBED (e.g. 20–30) or add dedicated */5 embed cron between coordinator ticks",
            "Run hermes_embedding_enqueue.py --backfill --limit 500 nightly until pending < 200",
            f"Keep --reset-failed {CAP_EMBED_RESET_FAILED} on worker; investigate failed error_message patterns",
            "Gate auto-promote when embed_pending > threshold (backpressure)",
        ],
    }


def _gap_watchlist_jobs(metrics: dict) -> dict:
    queued = metrics.get("watchlist_jobs_queued", 0)
    stale_queued = metrics.get("watchlist_jobs_stale_2h", 0)
    watchlist_total = metrics.get("watchlist_total", 0)

    return {
        "id": "watchlist_agent_backlog",
        "title": "Watchlist agent job backlog",
        "severity": "critical" if stale_queued > 20 else "warning" if queued > 50 else "info",
        "policy_manual": False,
        "policy_reason": None,
        "automatable": True,
        "metrics": {
            "watchlist_symbols": watchlist_total,
            "jobs_queued": queued,
            "jobs_stale_over_2h": stale_queued,
            "cron_limit_typical": "5–10 jobs/run",
        },
        "why_not_autonomous_yet": (
            f"Not policy-forbidden — scale problem. ~{watchlist_total} watchlist symbols compete for "
            "5–15 LLM agent jobs per cron window; priority tiers help the front page but the tail waits."
        ),
        "blockers": [
            "LLM agent jobs are slow (~minutes each) with 12m flock timeout",
            f"{queued} queued jobs ({stale_queued} older than 2h)",
            "Enrichment sweep caps ~180 symbols/run (Finviz rate limits)",
            "Jobs only created on demand — no auto-queue for full universe",
        ],
        "recommended_fixes": [
            "Off-hours cron with --limit 25 for priority tier only (directive + active + held)",
            "Shard watchlist_agent_jobs by symbol prefix with parallel flock locks",
            "Auto-synthesize stale BUY cards without full 4-agent chain for tail symbols",
            "Raise intraday limit 10→15 when queue depth > 100",
        ],
    }


def _gap_closed_trade_drain(metrics: dict) -> dict:
    needs = metrics.get("closed_trades_need_reflection", 0)

    return {
        "id": "closed_trade_reflection_drain",
        "title": "Closed-trade reflection drain",
        "severity": "warning" if needs > 50 else "info",
        "policy_manual": True,
        "policy_reason": (
            "Operator policy (HERMES_ALL_TRADES_REFLECTION_DRAIN_20260606): drain mode must stay "
            "manual/explicit so 24/7 held-position research is never starved by a closed-trade backlog."
        ),
        "automatable": True,
        "metrics": {
            "closed_trades_needing_reflection": needs,
            "autonomous_cap_per_tick": CAP_AUTONOMOUS,
            "held_priority": "tier 0 (always wins normal ticks)",
        },
        "why_not_autonomous_yet": (
            f"Intentional policy — {needs} closed trades wait for explicit --drain-closed-trades runs. "
            "Normal cron always serves open holdings first with only 3 LLM slots per 15 min."
        ),
        "blockers": [
            "Documented prohibition on wiring drain mode into production coordinator cron",
            f"Only {CAP_AUTONOMOUS} autonomous LLM rows/tick — held + proposals consume slots",
            "Closed-trade reflection is lifetime-dedup per trade_instance (burst would need many ticks)",
        ],
        "recommended_fixes": [
            "Off-hours-only drain cron (e.g. 02:00 ET) with --drain-closed-trades --max-rows 6",
            "Separate low-priority autonomous loop timer (not coordinator) for reflection-only",
            "Operator approval to add weekly scheduled drain with held-priority guard",
        ],
    }


def _build_scalp_kpis(cur) -> dict:
    """Hermes audit 2026-07-02 — scalp-aligned scope/throughput KPIs for Maturity tab."""
    watchlist_active = _scalar(
        cur,
        "SELECT count(DISTINCT UPPER(symbol)) FROM watchlist_items WHERE status IN ('active','researched')",
    )
    watchlist_archived = _scalar(
        cur,
        "SELECT count(DISTINCT UPPER(symbol)) FROM watchlist_items WHERE status='archived'",
    )
    rank_gt_200 = _scalar(
        cur,
        "SELECT count(*) FROM watchlist_items WHERE status IN ('active','researched') AND hermes_rank > 200",
    )
    score_inserts_24h = _scalar(
        cur,
        "SELECT count(*) FROM hermes_score_history WHERE scored_at > NOW() - INTERVAL '24 hours'",
    )
    symbols_scored_24h = _scalar(
        cur,
        "SELECT count(DISTINCT symbol) FROM hermes_score_history WHERE scored_at > NOW() - INTERVAL '24 hours'",
    )
    tagged = _scalar(
        cur,
        """SELECT count(*) FROM hermes_research_intelligence
           WHERE strategy_tags IS NOT NULL AND cardinality(strategy_tags) > 0""",
    )
    research_total = _scalar(cur, "SELECT count(*) FROM hermes_research_intelligence")
    strategy_tags_pct = _pct(tagged, research_total)
    stale_jobs = _scalar(
        cur,
        "SELECT count(*) FROM watchlist_agent_jobs WHERE status='queued' AND created_at < NOW() - INTERVAL '2 hours'",
    )

    import os
    weights_profile = (os.getenv("HERMES_WEIGHTS_PROFILE") or "default").strip().lower()
    scorer_cap = os.getenv("HERMES_SCORER_ALWAYS_CAP", "1").strip() == "1"

    targets = {
        "watchlist_active_max": 800,
        "score_inserts_24h_max": 5000,
        "strategy_tags_pct_min": 95.0,
        "stale_jobs_max": 20,
    }
    return {
        "watchlist_active": watchlist_active,
        "watchlist_archived": watchlist_archived,
        "watchlist_rank_gt_200": rank_gt_200,
        "score_inserts_24h": score_inserts_24h,
        "symbols_scored_24h": symbols_scored_24h,
        "strategy_tags_populated_pct": strategy_tags_pct,
        "strategy_tags_populated": tagged,
        "research_rows_total": research_total,
        "watchlist_jobs_stale_2h": stale_jobs,
        "weights_profile": weights_profile,
        "scorer_always_cap": scorer_cap,
        "targets": targets,
        "health": {
            "watchlist_active_ok": watchlist_active <= targets["watchlist_active_max"],
            "score_volume_ok": score_inserts_24h <= targets["score_inserts_24h_max"],
            "strategy_tags_ok": (strategy_tags_pct or 0) >= targets["strategy_tags_pct_min"],
            "stale_jobs_ok": stale_jobs <= targets["stale_jobs_max"],
        },
    }


def _gap_taxonomy_iris(metrics: dict) -> dict:
    tagger_ran = metrics.get("taxonomy_tagger_last_ran")
    iris_pending = metrics.get("iris_proposals_pending", 0)

    return {
        "id": "taxonomy_iris_cadence",
        "title": "Taxonomy / Iris not every tick",
        "severity": "info",
        "policy_manual": False,
        "policy_reason": None,
        "automatable": True,
        "metrics": {
            "taxonomy_tagger_cadence": "hourly (first 15 min each hour)",
            "iris_weekly_scan": "iris_taxonomy_agent.py cron",
            "iris_proposals_pending": iris_pending,
            "last_tagger_ran": tagger_ran,
        },
        "why_not_autonomous_yet": (
            "Bounded compute choice, not a hard ban. Full taxonomy_tagger + Iris classification "
            "is deferred to hourly/deep curator windows to keep 15-min ticks under CPU/LLM budget."
        ),
        "blockers": [
            "run_taxonomy_tagger only when tick_depth in_hour_window",
            "taxonomy_tagger subprocess timeout 120s — risky every 15 min",
            f"{iris_pending} Iris proposals still pending operator review" if iris_pending else "Iris add/retire proposals need human review by design",
        ],
        "recommended_fixes": [
            "Lightweight classify_fast rules-only pass every tick; heavy tagger stays hourly",
            "Raise tagger limit on deep/force-deep curator passes",
            "Auto-apply Iris reclassify ≥0.85 (iris_proposal_curator already does partial closure)",
        ],
    }


def _area(
    area_id: str,
    label: str,
    level: str,
    autonomy_pct: int,
    *,
    policy_manual: bool = False,
    policy_note: str | None = None,
    metrics: dict | None = None,
    cadence: str | None = None,
) -> dict:
    return {
        "id": area_id,
        "label": label,
        "level": level,
        "level_label": MATURITY_LABEL[level],
        "color": MATURITY_COLOR[level],
        "autonomy_pct": autonomy_pct,
        "policy_manual": policy_manual,
        "policy_note": policy_note,
        "cadence": cadence,
        "metrics": metrics or {},
    }


def build_maturity_report(conn) -> dict:
    cur = conn.cursor()
    now = datetime.now(timezone.utc)

    research_status = {}
    cur.execute(
        "SELECT status, count(*) FROM hermes_research_intelligence GROUP BY 1 ORDER BY 2 DESC"
    )
    for st, n in cur.fetchall():
        research_status[st or "unknown"] = n

    embed_pending = _scalar(cur, "SELECT count(*) FROM hermes_embedding_queue WHERE embedding_status='pending'")
    embed_failed = _scalar(cur, "SELECT count(*) FROM hermes_embedding_queue WHERE embedding_status='failed'")
    embed_completed = _scalar(cur, "SELECT count(*) FROM hermes_embedding_queue WHERE embedding_status='completed'")
    promoted_missing_embed = _scalar(
        cur,
        """SELECT count(*) FROM hermes_research_intelligence h
           WHERE h.status='promoted'
             AND NOT EXISTS (
               SELECT 1 FROM content_embeddings ce
               WHERE ce.source_type='hermes_research' AND ce.source_id=h.id)""",
    )

    watchlist_total = _scalar(
        cur,
        "SELECT count(DISTINCT UPPER(symbol)) FROM watchlist_items WHERE status <> 'removed'",
    )
    watchlist_jobs_queued = _scalar(cur, "SELECT count(*) FROM watchlist_agent_jobs WHERE status='queued'")
    watchlist_jobs_stale_2h = _scalar(
        cur,
        "SELECT count(*) FROM watchlist_agent_jobs WHERE status='queued' AND created_at < now() - interval '2 hours'",
    )

    held_count = _scalar(
        cur,
        """SELECT count(DISTINCT symbol) FROM (
               SELECT symbol FROM trades WHERE lower(status)='open' AND symbol ~ '^[A-Z]{1,5}$'
               UNION SELECT symbol FROM paper_trades WHERE lower(status)='open' AND symbol ~ '^[A-Z]{1,5}$'
           ) h""",
    )

    closed_needs_reflection = _scalar(
        cur,
        """SELECT count(*) FROM trade_instances ti
           WHERE lower(coalesce(status,''))='closed' AND symbol ~ '^[A-Z]{1,5}$'
             AND NOT EXISTS (
               SELECT 1 FROM hermes_research_intelligence h WHERE h.trade_instance_id = ti.id)""",
    )

    iris_pending = _scalar(
        cur,
        "SELECT count(*) FROM iris_taxonomy_proposals WHERE status='pending'",
        default=0,
    )

    stale_flags = _scalar(
        cur,
        "SELECT count(*) FROM hermes_validation_findings WHERE status='active' AND finding_type='stale_data'",
    )
    active_directives = _scalar(cur, "SELECT count(*) FROM watch_directives WHERE status='active'")
    staged_hits = _scalar(cur, "SELECT count(*) FROM hermes_directive_hits_staging WHERE drained=false")
    scalp_incubator = _scalar(
        cur,
        "SELECT count(*) FROM incubator_universe WHERE strategy_id='momentum_scalp' AND status='ACTIVE'",
    )

    consciousness = _load_consciousness()
    pp = consciousness.get("prospect_pipeline") or {}

    metrics = {
        "embed_pending": embed_pending,
        "embed_failed": embed_failed,
        "embed_completed": embed_completed,
        "promoted_missing_embed": promoted_missing_embed,
        "watchlist_total": watchlist_total,
        "watchlist_jobs_queued": watchlist_jobs_queued,
        "watchlist_jobs_stale_2h": watchlist_jobs_stale_2h,
        "held_count": held_count,
        "closed_trades_need_reflection": closed_needs_reflection,
        "iris_proposals_pending": iris_pending,
        "stale_flags": stale_flags,
        "active_directives": active_directives,
        "staged_hits": staged_hits,
        "scalp_incubator_active": scalp_incubator,
        "research_status": research_status,
    }

    embed_catchup_days = None
    if embed_pending and CAP_EMBED > 0:
        per_day = CAP_EMBED * (24 * 60 // COORDINATOR_INTERVAL_MIN)
        embed_catchup_days = round(embed_pending / per_day, 1) if per_day else None
    metrics["embed_catchup_days_at_current_cap"] = embed_catchup_days
    scalp_kpis = _build_scalp_kpis(cur)

    areas = [
        _area("coordinator", "Chief Coordinator", "full", 95,
              cadence=f"*/{COORDINATOR_INTERVAL_MIN} min · --apply",
              metrics={"kill_switch": _kill_switch_active(), "agents_per_tick": 7}),
        _area("research_curator", "24/7 Research Curator", "full", 88,
              cadence="every coordinator tick",
              metrics={"mode": consciousness.get("mode"), "attention_lines": len(consciousness.get("attention") or [])}),
        _area("holdings_research", "Holdings LLM research", "mostly", 72,
              cadence=f"{CAP_AUTONOMOUS} symbols / 15 min · 24h refresh",
              metrics={"held_tracked": held_count, "cap_per_tick": CAP_AUTONOMOUS}),
        _area("critique_hygiene", "Librarian critique + stale purge", "full", 92,
              metrics={"stale_flags_active": stale_flags, "directives_active": active_directives}),
        _area("auto_promote", "Auto-promote + audit", "mostly", 80,
              policy_note="Directive B — ungated promote, capped per tick",
              metrics={"cap_per_tick": CAP_PROMOTE, "research_promoted": research_status.get("promoted", 0)}),
        _area("rag_embed", "RAG embedding worker", "semi", 55 if embed_pending > 1000 else 70,
              metrics={"pending": embed_pending, "failed": embed_failed, "catchup_days": embed_catchup_days}),
        _area("prospect_funnel", "Prospects → directives → watchlist", "mostly", 75,
              metrics={
                  "prospects_mined_last": pp.get("prospects_mined"),
                  "scalp_leads_mined": pp.get("scalp_leads_mined"),
                  "staged_hits": staged_hits,
              }),
        _area("watchlist_agents", "Watchlist multi-agent research", "semi", 60 if watchlist_jobs_queued > 50 else 72,
              metrics={"watchlist_symbols": watchlist_total, "queued_jobs": watchlist_jobs_queued}),
        _area("closed_reflection", "Closed-trade reflection", "manual", 25,
              policy_manual=True,
              policy_note="Drain mode manual-only by operator policy",
              metrics={"backlog": closed_needs_reflection}),
        _area("taxonomy_iris", "Taxonomy tagger + Iris", "semi", 65,
              metrics={"iris_pending": iris_pending, "tagger": "hourly window"}),
        _area("trading_proposals", "Proposals + live trading", "manual", 5,
              policy_manual=True,
              policy_note="Safety Rules §19 — human approval, no broker access for Hermes"),
    ]

    layer_scores = {
        "research_mind": round(sum(a["autonomy_pct"] for a in areas[:7]) / 7),
        "portfolio_attention": round((areas[2]["autonomy_pct"] + areas[6]["autonomy_pct"] + areas[7]["autonomy_pct"]) / 3),
        "trade_execution": areas[10]["autonomy_pct"],
    }
    layer_scores["overall_autonomous"] = round(
        layer_scores["research_mind"] * 0.5
        + layer_scores["portfolio_attention"] * 0.35
        + layer_scores["trade_execution"] * 0.15
    )

    gaps = [
        _gap_embedding_backlog(metrics),
        _gap_watchlist_jobs(metrics),
        _gap_closed_trade_drain(metrics),
        _gap_taxonomy_iris(metrics),
    ]

    policy_manual_count = sum(1 for g in gaps if g["policy_manual"])
    automatable_gaps = [g for g in gaps if g["automatable"] and not g["policy_manual"]]
    policy_gaps = [g for g in gaps if g["policy_manual"]]

    # Phase 5.3 (2026-07-02): the honest board — every gate computed live, 5s persistence-gated.
    # This is the canonical maturity measure; the legacy areas below keep their UI but their
    # autonomy_pct measures throughput/self-running-ness, not correctness.
    try:
        from hermes_maturity_gates import build_gates
        maturity_gates = build_gates(cur)
    except Exception as e:
        maturity_gates = {"error": str(e)[:120]}

    return {
        "ok": True,
        "updated_at": now.isoformat(),
        "maturity_gates": maturity_gates,
        "kill_switch_active": _kill_switch_active(),
        "directive_b_active": _directive_b_active(),
        "directive_b_note": "Operator Directive B (2026-06-02): live auto-promote + RAG writes enabled (audited + reversible). See docs/hermes/HERMES_AGENT_CONTRACTS_AND_PERMISSIONS.md and coordinator header.",
        "coordinator_caps": {
            "librarian": CAP_LIBRARIAN,
            "autonomous": CAP_AUTONOMOUS,
            "promote": CAP_PROMOTE,
            "embed": CAP_EMBED,
            "embed_reset_failed": CAP_EMBED_RESET_FAILED,
            "interval_minutes": COORDINATOR_INTERVAL_MIN,
        },
        "layer_scores": layer_scores,
        "areas": areas,
        "gaps": gaps,
        "gap_summary": {
            "total": len(gaps),
            "policy_manual": policy_manual_count,
            "automatable_now": len(automatable_gaps),
            "needs_operator_policy_change": len(policy_gaps),
        },
        "live_metrics": metrics,
        "scalp_kpis": scalp_kpis,
        "consciousness": {
            "mode": consciousness.get("mode"),
            "attention": consciousness.get("attention"),
            "prospect_pipeline": pp,
        },
        "advisory_notice": "Maturity dashboard — honest autonomy vs policy gates; gaps include recommended fixes",
    }


def main():
    import os
    import psycopg2

    for ln in (ROOT / ".env").read_text().splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, _, v = ln.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )
    report = build_maturity_report(conn)
    conn.close()
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())