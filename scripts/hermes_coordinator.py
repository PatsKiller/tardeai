#!/usr/bin/env python3
"""Chief Hermes Coordinator — orchestrates the full Hermes agent fleet.

OPERATOR DIRECTIVE B (2026-06-02, "Option B"): runs all agents LIVE (--apply), including
auto-promote and RAG embedding into the shared intelligence layer. 
Kill switch (data/runtime/HERMES_DISABLED) is still checked every tick.

This is the explicit "challenger wall open" mode. All promotions are logged to
hermes_promotion_audit with rollback_sql. Embeddings are reversible by deleting rows.
See docs/hermes/HERMES_AGENT_CONTRACTS_AND_PERMISSIONS.md for full contract.

Scheduled 24/7 via cron (every 15 min), flock-guarded. Runs the research curator every
tick for conscious signal mining + curation; per-tick caps keep it bounded; kill switch
halts the next tick.
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
CAP_BACKLOG_DRAIN = 2
CAP_SOURCE_AUTO = 8
# 24/7 research curator — always-on conscious curation (deep synthesis also on think_tank cron)
CAP_AUTONOMOUS_PROMOTE = 5  # Phase 1 autonomous discovery governance — curator promotes inside rails
CAP_PROMOTE = 10        # ungated by confidence (operator directive B); capped per tick for sanity
CAP_EMBED = 15
CAP_EMBED_RESET_FAILED = 20


def kill_switch_active():
    """Canonical kill-switch (data/runtime/HERMES_DISABLED) + coordinator-only COORDINATOR_DISABLED.
    The retired sidecar .hermes/DISABLED path is never consulted (see hermes_killswitch)."""
    from hermes_killswitch import is_hermes_disabled
    _active, path = is_hermes_disabled(extra=[COORD_EXTRA])
    return path or None


def run_script(label, args, timeout=600):
    """Invoke an agent script as a subprocess; isolate failures."""
    try:
        r = subprocess.run(
            [PY] + args,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
        ok = r.returncode == 0
        tail = (r.stdout or r.stderr or "").strip().splitlines()[-1:] or [""]
        log.info("  %s: %s — %s", label, "ok" if ok else f"exit {r.returncode}", tail[0][:120])
        return {"agent": label, "ok": ok, "exit": r.returncode}
    except Exception as e:
        log.warning("  %s: FAILED %s", label, e)
        return {"agent": label, "ok": False, "error": str(e)[:120]}


def auto_promote(conn):
    """Ungated auto-promote of staged research (operator directive B). Audited + reversible.
    Includes basic backpressure: if embedding queue is heavily backlogged, reduce promotions
    this tick to avoid worsening the RAG gap.
    """
    from hermes_embedding_enqueue import enqueue_research
    cur = conn.cursor()

    # Backpressure: query pending embeds
    cur.execute("SELECT count(*) FROM hermes_embedding_queue WHERE embedding_status='pending'")
    pending = cur.fetchone()[0] or 0
    effective_cap = CAP_PROMOTE
    if pending > 150:
        effective_cap = max(3, CAP_PROMOTE // 2)
    elif pending > 80:
        effective_cap = max(5, CAP_PROMOTE - 4)

    # Phase 3 (2026-07-02): learned per-type confidence gate from graded promotion outcomes
    # (hermes_promotion_thresholds, written nightly by hermes_outcome_learning.py). Types with
    # no measured row keep the ungated directive-B behavior (threshold defaults to 0).
    cur.execute("""SELECT id, symbol, research_type, confidence_score FROM hermes_research_intelligence hri
                   WHERE status='staged'
                     AND COALESCE(confidence_score, 0) >= COALESCE(
                           (SELECT t.min_confidence FROM hermes_promotion_thresholds t
                            WHERE t.research_type = COALESCE(hri.research_type,'unknown')), 0)
                   ORDER BY confidence_score DESC NULLS LAST LIMIT %s""", (effective_cap,))
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
    throttled = effective_cap < CAP_PROMOTE
    log.info("  auto-promote: %d staged → promoted (cap=%d%s), %d enqueued for RAG (reversible via hermes_promotion_audit.rollback_sql)", promoted, effective_cap, " throttled" if throttled else "", enqueued)
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
    log.info("Coordinator tick START (LIVE / **DIRECTIVE B ACTIVE** — auto-promote + RAG on, kill switch off. See HERMES_AGENT_CONTRACTS_AND_PERMISSIONS.md)")
    agents = []
    # 1. Research generation (Source Discovery + Autonomous Research Manager via the autonomous loop)
    for loop in ("ticker_challenger", "pipeline_quality"):
        agents.append(run_script(f"autonomous:{loop}", ["scripts/hermes_autonomous_loop.py", "--loop", loop, "--apply", "--max-rows", str(CAP_AUTONOMOUS)]))
    # 2. Librarian v2 light scopes (Phase 3): freshness + retention every tick
    agents.append(run_script("librarian_light", ["scripts/hermes_librarian_agent.py", "--apply",
        "--scope", "freshness,retention", "--max-rows", "10"]))
    # 2b. Legacy backlog drain (moved into librarian v2 backlog scope — kept for transition)
    agents.append(run_script("backlog_drain", ["scripts/hermes_backlog_drain.py", "--apply", "--max-rows", str(CAP_BACKLOG_DRAIN)]))
    # 2b. Autonomous source vetting closure (no operator approval queue)
    agents.append(run_script("source_auto_approval", ["scripts/hermes_source_auto_approval.py", "--apply", "--max-actions", str(CAP_SOURCE_AUTO)]))
    # 2c. Autonomous discovery governance (Phase 1): curator promotes research-only inbox candidates inside rails
    agents.append(run_script("discovery_autonomy", ["scripts/hermes_discovery_autonomy.py", "--apply", "--limit", str(CAP_AUTONOMOUS_PROMOTE)]))
    agents.append(run_script("research_curator", ["scripts/hermes_research_curator.py", "--apply"], timeout=900))
    agents.append(run_script("options_research_bridge", ["scripts/options_research_bridge.py", "--apply"], timeout=300))
    # 3. Auto-promote (ungated) + backfill RAG gap + 4. embedding worker — isolated per step
    conn = psycopg2.connect(**DB)
    promoted = 0
    backfilled = 0
    try:
        promoted = auto_promote(conn)
    except Exception as e:
        conn.rollback(); log.warning("auto-promote failed (rolled back): %s", e)
    try:
        from hermes_embedding_enqueue import backfill_promoted
        backfilled = backfill_promoted(conn, limit=30)
        if backfilled:
            log.info("  embed-backfill: enqueued %d promoted rows missing from RAG queue", backfilled)
    except Exception as e:
        conn.rollback(); log.warning("embed-backfill failed: %s", e)
    agents.append(run_script(
        "embedding_worker",
        ["scripts/hermes_embedding_worker.py", "--apply", "--limit", str(CAP_EMBED),
         "--retry-failed", "--reset-failed", str(CAP_EMBED_RESET_FAILED)],
    ))
    summary = {"ts": datetime.now(timezone.utc).isoformat(), "promoted": promoted,
               "embed_backfilled": backfilled, "agents": agents}
    try:
        log_plan(conn, summary)
    except Exception as e:
        conn.rollback(); log.warning("plan log failed: %s", e)
    conn.close()
    log.info("Coordinator tick DONE: %d promoted, %d agents run", promoted, len(agents))
    return 0


if __name__ == "__main__":
    sys.exit(main())
