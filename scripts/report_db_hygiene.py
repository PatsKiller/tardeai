#!/usr/bin/env python3
"""report_db_hygiene.py — nightly measurement that keeps the trim from being one-time.

Reads the live database (read-only) and the retention registry, writes
`data/runtime/db_hygiene_last.json` (DbHygieneReport@v1) with findings the incident fan-in
turns into open incidents until they are fixed:

  UNCOVERED_TABLE      a public table >= min_table_mb (default 20) with no registry row
  DUPLICATE_INDEX      an exact-duplicate index pair exists (the trim removed 26 on 2026-10-07)
  BACKUP_NAMED_TABLE   a bak_/_bak_/_backup_/_legacy table exists
  SIZE_BUDGET          pg_database_size exceeds size_budget_gb
  TABLE_BUDGET         a table exceeds its table_budget_mb
  STALE_WINDOW         rows older than window_days + 2 remain that retention CAN delete (retention not
                       enforcing). Counted with the same single-column foreign-key guard db_retention.py
                       applies, so a row deliberately kept because a child row still references it
                       (fk_guard, db_retention.py) is not a finding; those are carried in ``stale_held``.
  DEAD_QUEUE           known queue tables with rows older than 30 d in terminal states
  RETENTION_SCHEDULERS a second scheduler for db_retention is installed (cron + timer)
  ARCHIVE_TRIPWIRE     (P1) a live consumer (repo scripts/config, crontab, user systemd unit) names an
                       archived path under archive/db_retention or archive/db_trim (AGENTS.md §0 rule 6)
  ARCHIVE_MISSING      a TRIPWIRE.jsonl record names an archive file that is gone
  TRIPWIRE_UNREADABLE  a TRIPWIRE.jsonl line does not parse
                       (the last three: scripts/lib/retention_tripwire.py; files only, no DB)
  ARCHIVE_GROWTH       (P2) the retention archive (same disk as the DB) grew faster than the registry's
                       archive_growth_cap_gb_month over the last 30 d, holds more than archive_total_budget_gb,
                       or free disk is under 20 GB. Report only: no job deletes an archive (AGENTS.md §0
                       rule 6); an off-box copy is an operator decision (§17). The size/age table is in the
                       report as ``archive_usage`` (RetentionArchiveUsage@v1).

    python3 scripts/report_db_hygiene.py [--write] [--min-table-mb 20]

AUTHORITY: READ_ONLY_ADVISORY. SELECT only. Lane: db-hygiene-nightly.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
NO_CONSUMER_REASON = "consumed by scripts/n8n_incident_fanin.py (source db_hygiene) and the weekly report"
SCHEMA = "DbHygieneReport@v1"
BACKUP_NAME = re.compile(r"^(bak_|_bak_|_backup_|backup_|.*_bak_r\d+_\d{8}$|.*_backup_\d{8}.*|.*_legacy$)")
QUEUES = {"watch_decision_refresh_jobs": ("created_at", "stage NOT IN ('RUNNING','QUEUED')"),
          "inference_ensemble_jobs": ("created_at", "status = 'expired'"),
          "alert_digest_queue": ("created_at", "expires_at < now()")}


def env() -> dict:
    e = dict(os.environ)
    e.setdefault("PGHOST", e.get("DB_HOST", "127.0.0.1")); e.setdefault("PGUSER", e.get("DB_USER", "trade_ai"))
    e.setdefault("PGDATABASE", e.get("DB_NAME", "trade_ai"))
    if e.get("DB_PASSWORD"):
        e["PGPASSWORD"] = e["DB_PASSWORD"]
    e["PGOPTIONS"] = "-c statement_timeout=120s -c default_transaction_read_only=on"
    return e


def q(sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", "-X", "-q", "-tA", "-v", "ON_ERROR_STOP=1", "-c", sql], capture_output=True, text=True, env=env())
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])
    return [ln.split("|") for ln in r.stdout.splitlines() if ln]


def state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")


# --- STALE_WINDOW: count what retention can actually delete -----------------------------------------
# 2026-11-06: the reader counted every old row and called it "retention not enforcing", while the writer
# deliberately keeps a row whose child still references it (db_retention.fk_guard: "Expired rows nothing
# references are deleted; referenced rows wait until their children expire under their own policy"). On
# 2026-11-06 the two disagreed on every such table — decision_packets had 6,340 old rows and ZERO that
# retention could delete (every one was referenced by a blueprint, run, contradiction or successor), and
# aegis_steph_escalations reported the 3 rows its resolution history holds on purpose. A nightly P2 that
# says a policy is not enforced when it is enforcing exactly as designed is noise that hides the real one.
IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
#: One row per foreign key: referenced table, child table (schema-qualified, quoted), child column, parent
#: column. Single-column keys only — the shape db_retention.fk_guard() handles; a composite key is left to
#: the writer's own loud error, never guessed at here.
_FK_ROWS_SQL = """
SELECT pa.relname,
       format('%I.%I', n.nspname, ch.relname),
       quote_ident(a.attname),
       quote_ident(af.attname)
  FROM pg_constraint c
  JOIN pg_class ch ON ch.oid = c.conrelid
  JOIN pg_class pa ON pa.oid = c.confrelid
  JOIN pg_namespace n ON n.oid = ch.relnamespace
  JOIN pg_namespace pn ON pn.oid = pa.relnamespace
  JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
  JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = c.confkey[1]
 WHERE c.contype = 'f' AND pn.nspname = 'public' AND array_length(c.conkey, 1) = 1
