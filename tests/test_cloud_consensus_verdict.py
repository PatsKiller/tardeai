#!/usr/bin/env python3
"""Tests for cloud_consensus_verdict.py — advisory dual-consensus verdicts.

Covers: qualifier exclusions (over-cap / unverified catalyst / expired), both-AGREE →
CLOUD_APPROVE, split/CAUTION/lane-failure → ESCALATED (fail-closed), daily cap, pause
flag, telegram 24h throttle, NO proposal-status mutation, forbidden-imports grep.
"""
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import cloud_consensus_verdict as ccv

SCRIPT_SRC = (Path(__file__).resolve().parent.parent / "scripts" / "cloud_consensus_verdict.py").read_text()


def _policy(**over):
    pol = {"daily_cap": 5, "enabled": True, "paused": False, "pause_reason": None}
    pol.update(over)
    return pol


def _lane(ok=True, verdict="AGREE", note="looks sound", error=None):
    d = {"ok": ok, "verdict": verdict, "assessment": note}
    if error:
        d["error"] = error
    return d


class TestQualifier(unittest.TestCase):
    def test_sql_excludes_unverified_catalyst_and_expired(self):
        sql = ccv.QUALIFIER_SQL
        self.assertIn("catalyst_verified IS TRUE", sql)
        self.assertIn("expires_at IS NULL OR expires_at > NOW()", sql)
        self.assertIn("'PENDING'", sql)
        self.assertIn("'APPROVED_FOR_PAPER_TEST'", sql)
        # 24h re-score dedup against our own verdict table
        self.assertIn("cloud_consensus_verdicts", sql)
        self.assertIn("24 hours", sql)

    def test_policy_cap_check_excludes_over_cap(self):
        fake = types.SimpleNamespace(evaluate_broker_promote=MagicMock(return_value={
            "warnings": ["Operator 500 sh vs policy cap 200 (binding=max_dollar_risk, engine=v2)"],
            "violations": [], "policy_max_shares": 200,
        }))
        prop = {"id": 1, "account": "schwab_taxable", "strategy_id": "momentum_scalp",
                "proposed_entry": 10, "proposed_stop": 9, "proposed_target1": 12,
                "proposed_shares": 500, "status": "PENDING"}
        with patch.dict(sys.modules, {"broker_promote_sizing": fake}):
            ok, reason = ccv.policy_cap_check(prop)
        self.assertFalse(ok)
        self.assertIn("outside policy caps", reason)

    def test_policy_cap_check_excludes_override_warning(self):
        fake = types.SimpleNamespace(evaluate_broker_promote=MagicMock(return_value={
            "warnings": ["Policy sizing cap is 0 (SIZE_TOO_SMALL) — operator override"],
            "violations": [], "policy_max_shares": 0,
        }))
        prop = {"id": 2, "account": "schwab_taxable", "proposed_entry": 10, "proposed_stop": 9,
                "proposed_target1": 12, "proposed_shares": 10, "status": "PENDING"}
        with patch.dict(sys.modules, {"broker_promote_sizing": fake}):
            ok, _ = ccv.policy_cap_check(prop)
        self.assertFalse(ok)

    def test_policy_cap_check_passes_within_cap(self):
        fake = types.SimpleNamespace(evaluate_broker_promote=MagicMock(return_value={
            "warnings": [], "violations": [], "policy_max_shares": 200,
        }))
        prop = {"id": 3, "account": "schwab_taxable", "proposed_entry": 10, "proposed_stop": 9,
                "proposed_target1": 12, "proposed_shares": 100, "status": "PENDING"}
        with patch.dict(sys.modules, {"broker_promote_sizing": fake}):
            ok, reason = ccv.policy_cap_check(prop)
        self.assertTrue(ok)
        self.assertIn("within policy cap", reason)

    def test_policy_cap_check_fails_closed_without_account(self):
        ok, reason = ccv.policy_cap_check({"id": 4, "account": None, "proposed_shares": 10,
                                           "proposed_entry": 10, "proposed_stop": 9, "proposed_target1": 12})
        self.assertFalse(ok)
        self.assertIn("fail-closed", reason)

    def test_policy_cap_check_fails_closed_on_evaluator_error(self):
        fake = types.SimpleNamespace(evaluate_broker_promote=MagicMock(side_effect=RuntimeError("boom")))
        prop = {"id": 5, "account": "schwab_taxable", "proposed_entry": 10, "proposed_stop": 9,
                "proposed_target1": 12, "proposed_shares": 10}
        with patch.dict(sys.modules, {"broker_promote_sizing": fake}):
            ok, reason = ccv.policy_cap_check(prop)
        self.assertFalse(ok)
        self.assertIn("fail-closed", reason)


