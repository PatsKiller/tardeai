#!/usr/bin/env python3
"""build_hermes_canonical_status.py — merge live Hermes state into ONE canonical snapshot (Phase 217).

Read-only. Fetches the live /api/v2/hermes/* endpoints + systemd timer status, measures the Hermes DB
table lineage read-only through the shared credential loader, and writes a normalized snapshot to
data/runtime/hermes_canonical_status_latest.json. Portal labels, the matrix Markdown, and the Word doc
are all regenerated FROM this single source so portal/state/docs agree. No secrets are stored.
(LQ-20261107-478: the lineage used to be whatever the workflow-matrix endpoint served — a JSON whose
producer nothing schedules — so the canonical file reported June's row counts in November. The DB is
the source; the snapshot is the labelled fallback.)

  python3 scripts/build_hermes_canonical_status.py [--dry-run]

--dry-run (refactor wave 1, 2026-10-10): fetches the same read-only endpoints, prints the snapshot it
would write and exits; writes neither the snapshot nor the lane receipt. A real run still writes the
snapshot exactly as before, then writes data/runtime/build-hermes-canonical-status_last.json
(LaneRunReceipt@v1) and exits 1 when any endpoint failed (ok_at advances only when all succeeded).
"""
try:  # cc_auth (2026-10-14): service token for loopback Command Center (:7777) calls
    from lib.cc_client import cc_urlopen as _cc_urlopen
except ImportError:  # pragma: no cover - scripts/ not on sys.path
    import sys as _cc_sys
    from pathlib import Path as _CcPath
    _cc_sys.path.insert(0, str(next(p for p in _CcPath(__file__).resolve().parents if p.name == "scripts")))
    from lib.cc_client import cc_urlopen as _cc_urlopen

import os, sys, json, subprocess, urllib.request
import argparse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get("HERMES_API_BASE", "http://127.0.0.1:7777/api/v2/hermes")
OUT = ROOT / "data" / "runtime" / "hermes_canonical_status_latest.json"
LANE_ID = "build-hermes-canonical-status"
ENDPOINTS = ("workflow-matrix", "llm-auth-status", "self-learning-loops", "researcher-matrix",
             "legacy-agents", "health", "profiles-status")
XDG = {"XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}", **os.environ}


PROBE_CONFIG = ROOT / "config" / "hermes_canonical_status_probe.json"
_PROBE_DEFAULTS = {"first_call_timeout_s": 60.0, "timeout_s": 20.0, "retries": 2, "backoff_s": [3, 8]}
_first_call_done = False


def probe_config(path=None):
    """Timeouts/retries from config; a missing or broken file falls back to the defaults (never raises)."""
    cfg = dict(_PROBE_DEFAULTS)
    try:
        raw = json.loads(Path(path or PROBE_CONFIG).read_text())
        for k in cfg:
            if k in raw:
                cfg[k] = raw[k]
        cfg["first_call_timeout_s"] = float(cfg["first_call_timeout_s"])
        cfg["timeout_s"] = float(cfg["timeout_s"])
        cfg["retries"] = max(0, int(cfg["retries"]))
        cfg["backoff_s"] = [float(x) for x in cfg["backoff_s"]] or [0.0]
    except Exception:
        cfg = dict(_PROBE_DEFAULTS)
    return cfg


def _transient(exc):
    """Timeouts and connection failures (server restarting) retry; an HTTP status or bad JSON does not."""
    import urllib.error
    if isinstance(exc, urllib.error.HTTPError):
        return False
    return isinstance(exc, (TimeoutError, ConnectionError, OSError)) or isinstance(
        getattr(exc, "reason", None), (TimeoutError, ConnectionError, OSError))


