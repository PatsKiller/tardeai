#!/usr/bin/env python3
"""hermes_discovery_scorecard.py — Discovery Inbox scorecard (Stage 2).

Computes intake/decision/dedupe/promotion health from the hermes_discovery_*
tables, runs the do-no-harm comparison (last 7d vs prior 7d duplicate rate /
false-ticker rate / candidate volume → steady|tighten|pause recommendation),
writes data/runtime/hermes_discovery_scorecard.json, and publishes a compact
discovery_health summary to data/runtime/hermes_discovery_outcome_feed.json.

Metric definitions (operator-approved 2026-07-05):
  * duplicate_rate counts GENUINE duplication only — an explicit
    MERGED_DUPLICATE verdict, or single-sighting membership in a duplicate
    cluster shared with at least one other candidate. Idempotent re-sight
    bumps (seen_count > 1, e.g. a scheduled detector re-observing a seeded
    subject) are RECURRENCE signal, not duplication noise, and never count.
  * resight_rate surfaces those re-sight bumps for visibility only — it is
    never a do-no-harm degradation input.

NOTE on the outcome bus: state/hermes/outcome_bus.json is rewritten WHOLESALE
by lib/hermes_outcome_bus.bus.write_outcome_bus (nightly job) — there is no
additive per-section append API, so appending discovery_health there would be
clobbered on the next nightly run. The discovery feed file above is the
stable hand-off; the bus builder can fold it in when it grows section support.

Usage:
  python3 scripts/hermes_discovery_scorecard.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SCORECARD_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_discovery_scorecard.json"
OUTCOME_FEED_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_discovery_outcome_feed.json"
SCORECARD_VERSION = "discovery-scorecard-v3"
OUTCOME_FEED_VERSION = "discovery-outcome-feed-v1"
FEED_HISTORY_KEEP = 30

APPROVED = ("APPROVED_RESEARCH_ONLY", "APPROVED_SOURCE", "APPROVED_WATCH_DIRECTIVE",
            "STAGED_TICKER_REVIEW", "PROMOTED_TO_WATCH_EVALUATION")

# Do-no-harm thresholds: a metric is degraded only past BOTH an absolute floor
# (so tiny samples don't flap) and a relative worsening vs the prior window.
DNH_MIN_VOLUME = 10          # min last-7d candidates before duplicate-rate judgment
DNH_MIN_TICKERS = 5          # min last-7d ticker candidates before false-rate judgment
DNH_DUP_FLOOR = 0.15         # duplicate rate absolute floor
DNH_FALSE_FLOOR = 0.20       # false-ticker rate absolute floor
DNH_WORSEN_RATIO = 1.5       # last must exceed prior * ratio to count as degraded
DNH_VOLUME_FLOOD = 3.0       # last volume > prior * this (and > 20) = intake flood


def _rate(num: float, den: float) -> float:
    return round(float(num) / float(den), 4) if den else 0.0


def compute_do_no_harm(last_7d: dict, prior_7d: dict) -> dict:
    """Pure do-no-harm comparison (spec Part J). Inputs are the two window
    metric dicts (candidate_volume, duplicate_rate, false_ticker_rate).
    Degraded metrics → recommendation 'tighten' (one) or 'pause' (two or more).

    resight_rate, when present in the windows, is deliberately NOT a
    degradation input: re-sights are recurrence signal (tracked separately
    for visibility), not duplication noise.
    """
    degraded: list[str] = []
    reasons: list[str] = []

    vol, pvol = last_7d.get("candidate_volume", 0), prior_7d.get("candidate_volume", 0)
    dup, pdup = last_7d.get("duplicate_rate", 0.0), prior_7d.get("duplicate_rate", 0.0)
    fts, pfts = last_7d.get("false_ticker_rate", 0.0), prior_7d.get("false_ticker_rate", 0.0)

    if vol >= DNH_MIN_VOLUME and dup > max(DNH_DUP_FLOOR, pdup * DNH_WORSEN_RATIO):
        degraded.append("duplicate_rate")
        reasons.append(f"duplicate rate {dup:.2%} vs prior {pdup:.2%}")
    if last_7d.get("ticker_volume", 0) >= DNH_MIN_TICKERS and \
            fts > max(DNH_FALSE_FLOOR, pfts * DNH_WORSEN_RATIO):
        degraded.append("false_ticker_rate")
        reasons.append(f"false-ticker rate {fts:.2%} vs prior {pfts:.2%}")
    if vol > max(20, pvol * DNH_VOLUME_FLOOD):
        degraded.append("candidate_volume")
        reasons.append(f"intake flood: {vol} candidates vs prior {pvol}")

    recommendation = ("pause" if len(degraded) >= 2
                      else "tighten" if degraded else "steady")
    return {
        "window": "last_7d_vs_prior_7d",
        "last_7d": last_7d,
        "prior_7d": prior_7d,
        "degraded": degraded,
        "reasons": reasons,
        "recommendation": recommendation,
        "note": ("advisory only — 'tighten' = raise ingestor thresholds / lower caps; "
                 "'pause' = stop non-operator intake until reviewed. No automated action."),
    }


def _window_metrics() -> tuple[dict, dict]:
    """Last-7d vs prior-7d intake quality windows, one statement.

    duplicate_rate counts GENUINE duplication only (operator-approved
    2026-07-05): an explicit MERGED_DUPLICATE verdict, or a single-sighting
    row whose duplicate_cluster_id is shared with at least one other
    candidate. Rows with seen_count > 1 are idempotent re-sight bumps (e.g.
    the entity-spike detector re-observing a seeded subject) — that is
    RECURRENCE signal, not duplication noise, so they never count toward
    duplicate_rate; they are tracked separately as resight_rate (visibility
    only — compute_do_no_harm never degrades on it).
    """
    from db_adapter import _execute
    row = dict(_execute(
        """WITH shared_clusters AS (
             SELECT duplicate_cluster_id AS cid
             FROM hermes_discovery_candidates
             WHERE duplicate_cluster_id IS NOT NULL
             GROUP BY duplicate_cluster_id
             HAVING count(*) >= 2
           )
           SELECT
             count(*) FILTER (WHERE created_at > now() - interval '7 days') AS vol_last,
             count(*) FILTER (WHERE created_at <= now() - interval '7 days'
                                AND created_at > now() - interval '14 days') AS vol_prior,
             count(*) FILTER (WHERE created_at > now() - interval '7 days'
                                AND (status = 'MERGED_DUPLICATE'
                                     OR (seen_count = 1
                                         AND duplicate_cluster_id IN
                                             (SELECT cid FROM shared_clusters)))) AS dup_last,
             count(*) FILTER (WHERE created_at <= now() - interval '7 days'
                                AND created_at > now() - interval '14 days'
                                AND (status = 'MERGED_DUPLICATE'
                                     OR (seen_count = 1
                                         AND duplicate_cluster_id IN
                                             (SELECT cid FROM shared_clusters)))) AS dup_prior,
             count(*) FILTER (WHERE created_at > now() - interval '7 days'
                                AND seen_count > 1) AS resight_last,
             count(*) FILTER (WHERE created_at <= now() - interval '7 days'
                                AND created_at > now() - interval '14 days'
                                AND seen_count > 1) AS resight_prior,
             count(*) FILTER (WHERE candidate_type = 'TICKER_CANDIDATE'
                                AND created_at > now() - interval '7 days') AS tick_last,
             count(*) FILTER (WHERE candidate_type = 'TICKER_CANDIDATE'
                                AND created_at <= now() - interval '7 days'
                                AND created_at > now() - interval '14 days') AS tick_prior,
             count(*) FILTER (WHERE candidate_type = 'TICKER_CANDIDATE'
                                AND created_at > now() - interval '7 days'
                                AND (status = 'NEEDS_VALIDATION'
                                     OR risk_flags ? 'ticker_unvalidated')) AS bad_tick_last,
             count(*) FILTER (WHERE candidate_type = 'TICKER_CANDIDATE'
                                AND created_at <= now() - interval '7 days'
                                AND created_at > now() - interval '14 days'
                                AND (status = 'NEEDS_VALIDATION'
                                     OR risk_flags ? 'ticker_unvalidated')) AS bad_tick_prior
           FROM hermes_discovery_candidates""", fetch="one") or {})

    def _window(vol, dup, tick, bad, resight):
        return {
            "candidate_volume": int(row.get(vol) or 0),
            "duplicate_rate": _rate(row.get(dup) or 0, row.get(vol) or 0),
            # visibility only — never a do-no-harm degradation input
            "resight_rate": _rate(row.get(resight) or 0, row.get(vol) or 0),
            "ticker_volume": int(row.get(tick) or 0),
            "false_ticker_rate": _rate(row.get(bad) or 0, row.get(tick) or 0),
        }

    return (_window("vol_last", "dup_last", "tick_last", "bad_tick_last",
                    "resight_last"),
            _window("vol_prior", "dup_prior", "tick_prior", "bad_tick_prior",
                    "resight_prior"))


def _promotion_metrics() -> dict:
    """Promotion pathway metrics from meta stamps + PROMOTE audit rows."""
    from db_adapter import _execute
    by_ref = _execute(
        """SELECT meta_json->>'promoted_ref_type' AS ref_type, count(*) AS n
           FROM hermes_discovery_candidates
           WHERE meta_json ? 'promoted_ref_type'
           GROUP BY 1 ORDER BY n DESC""", fetch="all") or []
    audit = dict(_execute(
        """SELECT count(*) AS total,
                  count(*) FILTER (WHERE created_at > now() - interval '7 days') AS last_7d
           FROM hermes_discovery_audit WHERE action = 'PROMOTE'""", fetch="one") or {})
    return {
        "by_ref_type": {r["ref_type"]: int(r["n"]) for r in by_ref if r.get("ref_type")},
        "promotions_total": int(audit.get("total") or 0),
        "promotions_7d": int(audit.get("last_7d") or 0),
    }


def _by_lane_metrics() -> dict:
    """Per-lane intake / decision breakdown (meta_json->>'lane'), 7-day window.

    Surfaces the discovery lanes that carry a lane tag — analyst_signal,
    industry_novelty, white_space, … — so each new source can be watched (and,
    once the outcome bus grades it, judged) on its OWN merits rather than hidden
    in the aggregate. Lanes historically ran negative alpha, so per-lane
    visibility is a promotion-gate prerequisite, not a nicety."""
    from db_adapter import _execute
    rows = _execute(
        """SELECT meta_json->>'lane' AS lane,
                  count(*) AS n_7d,
                  count(*) FILTER (WHERE status IN %s) AS approved_7d,
                  count(*) FILTER (WHERE status IN ('REJECTED','BLOCKED')) AS rejected_7d
           FROM hermes_discovery_candidates
           WHERE created_at > now() - interval '7 days'
             AND meta_json ? 'lane'
           GROUP BY 1 ORDER BY n_7d DESC""", (APPROVED,), fetch="all") or []
    return {r["lane"]: {"new_7d": int(r["n_7d"] or 0),
                        "approved_7d": int(r["approved_7d"] or 0),
                        "rejected_7d": int(r["rejected_7d"] or 0)}
            for r in rows if r.get("lane")}


def _crontab_drift() -> dict:
    """Guard against the exact rot that produced a false discovery audit: the
    live `crontab -l` diverging from the committed crontab_backup.txt. Compares
    the two schedule-line sets and flags any divergence."""
    import subprocess

    def _sched_lines(text: str) -> set[str]:
        return {ln.strip() for ln in text.splitlines()
                if ln.strip() and not ln.strip().startswith("#")}

    try:
        live = subprocess.run(["crontab", "-l"], capture_output=True,
                              text=True, timeout=10).stdout
    except Exception as e:
        return {"checked": False, "error": str(e)[:200]}
    backup_path = PROJECT_ROOT / "crontab_backup.txt"
    if not backup_path.exists():
        return {"checked": False, "error": "crontab_backup.txt missing"}
    live_set = _sched_lines(live)
    backup_set = _sched_lines(backup_path.read_text(encoding="utf-8", errors="replace"))
    missing = sorted(live_set - backup_set)      # live has it, backup doesn't
    extra = sorted(backup_set - live_set)         # backup has it, live doesn't
    return {
        "checked": True,
        "in_sync": not missing and not extra,
        "live_line_count": len(live_set),
        "backup_line_count": len(backup_set),
        "missing_from_backup": missing[:25],
        "extra_in_backup": extra[:25],
    }


def build_scorecard() -> dict:
    from db_adapter import _execute
    from lib.hermes_discovery.inbox import inbox_stats

    stats = inbox_stats()
    by_status = stats["by_status"]
    total = int(stats["totals"].get("candidates", 0))
    approved = sum(by_status.get(s, 0) for s in APPROVED)
    rejected = by_status.get("REJECTED", 0) + by_status.get("BLOCKED", 0)
    decided = approved + rejected
    clustered = int(stats["totals"].get("clustered", 0))

    row = _execute(
        """SELECT count(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days') AS new_7d,
                  count(*) FILTER (WHERE last_seen_at > NOW() - INTERVAL '7 days') AS seen_7d,
                  coalesce(avg(seen_count), 0) AS avg_seen_count,
                  coalesce(avg(discovery_score) FILTER (WHERE status IN %s), 0) AS avg_score_approved,
                  coalesce(avg(discovery_score) FILTER (WHERE status IN ('REJECTED','BLOCKED')), 0) AS avg_score_rejected,
                  coalesce(avg(EXTRACT(EPOCH FROM (decided_at - created_at)) / 3600.0)
                           FILTER (WHERE decided_at IS NOT NULL), 0) AS avg_hours_to_decision
           FROM hermes_discovery_candidates""",
        (APPROVED,), fetch="one") or {}
    ticker_rows = _execute(
        """SELECT count(*) FILTER (WHERE status = 'READY_FOR_REVIEW') AS ticker_valid,
                  count(*) FILTER (WHERE status = 'NEEDS_VALIDATION') AS ticker_unvalidated
           FROM hermes_discovery_candidates WHERE candidate_type = 'TICKER_CANDIDATE'""",
        fetch="one") or {}
    fb = _execute(
        """SELECT feedback_type, count(*) AS n FROM hermes_discovery_feedback
           GROUP BY feedback_type""", fetch="all") or []

    last_7d, prior_7d = _window_metrics()

    return {
        "version": SCORECARD_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": stats["totals"],
        "by_status": by_status,
        "by_type": stats["by_type"],
        "intake": {
            "new_candidates_7d": int(row.get("new_7d") or 0),
            "seen_7d": int(row.get("seen_7d") or 0),
            "avg_seen_count": round(float(row.get("avg_seen_count") or 0), 3),
        },
        "decisions": {
            "decided": decided,
            "approved": approved,
            "rejected_or_blocked": rejected,
            "approval_rate": round(approved / decided, 4) if decided else 0.0,
            "avg_hours_to_decision": round(float(row.get("avg_hours_to_decision") or 0), 2),
            "avg_score_approved": round(float(row.get("avg_score_approved") or 0), 4),
            "avg_score_rejected": round(float(row.get("avg_score_rejected") or 0), 4),
        },
        "dedupe": {
            "clustered": clustered,
            "dedupe_rate": round(clustered / total, 4) if total else 0.0,
            "merged_duplicates": by_status.get("MERGED_DUPLICATE", 0),
        },
        "ticker_validation": {
            "valid_ready": int(ticker_rows.get("ticker_valid") or 0),
            "needs_validation": int(ticker_rows.get("ticker_unvalidated") or 0),
        },
        "feedback": {r["feedback_type"]: int(r["n"]) for r in fb},
        "audit_rows": stats["audit_rows"],
        "promotions": _promotion_metrics(),
        "by_lane": _by_lane_metrics(),
        "crontab_drift": _crontab_drift(),
        "windows": {"last_7d": last_7d, "prior_7d": prior_7d},
        "do_no_harm": compute_do_no_harm(last_7d, prior_7d),
    }


def build_discovery_health(card: dict) -> dict:
    """Compact discovery_health summary for the outcome feed (bus hand-off)."""
    dnh = card.get("do_no_harm") or {}
    last = (card.get("windows") or {}).get("last_7d") or {}
    return {
        "generated_at": card.get("generated_at"),
        "candidates_total": (card.get("totals") or {}).get("candidates", 0),
        "new_7d": (card.get("intake") or {}).get("new_candidates_7d", 0),
        "duplicate_rate_7d": last.get("duplicate_rate", 0.0),
        # recurrence visibility (re-sight bumps) — never degrades do-no-harm
        "resight_rate_7d": last.get("resight_rate", 0.0),
        "false_ticker_rate_7d": last.get("false_ticker_rate", 0.0),
        "approval_rate": (card.get("decisions") or {}).get("approval_rate", 0.0),
        "promotions_7d": (card.get("promotions") or {}).get("promotions_7d", 0),
        "degraded": dnh.get("degraded", []),
        "recommendation": dnh.get("recommendation", "steady"),
    }


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def write_outcome_feed(card: dict) -> Path:
    """Append this run's discovery_health to the rolling feed file (last 30).
    See module docstring for why this is NOT written into outcome_bus.json."""
    entry = build_discovery_health(card)
    history: list = []
    try:
        prior = json.loads(OUTCOME_FEED_PATH.read_text(encoding="utf-8"))
        history = list(prior.get("history") or [])
    except Exception:
        pass
    history = (history + [entry])[-FEED_HISTORY_KEEP:]
    _atomic_write(OUTCOME_FEED_PATH, {
        "version": OUTCOME_FEED_VERSION,
        "section": "discovery_health",
        "note": ("outcome_bus.json is rewritten wholesale by hermes_outcome_bus."
                 "bus.write_outcome_bus (no additive section API) — this file is "
                 "the stable discovery_health hand-off for the bus builder."),
        "latest": entry,
        "history": history,
    })
    return OUTCOME_FEED_PATH


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="print scorecard JSON to stdout")
    args = ap.parse_args()

    card = build_scorecard()
    _atomic_write(SCORECARD_PATH, card)
    feed = write_outcome_feed(card)
    if args.json:
        print(json.dumps(card, indent=2, default=str))
    else:
        print(f"scorecard written: {SCORECARD_PATH}")
        print(f"outcome feed written: {feed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
