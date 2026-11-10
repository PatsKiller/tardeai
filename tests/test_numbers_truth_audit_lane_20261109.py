"""LQ-20261107-1703 — the numbers-truth audit is registered as an hourly n8n lane.

Design: DSN-20261109-numbers-truth-audit.md §2 (schedule), aligned by REV 2 (§A-F) and REV 3 (§G-H).
Operator ask 2026-11-09 17:10 ET; assigned to cc-deepseek-8 by ASSIGN-20261109T2220Z-claude-lead.

This module pins the registration to itself and to the lane's own script, in one place, so the three
config files cannot drift apart again:

  * the registry row is a §23.11 dispatcher row at stage SHADOW, hourly at :07, 24x7 — the schedule is
    re-derived from the cron expression with the DST-safe ``fires_between`` (168 fires a week, every
    one at minute 07, every gap exactly 60 minutes), not asserted as a string alone;
  * the dispatch block parses, validates and is eligible (no forbidden token, no keep-on-cron marker);
  * the run-allowlist entry is the argv the executor would run, it passes ``validate_entry``, and the
    entry's output_signal is the path the lane's own receipt writer produces;
  * the scheduled argv is EMULATED against a throwaway state root: ``--dry-run`` writes no receipt
    (a shadow fire can never advance ok_at), which is the §23.11 stage-clamp promise;
  * the health contract is REVIEWED (a new lane's contract must be), its stage copy equals the
    registry's, its expected_output validates, and its produced_field is the field the script writes;
  * the superseded site-audit row says so (REV 2 §C: no second scheduled crawler).

Every fixture is synthetic: a tmp_path state root, no database, no provider, no HTTP, no broker, and the
script is run with ``--no-db --no-http``. Nothing here writes durable state.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.cron_schedule import fires_between  # noqa: E402
from scripts.lib.lane_dispatch import (  # noqa: E402
    dispatch_eligible, parse_dispatch_block, validate_dispatch_block,
)
from scripts.lib.lane_registry import validate_row  # noqa: E402
from scripts.lib.n8n_health_contracts import validate_contract  # noqa: E402
from scripts.lib.n8n_output_verdict import validate_expected_output  # noqa: E402

LID = "numbers-truth-audit"
SCRIPT = "scripts/numbers_truth_audit.py"
SIGNAL = "data/runtime/numbers-truth-audit_last.json"
LOCK = "/tmp/tradeai_numbers_truth_audit.lock"
RETRY_POLICIES = ROOT / "config" / "n8n_retry_policies.json"
ET = ZoneInfo("America/New_York")


# ── config readers ──────────────────────────────────────────────────────────────────────────────


def registry() -> dict:
    return json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))


def allowlist() -> dict:
    return json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))


def contracts() -> dict:
    return json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))


def row() -> dict:
    return next(r for r in registry()["lanes"] if r.get("lane_id") == LID)


def entry() -> dict:
    return next(e for e in allowlist()["lanes"] if e.get("lane_id") == LID)


def contract() -> dict:
    return next(c for c in contracts()["contracts"] if c.get("id") == LID)


def retry_policy_names() -> set[str]:
    doc = json.loads(RETRY_POLICIES.read_text(encoding="utf-8"))
    return set((doc.get("policies") or {}).keys())


# ── the registry row ────────────────────────────────────────────────────────────────────────────


def test_the_row_is_one_canary_dispatcher_lane():
    r = row()
    assert validate_row(r) == []
    sched = r["scheduler"]
    assert sched["kind"] == "n8n"
    assert sched["expression"] == "dispatcher", "a §23.11 dispatcher row, never the workflow id"
    assert sched["match"] == SCRIPT, "the retired-cron match text keeps the host-conflict check alive"
    assert sched["stage"] == "canary", "operator promoted 2026-11-09 ~19:00 ET after grok-a MERGE + live dry run"
    assert sched["cadence"] == "7 * * * *"
    assert sched["timezone"] == "America/New_York"
    assert r["state"] == "ACTIVE"
    assert r["expected_cadence_hours"] == 1.0
    assert r["active_days"] == [0, 1, 2, 3, 4, 5, 6], "24x7: weekends included"
    assert r["output_signal"]["kind"] == "json_key"
    assert r["output_signal"]["path"] == SIGNAL
    assert r["output_signal"]["key"] == "ok_at", "a receipt, not an exit code"


def test_the_schedule_is_hourly_at_minute_seven_across_the_whole_week():
    """Re-derived from the expression, not trusted from the string: 168 fires, minute 07, 60-min gaps."""
    expr = row()["scheduler"]["cadence"]
    start = datetime(2026, 11, 9, 0, 0, tzinfo=ET)   # Monday; DST ended 2026-11-01, so no fold/gap week
    end = start + timedelta(days=7)
    fires = fires_between(expr, start, end, tz="America/New_York")
    assert len(fires) == 24 * 7, f"one fire an hour, 24x7; got {len(fires)}"
    assert {f.at.minute for f in fires} == {7}
    gaps = {int((b.at - a.at).total_seconds() // 60) for a, b in zip(fires, fires[1:])}
    assert gaps == {60}, f"the gap between fires must be exactly one hour; got {sorted(gaps)}"


def test_the_dispatch_block_is_clean_and_the_lane_is_eligible():
    r = row()
    block = parse_dispatch_block(r)
    assert block is not None
    assert block.mode == "live", "canary runs live: --apply writes the receipt (read-only audit, no send)"
    assert block.klass == "monitor"
    assert block.retry_policy == "transient-2", "a monitor may retry; transient-2 permits the class"
    assert tuple(block.cron) == ("7 * * * *",), "the block and the cadence cannot disagree"
    assert block.tz == "America/New_York"
    known = {x.get("lane_id") for x in registry()["lanes"] if isinstance(x, dict)}
    issues = validate_dispatch_block(r, known_lane_ids=known, retry_policy_names=retry_policy_names())
    assert issues == [], [f"{i.code}: {i.detail}" for i in issues]
    ok, why = dispatch_eligible(r)
    assert ok, why


# ── the run-allowlist entry ────────────────────────────────────────────────────────────────────


def test_the_entry_runs_the_registered_script_in_the_registered_mode():
    e = entry()
    assert e["command"] == ["$PY", SCRIPT]
    assert e["dry_run_arg"] == ["--dry-run"]
    assert e["live_arg"] == ["--apply"], "promoted: the live fire writes this lane's LaneRunReceipt@v2"
    assert e["lock"] == LOCK
    assert e["lock_kind"] == "flock"
    assert e["timeout_s"] == 120, "DSN §F: a run must not hold the executor drain longer than 120 s"
    assert e["market_gate"] is False, "the lane runs 24x7 and decides the §28.8 HTTP window itself"
    assert e["output_signal"] == SIGNAL
    assert e["output_receipt"] == "v2"
    assert "DB_HOST" in e["env_names"] and "TRADEAI_STATE_ROOT" in e["env_names"]
    assert not [n for n in e["env_names"] if "SCHWAB" in n.upper() or "BROKER" in n.upper()]


def test_the_entry_passes_the_executors_own_validator():
    from scripts.n8n_run_executor import validate_entry

    assert validate_entry(entry()) is None


def test_the_signal_is_the_path_the_lane_receipt_writer_produces():
    from scripts.lib import lane_last_receipt as R

    produced = R.receipt_path(LID, Path("/tmp/nta-signal-root"))
    assert produced.as_posix().endswith(SIGNAL)


# ── the health contract ────────────────────────────────────────────────────────────────────────


def test_the_contract_is_reviewed_valid_and_at_the_registry_stage():
    c = contract()
    assert c["schema"] == "N8nHealthContract@v1"
    assert c["kind"] == "lane"
    assert c["status"] == "REVIEWED", "a new lane's contract must be REVIEWED before its registry PR"
    assert c["stage"] == row()["scheduler"]["stage"], "the contract's stage is a copy of the registry's"
    assert validate_contract(c) == []
    assert c["baseline"]["timeout_s"] == entry()["timeout_s"]
    assert c["baseline"]["duration_degraded_above_s"] == 0.8 * entry()["timeout_s"], (
        "a bound above the lane's own timeout is unreachable"
    )
    assert c["review_by"] > "2026-11-09", "a provisional baseline needs a future review date"


def test_the_expected_output_reads_a_field_the_lane_can_write():
    eo = contract()["expected_output"]
    assert validate_expected_output(eo) == []
    assert eo["produced_field"] == "produced_count"
    assert eo["min_produced"] == 1
    assert "no_runner" in eo["fatal_skip_reasons"]
    # Phase 2 (with the lane script): the same field must exist on the receipt the script writes.
    assert eo["rule"] != "empty_allowed", "every fire audits, so no typed empty is expected"


def test_the_three_files_agree_on_one_lane():
    assert row()["output_signal"]["path"] == entry()["output_signal"] == contract()["evidence"]["receipt"]


# ── no second scheduled crawler (REV 2 §C) ────────────────────────────────────────────────────


def test_site_audit_records_that_this_lane_supersedes_it():
    site = next(r for r in registry()["lanes"] if r.get("lane_id") == "site-audit")
    assert "superseded_by numbers-truth-audit (phase 2 DOM pass)" in site["note"]


# ── the script the entry runs (lands with LQ-1701) ─────────────────────────────────────────────


def _script() -> Path:
    path = ROOT / SCRIPT
    assert path.is_file(), f"{SCRIPT} is not in this tree (fold LQ-1701 with or before LQ-1703)"
    return path


def _run_script(state_root: Path, *mode: str) -> subprocess.CompletedProcess:
    """The scheduled argv, forced offline: no DB and no HTTP, so nothing live is touched."""
    env = dict(os.environ, TRADEAI_STATE_ROOT=str(state_root), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, str(_script()), *mode, "--no-db", "--no-http", "--state-root", str(state_root)],
        capture_output=True, text=True, timeout=150, cwd=str(ROOT), env=env,
    )


def test_a_shadow_fire_writes_no_receipt(tmp_path):
    """The §23.11 stage clamp's promise: in dry_run the fire cannot advance ok_at or write anything."""
    proc = _run_script(tmp_path, "--dry-run", "--json")
    assert "Traceback" not in proc.stderr, proc.stderr[-800:]
    assert proc.returncode in (0, 1), proc.stderr[-800:]
    assert not (tmp_path / SIGNAL).exists(), "a dry run wrote the receipt it must never write"
    assert list(tmp_path.rglob("*")) == [], "a dry run wrote into the state root"
    payload = json.loads(proc.stdout)
    assert payload["lane_id"] == LID


