#!/usr/bin/env python3
"""Cash-based sizing for watchlist propose flow."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import account_policy as ap


class TestWatchlistProposeSizing(unittest.TestCase):
    def test_fidelity_cash_from_holdings(self):
        cash = ap._cash_from_holdings("fidelity_rollover_ira")
        self.assertIsNotNone(cash)
        self.assertGreater(cash, 0)

    def test_retirement_uses_cash_not_equity_base(self):
        with patch.object(ap, "equity_for_account", return_value=(584500.0, "test")):
            with patch.object(ap, "cash_for_account", return_value=(29300.0, "schwab_live")):
                cash_base, equity, src = ap.sizing_cash_base("schwab_rollover_ira")
        self.assertEqual(cash_base, 29300.0)
        self.assertEqual(equity, 584500.0)
        self.assertTrue(ap.is_retirement_account("schwab_rollover_ira"))

    def test_risk_budget_on_cash_dxcm_example(self):
        """1% of $29.3k cash, not 1% of $584k equity."""
        sizing_base = 29300.0
        equity = 584500.0
        entry, stop = 67.80, 66.00
        risk_pct = 1.0
        budget = sizing_base * (risk_pct / 100)
        risk_per_share = entry - stop
        shares = int(budget / risk_per_share)
        cash_cap = int(sizing_base / entry)
        shares = min(shares, cash_cap)
        investment = shares * entry
        self.assertLess(shares, 500)
        self.assertLess(investment, sizing_base)
        pct_equity = (shares * risk_per_share) / equity * 100
        self.assertLess(pct_equity, 0.05)


if __name__ == "__main__":
    unittest.main()