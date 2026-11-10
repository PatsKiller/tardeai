"""
pipeline_watchdog.py — The nervous system. Runs every 5 min weekdays.
1. Detects missed/failed pipeline runs, retries critical scripts
2. Detects GO tickers with no agent analysis, auto-queues
3. Acts on stale IER entities
4. Daily summary at 8:30 AM
"""

import json, logging, os, re, signal, subprocess, sys, time
import os
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

import psycopg2

log = logging.getLogger(__name__)
PROJECT_ROOT = os.environ.get("TRADEAI_DEV_ROOT") or str(Path(__file__).resolve().parents[1])
MAX_RETRIES = 3
# Enrichment attempts per entity per week before backing off to weekly.
MAX_ENRICH_ATTEMPTS = int(os.getenv("WATCHDOG_MAX_ENRICH_ATTEMPTS", "6"))
# TIME SETTINGS — docs/ops/PIPELINE_TIME_SETTINGS.md. Do not lower without
# measured runtime evidence (pipeline_runs, pipeline_key='symbol_enrichment').
#
# symbol_enrichment.py takes p50 136s / p90 209s / p95 241s / max 419s
# (3,178 uncensored successes 2026-09-20..10-07, before the health tick). From
# 2026-10-08 the tick reaped these children after orphan_wait_s=30: 224 failed
# / 1 succeeded in the 36h to 2026-10-22, every failure at 29-33s.
#
# The independent enrichment service owns its children and waits for them.
# The health tick only requests that service; nohup/setsid cannot escape a cgroup. The batch is bounded by
# ENRICHMENT_BATCH_TIMEOUT_S (240s = measured p95) AND by what the health tick
# left this step (HEALTH_TICK_STEP_TIMEOUT_S, exported by health_tick.run_step)
# minus ENRICHMENT_RESERVE_S, so the watchdog terminates, reaps and records its
# children itself instead of being killed by the tick (tick_deadline_s=300,
# unit TimeoutStartSec=330).
ENRICHMENT_BATCH_TIMEOUT_S = max(1, int(os.getenv("WATCHDOG_ENRICHMENT_BATCH_TIMEOUT_S", "240")))
ENRICHMENT_TERM_GRACE_S = 5.0
# SIGTERM grace (5s) + SIGKILL reap wait (2s) + post-batch receipts/log_action (8s).
ENRICHMENT_RESERVE_S = 15.0
_STEP_STARTED_MONO = time.monotonic()


def _enrichment_batch_timeout_s(now=None):
    """Seconds the enrichment batch may still wait, measured from now.

    min(ENRICHMENT_BATCH_TIMEOUT_S, step budget left - ENRICHMENT_RESERVE_S),
    never below 1s. Without HEALTH_TICK_STEP_TIMEOUT_S (cron, manual run) only
    the fixed bound applies.
    """
    budget = float(ENRICHMENT_BATCH_TIMEOUT_S)
    raw = os.getenv("HEALTH_TICK_STEP_TIMEOUT_S")
    if raw:
        try:
            step_timeout = float(raw)
        except ValueError:
            step_timeout = None
        if step_timeout is not None and step_timeout > 0:
            now = time.monotonic() if now is None else now
            left = step_timeout - (now - _STEP_STARTED_MONO) - ENRICHMENT_RESERVE_S
            budget = min(budget, left)
    return max(1.0, budget)


class _EnrichmentInterrupted(Exception):
    def __init__(self, signum):
        self.signum = signum


def _signal_enrichment_groups(children, sig):
    """Signal only the independently supervised enrichment process groups."""
    for entity_id, proc in children:
        if not _process_group_alive(proc.pid):
            continue
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass
        except OSError as exc:
            log.error("[watchdog] could not signal enrichment %s pid=%s: %s", entity_id, proc.pid, type(exc).__name__)


def _process_group_alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _terminate_enrichment_groups(children, grace_s=ENRICHMENT_TERM_GRACE_S):
    """Terminate, escalate, and reap all still-running enrichment trees."""
    alive = [(entity_id, proc) for entity_id, proc in children if _process_group_alive(proc.pid)]
    if not alive:
        return
    _signal_enrichment_groups(alive, signal.SIGTERM)
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline and any(_process_group_alive(proc.pid) for _, proc in alive):
        # Reap direct children promptly; otherwise their zombie leaders keep
        # killpg(pgid, 0) reporting an apparently live group for the full grace.
        for _, proc in alive:
            proc.poll()
        time.sleep(0.05)
    remaining = [(entity_id, proc) for entity_id, proc in alive if _process_group_alive(proc.pid)]
    _signal_enrichment_groups(remaining, signal.SIGKILL)
    for _, proc in alive:
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            log.error("[watchdog] enrichment pid=%s did not reap after SIGKILL", proc.pid)


