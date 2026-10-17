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

Modes (2026-10-15 split, n8n fabric process hermes-learning step autonomous_self_tune):

  --learn          auto-graft ONLY (non-destructive: SELECTs, the weights yaml + its archive, one audit INSERT).
                   self_purge is never called, and the purge helpers refuse to run while it is the mode
                   (LearnOnlyViolation): a learn run cannot DELETE, UPDATE a queue or archive-purge a table.
                   It was the half the fabric shadow lane ran until the 2026-10-17 tune cutover.
  --purge          self-purge ONLY (destructive retention: archived DELETEs + queue UPDATEs).
  neither / both   both legs, auto-graft first — the historical behaviour, unchanged (the cron step runs
                   ``--apply`` with neither flag). Since the 2026-10-17 tune cutover (operator directive 2026-10-15,
                   F41 retention approved for n8n) the fabric lane runs exactly this argv too: when n8n owns the
                   effect key the cron step is skipped, so the lane must carry BOTH legs or the purge would stop.
  A real ``--apply`` run writes LaneRunReceipt@v2 (``lane_output``: produced_count = grafts applied + retention
  rows acted on; zero = ``nothing_due`` / ``no_new_input``) for the n8n output verdict. A dry run writes none.
  --apply          write; without it every leg previews (the purge leg counts what it would delete).
  --dry-run        preview that wins over --apply: read-only DB session, no CREATE TABLE, no file write.
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


class LearnOnlyViolation(RuntimeError):
    """A purge helper was reached while the run is --learn only (the non-destructive half)."""


#: Set by main() for a --learn-only run. The purge helpers refuse while it is True (defence in depth: main never
#: calls self_purge in that mode, so this only fires if a future edit routes a purge into the learn leg).
_LEARN_ONLY = False


def _refuse_if_learn_only(label: str) -> None:
    if _LEARN_ONLY:
        raise LearnOnlyViolation(f"purge step {label!r} refused: this run is --learn only (non-destructive)")


def _audit_table_present(cur) -> bool:
    cur.execute("SELECT to_regclass('hermes_autotune_audit')")
    row = cur.fetchone()
    return bool(row and row[0])


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


def auto_graft_weights(cur, apply: bool, *, audit_present: bool = True) -> dict:
    """Graft outcome-gated calibration suggestions into the live weights yaml — clamped.

    ``audit_present`` False (a dry run on a database that never had the audit table): the weekly drift reads 0
    instead of querying a table the read-only session may not create."""
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
    if audit_present:
        cur.execute("""SELECT COALESCE(SUM((c->>'to')::numeric - (c->>'from')::numeric), 0),
                              COALESCE(SUM(ABS((c->>'to')::numeric - (c->>'from')::numeric)), 0)
                       FROM hermes_autotune_audit, jsonb_array_elements(detail->'changes') c
                       WHERE action='auto_graft_weights_outcome' AND run_at > NOW() - interval '7 days'""")
        _net, drift_7d = cur.fetchone()
    else:
        _net, drift_7d = 0, 0
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
    _refuse_if_learn_only(label)
    if not apply:
        if not count_sql:
            return -1  # not previewed
        cur.execute(count_sql, params)
        r = cur.fetchone()
        return int(r[0]) if r else 0
    cur.execute(sql, params)
    return cur.rowcount


def _archived_purge(cur, label: str, table: str, where_sql: str, params=(), apply: bool = True) -> int:
    """2026-10-11 (retention-all-managed): archive + manifest + tripwire before the DELETE
    (lib.retention_archive.managed_purge); a dry run counts. ``where_sql`` uses alias ``t``."""
    _refuse_if_learn_only(label)
    try:
        from lib.retention_archive import managed_purge
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from lib.retention_archive import managed_purge
    r = managed_purge(cur.connection, table=table, where_sql=where_sql, params=params,
                      label=f"self_tune_{label}", writer="hermes_autonomous_self_tune", apply=apply)
    return r["deleted"] if apply else r["eligible"]


