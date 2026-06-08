"""Regression harness for the emit_siem idempotent upsert (Phase #1). Non-mutating: runs in a transaction
that is ROLLED BACK at the end, so alert_events is unchanged."""
import sys, psycopg2
from datetime import datetime, timezone, timedelta
sys.path.insert(0, "scripts")
import system_freshness_monitor as m
import os
for ln in open(".env"):
    if "=" in ln and not ln.strip().startswith("#"):
        k,_,v=ln.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'\""))
c = psycopg2.connect(host=os.getenv("DB_HOST","localhost"), port=os.getenv("DB_PORT","5432"),
                     dbname=os.getenv("DB_NAME","trade_ai"), user=os.getenv("DB_USER","trade_ai"),
                     password=os.getenv("DB_PASSWORD"))
cur = c.cursor()
UID = "freshness:__upsert_regression_test__"
cur.execute("DELETE FROM alert_events WHERE alert_uid=%s", (UID,))  # clean slate inside txn
f = {"key": "__upsert_regression_test__", "sev": "P1", "detail": "regression test detail v1"}
# 1) first insert
id1 = m.emit_siem(cur, f); print(f"1) first insert -> id={id1}  (expect a number)")
assert id1 is not None
# 2) immediate second call -> within dedup window -> returns None (no write, no crash)
id2 = m.emit_siem(cur, f); print(f"2) immediate re-call -> {id2}  (expect None = deduped, no crash)")
assert id2 is None
# 3) simulate dedup window elapsed: backdate created_at beyond DEDUP_HOURS
cur.execute("UPDATE alert_events SET created_at=%s WHERE alert_uid=%s",
            (datetime.now(timezone.utc) - timedelta(hours=m.DEDUP_HOURS + 1), UID))
f2 = {"key": "__upsert_regression_test__", "sev": "P0", "detail": "regression test detail v2 (post-window)"}
id3 = m.emit_siem(cur, f2); print(f"3) post-window re-call -> id={id3}  (expect SAME id, ON CONFLICT UPDATE, no crash)")
assert id3 == id1, f"expected same id {id1}, got {id3}"
# verify the row updated in place (severity + detail), still ONE row
cur.execute("SELECT count(*), max(severity), max(raw_text) FROM alert_events WHERE alert_uid=%s", (UID,))
n, sev, txt = cur.fetchone()
print(f"4) rows for uid={n} (expect 1)  severity={sev}  raw_text={txt!r}")
assert n == 1
print("ALL ASSERTIONS PASSED — idempotent, no crash, single row updated in place")
c.rollback(); c.close()   # non-mutating: discard everything
print("transaction ROLLED BACK (alert_events unchanged)")
