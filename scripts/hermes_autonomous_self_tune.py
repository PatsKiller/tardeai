#!/usr/bin/env python3
"""hermes_autonomous_self_tune.py — Hermes self-learning + self-purging, NO HUMAN TOUCH.

Operator chose full autonomy (minimal gates, audit-only). This closes the two open legs:

  SELF-LEARNING (auto-graft): take the latest H-4 calibration suggestions from hermes_weight_calibration
  and write them straight into config/hermes_score_weights.yaml (the live factor weights the scorer
  reads). Previously the operator hand-grafted these. Now automatic, every run, audited.

  SELF-PURGE: prune stale pipeline state so cruft can't accumulate (the class of failure that left a
  queue jammed 2 weeks and 653 embeddings failed) — stale queues, failed embeddings, aged
  score/research rows, and dead legacy tables.

Advisory layer only — Hermes scoring feeds watchlist RANKING, not live execution (which is separately
gated). Every action is logged to hermes_autotune_audit + stdout. Env-configurable retention.
Kill anytime by removing the cron (no separate kill-switch, per operator choice).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
WEIGHTS_FILE = PROJECT_ROOT / "config" / "hermes_score_weights.yaml"

# Each graft is archived before the live file is rewritten.
#
# WHY: cio_release_manifest classifies this file "runtime_state_with_release_seed" —
# the tracked copy is a SEED, the live weights are runtime state learned from the
# outcome ledger. Nothing enforced that classification, so the file stayed an
# ordinary tracked config that `git checkout` silently reverts to the seed. On
# 2026-09-06 a routine fast-forward of the executing tree did exactly that, and only
# an out-of-band backup preserved v11 — nine grafts of learning.
#
# skip-worktree on the executing clone stops the clobber, but it is invisible local
# state that any fresh clone or `--no-skip-worktree` drops. This archive is the
# durable half: a lost graft can always be recovered from here. It lives under
# data/runtime, which is gitignored, so it survives the checkout that causes the
# problem in the first place.
GRAFT_ARCHIVE_DIR = Path(
    os.getenv("HERMES_WEIGHT_GRAFT_ARCHIVE",
              str(PROJECT_ROOT / "data" / "runtime" / "weight_grafts"))
)


def _archive_graft(doc: dict):
    """Write the about-to-be-applied weights beside every prior graft.

    Best-effort by design: failing to archive must not block the graft, but it is
    reported rather than swallowed — a silent archive failure would leave the
    recovery path looking healthy while holding nothing.
    """
    import yaml

    try:
        GRAFT_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = GRAFT_ARCHIVE_DIR / f"hermes_score_weights.v{doc.get('version')}.{stamp}.yaml"
        dest.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
        return dest
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        print(f"  WARN could not archive graft: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None

# retention windows (days) — env override
SCORE_HISTORY_DAYS = int(os.getenv("HERMES_SCORE_HISTORY_RETENTION_DAYS", "30"))
RESEARCH_DAYS = int(os.getenv("HERMES_RESEARCH_RETENTION_DAYS", "180"))
EXTERNAL_DAYS = int(os.getenv("HERMES_EXTERNAL_RETENTION_DAYS", "180"))
EMBED_DROP_DAYS = int(os.getenv("HERMES_EMBED_DROP_DAYS", "7"))
QUEUE_STALE_DAYS = int(os.getenv("HERMES_QUEUE_STALE_DAYS", "7"))
DEAD_TABLES = [t.strip() for t in os.getenv(
    "HERMES_DEAD_TABLES", "watchlist_research_results,watchlist_research_queue,proposal_research_packets",
).split(",") if t.strip()]


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _ensure_audit(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS hermes_autotune_audit (
        id BIGSERIAL PRIMARY KEY, run_at TIMESTAMPTZ DEFAULT NOW(),
        action TEXT, detail JSONB, rows_affected INT)""")


def _audit(cur, action: str, detail: dict, rows: int = 0):
    cur.execute("INSERT INTO hermes_autotune_audit (action, detail, rows_affected) VALUES (%s,%s::jsonb,%s)",
                (action, json.dumps(detail, default=str), rows))


