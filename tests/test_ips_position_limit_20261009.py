"""Every single-position concentration threshold follows the IPS limit.

Operator approval 2026-10-09 ~18:05 ET ("Okay to everything except extending
the scout to closing"): the advisory-desk overweight flag, the CIO decision
engine human-review gates, the look-through single-name guideline and the
specialist-shadow severity split all read
config/investment_policy_statement.json instead of hardcoded 8/15.
READ_ONLY_ADVISORY: no order, stop or broker path is involved.
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib import ips_policy  # noqa: E402


def _cfg(tmp: str, constraints: dict | None) -> Path:
    d = Path(tmp)
    if constraints is not None:
        (d / ips_policy.IPS_FILENAME).write_text(json.dumps({"constraints": constraints}), encoding="utf-8")
    return d


class TestSharedHelper(unittest.TestCase):
    def setUp(self) -> None:
        ips_policy._warned.clear()

    def test_reads_max_and_critical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = _cfg(tmp, {"max_single_position_pct": 12.0, "critical_single_position_pct": 15.0})
            self.assertEqual(ips_policy.ips_max_position_pct(d), 12.0)
            self.assertEqual(ips_policy.ips_critical_position_pct(d), 15.0)

    def test_missing_config_falls_back_strict_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = _cfg(tmp, None)
            with self.assertLogs(ips_policy.log, level=logging.WARNING) as cm:
                self.assertEqual(ips_policy.ips_max_position_pct(d), 8.0)
                self.assertEqual(ips_policy.ips_critical_position_pct(d), 15.0)
            self.assertTrue(any("stricter fallback" in m for m in cm.output))

    def test_invalid_values_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = _cfg(tmp, {"max_single_position_pct": "x", "critical_single_position_pct": 0})
            with self.assertLogs(ips_policy.log, level=logging.WARNING):
                self.assertEqual(ips_policy.ips_max_position_pct(d), 8.0)
                self.assertEqual(ips_policy.ips_critical_position_pct(d), 15.0)

    def test_critical_never_below_max(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = _cfg(tmp, {"max_single_position_pct": 12.0, "critical_single_position_pct": 10.0})
            self.assertEqual(ips_policy.ips_critical_position_pct(d), 12.0)

    def test_repo_config_values(self) -> None:
        self.assertEqual(ips_policy.ips_max_position_pct(), 12.0)
        self.assertEqual(ips_policy.ips_critical_position_pct(), 15.0)

    def test_advisory_desk_wrapper_delegates(self) -> None:
        from lib.data_broker import advisory_desk as ad
        with tempfile.TemporaryDirectory() as tmp:
            d = _cfg(tmp, {"max_single_position_pct": 11.0})
            self.assertEqual(ad.ips_max_position_pct(d), 11.0)


class TestAdvisoryDeskOverweight(unittest.TestCase):
    def _opinion(self, pct: float, ips: float = 12.0) -> dict:
        from lib.data_broker import advisory_desk as ad
        with patch.object(ad, "ips_max_position_pct", return_value=ips):
            return ad._derive_holding_opinion(
                {"symbol": "SCHD", "market_value": 130_000, "portfolio_pct": pct,
                 "gain_loss_pct": 5.0, "cost_basis": 1000.0, "bucket": ""},
                1_000_000.0, risk_positions={}, tax_lots={}, portfolio_heat_pct=None,
            )

    def test_between_ips_and_old_15_is_now_overweight_trim(self) -> None:
        from lib.data_broker.advisory_desk import AdvisoryVerdict
        o = self._opinion(13.0)
        self.assertIn("overweight", o["risk_signals"])
        self.assertEqual(o["verdict"], AdvisoryVerdict.TRIM)
        self.assertEqual(o["trim_kind"], "policy")

    def test_at_or_below_ips_not_overweight(self) -> None:
        self.assertNotIn("overweight", self._opinion(11.9)["risk_signals"])
        self.assertNotIn("overweight", self._opinion(12.0)["risk_signals"])

    def test_follows_config_not_constant(self) -> None:
        self.assertNotIn("overweight", self._opinion(13.0, ips=14.0)["risk_signals"])

    def test_flag_agrees_with_validator(self) -> None:
        from lib.data_broker import advisory_desk as ad
        o = self._opinion(13.5)
        row = {"symbol": "SCHD", "verdict": o["verdict"], "confidence": 0.5, "market_value": 1.0,
               "weight_pct": 13.5, "source": "holdings", "risk_signals": o["risk_signals"]}
        with patch.object(ad, "ips_max_position_pct", return_value=12.0):
            errs = ad.validate_advisory_output({"ok": True, "data": {"metadata": {}, "rows": [row]}})
        self.assertEqual([e for e in errs if "exceeds IPS max" in e], [])


class TestCioDecisionEngineGate(unittest.TestCase):
    def test_review_line_is_ips_limit(self) -> None:
        import cio_decision_engine as eng
        self.assertFalse(eng._weight_needs_review(10.0, 12.0))  # was True under hardcoded 8
        self.assertFalse(eng._weight_needs_review(12.0, 12.0))
        self.assertTrue(eng._weight_needs_review(12.5, 12.0))

    def test_limit_read_from_config(self) -> None:
        import cio_decision_engine as eng
        with patch.object(ips_policy, "ips_max_position_pct", return_value=9.5):
            self.assertEqual(eng._ips_position_limit(), 9.5)

    def test_no_hardcoded_weight_8_left(self) -> None:
        src = (_ROOT / "scripts" / "cio_decision_engine.py").read_text(encoding="utf-8")
        self.assertNotIn("weight > 8", src)


class TestLookthroughGuideline(unittest.TestCase):
    def _adv(self, pct: float, ips: float | None = 12.0) -> list:
        import portfolio_lookthrough_themes as lt
        top = [{"symbol": "NVDA", "pct": pct, "value": 100_000}]
        return lt._advisories({}, top, 1_000_000, ips_max=ips)

    def test_high_only_at_ips_limit(self) -> None:
        self.assertEqual(self._adv(10.0)[0]["severity"], "medium")  # was high under >=8
        high = self._adv(12.0)[0]
        self.assertEqual(high["severity"], "high")
        self.assertIn("12% IPS single-name limit", high["detail"])

    def test_default_reads_config(self) -> None:
        with patch.object(ips_policy, "ips_max_position_pct", return_value=9.0):
            self.assertEqual(self._adv(10.0, ips=None)[0]["severity"], "high")


class TestSpecialistShadowSeverity(unittest.TestCase):
    def _findings(self, wp: float, ips_max: float = 12.0, crit: float = 15.0) -> list:
        from lib.advisory import specialist_shadow as ss
        desk = {"data": {"rows": [{"row_class": "holding", "symbol": "SCHD", "weight_pct": wp}]}}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(ss, "HOLDINGS", Path(tmp) / "none.json"), \
                patch.object(ss, "MODEL_PORTFOLIO", Path(tmp) / "none.json"), \
                patch.object(ss, "_write_artifact", return_value=Path(tmp) / "a.json"), \
                patch.object(ss, "_sentinel_review", return_value={}), \
                patch.object(ss, "_darwin_score", return_value={}), \
                patch.object(ips_policy, "ips_max_position_pct", return_value=ips_max), \
                patch.object(ips_policy, "ips_critical_position_pct", return_value=crit):
            art = ss.guardian_cash_concentration(session_id="t", desk=desk)
        return [f for f in art["findings"] if f["type"] == "ips_max_position"]

    def test_severity_split_from_config(self) -> None:
        self.assertEqual(self._findings(13.0)[0]["severity"], "medium")
        self.assertEqual(self._findings(15.5)[0]["severity"], "high")
        self.assertEqual(self._findings(13.0, crit=12.5)[0]["severity"], "high")

    def test_below_ips_no_finding(self) -> None:
        self.assertEqual(self._findings(11.0), [])


if __name__ == "__main__":
    unittest.main()