def self_purge(cur, apply: bool) -> dict:
    _refuse_if_learn_only("self_purge")
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
    dr = _archived_purge(cur, "embed_drop", "hermes_embedding_queue",
              "t.embedding_status='failed' AND t.created_at < NOW() - (%s||' days')::interval",
              (EMBED_DROP_DAYS,), apply)
    out["embeddings_requeued"], out["embeddings_dropped"] = rq, dr
    # 3. aged rows
    out["score_history_purged"] = _archived_purge(cur, "score_hist", "hermes_score_history",
        "t.scored_at < NOW() - (%s||' days')::interval", (SCORE_HISTORY_DAYS,), apply)
    out["research_purged"] = _archived_purge(cur, "research", "hermes_research_intelligence",
        "t.created_at < NOW() - (%s||' days')::interval AND t.status IN ('rejected','superseded','expired')",
        (RESEARCH_DAYS,), apply)
    out["external_purged"] = _archived_purge(cur, "external", "hermes_external_research",
        "t.created_at < NOW() - (%s||' days')::interval", (EXTERNAL_DAYS,), apply)
    # 4. dead legacy tables -- 2026-10-11: archived DELETE of every row instead of TRUNCATE (rule 6); the
    #    tables held 0 rows when measured, so this is the same no-op until something writes to them again.
    out["dead_tables_truncated"] = []
    for t in DEAD_TABLES:
        try:
            cur.execute("SELECT to_regclass(%s)", (t,))
            if cur.fetchone()[0] is None:
                out.setdefault("dead_table_errors", []).append(f"{t}: absent")
                continue
            n = _archived_purge(cur, "dead_table", t, "TRUE", (), apply)
            out["dead_tables_truncated"].append(t)
            # 2026-10-17 (tune cutover): the rows each dead-table purge removed (dry: would remove), so the lane
            # receipt's produced_count counts real retention work, not the table names (always three).
            out["dead_table_rows_purged"] = out.get("dead_table_rows_purged", 0) + max(int(n or 0), 0)
        except Exception as e:
            cur.connection.rollback()
            out.setdefault("dead_table_errors", []).append(f"{t}: {str(e)[:60]}")
    if apply:
        _audit(cur, "self_purge", out, sum(v for v in out.values() if isinstance(v, int)))
    return out


# ───────────────────── lane receipt (n8n output verdict) ─────────────────────
#: Lane id of this step on the n8n fabric (config/n8n_run_allowlist.json; health contract expected_output).
LANE_ID = "hermes-learning-autonomous-self-tune"
#: self_purge integer counters that are rows acted on (UPDATE / archived DELETE rowcounts; -1 = not previewed).
PURGE_ROW_KEYS = ("advisory_pending_expired", "embeddings_requeued", "embeddings_dropped", "score_history_purged",
                  "research_purged", "external_purged", "dead_table_rows_purged")
#: auto_graft statuses that mean "nothing was due this run" (a gate held, or no weight moved): a verified empty.
GRAFT_NOTHING_DUE = ("gated_persistence", "gated_weekly_drift_cap", "no_change")


def lane_output(result: dict) -> dict:
    """LaneRunReceipt@v2 output fields for one REAL --apply run (2026-10-17, tune cutover to n8n).

    produced_count = factor-weight grafts applied (auto_graft status ``applied``: len(changes)) + retention rows the
    purge acted on (the PURGE_ROW_KEYS rowcounts). Both legs audit into hermes_autotune_audit. Zero is a VERIFIED
    empty, not a failure: the graft is outcome-gated and drift-capped by design and most days nothing is past
    retention. empty_reason ``no_new_input`` when there were no outcome suggestions at all, else ``nothing_due`` (a
    gate held or no weight moved, and no row was due). Gate outcomes and dead-table errors are recorded as non-fatal
    skipped_reasons, so the receipt says WHY it was empty."""
    graft = result.get("auto_graft") or {}
    purge = result.get("self_purge") or {}
    grafted = len(graft.get("changes") or []) if graft.get("status") == "applied" else 0
    purged = sum(max(purge[k], 0) for k in PURGE_ROW_KEYS
                 if isinstance(purge.get(k), int) and not isinstance(purge.get(k), bool))
    produced = grafted + purged
    skipped: dict[str, int] = {}
    if graft.get("status") in GRAFT_NOTHING_DUE:
        skipped[f"graft_{graft['status']}"] = 1
    if purge.get("dead_table_errors"):
        skipped["dead_table_error"] = len(purge["dead_table_errors"])
    empty = None
    if not produced:
        empty = "no_new_input" if graft.get("status") == "no_outcome_suggestions" else "nothing_due"
    return {"produced_count": produced, "attempted_count": produced, "skipped_reasons": skipped,
            "empty_reason": empty,
            "output_evidence": [{"kind": "store_rows", "ref": "hermes_autotune_audit",
                                 "grafted": grafted, "purged_rows": purged}]}


