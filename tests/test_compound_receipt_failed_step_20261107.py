"""A compound lane's failed run must name the step that failed, not only that something did.

``run-research-intelligence-overnight`` failed twice in a row (2026-11-06 20:30 ET, 2026-11-07 00:15 ET) and both
receipts said exactly ``{"status": "failed", "step": null}`` with no ``error``. The failing step — ``narrative``,
whose LLM providers were unreachable — existed only in ``logs/ri_overnight.log``. The final receipt now carries
``summary.failed_steps`` and ``error: "failed step(s): …"``, which is also the field the Quality grade reads for
its headline.

This pins the behaviour in both directions:

* a real failure names every failed step, in order, in the summary **and** in ``error``;
* a successful run and a lock-skipped (75) run record none — a step list beside ``completed`` would be a lie;
* without ``--failed-step`` the receipt is byte-for-byte the old shape (no new key, no error), so lanes that have
  not adopted the flag are unaffected;
* the per-step receipts are untouched;
* and the overnight shell actually passes the flag — the wiring is part of the fix, not just the flag.

Hermetic: a synthetic state root under ``tmp_path``, no DB, no network, no LLM, no live persistent state.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import completion_compound_receipt as compound  # noqa: E402

SHELL = ROOT / "scripts" / "run_research_intelligence_overnight.sh"


def _receipt(tmp_path: Path, lane: str) -> dict:
    return json.loads((tmp_path / "data" / "runtime" / f"{lane}_last.json").read_text(encoding="utf-8"))


def _run(monkeypatch, tmp_path: Path, argv: list[str]) -> dict:
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.delenv("TRADEAI_RUN_ID", raising=False)
    monkeypatch.delenv("TRADEAI_RUN_ATTEMPT", raising=False)
    monkeypatch.delenv("TRADEAI_RUN_MODE", raising=False)
    assert compound.main(argv) == 0
    lane = argv[argv.index("--lane") + 1]
    if "--step" in argv:
        lane += "--step-" + argv[argv.index("--step") + 1]
    return _receipt(tmp_path, lane)


# ── the receipt ────────────────────────────────────────────────────────────────────────────────


def test_a_failed_run_names_every_failed_step_in_order(monkeypatch, tmp_path):
    doc = _run(
        monkeypatch,
        tmp_path,
        ["--lane", "ri-overnight", "--exit", "1", "--failed-step", "narrative", "--failed-step", "ingest"],
    )

    assert doc["status"] == "failed"
    assert doc["ok_at"] is None
    assert doc["summary"]["failed_steps"] == ["narrative", "ingest"]
    assert doc["error"] == "failed step(s): narrative, ingest"  # what the Quality headline reads


def test_a_successful_run_records_no_failed_step(monkeypatch, tmp_path):
    doc = _run(monkeypatch, tmp_path, ["--lane", "ri-overnight", "--exit", "0", "--failed-step", "narrative"])

    assert doc["status"] == "ok"
    assert "failed_steps" not in doc["summary"]  # a step list beside "completed" would contradict the status
    assert not doc.get("error")


def test_a_lock_skipped_run_records_no_failed_step(monkeypatch, tmp_path):
    doc = _run(monkeypatch, tmp_path, ["--lane", "ri-overnight", "--exit", "75", "--failed-step", "ingest"])

    assert doc["summary"]["status"] == "RUN_SKIPPED_LOCK"
    assert "failed_steps" not in doc["summary"]
    assert not doc.get("error")


def test_without_the_flag_the_receipt_keeps_its_old_shape(monkeypatch, tmp_path):
    doc = _run(monkeypatch, tmp_path, ["--lane", "ri-overnight", "--exit", "1"])

    assert set(doc["summary"]) == {"step", "status"}  # no new key for lanes that do not pass the flag
    assert doc["summary"] == {"step": None, "status": "failed"}
    assert not doc.get("error")


def test_a_per_step_receipt_still_names_its_step(monkeypatch, tmp_path):
    doc = _run(monkeypatch, tmp_path, ["--lane", "ri-overnight", "--step", "ingest", "--exit", "0"])

    assert doc["summary"] == {"step": "ingest", "status": "completed"}


# ── the wiring: the shell has to pass it ──────────────────────────────────────────────────────


def test_the_overnight_shell_passes_the_flag_it_accumulates():
    text = SHELL.read_text(encoding="utf-8")

    assert re.search(r"FAILED\+=\(", text), "the shell must accumulate failed step names"
    final = text.rsplit("completion_compound_receipt.py", 1)[-1]
    assert "--failed-step" in text.split("FAILED_ARGS=()")[-1]
    assert "FAILED_ARGS" in final, "the final (lane-level) receipt must carry the accumulated steps"
    # a lock skip is not a failure: the accumulate line sits on the FAIL branch only
    fail_line = next(ln for ln in text.splitlines() if "FAIL $name exit=$rc" in ln)
    assert "FAILED+=(" in fail_line