def api(ep, *, cfg=None, opener=None, sleep=None):
    """GET one hermes endpoint. The process's first request uses first_call_timeout_s (the portfolio-server
    is slow right after a restart); transient failures retry with backoff_s."""
    global _first_call_done
    import time
    cfg = cfg or probe_config()
    opener = opener or _cc_urlopen
    sleep = sleep or time.sleep
    timeout = cfg["timeout_s"] if _first_call_done else cfg["first_call_timeout_s"]
    _first_call_done = True
    last = None
    for attempt in range(cfg["retries"] + 1):
        try:
            with opener(f"{BASE}/{ep}", timeout=timeout) as r:
                return json.loads(r.read()).get("data", {})
        except Exception as e:
            last = e
            if attempt >= cfg["retries"] or not _transient(e):
                break
            sleep(cfg["backoff_s"][min(attempt, len(cfg["backoff_s"]) - 1)])
            timeout = max(timeout, cfg["timeout_s"])
    return {"_error": str(last)[:120]}


def sysd(cmd):
    try:
        return subprocess.run(["systemctl", "--user"] + cmd, capture_output=True, text=True,
                              timeout=10, env=XDG).stdout.strip()
    except Exception:
        return ""


def timer(name):
    return {"enabled": sysd(["is-enabled", f"{name}.timer"]) or "unknown",
            "active": sysd(["is-active", f"{name}.timer"]) or "unknown"}


def endpoint_errors(results):
    """{endpoint: error} for every endpoint api() could not read."""
    return {ep: r["_error"] for ep, r in results.items() if isinstance(r, dict) and "_error" in r}


# ── header counts ────────────────────────────────────────────────────────────────────────────────
# These four were literals from the first commit (baa3ac462, 2026-06-07): crons 209 and timers 38
# against a host that had 327 active crontab lines and 83 user timers (2026-11-07, LQ-20261107-139).
# A stale count cannot be reconciled by its reader — 209, 327 and 438 were all "the" number to
# somebody — so the two that the host can answer are measured, with their definition written beside
# them, and a host that cannot be asked yields None with the reason rather than a remembered number.
CRON_COUNT_DEFINITION = ("active lines in `crontab -l`: a line that is neither blank nor a '#' "
                         "comment (environment assignments such as SHELL= count as active)")
TIMER_COUNT_DEFINITION = ("non-blank lines of `systemctl --user list-timers --all --no-legend`: "
                          "every loaded user timer, active or not")
SYSTEM_TIMER_COUNT_DEFINITION = ("non-blank lines of `systemctl list-timers --all --no-legend`: the "
                                 "system-scope timers, reported separately so neither scope is mistaken "
                                 "for the other")
STATIC_COUNT_NOTE = "static System-page header scope; not measured from the host"
#: A lineage file older than this cannot answer "writes in the last 24 h". The producers
#: (audit_hermes_db_lineage.py, audit_hermes_workflow_owners.py) are not scheduled, so the file on
#: this host is from 2026-06-07 — its writes_24h describes that June day, not today.
LINEAGE_MAX_AGE_DAYS = 2
TABLE_COUNT_DEFINITION = ("entries in the `tables` list of data/hermes/hermes_db_lineage_latest.json, "
                          "as served by /api/v2/hermes/workflow-matrix; the snapshot names every table")
#: Live lineage (LQ-20261107-478): the table list and its counts are measured from the DB, read-only,
#: through the shared credential loader. The snapshot above is what the endpoint serves when nobody has
#: re-run the audit (its producer is unscheduled and the file on this host is from 2026-06-07), so it is
#: a labelled fallback — never mixed in silently with measured rows.
LIVE_LINEAGE_DEFINITION = ("BASE TABLEs in schema public whose name starts `hermes_`, read read-only "
                           "through session13_db (the shared credential loader): rows = count(*), "
                           "last_write = max(<timestamp column>), writes_24h/7d = rows whose timestamp "
                           "column falls inside the window")
