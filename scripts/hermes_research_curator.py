#!/usr/bin/env python3
"""hermes_research_curator.py — 24/7 conscious research and data curation for Hermes.

Hermes is a continuous research mind, not a twice-daily batch job. Every coordinator
tick (~15 min, 24/7) this curator:

  1. Mines live signals — Hermes research, RSS/news, catalyst API, RS/RSI clusters
  2. Discovers new web domains from probe + article URLs → research_sources
  3. Synthesizes emerging themes → watch_directives (rotating depth: rules always, web hourly, LLM q4h)
  4. Discovers prospects → stages directive hits → promotes watchlist items (governed)
  5. Rotates full sector + industry (sub-sector) universe into watch_directives + topic_monitor
  6. Librarian + taxonomy critique/rate scores; flag stale data for removal
  7. Publishes consciousness state — what Hermes is attending to right now

Deep synthesis (full web + LLM + drain) also runs via hermes_think_tank.py on cron;
this script is the always-on layer that keeps research and curation alive between those passes.

Usage:
    python scripts/hermes_research_curator.py [--apply] [--force-deep]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
CONSCIOUSNESS = ROOT / "data" / "runtime" / "hermes_consciousness_latest.json"

# LQ-20261107-1421: Postgres lock_timeout (role default 3s) on watchlist_items used to
# crash the curator with exit 1 and fail the whole hermes-coordinator cron tick. Exit 75
# (EX_TEMPFAIL) is the same class as flock -E 75 — contention, not a logic defect.
EX_TEMPFAIL = 75
_LOCK_RETRIES = 3
_LOCK_SLEEP_S = 2.0


def _is_pg_lock_error(exc: BaseException | str) -> bool:
    """True when the failure is Postgres lock/deadlock contention (retryable)."""
    text = str(exc).lower()
    return (
        "canceling statement due to lock timeout" in text
        or "lock not available" in text
        or "could not obtain lock" in text
        or "deadlock detected" in text
        or "lock_not_available" in text
    )


def _drop_traceback(exc: BaseException) -> BaseException:
    """Copy the error without keeping the failed frame (and its conn) alive."""
    out = type(exc)(str(exc))
    out.__cause__ = None
    out.__context__ = None
    out.__traceback__ = None
    return out


def _rollback_close(conn) -> None:
    """Release an aborted txn's locks before a retry opens a new connection."""
    if conn is None:
        return
    try:  # nosemgrep: tq-py-except-pass -- best-effort unlock before retry; lock path still raises EX_TEMPFAIL
        conn.rollback()
    except Exception:
        pass
    try:  # nosemgrep: tq-py-except-pass -- best-effort close of aborted conn; retry opens a fresh one
        conn.close()
    except Exception:
        pass


def _db_connect():
    import psycopg2

    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def _env():
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for ln in env_path.read_text().splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, _, v = ln.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def tick_depth(now: datetime | None = None, *, force_deep: bool = False) -> dict:
    """Rotate curation depth so 24/7 stays bounded but never dormant."""
    now = now or datetime.now(timezone.utc)
    m, h = now.minute, now.hour
    in_hour_window = m < 15  # first coordinator tick block each hour

    if force_deep:
        return {
            "mode": "deep",
            "skip_web": False,
            "skip_llm": False,
            "skip_sites": False,
            "skip_drain": False,
            "skip_watchlist_drain": False,
            "max_themes": 8,
            "max_site_register": 8,
            "max_prospects_stage": 10,
            "max_scalp_mine": 32,
            "max_scalp_stage": 12,
            "max_intel_discover": 5,
            "directive_discovery_limit": 8,
            "sector_universe_batch": 20,
            "sector_universe_research_queue": 8,
            "refresh_finviz": True,
            "critique_directive_batch": 25,
            "run_taxonomy_tagger": True,
        }

    skip_web = not in_hour_window
    skip_llm = not (in_hour_window and h % 4 == 0)
    skip_watchlist_drain = not in_hour_window  # promote staged prospects → watchlist hourly
    skip_drain = skip_watchlist_drain  # alias for think_tank deep drain (same cadence)
    mode = "baseline"
    if not skip_web:
        mode = "web"
    if not skip_llm:
        mode = "llm"
    if not skip_watchlist_drain:
        mode = "prospects"

    return {
        "mode": mode,
        "skip_web": skip_web,
        "skip_llm": skip_llm,
        "skip_sites": False,
        "skip_drain": skip_drain,
        "skip_watchlist_drain": skip_watchlist_drain,
        "max_themes": 4 if not skip_llm else 2,
        "max_site_register": 4,
        "max_prospects_stage": 6,
        "max_scalp_mine": 24,
        "max_scalp_stage": 8,
        "max_intel_discover": 3,
        "directive_discovery_limit": 4,
        "sector_universe_batch": 12,
        "sector_universe_research_queue": 3,
        "refresh_finviz": in_hour_window and h == 0,
        "critique_directive_batch": 15,
        "run_taxonomy_tagger": in_hour_window,
    }