"""


def fk_guard_sql(rows) -> str:
    """The guard db_retention.fk_guard() builds, from catalog rows (parent, child, child_col, parent_col).

    Identifiers arrive already quoted by Postgres (``format``/``quote_ident``), so nothing user-supplied is
    spliced: a table called ``select`` is ``"select"`` here, exactly as it is in the writer.
    """
    out = []
    for row in rows:
        if len(row) != 4:
            continue
        _parent, child, child_col, parent_col = row
        out.append(f' AND NOT EXISTS (SELECT 1 FROM {child} ch WHERE ch.{child_col} = t.{parent_col})')
    return "".join(out)


def stale_window_findings(policies: dict, tables: set, columns: dict, q_fn=q) -> tuple[list[dict], list[dict]]:
    """(findings, held) for every policy whose window has rows still inside it.

    ``findings`` holds STALE_WINDOW only where retention could have deleted rows and did not.
    ``held`` is the visibility half: tables whose old rows are all referenced by children, in the shape
    ``{"table", "rows", "held_by_references"}``. Pure over ``q_fn``: tests pass a dict-backed fake.
    """
    findings: list[dict] = []
    held: list[dict] = []
    for t, r in policies.items():
        if r.get("class") == "KEEP_FOREVER" or not r.get("window_days"):
            continue
        col = r.get("ts_column")
        if t not in tables or col not in columns.get(t, set()):
            continue
        if not IDENT.match(str(t)) or not IDENT.match(str(col)):
            findings.append({"code": "STALE_WINDOW", "item": t, "severity": "P3",
                             "detail": "table or column name is not a plain identifier; count skipped"})
            continue
        w = int(r["window_days"])
        try:
            stale = int(q_fn(f"SELECT count(*) FROM \"{t}\" t WHERE t.\"{col}\" < now() - interval '{w + 2} days'")[0][0])
            if stale == 0:
                continue
            guard = fk_guard_sql([row for row in q_fn(_FK_ROWS_SQL) if row and row[0] == t])
            deletable = int(q_fn(f"SELECT count(*) FROM \"{t}\" t WHERE t.\"{col}\" < now() - interval '{w + 2} days'{guard}")[0][0])
        except (RuntimeError, IndexError) as e:
            findings.append({"code": "STALE_WINDOW", "item": t, "severity": "P3", "detail": f"count failed: {e}"})
            continue
        if deletable > 0:
            findings.append({"code": "STALE_WINDOW", "item": t, "severity": "P2",
                             "detail": f"{deletable} rows older than {w}+2 d; retention not enforcing"})
        if stale > deletable:
            held.append({"table": t, "rows": stale - deletable, "held_by_references": True})
    return findings, held


def tripwire_findings() -> list[dict]:
    """Reader half of the row-archive tripwire (2026-10-11). Never fails the report: a reader that
    cannot run is itself a finding."""
    try:
        from scripts.lib.retention_tripwire import findings
        return findings(state_root(), ROOT)
    except Exception as e:  # noqa: BLE001
        return [{"code": "TRIPWIRE_UNREADABLE", "item": "retention_tripwire", "severity": "P2",
                 "detail": f"tripwire reader failed: {type(e).__name__}: {e}"[:160]}]


def archive_findings(reg: dict) -> tuple[list[dict], dict | None]:
    """ARCHIVE_GROWTH (2026-10-11). Files only; never fails the report."""
    try:
        import shutil
        from scripts.lib.retention_archive import archive_growth_findings, archive_usage
        usage = archive_usage(state_root() / "archive")
        free = shutil.disk_usage(str(state_root())).free if state_root().exists() else None
        return archive_growth_findings(usage, cap_gb_month=reg.get("archive_growth_cap_gb_month"),
                                       total_budget_gb=reg.get("archive_total_budget_gb"), disk_free_bytes=free), usage
    except Exception as e:  # noqa: BLE001
        return [{"code": "ARCHIVE_GROWTH", "item": "archive_usage", "severity": "P3",
                 "detail": f"archive usage reader failed: {type(e).__name__}: {e}"[:160]}], None


def collect(reg: dict, min_table_mb: int) -> dict:
    findings: list[dict] = []
    policies = {r["table"]: r for r in reg.get("policies") or []}
    db_bytes = int(q("SELECT pg_database_size(current_database())")[0][0])
    budget = float(reg.get("size_budget_gb") or 0)
    if budget and db_bytes > budget * 1e9:
        findings.append({"code": "SIZE_BUDGET", "item": "trade_ai", "severity": "P2", "detail": f"{db_bytes/1e9:.1f} GB > budget {budget} GB"})
    tables = q("SELECT relname, pg_total_relation_size(relid), n_live_tup FROM pg_stat_user_tables WHERE schemaname='public'")
    for name, size, live in tables:
        mb = int(size) / 1e6
        if BACKUP_NAME.match(name):
            findings.append({"code": "BACKUP_NAMED_TABLE", "item": name, "severity": "P3", "detail": f"{mb:.0f} MB"})
        if mb >= min_table_mb and name not in policies:
            findings.append({"code": "UNCOVERED_TABLE", "item": name, "severity": "P2", "detail": f"{mb:.0f} MB, no retention row"})
        tb = (reg.get("table_budget_mb") or {}).get(name)
        if tb and mb > tb:
            findings.append({"code": "TABLE_BUDGET", "item": name, "severity": "P2", "detail": f"{mb:.0f} MB > {tb} MB"})
    dups = q("""SELECT a.indexrelid::regclass::text, b.indexrelid::regclass::text FROM pg_index a JOIN pg_index b
                ON a.indrelid=b.indrelid AND a.indexrelid<b.indexrelid AND a.indkey::text=b.indkey::text
                AND coalesce(a.indexprs::text,'')=coalesce(b.indexprs::text,'') AND coalesce(a.indpred::text,'')=coalesce(b.indpred::text,'')
                JOIN pg_class c ON c.oid=a.indrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'""")
    for ia, ib in dups:
        findings.append({"code": "DUPLICATE_INDEX", "item": f"{ia}~{ib}", "severity": "P3", "detail": "exact duplicate definition"})
    tnames = {t[0] for t in tables}
    cols = {}
    for t, c in q("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public'"):
        cols.setdefault(t, set()).add(c)
    stale, stale_held = stale_window_findings(policies, tnames, cols)
    findings.extend(stale)
    for t, (c, where) in QUEUES.items():
        if t in tnames and c in cols.get(t, set()):
            n = int(q(f'SELECT count(*) FROM "{t}" WHERE "{c}" < now() - interval \'30 days\' AND ({where})')[0][0])
            if n > 0:
                findings.append({"code": "DEAD_QUEUE", "item": t, "severity": "P3", "detail": f"{n} terminal rows older than 30 d"})
    sched = subprocess.run(["bash", "-lc", "crontab -l 2>/dev/null | grep -c 'db_retention.py'; systemctl --user list-timers --all --no-pager 2>/dev/null | grep -c 'db-retention'"],
                           capture_output=True, text=True).stdout.split()
    if len(sched) == 2 and sched[0] != "0" and sched[1] != "0":
        findings.append({"code": "RETENTION_SCHEDULERS", "item": "db_retention", "severity": "P2", "detail": f"cron lines {sched[0]} AND timers {sched[1]}: one scheduler only"})
    findings.extend(tripwire_findings())
    arch_f, arch_usage = archive_findings(reg)
    findings.extend(arch_f)
    by = {}
    for f in findings:
        by[f["code"]] = by.get(f["code"], 0) + 1
    return {"schema": SCHEMA, "authority": "READ_ONLY_ADVISORY", "as_of": datetime.now(timezone.utc).isoformat(), "db_bytes": db_bytes,
            "size_budget_gb": budget, "tables": len(tables), "policies": len(policies), "findings": findings, "by_code": by, "archive_usage": arch_usage,
            # additive (nothing reads it as a verdict): old rows retention keeps on purpose, because a
            # child row still references them. Visible, but not an "enforcement" finding.
            "stale_held": stale_held,
            "ok": not any(f["severity"] in {"P1", "P2"} for f in findings)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--min-table-mb", type=int, default=20)
    ap.add_argument("--registry", default=str(ROOT / "config" / "data_retention_policy.json"))
    a = ap.parse_args(argv)
    try:
        reg = json.loads(Path(a.registry).read_text(encoding="utf-8"))
        rep = collect(reg, a.min_table_mb)
    except Exception as e:
        print(f"db hygiene CANNOT RUN: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    if a.write:
        out = state_root() / "data" / "runtime" / "db_hygiene_last.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".json.tmp"); tmp.write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8"); os.replace(tmp, out)
    print(json.dumps({"db_gb": round(rep["db_bytes"] / 1e9, 2), "findings": len(rep["findings"]), "by_code": rep["by_code"], "ok": rep["ok"]}))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