# ───────────────────── self-learning: auto-graft weights ─────────────────────
# Phase 3 (2026-07-02): the drift-fed multiplicative ratchet is FROZEN. Grafts now come only
# from OUTCOME_LEDGER-tagged suggestions (hermes_outcome_learning.py — graded 20-session
# outcomes + realized R), require graft-eligible days over a persistence window, are
# additively clamped per step, and respect a weekly total-drift cap. Audit trail unchanged.
GRAFT_MAX_STEP = float(os.getenv("HERMES_GRAFT_MAX_STEP", "0.02"))
GRAFT_WEEKLY_DRIFT_CAP = float(os.getenv("HERMES_GRAFT_WEEKLY_DRIFT_CAP", "0.10"))
GRAFT_ELIGIBLE_DAYS = int(os.getenv("HERMES_GRAFT_ELIGIBLE_DAYS", "5"))
GRAFT_ELIGIBLE_WINDOW_DAYS = int(os.getenv("HERMES_GRAFT_ELIGIBLE_WINDOW_DAYS", "14"))


def auto_graft_weights(cur, apply: bool) -> dict:
    """Graft outcome-gated calibration suggestions into the live weights yaml — clamped."""
    import yaml
    # persistence gate: eligible outcome suggestions on >= N distinct days in the window
    cur.execute("""SELECT count(DISTINCT created_at::date) FROM hermes_weight_calibration
                   WHERE rationale LIKE 'OUTCOME_LEDGER|eligible=1%%'
                     AND created_at > NOW() - make_interval(days => %s)""",
                (GRAFT_ELIGIBLE_WINDOW_DAYS,))
    eligible_days = cur.fetchone()[0] or 0
    if eligible_days < GRAFT_ELIGIBLE_DAYS:
        return {"status": "gated_persistence",
                "eligible_days": eligible_days, "required": GRAFT_ELIGIBLE_DAYS,
                "note": "drift-ratchet frozen; grafts require sustained outcome-eligible suggestions"}
    # weekly drift cap from the audit trail
    cur.execute("""SELECT COALESCE(SUM((c->>'to')::numeric - (c->>'from')::numeric), 0),
                          COALESCE(SUM(ABS((c->>'to')::numeric - (c->>'from')::numeric)), 0)
                   FROM hermes_autotune_audit, jsonb_array_elements(detail->'changes') c
                   WHERE action='auto_graft_weights_outcome' AND run_at > NOW() - interval '7 days'""")
    _net, drift_7d = cur.fetchone()
    if float(drift_7d or 0) >= GRAFT_WEEKLY_DRIFT_CAP:
        return {"status": "gated_weekly_drift_cap", "drift_7d": float(drift_7d),
                "cap": GRAFT_WEEKLY_DRIFT_CAP}
    cur.execute("""SELECT DISTINCT ON (factor) factor, suggested_weight, predictiveness
                   FROM hermes_weight_calibration
                   WHERE rationale LIKE 'OUTCOME_LEDGER|eligible=1%%'
                   ORDER BY factor, id DESC""")
    rows = cur.fetchall()
    if not rows:
        return {"status": "no_outcome_suggestions"}
    doc = yaml.safe_load(WEIGHTS_FILE.read_text()) or {}
    cur_w = dict(doc.get("weights") or {})
    new_w = dict(cur_w)
    changes = []
    for factor, sug, pred in rows:
        if factor not in new_w or sug is None:
            continue
        # additive clamp — never move a weight more than GRAFT_MAX_STEP per graft
        delta = max(-GRAFT_MAX_STEP, min(GRAFT_MAX_STEP, float(sug) - float(new_w[factor])))
        if abs(delta) <= 1e-4:
            continue
        changes.append({"factor": factor, "from": round(float(new_w[factor]), 4),
                        "to": round(float(new_w[factor]) + delta, 4),
                        "predictiveness": float(pred) if pred is not None else None})
        new_w[factor] = float(new_w[factor]) + delta
    if not changes:
        return {"status": "no_change", "eligible_days": eligible_days}
    tot = sum(new_w.values()) or 1.0
    new_w = {k: round(v / tot, 4) for k, v in new_w.items()}
    if apply:
        doc["weights"] = new_w
        doc["version"] = int(doc.get("version") or 1) + 1
        doc["auto_grafted_at"] = datetime.now(timezone.utc).isoformat()
        doc["graft_source"] = "outcome_ledger"
        archived = _archive_graft(doc)
        WEIGHTS_FILE.write_text(yaml.safe_dump(doc, sort_keys=False))
        if archived:
            print(f"  graft archived -> {archived}")
        _audit(cur, "auto_graft_weights_outcome",
               {"changes": changes, "new_weights": new_w, "eligible_days": eligible_days,
                "drift_7d_before": float(drift_7d or 0)}, len(changes))
    return {"status": "applied" if apply else "dry", "changes": changes,
            "eligible_days": eligible_days}