def _attention_summary(report: dict, depth: dict) -> list[str]:
    """Human-readable 'what Hermes is thinking about' lines."""
    lines = []
    signals = report.get("signals") or {}
    rs = signals.get("rs_rsi") or {}
    if rs.get("weekly_rs_leaders"):
        top = rs["weekly_rs_leaders"][0]
        lines.append(f"RS leader {top.get('symbol')} ({top.get('perf_week_pct'):+.1f}% 1W)")
    for s in (rs.get("sector_rs") or [])[:2]:
        lines.append(f"Sector RS: {s.get('sector')} avg {s.get('avg_perf_week_pct'):+.1f}%")
    for r in (signals.get("hermes_research") or [])[:3]:
        if str(r.get("theme", "")).lower() not in ("earnings", "news momentum", "youtube discovery"):
            lines.append(f"Research cluster: {r.get('theme')} ({r.get('count')} rows)")
    for t in (signals.get("news_feeds", {}).get("themes") or [])[:2]:
        if t.get("feed") == "pattern_match":
            lines.append(f"News theme: {t.get('theme')}")
    sites = report.get("site_registration") or {}
    if sites.get("registered"):
        lines.append(f"New sites registered: {', '.join(sites.get('sample') or [])}")
    if report.get("themes_upserted"):
        lines.append(f"Refreshed {len(report['themes_upserted'])} watch directives")
    pp = report.get("prospect_pipeline") or {}
    if pp.get("prospects_mined"):
        lines.append(f"Prospects mined: {pp['prospects_mined']}")
    staged = (pp.get("signal_staging") or {}).get("staged", 0)
    if staged:
        lines.append(f"Staged {staged} prospect hits for promotion")
    if pp.get("promoted_to_watchlist"):
        lines.append(f"Promoted {pp['promoted_to_watchlist']} to watchlist")
    sl = pp.get("scalp_leads") or {}
    if sl.get("mined"):
        inc = sl.get("incubator") or {}
        lines.append(
            f"Scalp leads beyond Finviz: {sl['mined']} mined "
            f"({sl.get('priority_boosted', 0)} portfolio-boosted), "
            f"{inc.get('staged', 0)} staged to incubator"
        )
    intel = pp.get("intel_discovery") or {}
    if intel.get("added"):
        lines.append(f"Intel discovery added: {', '.join(intel.get('symbols') or [])}")
    su = report.get("sector_universe") or {}
    if su.get("universe_total"):
        lines.append(
            f"Sector universe: batch {su.get('batch_offset', 0)}/{su.get('universe_total')} "
            f"({su.get('coverage', {}).get('sectors', 0)} sectors, "
            f"{su.get('coverage', {}).get('industries', 0)} industries)"
        )
    if su.get("topics_queued"):
        lines.append(f"Queued {su['topics_queued']} sector/industry research topics")
    cr = report.get("critique") or {}
    dr = cr.get("directives") or {}
    if dr.get("rated"):
        lines.append(
            f"Librarian/taxonomy rated {dr['rated']} directives "
            f"(approve {dr.get('approve', 0)} / review {dr.get('review', 0)} / reject {dr.get('reject', 0)})"
        )
    sr = cr.get("stale_removal") or {}
    stale_total = sr.get("total") or 0
    if stale_total:
        flagged = sr.get("flagged") or {}
        lines.append(
            f"Librarian flagged {stale_total} stale item(s) for removal "
            f"(directives {flagged.get('directives', 0)} / research {flagged.get('research', 0)} / staging {flagged.get('staging', 0)})"
        )
    aa = cr.get("auto_archive") or {}
    if aa.get("total"):
        ar = aa.get("archived") or {}
        lines.append(
            f"Auto-archived {aa['total']} row(s) "
            f"(directives {ar.get('directives', 0)} / research {ar.get('research', 0)} / staging {ar.get('staging_drained', 0)})"
        )
    rp = cr.get("retention_purge") or {}
    if rp.get("total"):
        lines.append(f"Retention purge deleted {rp['total']} archived/drained row(s)")
    sa = report.get("site_activation") or {}
    if sa.get("activated"):
        lines.append(f"Activated {sa['activated']} discovered web source(s)")
    if not lines:
        lines.append("Scanning feeds — no dominant cluster this tick")
    return lines[:8]


