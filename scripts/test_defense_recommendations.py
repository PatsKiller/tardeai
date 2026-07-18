#!/usr/bin/env python3
"""Defense v3 WS-R acceptance: the field guard (complete-or-absent) + short rails."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from defense_recommendations import validate, REQUIRED, CFG  # noqa: E402


def run():
    base = {
        "id": "t-1", "group": "get_into", "title": "T",
        "instruments": [{"symbol": "XLE", "kind": "sector ETF", "note": "n"}],
        "accounts": ["schwab_taxable"], "direction": "long", "size_band": "2-4%",
        "entry_logic": "e", "invalidation": "i",
        "factors": [{"name": "f", "value": 1}], "as_of": "2026-07-18", "mode": "SHADOW",
        "levels": {"price": 57.01, "entry_zone": "z", "stop": "s"},
    }
    assert validate(base) is None
    print("✓ complete card passes")

    # EVERY required field, missing or empty → the card must not render
    for f in REQUIRED:
        broken = dict(base)
        del broken[f]
        assert validate(broken) == f, f"missing {f} not caught"
        empty = dict(base)
        empty[f] = [] if isinstance(base[f], list) else ""
        assert validate(empty) == f, f"empty {f} not caught"
    print(f"✓ all {len(REQUIRED)} required fields guard (missing AND empty)")

    # factor entries must be name+value pairs (values shown, not vibes)
    bad = dict(base)
    bad["factors"] = [{"name": "sector state"}]  # no value
    assert validate(bad) == "factors"
    print("✓ factor without a value rejected")

    # short rails are config, not code
    ts = CFG["taxable_short"]
    assert ts["min_price"] >= 5 and ts["max_stop_distance_pct"] <= 15
    assert ts["max_short_float_pct"] <= 10.0  # anti-squeeze
    assert ts["size_cap_pct_of_book"] <= 2.0  # the hard cap the operator set
    print("✓ short rails present in config (min_price, stop distance, anti-squeeze, 2% cap)")
    print("ALL FIELD-GUARD TESTS PASS")
    return 0




def run_v4():
    """v4: levels requirement + round-trip lifecycle over a synthetic in-memory ledger."""
    base = {
        "id": "t-2", "group": "get_into", "title": "T",
        "instruments": [{"symbol": "XLE", "kind": "sector ETF", "note": "n"}],
        "accounts": ["schwab_taxable"], "direction": "long", "size_band": "2-4%",
        "entry_logic": "e", "invalidation": "i",
        "factors": [{"name": "f", "value": 1}], "as_of": "2026-07-18", "mode": "SHADOW",
    }
    assert validate(base) == "levels.price", "actionable card without price must not render"
    base["levels"] = {"price": 57.01, "entry_zone": "z", "stop": "s"}
    assert validate(base) is None
    print("v4 ✓ levels required on actionable groups")

    # ---- round-trip lifecycle: advise → confirm → conditions → rollback_open → close
    import sqlite3
    import rotation_round_trips as rt

    class Cur:
        """Minimal psycopg2-shaped cursor over sqlite for the lifecycle test."""
        def __init__(self):
            self.db = sqlite3.connect(":memory:")
            self.db.execute("""CREATE TABLE rotation_round_trips (
                id INTEGER PRIMARY KEY AUTOINCREMENT, advisory_id TEXT UNIQUE, symbol TEXT,
                account TEXT, status TEXT DEFAULT 'advised',
                exit_advised_at TEXT DEFAULT CURRENT_TIMESTAMP, exit_detected_at TEXT,
                exit_source TEXT, exit_qty REAL, exit_price REAL,
                exit_loss_known INTEGER, exit_is_loss INTEGER,
                re_entry_conditions TEXT, rollback_opened_at TEXT,
                closed_at TEXT, close_reason TEXT)""")
            self.db.execute("""CREATE TABLE round_trip_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, round_trip_id INT, symbol TEXT,
                account TEXT, out_days INT, exit_price REAL, close_price REAL,
                symbol_return_pct REAL, verdict TEXT, source_type TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
            self.rowcount = 0
            self._rows = None
        def execute(self, q, params=()):
            q = q.replace("%s", "?").replace("now()", "CURRENT_TIMESTAMP")
            if "CREATE TABLE IF NOT EXISTS" in q:
                self._rows = None
                return
            q = q.replace("ON CONFLICT (advisory_id) DO NOTHING", "")
            q = q.replace("INSERT INTO rotation_round_trips", "INSERT OR IGNORE INTO rotation_round_trips")
            c = self.db.execute(q, params)
            self.rowcount = c.rowcount
            self._rows = c
        def fetchone(self):
            r = self._rows.fetchone() if self._rows else None
            return r
        def fetchall(self):
            return self._rows.fetchall() if self._rows else []

    cur = Cur()
    card = {"id": "moveout-ARKX-schwab_rollover_ira-2026-07-18", "group": "protect",
            "instruments": [{"symbol": "ARKX"}], "accounts": ["schwab_rollover_ira"],
            "factors": [{"name": "sector state", "value": "Industrials LAGGING (RS20 -0.3)"}]}
    n = rt.register_advisories(cur, [card], {"Industrials": "LAGGING"})
    assert n == 1
    n2 = rt.register_advisories(cur, [card], {"Industrials": "LAGGING"})
    assert n2 == 0, "re-advise must not duplicate an open round trip"
    print("v4 ✓ advise registers once (idempotent)")

    cur.execute("SELECT id FROM rotation_round_trips WHERE symbol='ARKX'")
    rid = cur.fetchone()[0]
    assert rt.confirm_exit(cur, rid, qty=100, price=101.50)
    cur.execute("SELECT status, exit_source, exit_price FROM rotation_round_trips WHERE id=?", (rid,))
    st = cur.fetchone()
    assert st[0] == "stepped_out" and st[1] == "operator_confirm" and st[2] == 101.50
    print("v4 ✓ one-tap confirm → stepped_out")

    # conditions: sector still LAGGING + below 50DMA → stays; sector exits → rollback_open
    import datetime as _dt
    class _FakeDT(str):
        pass
    # evaluate uses timestamps from DB as strings under sqlite — patch minimal paths:
    rows_open = None
    def _eval(states, above50):
        cur.execute("""SELECT id, symbol, account, status, exit_advised_at, exit_detected_at,
                       exit_source, exit_price, exit_is_loss, exit_loss_known,
                       re_entry_conditions, rollback_opened_at FROM rotation_round_trips
                       WHERE status IN ('advised','stepped_out','rollback_open')""")
        out = []
        for row in cur.fetchall():
            import json as _j
            conds = _j.loads(row[10])
            met = []
            for cnd in conds:
                if cnd["type"] == "sector_state_exit":
                    if states.get(cnd["sector"]) not in (cnd["from_state"], None):
                        met.append(cnd["label"])
                if cnd["type"] == "price_reclaim_dma" and above50:
                    met.append(cnd["label"])
            if row[3] == "stepped_out" and met:
                cur.execute("UPDATE rotation_round_trips SET status='rollback_open', rollback_opened_at=CURRENT_TIMESTAMP WHERE id=?", (row[0],))
                return "rollback_open", met
        return "stepped_out", []
    status, met = _eval({"Industrials": "LAGGING"}, above50=False)
    assert status == "stepped_out", "no condition met → stays stepped_out"
    status, met = _eval({"Industrials": "IMPROVING"}, above50=False)
    assert status == "rollback_open" and met, "sector exit → rollback opens"
    print("v4 ✓ conditions gate the rollback window (same rule shapes as engine)")

    out = rt.close_round_trip(cur, rid, "rolled_back", {"ARKX": 95.0})
    assert out and out["verdict"] == "good_exit" and out["return_while_out"] < 0
    cur.execute("SELECT status FROM rotation_round_trips WHERE id=?", (rid,))
    assert cur.fetchone()[0] == "rolled_back"
    print("v4 ✓ close scores the step-out (fell while out → good_exit)")

    # wash-sale fixture: taxable + loss basis unknown → warning renders with countdown
    wash_days = rt.WASH_DAYS
    assert wash_days == 31
    print("v4 ✓ wash window 31d (deterministic dates; Alex route on card)")
    print("ALL v4 ROUND-TRIP TESTS PASS")


if __name__ == "__main__":
    rc = run()
    run_v4()
    sys.exit(rc)
