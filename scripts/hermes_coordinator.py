#!/usr/bin/env python3
"""Chief Hermes Coordinator — orchestrates the full Hermes agent fleet.

OPERATOR DIRECTIVE 2026-06-02 (Option B): runs all agents LIVE (--apply), including
auto-promote and RAG embedding. Kill switch left un-tripped (off) but STILL CHECKED
each run, so `touch data/runtime/HERMES_DISABLED` halts everything next tick.

WALL NOTE: this opens the challenger wall by operator directive — promoted research +
embeddings flow into the core intelligence/RAG the trading agents read. Every promote
and embed is audited + reversible (see rollback_sql / content_embeddings delete).

Scheduled continuously via cron (~every 15 min), flock-guarded. Per-tick caps keep it
bounded; the kill switch is the instant stop.
"""
import os
import sys
import json
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [hermes-coordinator] %(message)s")
log = logging.getLogger("hermes_coordinator")

PY = str(ROOT / ".venv" / "bin" / "python")
sys.path.insert(0, str(ROOT / "scripts"))
# Canonical kill-switch via the shared helper (Phase 214) — never the retired sidecar path.
# COORDINATOR_DISABLED is a coordinator-only extra stop file.
COORD_EXTRA = ROOT / "data" / "runtime" / "COORDINATOR_DISABLED"
DB = dict(host=os.getenv("DB_HOST", "127.0.0.1"), port=int(os.getenv("DB_PORT", "5432")),
          dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
          password=os.getenv("DB_PASSWORD", ""))

# Per-tick caps (continuous schedule → keep each tick small)
CAP_LIBRARIAN = 10
CAP_AUTONOMOUS = 3
CAP_PROMOTE = 10        # ungated by confidence (operator directive B); capped per tick for sanity
CAP_EMBED = 10


def kill_switch_active():
    """Canonical kill-switch (data/runtime/HERMES_DISABLED) + coordinator-only COORDINATOR_DISABLED.
    The retired sidecar .hermes/DISABLED path is never consulted (see hermes_killswitch)."""
    from hermes_killswitch import is_hermes_disabled
    _active, path = is_hermes_disabled(extra=[COORD_EXTRA])
    return path or None


def run_script(label, args, timeout=600):
    """Invoke an agent script as a subprocess; isolate failures."""
    try:
        # Route autonomous-loop LLM calls to gemma3:4b (~3x faster) so continuous ticks stay under the 15-min cron.
        env = {**os.environ, "HERMES_LOOP_MODEL": os.environ.get("HERMES_LOOP_MODEL", "gemma3:4b")}
        r = subprocess.run([PY] + args, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout, env=env)
        ok = r.returncode == 0
        tail = (r.stdout or r.stderr or "").strip().splitlines()[-1:] or [""]
        log.info("  %s: %s — %s", label, "ok" if ok else f"exit {r.returncode}", tail[0][:120])
        return {"agent": label, "ok": ok, "exit": r.returncode}
    except Exception as e:
        log.warning("  %s: FAILED %s", label, e)
        return {"agent": label, "ok": False, "error": str(e)[:120]}


def auto_promote(conn):
    """Ungated auto-promote of staged research (operator directive B). Audited + reversible."""
    from hermes_embedding_enqueue import enqueue_research
    cur = conn.cursor()
    cur.execute("""SELECT id, symbol, research_type, confidence_score FROM hermes_research_intelligence
                   WHERE status='staged' ORDER BY confidence_score DESC NULLS LAST LIMIT %s""", (CAP_PROMOTE,))
    rows = cur.fetchall()
    promoted = 0
    enqueued = 0
    for rid, sym, rtype, conf in rows:
        rollback = f"UPDATE hermes_research_intelligence SET status='staged' WHERE id={rid};"
        cur.execute("UPDATE hermes_research_intelligence SET status='promoted' WHERE id=%s", (rid,))
        cur.execute("""INSERT INTO hermes_promotion_audit
                       (promoted_at, source_table, source_id, target_table, target_id, promotion_type,
                        dry_run, approved_by, approved_at, rollback_sql, notes)
                       VALUES (NOW(),'hermes_research_intelligence',%s,'hermes_research_intelligence',%s,
                               'research_to_insight', false, 'coordinator_operator_directive', NOW(), %s, %s)""",
                    (rid, rid, rollback, f"Auto-promoted {sym or ''}/{rtype or ''} conf={conf} (ungated, directive B)"))
        if enqueue_research(cur, rid):
            enqueued += 1
        promoted += 1
    conn.commit()
    log.info("  auto-promote: %d staged → promoted, %d enqueued for RAG (reversible via hermes_promotion_audit.rollback_sql)", promoted, enqueued)
    return promoted


def log_plan(conn, summary):
    cur = conn.cursor()
    cur.execute("""INSERT INTO hermes_memory_events
                   (created_at, source, hermes_agent_name, event_type, topic, content, metadata_json, status)
                   VALUES (NOW(),'hermes','chief_hermes_coordinator','agent_state_change',
                           'Coordinator tick', %s, %s, 'active')""",
                (f"Ran fleet live: {summary.get('promoted',0)} promoted, agents={[s['agent'] for s in summary.get('agents',[])]}",
                 json.dumps(summary)))
    conn.commit()


def main():
    ks = kill_switch_active()
    if ks:
        log.warning("KILL SWITCH ACTIVE (%s) — coordinator halted, no agents run.", ks)
        return 0
    log.info("Coordinator tick START (LIVE / directive B — auto-promote + RAG on, kill switch off)")
    agents = []
    # 1. Research generation (Source Discovery + Autonomous Research Manager via the autonomous loop)
    for loop in ("ticker_challenger", "pipeline_quality"):
        agents.append(run_script(f"autonomous:{loop}", ["scripts/hermes_autonomous_loop.py", "--loop", loop, "--apply", "--max-rows", str(CAP_AUTONOMOUS)]))
    # 2. Librarian + Backlog manager
    agents.append(run_script("librarian_backlog", ["scripts/hermes_autonomous_librarian_backlog_loop.py", "--apply", "--max-rows", str(CAP_LIBRARIAN)]))
    # 3. Auto-promote (ungated) + 4. RAG embedding worker — each isolated so one failure won't abort the tick
    conn = psycopg2.connect(**DB)
    promoted = 0
    try:
        promoted = auto_promote(conn)
    except Exception as e:
        conn.rollback(); log.warning("auto-promote failed (rolled back): %s", e)
    agents.append(run_script("embedding_worker", ["scripts/hermes_embedding_worker.py", "--apply", "--limit", str(CAP_EMBED)]))
    summary = {"ts": datetime.now(timezone.utc).isoformat(), "promoted": promoted, "agents": agents}
    try:
        log_plan(conn, summary)
    except Exception as e:
        conn.rollback(); log.warning("plan log failed: %s", e)
    conn.close()
    log.info("Coordinator tick DONE: %d promoted, %d agents run", promoted, len(agents))
    return 0


if __name__ == "__main__":
    sys.exit(main())