def _log_consciousness(conn, report: dict, depth: dict, *, apply: bool):
    attention = _attention_summary(report, depth)
    consciousness = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "mode": depth["mode"],
        "apply": apply,
        "attention": attention,
        "themes_by_source": report.get("themes_by_source"),
        "site_candidates_found": report.get("site_candidates_found"),
        "site_registration": report.get("site_registration"),
        "themes_refreshed": len(report.get("themes_upserted") or []),
        "top_themes": [t.get("label") for t in (report.get("themes_upserted") or [])[:6]],
        "rs_universe": (report.get("signals") or {}).get("rs_rsi", {}).get("universe_size"),
        "prospect_pipeline": {
            "prospects_mined": (report.get("prospect_pipeline") or {}).get("prospects_mined"),
            "staged": (report.get("prospect_pipeline") or {}).get("signal_staging", {}).get("staged"),
            "promoted": (report.get("prospect_pipeline") or {}).get("promoted_to_watchlist"),
            "intel_added": (report.get("prospect_pipeline") or {}).get("intel_discovery", {}).get("added"),
            "scalp_leads_mined": (report.get("prospect_pipeline") or {}).get("scalp_leads", {}).get("mined"),
            "scalp_leads_staged": (
                (report.get("prospect_pipeline") or {}).get("scalp_leads", {}).get("incubator") or {}
            ).get("staged"),
        },
        "sector_universe": report.get("sector_universe"),
        "critique": report.get("critique"),
    }
    CONSCIOUSNESS.parent.mkdir(parents=True, exist_ok=True)
    if apply:
        CONSCIOUSNESS.write_text(json.dumps(consciousness, indent=2, default=str))
    if apply and conn is not None:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO hermes_memory_events
               (created_at, source, hermes_agent_name, event_type, topic, content, metadata_json, status)
               VALUES (NOW(), 'hermes', 'research_curator', 'agent_state_change',
                       %s, %s, %s::jsonb, 'active')""",
            (
                f"24/7 curation ({depth['mode']})",
                "; ".join(attention),
                json.dumps({"depth": depth, "consciousness": consciousness}, default=str),
            ),
        )
        conn.commit()
    return consciousness


def _run_scalp_with_lock_retry(conn, signals: dict, *, apply: bool, max_mine: int, max_stage: int):
    """Retry only the scalp→watchlist_items txn; never re-run think-tank or staging.

    On LockNotAvailable the open connection still references the aborted txn (and its
    row locks). Roll back + close, drop the traceback, then open a fresh connection
    for the next attempt (LQ-20261107-1421 REWORK / grok-b).
    """
    from momentum_scalp_lead_miner import run_scalp_lead_pipeline

    last_exc: BaseException | None = None
    for attempt in range(1, _LOCK_RETRIES + 1):
        try:
            return run_scalp_lead_pipeline(
                conn,
                signals,
                apply=apply,
                max_mine=max_mine,
                max_stage=max_stage,
            ), conn
        except Exception as exc:  # noqa: BLE001 — classify lock vs hard fail
            if not _is_pg_lock_error(exc):
                _rollback_close(conn)
                raise
            _rollback_close(conn)
            last_exc = _drop_traceback(exc)
            print(
                f"lock contention attempt {attempt}/{_LOCK_RETRIES}: {last_exc}",
                file=sys.stderr,
            )
            if attempt >= _LOCK_RETRIES:
                raise last_exc from None
            time.sleep(_LOCK_SLEEP_S * attempt)
            conn = _db_connect()
    raise last_exc from None  # pragma: no cover — loop always returns or raises


def run_curator(*, apply: bool, force_deep: bool = False) -> dict:
    _env()
    from hermes_think_tank import run_think_tank
    from think_tank_prospect_discovery import (
        mine_signal_prospects,
        stage_signal_prospects,
        run_intel_discovery,
        _run_script,
    )
    from sector_research_universe import run_sector_universe
    from research_critique_pipeline import run_critique_pipeline

    depth = tick_depth(force_deep=force_deep)

    # Own connection inside think_tank; already-committed themes/sites stay outside retry.
    report = run_think_tank(
        apply=apply,
        max_themes=depth["max_themes"],
        skip_drain=True,  # prospect pipeline owns watchlist drain cadence
        skip_web=depth["skip_web"],
        skip_llm=depth["skip_llm"],
        skip_sites=depth["skip_sites"],
        max_site_register=depth["max_site_register"],
    )
    signals = report.get("signals") or {}

    conn = _db_connect()
    try:
        # Prospect staging commits on success — leave it outside the scalp retry loop.
        prospects = mine_signal_prospects(
            conn, signals, max_prospects=depth.get("max_prospects_stage", 6) * 2
        )
        staged = stage_signal_prospects(
            conn,
            prospects,
            apply=apply,
            max_stage=depth.get("max_prospects_stage", 6),
        )

        scalp, conn = _run_scalp_with_lock_retry(
            conn,
            signals,
            apply=apply,
            max_mine=depth.get("max_scalp_mine", 24),
            max_stage=depth.get("max_scalp_stage", 8),
        )

        pp = {
            "prospects_mined": len(prospects),
            "signal_staging": staged,
            "scalp_leads": scalp,
            "intel_discovery": run_intel_discovery(
                apply=apply, max_add=depth.get("max_intel_discover", 3)
            ),
            "directive_discovery": _run_script(
                "hermes_directive_discovery.py",
                (
                    ["--apply", "--limit-per-directive", str(depth.get("directive_discovery_limit", 4))]
                    if apply
                    else ["--limit-per-directive", str(depth.get("directive_discovery_limit", 4))]
                ),
            ),
            "watchlist_drain": {},
        }
        if apply and not depth.get("skip_watchlist_drain", True):
            pp["watchlist_drain"] = _run_script(
                "watch_directives_service.py",
                ["--apply", "--max-hermes-drain", "5"],
                timeout=600,
            )
            drain = (pp["watchlist_drain"].get("result") or {})
            pp["promoted_to_watchlist"] = drain.get("promoted", 0)
            pp["staged_for_review"] = drain.get("staged", 0)
            pp["hermes_drained"] = drain.get("hermes_drained", 0)
        else:
            pp["promoted_to_watchlist"] = 0
            pp["staged_for_review"] = 0
            pp["hermes_drained"] = 0
        pp["updated_at"] = datetime.now(timezone.utc).isoformat()
        report["prospect_pipeline"] = pp

        report["sector_universe"] = run_sector_universe(
            conn,
            apply=apply,
            batch_size=depth.get("sector_universe_batch", 12),
            research_queue=depth.get("sector_universe_research_queue", 3),
            refresh_finviz=depth.get("refresh_finviz", False),
        )

        report["critique"] = run_critique_pipeline(
            conn,
            apply=apply,
            directive_batch=depth.get("critique_directive_batch", 15),
            run_tagger=depth.get("run_taxonomy_tagger", False),
        )

        consciousness = _log_consciousness(conn, report, depth, apply=apply)
        conn.close()
        conn = None
    except Exception:
        _rollback_close(conn)
        raise

    report["curator"] = {"depth": depth, "consciousness": consciousness}
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hermes 24/7 research curator")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--force-deep", action="store_true", help="Full web+LLM+drain pass (ignore rotation)")
    args = parser.parse_args(argv)
    try:
        report = run_curator(apply=args.apply, force_deep=args.force_deep)
        print(json.dumps(report, indent=2, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001 — boundary: lock → 75, else propagate
        if _is_pg_lock_error(exc):
            print(
                f"EX_TEMPFAIL: DB lock contention after {_LOCK_RETRIES} attempts "
                f"(watchlist_items / peer writer): {exc}",
                file=sys.stderr,
            )
            return EX_TEMPFAIL
        raise


if __name__ == "__main__":
    sys.exit(main())
