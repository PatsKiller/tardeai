"""STALE_WINDOW must count only the rows retention can delete, or it reports a policy that is working.

Measured 2026-11-06 against the live database, for the nightly `platform-maintenance-nightly` run at
2026-11-06T06:15Z whose receipt says `ok: false` (failed steps `db_retention`, `report_db_hygiene`):

    decision_packets        6,340 rows older than 90 d   ->  0 that db_retention could delete
    aegis_steph_escalations    24 rows older than 90 d   -> 21 that db_retention could delete (3 held)

`db_retention.fk_guard()` deliberately keeps a row whose child still references it — "Expired rows
nothing references are deleted; referenced rows wait until their children expire under their own
policy". The reader counted every old row and called it "retention not enforcing", so a table whose
rows are all held (decision_packets is held by blueprints, runs, contradictions and its own
superseded_by chain) produced a P2 every night since 2026-10.

The fix: count stale rows WITH the writer's guard. Rows it can delete and did not remain a P2; rows
it holds on purpose are carried in the report's additive `stale_held` list, visible but not a claim
that the policy failed.

Hermetic: synthetic registry rows, a dict-backed psql fake, a fake cursor for the writer's guard. No
database, no host state, no credential.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# db_retention autoloads ../.env for DB_PASSWORD at import time when the variable is unset. Set it first:
# the parity test may import that module, and a test must never read a credential file.
os.environ.setdefault("DB_PASSWORD", "test-not-a-credential")

from scripts import report_db_hygiene as hyg  # noqa: E402
from scripts import db_retention as dbr  # noqa: E402


def _policy(table, col="generated_at", days=90, cls="ARCHIVE_THEN_DELETE"):
    return {table: {"table": table, "ts_column": col, "window_days": days, "class": cls}}


def _q(stale, deletable, catalog=(), calls=None):
    """A psql fake: the catalog query, then per table the unguarded count and the guarded count in order."""
    seen: dict[str, int] = {}

    def _run(sql: str):
        if calls is not None:
            calls.append(sql)
        if "pg_constraint" in sql:
            return list(catalog)
        table = re.search(r'FROM "([^"]+)" t', sql).group(1)
        first = seen.get(table, 0) == 0
        seen[table] = seen.get(table, 0) + 1
        return [[str((stale if first else deletable).get(table, 0))]]
    return _run


def test_a_row_held_by_a_child_is_not_reported_as_retention_not_enforcing():
    """The 2026-11-06 decision_packets finding: 6,340 old rows, every one referenced."""
    catalog = [("decision_packets", "public.decision_packets", '"superseded_by"', '"packet_id"'),
               ("decision_packets", "public.decision_blueprints", '"packet_id"', '"packet_id"')]
    findings, held = hyg.stale_window_findings(_policy("decision_packets"), {"decision_packets"},
                                               {"decision_packets": {"generated_at"}},
                                               _q({"decision_packets": 6340}, {"decision_packets": 0}, catalog))
    assert findings == [], "a row retention keeps on purpose is not an enforcement failure"
    assert held == [{"table": "decision_packets", "rows": 6340, "held_by_references": True}]


def test_rows_retention_could_delete_are_still_a_p2_with_their_count():
    """aegis_steph_escalations: 24 old rows, 21 deletable, 3 held — the 21 are the real finding."""
    findings, held = hyg.stale_window_findings(_policy("aegis_steph_escalations", "observed_at"),
                                               {"aegis_steph_escalations"},
                                               {"aegis_steph_escalations": {"observed_at"}},
                                               _q({"aegis_steph_escalations": 24},
                                                  {"aegis_steph_escalations": 21}))
    assert [(f["code"], f["severity"], f["item"]) for f in findings] == [
        ("STALE_WINDOW", "P2", "aegis_steph_escalations")]
    assert findings[0]["detail"].startswith("21 rows older than 90+2 d")
    # the 3 the resolution history holds stay visible, just not as a claim that the policy failed
    assert held == [{"table": "aegis_steph_escalations", "rows": 3, "held_by_references": True}]


def test_a_table_with_nothing_stale_costs_no_guard_query():
    calls: list[str] = []
    findings, held = hyg.stale_window_findings(_policy("t"), {"t"}, {"t": {"generated_at"}},
                                               _q({"t": 0}, {}, calls=calls))
    assert (findings, held) == ([], [])
    assert not any("pg_constraint" in s for s in calls), "the catalog is only read for a table with stale rows"


def test_the_guard_is_byte_identical_to_the_writers():
    """Read side and write side must agree on what 'enforced' means, so the SQL is compared, not re-described."""
    class _Cur:
        def execute(self, sql, params=None):
            self.sql, self.params = sql, params

        def fetchall(self):
            return [("public.decision_blueprints", "packet_id", "packet_id")]

    writer = dbr.fk_guard(_Cur(), "decision_packets")
    reader = hyg.fk_guard_sql([("decision_packets", "public.decision_blueprints", '"packet_id"', '"packet_id"')])
    assert reader == writer == ' AND NOT EXISTS (SELECT 1 FROM public.decision_blueprints ch WHERE ch."packet_id" = t."packet_id")'


def test_a_count_that_cannot_run_is_a_p3_and_not_a_crash():
    def _boom(sql: str):
        raise RuntimeError("canceling statement due to statement timeout")

    findings, held = hyg.stale_window_findings(_policy("t"), {"t"}, {"t": {"generated_at"}}, _boom)
    assert [(f["code"], f["severity"]) for f in findings] == [("STALE_WINDOW", "P3")]
    assert "count failed" in findings[0]["detail"] and held == []


def test_a_table_name_that_is_not_a_plain_identifier_is_never_spliced_into_sql():
    calls: list[str] = []
    findings, _held = hyg.stale_window_findings(_policy('t"; DROP TABLE x; --'), {'t"; DROP TABLE x; --'},
                                                {'t"; DROP TABLE x; --': {"generated_at"}},
                                                _q({}, {}, calls=calls))
    assert [(f["code"], f["severity"]) for f in findings] == [("STALE_WINDOW", "P3")]
    assert "count skipped" in findings[0]["detail"]
    assert not any("DROP TABLE" in s for s in calls)


def test_keep_forever_rows_and_absent_tables_are_not_counted():
    calls: list[str] = []
    policies = {**_policy("keep", cls="KEEP_FOREVER"), **_policy("gone"), **_policy("nocol")}
    findings, held = hyg.stale_window_findings(policies, {"keep", "nocol"}, {"keep": {"generated_at"}, "nocol": set()},
                                               _q({}, {}, calls=calls))
    assert (findings, held) == ([], [])
    assert calls == []
