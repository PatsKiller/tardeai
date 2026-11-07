#!/usr/bin/env python3
"""Job coverage / heartbeat monitor.

Data-freshness checks (check_data_product_freshness.py) verify OUTPUTS, but they
can't catch two failure modes that bit us 2026-06-03:
  1. A job that was never scheduled at all (holdings_llm_refresh — built, run once,
     never crontab'd → silently froze).
  2. A job that IS scheduled but crashes/produces nothing (topic_ingestion.py --all —
     invalid arg, errored every run).

This monitor keeps a REGISTRY of jobs that are SUPPOSED to run, and for each checks:
  - SCHEDULED?  — does the crontab, an n8n lane run in the ledger, or its systemd timer say so?
  - RUNNING?    — has it RUN within its cadence (the n8n ledger, else its own log) —
                  and is what it WRITES still fresh (a DB row)? Two clocks, never one.
Status: OK / STALE (no fresh run) / STALE_OUTPUT (ran, output old) / NOT_SCHEDULED / NO_SIGNAL.

Usage:
    python3 scripts/job_coverage_monitor.py            # human-readable
    python3 scripts/job_coverage_monitor.py --json     # JSON
    python3 scripts/job_coverage_monitor.py --dry-run  # same evaluation, no receipt written

Exit code (n8n refactor 2026-10-10, wave 1): 0 when the monitor ran — STALE / NOT_SCHEDULED rows are
FINDINGS, reported in the output and the receipt, not a failed run. 2 when the instrument is blind
(``crontab -l`` could not be read, so every job would read NOT_SCHEDULED). It used to exit with the
FAIL count, so a dispatcher could not tell "found 1 stale job" from "crashed". ``--exit-fail-count``
keeps the old contract for a caller that wants it.

The monitor itself is read-only (crontab -l, systemctl is-active, SELECTs, log mtimes, the n8n run ledger). Its
writes are the ScheduledJobReceipt@v1 receipt and the durable record data/runtime/job_coverage_monitor_results.json;
``--dry-run`` writes neither (AGENTS.md §6).
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS = PROJECT_ROOT / "logs"
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# ── Registry: jobs that must run. cadence_h = max hours between heartbeats.
#   signal: ("log", filename) → use log mtime;  ("db", sql) → MAX(timestamp) from DB.
#   schedule_match: substring that must appear (uncommented) in crontab.
REGISTRY = [
    {"name": "holdings_llm_refresh", "schedule_match": "holdings_llm_refresh.py", "cadence_h": 30,
     "signal": ("db", "SELECT MAX(holdings_llm_at) FROM watchlist_items WHERE source='portfolio'")},
    {"name": "catalyst_momentum_engine", "schedule_match": "catalyst_momentum_engine.py", "cadence_h": 30,
     "signal": ("db", "SELECT MAX(created_at) FROM hermes_research_intelligence WHERE research_type='momentum_catalyst'")},
    # llm_priority_guard.sh defers it 06:00-11:59 ET on weekdays, so those ticks write nothing.
    {"name": "hermes_coordinator", "schedule_match": "hermes_coordinator.py", "cadence_h": 1,
     "signal": ("log", "hermes_coordinator.log"),
     "schedule_exprs": ["*/15 0-5,12-23 * * 1-5", "*/15 * * * 0,6"]},
    {"name": "iterate_research_topics", "schedule_match": "iterate_research_topics.py", "cadence_h": 30,
     "signal": ("log", "research_iterate.log")},
    {"name": "topic_ingestion", "schedule_match": "topic_ingestion.py", "cadence_h": 96,
     "signal": ("log", "topic_ingestion.log")},
    # 2026-09-15: the direct line was retired; the off-peak wrapper runs the same worker.
    {"name": "process_watchlist_agent_jobs", "schedule_match": "run_watchlist_agent_jobs_offpeak.sh", "cadence_h": 3,
     "signal": ("db", "SELECT MAX(created_at) FROM watchlist_agent_jobs WHERE status='completed'")},
    {"name": "aegis_overnight", "schedule_match": "aegis_overnight.py", "cadence_h": 30,
     "systemd_timer": "aegis-overnight.timer",
     "signal": ("db", "SELECT MAX(observed_at) FROM aegis_portfolio_briefs")},
    {"name": "portfolio_server_watchdog", "schedule_match": "portfolio_server_watchdog.sh", "cadence_h": 1,
     "signal": ("log", ".portfolio_watchdog_heartbeat")},
    # The :05 docs sync and :35 code mirror were folded into run_drive_syncs.sh (lane drive-syncs-hourly).
    {"name": "drive_sync", "schedule_match": "run_drive_syncs.sh", "cadence_h": 26,
     "signal": ("log", "drive-syncs.log")},
    {"name": "news_ingestion", "schedule_match": "news_ingestion.py", "cadence_h": 12,
     "signal": ("db", "SELECT MAX(created_at) FROM news_articles")},
    {"name": "rag_embeddings", "schedule_match": "rag_indexer.py", "cadence_h": 72,
     "signal": ("db", "SELECT MAX(created_at) FROM content_embeddings")},
    {"name": "transcript_discovery", "schedule_match": "aegis_transcript_discovery.py", "cadence_h": 240,
     "signal": ("db", "SELECT MAX(ingested_at) FROM youtube_transcripts")},
    {"name": "iris_proposal_curator", "schedule_match": "iris_proposal_curator.py", "cadence_h": 30,
     "signal": ("log", "iris_proposal_curator.log")},
    {"name": "hermes_youtube_discovery", "schedule_match": "hermes_youtube_discovery.py", "cadence_h": 30,
     "signal": ("log", "hermes_youtube_discovery.log")},
    {"name": "options_monitor", "schedule_match": "run_options_monitor", "cadence_h": 1,
     "signal": ("log", "options_monitor.log")},
    # options_paper_lifecycle (run_options_paper_position_monitor) and alpaca_paper_options_reconcile
    # (reconcile_alpaca_paper_options) removed 2026-11-06: operator decision "retire alpaca, paper
    # background"; lanes RETIRED (retire_batch retire-alpaca-paper-20261106). Their cron lines go, and a
    # JOBS row whose schedule_match is absent from the crontab would read NOT_SCHEDULED (a failure).
    {"name": "options_iv_snapshot", "schedule_match": "options_iv_snapshot.py", "cadence_h": 30,
     "signal": ("db", "SELECT MAX(captured_at) FROM options_iv_history")},
    {"name": "atm_auto_approver", "schedule_match": "atm_auto_approver.py", "cadence_h": 1,
     "signal": ("log", "atm.log")},
    # The pipeline writes its own log (protection_pipeline.log); the cron redirect only catches gate noise.
    {"name": "protection_pipeline", "schedule_match": "run_protection_pipeline.sh", "cadence_h": 2,
     "signal": ("log", "protection_pipeline.log")},
    {"name": "watchlist_proposal_bridge", "schedule_match": "watchlist_proposal_bridge.py", "cadence_h": 1,
     "signal": ("log", "watchlist_proposal_bridge.log")},
    {"name": "pullback_macd_screener", "schedule_match": "run_pullback_macd_screener.sh", "cadence_h": 30,
     "signal": ("log", "pullback_macd_screener.log")},
    {"name": "auto_proposal_generator", "schedule_match": "auto_proposal_generator.py", "cadence_h": 2,
     "signal": ("log", "auto_proposal.log")},
    {"name": "proposal_enrichment", "schedule_match": "proposal_enrichment_loop.py", "cadence_h": 1,
     "signal": ("log", "proposal_enrichment.log")},
    {"name": "strategy_audits", "schedule_match": "run_scheduled_strategy_audits.sh", "cadence_h": 30,
     "signal": ("log", "strategy_audits.log")},
    {"name": "schwab_journal_ingest", "schedule_match": "schwab_journal_builder.py", "cadence_h": 1,
     "signal": ("log", "schwab_ingest.log")},
    {"name": "journal_review_builder", "schedule_match": "journal_review_builder.py", "cadence_h": 30,
     "signal": ("log", "journal_review.log")},
    {"name": "journal_annotation_reminder", "schedule_match": "journal_annotation_reminder.py", "cadence_h": 30,
     "signal": ("log", "journal_annotation_reminder.log")},
    {"name": "journal_tilt_morning_hook", "schedule_match": "journal_tilt_morning_hook.py", "cadence_h": 30,
     "signal": ("log", "journal_tilt_hook.log")},
    # Hermes analyst-coverage LLM research — weekday-daily; 80h cadence tolerates
    # the weekend gap. Was silently deferred every day pre-2026-07-30 (guard
    # window bug), so this monitor exists specifically to catch a recurrence.
    {"name": "hermes_analyst_coverage", "schedule_match": "hermes_analyst_coverage.py", "cadence_h": 80,
     "signal": ("log", "hermes_analyst_coverage.log")},
    # Analyst-signal discovery feeder — every ~3h.
    {"name": "hermes_analyst_signal_discovery", "schedule_match": "hermes_analyst_signal_discovery.py",
     "cadence_h": 5, "signal": ("log", "hermes_analyst_signal.log")},
    # Industry/sector novelty discovery — daily.
    {"name": "hermes_industry_novelty_discovery", "schedule_match": "hermes_industry_novelty_discovery.py",
     "cadence_h": 30, "signal": ("log", "hermes_industry_novelty.log")},

    # ── Watchlist remediation lanes (2026-08-19 audit) — self-heal managed ──
    # Each carries cron_line (re-add when NOT_SCHEDULED) + remediate_cmd (re-run when
    # STALE). cadence_h=80 tolerates the weekend gap (weekday-daily jobs).
    {"name": "research_watchlist_discovery", "schedule_match": "research_watchlist_discovery.py",
     "cadence_h": 80, "signal": ("db", "SELECT MAX(last_success_at) FROM data_source_health WHERE source_key='research_discovery'"),
     "cron_line": "0 7 * * 1-5 cd $PROJ && $PY scripts/research_watchlist_discovery.py --apply >> logs/research_watchlist_discovery.log 2>&1",
     "remediate_cmd": "cd $PROJ && $PY scripts/research_watchlist_discovery.py --apply"},
    {"name": "sync_social_to_intelligence", "schedule_match": "sync_social_to_intelligence.py",
     "cadence_h": 80, "signal": ("db", "SELECT MAX(last_success_at) FROM data_source_health WHERE source_key='social'"),
     "cron_line": "30 11,15 * * 1-5 cd $PROJ && $PY scripts/sync_social_to_intelligence.py --apply >> logs/sync_social_to_intelligence.log 2>&1",
     "remediate_cmd": "cd $PROJ && $PY scripts/sync_social_to_intelligence.py --apply"},
    {"name": "hermes_social_sentiment", "schedule_match": "hermes_social_sentiment.py",
     "cadence_h": 80, "signal": ("db", "SELECT MAX(last_success_at) FROM data_source_health WHERE source_key='hermes_social'"),
     "cron_line": "15 11,15 * * 1-5 cd $PROJ && $PY scripts/hermes_social_sentiment.py --apply >> logs/hermes_social_sentiment.log 2>&1",
     "remediate_cmd": "cd $PROJ && $PY scripts/hermes_social_sentiment.py --apply"},
    {"name": "candidate_discovery_orchestrator", "schedule_match": "candidate_discovery_orchestrator.py",
     "cadence_h": 80, "signal": ("db", "SELECT MAX(last_success_at) FROM data_source_health WHERE source_key IN ('news_catalyst','incubator','social_scalp','yahoo_movers')"),
     "cron_line": "15 6 * * 1-5 cd $PROJ && $PY scripts/candidate_discovery_orchestrator.py --apply >> logs/candidate_discovery.log 2>&1",
     "remediate_cmd": "cd $PROJ && $PY scripts/candidate_discovery_orchestrator.py --apply"},
    {"name": "drain_discovery_backlog", "schedule_match": "drain_discovery_backlog.py",
     "cadence_h": 80, "signal": ("log", "drain_discovery_backlog.log"),
     "cron_line": "0 6 * * 1-5 cd $PROJ && $PY scripts/drain_discovery_backlog.py --apply >> logs/drain_discovery_backlog.log 2>&1",
     "remediate_cmd": "cd $PROJ && $PY scripts/drain_discovery_backlog.py --apply"},
    {"name": "desk_suggestions_digest", "schedule_match": "desk_suggestions_digest.py",
     "cadence_h": 80, "signal": ("log", "desk_suggestions_digest.log"),
     "cron_line": "0 8 * * 1-5 cd $PROJ && $PY scripts/desk_suggestions_digest.py >> logs/desk_suggestions_digest.log 2>&1",
     "remediate_cmd": "cd $PROJ && $PY scripts/desk_suggestions_digest.py"},
]

# ── Two clocks, never mixed (LQ-20261107-145). An OUTPUT row's age is not a run record, and the crontab is no
#   longer the only schedule: the n8n cutover retired most cron lines. A job is SCHEDULED when the crontab, its
#   systemd timer or an n8n ledger run says so; its RUN clock is the n8n ledger, else its own log;
#   its OUTPUT clock is a DB row, which can only ever say STALE_OUTPUT ("it ran, but what it writes is old").
RESULTS_REL = Path("data") / "runtime" / "job_coverage_monitor_results.json"
RESULTS_SCHEMA = "JobCoverageResults@v1"
ALLOWLIST_REL = Path("config") / "n8n_run_allowlist.json"

# Set by _crontab_lines() when `crontab -l` could not be read: the run is blind, not "nothing scheduled".
CRONTAB_ERROR = None


def _crontab_lines():
    global CRONTAB_ERROR
    try:
        cp = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
    except Exception as exc:  # noqa: BLE001
        CRONTAB_ERROR = type(exc).__name__
        return []
    out = cp.stdout
    if cp.returncode != 0 and not out.strip():
        CRONTAB_ERROR = f"crontab -l exit {cp.returncode}: {(cp.stderr or '').strip()[:120]}"
        return []
    CRONTAB_ERROR = None
    return [ln for ln in out.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def _is_scheduled(match, cron_lines):
    return any(match in ln for ln in cron_lines)


def _timer_active(unit):
    try:
        out = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() == "active"
    except Exception:
        return False


def _cron_exprs(match, cron_lines):
    """The schedule expressions of the active crontab lines that run this job."""
    from lib.cron_schedule import REBOOT, cron_fields  # the shared 5-field extractor

    out = []
    for ln in cron_lines:
        if match not in ln:
            continue
        fields = cron_fields(ln)
        if fields and fields != REBOOT:
            out.append(fields)
    return out


def _hours_since_due(exprs, now=None):
    """Hours since the job was last due to run (0 when unknown).

    2026-10-09: the monitor runs at 08:30 and 20:30, so every market-hours job (10:00-15:00, 09:00-16:00,
    ...) read STALE every morning and evening — 6 of the 9 FAILs that day were jobs idle by schedule.
    Staleness is now measured from the last scheduled fire, not from wall-clock now.
    """
    if not exprs:
        return 0.0
    import datetime as _dt

    from lib.cron_last_fire import last_fire

    now = now or _dt.datetime.now()
    fires = [f for f in (last_fire(e, now) for e in exprs) if f is not None]
    if not fires:
        return 0.0
    return max(0.0, (now - max(fires)).total_seconds() / 3600)


def _log_bases():
    # Logs live in the served tree's logs/ (persistent-state), the dev tree's logs/ (launchers and
    # wrappers that cd there: options monitor, pullback screener, protection pipeline) or ~/logs.
    dev = Path(os.environ.get("TRADEAI_DEV_TREE") or Path.home() / "trade-ai-v12-rebuild" / "trade-ai-v12-rebuild")
    bases = [LOGS]
    try:  # the persistent logs root, so a run from a worktree / release reads the served logs too
        from lib.persistent_state_root import logs_root
        bases.append(logs_root(PROJECT_ROOT))
    except Exception:  # noqa: BLE001
        pass
    bases += [dev / "logs", Path.home() / "logs"]
    out, seen = [], set()
    for b in bases:
        if str(b) not in seen:
            seen.add(str(b))
            out.append(b)
    return tuple(out)


def _log_age_h(fname):
    ages = []
    for base in _log_bases():
        p = base / fname
        if p.exists():
            ages.append(round((time.time() - p.stat().st_mtime) / 3600, 1))
    return min(ages) if ages else None


def _lane_map():
    """job name -> n8n lane id, derived from the allowlist commands (the script name is the key).

    Derived, never hand-listed: a lane whose command names this job's script IS this job's scheduler. A job with no
    such lane keeps its crontab/log evidence and is never silently upgraded to "scheduled"; an unreadable allowlist
    reports the error and leaves every job to the old evidence.
    """
    path = PROJECT_ROOT / ALLOWLIST_REL
    try:
        lanes = json.loads(path.read_text(encoding="utf-8")).get("lanes") or []
    except (OSError, ValueError) as exc:
        return {}, type(exc).__name__
    out = {}
    for job in REGISTRY:
        match = job["schedule_match"]
        hits = sorted(str(e.get("lane_id")) for e in lanes if isinstance(e, dict)
                      and match in " ".join(str(x) for x in (list(e.get("command") or [])
                                                             + list(e.get("live_arg") or []))))
        if len(hits) == 1:  # ambiguous = unmapped: a wrong lane would hide a job that never runs
            out[job["name"]] = hits[0]
    return out, None


def _age_h(ts, now=None):
    """Hours since an ISO stamp (Z or offset), or None when it cannot be parsed."""
    from datetime import datetime, timezone
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ref = now or datetime.now(timezone.utc)
    return round(max(0.0, (ref - dt).total_seconds() / 3600), 1)


def _ledger_last_run(lane_map, job):
    """The newest finished n8n run for this job's lane, or None. Read-only, never raises."""
    lane = lane_map.get(job["name"])
    if not lane:
        return None
    try:
        from lib.lane_registry import n8n_last_run
        hit = n8n_last_run(lane)
    except (ImportError, OSError):  # a missing ledger is "no evidence", not a crash
        return None
    return {**hit, "lane_id": lane} if hit else None


