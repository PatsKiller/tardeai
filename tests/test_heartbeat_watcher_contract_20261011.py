"""tradeai-heartbeat-watcher: the health contract says why it is held and what activation would prove (2026-10-11).

The watcher was held out of W0 on 2026-10-10 because its GET /due filter names lane ``heartbeat-watch``, which has no
registry row (403 ``bad_lane_filter``). These tests keep the committed contract honest about that:

* the six generic contracts in config/n8n_health_contracts.json are exactly what the builder produces (a DRAFT
  contract is regenerated, so a hand edit would be lost on the next --write);
* the watcher contract's "held / no registry row" claim matches the registry, so the note cannot outlive the fix;
* the observe mode the activation packet relies on (stage shadow -> skipped=dispatched_dry_run) is in the generated
  workflow, and the contract describes it;
* the watcher's failures are P1 in both the contract and the fan-in, and the contract says it is additive, not the
  P1 path (AGENTS.md §24.1).

Reads committed files only; no n8n, no network, no state.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import build_n8n_health_contracts as B  # noqa: E402

WF_DIR = ROOT / "docs" / "implementation" / "n8n-maturity" / "workflows"
WID = "tradeai-heartbeat-watcher"
LANE = "heartbeat-watch"


def _contracts() -> dict:
    doc = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))
    return {c["id"]: c for c in doc["contracts"]}


def _index() -> dict:
    return {w["id"]: w for w in json.loads((WF_DIR / "INDEX.json").read_text())["workflows"]}


def _registry_ids() -> set[str]:
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    return {r["lane_id"] for r in reg["lanes"]}


def test_committed_generic_contracts_match_the_builder():
    contracts, index = _contracts(), _index()
    for wid, wf in index.items():
        c = contracts[wid]
        if c.get("status") == "REVIEWED":
            continue                                   # an owner-reviewed contract is kept byte for byte
        built = B.generic_contract(wf, date.fromisoformat(c["baseline"]["computed_on"]))
        assert built == c, f"{wid}: committed DRAFT contract differs from build_n8n_health_contracts.generic_contract"


def test_held_note_matches_the_registry():
    c = _contracts()[WID]
    registered = LANE in _registry_ids()
    says_held = c["state_note"].startswith("HELD") and "no registry row" in c["state_note"]
    if registered:
        assert not says_held, "heartbeat-watch now has a registry row: update GENERIC_STATE['heartbeat-watcher']"
    else:
        assert says_held, "heartbeat-watch has no registry row: the contract must say the watcher is held and why"
        assert any(f["check"] == "lane_unregistered" for f in c["failed"])


def test_observe_mode_is_in_the_workflow_and_the_contract():
    wf = json.loads((WF_DIR / f"{WID}.json").read_text())
    node = next(n for n in wf["nodes"] if n["name"] == "Assert heartbeat fresh")
    code = node["parameters"]["jsCode"]
    assert "dispatched_dry_run" in code and "mode=live" in json.dumps(wf)
    assert wf["settings"]["saveManualExecutions"] is False
    assert wf["settings"]["errorWorkflow"] == "tradeai-incident-router"
    c = _contracts()[WID]
    checks = {h["check"] for h in c["healthy"]}
    assert {"observe_mode_skip", "live_run_fresh"} <= checks


def test_watcher_failures_are_p1_and_additive():
    from scripts import n8n_incident_fanin as F

    assert WID in F.WFERR_P1_WORKFLOWS
    c = _contracts()[WID]
    assert c["alerting"]["failed"]["notifier_priority"] == "P1"
    note = c["remediation"]["note"]
    assert "not the P1 path" in note and "§24.1" in note
    assert "has no reader" not in note
    names = " ".join(e["name"] for e in c["connects_to"])
    assert "n8n-workflow-error" in names and "heartbeat-watch" in names


def test_no_generic_contract_claims_the_fanin_has_no_reader():
    for wid in _index():
        assert "has no reader" not in _contracts()[wid]["remediation"]["note"], wid
