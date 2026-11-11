"""ANCHOR: ANALYST_WEEKLY_FLOCK_HELD_LQ1863_20261110 — the weekly analyst lane's lock skip, and the contract
baseline that still believed the retired cron twin.

LQ-20261107-1863. wave_watch reported `generate-analyst-reports-autonomous-weekly`'s latest live n8n slot as
RUN_SKIPPED_LOCK / flock_held (2026-11-09T02:15:07Z, exit 75, duration 0.029 s). The holder was the legacy host
cron twin, line 577, which started five seconds earlier (02:15:02Z, pid 3552391) and ran the same slot to completion
(04:40:24Z, 8722 s). The n8n arm's record is honest (`state=RUN_SKIPPED_LOCK`, `output_verdict not_evaluated /
flock_held`, `retry skipped`), and `run_quality.grade` grades it NOT_LIVE / skipped because the lane's scheduler is
n8n, so the file-receipt "twin run" exemption (which requires a non-n8n scheduler) cannot fire. This file pins that
honesty and fixes what is not honest: the lane's REVIEWED health contract.

The contract was written at the shadow stage and never rebuilt when the lane reached cutover (LQ-20261107-1590):

* `baseline.timeout_s` was 1800 and `duration_degraded_above_s` 1440.0, while LQ-20261107-1413 raised the gettable
  bound to 21600 s precisely because the measured weekly run takes 2 h 25 m (8722 s). `run_quality` reads that
  baseline, so the lane's first honest live run would have graded DEGRADED "took 8722 s, above its contract's
  1440 s degraded limit".
* `cron_twin_output_fresh` still declared that "the live cron line" keeps the output fresh — a line retired
  2026-11-09 00:02 ET. That criterion is the false comfort this ticket was opened on: it names a holder that no
  longer exists, and it is replaced by the dispatcher's own `fresh` / `output_advanced` criteria.
* `target_reason` still said `dispatch:dry_run` after the registry moved to a live dispatcher.
* No gate measured the disagreement: `check_n8n_health_contracts.py` was clean (rc 0) with the stale baseline in
  place. The new TIMEOUT_DRIFT warning is the measurement.

Synthetic and config-only: no run, no network, no DB, no cron/systemd edit, no lock file touched, no push.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.lib import n8n_health_contracts as H
from scripts.lib import run_quality as Q

ROOT = Path(__file__).resolve().parents[1]
LANE = "generate-analyst-reports-autonomous-weekly"
OUT_SIGNAL = "logs/analyst_reports_autonomous.log"
LOCK = "/tmp/analyst_reports_weekly.lock"

#: The twin's own LaneRunReceipt@v1: 2026-11-09T02:15:02.009392Z -> 04:40:24.448058Z.
MEASURED_RUN_S = 8722.4
TIMEOUT_S = 21600  # 6 h, LQ-20261107-1413; covers 8722 s and still ends before the next weekly fire
LIMIT_S = 17280.0  # 80% of the class-default timeout


def _doc(name):
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def contract() -> dict:
    return next(c for c in _doc("n8n_health_contracts.json")["contracts"] if c.get("id") == LANE)


def entry() -> dict:
    return next(e for e in _doc("n8n_run_allowlist.json")["lanes"] if e.get("lane_id") == LANE)


def registry_row() -> dict:
    return next(r for r in _doc("lane_registry.json")["lanes"] if r.get("lane_id") == LANE)


def _by_check(c: dict, name: str) -> dict:
    return next(h for h in c["healthy"] if h.get("check") == name)


# ── the contract baseline measures what the lane actually runs inside ──────────────────────────────────────────────

def test_nobody_else_owns_this_lock():
    """The lock the dispatcher competes for is this lane's own: no other allowlist entry names it, and the only
    cron line that ever did is retired. (Read-only config census; the live crontab is checked by
    scripts/check_cron_twins.py, which reports the twin as a stale baseline entry, not a finding.)"""
    users = [e["lane_id"] for e in _doc("n8n_run_allowlist.json")["lanes"] if e.get("lock") == LOCK]
    assert users == [LANE], users
    assert entry()["lock_kind"] == "flock"
    twin = next(f for f in _doc("cron_twin_baseline.json")["findings"]
                if f.get("key") == f"N8N_LIVE_WITH_CRON_TWIN:{LANE}")
    assert "flock -n /tmp/analyst_reports_weekly.lock" in twin["evidence"]


def test_contract_baseline_is_derived_from_the_lanes_timeout():
    c, e = contract(), entry()
    assert e["timeout_s"] == TIMEOUT_S
    assert c["baseline"]["timeout_s"] == e["timeout_s"], "contract timeout drifted from the allowlist bound"
    assert c["baseline"]["duration_degraded_above_s"] == LIMIT_S
    assert c["baseline"]["basis"] == "CLASS_DEFAULT_PROVISIONAL"  # < MIN_LEARNED_RUNS live n8n runs
    dur = _by_check(c, "duration_within_baseline")["text"]
    assert "17280" in dur and "21600" in dur and "1800" not in dur


def test_the_measured_two_and_a_half_hour_run_is_not_graded_degraded():
    """Production-shaped: the 8722 s run, graded by the real contract. Before the baseline fix the contract's
    1440 s limit flagged it; after, it is inside the lane's own bound and earns no duration flag."""
    now = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)
    start = now - timedelta(hours=6)
    row = {"lane_id": LANE, "state": "ACTIVE", "status": "ok", "runs": [{
        "mode": "live", "result": "succeeded", "started_at": start.isoformat(),
        "finished_at": (start + timedelta(seconds=MEASURED_RUN_S)).isoformat(), "duration_s": MEASURED_RUN_S,
        "run_id": "d:lane", "exit_code": 0, "reason": None, "source": "n8n run ledger"}]}
    lane = {"lane_id": LANE, "state": "ACTIVE", "output_signal": {"kind": "file_mtime", "path": OUT_SIGNAL},
            "scheduler": {"kind": "n8n", "stage": "cutover"}, "dispatch": {"mode": "live"}}
    evidence = {"receipt": None, "receipt_path": None, "output_at": start + timedelta(seconds=MEASURED_RUN_S),
                "ledger": [], "history": [], "contract": contract(), "freshness": [], "freshness_known": True,
                "plausibility": [], "plausibility_known": True}
    q = Q.grade(row, lane, evidence, now=now)
    assert q["checks"]["duration_vs_history"]["result"] != "fail", q["checks"]["duration_vs_history"]
    assert not any("degraded limit" in r for r in q["reasons"]), q["reasons"]
    assert q["checks"]["ran_live"]["result"] == "pass"
    assert q["grade"] != "FAILED"