@contextmanager
def _supervise_enrichment_batch(children, timeout_s=None, outcomes=None):
    """Bound the batch and always clean up its children on exit.

    A SIGTERM/SIGHUP to the watchdog is converted into an exception so this
    function can stop child process groups before the supervisor's kill grace
    expires. Child groups are independent because health_tick supervises the
    watchdog as one step and must not mistake its owned children for orphans.
    """
    old_handlers = {}

    def interrupted(signum, _frame):
        raise _EnrichmentInterrupted(signum)

    try:
        for sig in (signal.SIGTERM, signal.SIGHUP):
            old_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, interrupted)
        yield
        if timeout_s is None:
            # Measured after every child is spawned, against the step's real budget.
            timeout_s = _enrichment_batch_timeout_s()
        deadline = time.monotonic() + timeout_s
        pending = list(children)
        while pending and time.monotonic() < deadline:
            pending = [
                (entity_id, proc)
                for entity_id, proc in pending
                if proc.poll() is None or _process_group_alive(proc.pid)
            ]
            if pending:
                time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        if pending:
            if outcomes is not None:
                outcomes.update({entity_id: "batch_timeout" for entity_id, _ in pending})
            log.error(
                "[watchdog] enrichment batch exceeded %.0fs; terminating %d child process trees",
                timeout_s,
                len(pending),
            )
            _terminate_enrichment_groups(pending)
    except _EnrichmentInterrupted as exc:
        log.warning("[watchdog] received signal %s; terminating enrichment children", exc.signum)
        _terminate_enrichment_groups(children)
        raise
    finally:
        # Also covers spawn/wait failures. Completed children are already reaped
        # by poll()/wait(); only live groups are signalled here.
        _terminate_enrichment_groups(children)
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


def _load_env():
    env_path = Path(PROJECT_ROOT, ".env")
    if not env_path.is_file():
        # CI and tests have no rendered .env; production always does. Nothing to load.
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip()


if "--dry-run" not in sys.argv:
    _load_env()

DB_CONFIG = dict(host="127.0.0.1", port=5432, dbname="trade_ai", user="trade_ai", password=os.getenv("DB_PASSWORD", ""))


def send_telegram(message, urgent=False):
    try:
        scripts_dir = str(Path(__file__).resolve().parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from telegram_alert import send_telegram as _tg

        prefix = "🚨" if urgent else "⚠️"
        text = f"{prefix} WATCHDOG: {message}"
        # Intent: urgent (a script failed N times, manual check needed) is P1; the rest is FYI (P3).
        _tg(text, priority=("P1" if urgent else "P3"), producer="pipeline_watchdog")
        try:
            root = str(Path(__file__).resolve().parents[1])
            if root not in sys.path:
                sys.path.insert(0, root)
            from lib.comms import CommunicationEvent, publish_communication

            publish_communication(
                CommunicationEvent(
                    direction="OUTBOUND",
                    event_type="alert",
                    message_class="ops",
                    producer="pipeline_watchdog",
                    subject_key="ops:pipeline_watchdog",
                    retention_class="operational",
                    severity="critical" if urgent else "warning",
                    sanitized_body=text[:500],
                    short_summary=text[:120],
                )
            )
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


def log_action(conn, action_type, target, reason, success, result=""):
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO watchdog_actions (action_type,target,reason,success,result,created_at) VALUES (%s,%s,%s,%s,%s,NOW())",
            [action_type, target, reason, success, result[:200]],
        )
        conn.commit()
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


def was_alerted_recently(conn, target, hours=1.0):
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM watchdog_actions WHERE action_type='alert' AND target=%s AND created_at > NOW() - INTERVAL '%s hours'",
            [target, hours],
        )
        return (cur.fetchone()[0] or 0) > 0
    except Exception:
        return False


def _runs_today(run_days, now) -> bool:
    """Does a cron-style day-of-week spec include today?

    Accepts '1-5', '0', '0,6', '*' (cron DOW: 0=Sunday). Unparseable or empty
    means 'every day' — the previous behaviour — so a bad value can never make a
    job invisible to the watchdog.
    """
    spec = (run_days or "*").strip()
    if spec in ("*", ""):
        return True
    dow = (now.weekday() + 1) % 7  # Python Mon=0 -> cron Sun=0
    try:
        for part in spec.split(","):
            part = part.strip()
            if "-" in part:
                a, b = (int(x) for x in part.split("-", 1))
                if a <= dow <= b:
                    return True
            elif part.isdigit() and int(part) % 7 == dow:
                return True
    except (ValueError, TypeError):
        return True
    return False


