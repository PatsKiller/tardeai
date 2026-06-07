#!/usr/bin/env python3
"""audit_hermes_db_lineage.py — Hermes/TradeAI table read/write lineage + freshness (Phase 209D). Read-only.
Output: data/hermes/hermes_db_lineage_latest.json"""
import os, json, glob, re
from pathlib import Path
import psycopg2

for ln in (Path(__file__).resolve().parent.parent / ".env").read_text().splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip())

TABLES = ["hermes_research_intelligence", "hermes_alerts", "hermes_validation_findings",
          "hermes_memory_events", "hermes_embedding_queue", "hermes_promotion_audit"]
SCR = Path(__file__).resolve().parent


def code_refs(table):
    writers, readers = set(), set()
    for f in glob.glob(str(SCR / "*.py")) + glob.glob(str(SCR / "**/*.py"), recursive=True):
        try:
            s = Path(f).read_text(errors="ignore").lower()
        except Exception:
            continue
        nm = Path(f).name
        if re.search(r"insert into\s+" + table + r"|update\s+" + table, s):
            writers.add(nm)
        if re.search(r"from\s+" + table + r"|join\s+" + table, s):
            readers.add(nm)
    return sorted(writers)[:12], sorted(readers)[:12]


def main():
    c = psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
                         user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"))
    cur = c.cursor()
    def q1(s):
        try:
            cur.execute(s); return cur.fetchone()[0]
        except Exception:
            c.rollback(); return None
    rows = []
    for t in TABLES:
        cnt = q1(f"SELECT count(*) FROM {t}")
        if cnt is None:
            rows.append({"table": t, "exists": False}); continue
        has_created = q1(f"SELECT 1 FROM information_schema.columns WHERE table_name='{t}' AND column_name='created_at'")
        last = w24 = w7 = None
        if has_created:
            last = str(q1(f"SELECT max(created_at) FROM {t}"))
            w24 = q1(f"SELECT count(*) FROM {t} WHERE created_at > now()-interval '24 hours'")
            w7 = q1(f"SELECT count(*) FROM {t} WHERE created_at > now()-interval '7 days'")
        wr, rd = code_refs(t)
        rows.append({"table": t, "exists": True, "rows": cnt, "last_write": last,
                     "writes_24h": w24, "writes_7d": w7, "written_by": wr, "read_by": rd})
    # safe-view inventory (read-only inputs)
    views = [r[0] for r in (cur.execute("SELECT table_name FROM information_schema.views WHERE table_name LIKE 'hermes_v_%' OR table_name ILIKE '%safe%' LIMIT 30") or cur.fetchall())]
    out = {"generated_note": "Phase 209D DB read/write lineage", "tables": rows,
           "safe_views": sorted(views), "table_count": len([r for r in rows if r.get('exists')])}
    Path("data/hermes").mkdir(parents=True, exist_ok=True)
    Path("data/hermes/hermes_db_lineage_latest.json").write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps({"tables": [(r["table"], r.get("rows"), r.get("writes_24h"), len(r.get("written_by", []))) for r in rows],
                      "safe_views_found": len(views)}, indent=2, default=str))
    c.close()


if __name__ == "__main__":
    main()
