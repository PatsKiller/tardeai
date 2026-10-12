"""Source declarations never turn a GET-only observer into a host run requester."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.lib import lane_registry as L
from scripts.lib import n8n_coordination_gateway as G
from scripts.lib import n8n_momentum_lifecycle as M

ROOT = Path(__file__).resolve().parents[1]
WID = "tradeai-momentum-lifecycle-candidate"


@pytest.fixture
def catalogue(tmp_path):
    directory = tmp_path / "observer"
    directory.mkdir()
    source = ROOT / "docs/implementation/n8n-maturity/workflows"
    workflow = json.loads((source / f"{WID}.json").read_text())
    index = json.loads((source.parent / "observers/INDEX.json").read_text())
    contract = copy.deepcopy(
        next(
            c
            for c in json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]
            if c["id"] == WID
        )
    )
    # This is synthetic declaration data, not a copy of actual operator acceptance.
    contract.update(status="DRAFT", ownership_confirmation="NOT_MEASURED")
    contract["review"] = {"reviewed_by": None, "decision_ref": None}
    return directory, workflow, index, contract


def write_catalogue(fixture, *, rebind=True):
    directory, workflow, index, contract = fixture
    raw = json.dumps(workflow).encode()
    (directory / f"{WID}.json").write_bytes(raw)
    if rebind:
        digest = hashlib.sha256(raw).hexdigest()
        index["workflows"][0]["sha256"] = digest
        contract["workflow_source"]["sha256"] = digest
    (directory / "OBSERVERS.json").write_text(json.dumps(index))
    (directory / "contracts.json").write_text(json.dumps({"contracts": [contract]}))
    return directory / "OBSERVERS.json", directory / "contracts.json", directory


def test_source_declares_observer_without_host_run_or_generic_workflow(catalogue):
    paths = write_catalogue(catalogue)
    assert L.n8n_read_only_workflow_ids(*paths) == {WID: "observer:read-only"}
    assert len(L.n8n_generic_workflow_ids()) == 6
    registry = json.loads((ROOT / "config/lane_registry.json").read_text())
    allow = {e["lane_id"] for e in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]}
    assert WID not in {r["lane_id"] for r in registry["lanes"]}
    assert WID not in allow
    assert L.find_undeclared(registry, {"n8n": [{"expression": WID}]}, n8n_known_ids={WID}) == []
    response = G._run(
        {"lane_id": WID, "mode": "live", "run_id": "fixture"},
        {"caller_id": "fixture"},
        run_store=object(),
        run_allowlist=allow,
        now=0,
        peer=None,
    )
    assert response["reason"] == "run_lane_not_allowlisted"
    assert response["state"] == "REFUSED"


@pytest.mark.parametrize(
    "mutation",
    [
        "write",
        "run",
        "due",
        "external",
        "provider",
        "code_network",
        "code_env",
        "credential",
        "active",
        "id",
        "file_escape",
        "schema",
        "duplicate",
        "contract_binding",
        "code_python",
        "query",
        "contract_schema",
    ],
)
def test_unsafe_or_drifting_catalogue_fails_closed(catalogue, mutation):
    _, workflow, index, contract = catalogue
    http = next(n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.httpRequest")
    code = next(n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.code")
    if mutation == "write":
        http["parameters"]["method"] = "POST"
    elif mutation in {"run", "due"}:
        http["parameters"]["url"] = "={{ $('Relay').first().json.TRADEAI_N8N_RUN_URL }}/" + mutation
    elif mutation == "external":
        http["parameters"]["url"] = "https://fixture.invalid/momentum-lifecycle"
    elif mutation == "provider":
        workflow["nodes"].append({"type": "@n8n/n8n-nodes-langchain.agent", "parameters": {}})
    elif mutation == "code_network":
        code["parameters"]["jsCode"] = "return fetch('https://fixture.invalid');"
    elif mutation == "code_env":
        code["parameters"]["jsCode"] = "return $env.FIXTURE;"
    elif mutation == "credential":
        http["credentials"] = {"httpHeaderAuth": {"name": "fixture-other"}}
    elif mutation == "active":
        workflow["active"] = True
    elif mutation == "id":
        workflow["id"] = "fixture-other"
    elif mutation == "file_escape":
        index["workflows"][0]["file"] = "../fixture.json"
    elif mutation == "schema":
        index["schema"] = "fixture-wrong"
    elif mutation == "duplicate":
        index["workflows"].append(copy.deepcopy(index["workflows"][0]))
    elif mutation == "contract_binding":
        contract["workflow_source"]["file"] = "fixture-other.json"
    elif mutation == "code_python":
        code["parameters"] = {"language": "python", "pythonCode": "pass"}
    elif mutation == "query":
        http["parameters"]["queryParameters"] = {"parameters": [{"name": "fixture", "value": "inert"}]}
    elif mutation == "contract_schema":
        contract["schema"] = "fixture-wrong"
    with pytest.raises(ValueError):
        L.n8n_read_only_workflow_ids(*write_catalogue(catalogue))


def test_source_digest_drift_refuses_before_declaration(catalogue):
    paths = write_catalogue(catalogue)
    (paths[0].parent / f"{WID}.json").write_text("{}")
    with pytest.raises(ValueError, match="digest"):
        L.n8n_read_only_workflow_ids(*paths)


def test_source_symlink_escape_is_refused(catalogue):
    paths = write_catalogue(catalogue)
    workflow = paths[0].parent / f"{WID}.json"
    target = workflow.parent.parent / "owned-fixture.json"
    target.write_bytes(workflow.read_bytes())
    workflow.unlink()
    workflow.symlink_to(target)
    with pytest.raises(ValueError, match="escapes"):
        L.n8n_read_only_workflow_ids(*paths)


def test_reviewed_contract_remains_content_bound(catalogue):
    contract = catalogue[3]
    contract.update(status="REVIEWED", ownership_confirmation="OWNER_ACCEPTED")
    contract["review"] = {"reviewed_by": "TEST_ONLY_OWNER", "decision_ref": "fixture://body-review"}
    paths = write_catalogue(catalogue)
    contract["review"]["contract_body_sha256"] = M.contract_body_digest(contract)
    paths[1].write_text(json.dumps({"contracts": [contract]}))
    assert L.n8n_read_only_workflow_ids(*paths) == {WID: "observer:read-only"}
    contract["purpose"]["text"] += " changed after review"
    paths[1].write_text(json.dumps({"contracts": [contract]}))
    with pytest.raises(ValueError, match="review"):
        L.n8n_read_only_workflow_ids(*paths)
