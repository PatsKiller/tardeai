#!/usr/bin/env python3
"""P3 prep: protective_stop_policy.evaluate must PASS a valid OCO and reject a bad take-profit leg.

GATES_REMOVED is True in production (the policy is a 2FA-only pass-through today), so these tests patch it
OFF to exercise the GATED path — proving the OCO logic is correct for when the gates are re-armed. PURE: no
broker calls, nothing live; the patches are restored in finally.
"""
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import brokers.protective_stop_policy as p


class TestProtectivePolicyOco(unittest.TestCase):
    def _eval(self, **kw):
        """Run evaluate with the gates ARMED (GATES_REMOVED off) and a stub allowlist, then restore."""
        saved = (p.GATES_REMOVED, p.ENABLED, p.POC_MODE, p.effective_account_allowlist)
        p.GATES_REMOVED, p.ENABLED, p.POC_MODE = False, True, False
        p.effective_account_allowlist = lambda: ("schwab_taxable",)
        try:
            base = dict(account_key="schwab_taxable", instruction="SELL", order_type="OCO",
                        stop_price=10.75, advised_stop=10.75, current_price=10.97,
                        qty=293, held_qty=293, symbol="AGNC", take_profit=11.24)
            base.update(kw)
            return p.evaluate(**base)
        finally:
            p.GATES_REMOVED, p.ENABLED, p.POC_MODE, p.effective_account_allowlist = saved

    def test_01_valid_oco_passes(self):
        ok, reasons = self._eval()
        self.assertTrue(ok, f"valid OCO should pass, got: {reasons}")

    def test_02_missing_take_profit_fails(self):
        ok, reasons = self._eval(take_profit=None)
        self.assertFalse(ok)
        self.assertTrue(any("take_profit" in r for r in reasons), reasons)

    def test_03_take_profit_below_price_fails(self):
        ok, reasons = self._eval(take_profit=10.90)   # <= current 10.97
        self.assertFalse(ok)
        self.assertTrue(any("take-profit" in r for r in reasons), reasons)

    def test_04_stop_above_price_still_fails(self):
        # OCO does not bypass the stop-leg checks: a stop at/above price is still rejected.
        ok, reasons = self._eval(stop_price=11.50)
        self.assertFalse(ok)
        self.assertTrue(any("not a protective long stop" in r for r in reasons), reasons)

    def test_05_qty_over_held_still_fails(self):
        ok, reasons = self._eval(qty=500, held_qty=293)
        self.assertFalse(ok)
        self.assertTrue(any("exceeds held shares" in r for r in reasons), reasons)

    def test_06_stop_order_type_unaffected(self):
        # Regression: a plain STOP (no take_profit) still passes the gated path.
        ok, reasons = self._eval(order_type="STOP", take_profit=None)
        self.assertTrue(ok, f"plain STOP should still pass: {reasons}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