class TestConsensusRule(unittest.TestCase):
    def test_both_agree_is_cloud_approve(self):
        v = ccv.compute_consensus({"grok": _lane(), "chatgpt": _lane(note="agree, disciplined setup")})
        self.assertEqual(v["consensus"], "CLOUD_APPROVE")
        self.assertEqual(v["grok_verdict"], "AGREE")
        self.assertEqual(v["chatgpt_verdict"], "AGREE")

    def test_split_is_escalated(self):
        v = ccv.compute_consensus({"grok": _lane(), "chatgpt": _lane(verdict="DISAGREE")})
        self.assertEqual(v["consensus"], "ESCALATED")

    def test_any_caution_is_escalated(self):
        v = ccv.compute_consensus({"grok": _lane(verdict="CAUTION"), "chatgpt": _lane()})
        self.assertEqual(v["consensus"], "ESCALATED")

    def test_lane_failure_is_escalated_fail_closed(self):
        v = ccv.compute_consensus({"grok": _lane(ok=False, error="lane unavailable"), "chatgpt": _lane()})
        self.assertEqual(v["consensus"], "ESCALATED")
        self.assertEqual(v["grok_verdict"], "LANE_FAILED")
        self.assertIn("lane unavailable", v["grok_note"])

    def test_both_lanes_missing_is_escalated(self):
        v = ccv.compute_consensus({})
        self.assertEqual(v["consensus"], "ESCALATED")

    def test_unknown_verdict_is_escalated(self):
        v = ccv.compute_consensus({"grok": _lane(verdict="UNKNOWN"), "chatgpt": _lane()})
        self.assertEqual(v["consensus"], "ESCALATED")


class TestRunGuardrails(unittest.TestCase):
    def test_pause_flag_halts_scoring(self):
        with patch.object(ccv, "load_policy", return_value=_policy(paused=True, pause_reason="operator hold")), \
             patch.object(ccv, "fetch_candidates") as fc, \
             patch.object(ccv, "score_proposal") as sp:
            out = ccv.run()
        self.assertFalse(out["ok"])
        self.assertIn("paused", out["reason"])
        fc.assert_not_called()
        sp.assert_not_called()

    def test_disabled_halts_scoring(self):
        with patch.object(ccv, "load_policy", return_value=_policy(enabled=False)), \
             patch.object(ccv, "fetch_candidates") as fc:
            out = ccv.run()
        self.assertFalse(out["ok"])
        fc.assert_not_called()

    def test_daily_cap_enforced_before_scoring(self):
        with patch.object(ccv, "load_policy", return_value=_policy(daily_cap=5)), \
             patch.object(ccv, "todays_verdict_count", return_value=5), \
             patch.object(ccv, "fetch_candidates") as fc, \
             patch.object(ccv, "score_proposal") as sp:
            out = ccv.run()
        self.assertEqual(out["scored"], 0)
        self.assertIn("daily cap", out["reason"])
        fc.assert_not_called()
        sp.assert_not_called()

    def test_daily_cap_enforced_mid_run(self):
        cands = [{"id": i, "symbol": f"SY{i}"} for i in range(1, 6)]
        with patch.object(ccv, "load_policy", return_value=_policy(daily_cap=5)), \
             patch.object(ccv, "todays_verdict_count", return_value=3), \
             patch.object(ccv, "fetch_candidates", return_value=cands), \
             patch.object(ccv, "policy_cap_check", return_value=(True, "within")), \
             patch.object(ccv, "score_proposal", return_value={
                 "consensus": "CLOUD_APPROVE", "grok_verdict": "AGREE", "grok_note": "",
                 "chatgpt_verdict": "AGREE", "chatgpt_note": ""}) as sp, \
             patch.object(ccv, "insert_verdict") as ins, \
             patch.object(ccv, "send_split_alert") as alert, \
             patch.object(ccv, "weekly_do_no_harm_check", return_value={"checked": True}):
            out = ccv.run()
        self.assertEqual(out["scored"], 2)          # cap 5 − 3 used = 2 remaining
        self.assertEqual(sp.call_count, 2)
        self.assertEqual(ins.call_count, 2)
        alert.assert_not_called()                    # CLOUD_APPROVE never alerts

    def test_split_escalates_inserts_and_alerts(self):
        cands = [{"id": 9, "symbol": "XYZ"}]
        split = {"consensus": "ESCALATED", "grok_verdict": "AGREE", "grok_note": "ok",
                 "chatgpt_verdict": "CAUTION", "chatgpt_note": "spread risk"}
        with patch.object(ccv, "load_policy", return_value=_policy()), \
             patch.object(ccv, "todays_verdict_count", return_value=0), \
             patch.object(ccv, "fetch_candidates", return_value=cands), \
             patch.object(ccv, "policy_cap_check", return_value=(True, "within")), \
             patch.object(ccv, "score_proposal", return_value=dict(split)), \
             patch.object(ccv, "insert_verdict") as ins, \
             patch.object(ccv, "send_split_alert", return_value=True) as alert, \
             patch.object(ccv, "weekly_do_no_harm_check", return_value={"checked": True}):
            out = ccv.run()
        self.assertEqual(out["scored"], 1)
        alert.assert_called_once()
        pid, verdict, _reason = ins.call_args[0]
        self.assertEqual(pid, 9)
        self.assertEqual(verdict["consensus"], "ESCALATED")

    def test_dry_run_never_calls_lanes_or_writes(self):
        cands = [{"id": 7, "symbol": "ABC"}]
        with patch.object(ccv, "load_policy", return_value=_policy()), \
             patch.object(ccv, "todays_verdict_count", return_value=0), \
             patch.object(ccv, "fetch_candidates", return_value=cands), \
             patch.object(ccv, "policy_cap_check", return_value=(True, "within")), \
             patch.object(ccv, "score_proposal") as sp, \
             patch.object(ccv, "insert_verdict") as ins, \
             patch.object(ccv, "send_split_alert") as alert, \
             patch.object(ccv, "weekly_do_no_harm_check") as dnh:
            out = ccv.run(dry_run=True)
        self.assertTrue(out["dry_run"])
        sp.assert_not_called()
        ins.assert_not_called()
        alert.assert_not_called()
        dnh.assert_not_called()

    def test_over_cap_candidate_skipped_without_scoring(self):
        cands = [{"id": 8, "symbol": "BIG"}]
        with patch.object(ccv, "load_policy", return_value=_policy()), \
             patch.object(ccv, "todays_verdict_count", return_value=0), \
             patch.object(ccv, "fetch_candidates", return_value=cands), \
             patch.object(ccv, "policy_cap_check", return_value=(False, "outside policy caps: Operator 500 sh vs policy cap 200")), \
             patch.object(ccv, "score_proposal") as sp, \
             patch.object(ccv, "insert_verdict") as ins, \
             patch.object(ccv, "weekly_do_no_harm_check", return_value={"checked": True}):
            out = ccv.run()
        self.assertEqual(out["scored"], 0)
        self.assertEqual(len(out["skipped"]), 1)
        sp.assert_not_called()
        ins.assert_not_called()


