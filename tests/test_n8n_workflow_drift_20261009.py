"""AGENTS.md 3.0.0 §23.10 P18 — git-vs-live n8n workflow drift (audit C G9).

Fixture workflows under tmp_path only; no docker, no n8n DB. The live copy differs from git by the relay
host the operator substitutes at import, which is not drift; a node edit is; an id with no generated file
is MISSING_IN_GIT. --dry-run writes nothing, --write writes the receipt under the state root.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import check_n8n_workflow_drift as D  # noqa: E402
from scripts.lib import n8n_live_inventory as INV  # noqa: E402

PLACEHOLDER = "http://RELAY_HOST:18092"
WF_ID = "078e8fcbea0c5020"


def _git_doc() -> dict:
    return {
        "id": WF_ID,
        "name": "lane-a",
        "active": False,
        "nodes": [
            {
                "id": "n1",
                "name": "Schedule",
                "type": "n8n-nodes-base.scheduleTrigger",
                "typeVersion": 1.2,
                "position": [240, 300],
                "parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": "*/15 * * * *"}]}},
            },
            {
                "id": "n2",
                "name": "Relay constants",
                "type": "n8n-nodes-base.set",
                "typeVersion": 3.4,
                "position": [480, 300],
                "parameters": {
                    "assignments": {
                        "assignments": [{"name": "TRADEAI_N8N_RUN_URL", "type": "string", "value": PLACEHOLDER}]
                    }
                },
            },
            {
                "id": "n3",
                "name": "POST relay /run",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.2,
                "position": [720, 300],
                "parameters": {"method": "POST", "url": "={{ $json.TRADEAI_N8N_RUN_URL }}/run"},
            },
        ],
        "connections": {
            "Schedule": {"main": [[{"node": "Relay constants", "type": "main", "index": 0}]]},
            "Relay constants": {"main": [[{"node": "POST relay /run", "type": "main", "index": 0}]]},
        },
        "settings": {"executionOrder": "v1", "timezone": "America/New_York"},
    }


def _live(doc: dict, host: str = "172.19.0.1") -> dict:
    live = json.loads(json.dumps(doc).replace("RELAY_HOST", host))
    live["active"] = True
    return live


def _gen_dir(tmp_path: Path) -> Path:
    gen = tmp_path / "generated"
    (gen / "pending").mkdir(parents=True, exist_ok=True)
    (gen / "lane-a.json").write_text(json.dumps(_git_doc()), encoding="utf-8")
    shadow = _git_doc()
    shadow["id"], shadow["name"] = "baddad5487f9c288", "lane-a-shadow"
    (gen / "pending" / "lane-a-shadow.json").write_text(json.dumps(shadow), encoding="utf-8")
    (gen / "INDEX.json").write_text(
        json.dumps(
            {
                "relay_url_placeholder": PLACEHOLDER,
                "lanes": [{"lane_id": "lane-a", "live_workflow_id": WF_ID, "shadow_workflow_id": "baddad5487f9c288"}],
            }
        ),
        encoding="utf-8",
    )
    return gen


def _eval(tmp_path: Path, workflows: list[dict], **kw) -> list[dict]:
    return D.evaluate(
        workflows, git=INV.git_workflows(_gen_dir(tmp_path)), placeholder=PLACEHOLDER, repo_root=tmp_path, **kw
    )


def test_relay_host_substitution_and_layout_are_not_drift(tmp_path):
    live = _live(_git_doc())
    live["nodes"][0]["position"] = [999, 999]
    live["nodes"][1]["webhookId"] = "assigned-by-n8n"
    rows = _eval(tmp_path, [live])
    assert [(r["id"], r["status"], r["diffs"]) for r in rows] == [(WF_ID, D.OK, [])]
    assert rows[0]["git_file"] == "generated/lane-a.json" and rows[0]["placeholder_unsubstituted"] is False


def test_pending_shadow_files_are_found_by_id(tmp_path):
    shadow = _git_doc()
    shadow["id"], shadow["name"] = "baddad5487f9c288", "lane-a-shadow"
    rows = _eval(tmp_path, [_live(shadow)])
    assert rows[0]["status"] == D.OK and rows[0]["git_file"] == "generated/pending/lane-a-shadow.json"


def test_a_node_edit_connection_edit_or_settings_edit_is_drift(tmp_path):
    live = _live(_git_doc())
    live["nodes"][2]["parameters"]["url"] = "https://exfil.example.invalid/collect"
    live["connections"]["POST relay /run"] = {"main": [[{"node": "Schedule", "type": "main", "index": 0}]]}
    live["settings"]["saveManualExecutions"] = True
    rows = _eval(tmp_path, [live])
    assert rows[0]["status"] == D.DRIFT
    assert rows[0]["diffs"] == ["settings", "connections", "node:POST relay /run:parameters"]


def test_added_and_removed_nodes_are_named(tmp_path):
    live = _live(_git_doc())
    extra = copy.deepcopy(live["nodes"][2])
    extra["name"], extra["type"] = "Agent", "@n8n/n8n-nodes-langchain.agent"
    live["nodes"] = [live["nodes"][0], live["nodes"][2], extra]
    diffs = _eval(tmp_path, [live])[0]["diffs"]
    assert "node:Agent:missing_in_git" in diffs and "node:Relay constants:missing_in_live" in diffs


def test_unknown_id_is_missing_in_git_and_inactive_is_skipped_unless_asked(tmp_path):
    ui_built = _live(_git_doc())
    ui_built["id"], ui_built["name"] = "UiBuilt000000001", "hand-made"
    inactive = _live(_git_doc())
    inactive["id"], inactive["active"] = "Inactive00000001", False
    rows = _eval(tmp_path, [ui_built, inactive])
    assert [(r["id"], r["status"]) for r in rows] == [("UiBuilt000000001", D.MISSING_IN_GIT)]
    rows = _eval(tmp_path, [ui_built, inactive], include_inactive=True)
    assert {r["id"] for r in rows} == {"UiBuilt000000001", "Inactive00000001"}


def test_an_unsubstituted_placeholder_matches_git_but_is_flagged(tmp_path):
    rows = _eval(tmp_path, [_live(_git_doc(), host="RELAY_HOST")])
    assert rows[0]["status"] == D.OK and rows[0]["placeholder_unsubstituted"] is True


def test_receipt_shape_counts_and_wired_fanin_findings(tmp_path):
    bad = _live(_git_doc())
    bad["nodes"][0]["parameters"]["rule"]["interval"][0]["expression"] = "* * * * *"
    rows = _eval(tmp_path, [bad])
    rec = D.build_receipt(rows, source="fixture")
    assert rec["schema"] == "N8nWorkflowDriftReceipt@v1" and rec["verdict"] == "DRIFT"
    assert rec["counts"] == {"OK": 0, "DRIFT": 1, "MISSING_IN_GIT": 0}
    assert rec["fanin_wired"] is True
    assert rec["fanin_findings"][0]["severity"] == "P2"
    assert rec["fanin_findings"][0]["source"] == "n8n_workflow_drift"
    assert rec["fanin_findings"][0]["artifact_rel"] == "data/runtime/n8n_workflow_drift_last.json"


def _main(tmp_path: Path, workflows: list[dict], *extra: str) -> int:
    gen = _gen_dir(tmp_path)
    wf = tmp_path / "workflows.json"
    wf.write_text(json.dumps(workflows), encoding="utf-8")
    return D.main(
        ["--workflows-json", str(wf), "--generated-dir", str(gen), "--index", str(gen / "INDEX.json"), *extra]
    )


def test_dry_run_writes_nothing_and_write_writes_the_receipt_under_the_state_root(tmp_path, monkeypatch, capsys):
    state = tmp_path / "state"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    assert _main(tmp_path, [_live(_git_doc())], "--dry-run") == 0
    assert not (state / D.RECEIPT_REL).exists()
    assert "OK=1 DRIFT=0 MISSING_IN_GIT=0" in capsys.readouterr().out
    assert _main(tmp_path, [_live(_git_doc())], "--write") == 0
    rec = json.loads((state / D.RECEIPT_REL).read_text(encoding="utf-8"))
    assert rec["verdict"] == "CLEAN" and rec["active_count"] == 1 and rec["source"] == "file:workflows.json"


def test_fail_on_drift_exit_codes(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    unknown = _live(_git_doc())
    unknown["id"] = "Unknown000000001"
    assert _main(tmp_path, [unknown], "--fail-on-drift") == 1
    assert _main(tmp_path, [unknown]) == 0  # report mode
    assert D.main(["--workflows-json", str(tmp_path / "absent.json")]) == 2


def test_every_committed_generated_workflow_normalises_equal_to_itself_after_import_substitution():
    idx = INV.load_generated_index()
    placeholder = idx["relay_url_placeholder"]
    git = INV.git_workflows()
    assert git
    live = [_live(doc) for _, doc in git.values()]
    rows = D.evaluate(live, git=git, placeholder=placeholder)
    assert {r["status"] for r in rows} == {D.OK}


def test_the_proposed_lane_is_declared_never_scheduled_and_allowlisted_dry_run_first():
    reg = {
        r["lane_id"]: r for r in json.loads((ROOT / "config/lane_registry.json").read_text(encoding="utf-8"))["lanes"]
    }
    row = reg["n8n-workflow-drift-check"]
    # registry-ops-crons 2026-10-09: scheduled on host cron (:07), PAUSED until the line is installed, then
    # ACTIVE; the generated n8n workflows below stay inactive (activating them too would double-schedule).
    assert row["state"] in {"PAUSED", "ACTIVE"} and row["scheduler"]["kind"] == "cron"
    assert row["scheduler"]["match"] == "scripts/check_n8n_workflow_drift.py --write"
    assert row["output_signal"]["path"] == "data/runtime/n8n_workflow_drift_last.json"
    allow = {
        e["lane_id"]: e
        for e in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text(encoding="utf-8"))["lanes"]
    }
    entry = allow["n8n-workflow-drift-check"]
    assert entry["command"] == ["$PY", "scripts/check_n8n_workflow_drift.py"]
    assert entry["dry_run_arg"] == ["--dry-run"] and entry["live_arg"] == ["--write"]
    assert entry["output_signal"] == row["output_signal"]["path"]
    # generated (N7 ops lanes, 2026-10-09) but inactive: importable only under a grant naming its id
    lanes = {lane["lane_id"]: lane for lane in INV.load_generated_index()["lanes"]}
    assert lanes["n8n-workflow-drift-check"]["tranche"] == "N7"
    assert lanes["n8n-workflow-drift-check"]["shadow_workflow_id"]