# ───────────────────── self-purge ─────────────────────
def _purge(cur, label: str, sql: str, params=(), apply: bool = True, count_sql: str | None = None) -> int:
    """Execute a purge (UPDATE/DELETE). In dry mode run count_sql (the matching SELECT) instead."""
    if not apply:
        if not count_sql:
            return -1  # not previewed
        cur.execute(count_sql, params)
        r = cur.fetchone()
        return int(r[0]) if r else 0
    cur.execute(sql, params)
    return cur.rowcount


def self_purge(cur, apply: bool) -> dict:
    out = {}
    # 1. jammed/stale queues
    n = _purge(cur, "advisory_queue", """UPDATE hermes_advisory_events SET event_status='skipped',
              processed_at=NOW(), error_message='auto-purged stale pending'
              WHERE event_status='pending' AND created_at < NOW() - (%s||' days')::interval""",
              (QUEUE_STALE_DAYS,), apply)
    out["advisory_pending_expired"] = n
    # 2. failed embeddings → re-queue recent, drop old
    rq = _purge(cur, "embed_requeue", """UPDATE hermes_embedding_queue SET embedding_status='pending'
              WHERE embedding_status='failed' AND created_at >= NOW() - (%s||' days')::interval""",
              (EMBED_DROP_DAYS,), apply)
    dr = _purge(cur, "embed_drop", """DELETE FROM hermes_embedding_queue
              WHERE embedding_status='failed' AND created_at < NOW() - (%s||' days')::interval""",
              (EMBED_DROP_DAYS,), apply)
    out["embeddings_requeued"], out["embeddings_dropped"] = rq, dr
    # 3. aged rows
    out["score_history_purged"] = _purge(cur, "score_hist",
        "DELETE FROM hermes_score_history WHERE scored_at < NOW() - (%s||' days')::interval", (SCORE_HISTORY_DAYS,), apply)
    out["research_purged"] = _purge(cur, "research",
        "DELETE FROM hermes_research_intelligence WHERE created_at < NOW() - (%s||' days')::interval AND status IN ('rejected','superseded','expired')",
        (RESEARCH_DAYS,), apply)
    out["external_purged"] = _purge(cur, "external",
        "DELETE FROM hermes_external_research WHERE created_at < NOW() - (%s||' days')::interval", (EXTERNAL_DAYS,), apply)
    # 4. dead legacy tables
    out["dead_tables_truncated"] = []
    for t in DEAD_TABLES:
        try:
            if apply:
                cur.execute(f"TRUNCATE TABLE {t}")
            out["dead_tables_truncated"].append(t)
        except Exception as e:
            out.setdefault("dead_table_errors", []).append(f"{t}: {str(e)[:60]}")
    if apply:
        _audit(cur, "self_purge", out, sum(v for v in out.values() if isinstance(v, int)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually write (default dry-run)")
    ap.add_argument("--learn", action="store_true", help="run auto-graft only")
    ap.add_argument("--purge", action="store_true", help="run self-purge only")
    a = ap.parse_args()
    do_learn = a.learn or not a.purge
    do_purge = a.purge or not a.learn
    conn = _conn(); cur = conn.cursor()
    _ensure_audit(cur)
    result = {"apply": a.apply, "ts": datetime.now(timezone.utc).isoformat()}
    if do_learn:
        result["auto_graft"] = auto_graft_weights(cur, a.apply)
    if do_purge:
        result["self_purge"] = self_purge(cur, a.apply)
    if a.apply:
        conn.commit()
    conn.close()
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