# ── the healthy criteria name the holder that exists, not the retired twin ────────────────────────────────────────

def test_a_cutover_lane_does_not_name_a_retired_cron_twin():
    c, row = contract(), registry_row()
    assert (row["scheduler"]["kind"], row["scheduler"]["stage"], row["dispatch"]["mode"]) == ("n8n", "cutover", "live")
    checks = [h["check"] for h in c["healthy"]]
    assert "cron_twin_output_fresh" not in checks, f"names a cron line retired 2026-11-09: {checks}"
    assert "canary_live_done" in checks and "RUN_SKIPPED_LOCK is a stray trigger" in _by_check(c, "canary_live_done")["text"]
    assert OUT_SIGNAL in _by_check(c, "fresh")["text"]
    assert "advanced" in _by_check(c, "output_advanced")["text"]
    assert c["target_reason"] == H.registry_targets(_doc("lane_registry.json"))[LANE] == "stage:cutover"


# ── the gate measures the drift instead of reporting clean ────────────────────────────────────────────────────────

def test_gate_warns_when_a_contract_baseline_disagrees_with_the_allowlist():
    doc = _doc("n8n_health_contracts.json")
    reg = _doc("lane_registry.json")
    idx = json.loads((ROOT / "docs/implementation/n8n-maturity/workflows/INDEX.json").read_text(encoding="utf-8"))
    allow = _doc("n8n_run_allowlist.json")

    clean = H.check(doc, reg, idx, allowlist=allow)
    assert not any(w.startswith(f"TIMEOUT_DRIFT {LANE}") for w in clean["warnings"]), clean["warnings"]

    stale_doc = copy.deepcopy(doc)
    stale = next(c for c in stale_doc["contracts"] if c.get("id") == LANE)
    stale["baseline"]["timeout_s"] = 1800
    stale["baseline"]["duration_degraded_above_s"] = 1440.0
    bad = H.check(stale_doc, reg, idx, allowlist=allow)
    line = next(w for w in bad["warnings"] if w.startswith(f"TIMEOUT_DRIFT {LANE}"))
    assert "1800" in line and str(TIMEOUT_S) in line


# ── the skip is graded honestly: skipped is not success, and not silence ──────────────────────────────────────────

def test_a_skip_on_an_n8n_only_lane_is_graded_not_live_however_twin_shaped_its_receipt():
    """The recorded slot: n8n skipped at 02:15:07Z, the twin's ok receipt started 02:15:02Z (5 s earlier, inside
    SAME_RUN). With scheduler.kind n8n the run_quality twin exemption must NOT fire: the slot did no n8n work."""
    now = datetime(2026, 11, 9, 6, 0, tzinfo=timezone.utc)
    slot = now - timedelta(hours=3.75)  # 02:15Z
    row = {"lane_id": LANE, "state": "ACTIVE", "status": "ok", "runs": [{
        "mode": "live", "result": "skipped_lock", "started_at": slot.isoformat(),
        "finished_at": (slot + timedelta(seconds=0.029)).isoformat(), "duration_s": 0.029, "run_id": "d:skip",
        "exit_code": 75, "reason": "flock_held", "source": "n8n run ledger"}]}
    lane = {"lane_id": LANE, "state": "ACTIVE", "output_signal": {"kind": "file_mtime", "path": OUT_SIGNAL},
            "scheduler": {"kind": "n8n", "stage": "cutover"}, "dispatch": {"mode": "live"}}
    receipt = {"started_at": (slot - timedelta(seconds=5)).isoformat(), "finished_at": now.isoformat(),
               "status": "ok", "mode": "live", "pid": 3552391}
    ledger = [{"run_id": "d:skip", "mode": "live", "state": "RUN_SKIPPED_LOCK", "started": slot, "duration_s": 0.029,
               "reason": "flock_held", "why": None, "produced": None, "mtime_before": None, "mtime_after": None}]
    evidence = {"receipt": receipt, "receipt_path": None, "output_at": now - timedelta(hours=1),
                "ledger": ledger, "history": [], "contract": contract(), "freshness": [], "freshness_known": True,
                "plausibility": [], "plausibility_known": True}
    q = Q.grade(row, lane, evidence, now=now)
    assert (q["grade"], q["sub"]) == ("NOT_LIVE", "skipped"), q
    assert "did no work" in q["reasons"][0] and "held its lock" in q["reasons"][0]
    assert q["checks"]["ran_live"]["result"] == "fail"
    assert q["graded_run"]["result"] == "skipped_lock"
    assert any("n8n is the scheduler of record but its last live slot did nothing" in d for d in q["design_issues"])
