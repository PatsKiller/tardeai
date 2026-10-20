"""Canary wave 1 (AGENTS.md §23.11 / §23.12 / §23.18 (c)), 2026-10-11 — the first R1 cron row moves shadow -> canary.

COVERS = ["config/lane_registry.json", "config/n8n_run_allowlist.json", "config/n8n_health_contracts.json"]

Selection (read-only evidence, packets/canary-wave1/OPERATOR.md): of the 57 shadow rows only the 22 R1 rows (ingest /
learn) may climb; of those only research-insight-extractor has a natural dispatcher RUN_DONE dry_run, zero
RUN_FAILED / RUN_TIMEOUT / RUN_REFUSED, a flock lock on both the live cron line and scheduler.command_text equal to
the allowlist lock, and a script that loads only DB_PASSWORD (no whole secret-render load). Every other R1 row with a
natural RUN_DONE loads the whole .env / rendered env into the process (the finviz exposure class).

The canary shape (§23.18 (c)): scheduler.kind cron, scheduler.stage canary, dispatch.mode live, allowlist live_arg
set, lock_kind flock, allowlist lock == every flock lock in scheduler.command_text. The failures this guards:
* a canary row whose live fire could double-run the cron line (lock mismatch, safe_flock, no cron lock);
* a live argv that differs from the cron line's argv (the canary must do exactly the cron line's work);
* a canary row without its health contract at stage canary (the operator REVIEWs it before merge, §23.19);
* any other shadow row silently gaining a live argv.
Hermetic: repo config only.
"""

from __future__ import annotations

import copy
import json
import shlex
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.append(str(ROOT / "tests"))
from support import n8n_cutover_waves as CW  # noqa: E402
from tests.support import hermes_learning_cutover as HL  # noqa: E402
from tests.support import comms_intent_consumer_live as CIL  # noqa: E402
from tests.support import data_integrity_monitors_n8n as DIM  # noqa: E402
from tests.support import active_trader_motion_watchdog as ATMW  # noqa: E402
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import lane_stage_clamp as SC  # noqa: E402

REGISTRY = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REGISTRY["lanes"]}
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
CONTRACTS = {c["id"]: c for c in json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())["contracts"]}

#: lane -> the exact cron line it ran on as canary (crontab -l 2026-10-11, L418; matched by text, never by line number).
#: research-insight-extractor climbed canary -> cutover 2026-10-13 17:56 ET (operator _cutover.py --apply, receipt
#: n8n_cutover/research-insight-extractor-20261013T215647Z-cutover.json): this line is now `# RETIRED` and the row is
#: the n8n dispatcher row. The canary-gate checks below run on the canary row rebuilt from this line (_as_canary), so
#: the gate keeps its coverage; the live row is pinned at cutover.
CANARY_WAVE1 = {
    "research-insight-extractor": (
        "50 6,12,18 * * * cd $PROJ && flock -n /tmp/research_insight_extractor.lock "
        "$PY scripts/research_insight_extractor.py >> logs/research_insight_extractor.log 2>&1"
    ),
}
CUTOVER = frozenset({"research-insight-extractor"})


def _as_canary(lane: str) -> dict:
    """The row as it stood at canary (2026-10-11 .. 2026-10-13): kind cron on its live line, stage canary."""
    row = copy.deepcopy(ROWS[lane])
    expr, cmd = CANARY_WAVE1[lane].split(" cd ", 1)[0], "cd " + CANARY_WAVE1[lane].split(" cd ", 1)[1]
    row["scheduler"] = {"kind": "cron", "expression": expr, "match": row["scheduler"]["match"], "stage": "canary",
                        "wave": row["scheduler"]["wave"], "command_text": cmd}
    return row


@pytest.mark.parametrize("lane", sorted(CUTOVER))
def test_canary_lane_is_now_cut_over(lane):
    s = ROWS[lane]["scheduler"]
    assert s["kind"] == "n8n" and s["expression"] == "dispatcher" and s["stage"] == "cutover"
    assert s["cadence"] == CANARY_WAVE1[lane].split(" cd ", 1)[0]
    assert SC.clamp_mode(lane, "live", REGISTRY["lanes"])["effective_mode"] == "live"


@pytest.mark.parametrize("lane", sorted(CANARY_WAVE1))
def test_row_has_the_canary_on_cron_shape_and_is_admitted(lane):
    row, e = _as_canary(lane), ALLOW[lane]
    s = row["scheduler"]
    assert s["kind"] == "cron" and s["stage"] == "canary"
    assert row["dispatch"]["mode"] == "live" and row["dispatch"]["class"] in LD.R1_ADMITTED_CLASSES
    assert isinstance(e["live_arg"], list) and e["lock_kind"] == "flock"
    assert LD.r1_canary_lock_matches(row, e) == (True, "canary_on_cron")
    assert LD.r1_shadow_on_cron_shape(row) == (True, "canary_on_cron")
    assert LD.r1_class_admission(row, e) == (True, f"r1_admitted:{row['dispatch']['class']}")
    assert LD.validate_dispatch_block(row) == []


@pytest.mark.parametrize("lane", sorted(CANARY_WAVE1))
def test_command_text_is_the_live_cron_line_and_its_only_lock_is_the_allowlist_lock(lane):
    line = CANARY_WAVE1[lane]
    s = _as_canary(lane)["scheduler"]
    assert line.startswith(s["expression"] + " ") and s["match"] in line
    assert s["command_text"] == line[len(s["expression"]) + 1:]
    assert LD.cron_flock_locks(s["command_text"]) == [ALLOW[lane]["lock"]]