class TestTelegramThrottle(unittest.TestCase):
    def test_throttled_within_24h(self):
        with patch.object(ccv, "recent_escalation_exists", return_value=True), \
             patch.object(ccv, "_send_telegram") as tg:
            sent = ccv.send_split_alert(11, "XYZ", {"grok_verdict": "AGREE", "chatgpt_verdict": "DISAGREE"})
        self.assertFalse(sent)
        tg.assert_not_called()

    def test_sends_once_when_not_throttled(self):
        with patch.object(ccv, "recent_escalation_exists", return_value=False), \
             patch.object(ccv, "_send_telegram") as tg:
            sent = ccv.send_split_alert(11, "XYZ", {"grok_verdict": "AGREE", "chatgpt_verdict": "DISAGREE"})
        self.assertTrue(sent)
        tg.assert_called_once()
        msg = tg.call_args[0][0]
        self.assertIn("Cloud consensus split on #11 XYZ", msg)
        self.assertIn("grok=AGREE", msg)
        self.assertIn("chatgpt=DISAGREE", msg)


class TestDoNoHarmKillSwitch(unittest.TestCase):
    def test_pauses_on_win_rate_degradation(self):
        def fake_exec(sql, params=None, fetch=None):
            if "paper_trades" in sql:
                return [{"cloud_approved": True, "n": 12, "win_rate": 30.0},
                        {"cloud_approved": False, "n": 40, "win_rate": 55.0}]
            return []
        pol = _policy()
        with patch.object(ccv, "_exec", side_effect=fake_exec), \
             patch.object(ccv, "save_policy") as sp, \
             patch.object(ccv, "_send_telegram") as tg:
            out = ccv.weekly_do_no_harm_check(pol)
        self.assertIsNotNone(out["degraded"])
        self.assertTrue(pol["paused"])
        self.assertIn("do-no-harm", pol["pause_reason"])
        sp.assert_called_once()
        tg.assert_called_once()

    def test_pauses_on_lane_disagreement(self):
        def fake_exec(sql, params=None, fetch=None):
            if "paper_trades" in sql:
                return []
            return [{"consensus": "ESCALATED"}] * 7 + [{"consensus": "CLOUD_APPROVE"}] * 3
        pol = _policy()
        with patch.object(ccv, "_exec", side_effect=fake_exec), \
             patch.object(ccv, "save_policy"), \
             patch.object(ccv, "_send_telegram"):
            out = ccv.weekly_do_no_harm_check(pol)
        self.assertIn("disagreement", out["degraded"])
        self.assertTrue(pol["paused"])

    def test_healthy_stats_do_not_pause(self):
        def fake_exec(sql, params=None, fetch=None):
            if "paper_trades" in sql:
                return [{"cloud_approved": True, "n": 12, "win_rate": 60.0},
                        {"cloud_approved": False, "n": 40, "win_rate": 55.0}]
            return [{"consensus": "CLOUD_APPROVE"}] * 8 + [{"consensus": "ESCALATED"}] * 2
        pol = _policy()
        with patch.object(ccv, "_exec", side_effect=fake_exec), \
             patch.object(ccv, "save_policy") as sp, \
             patch.object(ccv, "_send_telegram") as tg:
            out = ccv.weekly_do_no_harm_check(pol)
        self.assertIsNone(out["degraded"])
        self.assertFalse(pol["paused"])
        sp.assert_not_called()
        tg.assert_not_called()


