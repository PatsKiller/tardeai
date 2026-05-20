#!/usr/bin/env python3
"""Tests for UI-AUDIT-2 route and tab cleanup."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestRoutes(unittest.TestCase):
    def _app(self):
        return (PROJECT_ROOT / "apps/command-center-v2/src/App.tsx").read_text()

    def test_01_journal_analytics_redirects(self):
        self.assertIn('journal-analytics', self._app())
        self.assertIn('tab=analytics', self._app())

    def test_02_journal_reports_redirects(self):
        self.assertIn('journal-reports', self._app())
        self.assertIn('tab=reports', self._app())

    def test_03_content_health_redirects(self):
        self.assertIn('content-health', self._app())
        self.assertIn('tab=content-health', self._app())

    def test_04_learning_governance_redirects(self):
        self.assertIn('learning-governance', self._app())
        self.assertIn('tab=learning', self._app())

    def test_05_forecast_not_returns(self):
        src = self._app()
        # forecast should NOT render Returns component
        idx = src.index('path="forecast"')
        block = src[idx:idx+200]
        self.assertNotIn('<Returns', block)
        self.assertIn('not activated', block.lower())

    def test_06_broker_recon_redirect(self):
        self.assertIn('broker-recon', self._app())
        self.assertIn('broker-reconciliation', self._app())

    def test_07_system_hub_redirect(self):
        self.assertIn('system-hub', self._app())
        self.assertIn('/v2/ops', self._app())


class TestPriorFixes(unittest.TestCase):
    def test_08_self_improvement_not_double_unwrap(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/SelfImprovement.tsx").read_text()
        # Should not have status?.data (double unwrap)
        self.assertNotIn("status?.data", src)

    def test_09_risk_regime_not_double_unwrap(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/RiskRegime.tsx").read_text()
        self.assertNotIn("regime?.data", src)


class TestSafety(unittest.TestCase):
    def test_10_no_unsafe_buttons(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/App.tsx").read_text()
        for unsafe in ["Execute Trade", "Submit Order", "Enable Live"]:
            self.assertNotIn(unsafe, src)

    def test_11_frontend_builds(self):
        dist = PROJECT_ROOT / "apps/command-center-v2/dist/assets"
        self.assertTrue(list(dist.glob("index-*.js")))


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
