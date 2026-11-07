#!/usr/bin/env python3
"""Job coverage / heartbeat monitor.

Data-freshness checks (check_data_product_freshness.py) verify OUTPUTS, but they
can't catch two failure modes that bit us 2026-06-03:
  1. A job that was never scheduled at all (holdings_llm_refresh — built, run once,
     never crontab'd → silently froze).
  2. A job that IS scheduled but crashes/produces nothing (topic_ingestion.py --all —
     invalid arg, errored every run).

This monitor keeps a REGISTRY of jobs that are SUPPOSED to run, and for each checks:
  - SCHEDULED?  — does the crontab (including the wrapper a lane declares — a job's own script name is not always what the crontab line says), an n8n lane run in the ledger (``runs`` or ``run_outcomes``), or its systemd timer say so?
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
LANE_REGISTRY_REL = Path("config") / "lane_registry.json"
#: The ledger tables that record a finished run, and the column each names the run state in.
#: `runs` is the scheduler-of-record row; `run_outcomes` is the outcome journal written beside it.
#: Measured 2026-11-07: 79,820 `runs` rows against 71,852 `run_outcomes` rows, 0 outcomes without a
#: matching run and the same state vocabulary — they agree today, so reading both costs one indexed
#: query each and means a prune or a write lag in either one is not blindness.
LEDGER_RUN_TABLES = (("runs", "state"), ("run_outcomes", "run_state"))

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


def _cron_exprs(markers, cron_lines):
    """The schedule expressions of the active crontab lines that run this job (any of its markers)."""
    from lib.cron_schedule import REBOOT, cron_fields  # the shared 5-field extractor

    markers = [markers] if isinstance(markers, str) else list(markers or [])
    out = []
    for ln in cron_lines:
        if not any(mk in ln for mk in markers):
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


def _lane_registry():
    """lane_id -> lane row from config/lane_registry.json. Never raises; unreadable -> ({}, error)."""
    path = PROJECT_ROOT / LANE_REGISTRY_REL
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, type(exc).__name__
    lanes = doc.get("lanes") if isinstance(doc, dict) else doc
    if not isinstance(lanes, list):
        return {}, "NO_LANES"
    return ({str(e["lane_id"]): e for e in lanes if isinstance(e, dict) and e.get("lane_id")}, None)


def _lane_names_script(lane, match):
    """Does this lane's declared scheduler or command name `match` (a script or wrapper path)?

    `scheduler.match` may be a LIST (one lane, several crontab lines): a str-only test misses the rest.
    `command` is how the lane records the script it actually runs, which is the only place a wrapper
    scheduler shows up (`run_family_slot.py --family topic-ingestion` runs `topic_ingestion.py`).
    """
    sched = lane.get("scheduler") or {}
    m = sched.get("match")
    texts = list(m) if isinstance(m, list) else ([m] if m else [])
    texts += [sched.get("command_text"), lane.get("exec_start")]
    cmd = lane.get("command")
    texts += cmd if isinstance(cmd, list) else [cmd]
    return any(match in str(t) for t in texts if t)


def _lane_map():
    """job name -> [lane ids] that run it, derived from the lane registry and the allowlist.

    Derived, never hand-listed: a lane whose declared command runs this job's script IS this job's
    scheduler. Two catalogues are read because they answer different questions.
    config/lane_registry.json is the scheduler-of-record catalogue (718 lanes) and the only place a
    WRAPPER scheduler is written down. `topic_ingestion` is the case that proves it: the live crontab
    runs it twice a day as `run_family_slot.py --family topic-ingestion` (lane `topic-ingestion`,
    ACTIVE), so a match on this registry's `schedule_match` (`topic_ingestion.py`) finds no line and
    the job read NOT_SCHEDULED although cron was running it — measured 2026-11-07 against the head's
    own results file. config/n8n_run_allowlist.json is still read: an n8n lane can exist there before
    the registry catches up.

    Several lanes for one job is kept rather than dropped as ambiguous: three catalyst bands, two
    news lanes and two protection-pipeline slots are ONE job each, and the newest run across its
    lanes is evidence while a single chosen lane would be a guess. A job with no such lane keeps its
    crontab/log evidence and is never silently upgraded to "scheduled"; an unreadable catalogue
    reports its error and leaves every job to the old evidence.
    """
    registry, reg_err = _lane_registry()
    try:
        allow = json.loads((PROJECT_ROOT / ALLOWLIST_REL).read_text(encoding="utf-8")).get("lanes") or []
        allow_err = None
    except (OSError, ValueError) as exc:
        allow, allow_err = [], type(exc).__name__
    except AttributeError:  # a document that is not an object has no .get
        allow, allow_err = [], "NO_LANES"
    out = {}
    for job in REGISTRY:
        match = job["schedule_match"]
        hits = [lane_id for lane_id, lane in registry.items() if _lane_names_script(lane, match)]
        hits += [str(e.get("lane_id")) for e in allow if isinstance(e, dict)
                 and match in " ".join(str(x) for x in (list(e.get("command") or [])
                                                        + list(e.get("live_arg") or [])))]
        if hits:
            out[job["name"]] = sorted({h for h in hits if h and h != "None"})
    return out, (reg_err or allow_err)


def _lane_is_active(lane_id, registry):
    """True unless the lane registry explicitly says the lane is not ACTIVE.

    Unknown is not retired: a lane the registry has never heard of (an allowlist-only n8n lane, or an
    unreadable registry) keeps the run evidence it has today. A lane the registry marks RETIRED does
    not schedule a job by having run once — `hermes-industry-novelty-discovery` is RETIRED and its
    last ledger row is a single dry run from 2026-10-14, which would otherwise have turned a job
    nothing schedules into a green row as soon as its log was fresher than that row.
    """
    lane = (registry or {}).get(str(lane_id)) if lane_id else None
    if lane is None:
        return True
    return str(lane.get("state") or "ACTIVE").upper() == "ACTIVE"


def _job_schedulers(job, lane_ids, registry=None):
    """(cron markers, systemd units) that can legitimately schedule this job.

    The job's own `schedule_match` and timer always count. A lane contributes only while it is
    ACTIVE: a RETIRED lane still names the script, and letting it schedule the job would turn an
    honest NOT_SCHEDULED into a false OK (`hermes-industry-novelty-discovery` is RETIRED and its last
    ledger run is 2026-10-14). A cron lane contributes its `match` string — never its bare schedule
    expression, which another job's line can share and would schedule this job by coincidence.
    """
    markers = [job["schedule_match"]]
    units = [job["systemd_timer"]] if job.get("systemd_timer") else []
    if registry is None:
        registry = _lane_registry()[0]
    for lane_id in lane_ids:
        lane = registry.get(lane_id) or {}
        if str(lane.get("state") or "ACTIVE").upper() != "ACTIVE":
            continue
        sched = lane.get("scheduler") or {}
        kind = str(sched.get("kind") or "")
        m = sched.get("match")
        if kind == "cron":
            markers += [str(x) for x in (m if isinstance(m, list) else [m]) if x]
        elif kind == "systemd" and sched.get("expression"):
            units.append(str(sched["expression"]))
    return markers, sorted(set(units))


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


def _ts_key(ts):
    """An ISO stamp as a comparable datetime (naive read as UTC), or None."""
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _newer(candidate, held):
    """True when `candidate`'s finished_at is later than `held`'s (an unparsable stamp never wins)."""
    a, b = _ts_key(candidate.get("finished_at")), _ts_key(held.get("finished_at"))
    if b is None:
        return True
    return a is not None and a > b


def _ledger_newest(lane_ids, *, root=None):
    """lane_id -> newest finished run across BOTH ledger tables. Read-only, never raises.

    One query per table for every lane in the run, not one connection per lane: the ledger is 80k
    rows and the monitor is dispatched twice a day, so the cost has to stay a single indexed read.
    """
    out = {}
    lanes = sorted({str(x) for x in lane_ids if x})
    if not lanes:
        return out
    try:
        from lib.lane_registry import N8N_RUN_STATES_PRESENT, n8n_ledger_path
        states, path = tuple(N8N_RUN_STATES_PRESENT), n8n_ledger_path(root)
    except (ImportError, OSError, TypeError):  # a missing module or ledger is "no evidence", not a crash
        return out
    if not Path(path).is_file():
        return out
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            for table, state_col in LEDGER_RUN_TABLES:
                sql = ("SELECT lane_id, run_id, mode, {c} AS state, finished_at, exit_code FROM {t} "
                       "WHERE lane_id IN ({l}) AND finished_at IS NOT NULL AND {c} IN ({s})").format(
                    t=table, c=state_col, l=",".join("?" * len(lanes)), s=",".join("?" * len(states)))
                for lane_id, run_id, mode, state, finished_at, exit_code in conn.execute(
                        sql, (*lanes, *states)):
                    hit = {"run_id": run_id, "lane_id": lane_id, "mode": mode, "state": state,
                           "finished_at": finished_at, "exit_code": exit_code,
                           "table": table, "source": "ledger"}
                    if lane_id not in out or _newer(hit, out[lane_id]):
                        out[lane_id] = hit
        finally:
            conn.close()
    except sqlite3.Error:  # absent table / locked / not a db: fall back to receipts
        return out
    return out


def _receipt_newest(lane_ids, *, root=None):
    """lane_id -> newest finished RunReceipt for lanes the ledger has no row for. Never raises.

    The lane is read from the FILE NAME (`<mode>:<lane_id>:<stamp>.json`), not by parsing every
    receipt: the folder holds ~80,000 files (measured 2026-11-07), so a glob that names the lane is
    the difference between a bounded read and a full scan repeated for every unmapped lane.
    """
    out = {}
    try:
        from lib.lane_registry import N8N_RUN_STATES_PRESENT, n8n_runs_dir
        states, folder = set(N8N_RUN_STATES_PRESENT), Path(n8n_runs_dir(root))
    except (ImportError, OSError, TypeError):
        return out
    if not folder.is_dir():
        return out
    for lane_id in lane_ids:
        if not lane_id or lane_id in out:
            continue
        try:
            candidates = list(folder.glob(f"*:{lane_id}:*.json"))
        except OSError:
            continue
        for p in candidates:
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(doc, dict) or str(doc.get("lane_id") or "") != lane_id:
                continue
            if states and str(doc.get("state") or "") not in states:
                continue
            hit = {"run_id": doc.get("run_id") or p.stem, "lane_id": lane_id,
                   "mode": doc.get("mode"), "state": doc.get("state"),
                   "finished_at": doc.get("finished_at"), "exit_code": doc.get("exit_code"),
                   "table": "receipt", "source": "receipt"}
            if lane_id not in out or _newer(hit, out[lane_id]):
                out[lane_id] = hit
    return out


def _lane_ids(lane_map, job):
    """This job's lane ids, accepting both the old single-id map and today's list."""
    hit = lane_map.get(job["name"]) if isinstance(lane_map, dict) else None
    if not hit:
        return []
    return [hit] if isinstance(hit, str) else [str(x) for x in hit if x]


def _ledger_last_run(lane_map, job, *, newest=None):
    """The newest finished n8n run across this job's lanes (ledger first, else a RunReceipt), or None."""
    lanes = _lane_ids(lane_map, job)
    if not lanes:
        return None
    newest = _ledger_newest(lanes) if newest is None else newest
    hits = [newest[l] for l in lanes if l in newest]
    if not hits:
        hits = list(_receipt_newest(lanes).values())
    if not hits:
        return None
    best = hits[0]
    for hit in hits[1:]:
        if _newer(hit, best):
            best = hit
    return best


