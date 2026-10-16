"""Canary wave 2026-10-14 (AGENTS.md §23.11 / §23.12 / §23.18 (c)) — 11 shadow cron rows move shadow -> canary.

COVERS = ["config/lane_registry.json", "config/n8n_run_allowlist.json", "config/n8n_health_contracts.json"]

Selection (read-only evidence, n8n-maturity packets/canary-wave-20261014/OPERATOR.md): every ACTIVE shadow cron row in
dry_run with >= 5 natural RUN_DONE dry runs and 0 dry-run receipts in any other state than RUN_DONE / RUN_SKIPPED_LOCK
(data/runtime/n8n_runs), a `flock` lock on the live cron line (crontab -l 2026-10-14) equal to the allowlist lock,
scheduler.command_text == that line, a live argv equal to the cron line's argv, and no sender / broker reach
(advisory_lane_guard.scan_entry) — except trade-ai-scalp-live, the named 4.0.0 exception, admitted to this wave by the
operator ruling of 2026-10-14 ~11:05 ET (cut over after defects fixed + dry run + regression tests + >= 1 successful
live n8n run with cron present under the shared lock; multi-day soak removed).

Excluded from the 20 that met the ledger bar (pinned below so a later edit cannot slip one in):
* hermes-pipeline-health: the cron line's live arg is --send (alert_dispatcher_unified); a sender.
* resolve-due-checkpoints, aegis-social-sentiment: no flock lock on the cron line (cron flock wrapper needs a cron grant).
* hermes-scope-governor, hermes-score-event-feeder: safe_flock.sh only; the canary gate needs `flock` + lock_kind flock.
* catalyst-momentum-engine-overnight: 7.0.0 sender baseline (advisory send + account reads); lock_kind safe_flock.
Hermetic: repo config only.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.append(str(ROOT / "tests"))
from support import n8n_cutover_waves as CW  # noqa: E402
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import lane_stage_clamp as SC  # noqa: E402

REGISTRY = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REGISTRY["lanes"]}
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
CONTRACTS = {c["id"]: c for c in json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())["contracts"]}

#: lane -> (live cron line number on 2026-10-14, flock lock, live_arg)
CANARY_WAVE_20261014 = {
    "job-coverage-monitor": (391, "/tmp/tradeai_job_coverage_monitor.lock", []),
    "material-change-detector-stage1": (938, "/tmp/material_change_detect.lock", []),
    "document-mentions-backfill": (922, "/tmp/document_mentions_backfill.lock", []),
    "trade-ai-scalp-live": (1055, "/tmp/tradeai_scalp_live.lock", []),
    "hermes-entity-spike-discovery": (688, "/tmp/hermes_entity_spike.lock", []),
    "data-gap-resolver-at-0-10-16": (139, "/tmp/data_gap_resolver.lock", []),
    "hermes-analyst-signal-discovery": (690, "/tmp/hermes_analyst_signal.lock", []),
    "hermes-news-bridge": (415, "/tmp/hermes_news_bridge.lock", []),
    "finviz-proactive-research": (524, "/tmp/finviz_proactive.lock", []),
    "finviz-sector-research": (526, "/tmp/finviz_sector.lock", []),
    "proposal-backtest-engine": (608, "/tmp/proposal_backtest.lock", []),
}
EXCLUDED = {
    "hermes-pipeline-health": "live arg --send (sender)",
    "resolve-due-checkpoints": "no flock lock on the cron line",
    "aegis-social-sentiment": "no flock lock on the cron line",
    "hermes-scope-governor": "safe_flock.sh only",
    "hermes-score-event-feeder": "safe_flock.sh only",
    "catalyst-momentum-engine-overnight": "7.0.0 sender baseline; lock_kind safe_flock",
    # Passed every canary check, then held by the operator 2026-10-14 (~12:35 ET): failing on cron (pool_incomplete).
    "hermes-research-worker-pool": "held 2026-10-14: failing on cron (pool_incomplete)",
    # Dropped from the wave 2026-10-14 (PR #1729 CI): their existing shadow contracts pin them at shadow.
    "identity-sweep-stage0": "held 2026-10-14: sw4 shadow contract / --apply live_arg",
    "news-to-catalyst": "held: unexplained 13:42Z live run + w5 event-consumer contract",
}
LANES = sorted(CANARY_WAVE_20261014)


def _cron_argv(command_text: str) -> list[str]:
    toks = shlex.split(command_text.split(">>", 1)[0].split(" #", 1)[0])
    return toks[toks.index("$PY"):]


#: 2026-10-15/16: a lane the n8n cutover waves moved on to the dispatcher cutover row leaves the cron-canary pin
#: (tests/test_n8n_cutover_wave_20261015.py pins the cutover row).
@pytest.mark.parametrize("lane", sorted(set(LANES) - set(CW.CUT_OVER)))
def test_row_is_a_canary_cron_row(lane):
    row = ROWS[lane]
    s, d = row["scheduler"], row["dispatch"]
    assert row["state"] == "ACTIVE"
    assert (s["kind"], s["stage"], d["mode"]) == ("cron", "canary", "live")
    assert d["cron"] == [s["expression"]]
    assert row["canary"]["wave"] == "canary-wave-20261014" and row["canary"]["since"] == "2026-10-14"
    assert "operator ruling 2026-10-14" in row["canary"]["evidence"]
    assert "RUN_DONE" in row["canary"]["evidence"] and "0 RUN_FAILED" in row["canary"]["evidence"]
    assert f"L{CANARY_WAVE_20261014[lane][0]}" in row["canary"]["lock_proof"]
    assert "live_arg null" in row["canary"]["rollback"]


@pytest.mark.parametrize("lane", LANES)
def test_lock_is_the_cron_flock_lock_and_live_argv_is_the_cron_argv(lane):
    row, e = ROWS[lane], ALLOW[lane]
    _, lock, live = CANARY_WAVE_20261014[lane]
    assert e["lock"] == lock and e["lock_kind"] == "flock" and not lock.endswith(".dryrun")
    assert LD.cron_flock_locks(row["scheduler"]["command_text"]) == [lock]
    assert e["live_arg"] == live
    assert e["dry_run_arg"] == ["--dry-run"]
    assert [*e["command"], *e["live_arg"]] == _cron_argv(row["scheduler"]["command_text"])


@pytest.mark.parametrize("lane", LANES)
def test_gates_admit_the_canary_shape(lane):
    row, e = ROWS[lane], ALLOW[lane]
    assert LD.dispatch_eligible(row)[0] is True
    assert LD.validate_dispatch_block(row) == []
    if row["dispatch"]["class"] in LD.R1_ADMITTED_CLASSES:
        assert LD.r1_class_admission(row, e) == (True, f"r1_admitted:{row['dispatch']['class']}")
        assert LD.r1_canary_lock_matches(row, e) == (True, "canary_on_cron")
    assert SC.clamp_mode(lane, "live", list(ROWS.values()))["effective_mode"] == "live"


@pytest.mark.parametrize("lane", LANES)
def test_contract_is_reviewed_at_stage_canary(lane):
    """The 6 contracts that were DRAFT were regenerated at stage canary and marked REVIEWED by the operator
    (2026-10-14 ~11:25 ET). The 8 already REVIEWED before this wave are kept byte for byte by the builder, so they still
    record stage shadow; refreshing them is an operator re-review (packet OPERATOR.md), never an agent edit."""
    c = CONTRACTS[lane]
    assert c["status"] == "REVIEWED"
    assert c["stage"] == ("shadow" if lane in REVIEWED_BEFORE_WAVE else "canary"), lane
    assert "UNKNOWN" not in json.dumps(c)


REVIEWED_BEFORE_WAVE = frozenset({
    "material-change-detector-stage1", "document-mentions-backfill", "trade-ai-scalp-live",
    "finviz-proactive-research", "finviz-sector-research", "proposal-backtest-engine",
})


#: 2026-10-15: identity-sweep-stage0 was held only by its sw4 shadow pins; cutover wave CW1 promotes it (the sw4 pins
#: now follow tests/support/n8n_cutover_waves.py). A promoted lane leaves this check.
@pytest.mark.parametrize("lane", sorted(set(EXCLUDED) - set(CW.PROMOTED)))
def test_excluded_lanes_stay_shadow(lane):
    row = ROWS[lane]
    assert row["scheduler"].get("stage") == "shadow" and row["dispatch"]["mode"] == "dry_run", lane
    assert "canary" not in row, lane
