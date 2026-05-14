#!/usr/bin/env python3
"""report_deep_overnight_queue_status.py — Deep overnight LLM queue status reporter.

Standalone CLI tool for inspecting queue health, job mix, and model status.

Usage:
    .venv/bin/python scripts/report_deep_overnight_queue_status.py --summary
    .venv/bin/python scripts/report_deep_overnight_queue_status.py --pending-top 30
    .venv/bin/python scripts/report_deep_overnight_queue_status.py --json > /tmp/status.json

Does NOT touch broker, holdings, execution, or trading behavior.
"""

import argparse
import json
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
LOCK_FILE = Path("/tmp/tradeai_deep_llm_window.lock")
USE_COLOR = sys.stdout.isatty()


# ── ANSI helpers ─────────────────────────────────────────────────────────────

def _c(code: str, text: str) -> str:
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"

def bold(t):   return _c("1", t)
def green(t):  return _c("32", t)
def red(t):    return _c("31", t)
def yellow(t): return _c("33", t)
def cyan(t):   return _c("36", t)
def dim(t):    return _c("2", t)


def section(title: str) -> str:
    return bold(f"┌─ {title} " + "─" * max(0, 60 - len(title)))


# ── DB ───────────────────────────────────────────────────────────────────────

def get_db_connection():
    import psycopg2
    env_path = PROJ / ".env"
    env_vars = {}
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    return psycopg2.connect(
        host=env_vars.get("DB_HOST", "localhost"),
        dbname=env_vars.get("DB_NAME", "trade_ai"),
        user=env_vars.get("DB_USER", "trade_ai"),
        password=env_vars.get("DB_PASSWORD", ""),
    )


# ── Data collection ─────────────────────────────────────────────────────────

def collect(args):
    import psycopg2.extras
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    data = {}

    since = None
    if args.today:
        since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # 1. Queue counts by status
    cur.execute("SELECT status, COUNT(*) FROM deep_overnight_llm_queue GROUP BY status ORDER BY status")
    data["status_counts"] = {r["status"]: r["count"] for r in cur.fetchall()}

    # 2. Counts by job_type + status
    cur.execute("""SELECT job_type, status, COUNT(*) AS cnt
                   FROM deep_overnight_llm_queue
                   GROUP BY job_type, status ORDER BY job_type, status""")
    jt_status = {}
    for r in cur.fetchall():
        jt_status.setdefault(r["job_type"], {})[r["status"]] = r["cnt"]
    data["job_type_status"] = jt_status

    # 3. Done in last 24h by job_type
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    cur.execute("""SELECT job_type, COUNT(*) AS cnt
                   FROM deep_overnight_llm_queue
                   WHERE status='done' AND completed_at >= %s
                   GROUP BY job_type ORDER BY cnt DESC""", [since_24h])
    data["done_24h"] = {r["job_type"]: r["cnt"] for r in cur.fetchall()}

    # 4. Failed jobs with last_error (max 10)
    q = """SELECT id, job_type, symbol, last_error, attempt_count, updated_at
           FROM deep_overnight_llm_queue
           WHERE status='failed'"""
    if since:
        q += " AND updated_at >= %s"
    q += " ORDER BY updated_at DESC LIMIT 10"
    cur.execute(q, [since] if since else [])
    data["failed_jobs"] = [dict(r) for r in cur.fetchall()]

    # 5. Pending P0/P1 counts
    cur.execute("""SELECT priority_tier, COUNT(*) AS cnt
                   FROM deep_overnight_llm_queue
                   WHERE status='pending' AND priority_tier IN ('P0','P1')
                   GROUP BY priority_tier ORDER BY priority_tier""")
    data["pending_priority"] = {r["priority_tier"]: r["cnt"] for r in cur.fetchall()}

    # 6. Oldest pending jobs
    limit_pending = args.pending_top if args.pending_top else 5
    cur.execute("""SELECT id, job_type, symbol, priority_tier, priority_score,
                          queued_at, attempt_count
                   FROM deep_overnight_llm_queue
                   WHERE status='pending'
                   ORDER BY queued_at ASC LIMIT %s""", [limit_pending])
    data["oldest_pending"] = [dict(r) for r in cur.fetchall()]

    # 7. Latest run summary (from queue timestamps)
    cur.execute("""SELECT MIN(started_at) AS run_start, MAX(completed_at) AS run_end,
                          COUNT(*) FILTER (WHERE status='done') AS done,
                          COUNT(*) FILTER (WHERE status='failed') AS failed
                   FROM deep_overnight_llm_queue
                   WHERE started_at >= NOW() - INTERVAL '24 hours'""")
    row = cur.fetchone()
    data["latest_run"] = dict(row) if row else {}

    # 8. Latest risk synthesis
    cur.execute("""SELECT id, generated_at, portfolio_value, narrative,
                          morning_brief_ready, top_risks
                   FROM risk_synthesis_results
                   ORDER BY generated_at DESC LIMIT 1""")
    row = cur.fetchone()
    data["risk_synthesis"] = dict(row) if row else None

    # 9. Latest recovery watch verdicts
    cur.execute("""SELECT r.symbol, r.reentry_verdict, r.created_at
                   FROM deep_overnight_llm_results r
                   WHERE r.job_type='recovery_watch_review'
                   ORDER BY r.created_at DESC LIMIT 10""")
    data["recovery_verdicts"] = [dict(r) for r in cur.fetchall()]

    # 10. Journal / closed-trade review count (last 24h)
    cur.execute("""SELECT job_type, COUNT(*) AS cnt
                   FROM deep_overnight_llm_results
                   WHERE job_type IN ('closed_trade_review','auto_journal_review','manual_journal_review')
                   AND created_at >= %s
                   GROUP BY job_type""", [since_24h])
    data["journal_review_counts"] = {r["job_type"]: r["cnt"] for r in cur.fetchall()}

    # 11. RAG curation verdict counts (last 24h)
    cur.execute("""SELECT curation_verdict, COUNT(*) AS cnt
                   FROM deep_overnight_llm_results
                   WHERE job_type='rag_content_curation'
                   AND created_at >= %s
                   GROUP BY curation_verdict ORDER BY cnt DESC""", [since_24h])
    data["rag_verdicts"] = {r["curation_verdict"]: r["cnt"] for r in cur.fetchall()}

    cur.close()
    conn.close()

    # 12. Ollama model status
    data["ollama_models"] = _check_ollama()

    # 13. Lock file
    data["lock_exists"] = LOCK_FILE.exists()

    # 14. Cron check
    data["cron_scheduled"] = _check_cron()

    return data


