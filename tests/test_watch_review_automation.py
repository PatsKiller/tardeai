#!/usr/bin/env python3
"""Watch Intelligence Maria/CIO automated review pipeline — phase 1/2 (zero provider calls)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

ET = ZoneInfo("America/New_York")


class TestModelPolicyExact(unittest.TestCase):
    def test_maria_spec(self):
        from lib.watch_review_policy_ledger import MARIA_SPEC, MARIA_PROCESS_ID
        self.assertEqual(MARIA_PROCESS_ID, "watchlist_maria_flash_narrative")
        self.assertEqual(MARIA_SPEC["model"], "deepseek-v4-flash")
        self.assertEqual(MARIA_SPEC["policy"], "FAST")
        self.assertEqual(MARIA_SPEC["thinking"], "off")
        self.assertFalse(MARIA_SPEC["fallback_allowed"])
        self.assertEqual(MARIA_SPEC["provider"], "deepseek")

    def test_cio_spec(self):
        from lib.watch_review_policy_ledger import CIO_SPEC, CIO_PROCESS_ID
        self.assertEqual(CIO_PROCESS_ID, "watchlist_cio_synthesis")
        self.assertEqual(CIO_SPEC["model"], "deepseek-v4-pro")
        self.assertEqual(CIO_SPEC["policy"], "PRO")
        self.assertEqual(CIO_SPEC["thinking"], "off")
        self.assertFalse(CIO_SPEC["fallback_allowed"])

    def test_registry_cio_allows_pro(self):
        reg = json.loads((ROOT / "config/llm_process_registry.json").read_text())
        by_id = {p["id"]: p for p in reg["processes"]}
        cio = by_id["watchlist_cio_synthesis"]
        self.assertIn("PRO", cio["deepseek_allowed_policies"])
        self.assertEqual(cio.get("fallback_allowed"), False)
        maria = by_id["watchlist_maria_flash_narrative"]
        self.assertEqual(maria["deepseek_default_policy"], "FAST")
        self.assertEqual(maria.get("fallback_allowed"), False)


class TestSchedule(unittest.TestCase):
    def test_mwf_et(self):
        from lib.watch_review_pipeline import next_mwf_at, schedule_times, SCHEDULE_DAYS
        # Wednesday 2026-08-05 10:00 ET → next Maria is same day 16:05 if before, else Friday
        wed = datetime(2026, 8, 5, 10, 0, tzinfo=ET)
        m = next_mwf_at(16, 5, after=wed)
        self.assertEqual(m.weekday(), 2)  # Wednesday
        self.assertEqual(m.hour, 16)
        self.assertEqual(m.minute, 5)
        after = datetime(2026, 8, 5, 16, 30, tzinfo=ET)
        m2 = next_mwf_at(16, 5, after=after)
        self.assertEqual(m2.weekday(), 4)  # Friday
        cio = next_mwf_at(16, 20, after=wed)
        self.assertGreater(cio, next_mwf_at(16, 5, after=wed))
        times = schedule_times()
        self.assertEqual(times["timezone"], "America/New_York")
        self.assertTrue(times["maria_precedes_cio"])
        self.assertEqual(SCHEDULE_DAYS, frozenset({"Monday", "Wednesday", "Friday"}))


class TestEventTrigger(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        # patch event state dir
        import lib.watch_review_pipeline as p
        import lib.watch_review_policy_ledger as ledger
        self._p_event = p.EVENT_STATE_DIR
        self._l_event = ledger.EVENT_STATE_DIR
        p.EVENT_STATE_DIR = self.root / "event_state"
        ledger.EVENT_STATE_DIR = self.root / "event_state"
        p.EVENT_STATE_DIR.mkdir(parents=True)

    def tearDown(self):
        import lib.watch_review_pipeline as p
        import lib.watch_review_policy_ledger as ledger
        p.EVENT_STATE_DIR = self._p_event
        ledger.EVENT_STATE_DIR = self._l_event
        self._tmpdir.cleanup()

    def test_plus_7_triggers(self):
        from lib.watch_review_pipeline import evaluate_event_trigger
        r = evaluate_event_trigger("TEST", current_price=107, close_5_sessions_ago=100)
        self.assertAlmostEqual(r["move_pct"], 0.07)
        self.assertTrue(r["triggered"])
        self.assertEqual(r["reason_code"], "ROLLING_5_SESSION_MOVE_GE_7PCT")
        self.assertEqual(r["provider_calls"], 0)

    def test_minus_7_triggers(self):
        from lib.watch_review_pipeline import evaluate_event_trigger
        r = evaluate_event_trigger("TESTM", current_price=90.0, close_5_sessions_ago=100.0)
        self.assertLessEqual(r["move_pct"], -0.07)
        self.assertTrue(r["triggered"])
        # exact boundary (-7%): prior 100 → current 93
        r2 = evaluate_event_trigger("TESTM2", current_price=93.0, close_5_sessions_ago=100.0)
        self.assertGreaterEqual(abs(r2["move_pct"]), 0.07 - 1e-9)
        self.assertTrue(r2["triggered"])

    def test_6_99_no_trigger(self):
        from lib.watch_review_pipeline import evaluate_event_trigger
        r = evaluate_event_trigger("TEST2", current_price=106.99, close_5_sessions_ago=100)
        self.assertFalse(r["triggered"])
        self.assertGreater(r["abs_move_pct"], 0.06)
        self.assertLess(r["abs_move_pct"], 0.07)

    def test_stale_price_rejected(self):
        from lib.watch_review_pipeline import evaluate_event_trigger
        stale = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        r = evaluate_event_trigger(
            "STALE", current_price=110, close_5_sessions_ago=100, current_as_of=stale,
        )
        self.assertIsNotNone(r["reject_reason"])
        self.assertFalse(r["triggered"])

    def test_no_retrigger_while_above(self):
        from lib.watch_review_pipeline import evaluate_event_trigger
        r1 = evaluate_event_trigger("EDGE", current_price=110, close_5_sessions_ago=100)
        self.assertTrue(r1["triggered"])
        r2 = evaluate_event_trigger("EDGE", current_price=111, close_5_sessions_ago=100)
        self.assertFalse(r2["triggered"])  # still above, no edge

    def test_24h_cooldown(self):
        from lib.watch_review_pipeline import evaluate_event_trigger, EVENT_STATE_DIR
        r1 = evaluate_event_trigger("CD", current_price=110, close_5_sessions_ago=100)
        self.assertTrue(r1["triggered"])
        # drop below then cross again immediately — cooldown blocks
        evaluate_event_trigger("CD", current_price=100, close_5_sessions_ago=100)
        r3 = evaluate_event_trigger("CD", current_price=110, close_5_sessions_ago=100)
        self.assertFalse(r3["triggered"])
        self.assertTrue(r3.get("cooldown_active"))


class TestPolicyLedger(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        import lib.watch_review_policy_ledger as L
        self.L = L
        self._paths = {}
        for name in ("LEDGER_ROOT", "POLICIES_DIR", "EXEC_DIR", "JOBS_DIR", "EVENT_STATE_DIR", "NO_CALL_DIR"):
            self._paths[name] = getattr(L, name)
        L.LEDGER_ROOT = self.root / "ledger"
        L.POLICIES_DIR = L.LEDGER_ROOT / "policies"
        L.EXEC_DIR = L.LEDGER_ROOT / "execution_authorizations"
        L.JOBS_DIR = L.LEDGER_ROOT / "jobs"
        L.EVENT_STATE_DIR = L.LEDGER_ROOT / "event_state"
        L.NO_CALL_DIR = self.root / "no_call"

    def tearDown(self):
        L = self.L
        for name, val in self._paths.items():
            setattr(L, name, val)
        self._tmpdir.cleanup()

    def test_persist_and_validate(self):
        with mock.patch.object(self.L, "containment_required_ok", return_value=(True, "containment_active")):
            pol = self.L.persist_policy(self.L.build_intended_policy())
            ok, reason = self.L.validate_policy(pol)
            self.assertTrue(ok, reason)
            self.assertFalse(pol["workers_enabled"])
            self.assertFalse(pol["event_watcher_enabled"])
            self.assertFalse(pol["fallback_allowed"])
            self.assertEqual(pol["authorization_policy_id"], self.L.CANONICAL_POLICY_ID)

    def test_expired_rejected(self):
        with mock.patch.object(self.L, "containment_required_ok", return_value=(True, "ok")):
            pol = self.L.build_intended_policy()
            pol["expires_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            self.L.persist_policy(pol)
            ok, reason = self.L.validate_policy(self.L.load_policy())
            self.assertFalse(ok)
            self.assertEqual(reason, "POLICY_EXPIRED")

    def test_revoked_rejected(self):
        with mock.patch.object(self.L, "containment_required_ok", return_value=(True, "ok")):
            self.L.persist_policy(self.L.build_intended_policy())
            self.L.revoke_policy(self.L.CANONICAL_POLICY_ID, "test")
            ok, reason = self.L.validate_policy(self.L.load_policy())
            self.assertFalse(ok)
            self.assertIn("REVOKED", reason)

    def test_execution_auth_and_reuse(self):
        with mock.patch.object(self.L, "containment_required_ok", return_value=(True, "ok")):
            self.L.persist_policy(self.L.build_intended_policy())
            ex = self.L.create_execution_authorization(
                policy_id=self.L.CANONICAL_POLICY_ID,
                symbol="AAPL",
                agent_id="maria",
                input_snapshot_id="snap1",
                input_hash="hash1",
                trigger_reason="SCHEDULED_MWF",
            )
            ok, reason, _ = self.L.validate_execution_authorization(
                ex["execution_authorization_id"],
                symbol="AAPL",
                agent_id="maria",
                process_id="watchlist_maria_flash_narrative",
                provider="deepseek",
                model="deepseek-v4-flash",
                policy="FAST",
                input_hash="hash1",
            )
            self.assertTrue(ok, reason)
            # input mismatch
            ok2, reason2, _ = self.L.validate_execution_authorization(
                ex["execution_authorization_id"],
                symbol="AAPL",
                agent_id="maria",
                process_id="watchlist_maria_flash_narrative",
                provider="deepseek",
                model="deepseek-v4-flash",
                policy="FAST",
                input_hash="WRONG",
            )
            self.assertFalse(ok2)
            self.assertEqual(reason2, "INPUT_HASH_MISMATCH")
            # consume then reuse
            self.L.mark_execution_consumed(ex["execution_authorization_id"], provider_request_reference="req-1")
            ok3, reason3, _ = self.L.validate_execution_authorization(
                ex["execution_authorization_id"],
                symbol="AAPL",
                agent_id="maria",
                process_id="watchlist_maria_flash_narrative",
                provider="deepseek",
                model="deepseek-v4-flash",
                policy="FAST",
                input_hash="hash1",
            )
            self.assertFalse(ok3)
            self.assertEqual(reason3, "EXECUTION_AUTHORIZATION_REUSED")

    def test_process_mismatch(self):
        with mock.patch.object(self.L, "containment_required_ok", return_value=(True, "ok")):
            self.L.persist_policy(self.L.build_intended_policy())
            ex = self.L.create_execution_authorization(
                policy_id=self.L.CANONICAL_POLICY_ID,
                symbol="MSFT",
                agent_id="cio",
                input_snapshot_id="s",
                input_hash="h",
                trigger_reason="EVENT",
            )
            ok, reason, _ = self.L.validate_execution_authorization(
                ex["execution_authorization_id"],
                symbol="MSFT",
                agent_id="cio",
                process_id="watchlist_maria_flash_narrative",  # wrong
                provider="deepseek",
                model="deepseek-v4-pro",
                policy="PRO",
                input_hash="h",
            )
            self.assertFalse(ok)
            self.assertEqual(reason, "PROCESS_MISMATCH")


class TestPipelineGuards(unittest.TestCase):
    def test_cio_requires_maria(self):
        from lib.watch_review_pipeline import cio_may_run
        with mock.patch("lib.data_broker.watch_domains.load_review_artifacts", return_value={
            "maria": {"status": "NOT_RUN", "reason_code": "NOT_SCHEDULED"},
        }):
            ok, reason = cio_may_run("ZZZZ")
            self.assertFalse(ok)
            self.assertEqual(reason, "MARIA_PREREQUISITE_MISSING")

    def test_no_call_artifact(self):
        import tempfile
        from pathlib import Path
        import lib.watch_review_pipeline as p
        import lib.watch_review_policy_ledger as L
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = L.NO_CALL_DIR
            L.NO_CALL_DIR = root
            p.NO_CALL_DIR = root
            try:
                rec = p.write_no_call_artifact(
                    symbol="XYZ",
                    agent_id="maria",
                    input_hash="abc",
                    process_id="watchlist_maria_flash_narrative",
                    trigger_reason="SCHEDULED_MWF",
                )
                self.assertEqual(rec["status"], "NOT_RUN")
                self.assertEqual(rec["reason_code"], "NO_MATERIAL_CHANGE_NO_CALL")
                self.assertIsNone(rec["provider"])
                self.assertIsNone(rec["model"])
                self.assertEqual(rec["executed_policy"], "NO_CALL")
                self.assertEqual(rec["estimated_cost_usd"], 0.0)
            finally:
                L.NO_CALL_DIR = old
                p.NO_CALL_DIR = old

    def test_plan_zero_provider_calls(self):
        from lib.watch_review_pipeline import plan_jobs
        import lib.watch_review_policy_ledger as L
        with mock.patch.object(L, "containment_required_ok", return_value=(True, "ok")):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                olds = {}
                for name in ("LEDGER_ROOT", "POLICIES_DIR", "EXEC_DIR", "JOBS_DIR", "EVENT_STATE_DIR"):
                    olds[name] = getattr(L, name)
                L.LEDGER_ROOT = root / "ledger"
                L.POLICIES_DIR = L.LEDGER_ROOT / "policies"
                L.EXEC_DIR = L.LEDGER_ROOT / "execution_authorizations"
                L.JOBS_DIR = L.LEDGER_ROOT / "jobs"
                L.EVENT_STATE_DIR = L.LEDGER_ROOT / "event_state"
                try:
                    L.persist_policy(L.build_intended_policy())
                    cards = [
                        {"symbol": "AAA", "held": True, "trade_ai_state": "WAIT", "last": 10, "street_rating": "BUY"},
                        {"symbol": "BBB", "starred": True, "trade_ai_state": "READY", "last": 11},
                        {"symbol": "CCC", "trade_ai_state": "AVOID", "last": 12},
                    ]
                    with mock.patch("lib.data_broker.watch_domains.load_review_artifacts", return_value={}):
                        plan = plan_jobs(cards, dry_run=True)
                    self.assertTrue(plan["ok"])
                    self.assertEqual(plan["provider_calls"], 0)
                    self.assertFalse(plan["workers_enabled"])
                    # AVOID excluded
                    syms = {j["symbol"] for j in plan["jobs"]}
                    self.assertNotIn("CCC", syms)
                finally:
                    for name, val in olds.items():
                        setattr(L, name, val)


class TestCecoQuarantinePreserved(unittest.TestCase):
    def test_ceco_still_quarantined(self):
        from lib.data_broker.watch_domains import load_review_artifacts, QUARANTINE
        if not QUARANTINE.exists() or not any(QUARANTINE.glob("CECO_*.json")):
            self.skipTest("CECO quarantine not present in this worktree data")
        arts = load_review_artifacts("CECO")
        for a in ("cio", "maria"):
            self.assertEqual(arts[a].get("status"), "NOT_RUN")
            self.assertEqual(arts[a].get("reason_code"), "UNVERIFIED_OPERATOR_AUTHORIZATION")
            self.assertEqual(arts[a].get("artifact_disposition"), "QUARANTINED")

    def test_no_unquarantine_in_source(self):
        src = (ROOT / "scripts/lib/watch_review_policy_ledger.py").read_text()
        self.assertNotIn("unquarantine", src.lower())


class TestWorkerDisabled(unittest.TestCase):
    def test_execute_blocked(self):
        import subprocess
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts/run_watch_review_workers.py"), "--mode", "execute", "--allow-execute"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(ROOT / "scripts")},
        )
        self.assertNotEqual(r.returncode, 0)
        body = json.loads(r.stdout or "{}")
        self.assertEqual(body.get("provider_calls"), 0)


class TestUiDoesNotHardcodeProviderWhenIncomplete(unittest.TestCase):
    def test_review_box_none_when_not_complete(self):
        ui = (ROOT / "apps/command-center-v3/src/pages/WatchIntelligenceUnified.tsx").read_text()
        self.assertIn("Provider NONE · Model NONE · Policy NO_CALL", ui)
        self.assertIn("complete ? String(rev?.model", ui)


if __name__ == "__main__":
    unittest.main()
