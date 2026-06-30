#!/usr/bin/env python3
"""Stock-management due-diligence gaps before any Schwab OCO canary (paper-only, no live calls).

Covers:
  1. convert_to_oco stop-never-absent across process-interruption states (OCO_REPLACING marker, rollback,
     read-back verify) + the repair_oco_replacing() supervisor.
  2. The reconciler's --fix is DB-metadata-only — the OCO broker mutation is gated behind --apply-oco-retrofit.
  3. qty_available unreadable fails closed (BROKER_QTY_UNKNOWN / DEFER_RECHECK) with a bounded retry.

PURE: every broker call is mocked; the DB connection is a fake. Nothing touches Alpaca or Schwab.
"""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Stub telegram so the supervisor's alert path never does network I/O.
sys.modules.setdefault("telegram_alert", types.ModuleType("telegram_alert"))
sys.modules["telegram_alert"].send_telegram = lambda *a, **k: None

import alpaca_stop_manager as asm            # noqa: E402
import alpaca_paper_reconciler as apr        # noqa: E402
import apply_paper_protection_adjustment as appa  # noqa: E402


class FakeCursor:
    description = []   # reconcile() reads cur.description to name columns; [] is harmless for empty result sets
    def __init__(self, conn): self.c = conn
    def execute(self, sql, params=None):
        self.c.events.append(("DB", " ".join(sql.split()), params))
        s = " ".join(sql.split()).upper()
        if "RETURNING QTY_RECHECK_ATTEMPTS" in s:
            self.c.attempts += 1; self.c._one = (self.c.attempts,)
        elif s.startswith("SELECT"):
            self.c._all = list(self.c.rows)
    def fetchone(self): return getattr(self.c, "_one", None)
    def fetchall(self): return getattr(self.c, "_all", [])
    def close(self): pass


class FakeConn:
    def __init__(self, rows=None, events=None):
        self.events = events if events is not None else []
        self.rows = rows or []
        self.attempts = 0
        self.closed = False
    def cursor(self, *a, **k): return FakeCursor(self)
    def commit(self): pass
    def rollback(self): pass
    def close(self): self.closed = True


def _oco_resp():
    return {"id": "grp1", "legs": [{"id": "stp1", "type": "stop", "order_class": "oco"},
                                   {"id": "tp1", "type": "limit", "order_class": "oco"}]}


def _mock_alpaca(events, oco_raises=False):
    """Return a fake _alpaca_req that records (method, path) into `events`."""
    def fake(env, path, method="GET", body=None):
        events.append(("HTTP", method, path))
        if method == "POST" and body and body.get("order_class") == "oco":
            if oco_raises:
                raise RuntimeError("simulated OCO POST failure")
            return _oco_resp()
        if method == "POST":                       # simple stop re-place
            return {"id": "newstop1"}
        return {}
    return fake


class TestConvertToOcoInterruption(unittest.TestCase):
    def setUp(self):
        self._saved = (asm._alpaca_req, asm._classify_broker_protection, asm._place_simple_stop)

    def tearDown(self):
        asm._alpaca_req, asm._classify_broker_protection, asm._place_simple_stop = self._saved

    def test_01_oco_replacing_set_before_cancel(self):
        ev = []
        conn = FakeConn(events=ev)
        asm._alpaca_req = _mock_alpaca(ev)
        asm._classify_broker_protection = lambda env, sym, group_id=None: {
            "readable": True, "has_oco": True, "has_stop": False, "stop_id": "stp1", "tp_id": "tp1"}
        r = asm.convert_to_oco({}, "AAPL", 10, 100.0, 110.0, "oldstop", conn=conn)
        self.assertEqual(r["status"], "OCO_ACTIVE")
        # the OCO_REPLACING marker must be written BEFORE the cancel DELETE hits the broker
        # (state value is a SQL param, so search both the statement text and its params)
        repl_idx = next(i for i, e in enumerate(ev) if e[0] == "DB" and "OCO_REPLACING" in (str(e[1]) + str(e[2])))
        del_idx = next(i for i, e in enumerate(ev) if e[0] == "HTTP" and e[1] == "DELETE")
        self.assertLess(repl_idx, del_idx, "OCO_REPLACING must be persisted before the standalone stop is canceled")

    def test_02_oco_post_fails_rolls_back_to_stop(self):
        ev = []
        conn = FakeConn(events=ev)
        asm._alpaca_req = _mock_alpaca(ev, oco_raises=True)
        asm._place_simple_stop = lambda env, sym, qty, sp: (ev.append(("HTTP", "POST", "/replace-stop")) or {"id": "rb1"})
        r = asm.convert_to_oco({}, "AAPL", 10, 100.0, 110.0, "oldstop", conn=conn)
        self.assertEqual(r["status"], "ROLLED_BACK")
        self.assertTrue(any(e[0] == "HTTP" and e[2] == "/replace-stop" for e in ev), "standalone stop must be re-placed")
        self.assertTrue(any("STOP_ONLY" in str(e[1]) for e in ev if e[0] == "DB"))

    def test_03_readback_no_oco_rolls_back(self):
        ev = []
        conn = FakeConn(events=ev)
        asm._alpaca_req = _mock_alpaca(ev)
        asm._place_simple_stop = lambda env, sym, qty, sp: (ev.append(("HTTP", "POST", "/replace-stop")) or {"id": "rb1"})
        # POST "succeeds" but read-back cannot confirm an OCO -> must NOT declare OCO_ACTIVE
        asm._classify_broker_protection = lambda env, sym, group_id=None: {
            "readable": True, "has_oco": False, "has_stop": False}
        r = asm.convert_to_oco({}, "AAPL", 10, 100.0, 110.0, "oldstop", conn=conn)
        self.assertEqual(r["status"], "ROLLED_BACK")
        self.assertIn("readback_no_oco", r["reason"])

    def test_04_readback_unreadable_rolls_back(self):
        ev = []
        conn = FakeConn(events=ev)
        asm._alpaca_req = _mock_alpaca(ev)
        asm._place_simple_stop = lambda env, sym, qty, sp: (ev.append(("HTTP", "POST", "/replace-stop")) or {"id": "rb1"})
        asm._classify_broker_protection = lambda env, sym, group_id=None: {"readable": False, "has_oco": False, "has_stop": False}
        r = asm.convert_to_oco({}, "AAPL", 10, 100.0, 110.0, "oldstop", conn=conn)
        self.assertEqual(r["status"], "ROLLED_BACK")
        self.assertIn("readback_unreadable", r["reason"])


