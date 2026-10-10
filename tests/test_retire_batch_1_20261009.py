"""Retire batch 1 (operator approval 2026-10-09 23:10 ET): the repository half of the retirement.

33 inventory units (17 crontab lines, 16 user timers) were verified idle / never-running / without a
consumer (n8n-maturity cron inventory, retire_check_R1..R3). This PR changes only repository files:

  * 32 lane rows become RETIRED with their inventory id; they keep declaring their line / unit, so the
    gate stays green while the lines are live and is ALIGNED once they are commented and disabled;
  * opening-intelligence keeps its row (it also declares L790) and only drops the 03:30 schedule (L789);
  * the rows are hand-curated, so reconcile_lane_registry.py keeps the decision instead of re-deriving
    the row ACTIVE from the scheduler snapshot;
  * pipeline steps of retired jobs move to ``excluded`` (a cutover must not resurrect them);
  * the 11 retired timers listed in config/expected_services.json leave it (its _how_to_change rule);
  * the self-healing evidence for the Hermes backlog drain follows the coordinator, which still runs it.

Hermetic: repository files only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import lane_registry as LR  # noqa: E402
from scripts.lib import n8n_lane_host_conflict as HC  # noqa: E402
from scripts.lib.lane_state_drift import classify_lanes  # noqa: E402

CRON_LINES = {
    "run-automated-trade-proposal-revalidation": "cron:L125",
    "run-scheduled-atp2-research-cycle-evening": "cron:L151",
    "run-scheduled-atp2-research-cycle-at-0-4": "cron:L157",
    "run-scheduled-atp2-research-cycle-at-0-9": "cron:L169",
    "run-scheduled-stale-proposal-sweeper-report": "cron:L170",
    "run-scheduled-stale-proposal-sweeper-dry": "cron:L181",
    "run-scheduled-atp2-research-cycle-overnight": "cron:L189",
    "rebalance-verifier": "cron:L190",
    "run-scheduled-atp2-research-cycle-eod": "cron:L214",
    "rerun-cio-dual-consensus": "cron:L507",
    "commit-hermes-daily": "cron:L518",
    "claude-challenger-curator": "cron:L588",
    "momentum-scalp-validation-fast-path": "cron:L633",
    "cloud-consensus-verdict": "cron:L687",
    "hermes-backlog-drain": "cron:L748",
    "hermes-research-agenda-at-15-18": "cron:L822",
}
AGENTS = ("aegis", "argus", "darwin", "iris", "maria", "reflection", "risk_agent", "sentinel", "tax_agent", "vega")
TIMERS = {f"tradeai-agent-runtime-{a.replace('_', '-')}": f"tradeai-agent-runtime@{a}.timer" for a in AGENTS}
TIMERS.update({
    "hermes-advisory-cache-worker": "hermes-advisory-cache-worker.timer",
    "hermes-source-discovery-dryrun": "hermes-source-discovery-dryrun.timer",
    "high-llm-execution-worker": "high-llm-execution-worker.timer",
    "tradeai-advisory-shadow-session": "tradeai-advisory-shadow-session.timer",
    "tradeai-stance-organic-observe-early": "tradeai-stance-organic-observe-early.timer",
    "tradeai-stance-organic-observe": "tradeai-stance-organic-observe.timer",
})


def _registry() -> dict:
    return LR.load_registry(ROOT / "config" / "lane_registry.json")


def _rows() -> dict:
    return {r["lane_id"]: r for r in _registry()["lanes"]}


def _json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_batch_is_exactly_32_retired_rows_with_inventory_ids():
    rows = _rows()
    batch = {k: r for k, r in rows.items() if r.get("retire_batch") == "retire-batch-1"}
    assert len(CRON_LINES) == 16 and len(TIMERS) == 16
    assert set(batch) == set(CRON_LINES) | set(TIMERS)
    for lane, inv in CRON_LINES.items():
        assert batch[lane]["inventory_id"] == inv, lane
    for lane, unit in TIMERS.items():
        assert batch[lane]["inventory_id"] == f"timer:{unit}", lane
        assert batch[lane]["scheduler"] == {"kind": "systemd", "expression": unit}, lane
    for lane, r in batch.items():
        assert r["state"] == "RETIRED" and r["state_since"] == "2026-10-09", lane
        assert r["reason_confidence"] == "ESTABLISHED" and r["reason_evidence"], lane
        assert r["state_reason"].startswith("operator-approved retire batch 1 2026-10-09"), lane
        assert r["inventory_id"] in r["state_reason"], lane
        # the generator must not own a retired row: it would re-derive it ACTIVE from the snapshot
        assert "generated_by" not in r, lane
    assert LR.validate_registry(_registry()) == []


def test_superseded_by_names_live_rows():
    rows = _rows()
    for lane, r in rows.items():
        if r.get("retire_batch") == "retire-batch-1" and r.get("superseded_by"):
            assert rows[r["superseded_by"]]["state"] == "ACTIVE", lane


def test_opening_intelligence_keeps_its_row_and_drops_only_the_0330_schedule():
    r = _rows()["opening-intelligence"]
    assert r["state"] == "ACTIVE" and "retire_batch" not in r
    assert r["scheduler"]["schedules"] == ["0 7 * * 1-5"] and r["scheduler"]["expression"] == "0 7 * * 1-5"
    assert r["scheduler"]["match"] == "scripts/opening_intelligence.py --persist >>"
    assert r["expected_cadence_hours"] == 72.0
    assert r["schedule_change"]["removed_schedule"] == "30 3 * * 1-5"
    assert r["schedule_change"]["inventory_id"] == "cron:L789"


def test_gate_is_green_before_and_aligned_after_the_host_apply():
    """Before: lines live, timers enabled -> no undeclared job and no cron conflict (timers are host-only).
    After: lines commented with the retire tag, timers disabled -> every batch row ALIGNED."""
    reg = _registry()
    retiring = "0 4 * * 1-5 cd $PROJ && ./scripts/run_scheduled_atp2_research_cycle.sh --cycle premarket_4am >> x 2>&1"
    staying = "0 7 * * 1-5 cd $PROJ && $PY scripts/opening_intelligence.py --persist >> logs/o.log 2>&1"
    found = {"cron": LR.discover_cron(f"{retiring}\n{staying}"), "systemd": [], "systemd_services": []}
    assert LR.find_undeclared(reg, found, n8n_known_ids=[]) == []
    lanes = [r for r in reg["lanes"] if r.get("retire_batch") == "retire-batch-1" or r["lane_id"] == "opening-intelligence"]
    before = classify_lanes(lanes, cron_rows=found["cron"], host_state={"timers": {}})
    assert not [r for r in before if r["kind"] == "cron" and r["code"] not in (HC.ALIGNED, HC.UNCLASSIFIED)]
    commented = f"# RETIRED 2026-10-10 inventory cron:L157 {retiring}\n{staying}"
    after_cron = LR.discover_cron(commented)
    off = {u: {"unit_file_state": "disabled", "sub_state": "dead", "next_elapse": "", "recurring": True}
           for u in TIMERS.values()}
    after = {r["lane_id"]: r["code"] for r in classify_lanes(lanes, cron_rows=after_cron, host_state={"timers": off})}
    assert set(after.values()) == {HC.ALIGNED}, after
    tagged = LR.discover_commented_cron(commented)
    assert tagged and any("RETIRED 2026-10-10" in t for t in tagged[0]["tags"])


def test_retired_pipeline_steps_are_excluded_not_steps():
    gone = {
        "config/pipelines/hermes_overnight.json": {"backlog_drain": 748, "commit_hermes_daily": 518},
        "config/pipelines/after_close.json": {"atp2_research_eod": 214, "stale_proposal_sweeper_report": 170},
    }
    for rel, ids in gone.items():
        m = _json(rel)
        steps = {st["id"] for stage in m["stages"].values() for st in stage["steps"]}
        assert not steps & set(ids), rel
        retired = [e for e in m["excluded"] if e["category"] == "RETIRED"]
        assert len(retired) == len(ids), rel
        for e in retired:
            assert isinstance(e["cron_line"], int) and e["reason"].startswith("operator-approved retire batch 1")
            assert any(f"cron:L{n}" in e["reason"] for n in ids.values()), e


def test_expected_services_no_longer_expects_the_retired_timers():
    units = {u["unit"] for u in _json("config/expected_services.json")["units"]}
    assert not units & set(TIMERS.values())
    # the four persona timers that keep running stay expected
    for keep in ("steph", "alex", "morgan"):
        assert f"tradeai-agent-runtime@{keep}.timer" in units


def test_backlog_drain_self_healing_evidence_follows_the_coordinator():
    m = next(x for x in _json("config/self_healing_mechanisms.json")["mechanisms"] if x["id"] == "hermes_backlog_drain")
    ev = m["evidence_source"]
    assert ev["path"] == "logs/hermes_coordinator.log" and ev["ts_regex"] and ev["line_regex"] == "backlog_drain: "
    line = "2026-10-09 22:30:02,704 [hermes-coordinator]   backlog_drain: ok — Done in 3.2s: 2 drained, 2 validated, 0 failed"
    import re
    assert re.search(m["success_predicate"]["regex"], line)
    assert not re.search(m["success_predicate"]["regex"], line.replace("2 drained", "0 drained"))


def test_cloud_consensus_policy_is_disabled():
    pol = _json("config/cloud_consensus_policy.json")
    assert pol["enabled"] is False and "cron:L687" in pol["retired_note"]
