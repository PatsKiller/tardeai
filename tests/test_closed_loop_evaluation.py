"""Phase D — closed-loop evaluation (watchlist promotion gate)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from lib.hermes_thresholds.closed_loop_evaluation import (  # noqa: E402
    evaluate_watchlist_promotion_gate,
    run_closed_loop_evaluation_cycle,
)


def _synthetic_series(improve_after: bool = True) -> list[dict]:
    series = []
    for i in range(30):
        day = f"2026-06-{i + 1:02d}"
        after = i >= 14
        series.append({
            "day": day,
            "hit_rate_promotions": 0.44 if (after and improve_after) else 0.36,
            "maturity_composite_score": 72 if after else 65,
        })
    return series


class TestClosedLoopEvaluation(unittest.TestCase):
    def test_insufficient_data_without_audit(self):
        cfg = {"evaluation": {"enabled": True, "min_window_days": 7}}
        ev = evaluate_watchlist_promotion_gate([], [], cfg)
        self.assertEqual(ev["verdict"], "insufficient_data")
        self.assertFalse(ev.get("gate_active"))

    def test_helped_when_hit_rate_improves_after_gate(self):
        cfg = {
            "evaluation": {
                "enabled": True,
                "min_days_after_activation": 0,
                "before_window_days": 14,
                "after_window_days": 14,
                "min_window_days": 7,
                "helped_hit_rate_delta": 0.02,
            },
            "health_thresholds": {"promote_floor": 62},
            "promotion_success": {"lookback_days": 90},
        }
        audit = [
            {"at": "2026-06-15T12:00:00+00:00", "action": "blocked_promotion",
             "symbol": "WEAK", "health_score": 54, "reason": "health=54<62"},
            {"at": "2026-06-15T12:05:00+00:00", "action": "lifecycle_tick", "blocked_promotion_count": 1},
        ]
        ev = evaluate_watchlist_promotion_gate(_synthetic_series(True), audit, cfg)
        self.assertTrue(ev.get("gate_active"))
        self.assertIn(ev["verdict"], ("helped", "neutral"))
        self.assertIn(ev["recommendation"], ("keep_gate", "monitor", "needs_more_data"))

    def test_cycle_persists_with_audit(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_thresholds import closed_loop_evaluation as mod
            from lib.hermes_thresholds import closed_loop_evaluation_store as store
            old_audit = mod.WATCHLIST_AUDIT_PATH
            old_eval = store.CLOSED_LOOP_EVAL_PATH
            try:
                audit_path = Path(td) / "audit.jsonl"
                audit_path.write_text(
                    json.dumps({
                        "at": "2026-06-10T10:00:00+00:00",
                        "action": "blocked_promotion",
                        "symbol": "XYZ",
                        "reason": "health=50<62",
                    }) + "\n",
                    encoding="utf-8",
                )
                mod.WATCHLIST_AUDIT_PATH = audit_path
                store.CLOSED_LOOP_EVAL_PATH = Path(td) / "evals.json"

                from lib.hermes_outcome_bus import bus as bus_mod
                old_hist = bus_mod.HISTORY_DIR
                try:
                    bus_mod.HISTORY_DIR = Path(td) / "history"
                    bus_mod.HISTORY_DIR.mkdir(parents=True, exist_ok=True)
                    for i in range(20):
                        day = f"2026-06-{i + 1:02d}"
                        snap = {
                            "generated_at": f"{day}T03:25:00+00:00",
                            "global": {"hit_rate_promotions": 0.40},
                            "maturity": {"composite_score": 70, "maturity_score": 70},
                            "by_symbol": {},
                        }
                        (bus_mod.HISTORY_DIR / f"outcome_bus_{day}.json").write_text(
                            json.dumps(snap), encoding="utf-8",
                        )
                    result = run_closed_loop_evaluation_cycle(lookback_days=30)
                    self.assertTrue(result["ok"])
                    self.assertIn("evaluation", result)
                    saved = store.load_closed_loop_evaluations()
                    self.assertGreaterEqual(len(saved.get("evaluations") or []), 1)
                finally:
                    bus_mod.HISTORY_DIR = old_hist
            finally:
                mod.WATCHLIST_AUDIT_PATH = old_audit
                store.CLOSED_LOOP_EVAL_PATH = old_eval


if __name__ == "__main__":
    unittest.main()