"""tradeai-heartbeat-watcher: the health contract says why it is held and what activation would prove (2026-10-11).

The watcher was held out of W0 on 2026-10-10 because its GET /due filter names lane ``heartbeat-watch``, which has no
registry row (403 ``bad_lane_filter``). These tests keep the committed contract honest about that:

* the six generic contracts use the actual builder merge: REVIEWED bodies are kept,
  authored DRAFT limits and review history survive, and unreviewed generated fields refresh;
* the watcher contract's "held / no registry row" claim matches the registry, so the note cannot outlive the fix;
* the observe mode the activation packet relies on (stage shadow -> skipped=dispatched_dry_run) is in the generated
  workflow, and the contract describes it;
* the watcher's failures are P1 in both the contract and the fan-in, and the contract says it is additive, not the
  P1 path (AGENTS.md §24.1).

Reads committed files only; no n8n, no network, no state.
"""

from __future__ import annotations

import json
import copy
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import build_n8n_health_contracts as B  # noqa: E402
from scripts.lib import n8n_health_contracts as H  # noqa: E402
from scripts.lib.n8n_momentum_lifecycle import contract_body_digest, contract_review_proven  # noqa: E402

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
        as_of = date.fromisoformat(c["baseline"]["computed_on"])
        rebuilt = B.build(
            registry={"lanes": []},
            allowlist={"lanes": []},
            catalogue={},
            inventory={},
            index={"workflows": [wf]},
            ledger=None,
            excluded=frozenset(),
            as_of=as_of,
            existing={"contracts": [c]},
        )["contracts"][0]
        if c.get("status") == "REVIEWED":
            assert rebuilt == c, f"{wid}: owner-reviewed contract was rewritten"
            continue
        assert rebuilt["status"] == c["status"] == "DRAFT"
        assert rebuilt["baseline"] == c["baseline"], f"{wid}: authored limits were replaced by defaults"
        assert rebuilt["owner"] == c["owner"]
        assert rebuilt.get("ownership_confirmation") == c.get("ownership_confirmation")
        review = copy.deepcopy(c.get("review"))
        if isinstance(review, dict) and "proposed_contract_body_sha256" in review:
            review["proposed_contract_body_sha256"] = contract_body_digest(rebuilt)
        assert rebuilt.get("review") == review, f"{wid}: review history was lost or fabricated"
        assert H.validate_contract(rebuilt) == [], wid
        assert contract_review_proven(rebuilt) is False, wid
        generated = B.generic_contract(wf, as_of)
        generated_fields = set(generated) - {"baseline", "owner", "ownership_confirmation", "review"}
        assert {k: rebuilt[k] for k in generated_fields} == {k: generated[k] for k in generated_fields}, wid


def test_authored_draft_limits_survive_without_manufacturing_review():
    wf = _index()["tradeai-dispatcher"]
    draft = copy.deepcopy(_contracts()[wf["id"]])
    draft["baseline"].update(timeout_s=99, freshness_degraded_after_h=0.5, freshness_failed_after_h=1.0)
    before = copy.deepcopy(draft)
    rebuilt = B.build(
        registry={"lanes": []},
        allowlist={"lanes": []},
        catalogue={},
        inventory={},
        index={"workflows": [wf]},
        ledger=None,
        excluded=frozenset(),
        as_of=date(2026, 10, 12),
        existing={"contracts": [draft]},
    )["contracts"][0]
    assert draft == before
    assert rebuilt["baseline"] == draft["baseline"]
    assert rebuilt["status"] == "DRAFT" and contract_review_proven(rebuilt) is False
    assert rebuilt["review"]["baseline_correction_requires_review"] is True
    assert rebuilt["review"]["proposed_contract_body_sha256"] == contract_body_digest(rebuilt)


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
