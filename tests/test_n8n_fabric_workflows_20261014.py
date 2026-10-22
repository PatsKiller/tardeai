"""n8n fabric Phase 1 (2026-10-14): `build-fabric` — Run Lane sub-workflow, fabric error workflow, probe, manifest.

Static: committed files equal a fresh render (--check); the six generic workflows are byte-unchanged; every fabric
workflow uses only FABRIC_ALLOWED_NODE_TYPES (the §23.23 relaxation adds exactly Execute Workflow + Trigger,
Switch and Merge to what the generic set already allowed, plus the Manual Trigger the Run Lane probe starts from so
`n8n execute --id` can run it, 2026-10-15), no messaging / AI / community node, an errorWorkflow on
every workflow, successes saved, inactive; the manifest's graph and policy hashes verify, and the trusted-deployer
verify accepts a re-export but refuses a tampered graph. Behaviour: the generated Code nodes run under node.js with
stubbed n8n globals (skipped when node is absent). Imports nothing into n8n."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import n8n_run_relay as R  # noqa: E402
from scripts import n8n_workflow_templates as T  # noqa: E402
from scripts.lib import n8n_fabric_store as F  # noqa: E402

FABRIC_DIR = ROOT / "docs" / "implementation" / "n8n-maturity" / "workflows" / "fabric"
IDS = (T.RUN_LANE_ID, T.FABRIC_ERROR_ID, T.FABRIC_PROBE_ID, T.FABRIC_ERROR_PROBE_ID)


def _wf(wid: str) -> dict:
    return json.loads((FABRIC_DIR / f"{wid}.json").read_text(encoding="utf-8"))


def _index() -> dict:
    return json.loads((FABRIC_DIR / "INDEX.json").read_text(encoding="utf-8"))


def _node(wf: dict, name: str) -> dict:
    return next(n for n in wf["nodes"] if n["name"] == name)


# ── determinism and isolation from the live generic set ─────────────────────────────────────────────────────────


#: Process workflows (2026-10-15, config/n8n_fabric_processes.json; tests/test_n8n_fabric_hermes_learning_20261015.py).
PROCESS_IDS = ("tradeai-fabric-hermes-learning",)
#: 2026-10-21 Release Train v2 Phase 4: coordination workflows rendered by FABRIC_BUILDERS after the four primitives.
COORD_IDS = (T.RELEASE_TRAIN_ID,)


def test_committed_fabric_files_equal_a_fresh_render():
    assert T.main(["build-fabric", "--check"]) == 0
    assert sorted(p.name for p in FABRIC_DIR.iterdir()) == sorted(
        [f"{i}.json" for i in IDS + COORD_IDS + PROCESS_IDS] + ["INDEX.json"]
    )


def test_the_six_generic_workflows_are_byte_unchanged():
    assert T.main(["build-generic", "--check"]) == 0
    assert not set(IDS) & {
        row["id"] for row in json.loads((T.GENERIC_DEFAULT_OUT / "INDEX.json").read_text())["workflows"]
    }


# ── node allowlist ──────────────────────────────────────────────────────────────────────────────────────────────


def test_relaxation_is_exactly_the_section_23_23_list_for_this_pr():
    assert T.FABRIC_RELAXED_NODE_TYPES == {
        "n8n-nodes-base.executeWorkflow",
        "n8n-nodes-base.executeWorkflowTrigger",
        "n8n-nodes-base.wait",
        "n8n-nodes-base.switch",
        "n8n-nodes-base.if",
        "n8n-nodes-base.merge",
        "n8n-nodes-base.errorTrigger",
        "n8n-nodes-base.manualTrigger",
    }
    assert T.FABRIC_ALLOWED_NODE_TYPES - T.GENERIC_ALLOWED_NODE_TYPES == {
        "n8n-nodes-base.executeWorkflow",
        "n8n-nodes-base.executeWorkflowTrigger",
        "n8n-nodes-base.switch",
        "n8n-nodes-base.merge",
        "n8n-nodes-base.manualTrigger",
    }
    # The generic (live) set does not gain it: the relaxation is fabric-only.
    assert "n8n-nodes-base.manualTrigger" not in T.GENERIC_ALLOWED_NODE_TYPES
    assert not T.FABRIC_ALLOWED_NODE_TYPES & T.FABRIC_FORBIDDEN_NODE_TYPES
    assert all(t.startswith("n8n-nodes-base.") for t in T.FABRIC_ALLOWED_NODE_TYPES)
    for msg in ("telegram", "slack", "discord", "emailSend", "gmail", "microsoftTeams", "form", "formTrigger"):
        assert f"n8n-nodes-base.{msg}" in T.FABRIC_FORBIDDEN_NODE_TYPES


@pytest.mark.parametrize("wid", IDS)
def test_every_fabric_workflow_uses_only_allowed_nodes_and_has_an_error_workflow(wid):
    wf = _wf(wid)
    types = {n["type"] for n in wf["nodes"]}
    assert types <= T.FABRIC_ALLOWED_NODE_TYPES, types - T.FABRIC_ALLOWED_NODE_TYPES
    assert not types & T.FABRIC_FORBIDDEN_NODE_TYPES
    assert wf["active"] is False
    s = wf["settings"]
    assert s["errorWorkflow"] == T.FABRIC_ERROR_ID
    assert s["saveDataSuccessExecution"] == "all" and s["saveDataErrorExecution"] == "all"
    assert s["saveManualExecutions"] is False and isinstance(s["executionTimeout"], int)
    assert T.validate_fabric_workflow(wf, set(IDS)) == []
    for n in wf["nodes"]:
        for ctype, cred in (n.get("credentials") or {}).items():
            assert ctype == "httpHeaderAuth" and cred["name"] == T.CREDENTIAL_NAME
        if n["type"] == "n8n-nodes-base.code":
            js = n["parameters"]["jsCode"]
            assert "$env" not in js and "require(" not in js and "fetch(" not in js and "this.helpers" not in js


def test_the_set_uses_every_new_primitive_except_merge():
    used = set().union(*({n["type"] for n in _wf(wid)["nodes"]} for wid in IDS))
    assert {
        "n8n-nodes-base.executeWorkflow",
        "n8n-nodes-base.executeWorkflowTrigger",
        "n8n-nodes-base.switch",
        "n8n-nodes-base.wait",
        "n8n-nodes-base.if",
        "n8n-nodes-base.errorTrigger",
    } <= used


@pytest.mark.parametrize(
    "mutate,problem",
    [
        (
            lambda wf: wf["nodes"].append({"name": "tg", "type": "n8n-nodes-base.telegram"}),
            "node_forbidden:n8n-nodes-base.telegram",
        ),
        (
            lambda wf: wf["nodes"].append({"name": "ai", "type": "@n8n/n8n-nodes-langchain.agent"}),
            "node_package_refused:@n8n/n8n-nodes-langchain.agent",
        ),
        (
            lambda wf: wf["nodes"].append({"name": "c", "type": "n8n-nodes-community.thing"}),
            "node_package_refused:n8n-nodes-community.thing",
        ),
        (
            lambda wf: wf["nodes"].append({"name": "x", "type": "n8n-nodes-base.aggregate"}),
            "node_not_allowed:n8n-nodes-base.aggregate",
        ),
        (lambda wf: wf["settings"].pop("errorWorkflow"), "error_workflow_missing"),
        (lambda wf: wf["settings"].update(errorWorkflow="elsewhere"), "error_workflow_unknown:elsewhere"),
        (lambda wf: wf["settings"].update(saveDataSuccessExecution="none"), "setting:saveDataSuccessExecution"),
        (lambda wf: wf.update(active=True), "active_not_false"),
        (lambda wf: wf["nodes"][0].update(credentials={"telegramApi": {"name": "bot"}}), "credential_refused"),
    ],
)
def test_validator_refuses(mutate, problem):
    wf = copy.deepcopy(_wf(T.RUN_LANE_ID))
    mutate(wf)
    wf["meta"]["graph_sha256"] = T.graph_hash(wf)
    problems = T.validate_fabric_workflow(wf, set(IDS))
    assert any(p.startswith(problem) for p in problems), problems


# ── manifest: graph hash + policy hash; trusted-deployer verify ─────────────────────────────────────────────────


def test_manifest_hashes_match_the_files():
    idx = _index()
    assert idx["schema"] == T.FABRIC_SCHEMA and idx["policy_sha256"] == T.policy_hash()
    assert idx["policy"]["allowed_node_types"] == sorted(T.FABRIC_ALLOWED_NODE_TYPES)
    assert (
        idx["policy"]["intent_routes_sha256"]
        == hashlib.sha256((ROOT / "config" / "n8n_comms_intent_routes.json").read_bytes()).hexdigest()
    )
    assert [r["id"] for r in idx["workflows"]] == list(IDS + COORD_IDS + PROCESS_IDS)
    for row in idx["workflows"]:
        text = (FABRIC_DIR / row["file"]).read_bytes()
        wf = json.loads(text)
        assert row["sha256"] == hashlib.sha256(text).hexdigest()
        assert row["graph_sha256"] == wf["meta"]["graph_sha256"] == T.graph_hash(wf)
        assert wf["meta"]["policy_sha256"] == idx["policy_sha256"]
        assert row["error_workflow"] == T.FABRIC_ERROR_ID and row["active"] is False


def _export_like_n8n(wf: dict) -> dict:
    """What an n8n export adds or changes without changing behaviour."""
    out = copy.deepcopy(wf)
    out["active"] = True
    out["versionId"] = "1b2c3d"
    out.pop("meta", None)
    for i, n in enumerate(out["nodes"]):
        n["position"] = [i * 7, i * 11]
        n["webhookId"] = f"wh-{i}"
        n["id"] = f"n8n-assigned-{i}"
    out["nodes"].reverse()
    return out


def test_verify_accepts_a_reexport_of_the_same_graph(tmp_path):
    p = tmp_path / "export.json"
    p.write_text(json.dumps([_export_like_n8n(_wf(wid)) for wid in IDS]))
    res = T.verify_fabric([p], FABRIC_DIR / "INDEX.json")
    assert res["ok"] is True, res
    assert all(w["problems"] == [] for w in res["workflows"])


@pytest.mark.parametrize(
    "mutate,problem",
    [
        (
            lambda wf: _node(wf, T.RL_CLASSIFY)["parameters"].update(jsCode="return $input.all();"),
            "graph_hash_mismatch",
        ),
        (lambda wf: wf["settings"].update(errorWorkflow=T.RUN_LANE_ID), "graph_hash_mismatch"),
        (lambda wf: wf["connections"].pop(T.RL_NEXT), "graph_hash_mismatch"),
        (lambda wf: _node(wf, T.RL_POST).update(disabled=True), "graph_hash_mismatch"),
        (lambda wf: wf.update(id="tradeai-unknown"), "not_in_manifest"),
    ],
)
def test_verify_refuses_a_tampered_graph(tmp_path, mutate, problem):
    wf = _export_like_n8n(_wf(T.RUN_LANE_ID))
    mutate(wf)
    p = tmp_path / "export.json"
    p.write_text(json.dumps(wf))
    res = T.verify_fabric([p], FABRIC_DIR / "INDEX.json")
    assert res["ok"] is False and problem in res["workflows"][0]["problems"]


def test_verify_refuses_a_manifest_whose_policy_hash_is_not_the_code(tmp_path):
    idx = _index()
    idx["policy_sha256"] = "0" * 64
    m = tmp_path / "INDEX.json"
    m.write_text(json.dumps(idx))
    p = tmp_path / "wf.json"
    p.write_text(json.dumps(_wf(T.FABRIC_ERROR_ID)))
    res = T.verify_fabric([p], m)
    assert res["ok"] is False and res["policy_mismatch"] is True


def test_verify_cli_exit_codes(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_wf(T.FABRIC_ERROR_ID)))
    assert T.main(["build-fabric", "--verify", str(good)]) == 0
    bad_wf = _wf(T.FABRIC_ERROR_ID)
    bad_wf["settings"]["errorWorkflow"] = None
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(bad_wf))
    assert T.main(["build-fabric", "--verify", str(bad)]) == 1


# ── relay contract and topology ─────────────────────────────────────────────────────────────────────────────────


def _http_paths(wf: dict) -> list[tuple[str, str]]:
    out = []
    for n in wf["nodes"]:
        if n["type"] == "n8n-nodes-base.httpRequest":
            url = n["parameters"]["url"]
            path = url.split("}}", 1)[1].split("?", 1)[0]
            out.append((n["parameters"]["method"], path))
    return out


@pytest.mark.parametrize("wid", IDS)
def test_every_http_node_calls_a_served_relay_route_at_the_bridge_ip(wid):
    wf = _wf(wid)
    calls = _http_paths(wf)
    assert sorted(f"{m} {p}" for m, p in calls) == sorted(T.FABRIC_RELAY_CALLS[wid])
    for m, p in calls:
        assert (m, p) in R.ROUTES
    relays = [n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.set" and n["name"] == "Relay"]
    for n in relays:
        assert n["parameters"]["assignments"]["assignments"][0]["value"] == T.GENERIC_RELAY_URL


def test_run_lane_topology():
    wf = _wf(T.RUN_LANE_ID)
    c = wf["connections"]
    targets = lambda src: [[d["node"] for d in out] for out in c[src]["main"]]  # noqa: E731
    assert targets(T.RL_INPUT) == [[T.RL_SET]]
    assert targets(T.RL_REQUESTED) == [[T.RL_WAIT], [T.RL_SWITCH]]
    assert targets(T.RL_PENDING) == [[T.RL_WAIT], [T.RL_SWITCH]]  # bounded poll loop
    assert targets(T.RL_SWITCH) == [[T.RL_RESULT], [T.RL_BUDGET], [T.RL_RESULT], [T.RL_RESULT], [T.RL_RESULT]]
    assert targets(T.RL_BUDGET) == [[T.RL_BACKOFF], [T.RL_RESULT]]
    assert targets(T.RL_NEXT) == [[T.RL_PREP]]  # the retry loop is owned here
    sw = _node(wf, T.RL_SWITCH)
    assert [r["outputKey"] for r in sw["parameters"]["rules"]["values"]] == list(T.RUN_LANE_TERMINAL)
    assert sw["parameters"]["options"]["fallbackOutput"] == "extra"
    inputs = [v["name"] for v in _node(wf, T.RL_INPUT)["parameters"]["workflowInputs"]["values"]]
    assert inputs == ["lane_id", "mode", "idempotency_key", "max_attempts", "outcome_timeout_s", "process_id"]
    worst = T.RUN_LANE_MAX_ATTEMPTS * (T.RUN_LANE_OUTCOME_TIMEOUT_MAX_S + T.RUN_LANE_RETRY_BACKOFF_MAX_S)
    assert worst < wf["settings"]["executionTimeout"] <= 3600  # n8n EXECUTIONS_TIMEOUT_MAX default
    body = _node(wf, T.RL_POST)["parameters"]["jsonBody"]
    assert set(re.findall(r"(\w+):", body.split("JSON.stringify(", 1)[1])) == set(T.RUN_BODY_KEYS)


def test_error_workflow_posts_exactly_the_relay_intent_keys_on_a_routed_kind():
    wf = _wf(T.FABRIC_ERROR_ID)
    body = _node(wf, T.FE_POST)["parameters"]["jsonBody"]
    assert set(re.findall(r"(\w+): \$json", body)) == set(R.INTENT_BODY_KEYS) == set(F.INTENT_FIELDS)
    shape = _node(wf, T.FE_SHAPE)["parameters"]["jsCode"]
    routes = F.load_intent_routes()["routes"]
    assert ("fabric", "workflow_error") in routes and "domain: 'fabric', kind: 'workflow_error'" in shape
    assert wf["settings"]["errorWorkflow"] == wf["id"]  # names itself; n8n skips self-recursion
    assert not any("telegram" in n["type"].lower() for n in wf["nodes"])
    creds = {c for n in wf["nodes"] for c in (n.get("credentials") or {})}
    assert creds == {"httpHeaderAuth"}  # the relay bearer only: no bot token, no messaging credential


def test_probe_calls_run_lane_by_id_in_dry_run_on_an_allowlisted_lane():
    wf = _wf(T.FABRIC_PROBE_ID)
    call = _node(wf, T.FP_CALL)["parameters"]
    assert call["workflowId"]["value"] == T.RUN_LANE_ID and call["options"]["waitForSubWorkflow"] is True
    vals = {a["name"]: a["value"] for a in _node(wf, T.FP_INPUT)["parameters"]["assignments"]["assignments"]}
    assert vals["mode"] == "dry_run" and vals["lane_id"] == T.FABRIC_PROBE_LANE and vals["max_attempts"] == 1
    allow = {x["lane_id"]: x for x in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
    assert T.FABRIC_PROBE_LANE in allow and allow[T.FABRIC_PROBE_LANE]["dry_run_arg"]


def test_manual_trigger_is_the_run_lane_probe_start_node_and_nowhere_else():
    # `n8n execute --id` needs a Manual Trigger start node (operator live run 2026-10-15: "Missing node to start
    # execution"). The probe has no schedule at all, so it can never fire on its own.
    wf = _wf(T.FABRIC_PROBE_ID)
    types = [n["type"] for n in wf["nodes"]]
    assert types.count("n8n-nodes-base.manualTrigger") == 1
    assert "n8n-nodes-base.scheduleTrigger" not in types
    manual = _node(wf, T.FP_MANUAL)
    assert manual["type"] == "n8n-nodes-base.manualTrigger" and manual["parameters"] == {}
    assert [c["node"] for c in wf["connections"][T.FP_MANUAL]["main"][0]] == [T.FP_INPUT]
    for wid in IDS:
        if wid != T.FABRIC_PROBE_ID:
            assert "n8n-nodes-base.manualTrigger" not in {n["type"] for n in _wf(wid)["nodes"]}, wid
    rows = {r["id"]: r for r in _index()["workflows"]}
    # 2026-10-15: a process workflow also carries one Manual Trigger, for the operator's CLI proof run.
    assert [w for w, r in rows.items() if "n8n-nodes-base.manualTrigger" in r["node_types"]] == [
        T.FABRIC_PROBE_ID,
        *COORD_IDS,  # 2026-10-21: the release-train Manual Trigger is the forced shadow tick (contract §10)
        *PROCESS_IDS,
    ]


#: Graph hashes in INDEX.json. The three non-probe graphs are pinned to what the operator imported on 2026-10-15
#: (they must not move, or the imported copies stop verifying); the probe pin is the Manual Trigger graph.
GRAPH_PINS = {
    T.RUN_LANE_ID: "b72c74dd202bde396faa3eb705d893a330d0560023c92ac9d2965e051b9f0b55",
    T.FABRIC_ERROR_ID: "21c7ddd097b1eca3859f3ba6c407817d6ba6eed73a6a37a9f5d1858cfbd578da",
    T.FABRIC_PROBE_ID: "4dc071b31eaaa3788522ffae581a95be66918f3b6a4d24fff68931de484b9510",
    T.FABRIC_ERROR_PROBE_ID: "f92070400e85d42fc047dd6f0fade44d81174fe654d55f8bbb7e4d1bbdab116e",
    # 2026-10-15: the first process workflow (adding it moves none of the four pins above, nor the policy hash).
    # Re-pinned by the hermes-learning unblock (three steps runnable, default_max_attempts 1, tune wait 600 s);
    # never imported yet, so no imported copy stops verifying.
    # hermes-learning cutover PR-2 (2026-10-15): spec MODE live; still never imported, so nothing stops verifying.
    "tradeai-fabric-hermes-learning": "f1d0984c64b06191020008af6d09f8b26a9c5a0ba5789f8e97ddb0e45215ebe4",
    # 2026-10-21 Release Train v2 Phase 4 (docs/ops/RELEASE_TRAIN_N8N_CONTRACT.md); never imported. Adding it moves
    # none of the pins above. Re-pinned 2026-10-21 (operator "rtw yes"): the gate node mints the host-validated
    # rtw:<slot>:<window date>:<shadow|live> key for live runs; still never imported, so nothing stops verifying.
    T.RELEASE_TRAIN_ID: "4c3a912e283c16fa7b2631337b34fa59029f05512cb08997668f5ea4636324ca",
}


def test_index_graph_hash_pins():
    assert {r["id"]: r["graph_sha256"] for r in _index()["workflows"]} == GRAPH_PINS


def test_error_probe_fails_on_its_own_schedule_into_the_fabric_error_workflow():
    wf = _wf(T.FABRIC_ERROR_PROBE_ID)
    assert wf["active"] is False and wf["settings"]["errorWorkflow"] == T.FABRIC_ERROR_ID
    assert {n["type"] for n in wf["nodes"]} == {"n8n-nodes-base.scheduleTrigger", "n8n-nodes-base.code"}
    assert "throw new Error('fabric-error-probe:" in _node(wf, T.FEP_FAIL)["parameters"]["jsCode"]
    assert T.FABRIC_RELAY_CALLS[T.FABRIC_ERROR_PROBE_ID] == []


# ── behaviour of the generated Code nodes (node.js; skipped when absent) ────────────────────────────────────────

NODE = shutil.which("node")
HARNESS = r"""
const fs = require('fs');
const spec = JSON.parse(fs.readFileSync(0, 'utf8'));
const custom = {};
globalThis.$input = { first: () => ({ json: spec.input }), all: () => [{ json: spec.input }] };
globalThis.$ = (name) => ({ last: () => ({ json: spec.nodes[name] }), first: () => ({ json: spec.nodes[name] }) });
globalThis.$execution = { id: '77', customData: { set: (k, v) => { custom[k] = v; } } };
globalThis.$workflow = { id: 'wf-1' };
(async () => {
  try {
    const fn = new Function('return (async () => {' + spec.code + '\n})();');
    const out = await fn();
    process.stdout.write(JSON.stringify({ ok: true, out: out.map((i) => i.json), custom }));
  } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, error: String(e.message) }));
  }
})();
"""


def _js(wid: str, node: str, input_json: dict, nodes: dict | None = None) -> dict:
    code = _node(_wf(wid), node)["parameters"]["jsCode"]
    proc = subprocess.run(
        [NODE, "-e", HARNESS],
        input=json.dumps({"code": code, "input": input_json, "nodes": nodes or {}}),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


needs_node = pytest.mark.skipif(NODE is None, reason="node.js not on PATH")
STATE = {
    "lane_id": "lane-a",
    "mode": "dry_run",
    "base_key": "d:lane-a:dry_run:20261014T0730",
    "attempt": 1,
    "key_attempt": 1,
    "max_attempts": 3,
    "outcome_timeout_s": 900,
    "process_id": "",
    "history": [],
}


@needs_node
def test_js_init_validates_and_prepare_builds_attempt_keys():
    ok = _js(
        T.RUN_LANE_ID,
        T.RL_INIT,
        {"lane_id": "lane-a", "mode": "live", "idempotency_key": "d:lane-a:live:20261014T0730:a2", "max_attempts": 9},
    )
    s = ok["out"][0]
    assert ok["ok"] and s["base_key"] == "d:lane-a:live:20261014T0730" and s["key_attempt"] == 2
    assert s["max_attempts"] == T.RUN_LANE_MAX_ATTEMPTS and s["outcome_timeout_s"] == 900
    assert ok["custom"] == {"lane_id": "lane-a"}
    bad = _js(T.RUN_LANE_ID, T.RL_INIT, {"lane_id": "Lane A", "mode": "live", "idempotency_key": "x" * 20})
    assert not bad["ok"] and "bad lane_id" in bad["error"]
    prep = _js(T.RUN_LANE_ID, T.RL_PREP, dict(STATE, key_attempt=3))["out"][0]
    assert prep["idempotency_key"] == prep["run_id"] == STATE["base_key"] + ":a3" and prep["phase"] == "request"


@needs_node
@pytest.mark.parametrize(
    "attempt,response,want",
    [
        (1, {"statusCode": 200, "body": {"state": "REQUESTED", "run_id": "rid-1"}}, ("poll", None, None)),
        (1, {"statusCode": 200, "body": {"state": "RUN_DONE", "duplicate": True}}, ("poll", None, None)),
        (
            1,
            {"statusCode": 403, "body": {"state": "REFUSED", "reason": "run_slot_not_due"}},
            ("done", "refused_policy", False),
        ),
        (2, {"statusCode": 403, "body": {"state": "REFUSED", "reason": "run_slot_not_due"}}, ("done", "failed", False)),
        (1, {"statusCode": 502, "body": {"reason": "relay_gateway_unreachable"}}, ("done", "failed", True)),
        (1, {"error": {"message": "ECONNREFUSED"}}, ("done", "failed", True)),
    ],
)
def test_js_classify_request_makes_refusals_data(attempt, response, want):
    prep = dict(STATE, attempt=attempt, idempotency_key="k" * 20, run_id="k" * 20, phase="request")
    res = _js(T.RUN_LANE_ID, T.RL_CLASSIFY, response, {T.RL_PREP: prep})
    assert res["ok"], res
    out = res["out"][0]
    assert out["phase"] == want[0]
    if want[1] is not None:
        assert out["status"] == want[1] and out["retryable"] is want[2]
    if attempt == 2 and want[1] == "failed":
        assert out["reason"].startswith("retry_refused:")


@needs_node
def test_js_classify_throws_on_relay_auth_failure():
    res = _js(
        T.RUN_LANE_ID,
        T.RL_CLASSIFY,
        {"statusCode": 401, "body": {"reason": "relay_bad_bearer"}},
        {T.RL_PREP: dict(STATE, run_id="k" * 20)},
    )
    assert not res["ok"] and "HTTP 401" in res["error"]


@needs_node
def test_js_evaluate_outcome_terminal_pending_backoff_and_timeout():
    waiting = dict(STATE, run_id="rid-1", phase="poll", polls=0, waited_s=0, wait_s=5)
    done = _js(
        T.RUN_LANE_ID,
        T.RL_EVAL,
        {
            "statusCode": 200,
            "body": {
                "schema": "RunOutcome@v1",
                "state": "OK",
                "status": "success",
                "exit_code": 0,
                "receipt_path": "/s/r.json",
                "effect_key": None,
            },
        },
        {T.RL_WAIT: waiting},
    )["out"][0]
    assert done["phase"] == "done" and done["status"] == "success" and done["receipt_path"] == "/s/r.json"
    pend = _js(
        T.RUN_LANE_ID,
        T.RL_EVAL,
        {"statusCode": 200, "body": {"schema": "RunOutcome@v1", "state": "OK", "status": "pending"}},
        {T.RL_WAIT: waiting},
    )["out"][0]
    assert pend["phase"] == "poll" and pend["wait_s"] == 10 and pend["waited_s"] == 5
    capped = _js(T.RUN_LANE_ID, T.RL_EVAL, {"statusCode": 502}, {T.RL_WAIT: dict(waiting, wait_s=60, waited_s=100)})
    assert capped["out"][0]["wait_s"] == T.RUN_LANE_POLL_MAX_S
    lost = _js(
        T.RUN_LANE_ID,
        T.RL_EVAL,
        {"statusCode": 200, "body": {"schema": "RunOutcome@v1", "state": "OK", "status": "pending"}},
        {T.RL_WAIT: dict(waiting, waited_s=880, wait_s=20)},
    )["out"][0]
    assert lost["phase"] == "done" and lost["status"] == "failed" and lost["reason"] == "outcome_timeout"
    assert lost["retryable"] is False
    refused = _js(
        T.RUN_LANE_ID,
        T.RL_EVAL,
        {
            "statusCode": 200,
            "body": {"schema": "RunOutcome@v1", "state": "OK", "status": "refused_policy", "reason": "effect:x"},
        },
        {T.RL_WAIT: waiting},
    )["out"][0]
    assert refused["status"] == "refused_policy" and refused["retryable"] is False


@needs_node
def test_js_next_attempt_and_result():
    failed = dict(STATE, run_id="rid-1", status="failed", reason="exit_2", requested=True, retryable=True)
    nxt = _js(T.RUN_LANE_ID, T.RL_NEXT, failed)["out"][0]
    assert nxt["attempt"] == 2 and nxt["key_attempt"] == 2 and nxt["history"][0]["status"] == "failed"
    unreq = _js(T.RUN_LANE_ID, T.RL_NEXT, dict(failed, requested=False))["out"][0]
    assert unreq["attempt"] == 2 and unreq["key_attempt"] == 1  # transport failure: same key again
    res = _js(T.RUN_LANE_ID, T.RL_RESULT, dict(failed, attempt=3))["out"][0]
    assert res["schema"] == "RunLaneResult@v1" and res["dead_letter"] is True and res["attempts"] == 3
    ok = _js(T.RUN_LANE_ID, T.RL_RESULT, dict(STATE, run_id="rid", status="skipped_lock", reason="flock_held"))
    assert ok["out"][0]["status"] == "skipped_lock" and ok["out"][0]["dead_letter"] is False


@needs_node
def test_js_error_workflow_shapes_a_bounded_intent_and_asserts_acceptance():
    payload = {
        "execution": {
            "id": "991",
            "lastNodeExecuted": "Classify request",
            "mode": "trigger",
            "error": {"message": "run-lane: relay /run HTTP 401 " + "x" * 400},
        },
        "workflow": {"id": "tradeai-fabric-run-lane", "name": "tradeai-fabric-run-lane"},
    }
    shaped = _js(T.FABRIC_ERROR_ID, T.FE_SHAPE, payload)["out"][0]
    assert set(shaped) == set(F.INTENT_FIELDS) and shaped["domain"] == "fabric" and shaped["kind"] == "workflow_error"
    assert len(shaped["summary"]) == 300 and shaped["execution_id"] == "991" and shaped["node"] == "Classify request"
    F.validate_intent(shaped)  # the host accepts what the error workflow sends
    trig = _js(
        T.FABRIC_ERROR_ID, T.FE_SHAPE, {"trigger": {"error": {"message": "cron parse"}}, "workflow": {"id": "w1"}}
    )["out"][0]
    assert trig["execution_id"] == "none" and trig["subject"].endswith("failed at trigger")
    ok = _js(T.FABRIC_ERROR_ID, T.FE_ASSERT, {"statusCode": 200, "body": {"state": "ACCEPTED", "intent_id": "ci-1"}})
    assert ok["ok"] and ok["out"][0]["intent_id"] == "ci-1"
    bad = _js(T.FABRIC_ERROR_ID, T.FE_ASSERT, {"statusCode": 403, "body": {"reason": "intent_rate_limited"}})
    assert not bad["ok"] and "intent_rate_limited" in bad["error"]