def _db_age_h(sql):
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from db_adapter import get_connection
        conn = get_connection(); cur = conn.cursor()
        cur.execute(sql); row = cur.fetchone(); conn.close()
        if not row or not row[0]:
            return None
        from datetime import datetime
        ts = row[0]
        dt = ts.replace(tzinfo=None) if hasattr(ts, "replace") else datetime.fromisoformat(str(ts))
        return round((datetime.now() - dt).total_seconds() / 3600, 1)
    except Exception:
        return None


FAIL_STATUSES = ("NOT_SCHEDULED", "STALE", "STALE_OUTPUT")


def evaluate(*, now=None, cron_lines=None, log_age=None, db_age=None, last_run=None, lane_map=None):
    """One row per registered job. Every dependency is injectable so a test never reads the host.

    Two clocks, never mixed (LQ-20261107-145): ``run_age_hours`` answers "when did it last RUN" from a run record
    (the n8n ledger, else its own log); ``output_age_hours`` answers "how old is what it writes" from a DB row. A
    fresh run with an old output is STALE_OUTPUT — a finding, but never reported as "did not run". It stays a
    finding even when the run's own record says it staged 0 rows: an absence the run cannot explain is precisely
    what a monitor must not wave through (catalyst: 25 researcher records/day, ``staged: 0`` for nine days).
    """
    cron_lines = _crontab_lines() if cron_lines is None else list(cron_lines)
    log_age = _log_age_h if log_age is None else log_age
    db_age = _db_age_h if db_age is None else db_age
    lane_map = (_lane_map()[0] if lane_map is None else lane_map)
    last_run = ((lambda job: _ledger_last_run(lane_map, job)) if last_run is None else last_run)
    results = []
    for job in REGISTRY:
        timer = job.get("systemd_timer")
        in_cron = _is_scheduled(job["schedule_match"], cron_lines)
        last = last_run(job)
        kind, arg = job["signal"]
        run_age, run_source = None, None
        output_age = None
        if kind == "db":
            output_age = db_age(arg)
        else:
            run_age, run_source = log_age(arg), "log"
        ledger_age = _age_h((last or {}).get("finished_at"), now)
        if ledger_age is not None and (run_age is None or ledger_age < run_age):
            run_age, run_source = ledger_age, f"n8n ledger ({last.get('state') or '?'})"
        scheduled = in_cron or bool(timer and _timer_active(timer)) or last is not None
        idle = _hours_since_due(job.get("schedule_exprs") or _cron_exprs(job["schedule_match"], cron_lines), now)
        # Never looser than the cadence while the job is in its window; outside it, the heartbeat only has to
        # postdate the last due fire (plus up to 1h of run time).
        allowed = max(job["cadence_h"], idle + min(job["cadence_h"], 1.0))
        if not scheduled:
            where = f"crontab, {timer}, or an n8n ledger run" if timer else "crontab or an n8n ledger run"
            beat = run_age if run_age is not None else output_age
            status, detail = "NOT_SCHEDULED", (f"not in {where} (last signal {beat}h ago)" if beat is not None
                                              else f"not in {where}, no heartbeat")
        elif run_age is None and output_age is None:
            status, detail = "NO_SIGNAL", "scheduled but no heartbeat found yet"
        elif run_age is not None and run_age > allowed:
            status, detail = "STALE", (f"{run_age}h since last run ({run_source}; max {allowed:.1f}h; "
                                       f"last due {idle:.1f}h ago)")
        elif run_age is not None:
            if output_age is not None and output_age > allowed:
                status, detail = "STALE_OUTPUT", (f"ran {run_age}h ago ({run_source}) but its output is "
                                                  f"{output_age}h old (max {allowed:.1f}h)")
            else:
                status, detail = "OK", (f"ran {run_age}h ago ({run_source}; max {allowed:.1f}h; "
                                        f"last due {idle:.1f}h ago)")
        elif output_age > allowed:
            # no run record at all; the declared output signal is the only evidence there is
            status, detail = "STALE_OUTPUT", (f"output {output_age}h old and no run record "
                                              f"(max {allowed:.1f}h; last due {idle:.1f}h ago)")
        else:
            status, detail = "OK", (f"output {output_age}h ago (max {allowed:.1f}h; last due {idle:.1f}h ago)")
        results.append({"job": job["name"], "status": status, "detail": detail,
                        "run_age_hours": run_age, "run_source": run_source,
                        "output_age_hours": output_age, "cadence_hours": job["cadence_h"],
                        "allowed_hours": round(allowed, 1), "idle_hours": round(idle, 1),
                        "scheduled": scheduled})
    return results


