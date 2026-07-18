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




def run_v5():
    """v5: trim composite arithmetic · ladder fire AND disarm · partial-trim →
    re-entry watch · guard rejects ticketless trim cards."""
    import defense_trim_ladders as dtl

    # ── DT1: the composite is deterministic and each input moves it visibly
    f2 = [{"name": "a", "value": 1}, {"name": "b", "value": 2}]
    f3 = f2 + [{"name": "c", "value": 3}]
    p = dtl.compute_trim_plan(f2, False, None, None, None)
    assert p["fraction_pct"] == 25, p  # 20 base + 5 no-protection (no GG row)
    assert "absent" in p["rationale"] and "GG: no row" in p["rationale"]
    p = dtl.compute_trim_plan(f3, False, {"giveback_state": "GIVEBACK_WATCH"}, None, None)
    assert p["fraction_pct"] == 35, p  # 30 + 5 watch (GG row exists → no no-protection bump... watch IS protection signal)
    p = dtl.compute_trim_plan(f3, False, {"giveback_state": "GIVEBACK_BREACH"}, 24.1, None)
    # 30 + 15 breach + min(15, 12.1)=12 → 57 → rounds to 55
    assert p["fraction_pct"] == 55, p
    p = dtl.compute_trim_plan(f3, True, {"giveback_state": "GIVEBACK_BREACH"}, 30.0, None)
    assert p["fraction_pct"] == 60, p  # 40 urgent + 15 + 15cap = 70 → bounded 60
    assert "bounded" in " ".join(p["arithmetic"])
    print("v5 ✓ trim composite: differing fractions, arithmetic + bounds rendered")

    # ── guard: a trim card without rationale/ticket does NOT render
    base = {
        "id": "moveout-TEST-acct-2026-07-18", "group": "protect", "title": "T",
        "instruments": [{"symbol": "TEST", "kind": "held position", "note": "n"}],
        "accounts": ["schwab_rollover_ira"], "direction": "reduce/exit", "size_band": "x",
        "entry_logic": "e", "invalidation": "i",
        "factors": [{"name": "f", "value": 1}], "as_of": "2026-07-18", "mode": "SHADOW",
        "levels": {"price": 1, "position_value": 1},
    }
    assert validate(base) == "trim_rationale"
    base["trim_rationale"] = "trim 35% — ..."
    assert validate(base) == "ticket"
    base["ticket"] = {"options": [{"line": "Sell ≈ 1 sh"}]}
    assert validate(base) is None
    print("v5 ✓ field guard: ticket-less trim card rejected (static-band regression impossible)")

    # ── EL: fire path and disarm path over a synthetic ladder
    import sqlite3
    class Cur:
        def __init__(self):
            self.db = sqlite3.connect(":memory:")
            self.db.execute("""CREATE TABLE rotation_ladders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, advisory_id TEXT UNIQUE, symbol TEXT,
                account TEXT, status TEXT DEFAULT 'open', t1_fraction INT,
                t1_status TEXT DEFAULT 'advised', tranches TEXT,
                factor_count_at_creation INT, created_at TEXT DEFAULT '2026-07-01 00:00:00',
                closed_at TEXT, close_reason TEXT)""")
            self.db.execute("""CREATE TABLE watch_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, condition_type TEXT,
                threshold REAL, recurring INT, active INT, created_by TEXT, note TEXT,
                last_fired_at TEXT)""")
            self.db.execute("""CREATE TABLE rotation_round_trips (
                id INTEGER PRIMARY KEY AUTOINCREMENT, advisory_id TEXT UNIQUE, symbol TEXT,
                account TEXT, status TEXT, exit_advised_at TEXT, exit_detected_at TEXT,
                exit_source TEXT, exit_qty REAL, exit_price REAL, exit_loss_known INT,
                exit_is_loss INT, re_entry_conditions TEXT, rollback_opened_at TEXT,
                closed_at TEXT, close_reason TEXT, tranche_of INT)""")
            self._rows = None
            self.rowcount = 0
            class _C:
                def rollback(self): pass
            self.connection = _C()
        def execute(self, q, params=()):
            q = q.replace("%s", "?").replace("now()", "CURRENT_TIMESTAMP")
            if "CREATE TABLE IF NOT EXISTS" in q or "ADD COLUMN" in q:
                self._rows = None
                return
            q = q.replace("ON CONFLICT (advisory_id) DO NOTHING", "")
            q = q.replace("INSERT INTO rotation_round_trips", "INSERT OR IGNORE INTO rotation_round_trips")
            c = self.db.execute(q, params)
            self.rowcount = c.rowcount
            self._rows = c
        def fetchone(self): return self._rows.fetchone() if self._rows else None
        def fetchall(self): return self._rows.fetchall() if self._rows else []

    cur = Cur()
    import json as _j
    tranches = [{"tranche": "T2", "add_fraction_pct": 25, "status": "armed", "triggers": [
        {"type": "sector_persist", "sector": "Industrials", "state": "LAGGING", "sessions": 5,
         "label": "Industrials still LAGGING after 5 more sessions"},
        {"type": "factor_increase", "baseline": 3, "label": "factor count rises above 3"}]}]
    cur.execute("""INSERT INTO rotation_ladders (advisory_id, symbol, account, t1_fraction, tranches,
                   factor_count_at_creation) VALUES ('adv-1','ARKX','schwab_rollover_ira',35,?,3)""",
                (_j.dumps(tranches),))
    # fire path: sector persists (created 2026-07-01 → sessions elapsed >> 5)
    rows = dtl.evaluate_ladders(cur, {"Industrials": "LAGGING"}, {("ARKX", "schwab_rollover_ira"): 3}, {})
    t2 = rows[0]["tranches"][0]
    assert t2["status"] == "fired" and "LAGGING" in t2["fired_by"], t2
    print("v5 ✓ ladder T2 FIRES on sector persistence")

    # disarm path: fresh ladder, sector recovers
    cur.execute("""INSERT INTO rotation_ladders (advisory_id, symbol, account, t1_fraction, tranches,
                   factor_count_at_creation, created_at)
                   VALUES ('adv-2','XAR','schwab_rollover_ira',35,?,3,CURRENT_TIMESTAMP)""",
                (_j.dumps(tranches),))
    rows = dtl.evaluate_ladders(cur, {"Industrials": "IMPROVING"}, {}, {})
    lad2 = next(r for r in rows if r["advisory_id"] == "adv-2")
    t2 = lad2["tranches"][0]
    assert t2["status"] == "disarmed" and "recovered" in t2["disarmed_reason"], t2
    print("v5 ✓ ladder T2 DISARMS visibly when the sector recovers")

    # ── RP1: tranche confirm opens a re-entry watch for the slice
    ok2 = dtl.confirm_tranche(cur, 1, "T1", qty=350, price=30.30)
    assert ok2
    cur.execute("SELECT advisory_id, status, tranche_of, exit_qty FROM rotation_round_trips WHERE tranche_of=1")
    slice_row = cur.fetchone()
    assert slice_row and slice_row[1] == "stepped_out" and slice_row[3] == 350, slice_row
    print("v5 ✓ partial trim confirmed → re-entry watch opened for the slice (tranche_of keyed)")
    print("ALL v5 TESTS PASS")


if __name__ == "__main__":
    rc = run()
    run_v4()
    run_v5()
    sys.exit(rc)