# ── live-lane guard: the n8n dispatcher owns these jobs, not the watchdog ──
#
# LQ-20261107-1722. `pipeline_schedule` still carries rows written before the n8n
# cutover. A row whose lane the dispatcher runs with `dispatch.mode: live` gets a
# SECOND scheduler here: the watchdog starts the script again, outside the
# coordination ledger, without the lane's lock, from the dev checkout. That is how
# incubator-llm-screener ran twice on 2026-11-09 (DONE-LQ-20261107-1714 §5).
#
# The guard fails CLOSED: if no registry copy can be read, nothing is checked or
# retried this cycle. "I could not tell which lanes are live" must never become
# "retry everything".
#
# Arguments matter: `scripts/news_ingestion.py --tail-rotate` is a live lane, while
# the schedule row runs the un-flagged `scripts/news_ingestion.py` (the priority
# ingestion, whose lane is not live). Matching on the script alone would silence a
# job the dispatcher does not own, so every flag in the lane's match must also
# appear in the row's command.
#
# A flag's VALUE is part of its identity (LQ-20261107-1736, review 6a): `--mode weekly` and
# `--mode daily` are two jobs. A lane that names a value must see that value in the row; a lane
# that names only the flag (`--tail-rotate`) accepts whatever value the row passes.
#
# And "dispatch.mode live" is not the same as "the dispatcher will run it" (review 6b): an operator
# hold, a stay_on_cron / KEEP_ON_CRON marker, a stay-behind row or a forbidden token refuses the lane
# whatever the block says (lane_dispatch.dispatch_eligible), so such a row stays checked here — the
# watchdog is then the only scheduler it has.

LANE_REGISTRY_ENV = "TRADEAI_LANE_REGISTRY"
_SCRIPT_NAME_RE = re.compile(r"(?:^|/)([\w.+-]+\.(?:py|sh))$")
_FLAG_RE = re.compile(r"^--")
_REDIRECT_RE = re.compile(r"\d?>>?\s*[^\s;|&]+")


def _command_tokens(text) -> list:
    """Shell words with redirections removed (`>> logs/x.log`, `2>&1`)."""
    stripped = _REDIRECT_RE.sub(" ", str(text or ""))
    return [t for t in stripped.split() if ">&" not in t]


def _flag_pairs(tokens) -> dict:
    """{name: value or None} for `--flag`, `--flag=value` and `--flag value`.

    The value is what separates two jobs that share a script and a flag name (LQ-20261107-1736).
    Only the token after a flag is read as its value, so the script path and a trailing argument of a
    boolean flag (`--run 500`) behave as they did before: the lane that names no value accepts any.
    """
    out = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if _FLAG_RE.match(tok):
            if "=" in tok:
                name, val = tok.split("=", 1)
                out[name] = val
            elif i + 1 < len(tokens) and not _FLAG_RE.match(tokens[i + 1]):
                out[tok] = tokens[i + 1]
                i += 1
            else:
                out[tok] = None
        i += 1
    return out


def _flags_cover(lane_flags: dict, row_flags: dict) -> bool:
    """True when the row runs every flag the lane's match names, with the value the lane names.

    A lane value of None is name-only: the row may pass any argument. A named value must match
    exactly (`--mode weekly` is not `--mode daily`).
    """
    for name, val in lane_flags.items():
        if name not in row_flags:
            return False
        if val is not None and row_flags[name] != val:
            return False
    return True


def _script_basenames(tokens) -> set:
    names = set()
    for tok in tokens:
        m = _SCRIPT_NAME_RE.search(tok.strip(";,'\""))
        if m:
            names.add(m.group(1))
    return names


