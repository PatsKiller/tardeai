"""LQ-20261107-1884 — the promotion writer is REGISTERED, not merely committed.

Registration is not execution (Engineering Constitution v1.5). These tests prove only that the
allowlist entry, the registry row and the R1 class admission agree with each other, and that the
scheduled path cannot promote on its own. The proof that the lane ran is a receipt
``data/runtime/lesson-queue-cycle_last.json`` with ``ok_at``, PROMOTED > 0 and a
``learning_promotion_decisions`` row (operator acceptance 2026-11-11T15:03:13Z).

Fail-before (release ae43e4c39 *without* the registry hunk): ``lesson-queue-cycle`` is in the
allowlist and half-registered — no row in ``config/lane_registry.json`` — so the registry and
admission tests below fail. An allowlist entry alone schedules nothing, which is exactly how the
queue went unwritten from 2026-10-04 to 2026-11-11.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LANE = "lesson-queue-cycle"
SCRIPT = "scripts/lesson_queue_cycle.py"
RECEIPT = "data/runtime/lesson-queue-cycle_last.json"


def _json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _allow() -> dict:
    return next(e for e in _json("config/n8n_run_allowlist.json")["lanes"] if e.get("lane_id") == LANE)


def _row() -> dict:
    rows = [r for r in _json("config/lane_registry.json")["lanes"] if r.get("lane_id") == LANE]
    assert len(rows) == 1, f"{LANE}: expected exactly one registry row, found {len(rows)}"
    return rows[0]


def test_allowlist_entry_is_a_dispatcher_lane_for_the_cycle_script():
    e = _allow()
    assert e["command"] == ["$PY", SCRIPT]
    assert e["dry_run_arg"] == ["--dry-run"] and e["live_arg"] == ["--apply"]
    assert e["lock_kind"] == "flock" and e["lock"] == "/tmp/tradeai_lesson_queue_cycle.lock"
    assert e["market_gate"] is False
    assert 0 < int(e["timeout_s"]) <= 900
    assert e["output_signal"] == RECEIPT
    assert (ROOT / SCRIPT).is_file()


def test_registry_row_schedules_the_dispatcher_and_matches_the_allowlist():
    e, r = _allow(), _row()
    sched, disp = r["scheduler"], r["dispatch"]
    assert sched["kind"] == "n8n" and sched["expression"] == "dispatcher"
    assert sched["stage"] in ("shadow", "canary", "cutover")
    # the dispatcher's match is the allowlist command plus its LIVE argv, never the dry one
    expected_match = " ".join(["$PY".replace("$PY", SCRIPT), *e["live_arg"]])
    assert sched["match"] == expected_match, sched["match"]
    assert sched["cadence"] in disp["cron"], (sched["cadence"], disp["cron"])
    assert disp["mode"] == "live" and disp["class"] == "learn"
    assert disp["wave"][0] == "W" and disp["wave"][1:].isdigit()
    # never cron and never systemd: the operator rail is that scheduling goes through n8n
    assert sched["kind"] != "cron" and sched["kind"] != "systemd"
    sig = r["output_signal"]
    assert sig["kind"] == "json_key" and sig["path"] == e["output_signal"] and sig["key"] == "ok_at"
    assert r["state"] == "ACTIVE" and r["value_class"] and r["severity"]


def test_row_is_admitted_by_the_r1_gate():
    import sys

    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    import lane_dispatch as ld

    ok, reason = ld.r1_class_admission(_row(), _allow())
    assert ok is True, reason
    assert reason == "r1_admitted:learn", reason


def test_the_scheduled_path_cannot_promote_on_its_own():
    """The learn lane may enqueue and open a package; only an operator act moves a lesson to PROMOTED."""
    src = (ROOT / SCRIPT).read_text(encoding="utf-8")
    tree = ast.parse(src)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "run_cycle" in funcs and "promote_one" in funcs
    cycle_calls = {
        (n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id)
        for n in ast.walk(funcs["run_cycle"])
        if isinstance(n, ast.Call) and isinstance(n.func, (ast.Attribute, ast.Name))
    }
    assert "decide" not in cycle_calls, "run_cycle must not promote; only consume_approved may"
    assert "consume_approved" in cycle_calls
    promote_src = ast.get_source_segment(src, funcs["promote_one"])
    assert 'startswith("operator:")' in promote_src