class TestRepairSupervisor(unittest.TestCase):
    def setUp(self):
        import db_adapter
        self._saved = (db_adapter._get_conn, apr.get_env, asm._classify_broker_protection, asm._place_simple_stop)
        apr.get_env = lambda: {}

    def tearDown(self):
        import db_adapter
        db_adapter._get_conn, apr.get_env, asm._classify_broker_protection, asm._place_simple_stop = self._saved

    def _run(self, broker_state, apply=True, place_spy=None):
        import db_adapter
        conn = FakeConn(rows=[("AAPL", 10, 42.5, "oldstop")])
        db_adapter._get_conn = lambda: conn
        asm._classify_broker_protection = lambda env, sym, group_id=None: broker_state
        asm._place_simple_stop = place_spy or (lambda env, sym, qty, sp: {"id": "ns1"})
        return asm.repair_oco_replacing(apply=apply), conn

    def test_05_naked_replaces_stop(self):
        spy = {"n": 0}
        rep, conn = self._run({"readable": True, "has_oco": False, "has_stop": False},
                              place_spy=lambda env, sym, qty, sp: (spy.__setitem__("n", spy["n"] + 1) or {"id": "ns1"}))
        self.assertEqual(rep["naked_fixed"], 1)
        self.assertEqual(spy["n"], 1, "a protective stop must be re-placed for a naked OCO_REPLACING row")
        self.assertTrue(any("STOP_ONLY" in (str(e[1]) + str(e[2])) for e in conn.events if e[0] == "DB"))

    def test_06_oco_present_marks_active_no_replace(self):
        spy = {"n": 0}
        rep, conn = self._run({"readable": True, "has_oco": True, "has_stop": False, "stop_id": "s", "tp_id": "t"},
                              place_spy=lambda *a: (spy.__setitem__("n", spy["n"] + 1) or {"id": "x"}))
        self.assertEqual(rep["oco_confirmed"], 1)
        self.assertEqual(spy["n"], 0, "must not place a stop when an OCO already exists")
        self.assertTrue(any("OCO_ACTIVE" in str(e[1]) for e in conn.events if e[0] == "DB"))

    def test_07_standalone_stop_marks_restored(self):
        spy = {"n": 0}
        rep, _ = self._run({"readable": True, "has_oco": False, "has_stop": True, "stop_id": "s"},
                           place_spy=lambda *a: (spy.__setitem__("n", spy["n"] + 1) or {"id": "x"}))
        self.assertEqual(rep["stop_restored"], 1)
        self.assertEqual(spy["n"], 0)

    def test_08_unreadable_leaves_replacing_no_action(self):
        spy = {"n": 0}
        rep, conn = self._run({"readable": False, "has_oco": False, "has_stop": False},
                              place_spy=lambda *a: (spy.__setitem__("n", spy["n"] + 1) or {"id": "x"}))
        self.assertEqual(rep["unreadable"], 1)
        self.assertEqual(spy["n"], 0, "must never re-place a stop when the broker is unreadable (no naked guess)")
        self.assertFalse(any(("STOP_ONLY" in (str(e[1]) + str(e[2])) or "OCO_ACTIVE" in (str(e[1]) + str(e[2])))
                             for e in conn.events if e[0] == "DB"))


