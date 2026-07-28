#!/usr/bin/env python3
"""Full-run decision restore must never contradict a manual-review lane.

Regression: 2026-07-28. LVWR and POLA persisted to trade_ai_scans as
decision=GO with awareness_status=HIGH_RVOL, manual_review_required=True and
not_tradeable=True — a row simultaneously auto-tradeable and flagged
not-tradeable.

Mechanism (deterministic, fired every live cycle):
  scoring.py qualifies_high_rvol_manual() -> apply_high_rvol_manual_fields()
    sets decision=MANUAL_REVIEW + the HIGH_RVOL lane + not_tradeable=True
  ...which drives the live pass to GO=0
  ...which triggers continuous_runner's "PRESERVE FULL RUN SCORES" fallback
  ...which overwrote ONLY t["decision"] from live_run_state.json, leaving the
     lane fields intact.

live_run_state.json carries only {symbol, decision, score} — it has no lane
fields — so the lane cannot be restored alongside the decision. The invariant
is therefore: never restore a decision onto a row the live pass routed to
manual review.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from continuous_runner import (  # noqa: E402
    is_manual_lane_row,
    restore_full_run_decisions,
)

pass_ct = 0


def check(label: str, ok: bool):
    global pass_ct
    print(f"{'PASS' if ok else 'FAIL'}: {label}")
    if not ok:
        raise SystemExit(1)
    pass_ct += 1


def main() -> int:
    # ---- the exact production shape apply_high_rvol_manual_fields() produces ----
    lvwr = {
        "symbol": "LVWR", "score": 30, "grade": "RUNNER", "decision": "MANUAL_REVIEW",
        "awareness_status": "HIGH_RVOL", "setup_class": "high_rvol_runner",
        "route": "warrior_manual", "route_actionability": "MANUAL_REVIEW",
        "manual_review_required": True, "not_tradeable": True,
        "not_validation_ready": True, "operator_pill": "RUNNER · 29.5x",
    }
    clean = {"symbol": "ENTX", "score": 22, "decision": "WAIT"}
    scored = [lvwr, clean]
    full_map = {"LVWR": "GO", "ENTX": "GO", "ABSENT": "GO"}

    restored, skipped = restore_full_run_decisions(scored, full_map)

    check("manual-lane row keeps MANUAL_REVIEW", lvwr["decision"] == "MANUAL_REVIEW")
    check("manual-lane row was skipped, not restored", skipped == 1)
    check("clean row still restored to GO", clean["decision"] == "GO")
    check("restored count counts only clean rows", restored == 1)
    check("symbols absent from scored are ignored", len(scored) == 2)

    # The invariant the DB rows violated.
    for row in scored:
        actionable = str(row.get("decision", "")).upper() in ("GO", "ENTER", "TAKE")
        check(
            f"{row['symbol']}: never actionable AND not_tradeable",
            not (actionable and row.get("not_tradeable")),
        )

    # ---- lane detection covers every manual lane, not just HIGH_RVOL ----
    for status in ("SQUEEZE", "HIGH_RVOL", "MICRO_FLOAT", "MOMENTUM_RUNNER", "LOW_PRICE"):
        check(f"{status} detected as manual lane", is_manual_lane_row({"awareness_status": status}))
    check("manual_review_required alone is enough", is_manual_lane_row({"manual_review_required": True}))
    check("not_tradeable alone is enough", is_manual_lane_row({"not_tradeable": True}))
    check("plain scored row is not a manual lane", not is_manual_lane_row({"symbol": "X", "decision": "WAIT"}))
    check("empty row is not a manual lane", not is_manual_lane_row({}))

    # ---- a not_tradeable awareness row must never be upgraded either ----
    social = {"symbol": "QTEX", "decision": "WAIT",
              "awareness_status": "SOCIAL_AWARENESS", "not_tradeable": True}
    only = [social]
    r2, s2 = restore_full_run_decisions(only, {"QTEX": "GO"})
    check("not_tradeable awareness row not upgraded to GO", social["decision"] == "WAIT")
    check("awareness row counted as skipped", (r2, s2) == (0, 1))

    # ---- no-op safety ----
    empty_scored: list[dict] = []
    check("empty scored list is a no-op", restore_full_run_decisions(empty_scored, {"A": "GO"}) == (0, 0))
    solo = [{"symbol": "A", "decision": "WAIT"}]
    check("empty full_map is a no-op", restore_full_run_decisions(solo, {}) == (0, 0))
    check("empty full_map leaves decision untouched", solo[0]["decision"] == "WAIT")

    print(f"\nAll {pass_ct} continuous_runner restore checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