def _run_source_label(last):
    """`n8n ledger (RUN_DONE)` — which table the run record came from, and the state it recorded."""
    table = str((last or {}).get("table") or (last or {}).get("source") or "ledger")
    label = {"runs": "n8n ledger", "run_outcomes": "n8n run_outcomes",
             "receipt": "n8n receipt"}.get(table, f"n8n {table}")
    return f"{label} ({(last or {}).get('state') or '?'})"


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


def evaluate(*, now=None, cron_lines=None, log_age=None, db_age=None, last_run=None, lane_map=None,
             schedulers=None):
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
    registry = None if schedulers is not None else _lane_registry()[0]
    if last_run is None:
        # One read for every lane in the run, then a dict lookup per job (see _ledger_newest).
        newest = _ledger_newest([l for v in lane_map.values() for l in
                                 ([v] if isinstance(v, str) else list(v or []))])
        last_run = lambda job: _ledger_last_run(lane_map, job, newest=newest)  # noqa: E731
    results = []
    for job in REGISTRY:
        markers, units = (schedulers(job) if schedulers is not None
                          else _job_schedulers(job, _lane_ids(lane_map, job), registry))
        cron_marker = next((mk for mk in markers if _is_scheduled(mk, cron_lines)), None)
        in_cron = cron_marker is not None
        timer_on = next((u for u in units if _timer_active(u)), None)
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
            run_age, run_source = ledger_age, _run_source_label(last)
        # A run schedules only when its lane is not retired: the scheduler-of-record, not the pulse.
        run_schedules = last is not None and _lane_is_active((last or {}).get("lane_id"), registry)
        scheduled = in_cron or bool(timer_on) or run_schedules
        schedule_source = (f"crontab:{cron_marker}" if in_cron else f"systemd:{timer_on}" if timer_on
                           else "n8n ledger" if run_schedules else None)
        idle = _hours_since_due(job.get("schedule_exprs") or _cron_exprs(markers, cron_lines), now)
        # Never looser than the cadence while the job is in its window; outside it, the heartbeat only has to
        # postdate the last due fire (plus up to 1h of run time).
        allowed = max(job["cadence_h"], idle + min(job["cadence_h"], 1.0))
        if not scheduled:
            where = (f"crontab, {', '.join(units)}, or an n8n ledger run" if units
                     else "crontab or an n8n ledger run")
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
                        "scheduled": scheduled, "schedule_source": schedule_source})
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