def _check_ollama():
    """Check which models are resident in ollama."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/ps")
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = json.loads(resp.read())
        running = [m.get("name", "") for m in body.get("models", [])]
        return {
            "qwen3_14b": any("qwen3" in n and "14b" in n for n in running),
            "nomic_embed": any("nomic-embed" in n for n in running),
            "raw": running,
        }
    except Exception:
        return {"qwen3_14b": False, "nomic_embed": False, "raw": [], "error": "ollama unreachable"}


def _check_cron():
    """Check if deep overnight run is in crontab."""
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
        lines = result.stdout.splitlines()
        return any("deep_overnight" in l or "deep-overnight" in l for l in lines if not l.strip().startswith("#"))
    except Exception:
        return False


# ── Renderers ────────────────────────────────────────────────────────────────

def _fmt_ts(ts):
    if ts is None:
        return dim("—")
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M")
    return str(ts)


def _status_color(status):
    colors = {"done": green, "pending": yellow, "running": cyan, "failed": red}
    fn = colors.get(status, lambda x: x)
    return fn(status)


def render_summary(data):
    lines = []

    # 1. Status counts
    lines.append(section("Queue Status"))
    sc = data["status_counts"]
    parts = [f"  {_status_color(s)}: {c}" for s, c in sorted(sc.items())]
    total = sum(sc.values())
    lines.append("│ " + "  ".join(parts) + f"  total: {bold(str(total))}")

    # 2. Job type x status
    lines.append(section("Job Type Breakdown"))
    jts = data["job_type_status"]
    all_statuses = sorted({s for m in jts.values() for s in m})
    hdr = f"│ {'job_type':<28}" + "".join(f"{s:>9}" for s in all_statuses)
    lines.append(hdr)
    lines.append("│ " + "─" * (28 + 9 * len(all_statuses)))
    for jt in sorted(jts):
        vals = "".join(f"{jts[jt].get(s, 0):>9}" for s in all_statuses)
        lines.append(f"│ {jt:<28}{vals}")

    # 3. Done last 24h
    lines.append(section("Done (last 24h)"))
    d24 = data["done_24h"]
    if d24:
        for jt, cnt in d24.items():
            lines.append(f"│  {jt:<30} {green(str(cnt))}")
    else:
        lines.append("│  " + dim("none"))

    # 4. Failed jobs
    lines.append(section("Failed Jobs (latest 10)"))
    fj = data["failed_jobs"]
    if fj:
        for j in fj:
            err = (j["last_error"] or "")[:80]
            sym = j["symbol"] or "—"
            lines.append(f"│  #{j['id']} {j['job_type']:<26} {sym:<8} att={j['attempt_count']}  {red(err)}")
    else:
        lines.append("│  " + green("no failures"))

    # 5. Pending priority
    lines.append(section("Pending High-Priority"))
    pp = data["pending_priority"]
    if pp:
        lines.append("│  " + "  ".join(f"{t}: {bold(str(c))}" for t, c in pp.items()))
    else:
        lines.append("│  " + dim("none"))

    # 6. Oldest pending
    lines.append(section(f"Oldest Pending ({len(data['oldest_pending'])})"))
    for j in data["oldest_pending"]:
        sym = j["symbol"] or "—"
        lines.append(f"│  #{j['id']}  {j['job_type']:<26} {sym:<8} {j['priority_tier']}/{j['priority_score']}  queued {_fmt_ts(j['queued_at'])}")

    # 7. Latest run
    lines.append(section("Latest Run (24h window)"))
    lr = data["latest_run"]
    if lr and lr.get("run_start"):
        lines.append(f"│  start: {_fmt_ts(lr['run_start'])}  end: {_fmt_ts(lr['run_end'])}")
        lines.append(f"│  done: {green(str(lr['done']))}  failed: {red(str(lr['failed']))}")
    else:
        lines.append("│  " + dim("no run in last 24h"))

    # 8. Risk synthesis
    lines.append(section("Risk Synthesis"))
    rs = data["risk_synthesis"]
    if rs:
        lines.append(f"│  generated: {_fmt_ts(rs['generated_at'])}  value: ${rs['portfolio_value'] or '?':>10}")
        lines.append(f"│  brief_ready: {green('yes') if rs['morning_brief_ready'] else red('no')}")
        narr = (rs["narrative"] or "")[:120]
        if narr:
            lines.append(f"│  {dim(narr)}")
    else:
        lines.append("│  " + dim("none"))

    # 9. Recovery watch verdicts
    lines.append(section("Recovery Watch Verdicts"))
    rv = data["recovery_verdicts"]
    if rv:
        for v in rv[:5]:
            verdict = v["reentry_verdict"] or "—"
            color = green if verdict in ("ready", "reenter") else yellow if verdict == "watch" else dim
            lines.append(f"│  {v['symbol']:<8} {color(verdict):<16} {_fmt_ts(v['created_at'])}")
    else:
        lines.append("│  " + dim("none"))

    # 10. Journal/closed-trade reviews
    lines.append(section("Journal & Trade Reviews (24h)"))
    jrc = data["journal_review_counts"]
    if jrc:
        for jt, cnt in jrc.items():
            lines.append(f"│  {jt:<30} {cnt}")
    else:
        lines.append("│  " + dim("none"))

    # 11. RAG curation
    lines.append(section("RAG Curation Verdicts (24h)"))
    rag = data["rag_verdicts"]
    if rag:
        lines.append("│  " + "  ".join(f"{v}: {c}" for v, c in rag.items()))
    else:
        lines.append("│  " + dim("none"))

    # 12. Ollama status
    lines.append(section("Ollama Model Status"))
    om = data["ollama_models"]
    if om.get("error"):
        lines.append(f"│  {red(om['error'])}")
    else:
        q = green("RESIDENT") if om["qwen3_14b"] else red("NOT LOADED")
        n = green("RESIDENT") if om["nomic_embed"] else red("NOT LOADED")
        lines.append(f"│  qwen3:14b       {q}")
        lines.append(f"│  nomic-embed-text {n}")
        if om["raw"]:
            lines.append(f"│  loaded: {', '.join(om['raw'])}")

    # 13. Lock file
    lines.append(section("Lock / Scheduling"))
    lf = data["lock_exists"]
    lines.append(f"│  window lock:  {green('ACTIVE') if lf else dim('inactive')}")
    cs = data["cron_scheduled"]
    lines.append(f"│  cron entry:   {green('FOUND') if cs else yellow('NOT FOUND')}")

    lines.append(bold("└" + "─" * 63))
    print("\n".join(lines))


def render_json(data):
    """JSON-safe output."""
    def default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)
    print(json.dumps(data, indent=2, default=default))


def render_verbose(data):
    """Verbose = summary + full error text + all pending."""
    render_summary(data)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Deep overnight LLM queue status reporter")
    ap.add_argument("--summary", action="store_true", default=True, help="Compact overview (default)")
    ap.add_argument("--verbose", action="store_true", help="Detailed output")
    ap.add_argument("--json", action="store_true", dest="json_out", help="JSON to stdout")
    ap.add_argument("--today", action="store_true", help="Show only today's activity")
    ap.add_argument("--pending-top", type=int, default=0, metavar="N", help="Show top N pending jobs")
    args = ap.parse_args()

    data = collect(args)

    if args.json_out:
        render_json(data)
    elif args.verbose:
        render_verbose(data)
    else:
        render_summary(data)


if __name__ == "__main__":
    main()
