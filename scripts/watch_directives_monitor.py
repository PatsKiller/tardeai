#!/usr/bin/env python3
"""watch_directives_monitor.py — track watch-directive hits + promotions over time.

READ-ONLY. Daily snapshot of directive servicing health: hits (24h/7d) by surfaced_by + promotion_status,
promotions, watchpool entries from directives, Hermes staging backlog, and per-directive servicing staleness.
Appends to data/runtime/watch_directives_history.json (90d) with deltas + status. No mutation.

  python3 scripts/watch_directives_monitor.py [--dry-run]
"""
import os, sys, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "data" / "runtime" / "watch_directives_history.json"
for ln in (ROOT / ".env").read_text().splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'\""))
import psycopg2
import psycopg2.extras


def _db():
    return psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
                            dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                            password=os.getenv("DB_PASSWORD"), cursor_factory=psycopg2.extras.RealDictCursor)


def main():
    dry = "--dry-run" in sys.argv
    c = _db(); cur = c.cursor()
    def one(q, *a):
        cur.execute(q, a); r = cur.fetchone(); return list(r.values())[0] if r else 0
    def kv(q, *a):
        cur.execute(q, a); return {str(r["k"]): r["n"] for r in cur.fetchall()}

    active = one("SELECT count(*) FROM watch_directives WHERE status='active'")
    # Two-way curation KPIs (forward + reverse)
    def _safe_one(q, *a):
        try:
            return one(q, *a)
        except Exception:
            try:
                c.rollback()
            except Exception:
                pass
            return 0

    def _safe_kv(q, *a):
        try:
            return kv(q, *a)
        except Exception:
            try:
                c.rollback()
            except Exception:
                pass
            return {}

    snap = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "ts": datetime.now(timezone.utc).isoformat(),
            "directives_active": active,
            "hits_24h": one("SELECT count(*) FROM watch_directive_hits WHERE surfaced_at>now()-interval '24 hours'"),
            "hits_7d": one("SELECT count(*) FROM watch_directive_hits WHERE surfaced_at>now()-interval '7 days'"),
            "by_surfaced_24h": kv("SELECT surfaced_by k, count(*) n FROM watch_directive_hits WHERE surfaced_at>now()-interval '24 hours' GROUP BY 1"),
            "by_status_24h": kv("SELECT coalesce(promotion_status,'(null)') k, count(*) n FROM watch_directive_hits WHERE surfaced_at>now()-interval '24 hours' GROUP BY 1"),
            "promoted_total": one("SELECT count(*) FROM watch_directive_hits WHERE promoted"),
            "promoted_24h": one("SELECT count(*) FROM watch_directive_hits WHERE promoted AND surfaced_at>now()-interval '24 hours'"),
            "watchpool_from_directives": one("SELECT count(*) FROM strategy_watchpool WHERE directive_id IS NOT NULL"),
            "staging_undrained": one("SELECT count(*) FROM hermes_directive_hits_staging WHERE NOT drained"),
            "stale_directives": one("""SELECT count(*) FROM watch_directives WHERE status='active'
                                       AND (last_serviced_at IS NULL OR last_serviced_at < now()-interval '24 hours')"""),
            "two_way_curation": {
                "staging_undrained": {
                    "cio": _safe_one("SELECT count(*) FROM cio_directive_hits_staging WHERE NOT drained"),
                    "advisory": _safe_one("SELECT count(*) FROM advisory_directive_hits_staging WHERE NOT drained"),
                    "defense": _safe_one("SELECT count(*) FROM defense_directive_hits_staging WHERE NOT drained"),
                    "rotation": _safe_one("SELECT count(*) FROM rotation_directive_hits_staging WHERE NOT drained"),
                    "reentry": _safe_one("SELECT count(*) FROM reentry_directive_hits_staging WHERE NOT drained"),
                    "hermes": one("SELECT count(*) FROM hermes_directive_hits_staging WHERE NOT drained"),
                },
                "staging_total": {
                    "cio": _safe_one("SELECT count(*) FROM cio_directive_hits_staging"),
                    "advisory": _safe_one("SELECT count(*) FROM advisory_directive_hits_staging"),
                    "defense": _safe_one("SELECT count(*) FROM defense_directive_hits_staging"),
                    "rotation": _safe_one("SELECT count(*) FROM rotation_directive_hits_staging"),
                    "reentry": _safe_one("SELECT count(*) FROM reentry_directive_hits_staging"),
                },
                "desk_directives_active": _safe_one(
                    "SELECT count(*) FROM watch_directives WHERE status='active' "
                    "AND created_by IN ('cio','advisory','defense','rotation','reentry')"
                ),
                "desk_hits_24h": _safe_kv(
                    "SELECT surfaced_by k, count(*) n FROM watch_directive_hits "
                    "WHERE surfaced_at>now()-interval '24 hours' "
                    "AND surfaced_by IN ('cio','advisory','defense','rotation','reentry') GROUP BY 1"
                ),
                "audit_events_24h": _safe_one(
                    "SELECT count(*) FROM curation_loop_audit WHERE created_at>now()-interval '24 hours'"
                ),
                "audit_by_source_24h": _safe_kv(
                    "SELECT source k, count(*) n FROM curation_loop_audit "
                    "WHERE created_at>now()-interval '24 hours' GROUP BY 1"
                ),
                "reverse_coverage": {
                    "with_realized_outcome": _safe_one(
                        "SELECT count(*) FROM watchlist_items WHERE status IN ('active','researched') "
                        "AND realized_outcome IS NOT NULL"
                    ),
                    "with_hermes_research": _safe_one(
                        "SELECT count(*) FROM watchlist_items WHERE status IN ('active','researched') "
                        "AND hermes_research_score IS NOT NULL"
                    ),
                    "with_options_edge": _safe_one(
                        "SELECT count(*) FROM watchlist_items WHERE status IN ('active','researched') "
                        "AND options_edge_score IS NOT NULL"
                    ),
                    "active_researched": _safe_one(
                        "SELECT count(*) FROM watchlist_items WHERE status IN ('active','researched')"
                    ),
                },
            }}
    c.close()

    hist = []
    try:
        hist = json.loads(HIST.read_text()).get("snapshots", [])
    except Exception:
        pass
    prev = hist[-1] if hist else None
    if prev:
        snap["delta"] = {"hits_7d": snap["hits_7d"] - prev.get("hits_7d", 0),
                         "promoted_total": snap["promoted_total"] - prev.get("promoted_total", 0),
                         "watchpool_from_directives": snap["watchpool_from_directives"] - prev.get("watchpool_from_directives", 0)}

    notes, status = [], "ACTIVE"
    if active == 0:
        status = "IDLE"; notes.append("no active directives")
    else:
        if snap["stale_directives"] > 0:
            status = "STALLED"; notes.append(f"{snap['stale_directives']} active directive(s) not serviced in 24h")
        if snap["staging_undrained"] >= 25:
            status = "STALLED"; notes.append(f"{snap['staging_undrained']} Hermes proposals undrained — drain backlog")
        if prev and snap.get("delta", {}).get("promoted_total", 0) > 0:
            notes.append(f"{snap['delta']['promoted_total']} new promotion(s) since last snapshot")
    snap["status"], snap["notes"] = status, notes

    if not dry:
        hist.append(snap); hist = hist[-90:]
        HIST.parent.mkdir(parents=True, exist_ok=True)
        HIST.write_text(json.dumps({"updated_at": snap["ts"], "snapshots": hist}, indent=2))
    print(json.dumps({k: snap[k] for k in ("date", "directives_active", "hits_24h", "hits_7d", "by_surfaced_24h",
          "by_status_24h", "promoted_total", "promoted_24h", "watchpool_from_directives", "staging_undrained",
          "two_way_curation", "status", "notes")}, indent=2, default=str))


if __name__ == "__main__":
    main()