def _lane_registry_paths():
    """Registry copies to trust: the served release first (what the executor reads), then this tree.

    Three fallbacks, because "no copy" means fail closed: the dev root, then the tree this module was
    loaded from (the hermetic test bootstrap points TRADEAI_DEV_ROOT at an absent path, so the dev-root
    candidate alone would make every test look like an unreadable registry).
    """
    override = os.environ.get(LANE_REGISTRY_ENV)
    if override:
        return [Path(override)]
    paths = []
    try:
        from lib.live_project_root import get_live_project_root

        live_root = Path(get_live_project_root())
    except Exception as exc:  # an unresolvable release pin must not silence the guard
        log.warning("[watchdog] live project root unresolved (%s); using this tree's registry", type(exc).__name__)
        live_root = None
    if live_root is not None:
        paths.append(live_root / "config" / "lane_registry.json")
    paths.append(Path(PROJECT_ROOT) / "config" / "lane_registry.json")
    paths.append(Path(__file__).resolve().parents[1] / "config" / "lane_registry.json")
    return list(dict.fromkeys(paths))


def _live_lane_index(paths=None):
    """basename -> [(lane_id, {flag: value or None}, state)] for the lanes the dispatcher runs live.

    None means no registry copy could be read at all: callers must skip every job.
    A row with no well-formed dispatch block is not live (`dispatch_mode` fails
    closed to "off"), so a malformed row can never hide a live lane behind an
    exception, and can never be silently skipped either.

    "Live" is the dispatcher's own predicate, not the block alone (LQ-20261107-1736, review 6b): a lane
    `dispatch_eligible` refuses (operator hold, stay_on_cron / KEEP_ON_CRON, stay_behind, a forbidden
    token) is not indexed, so its schedule row stays checked. An eligibility call that cannot be made
    keeps the lane live — the dispatcher may still run it, and a second scheduler is the harm this
    guard exists for — and says so at ERROR.
    """
    try:
        from lib.lane_dispatch import dispatch_eligible, dispatch_mode
    except ImportError:  # imported as scripts.pipeline_watchdog
        from scripts.lib.lane_dispatch import dispatch_eligible, dispatch_mode

    index = {}
    readable = 0
    for path in paths if paths is not None else _lane_registry_paths():
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            log.warning("[watchdog] lane registry not read at %s (%s): relying on other copies",
                        path, type(exc).__name__)
            continue
        except ValueError as exc:
            log.error("[watchdog] lane registry unreadable at %s (%s): live lanes unknown",
                      path, type(exc).__name__)
            continue
        rows = doc.get("lanes") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            log.error("[watchdog] lane registry at %s has no lanes list: live lanes unknown", path)
            continue
        readable += 1
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                mode = dispatch_mode(row)
            except Exception as exc:
                # Not silent: the row cannot be classified, so it is NOT live (the dispatcher
                # refuses it too) and the watchdog keeps checking it.
                log.error("[watchdog] lane %s dispatch block unreadable (%s); treating as not live",
                          row.get("lane_id"), type(exc).__name__)
                mode = "off"
            if mode != "live":
                continue
            try:
                eligible, why = dispatch_eligible(row)
            except Exception as exc:
                # The block says live and only our eligibility call failed: assume the dispatcher may
                # still run it (skip the row, the harm this guard exists for) and say so.
                log.error("[watchdog] lane %s eligibility unreadable (%s); keeping it live",
                          row.get("lane_id"), type(exc).__name__)
                eligible, why = True, f"eligibility unreadable: {type(exc).__name__}"
            if not eligible:
                log.info("[watchdog] lane %s is dispatch.mode live but the dispatcher refuses it (%s); "
                         "the row stays checked", row.get("lane_id"), why)
                continue
            sched = row.get("scheduler") or {}
            match = sched.get("match")
            if isinstance(match, (list, tuple)):
                match = " ".join(str(m) for m in match)
            tokens = _command_tokens(f"{match or ''} {row.get('entrypoint') or ''}")
            flags = _flag_pairs(tokens)
            for name in _script_basenames(tokens):
                entry = (str(row.get("lane_id") or ""), flags, str(row.get("state") or "").upper())
                bucket = index.setdefault(name, [])
                if entry not in bucket:
                    bucket.append(entry)
    return index if readable else None


def _job_script_basenames(script_name, command) -> set:
    names = _script_basenames(_command_tokens(command)) | _script_basenames(_command_tokens(script_name))
    bare = str(script_name or "").strip()
    if bare and "." not in bare:
        names.add(bare + ".py")  # script_name without the extension ("agent_outcome_scorer")
    return names


def live_lane_for_job(script_name, command, index):
    """(lane_id, state) when a live-dispatched lane owns this schedule row, else None."""
    if not index:
        return None
    row_flags = _flag_pairs(_command_tokens(command))
    for name in sorted(_job_script_basenames(script_name, command)):
        for lane_id, lane_flags, state in index.get(name) or ():
            if _flags_cover(lane_flags, row_flags):
                return lane_id, state
    return None