class TestReconcilerFixIsDbOnly(unittest.TestCase):
    def setUp(self):
        self._saved = (apr.get_env, apr.get_alpaca_positions, apr.get_alpaca_orders,
                       apr.get_db_connection, asm.run_oco_retrofit)
        apr.get_env = lambda: {}
        apr.get_alpaca_positions = lambda env: []
        apr.get_alpaca_orders = lambda env, status="open": []
        apr.get_db_connection = lambda: FakeConn(rows=[])

    def tearDown(self):
        (apr.get_env, apr.get_alpaca_positions, apr.get_alpaca_orders,
         apr.get_db_connection, asm.run_oco_retrofit) = self._saved

    def test_09_fix_alone_never_triggers_oco_mutation(self):
        calls = {"n": 0}
        asm.run_oco_retrofit = lambda apply=False: (calls.__setitem__("n", calls["n"] + 1) or {"converted": 0})
        apr.reconcile(apply_fixes=True, apply_oco_retrofit=False)
        self.assertEqual(calls["n"], 0, "--fix must NEVER call the OCO broker-mutating retrofit")

    def test_10_apply_oco_retrofit_is_explicit(self):
        calls = {"n": 0}
        asm.run_oco_retrofit = lambda apply=False: (calls.__setitem__("n", calls["n"] + 1) or {"converted": 0, "mode": "APPLIED"})
        apr.reconcile(apply_fixes=True, apply_oco_retrofit=True)
        self.assertEqual(calls["n"], 1, "the OCO retrofit must run only under the explicit flag")

    def test_11_retrofit_targets_paper_api(self):
        # paper-only: the broker base is the Alpaca PAPER endpoint, and there is NO Schwab/live HTTP host
        # anywhere in the stop manager (the word "schwab" appears only in explanatory prose, never a URL).
        src = (ROOT / "scripts" / "alpaca_stop_manager.py").read_text().lower()
        self.assertIn("paper-api.alpaca.markets", src)
        for host in ("api.schwabapi.com", "schwabapi.com", "live-api", "api.alpaca.markets/"):
            self.assertNotIn(host, src, f"stop manager must not reach a live/Schwab host ({host})")


class TestQtyFailClosed(unittest.TestCase):
    def setUp(self):
        import requests
        self._saved = (requests.get, requests.post)
        self._post_calls = {"n": 0}
        def _post(*a, **k):
            self._post_calls["n"] += 1
            class R: status_code = 200
            R.json = lambda self_=None: {"id": "o1"}
            return R()
        requests.post = _post

    def tearDown(self):
        import requests
        requests.get, requests.post = self._saved

    def _call(self, conn, requests_get):
        import requests
        requests.get = requests_get
        result = {"proposal_id": 1, "symbol": "AGNC"}
        p = {"symbol": "AGNC", "proposed_take_profit": 11.24}
        t = {"shares": 293}
        q = {"last_price": 10.97}
        return appa._apply_take_profit(result, conn, p, t, q, 1, confirm=True)

    def test_12_qty_read_exception_fails_closed(self):
        def boom(*a, **k): raise RuntimeError("network down")
        r = self._call(FakeConn(), boom)
        self.assertEqual(r["status"], "BROKER_QTY_UNKNOWN")
        self.assertEqual(r["action"], "DEFER_RECHECK")
        self.assertEqual(self._post_calls["n"], 0, "must NOT place a take-profit when qty is unreadable")

    def test_13_qty_read_non200_fails_closed(self):
        class R:
            status_code = 500
            def json(self): return {}
        r = self._call(FakeConn(), lambda *a, **k: R())
        self.assertEqual(r["status"], "BROKER_QTY_UNKNOWN")
        self.assertEqual(self._post_calls["n"], 0)

    def test_14_defer_is_bounded_not_endless(self):
        def boom(*a, **k): raise RuntimeError("still down")
        conn = FakeConn()
        last = None
        for _ in range(appa._MAX_QTY_RECHECKS + 1):
            last = self._call(conn, boom)
        self.assertEqual(last["action"], "GIVE_UP_OPERATOR_REVIEW",
                         "after the recheck cap the proposal must become terminal (no endless loop)")
        self.assertEqual(self._post_calls["n"], 0, "still never places an order")


if __name__ == "__main__":
    unittest.main(verbosity=2)
