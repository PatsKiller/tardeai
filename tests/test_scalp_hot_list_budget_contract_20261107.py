"""scalp-hot-list's contract must follow the budget the operator actually gave it (2026-11-07).

Ops › Quality graded the lane DEGRADED on 2026-11-06:

    "Ran live 13 h ago and wrote output, but: took 128 s, above its contract's 88 s degraded limit"

The run was healthy: four Finviz screeners, 79 rows, ``status: ok``, one stage, and its receipt
(``data/runtime/scalp-hot-list_last.json``) spans 14:56:01.763Z → 14:58:09.781Z = 128.0 s.

The limit was stale, not the run. The contract's baseline was computed 2026-10-14 with
``basis: CLASS_DEFAULT_PROVISIONAL`` and ``runs_considered: 0`` — a placeholder derived from that
day's cron line (``MOMENTUM_SCALP_OUTER_DEADLINE_S=100 ... timeout 110``, degraded above 80% =
88 s). On 2026-10-23 the operator widened the budget to ``MOMENTUM_SCALP_OUTER_DEADLINE_S=170`` with
``timeout 180`` (the comment on the installed cron line names that date), and neither
``config/n8n_run_allowlist.json`` nor the contract was revised. Every healthy hot-list run above
88 s therefore graded DEGRADED against a limit it could not meet.

These tests pin the corrected values to the file's own 80%-of-timeout rule, and pin the reason: the
allowlist entry and the contract must agree, because that disagreement is what let the drift sit.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANE = "scalp-hot-list"
#: The receipt of the 2026-11-06 14:56Z live run (started_at → ok_at).
OBSERVED_LIVE_RUN_S = 128.018
#: crontab -l 2026-11-07: `... MOMENTUM_SCALP_OUTER_DEADLINE_S=170 ... timeout 180 ...`.
INSTALLED_OUTER_DEADLINE_S = 170
INSTALLED_TIMEOUT_S = 180


def _entry() -> dict:
    doc = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text(encoding="utf-8"))
    lanes = doc["lanes"] if isinstance(doc, dict) else doc
    rows = lanes.values() if isinstance(lanes, dict) else lanes
    return next(row for row in rows if row.get("lane_id") == LANE)


def _contract() -> dict:
    doc = json.loads((ROOT / "config/n8n_health_contracts.json").read_text(encoding="utf-8"))
    return next(c for c in doc["contracts"] if c.get("id") == LANE)


def _registry_row() -> dict:
    doc = json.loads((ROOT / "config/lane_registry.json").read_text(encoding="utf-8"))
    lanes = doc["lanes"] if isinstance(doc, dict) else doc
    rows = lanes.values() if isinstance(lanes, dict) else lanes
    return next(row for row in rows if row.get("lane_id") == LANE)


def test_the_contract_timeout_is_the_installed_cron_timeout():
    """The allowlist and the contract describe one runner; a split lets the contract go stale."""
    assert _entry()["timeout_s"] == INSTALLED_TIMEOUT_S
    assert _contract()["baseline"]["timeout_s"] == _entry()["timeout_s"]


def test_degraded_duration_stays_the_files_own_eighty_percent_rule():
    base = _contract()["baseline"]
    assert base["duration_degraded_above_s"] == round(0.8 * base["timeout_s"], 1)
    assert base["duration_degraded_above_s"] == 144.0
    slow = [d for d in _contract()["degraded"] if d.get("check") == "slow"]
    assert slow and "144.0 s" in slow[0]["text"], "the human-readable limit must match the graded one"


def test_the_runner_aborts_before_the_kill_so_the_budget_is_real():
    """The script's own deadline must sit under the hard kill, or a slow run is killed without a receipt."""
    entry = _entry()
    deadline = [a for a in entry["command"] if str(a).startswith("MOMENTUM_SCALP_OUTER_DEADLINE_S=")]
    assert deadline == [f"MOMENTUM_SCALP_OUTER_DEADLINE_S={INSTALLED_OUTER_DEADLINE_S}"]
    assert INSTALLED_OUTER_DEADLINE_S < entry["timeout_s"]
    assert entry["timeout_s"] - INSTALLED_OUTER_DEADLINE_S >= 10, "leave the script room to write its receipt"


def test_the_run_that_was_graded_degraded_is_inside_the_corrected_limit():
    """128 s was normal under a 170 s budget; only the 2026-10-14 placeholder called it slow."""
    limit = _contract()["baseline"]["duration_degraded_above_s"]
    assert OBSERVED_LIVE_RUN_S <= limit
    assert OBSERVED_LIVE_RUN_S > 88.0, "the old limit is what flagged it — keep the evidence of the drift"