def _skip_live_job(script, command, index) -> bool:
    """True when the row must not be checked/retried because its lane runs live."""
    owner = live_lane_for_job(script, command, index)
    if not owner:
        return False
    lane_id, state = owner
    if state == "ACTIVE":
        log.info("[watchdog] skipping %s: lane %s is dispatch.mode live", script, lane_id)
    else:
        log.warning("[watchdog] skipping %s: lane %s is dispatch.mode live but state %s; "
                    "the row is inert until the lane is ACTIVE", script, lane_id, state or "unknown")
    return True


# ── FUNCTION 1: Pipeline Execution Monitor ──


def check_pipeline_execution(conn):
    issues = []
    now = datetime.now()
    cur = conn.cursor()
    live_lanes = _live_lane_index()
    if live_lanes is None:
        log.error("[watchdog] no readable lane registry: skipping every schedule job this cycle (fail closed)")
        return issues
    # run_days exists in the schema but was never read: the check simply skipped
    # Sat/Sun and treated every entry as weekday-daily. Sunday-only jobs
    # (agent_outcome_scorer, strategy_weekly_review) were therefore expected on
    # weekdays they never run — and never checked on the day they DO run
    # (2026-07-20 sweep).
    cur.execute("""SELECT script_name, display_name, expected_hour, expected_min,
        max_latency_min, min_rows, critical, command, run_days
        FROM pipeline_schedule WHERE active=true""")
    for script, display, exp_h, exp_m, latency, min_rows, critical, command, run_days in cur.fetchall():
        if exp_h is None:
            continue
        if _skip_live_job(script, command, live_lanes):
            continue
        if not _runs_today(run_days, now):
            continue
        expected = now.replace(hour=exp_h, minute=exp_m, second=0, microsecond=0)
        deadline = expected + timedelta(minutes=latency)
        if now < deadline:
            continue  # Not yet overdue

        window_start = expected - timedelta(minutes=5)
        cur.execute(
            """SELECT id, status, summary FROM pipeline_runs
            WHERE pipeline_key=%s AND started_at BETWEEN %s AND NOW()
            ORDER BY started_at DESC LIMIT 1""",
            [script, window_start],
        )
        run = cur.fetchone()

        if not run:
            issues.append(
                {"script": script, "display": display, "issue": "not_started", "critical": critical, "command": command}
            )
        elif run[1] == "failed":
            issues.append(
                {"script": script, "display": display, "issue": "failed", "critical": critical, "command": command}
            )
    return issues