def test_the_script_accepts_the_registered_flags():
    src = _script().read_text(encoding="utf-8")
    assert f'LANE = "{LID}"' in src, "the script must write under the registered lane id"
    assert "MAX_RUNTIME_S = 120" in src, "the script self-bounds at the allowlist timeout"
    proc = subprocess.run([sys.executable, str(_script()), "--help"], capture_output=True, text=True,
                          timeout=60)
    assert proc.returncode == 0, proc.stderr[-800:]
    for flag in (*entry()["dry_run_arg"], "--apply", "--state-root", "--catalog", "--no-db", "--no-http"):
        assert flag in proc.stdout, f"the registered argv names {flag}; the script does not accept it"

def test_apply_writes_the_v2_receipt_the_contract_reads(tmp_path):
    """--apply against a scratch root: the receipt lands at the registered signal path, on v2, with the
    produced field the contract grades. Forced offline all three sources are unreadable, so the script's
    own dependency_unavailable path runs — the typed skip my contract lists as fatal."""
    proc = _run_script(tmp_path, "--apply", "--json")
    assert "Traceback" not in proc.stderr, proc.stderr[-800:]
    receipt = tmp_path / SIGNAL
    assert receipt.is_file(), "the lane's own writer did not produce the registered signal path"
    doc = json.loads(receipt.read_text(encoding="utf-8"))
    eo = contract()["expected_output"]
    assert doc["schema"] == "LaneRunReceipt@v2", "the entry declares output_receipt v2; the writer must write it"
    assert eo["produced_field"] in doc, "the field the contract grades must exist on the receipt it grades"
    assert doc[eo["produced_field"]] == 0, "all three sources were unreadable: produced_count 0"
    assert set(doc.get("skipped_reasons") or {}) <= set(eo["fatal_skip_reasons"]), (
        "a failed read is a fatal skip the contract names, not an unlisted empty_reason"
    )
    assert doc["ok_at"] is None, "a failed run carries ok_at forward; it must not advance it"
    assert isinstance((doc.get("summary") or {}).get("findings"), list), "the findings list LQ-1702 consumes"