def test_the_three_files_agree_with_the_installed_cron_line():
    """The registry's command_text is the copied crontab line. Read the budget out of it and compare.

    This is the check that would have caught the drift: the registry was updated on 2026-10-23 and the
    allowlist and contract were not, so the two latter copies kept grading against 110 s.
    """
    cmd = _registry_row()["scheduler"]["command_text"]
    deadline = re.search(r"MOMENTUM_SCALP_OUTER_DEADLINE_S=(\d+)", cmd)
    kill = re.search(r"\btimeout (\d+)\b", cmd)
    assert deadline and kill, cmd
    assert int(deadline.group(1)) == INSTALLED_OUTER_DEADLINE_S
    assert int(kill.group(1)) == INSTALLED_TIMEOUT_S
    assert _entry()["timeout_s"] == int(kill.group(1))
    assert _contract()["baseline"]["timeout_s"] == int(kill.group(1))
    assert _entry()["command"] and f"MOMENTUM_SCALP_OUTER_DEADLINE_S={deadline.group(1)}" in _entry()["command"]


def test_the_baseline_no_longer_claims_a_class_default_it_cannot_know():
    base = _contract()["baseline"]
    assert base["basis"] == "OPERATOR_BUDGET_2026_10_23"
    assert "2026-10-23" in base["source"] and str(INSTALLED_TIMEOUT_S) in base["source"]


# --- the grade itself: the receipt shape and the contract together -----------------------------------------


def _receipt(rows_key: bool) -> dict:
    """The 2026-11-06 run's shape: ok, one finviz_scan stage with 79 rows, 128.018 s long."""
    start = "2026-11-06T14:56:01.763379+00:00"
    ok_at = "2026-11-06T14:58:09.781198+00:00"
    summary = {
        "stages": [
            {
                "stage": "finviz_scan",
                "ran": True,
                "ok": True,
                "reason": "finviz_screener_runner --screener x4",
                "rc": 0,
                "rows": 79,
            }
        ],
        "screener_ids": ["prime_setups", "watchlist_setups", "pm_breakout_confirmation", "pm_volume_continuation"],
        "refresh_age_min_before": 0.6,
    }
    if rows_key:
        summary["rows"] = 79  # what hot_list_summary now states
    return {
        "schema": "LaneRunReceipt@v1",
        "lane_id": LANE,
        "script": "run_finviz_momentum_scalp_scan.py --hot-list-only",
        "mode": "live",
        "status": "ok",
        "exit": 0,
        "started_at": start,
        "finished_at": ok_at,
        "ok_at": ok_at,
        "summary": summary,
        "consecutive_failures": 0,
    }


def _grade(receipt: dict, contract: dict) -> dict:
    from datetime import datetime, timezone

    from scripts.lib import run_quality as RQ

    when = receipt["started_at"]
    row = {
        "lane_id": LANE,
        "status": "ok",
        "runs": [
            {
                "result": "succeeded",
                "mode": "live",
                "started_at": when,
                "source": "lane receipt",
                "finished_at": receipt["ok_at"],
                "duration_s": OBSERVED_LIVE_RUN_S,
            }
        ],
    }
    evidence = {
        "contract": contract,
        "receipt": receipt,
        "receipt_path": "data/runtime/scalp-hot-list_last.json",
        "output_at": receipt["ok_at"],
        "history": [],
        "freshness": [],
        "freshness_known": True,
        "plausibility": [],
        "plausibility_known": True,
    }
    return RQ.grade(row, _registry_row(), evidence, now=datetime(2026, 11, 7, 4, 0, tzinfo=timezone.utc))


def test_the_stale_limit_is_what_flagged_the_healthy_run():
    old = json.loads(json.dumps(_contract()))
    old["baseline"].update({"timeout_s": 110, "duration_degraded_above_s": 88.0})
    graded = _grade(_receipt(rows_key=True), old)
    assert graded["grade"] == "DEGRADED"
    assert "above its contract's 88 s degraded limit" in graded["headline"]


def test_the_corrected_contract_plus_the_count_grades_good():
    """Both halves are needed: the limit stops flagging it, and the receipt states what it produced."""
    graded = _grade(_receipt(rows_key=True), _contract())
    assert graded["grade"] == "GOOD", graded["headline"]
    assert graded["count"] == {"value": 79, "key": "summary.rows", "median": None, "history_n": 0}


def test_without_the_count_the_run_is_unproven_not_good():
    graded = _grade(_receipt(rows_key=False), _contract())
    assert graded["grade"] == "UNPROVEN" and graded["sub"] == "output_unverifiable"


def test_the_script_states_the_row_count_it_measured():
    from scripts.run_finviz_momentum_scalp_scan import hot_list_summary

    scanned = [{"stage": "finviz_scan", "ran": True, "ok": True, "rc": 0, "rows": 79}]
    skipped = [{"stage": "finviz_scan", "ran": False, "ok": True, "reason": "skipped_fresh (age=0.20m < 0.5m)"}]
    assert hot_list_summary(scanned, ["prime_setups"], 0.6)["rows"] == 79
    assert "rows" not in hot_list_summary(skipped, ["prime_setups"], 0.2)
    assert hot_list_summary(scanned, ["prime_setups"], 0.6)["stages"][0]["rows"] == 79, "the stage keeps its own row"