def handle_pipeline_issues(conn, issues, no_telegram=False):
    # Second gate for the live-lane guard: `check_pipeline_execution` already drops these, but a caller
    # that builds its own issue list must not be able to re-fire a lane the dispatcher owns.
    live_lanes = _live_lane_index()
    if live_lanes is None and issues:
        log.error("[watchdog] no readable lane registry: no schedule retry this cycle (fail closed)")
        return
    for issue in issues:
        script = issue["script"]
        if not issue.get("critical"):
            continue
        if _skip_live_job(script, issue.get("command"), live_lanes):
            continue

        cur = conn.cursor()
        cur.execute(
            "SELECT (SELECT COUNT(*) FROM pipeline_runs WHERE pipeline_key=%s "
            "AND run_label LIKE 'retry%%' AND started_at>NOW()-INTERVAL '24 hours') + "
            "(SELECT COUNT(*) FROM watchdog_actions WHERE action_type='retry_handoff' "
            "AND target=%s AND created_at>NOW()-INTERVAL '24 hours')",
            [script, script],
        )
        retries_today = cur.fetchone()[0] or 0

        if retries_today < MAX_RETRIES and issue.get("command"):
            log.info(f"[watchdog] Retrying {script} (attempt {retries_today + 1})")
            if "scripts/trade_ai_orchestrator.py" in str(issue["command"]):
                from lib.pipeline_repair_handoff import request_repair
                handoff = request_repair("orchestrator")
                log_action(conn, "retry_handoff", script, issue["issue"], False,
                           json.dumps(handoff))
                if not handoff.get("accepted"):
                    log.error("[watchdog] orchestrator handoff failed: %s", handoff)
                continue
            # Injection triage 21 (2026-11-06): pipeline_schedule.command is a DB row, so only the narrow
            # remediation grammar may reach the shell. A refused line is a failed retry, so it still escalates.
            # The seeded rows `cd` into the dev checkout (pipeline_registry.seed_schedule).
            from lib.live_project_root import DEV_ROOT
            from lib.shell_command_guard import check_command

            _ok, _why = check_command(issue["command"], roots=(PROJECT_ROOT, str(DEV_ROOT)))
            if not _ok:
                # A refused line never starts a retry run, so the retry count would never reach MAX_RETRIES:
                # escalate now (hourly dedupe) instead of refusing silently every cycle.
                log.warning(f"[watchdog] Retry refused for {script}: {_why}")
                refused = f"command_refused_by_guard: {_why}"[:100]
                log_action(conn, "retry_refused", script, issue["issue"], False, refused)
                if not no_telegram and not was_alerted_recently(conn, script):
                    send_telegram(
                        f"CRITICAL: {script} retry command refused by the shell guard ({_why[:120]}). "
                        "Manual check of pipeline_schedule.command needed.",
                        urgent=True,
                    )
                    log_action(conn, "alert", script, "retry_refused", True, "")
                continue
            rid = None
            run_fail = None
            try:
                from pipeline_registry import run_start, run_complete, run_fail

                rid = run_start(script, run_label=f"retry_{retries_today + 1}", triggered_by="watchdog")
                result = subprocess.run(  # nosemgrep: tq-py-subprocess-shell -- command passed shell_command_guard
                    issue["command"], shell=True, timeout=300, capture_output=True, text=True, cwd=PROJECT_ROOT
                )
                if result.returncode == 0:
                    run_complete(rid)
                    log_action(conn, "retry", script, issue["issue"], True, "success")
                else:
                    _record_retry_failure(
                        conn, issue, retries_today, no_telegram, result.stderr, rid=rid, run_fail=run_fail
                    )
            except Exception as e:
                # A retry that RAISES (typically subprocess.TimeoutExpired at 300s) is still just a
                # failed retry. It used to log a bare ERROR every cycle -- flooding the
                # execution_health log_errors check (PR #140, 2026-07-08) -- while leaving the
                # pipeline_runs row stuck 'running' and never escalating at MAX_RETRIES.
                log.warning(f"[watchdog] Retry error for {script}: {str(e)[:200]}")
                _record_retry_failure(conn, issue, retries_today, no_telegram, str(e), rid=rid, run_fail=run_fail)


def _record_retry_failure(conn, issue, retries_today, no_telegram, detail, *, rid=None, run_fail=None):
    """One failed-retry path for a non-zero exit AND a raised retry: close the run as failed,
    record the action, and escalate once at MAX_RETRIES (deduped by was_alerted_recently)."""
    script = issue["script"]
    detail = str(detail or "")
    if rid is not None and run_fail is not None:
        try:
            run_fail(rid, detail[-200:])
        except Exception as e:  # the registry being down must not hide the escalation below
            log.warning(f"[watchdog] could not mark retry run failed for {script}: {e}")
    log_action(conn, "retry", script, issue["issue"], False, detail[-100:])
    if retries_today + 1 >= MAX_RETRIES and not no_telegram:
        if not was_alerted_recently(conn, script):
            send_telegram(f"CRITICAL: {script} failed {MAX_RETRIES}x. Manual check needed.", urgent=True)
            log_action(conn, "alert", script, "max_retries", True, "")


# ── FUNCTION 2: GO Signal Coverage ──