LIVE_VIEWS_DEFINITION = "VIEWs in schema public whose name starts `hermes_v_`"
LINEAGE_SNAPSHOT_REL = "data/hermes/hermes_db_lineage_latest.json"
LINEAGE_SNAPSHOT = ROOT / "data" / "hermes" / "hermes_db_lineage_latest.json"
_TS_COLUMN_PREFERENCE = ("created_at", "run_at", "emitted_at", "scored_at", "promoted_at",
                         "first_seen_at", "checked_at", "updated_at")


def _run(cmd, env=None):
    """(returncode, stdout) of a host command; (-1, '') when it cannot be started at all."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=env)
        return p.returncode, p.stdout
    except Exception:
        return -1, ""


def count_active_crontab_lines(text):
    """Active crontab lines. A failed `crontab -l` prints a message, not a crontab — see _measure."""
    return sum(1 for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#'))


def count_user_timers(text):
    return sum(1 for line in text.splitlines() if line.strip())


def _measure(command, counter, label, env=None):
    """(count | None, error | None). A command that failed answers nothing; it does not answer 0."""
    rc, out = _run(command, env=env)
    if rc != 0:
        return None, f"{label} failed (exit {rc}); the count is unknown, not zero"
    return counter(out), None


def measure_host_counts():
    """The snapshot's header counts: measured where the host can answer, marked static where not."""
    crons, crons_err = _measure(["crontab", "-l"], count_active_crontab_lines, "crontab -l")
    timers, timers_err = _measure(["systemctl", "--user", "list-timers", "--all", "--no-legend"],
                                  count_user_timers, "systemctl --user list-timers", env=XDG)
    sys_timers, sys_timers_err = _measure(["systemctl", "list-timers", "--all", "--no-legend"],
                                          count_user_timers, "systemctl list-timers")
    measured_at = datetime.now(timezone.utc).isoformat()
    return {
        "crons_count": crons,
        "timers_count": timers,
        "timers_system_count": sys_timers,
        "counts_provenance": {
            "crons_count": {"definition": CRON_COUNT_DEFINITION, "measured_at": measured_at, "error": crons_err},
            "timers_count": {"definition": TIMER_COUNT_DEFINITION, "measured_at": measured_at, "error": timers_err},
            "timers_system_count": {"definition": SYSTEM_TIMER_COUNT_DEFINITION, "measured_at": measured_at,
                                    "error": sys_timers_err},
            "services_count": {"value": 2, "measured": False, "note": STATIC_COUNT_NOTE},
            "llm_jobs_count": {"value": 6, "measured": False, "note": STATIC_COUNT_NOTE},
        },
    }


def _age_days(iso_text, now=None):
    """Age of an ISO-8601 timestamp in days, or None when it is absent or unreadable."""
    if not isinstance(iso_text, str) or not iso_text:
        return None
    try:
        at = datetime.fromisoformat(iso_text)
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return round(((now or datetime.now(timezone.utc)) - at.astimezone(timezone.utc)).total_seconds() / 86400, 2)


