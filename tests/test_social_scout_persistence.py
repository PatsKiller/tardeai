#!/usr/bin/env python3
"""P0-3: Social Scout metadata persistence.

DB-free: a fake connection records SQL + verifies (1) scout fields are stamped when columns exist,
(2) the persisted operator_pill exactly matches route output, (3) missing columns degrade safely with
no crash and no UPDATE, (4) persisted rows are always not_tradeable + not_validation_ready.
"""
import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

# The scanner calls load_dotenv(.env) at import; stub it so this stays a DB-free unit test (the
# scanner's other deps — psycopg2/requests/scoring/etc. — are all importable).
if "dotenv" not in sys.modules:
    _d = types.ModuleType("dotenv")
    _d.load_dotenv = lambda *a, **k: None
    sys.modules["dotenv"] = _d

import social_scalp_scanner as sss  # noqa: E402
from social_route_policy import route_social_candidate  # noqa: E402
from migrate_social_scout_fields import COLUMNS  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


class FakeCursor:
    def __init__(self, columns, log):
        self.columns, self.log, self._last = columns, log, (None, None)

    def execute(self, sql, params=None):
        self.log.append((sql, params))
        self._last = (sql, params)

    def fetchone(self):
        sql, params = self._last
        if "information_schema.columns" in sql:
            return (1,) if params and params[1] in self.columns else None
        return None

    def fetchall(self):
        return []


class FakeConn:
    def __init__(self, columns):
        self.columns, self.log, self.committed = set(columns), [], 0

    def cursor(self):
        return FakeCursor(self.columns, self.log)

    def commit(self):
        self.committed += 1

    def rollback(self):
        pass


SCOUT_COLS = {"scout_status", "scout_pillar_count", "scout_pillars_met", "scout_pillars_missing",
              "operator_pill", "operator_subtitle", "operator_color_token",
              "not_validation_ready", "not_tradeable"}


def _updates(conn):
    return [(s, p) for (s, p) in conn.log if s.strip().upper().startswith("UPDATE")]


def main():
    # 0. Migration defines the scout columns on both discovery tables.
    for tbl in ("scalp_scan_results", "trade_ai_scans"):
        defined = {c for c, _ in COLUMNS[tbl]}
        check(f"{tbl} scout columns defined", SCOUT_COLS <= defined)

    # A real 2/5 Social Scout route output (social velocity + market confirmation, no catalyst/float).
    route = route_social_candidate(
        {"symbol": "PERS", "mention_count": 80, "sources": ["reddit", "stocktwits"]},
        {"price": 4.0, "rvol": 9.0, "float_m": None, "gap_pct": 7.0}, {})
    assert route["scout_status"] == "SOCIAL_SCOUT" and route["operator_pill"] == "SOCIAL SCOUT · 2/5"

    # 1. Columns present → an UPDATE is issued carrying the scout metadata.
    sss._TRACE_COL_CACHE.clear()
    conn = FakeConn(SCOUT_COLS)
    sss.stamp_scout_fields(conn, "scalp_scan_results", "PERS", route)
    ups = _updates(conn)
    check("stamps an UPDATE when columns exist", len(ups) == 1)
    if ups:
        sql, params = ups[0]
        check("UPDATE targets scout_status", "scout_status=%s" in sql)
        # params order: status,count,met,missing,pill,subtitle,color,not_val,not_trade, symbol
        check("persisted operator_pill matches route exactly", params[4] == "SOCIAL SCOUT · 2/5")
        check("persisted scout_status matches", params[0] == "SOCIAL_SCOUT")
        check("persisted pillar_count matches", params[1] == 2)
        check("persisted pillars_met is JSON array", json.loads(params[2]) == route["pillars_met"])
        check("persisted not_validation_ready True", params[7] is True)
        check("persisted not_tradeable True", params[8] is True)
        check("symbol bound last", params[-1] == "PERS")
    check("commit called", conn.committed >= 1)

    # 2. Missing columns → safe degrade: no UPDATE, no crash.
    sss._TRACE_COL_CACHE.clear()
    conn2 = FakeConn(set())  # no scout columns at all
    try:
        sss.stamp_scout_fields(conn2, "scalp_scan_results", "PERS", route)
        crashed = False
    except Exception:
        crashed = True
    check("missing columns do not crash", not crashed)
    check("missing columns → no UPDATE issued", len(_updates(conn2)) == 0)

    # 3. trade_ai_scans path also stamps (CURRENT_DATE guarded UPDATE).
    sss._TRACE_COL_CACHE.clear()
    conn3 = FakeConn(SCOUT_COLS)
    sss.stamp_scout_fields(conn3, "trade_ai_scans", "PERS", route)
    ups3 = _updates(conn3)
    check("trade_ai_scans stamps an UPDATE", len(ups3) == 1 and "trade_ai_scans" in ups3[0][0])

    # 4. A GO row (no scout) still persists not_tradeable=False honestly (normal path eligible).
    go = route_social_candidate(
        {"symbol": "GOOD", "mention_count": 30, "sources": ["stocktwits"]},
        {"price": 5.0, "rvol": 7.0, "float_m": 8.0, "gap_pct": 4.0},
        {"catalyst_verified": True, "catalyst_source": "news"})
    sss._TRACE_COL_CACHE.clear()
    conn4 = FakeConn(SCOUT_COLS)
    sss.stamp_scout_fields(conn4, "scalp_scan_results", "GOOD", go)
    ups4 = _updates(conn4)
    check("GO row scout_status NONE persisted", ups4 and ups4[0][1][0] == "NONE")
    check("GO row not_tradeable False persisted", ups4 and ups4[0][1][8] is False)

    # 5. No raw social-post text is ever in the stamped params (privacy).
    flat = " ".join(str(x) for (_, p) in _updates(conn) for x in (p or []))
    check("no raw sample_content leaked into storage", "reddit" not in flat.lower() or
          "sample_content" not in flat.lower())

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