def check_go_coverage(conn):
    now = datetime.now()
    if now.hour < 10 or now.hour >= 18 or now.weekday() >= 5:
        return 0

    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT ON (t.symbol) t.symbol, t.score, t.decision, t.scanned_at, t.intelligence_readiness
        FROM trade_ai_scans t
        WHERE t.decision IN ('GO','WAIT') AND t.scanned_at > NOW()-INTERVAL '48 hours'
        AND NOT EXISTS (SELECT 1 FROM watchlist_agent_jobs j WHERE j.symbol=t.symbol
            AND j.created_at > t.scanned_at - INTERVAL '30 minutes'
            AND j.status IN ('pending','running','completed'))
        ORDER BY t.symbol, t.score DESC LIMIT 20
    """)
    missing = cur.fetchall()
    fixed = 0

    for symbol, score, decision, scanned_at, readiness in missing:
        age_h = (datetime.now(timezone.utc) - scanned_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600
        try:
            cur.execute(
                """INSERT INTO watchlist_agent_jobs
                (symbol, requested_agent, task_type, priority, status, submitted_from, context_data, created_at)
                VALUES (%s,'maria_research','scalp_discovery','high','pending','pipeline_watchdog',%s::jsonb,NOW())
                ON CONFLICT DO NOTHING""",
                [symbol, json.dumps({"score": score, "trigger": "watchdog_coverage", "age_h": round(age_h, 1)})],
            )
            conn.commit()
            fixed += 1
            log_action(conn, "queue_agent", symbol, f"GO {score}pts {age_h:.1f}hr no analysis", True, "")

            if age_h > 4 and not was_alerted_recently(conn, f"go_{symbol}", hours=4):
                send_telegram(f"{symbol} {decision} {score}pts for {age_h:.1f}hr with 0 analyses. Queued.")
                log_action(conn, "alert", f"go_{symbol}", f"{age_h:.1f}hr gap", True, "")
        except Exception:
            pass

    return fixed


# ── FUNCTION 3: IER Action Engine ──


def run_ier_engine(conn, report=None):
    report = report if report is not None else {}
    report.update(completed=0, failed=0, deferred=0)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT e.entity_id, e.entity_type, e.intelligence_score, e.iris_freshness,
               e.screener_decision
        FROM intelligence_entities e
        WHERE e.active=true
        AND (e.iris_freshness IN ('CRITICAL','STALE') OR e.intelligence_score < 25)
        AND (e.last_enriched IS NULL OR e.last_enriched < NOW()-INTERVAL '4 hours')
        -- BOUNDED RETRY (2026-07-20). Selection is score-based, but enrichment
        -- does not necessarily RAISE the score: an entity stuck at 7.0 stays
        -- below 25 forever and was re-triggered every 4h indefinitely (61 times
        -- in 14 days for the worst case, 2752 entities permanently eligible).
        -- Keep the rolling weekly attempt cap even when a failed child releases
        -- its freshness claim. NULL/old freshness must not bypass that cap.
        AND (SELECT count(*) FROM watchdog_actions w
              WHERE w.action_type='trigger_enrichment' AND w.target=e.entity_id
                AND w.created_at > NOW()-INTERVAL '7 days') < %s
        ORDER BY e.intelligence_score NULLS FIRST LIMIT 15
    """,
        [MAX_ENRICH_ATTEMPTS],
    )
    actions = 0
    enrichments = []
    children = []
    enrichment_outcomes = {}
    claim_times = {}
    interrupted = None
    try:
        with _supervise_enrichment_batch(children, outcomes=enrichment_outcomes):
            for eid, etype, score, freshness, decision in cur.fetchall():
                if was_alerted_recently(conn, f"ier_{eid}", hours=4):
                    report["deferred"] += 1
                    continue

                if etype == "market":
                    # Claim the four-hour slot atomically before spawning. Two
                    # watchdog invocations may have read the same stale row; only
                    # one can update it from stale to current and launch a writer.
                    claim_time = None
                    try:
                        cur.execute(
                            """UPDATE intelligence_entities SET last_enriched=NOW()
                            WHERE entity_id=%s
                              AND (last_enriched IS NULL OR last_enriched < NOW()-INTERVAL '4 hours')
                            RETURNING last_enriched""",
                            [eid],
                        )
                        claim = cur.fetchone()
                        if not claim:
                            report["deferred"] += 1
                            conn.commit()
                            continue
                        claim_time = claim[0]
                        conn.commit()
                        proc = subprocess.Popen(
                            [sys.executable, "scripts/symbol_enrichment.py", eid, str(int(score or 0))],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            cwd=PROJECT_ROOT,
                            start_new_session=True,
                        )
                        claim_times[eid] = claim_time
                        children.append((eid, proc))
                        enrichments.append((eid, score, freshness, proc))
                    except Exception as exc:
                        log.warning("[watchdog] could not start enrichment for %s: %s", eid, type(exc).__name__)
                        if claim_time is not None:
                            try:
                                conn.rollback()
                                cur.execute(
                                    """UPDATE intelligence_entities SET last_enriched=NULL
                                    WHERE entity_id=%s AND last_enriched=%s""",
                                    [eid, claim_time],
                                )
                                conn.commit()
                            except Exception as reset_exc:
                                log.error(
                                    "[watchdog] could not release enrichment claim for %s: %s",
                                    eid,
                                    type(reset_exc).__name__,
                                )
                            finally:
                                del claim_time
                        log_action(
                            conn,
                            "trigger_enrichment",
                            eid,
                            f"score={score} fresh={freshness}",
                            False,
                            f"spawn failed: {type(exc).__name__}",
                        )
                        report["failed"] += 1
                elif etype == "subject" and freshness == "CRITICAL":
                    try:
                        cur.execute(
                            """INSERT INTO watchdog_actions (action_type,target,reason,success,result,created_at)
                            VALUES ('queue_alex_refresh',%s,'subject CRITICAL',true,'queued',NOW())""",
                            [eid],
                        )
                        conn.commit()
                        actions += 1
                    except Exception:
                        pass
    except _EnrichmentInterrupted as exc:
        interrupted = exc
        enrichment_outcomes.update({eid: "parent_interrupted" for eid, _ in children})

    # No fire-and-forget children: this step returns only after every child has
    # completed, or its bounded supervisor has terminated and reaped it.
    for eid, score, freshness, proc in enrichments:
        if proc.returncode == 0 and eid not in enrichment_outcomes:
            log_action(
                conn,
                "trigger_enrichment",
                eid,
                f"score={score} fresh={freshness}",
                True,
                "child exit=0; may be a safe no-op because another session owns the symbol lock",
            )
            actions += 1
            report["completed"] += 1
        else:
            report["failed"] += 1
            # A failed batch must not hold its four-hour freshness claim. Only
            # release our own timestamp; a later successful writer wins.
            cur.execute("UPDATE intelligence_entities SET last_enriched=NULL "
                        "WHERE entity_id=%s AND last_enriched=%s", [eid, claim_times[eid]])
            conn.commit()
            detail = enrichment_outcomes.get(eid, f"exit={proc.returncode}")
            log.warning("[watchdog] symbol enrichment for %s ended with %s", eid, detail)
            log_action(conn, "trigger_enrichment", eid, f"score={score} fresh={freshness}", False, detail)
    if interrupted is not None:
        raise interrupted
    return actions