def _readonly_conn():
    """A READ ONLY DB connection through the shared loader (never a psql shell-out, never os.environ)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import session13_db
    conn = session13_db.get_conn(options="-c default_transaction_read_only=on", connect_timeout=8)
    conn.set_session(readonly=True)
    return conn


def _sql_ident(name):
    """A psycopg2 Identifier for a name read from information_schema — identifiers cannot be bound as
    parameters, so they are composed (not interpolated) and quoted by the driver."""
    from psycopg2 import sql
    return sql.Identifier(str(name))


def _timestamp_columns(cur):
    """{table: [timestamp column, ...]} for the hermes tables, in ordinal order."""
    cur.execute("select table_name, column_name from information_schema.columns "
                "where table_schema='public' and table_name like 'hermes\\_%' "
                "and data_type in ('timestamp with time zone','timestamp without time zone') "
                "order by table_name, ordinal_position")
    cols = {}
    for table, column in cur.fetchall():
        cols.setdefault(table, []).append(column)
    return cols


def measure_db_lineage(static_tables=None, connect=None):
    """(tables, views, provenance) measured read-only from the live DB.

    ``static_tables`` is the endpoint's (snapshot-sourced) list; its ``written_by``/``read_by`` name
    scripts found by a code audit that no query can reproduce, so they are carried by name and the
    provenance says where they came from. Any failure — no credentials, an unreachable server, a
    missing table — returns ``(None, None, provenance)`` with ``source: "snapshot"`` and the reason,
    so the caller keeps the snapshot and the snapshot stays labelled as one.
    """
    static = {t.get("table"): t for t in (static_tables or []) if isinstance(t, dict) and t.get("table")}
    measured_at = datetime.now(timezone.utc).isoformat()
    conn = None
    try:
        from psycopg2 import sql  # identifiers composed, never interpolated into the SQL text
        conn = (connect or _readonly_conn)()
        cur = conn.cursor()
        cur.execute("select table_name, table_type from information_schema.tables "
                    "where table_schema='public' and table_name like 'hermes\\_%' order by table_name")
        relations = [(row[0], row[1]) for row in cur.fetchall()]
        ts_columns = _timestamp_columns(cur)
        tables = []
        for name, kind in relations:
            if kind != "BASE TABLE":
                continue
            columns = ts_columns.get(name) or []
            ts = next((c for c in _TS_COLUMN_PREFERENCE if c in columns), columns[0] if columns else None)
            if ts:
                cur.execute(sql.SQL("select count(*), max({ts}), "
                                    "count(*) filter (where {ts} >= now() - interval '24 hours'), "
                                    "count(*) filter (where {ts} >= now() - interval '7 days') "
                                    "from public.{tbl}").format(ts=_sql_ident(ts), tbl=_sql_ident(name)))
                rows, last_write, writes_24h, writes_7d = cur.fetchone()
            else:
                cur.execute(sql.SQL("select count(*) from public.{tbl}").format(tbl=_sql_ident(name)))
                rows = cur.fetchone()[0]
                last_write = writes_24h = writes_7d = None
            tables.append({
                "table": name, "exists": True, "rows": rows,
                "last_write": last_write.isoformat() if hasattr(last_write, "isoformat") else last_write,
                "writes_24h": writes_24h, "writes_7d": writes_7d, "counted_by": ts,
                "written_by": (static.get(name) or {}).get("written_by"),
                "read_by": (static.get(name) or {}).get("read_by"),
            })
        views = [name for name, kind in relations if kind == "VIEW"]
        cur.close()
        provenance = {
            "definition": LIVE_LINEAGE_DEFINITION, "source": "live", "measured_at": measured_at,
            "tables_counted": len(tables), "views_counted": len(views),
            "static_audit_fields_from": (LINEAGE_SNAPSHOT_REL if static else None),
            "snapshot_tables_not_in_db": sorted(set(static) - {t["table"] for t in tables}),
            "error": None,
        }
        return tables, views, provenance
    except Exception as e:  # noqa: BLE001 — any failure is reported, never guessed around
        provenance = {
            "definition": LIVE_LINEAGE_DEFINITION, "source": "snapshot", "measured_at": None,
            "snapshot_path": str(LINEAGE_SNAPSHOT),
            "error": f"{type(e).__name__}: {str(e)[:180]}",
        }
        return None, None, provenance
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception as e:  # noqa: BLE001 — the answer is already decided; a close failure is noise
                print(f"WARN: could not close the lineage connection: {type(e).__name__}: {e}", file=sys.stderr)


def derive_matrix(wf, live=None):
    """(snapshot fields, provenance) for everything the workflow-matrix endpoint answers.

    An endpoint that could not answer yields ``None`` — the old shape turned a missing file into
    "0 DB tables", which reads as a measured zero and left the reader nothing to reconcile. The
    tables are named, not only counted (LQ-20261107-53), and the lineage's own age is carried: a
    ``writes_24h`` recorded on 2026-06-07 is not today's write count, so it is reported as unknown
    rather than as a five-month-old number with a 24-hour label.

    ``live`` is ``measure_db_lineage()``'s ``(tables, views, provenance)``. When it measured, its
    list and counts are the answer and the snapshot fields below are only the static-audit columns;
    when it did not, the snapshot is the answer and its provenance stays exactly as it was.
    """
    wf = wf if isinstance(wf, dict) else {}
    audit = wf.get("audit_sources") if isinstance(wf.get("audit_sources"), dict) else {}
    files = audit.get("files") if isinstance(audit.get("files"), dict) else {}
    lin = files.get("db_lineage") if isinstance(files.get("db_lineage"), dict) else {}
    nodes_src = files.get("graph_nodes") if isinstance(files.get("graph_nodes"), dict) else {}
    lineage_at = lin.get("modified_at")
    age = _age_days(lineage_at)
    answered = bool(lin.get("present")) and not lin.get("error")
    fresh = answered and age is not None and age <= LINEAGE_MAX_AGE_DAYS

    tables = wf.get("db_lineage") if isinstance(wf.get("db_lineage"), list) else None
    names = None if tables is None else [
        {"table": t.get("table"), "exists": t.get("exists"), "rows": t.get("rows"),
         "writes_24h": t.get("writes_24h") if fresh else None, "last_write": t.get("last_write")}
        for t in tables if isinstance(t, dict)]
    live_tables, live_views, live_provenance = live if live else (None, None, None)
    measured = live_tables is not None
    if measured:
        names = live_tables
    by_table = {n["table"]: n for n in (names or [])}
    graph_nodes = wf.get("graph_nodes") if isinstance(wf.get("graph_nodes"), list) else None
    fields = {
        "workflows_count": wf.get("workflow_count") if isinstance(wf.get("workflow_count"), int) else None,
        "graph_nodes_count": None if graph_nodes is None else len(graph_nodes),
        "graph_nodes": None if graph_nodes is None else [
            {"id": n.get("id"), "name": n.get("name"), "owner": n.get("owner_hint")}
            for n in graph_nodes if isinstance(n, dict)],
        "db_tables": names,
        "db_tables_count": None if names is None else len(names),
        "safe_views_count": (len(live_views) if measured else
                             (wf.get("safe_views_count") if isinstance(wf.get("safe_views_count"), int) else None)),
        "db_writes_24h": {"research_intelligence": (by_table.get("hermes_research_intelligence") or {}).get("writes_24h"),
                          "memory_events": (by_table.get("hermes_memory_events") or {}).get("writes_24h")},
    }
    provenance = {
        "db_tables_count": {
            "definition": TABLE_COUNT_DEFINITION, "source": lin.get("path"), "modified_at": lineage_at,
            "age_days": age, "stale": bool(answered and not fresh),
            "error": lin.get("error") or (None if answered else "lineage source not found"),
        },
        "db_writes_24h": {
            "definition": ("writes_24h recorded when the lineage file was generated; reported only when that "
                           f"file is at most {LINEAGE_MAX_AGE_DAYS:g} days old"),
            "source": lin.get("path"), "modified_at": lineage_at, "age_days": age, "fresh": fresh,
        },
        "graph_nodes_count": {"source": nodes_src.get("path"), "modified_at": nodes_src.get("modified_at"),
                              "error": nodes_src.get("error") or (None if nodes_src.get("present") else "graph source not found")},
    }
    if measured:
        provenance["db_tables_count"] = {
            **live_provenance, "snapshot_at": lineage_at, "snapshot_age_days": age,
            "snapshot_static_fields": {n["table"]: bool(n.get("written_by") or n.get("read_by"))
                                       for n in names if n.get("written_by") or n.get("read_by")},
        }
        provenance["db_writes_24h"] = {
            "definition": "rows whose timestamp column falls inside the 24-hour window, counted live",
            "source": "live", "measured_at": live_provenance["measured_at"], "fresh": True,
        }
        provenance["safe_views_count"] = {"definition": LIVE_VIEWS_DEFINITION, "source": "live",
                                          "measured_at": live_provenance["measured_at"]}
    elif live_provenance:
        # The measurement failed: the snapshot stands in, and its provenance says the live read failed.
        for key in ("db_tables_count", "db_writes_24h", "safe_views_count"):
            provenance.setdefault(key, {})["live_error"] = live_provenance["error"]
    return fields, provenance


def build_snapshot():
    """Read-only: the snapshot dict plus the raw endpoint results. Writes nothing."""
    results = {ep: api(ep) for ep in ENDPOINTS}
    wf = results["workflow-matrix"]; auth = results["llm-auth-status"]; sll = results["self-learning-loops"]
    leg = results["legacy-agents"]; health = results["health"]; ps = results["profiles-status"]
    matrix, matrix_provenance = derive_matrix(wf, measure_db_lineage(wf.get("db_lineage")))

    deep_timer = timer("hermes-deep-research-local")
    counts = measure_host_counts()
    codex = next((l for l in auth.get("lanes", []) if l.get("provider") == "openai-codex"), {})
    serverops = next((p for p in (ps.get("profiles") or []) if p.get("profile") == "serverops"), {})
    so_tools = serverops.get("tools", "")
    so_count = int(so_tools.split(" ")[0]) if so_tools and so_tools.split(" ")[0].isdigit() else None

    snap = {
        "portal_snapshot_timestamp": datetime.now().isoformat(),
        "hermes_version": "v0.16.0",
        "timers_count": counts["timers_count"], "crons_count": counts["crons_count"],
        "timers_system_count": counts["timers_system_count"],
        "services_count": 2, "llm_jobs_count": 6,  # static System-page header scope
        "counts_provenance": {**counts["counts_provenance"], **matrix_provenance},
        "workflows_count": matrix["workflows_count"],
        "graph_nodes_count": matrix["graph_nodes_count"],
        "db_tables": matrix["db_tables"],
        "db_tables_count": matrix["db_tables_count"],
        "safe_views_count": matrix["safe_views_count"],
        "cli_profile_used_by_automation": wf.get("any_cli_profile_in_jobs"),
        "db_writes_24h": matrix["db_writes_24h"],
        "profiles": [{"profile": p.get("profile"), "model": p.get("model"),
                      "tools": p.get("tools"), "soul_hash": p.get("soul_hash")} for p in (ps.get("profiles") or [])],
        "llm_lanes": [{"lane": l.get("lane"), "provider": l.get("provider"), "authed": l.get("authed"),
                       "usable": l.get("usable"), "headless_status": l.get("headless_status"),
                       "reason_code": l.get("reason_code")} for l in auth.get("lanes", [])],
        "self_learning_loops": {"count": sll.get("loop_count"), "advisory_only": sll.get("advisory_only_loops"),
                                "feed_prompts": sll.get("loops_affecting_prompts"),
                                "mutate_scoring": sll.get("loops_affecting_scoring_directly"),
                                "closed_loop_status": (sll.get("closed_loop_status") or "").split("—")[0].strip(),
                                "gaps": sll.get("highest_priority_gaps"),
                                "loops": [{"loop": l["loop"], "rows": l.get("rows"),
                                           "feeds_prompts": l.get("affects_future_prompts"),
                                           "mutates_scoring": l.get("affects_scoring")} for l in sll.get("loops", [])]},
        "graph_nodes": matrix["graph_nodes"],
        "retired_agents": leg.get("count") or len(leg.get("items", [])),
        "gateway_status": sysd(["is-active", "hermes-gateway.service"]) + "/" + sysd(["is-enabled", "hermes-gateway.service"]),
        "kill_switch": {"active": health.get("kill_switch_active"),
                        "canonical_path": (health.get("kill_switch") or {}).get("canonical_path", "data/runtime/HERMES_DISABLED")},
        "deep_research_lane": {
            "design_status": "designed", "runner_built": True,
            "runner_script": "scripts/hermes_deep_research_local.py",
            "timer_enabled": deep_timer["enabled"] == "enabled",
            "timer_active": deep_timer["active"] == "active",
            "next_run": "daily 02:30 local (overnight-gated)",
            "model": "gemma3:27b / gemma3-overnight", "writes_to": "hermes_research_intelligence (staging)",
            "safety": "advisory/staging-only; kill-switch + health-gate; --apply self-gated to overnight"},
        "codex_lane": {
            "auth_ready": codex.get("authed"), "interactive_ready": True,
            "headless_available": codex.get("headless_status") == "ready",
            "headless_reason": codex.get("reason_code"), "runtime_enabled": False,
            "usage": "hermes -p dev chat (interactive only on Hermes 0.16.0)"},
        "serverops": {"tool_count": so_count, "tools": so_tools,
                      "risk_status": "UNSAFE — terminal/code_execution/computer_use enabled",
                      "p1_hardening_required": True},
        "canonical_docs": {
            "markdown_path": "docs/hermes/HERMES_AGENTS_WORKFLOWS_SOULS_AND_SELF_LEARNING_MATRIX.md",
            "word_path": "docs/hermes/HERMES_AGENTS_WORKFLOWS_SOULS_AND_SELF_LEARNING_MATRIX.docx",
            "status_json": "data/runtime/hermes_canonical_status_latest.json"},
        "open_gates": ["P1: harden serverops dangerous tools (terminal/code_execution/computer_use)",
                       "self-learning: dedicated research_backlog table",
                       "shadow-efficacy < graft sample (keep advisory)",
                       "Codex headless: blocked on Hermes 0.16.0 (auto-recovers on newer build)",
                       "Claude: add Anthropic credits; Nous: complete OAuth; gemma4: deferred"],
    }
    return snap, results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--dry-run", action="store_true", help="fetch + print; write nothing")
    args = ap.parse_args(argv)
    started = datetime.now(timezone.utc)
    snap, results = build_snapshot()
    errors = endpoint_errors(results)
    if args.dry_run:
        # Returns BEFORE any write is reachable (AGENTS.md §6).
        print(json.dumps(snap, indent=2, default=str))
        print(f"DRY RUN: would write {OUT}")
        print(f"DRY RUN: endpoint errors: {errors or 'none'}; live exit would be {1 if errors else 0}")
        print("DRY RUN: nothing written, no receipt")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snap, indent=2, default=str))
    print(json.dumps({k: snap[k] for k in ("workflows_count", "graph_nodes_count", "db_tables_count",
          "safe_views_count", "retired_agents", "gateway_status")}, indent=2))
    print("deep_research timer_enabled:", snap["deep_research_lane"]["timer_enabled"])
    print("codex headless_available:", snap["codex_lane"]["headless_available"], "reason:", snap["codex_lane"]["headless_reason"])
    print("serverops tools:", snap["serverops"]["tool_count"], "p1:", snap["serverops"]["p1_hardening_required"])
    lineage_source = ("live" if (snap.get("counts_provenance") or {}).get("db_tables_count", {}).get("source")
                      == "live" else "snapshot")
    print("db lineage source:", lineage_source)
    print("wrote", OUT)
    rc = 1 if errors else 0
    if errors:
        print(f"ERROR: {len(errors)}/{len(ENDPOINTS)} endpoint(s) failed: {sorted(errors)}", file=sys.stderr)
    sys.path.insert(0, str(ROOT / "scripts"))
    from lib.lane_last_receipt import write_lane_receipt
    write_lane_receipt(LANE_ID, ok=not errors, exit_code=rc, started_at=started,
                       summary={"out": str(OUT), "endpoints": len(ENDPOINTS),
                                "endpoint_errors": sorted(errors),
                                "db_lineage_source": lineage_source})
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