def _summary(results):
    return {"total": len(results),
            "fail": sum(1 for r in results if r["status"] in FAIL_STATUSES),
            "ok": sum(1 for r in results if r["status"] == "OK"),
            "stale": sum(1 for r in results if r["status"] == "STALE"),
            "stale_output": sum(1 for r in results if r["status"] == "STALE_OUTPUT"),
            "not_scheduled": sum(1 for r in results if r["status"] == "NOT_SCHEDULED"),
            "no_signal": sum(1 for r in results if r["status"] == "NO_SIGNAL")}


def write_results(results, *, generated_at=None, root=None):
    """Atomically replace the durable record. Returns ``{"ok", "path", "error"}`` and never raises.

    The monitor had no durable output at all (LQ-20261107-145: only a 193-byte receipt), so nothing downstream could
    read what it found. This is the monitor's second and last write; the caller keeps it out of the dry-run path.
    ``root`` is the persistent state root (resolved from the durable resolver unless a caller passes one). A write
    that fails answers ``ok: False`` with the exception's name: an explicit unknown a reader can see, never a silent
    empty file and never a crash that would mask the run's own result.
    """
    import datetime as _dt

    target = None
    try:
        try:
            from lib.data_broker.atomic_json import atomic_write_json
        except ImportError:  # scripts/ on sys.path, repo root not
            from scripts.lib.data_broker.atomic_json import atomic_write_json  # type: ignore[no-redef] -- fallback
        if root is None:
            from lib.persistent_state_root import good_persistent_root
            root = good_persistent_root()
        target = Path(root) / RESULTS_REL
        doc = {"schema": RESULTS_SCHEMA, "generated_at": generated_at or _dt.datetime.now(_dt.timezone.utc).isoformat(),
               "monitor": "job_coverage_monitor", "summary": _summary(results), "results": results}
        atomic_write_json(target, doc, indent=1)
        return {"ok": True, "path": str(target), "error": None}
    except Exception as exc:  # noqa: BLE001 -- the record must never mask the run's own result
        print(f"[job_coverage_monitor] durable record write failed: {type(exc).__name__}", file=sys.stderr)
        return {"ok": False, "path": None if target is None else str(target), "error": type(exc).__name__}