# ── MAIN ──


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--no-telegram", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--enrichment-only", action="store_true",
                        help="independent repair service only; never run in health tick")
    args = parser.parse_args()

    if args.dry_run:
        # Truly offline; no DB, environment file, provider, labels or services.
        from lib.pipeline_repair_handoff import request_repair
        print(json.dumps(request_repair("enrichment", dry_run=True)))
        return 0
    from lib.pipeline_repair_handoff import independently_owned
    if args.enrichment_only and (os.getenv("TRADEAI_PIPELINE_REPAIR_KIND") != "enrichment"
                                 or os.getenv("HEALTH_TICK_STEP_TIMEOUT_S") or not independently_owned("enrichment")):
        log.error("enrichment requires independent repair service")
        return 2
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True  # Prevent transaction state issues between functions
    try:
        if args.enrichment_only:
            report = {}
            run_ier_engine(conn, report=report)
            print(json.dumps(report))
            log.info("[watchdog] enrichment result %s", json.dumps(report))
            return 1 if report.get("failed") else 0
        # Queue independent enrichment before potentially slow monitoring retries.
        # Otherwise a retry that exhausts the tick could still starve enrichment.
        from lib.pipeline_repair_handoff import request_repair
        handoff = request_repair("enrichment")
        log.info("[watchdog] enrichment handoff %s", json.dumps(handoff))
        # Function 1: Pipeline monitoring
        issues = check_pipeline_execution(conn)
        if issues and not args.dry_run:
            handle_pipeline_issues(conn, issues, no_telegram=args.no_telegram)
        elif issues:
            for i in issues:
                log.info(f"[DRY] Would handle: {i['script']} ({i['issue']})")

        # Function 2: GO coverage
        if not args.dry_run:
            fixed = check_go_coverage(conn)
            if fixed:
                log.info(f"[watchdog] GO coverage: fixed {fixed}")

        # A repair handoff that was not accepted (the repair unit is not installed, or it refused to start) is a
        # FINDING the handoff record already names, not a crash. Exit 3 (EXIT_FINDING), never 1: health_tick.py
        # reads 1 as an uncaught exception, and this step marked tradeai-health-tick failed every two hours
        # (LQ-20261107-307; 81 "crashed" rows 2026-11-01..07, all "repair unit not installed/loaded").
        # config/health_tick_steps.json declares finding_rc [3] for this step.
        from lib.monitor_exit_codes import EXIT_FINDING
        return 0 if handoff.get("accepted") else EXIT_FINDING

    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            *([] if "--dry-run" in sys.argv else
              [logging.FileHandler(os.path.join(PROJECT_ROOT, "logs/pipeline_watchdog.log"))]),
            logging.StreamHandler(),
        ],
    )
    raise SystemExit(main())
