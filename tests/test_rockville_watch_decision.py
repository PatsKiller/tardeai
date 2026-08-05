#!/usr/bin/env python3
"""Rockville decision-state + FTH regression tests."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.rockville.decision_projection import (  # noqa: E402
    INVALID_MECHANICS_STATES,
    assert_no_mechanics_on_invalid,
    project_watch_decision,
)
from lib.rockville.model_policy import (  # noqa: E402
    EXACT_FLASH,
    EXACT_PRO,
    resolve_policy,
    validate_exact_model,
)
from lib.rockville.material_fingerprint import (  # noqa: E402
    build_symbol_material_fingerprint,
    build_watchlist_material_hash,
    is_quote_noise_only,
)
from lib.rockville.cio_scheduler import (  # noqa: E402
    evaluate_cio_trigger,
    publish_no_material_change,
    mark_complete,
    mark_in_flight,
    STATE_PATH,
    ARTIFACTS_DIR,
)
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
FIXTURE = ROOT / "tests" / "fixtures" / "rockville" / "ROCKVILLE_FTH_REGRESSION_FIXTURE.json"


class TestFthRegression(unittest.TestCase):
    def setUp(self):
        self.fx = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fth_primary_is_deterministic_fail_not_wait(self):
        dec = project_watch_decision(self.fx["packet"], self.fx["action_policy"], symbol="FTH")
        exp = self.fx["expected_projection"]
        self.assertEqual(dec["primary_state"], "DETERMINISTIC_FAIL")
        self.assertNotIn(dec["primary_state"], exp["must_not_primary_state"])
        self.assertEqual(dec["allowed_action_now"], "NO TRADE ACTION")
        self.assertFalse(dec["proposal_allowed"])
        self.assertFalse(dec["current_mechanics_visible"])
        for k, v in exp["visibility"].items():
            self.assertFalse(dec["visibility"][k], msg=k)
        msgs = " ".join(b["message"] for b in dec["blockers"])
        for sub in exp["blocker_substrings"]:
            self.assertIn(sub, msgs)
        assert_no_mechanics_on_invalid(dec)

    def test_fth_does_not_expose_trigger_as_current(self):
        dec = project_watch_decision(self.fx["packet"], self.fx["action_policy"])
        self.assertIsNone(dec.get("current_mechanics"))
        hist = dec.get("history_mechanics_not_current") or {}
        self.assertEqual(hist.get("label"), "NOT CURRENT")

    def test_fth_identity_is_faeth_not_fate(self):
        """Permanent FTH/FATE anti-cross-map fixture."""
        company = self.fx.get("company") or ""
        self.assertIn("Faeth", company)
        self.assertNotIn("Fate Therapeutics", company)
        for bad in self.fx.get("company_must_not") or []:
            self.assertNotIn(bad, company)
        # API card path
        sys.path.insert(0, str(ROOT / "scripts"))
        import api_v3_watch_rockville as rv
        card = rv._card_from_fixture(self.fx)
        self.assertEqual(card["symbol"], "FTH")
        self.assertIn("Faeth", card["company"] or "")
        self.assertNotIn("Fate Therapeutics", card["company"] or "")
        # market fields present (live or fixture fallback)
        self.assertIsNotNone(card.get("last"))
        self.assertIsNotNone(card.get("day_change_pct"))


class TestDecisionStates(unittest.TestCase):
    def _pkt(self, **kwargs):
        base = {
            "symbol": "TEST",
            "ownership": {"held": False},
            "ticket_review": {"tickets_validated": True, "reconciled": {"state": "OK", "proposal_allowed": True}},
            "current_actionable_plan": {
                "trigger": 10,
                "invalidation": 8,
                "entry_zone": {"lo": 9, "hi": 10},
                "stop_price": 8,
                "targets": [12],
                "risk_reward": 2,
                "ticket_validation": {"state": "PASS", "ticket_hash": "h"},
            },
            "action_policy": {"state": "READY", "allowed": True, "action": "PROPOSE_ENTRY"},
        }
        base.update(kwargs)
        return base

    def test_ready_can_show_mechanics(self):
        dec = project_watch_decision(self._pkt(), self._pkt()["action_policy"])
        self.assertEqual(dec["primary_state"], "READY")
        self.assertTrue(dec["current_mechanics_visible"])
        self.assertTrue(dec["proposal_allowed"])

    def test_blocked_zero_mechanics(self):
        pkt = self._pkt()
        pkt["action_policy"] = {"state": "BLOCKED", "allowed": False}
        pkt["event_state"] = {"earnings": {"state": "BLOCK"}}
        dec = project_watch_decision(pkt, pkt["action_policy"])
        self.assertEqual(dec["primary_state"], "BLOCKED")
        assert_no_mechanics_on_invalid(dec)

    def test_stale_zero_mechanics(self):
        pkt = self._pkt()
        pkt["ticket_review"]["reconciled"]["state"] = "STALE_AFTER_REVIEW"
        pkt["action_policy"] = {"state": "STALE", "allowed": False}
        dec = project_watch_decision(pkt, pkt["action_policy"])
        self.assertEqual(dec["primary_state"], "STALE")
        assert_no_mechanics_on_invalid(dec)

    def test_managing_held(self):
        pkt = self._pkt(ownership={"held": True}, position={"shares": 10, "cost_basis": 5})
        dec = project_watch_decision(pkt, pkt["action_policy"])
        self.assertEqual(dec["primary_state"], "MANAGING")
        self.assertEqual(dec["allowed_action_now"], "VIEW POSITION PLAN")

    def test_llm_cannot_force_ready_on_fail(self):
        fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
        pkt = fx["packet"]
        pkt["llm_override_state"] = "READY"
        pkt["reflective_force_ready"] = True
        dec = project_watch_decision(pkt, fx["action_policy"])
        self.assertEqual(dec["primary_state"], "DETERMINISTIC_FAIL")
        self.assertFalse(dec["proposal_allowed"])


class TestModelPolicy(unittest.TestCase):
    def test_exact_flash(self):
        pol = resolve_policy("WATCH_FAST")
        self.assertEqual(pol["model"], EXACT_FLASH)
        self.assertFalse(pol["thinking"])

    def test_exact_pro_cio(self):
        pol = resolve_policy("CIO_DAILY_PRO")
        self.assertEqual(pol["model"], EXACT_PRO)
        self.assertTrue(pol["thinking"])
        self.assertEqual(pol["effort"], "high")

    def test_reject_ambiguous(self):
        for bad in ("deepseek-v4", "deepseek-chat", "deepseek-reasoner", "pro", "fast"):
            with self.assertRaises(ValueError):
                validate_exact_model(bad)


class TestFingerprint(unittest.TestCase):
    def test_quote_noise_does_not_change_hash(self):
        a = build_symbol_material_fingerprint({
            "symbol": "ABC",
            "primary_state": "WAIT",
            "last": 10.0,
            "quality": {"blockers": []},
            "decision": {"primary_state": "WAIT", "proposal_allowed": False},
        })
        b = build_symbol_material_fingerprint({
            "symbol": "ABC",
            "primary_state": "WAIT",
            "last": 10.05,  # quote noise
            "quality": {"blockers": []},
            "decision": {"primary_state": "WAIT", "proposal_allowed": False},
        })
        self.assertTrue(is_quote_noise_only(a, b))
        self.assertEqual(
            build_watchlist_material_hash([a]),
            build_watchlist_material_hash([b]),
        )

    def test_state_transition_dirties(self):
        a = build_symbol_material_fingerprint({
            "symbol": "ABC",
            "decision": {"primary_state": "WAIT", "proposal_allowed": False},
        })
        b = build_symbol_material_fingerprint({
            "symbol": "ABC",
            "decision": {"primary_state": "READY", "proposal_allowed": True},
        })
        self.assertNotEqual(a["material_fingerprint"], b["material_fingerprint"])


class TestCioScheduler(unittest.TestCase):
    def setUp(self):
        # isolate state
        if STATE_PATH.exists():
            STATE_PATH.write_text("{}", encoding="utf-8")

    def test_no_change_zero_provider_calls(self):
        mh = "a" * 64
        # first: dirties
        d1 = evaluate_cio_trigger(mh, now=datetime(2026, 8, 4, 16, 20, tzinfo=ET), force=False)
        # clear dirty by publishing no-change after setting dirty false path
        # set state dirty false with same hash
        from lib.rockville import cio_scheduler as cs
        st = {"last_material_hash": mh, "dirty": False, "days": {}}
        STATE_PATH.write_text(json.dumps(st), encoding="utf-8")
        d2 = evaluate_cio_trigger(mh, now=datetime(2026, 8, 4, 16, 20, tzinfo=ET))
        self.assertEqual(d2.action, "SKIP_NO_MATERIAL_CHANGE")
        self.assertFalse(d2.provider_call_allowed)
        art = publish_no_material_change(mh, now=datetime(2026, 8, 4, 16, 20, tzinfo=ET))
        self.assertEqual(art["status"], "NO_MATERIAL_CHANGE")
        self.assertEqual(art["usage"]["actual_cost_usd"], 0.0)
        # Truthful no-call provenance — never default to DeepSeek
        prov = art["provenance"]
        self.assertIsNone(prov.get("provider"))
        self.assertIsNone(prov.get("model"))
        self.assertEqual(prov.get("policy"), "NO_CALL")
        self.assertFalse(prov.get("provider_call_occurred"))
        self.assertNotEqual(prov.get("provider"), "deepseek")
        self.assertNotEqual(prov.get("model"), "deepseek-v4-pro")

    def test_duplicate_invocation_locked(self):
        mh = "b" * 64
        STATE_PATH.write_text(json.dumps({"last_material_hash": "old", "dirty": True, "days": {}}), encoding="utf-8")
        d = evaluate_cio_trigger(mh, now=datetime(2026, 8, 4, 16, 20, tzinfo=ET))
        self.assertEqual(d.action, "RUN")
        mark_in_flight(d)
        d2 = evaluate_cio_trigger(mh, now=datetime(2026, 8, 4, 16, 20, tzinfo=ET))
        self.assertEqual(d2.action, "SKIP_LOCKED")
        self.assertFalse(d2.provider_call_allowed)

    def test_already_complete_no_second_call(self):
        mh = "c" * 64
        STATE_PATH.write_text(json.dumps({
            "last_material_hash": mh,
            "dirty": True,
            "days": {
                "2026-08-04": {
                    "status": "COMPLETE",
                    "artifact_id": "art-1",
                }
            },
        }), encoding="utf-8")
        d = evaluate_cio_trigger(mh, now=datetime(2026, 8, 4, 16, 20, tzinfo=ET))
        self.assertEqual(d.action, "SKIP_ALREADY_COMPLETE")
        self.assertFalse(d.provider_call_allowed)

    def test_next_market_day_can_run(self):
        mh = "d" * 64
        STATE_PATH.write_text(json.dumps({
            "last_material_hash": "oldhash",
            "dirty": True,
            "days": {
                "2026-08-04": {"status": "COMPLETE", "artifact_id": "art-1"},
            },
        }), encoding="utf-8")
        d = evaluate_cio_trigger(mh, now=datetime(2026, 8, 5, 16, 20, tzinfo=ET))
        self.assertEqual(d.action, "RUN")
        self.assertTrue(d.provider_call_allowed)


class TestOperatorPresentationFth(unittest.TestCase):
    def test_presentation_header_not_wait_on_fail(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import operator_presentation as op
        fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
        pres = op.build(fx["packet"], fx["action_policy"])
        self.assertEqual(pres["verification_state"], "DETERMINISTIC_FAIL")
        self.assertEqual(pres["header_state"], "DETERMINISTIC FAIL")
        self.assertNotEqual(pres["header_state"], "WAIT")
        self.assertFalse(pres["display_current_mechanics"])
        self.assertFalse(pres["proposal_allowed"])


if __name__ == "__main__":
    unittest.main()