def main(*, write=None, **eval_kwargs):
    results = evaluate(**eval_kwargs)
    fails = [r for r in results if r["status"] in FAIL_STATUSES]
    blind = CRONTAB_ERROR
    summary = _summary(results)
    if write is None:
        write = "--dry-run" not in sys.argv
    if write:
        write_results(results)
    if "--json" in sys.argv:
        print(json.dumps({"results": results, "summary": summary}, indent=2, default=str))
    else:
        icon = {"OK": "✅", "STALE": "🔴", "STALE_OUTPUT": "🟠", "NOT_SCHEDULED": "⛔", "NO_SIGNAL": "🟡"}
        print("Job coverage / heartbeat:")
        for r in sorted(results, key=lambda x: x["status"]):
            print(f"  {icon.get(r['status'],'?')} [{r['status']:13}] {r['job']:28} {r['detail']}")
        print(f"\n{len(fails)} FAIL ({summary['ok']}/{len(results)} OK)")
    if blind:
        print(f"BLIND: crontab unreadable ({blind}) — NOT_SCHEDULED rows are not evidence", file=sys.stderr)
        return 2
    if "--exit-fail-count" in sys.argv:
        return min(len(fails), 250)
    return 0


def cli():
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    if "--dry-run" in sys.argv:
        # AGENTS.md §6: neither the receipt wrapper nor the durable record is reachable from a dry run.
        code = main(write=False)
        print("(dry run — receipt not written, durable record not written: "
              f"data/runtime/job_coverage_monitor_last.json, {RESULTS_REL.as_posix()})")
        return code
    from lib.scheduled_job_receipt import run_with_receipt
    return run_with_receipt(main, script="job_coverage_monitor", root=PROJECT_ROOT)


if __name__ == "__main__":
    sys.exit(cli())
