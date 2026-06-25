"""Tests for portfolio_snapshot_sanity — market day 1D vs reconciliation outliers."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from portfolio_snapshot_sanity import (
    apply_market_day_1d,
    compute_drawdown_series,
    find_reconciliation_outlier_dates,
    holding_phantom_corrections,
    portfolio_market_day,
    snapshot_period_return_reliable,
    snapshot_total_write_ok,
)


class TestPortfolioSnapshotSanity(unittest.TestCase):
    def test_portfolio_market_day_from_totals(self):
        pf = {
            "portfolio_totals": {"total_value": 1_000_000, "day_change": -2_200, "day_change_pct": -0.22},
            "holdings": [],
        }
        md = portfolio_market_day(pf)
        self.assertIsNotNone(md)
        self.assertEqual(md["change"], -2_200)
        self.assertAlmostEqual(md["change_pct"], -0.22, places=2)
        self.assertEqual(md["source"], "market_day")

    def test_find_v_reconciliation_outlier(self):
        snaps = [
            {
                "date": "2026-06-22",
                "total_value": 1_279_410,
                "day_change": -1_950,
                "accounts": {"schwab_rollover_ira": {"value": 589_500, "day_change": -916}},
                "holdings": {"V:schwab_rollover_ira": {"symbol": "V", "market_value": 98_661}},
            },
            {
                "date": "2026-06-23",
                "total_value": 1_242_301,
                "day_change": -5_447,
                "accounts": {"schwab_rollover_ira": {"value": 556_705, "day_change": -1_538}},
                "holdings": {"V:schwab_rollover_ira": {"symbol": "V", "market_value": 65_937}},
            },
        ]
        outliers = find_reconciliation_outlier_dates(snaps)
        self.assertIn("2026-06-22", outliers)
        phantom = holding_phantom_corrections(snaps)
        self.assertIn("2026-06-22", phantom)
        self.assertGreater(phantom["2026-06-22"], 30_000)

    def test_drawdown_sanitized_after_outlier(self):
        snaps = [
            {"date": "2026-06-21", "total_value": 1_280_983, "day_change": -766,
             "holdings": {"V:schwab_rollover_ira": {"market_value": 98_661}}},
            {"date": "2026-06-22", "total_value": 1_279_410, "day_change": -1_950,
             "holdings": {"V:schwab_rollover_ira": {"market_value": 98_661}}},
            {"date": "2026-06-23", "total_value": 1_242_301, "day_change": -5_447,
             "holdings": {"V:schwab_rollover_ira": {"market_value": 65_937}}},
        ]
        dd = compute_drawdown_series(snaps)
        self.assertTrue(dd)
        max_dd = min(p["drawdown"] for p in dd)
        self.assertGreater(max_dd, -3.0)

    def test_apply_market_day_replaces_bad_1d(self):
        perf = {
            "periods": {
                "1D": {"change_pct": -5.11, "change": -36_496, "source": "account-aggregated"},
                "1W": {"change_pct": -2.62, "change": -18_212, "source": "account-aggregated"},
            },
            "accounts": {},
        }
        portfolio = {
            "portfolio_totals": {"total_value": 1_242_802, "day_change": -2_780, "day_change_pct": -0.22},
            "account_summaries": {},
            "holdings": [],
        }
        out = apply_market_day_1d(perf, portfolio)
        self.assertEqual(out["periods"]["1D"]["source"], "market_day")
        self.assertAlmostEqual(out["periods"]["1D"]["change_pct"], -0.22, places=2)
        self.assertTrue(out["periods"]["1D"]["snapshot_replaced"])
        self.assertEqual(out["periods"]["1W"]["change_pct"], -2.62)

    def test_snapshot_period_return_reliable(self):
        self.assertFalse(snapshot_period_return_reliable(-5.11, "1D", market_day_pct=-0.22))
        self.assertTrue(snapshot_period_return_reliable(-0.22, "1D", market_day_pct=-0.25))

    def test_holding_write_guard_rejects_v_jump(self):
        prev = {
            "total_value": 1_279_410,
            "holdings": {"V:schwab_rollover_ira": {"symbol": "V", "account": "schwab_rollover_ira", "market_value": 98_661}},
        }
        new = {
            "total_value": 1_242_301,
            "holdings": {"V:schwab_rollover_ira": {"symbol": "V", "account": "schwab_rollover_ira", "market_value": 65_937}},
        }
        ok, reason = snapshot_total_write_ok(new, prev)
        self.assertFalse(ok)
        self.assertIn("V", reason)


if __name__ == "__main__":
    unittest.main()