class TestAdvisoryOnlyGuarantees(unittest.TestCase):
    def test_no_proposal_status_mutation_in_source(self):
        """The pipeline must never change proposal status — only SELECT from
        paper_trade_proposals and INSERT into cloud_consensus_verdicts."""
        self.assertNotRegex(SCRIPT_SRC, re.compile(r"UPDATE\s+paper_trade_proposals", re.IGNORECASE))
        self.assertNotRegex(SCRIPT_SRC, re.compile(r"DELETE\s+FROM\s+paper_trade_proposals", re.IGNORECASE))
        for m in re.finditer(r"INSERT\s+INTO\s+(\w+)", SCRIPT_SRC, re.IGNORECASE):
            self.assertEqual(m.group(1), "cloud_consensus_verdicts")
        self.assertNotRegex(SCRIPT_SRC, re.compile(r"\bUPDATE\s+\w+\s+SET\b", re.IGNORECASE))

    def test_forbidden_imports_grep(self):
        """No brokers/schwab/alpaca/approval_service/execution_guard imports (2FA + gates untouched)."""
        import_lines = [ln for ln in SCRIPT_SRC.splitlines()
                        if re.match(r"\s*(import|from)\s+", ln)]
        forbidden = re.compile(r"\b(brokers|approval_service|execution_guard|schwab|alpaca|protective)\b",
                               re.IGNORECASE)
        for ln in import_lines:
            self.assertIsNone(forbidden.search(ln), f"forbidden import: {ln.strip()}")

    def test_run_never_touches_proposal_rows(self):
        """End-to-end run() with a scored proposal: every SQL statement executed is either a
        SELECT or an INSERT into cloud_consensus_verdicts — proposals are never mutated."""
        executed = []

        def spy_exec(sql, params=None, fetch=None):
            executed.append(" ".join(str(sql).split()))
            if "COUNT(*)" in sql:
                return {"n": 0}
            if "SELECT 1" in sql:
                return None
            if sql.strip().upper().startswith("SELECT"):
                return []
            return True

        with patch.object(ccv, "_exec", side_effect=spy_exec), \
             patch.object(ccv, "load_policy", return_value=_policy()), \
             patch.object(ccv, "fetch_candidates", return_value=[{"id": 21, "symbol": "QQQ"}]), \
             patch.object(ccv, "policy_cap_check", return_value=(True, "within")), \
             patch.object(ccv, "score_proposal", return_value={
                 "consensus": "ESCALATED", "grok_verdict": "AGREE", "grok_note": "",
                 "chatgpt_verdict": "LANE_FAILED", "chatgpt_note": "down"}), \
             patch.object(ccv, "_send_telegram"), \
             patch.object(ccv, "weekly_do_no_harm_check", return_value={"checked": True}):
            ccv.run()
        for sql in executed:
            up = sql.upper()
            if up.startswith("INSERT"):
                self.assertIn("CLOUD_CONSENSUS_VERDICTS", up)
            else:
                self.assertTrue(up.startswith("SELECT"), f"unexpected non-SELECT: {sql[:80]}")
            self.assertNotIn("UPDATE PAPER_TRADE_PROPOSALS", up)


if __name__ == "__main__":
    unittest.main()