def _write_receipt(ok: bool, started: str, *, result: dict | None = None, error: str | None = None) -> None:
    """Best-effort LaneRunReceipt@v2. Never raises; called for a real --apply run only, never a dry run (§6)."""
    try:
        try:
            from lib.lane_last_receipt import write_lane_receipt
        except ImportError:
            from scripts.lib.lane_last_receipt import write_lane_receipt
        res = result or {}
        out = lane_output(res) if ok else {
            "produced_count": 0, "attempted_count": 0, "skipped_reasons": {"dependency_unavailable": 1}}
        write_lane_receipt(LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=started,
                           script="hermes_autonomous_self_tune.py", error=error,
                           summary={"auto_graft": (res.get("auto_graft") or {}).get("status"),
                                    "self_purge_ran": "self_purge" in res},
                           output=out)
    except Exception as exc:  # noqa: BLE001 - the run's own result comes first
        print(f"  WARN lane receipt not written: {type(exc).__name__}: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    global _LEARN_ONLY
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually write (default dry-run)")
    ap.add_argument("--learn", action="store_true",
                    help="run auto-graft only (non-destructive; the purge helpers refuse in this mode)")
    ap.add_argument("--purge", action="store_true", help="run self-purge only (destructive retention; host cron)")
    ap.add_argument("--dry-run", action="store_true",
                    help="preview that wins over --apply: read-only DB session, no DDL, no file write")
    a = ap.parse_args(argv)
    do_learn = a.learn or not a.purge
    do_purge = a.purge or not a.learn
    _LEARN_ONLY = do_learn and not do_purge
    started = datetime.now(timezone.utc).isoformat()
    try:
        conn = _conn()
    except Exception as exc:
        if a.apply and not a.dry_run:
            _write_receipt(False, started, error=type(exc).__name__)
        raise
    if a.dry_run:
        from lib.lane_last_receipt import enforce_readonly
        enforce_readonly(conn)  # dry run: the server refuses any write (AGENTS.md §6)
        cur = conn.cursor()
        audit_present = _audit_table_present(cur)
        result = {"apply": False, "mode": "dry_run", "ts": datetime.now(timezone.utc).isoformat()}
        if do_learn:
            result["auto_graft"] = auto_graft_weights(cur, False, audit_present=audit_present)
        if do_purge:
            result["self_purge"] = self_purge(cur, False)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return 0
    result = {"apply": a.apply, "ts": started}
    try:
        cur = conn.cursor()
        _ensure_audit(cur)
        if do_learn:
            result["auto_graft"] = auto_graft_weights(cur, a.apply)
        if do_purge:
            result["self_purge"] = self_purge(cur, a.apply)
        if a.apply:
            conn.commit()
    except Exception as exc:
        # 2026-10-17 (tune cutover): a real run that raised leaves a failed v2 receipt (dependency_unavailable), so
        # the n8n output verdict never reads a stale success; the exception still propagates (rc != 0).
        if a.apply:
            _write_receipt(False, started, error=type(exc).__name__)
        raise
    finally:
        conn.close()
    if a.apply:
        _write_receipt(True, started, result=result)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
