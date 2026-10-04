#!/usr/bin/env python3
"""Tests for UI-AUDIT-2 route and tab cleanup."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestRoutes(unittest.TestCase):
    def _app(self):
        return (PROJECT_ROOT / "apps/command-center-v2/src/App.tsx").read_text()

    # 2026-06-26 (0ca6be146, trade-in-view P5-P6) moved the journal to v3: both legacy routes now
    # hand off to the canonical /v3/trade-in-view instead of a v2 journal tab (updated 2026-10-04).
    def _v3_journal_redirect(self):
        return (PROJECT_ROOT / "apps/command-center-v2/src/components/RedirectToV3Journal.tsx").read_text()

    def test_01_journal_analytics_redirects(self):
        self.assertIn('path="journal-analytics" element={<SafePage><RedirectToV3Journal />', self._app())
        self.assertIn('/v3/trade-in-view', self._v3_journal_redirect())

    def test_02_journal_reports_redirects(self):
        self.assertIn('path="journal-reports" element={<SafePage><RedirectToV3Journal />', self._app())
        self.assertIn('/v3/trade-in-view', self._v3_journal_redirect())

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
        # The placeholder was replaced by a real Forecast page (module now exists).
        self.assertIn('<Forecast', block)
        self.assertTrue((PROJECT_ROOT / "apps/command-center-v2/src/pages/Forecast.tsx").exists())

    def test_06_broker_recon_redirect(self):
        self.assertIn('broker-recon', self._app())
        self.assertIn('broker-reconciliation', self._app())

    def test_07_system_hub_redirect(self):
        # Router basename is /v2, so Navigate to "/ops" lands on /v2/ops.
        self.assertIn('path="system-hub" element={<Navigate to="/ops" replace />}', self._app())
        self.assertIn('basename="/v2"', self._app())


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
        if not dist.exists():
            # dist/ is gitignored build output: a fresh worktree or CI checkout has none.
            self.skipTest("command-center-v2 has not been built in this tree (dist/ is gitignored)")
        self.assertTrue(list(dist.glob("index-*.js")))


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