@pytest.mark.parametrize("lane", sorted(CANARY_WAVE1))
def test_live_argv_is_the_cron_argv(lane):
    """The executor runs command + live_arg; the cron line runs `$PY <script> <args>` (minus redirections)."""
    e = ALLOW[lane]
    toks = shlex.split(_as_canary(lane)["scheduler"]["command_text"].split(">>", 1)[0])
    cron_argv = toks[toks.index("$PY"):]
    assert e["command"] + e["live_arg"] == cron_argv
    assert e["dry_run_arg"] == ["--dry-run"] and "--dry-run" not in e["live_arg"]


@pytest.mark.parametrize("lane", sorted(CANARY_WAVE1))
def test_health_contract_is_built_for_the_canary_stage(lane):
    c = CONTRACTS[lane]
    assert c["stage"] == "canary" and c["target_reason"] == "stage:canary"
    assert {x["check"] for x in c["healthy"]} >= {"last_live_run_done", "output_advanced"}
    assert c["status"] in {"DRAFT", "REVIEWED"}  # agents never mark REVIEWED; the operator flips it before merge


@pytest.mark.parametrize("bad", ["lock_mismatch", "safe_flock", "no_cron_lock", "live_arg_null", "mode_dry_run"])
def test_canary_gate_refuses_a_row_that_cannot_prove_no_double_run(bad):
    lane = "research-insight-extractor"
    row, e = _as_canary(lane), copy.deepcopy(ALLOW[lane])
    if bad == "lock_mismatch":
        e["lock"] = "/tmp/some_other.lock"
    elif bad == "safe_flock":
        e["lock_kind"] = "safe_flock"
    elif bad == "no_cron_lock":
        row["scheduler"]["command_text"] = "cd $PROJ && $PY scripts/research_insight_extractor.py"
    elif bad == "live_arg_null":
        e["live_arg"] = None
    elif bad == "mode_dry_run":
        row["dispatch"]["mode"] = "dry_run"
    ok, why = LD.r1_class_admission(row, e)
    assert not ok and "canary_on_cron" in why, (bad, why)


def test_no_other_shadow_row_gained_a_live_argv():
    """Every other R1 (ingest / learn / llm) shadow row keeps live_arg null (§23.18 (c) shadow shape). Non-R1 shadow
    rows with a pre-existing live_arg are run dry by the stage clamp (test_n8n_maturity_registry_dispatch)."""
    for lane, row in ROWS.items():
        if ((row.get("scheduler") or {}).get("stage") == "shadow"
                and (row.get("dispatch") or {}).get("class") in LD.R1_ADMITTED_CLASSES):
            assert ALLOW[lane].get("live_arg") is None, lane
    canary = sorted(r for r, row in ROWS.items() if (row.get("scheduler") or {}).get("stage") == "canary")
    # heartbeat-watch is the n8n-native canary. momentum-cache-reconcile climbed to canary 2026-10-13 and the
    # operator returned it to shadow the same day (relay refused live, failing every dispatcher run);
    # research-insight-extractor, the R1 cron canary, climbed to cutover 2026-10-13.
    # canary-wave-20261014 moves 14 cron rows to canary (tests/test_canary_wave_20261014.py).
    from tests.test_canary_wave_20261014 import CANARY_WAVE_20261014

    # 2026-10-15 cutover waves (scripts/n8n_cutover_wave.py) add their promoted lanes (tests/support/n8n_cutover_waves.py).
    assert canary == sorted(({"heartbeat-watch", *CANARY_WAVE_20261014} | {
        lane for lane in CW.PROMOTED if (ROWS[lane].get("scheduler") or {}).get("stage") == "canary"}
        | set(HL.LIVE) | set(CIL.LIVE) | set(DIM.LIVE) | set(ATMW.LIVE)) - set(CW.CUT_OVER))  # + hermes-learning cutover PR-2 (tests/support/
    # hermes_learning_cutover.py) + comms-intent consumer live 2026-10-17 (tests/support/comms_intent_consumer_live.py)
    cut = sorted(r for r, row in ROWS.items() if (row.get("scheduler") or {}).get("stage") == "cutover")
    assert set(CUTOVER) <= set(cut), cut


def test_every_shadow_command_text_flock_lock_is_the_allowlist_lock():
    """canary-wave1 synced scheduler.command_text to the live crontab line (crontab -l 2026-10-11) for the shadow rows
    whose line carries a flock and no send (20 rows, incl. 4 drifted: catalyst-symbol-impact, catalyst-graph, maturity-remeasure,
    agent-number-grounding-slo; + the 3 W4 rows). Where command_text names a flock lock it must be the allowlist lock,
    so the lock half of the canary gate is already true for those rows. hermes-pipeline-health (--send) and
    crawl-v3-dashboard (--telegram) and audit-enrichment-coverage (--alert -> send_telegram) are senders on their live line
    (§23.18 ruling 4 / §24.1: never dispatcher-live) and are left without command_text."""
    synced = 0
    for lane, row in ROWS.items():
        s = row.get("scheduler") or {}
        if s.get("stage") not in ("shadow", "canary") or not s.get("command_text"):
            continue
        locks = LD.cron_flock_locks(s["command_text"])
        if locks:
            synced += 1
            assert ALLOW[lane]["lock_kind"] == "flock" and set(locks) == {ALLOW[lane]["lock"]}, (lane, locks)
    assert synced >= 20 + 3 + 1
    for sender in ("hermes-pipeline-health", "crawl-v3-dashboard", "audit-enrichment-coverage"):
        assert "command_text" not in ROWS[sender]["scheduler"], sender
