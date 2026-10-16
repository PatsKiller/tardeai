"""§23.24 framework checker, reference mature workflow and contracts design (2026-10-15).

Hermetic: reads committed repo files only (workflow JSON, configs, docs); synthetic workflows and contexts for the
element rules; node.js (when on PATH) interprets the reference workflow's Code nodes. No n8n, relay, gateway, DB,
ledger or network.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import build_n8n_reference_workflow as REF  # noqa: E402
import check_n8n_workflow_framework as F  # noqa: E402
import n8n_workflow_templates as T  # noqa: E402

REF_FILE = ROOT / REF.REL / f"{REF.WID}.json"


@pytest.fixture(scope="module")
def ctx() -> F.Context:
    return F.build_context(ROOT)


def _synthetic_ctx(**over) -> F.Context:
    base = dict(
        root=ROOT,
        contracts=[],
        allowlist_lanes={"lane-a"},
        effect_lanes={"lane-a"},
        class_caps={"ingest"},
        relay_routes={("POST", "/run"), ("GET", "/run_outcome"), ("POST", "/intent")},
        allowed_node_types=frozenset(T.FABRIC_ALLOWED_NODE_TYPES),
        forbidden_node_types=frozenset(T.FABRIC_FORBIDDEN_NODE_TYPES),
        credential_name=T.CREDENTIAL_NAME,
        run_lane_id=T.RUN_LANE_ID,
        error_workflow_ids=frozenset({T.FABRIC_ERROR_ID, T.INCIDENT_ROUTER_ID}),
    )
    base.update(over)
    return F.Context(**base)


def _ref() -> dict:
    return json.loads(REF_FILE.read_text(encoding="utf-8"))


def _contract() -> dict:
    return json.loads((ROOT / REF.REL / REF.CONTRACT_FILE).read_text(encoding="utf-8"))["contract"]


def _direct_run_wf(error_workflow: str | None = T.FABRIC_ERROR_ID) -> dict:
    settings = {"executionTimeout": 50, "saveDataErrorExecution": "all"}
    if error_workflow:
        settings["errorWorkflow"] = error_workflow
    return {
        "id": "wf-direct",
        "name": "wf-direct",
        "settings": settings,
        "nodes": [
            {"name": "Schedule", "type": "n8n-nodes-base.scheduleTrigger", "parameters": {}},
            {
                "name": "POST relay /run",
                "type": "n8n-nodes-base.httpRequest",
                "credentials": {"httpHeaderAuth": {"id": T.CREDENTIAL_NAME, "name": T.CREDENTIAL_NAME}},
                "retryOnFail": True,
                "parameters": {
                    "method": "POST",
                    "authentication": "genericCredentialType",
                    "genericAuthType": "httpHeaderAuth",
                    "url": "={{ $json.TRADEAI_N8N_RUN_URL }}/run",
                    "jsonBody": '={{ JSON.stringify({ lane_id: "lane-a", mode: "live", workflow_id: String($workflow.id), '
                    "execution_id: String($execution.id) }) }}",
                },
            },
            {
                "name": "Relay",
                "type": "n8n-nodes-base.set",
                "parameters": {
                    "assignments": {"assignments": [{"name": "TRADEAI_N8N_RUN_URL", "value": T.GENERIC_RELAY_URL}]}
                },
            },
        ],
        "connections": {
            "Schedule": {"main": [[{"node": "Relay", "type": "main", "index": 0}]]},
            "Relay": {"main": [[{"node": "POST relay /run", "type": "main", "index": 0}]]},
        },
    }


# ── the reference mature workflow ────────────────────────────────────────────────────────────────────────────────


def test_reference_is_generated_byte_stable_and_inert():
    assert REF.main(["--check"]) == 0
    wf = _ref()
    assert wf["active"] is False
    assert REF.problems(wf) == []  # the fabric generator's own invariants + process invariants
    assert not [n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"]
    allow = {x["lane_id"]: x for x in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]}
    assert allow[REF.LANE]["live_arg"] is None  # an import could only ever dry-run
    assert allow[REF.LANE]["timeout_s"] == REF.LANE_TIMEOUT_S
    assert wf["meta"]["framework"]["schema"] == F.META_SCHEMA


def test_reference_passes_every_checkable_element(ctx):
    r = F.score_workflow(_ref(), ctx, file=str(REF_FILE.relative_to(ROOT)))
    assert r["failing"] == [], r["failing"]
    assert r["score"]["pct"] == 100.0
    assert all(v["status"] in (F.PASS, F.NA) for v in r["elements"].values())
    assert r["elements"]["FW-M6"]["status"] == F.PASS


def test_reference_contract_has_the_expected_output_rule():
    c = _contract()
    eo = c["expected_output"]
    assert eo["schema"] == F.EXPECTED_OUTPUT_SCHEMA and eo["rule"] == "min_produced" and eo["min_produced"] >= 1
    assert "no_runner" in eo["fatal_skip_reasons"]
    assert {"empty_output", "output_unverifiable"} <= {f["check"] for f in c["failed"]}
    assert (ROOT / c["remediation"]["runbook"]).exists()


# ── FW-M6: exit 0 with nothing produced is a FAILURE ────────────────────────────────────────────────────────────


def test_m6_fails_without_expected_output_rule():
    c = _contract()
    del c["expected_output"]
    assert F._check_expected_output(c)["status"] == F.FAIL
    assert F._check_expected_output(None)["status"] == F.FAIL


@pytest.mark.parametrize(
    "patch",
    [
        {"rule": "whatever"},
        {"min_produced": 0},
        {"produced_field": ""},
        {"evidence": []},
        {"schema": "N8nExpectedOutput@v0"},
        {"rule": "per_window", "window_h": None},
    ],
)
def test_m6_fails_on_an_invalid_rule(patch):
    c = _contract()
    c["expected_output"].update(patch)
    assert F._check_expected_output(c)["status"] == F.FAIL


#: 2026-10-15 expected_output PR: 122 of 126 contracts declare a rule. Still failing FW-M6: the digest-bound REVIEWED
#: momentum candidate (adding a rule needs a fresh review) and the five workflows with no health contract on main.
M6_STILL_FAILING = {
    "tradeai-momentum-lifecycle-candidate",
    "finviz-view-contracts-shadow",
    "generate-analyst-daily-digest-shadow",
    "lane-governance-packet-weekly-shadow",
    "tradeai-fabric-run-lane",
    "tradeai-fabric-error",
}


def test_active_fleet_m6_passes_exactly_where_a_contract_declares_the_rule(ctx):
    active = json.loads((ROOT / F.DEFAULT_ACTIVE).read_text())
    rep = F.build_report([(ROOT / w["file"], w) for w in active["workflows"]], ctx, None, source="t")
    assert rep["fleet"]["workflows"] == len(active["workflows"]) == 18
    failing = {r["name"] for r in rep["workflows"] if r["elements"]["FW-M6"]["status"] != F.PASS}
    assert failing == M6_STILL_FAILING
    assert all(r["elements"]["FW-M6"]["status"] == F.FAIL for r in rep["workflows"] if r["name"] in failing)
    assert rep["fleet"]["fully_compliant"] == 0


def test_every_committed_expected_output_rule_passes_m6():
    doc = json.loads((ROOT / "config/n8n_health_contracts.json").read_text())
    declared = [c for c in doc["contracts"] if "expected_output" in c]
    # 122 from the 2026-10-15 expected_output PR + rules that later lanes carry themselves (#1777: 6).
    assert len(declared) >= 122
    undeclared = {c["id"] for c in doc["contracts"]} - {c["id"] for c in declared}
    assert undeclared == {
        "momentum-lifecycle-monitor",
        "tradeai-momentum-lifecycle-candidate",
        "momentum-cache-reconcile",
        "trade-ai-scalp-live",
    }  # digest-bound REVIEWED bodies: a rule needs a fresh content-bound review
    for c in declared:
        assert F._check_expected_output(c)["status"] == F.PASS, c["id"]
        assert "output_produced" in {x["check"] for x in c["healthy"]}, c["id"]
        assert "empty_output" in {x["check"] for x in c["failed"]}, c["id"]


# ── element rules on synthetic workflows ─────────────────────────────────────────────────────────────────────────


def test_direct_post_run_makes_refusals_errors_and_legacy_retry_partial():
    r = F.score_workflow(_direct_run_wf(), _synthetic_ctx())
    assert r["elements"]["FW-A4"]["status"] == F.FAIL
    assert r["elements"]["FW-R1"]["status"] == F.PARTIAL
    assert r["elements"]["FW-S2"]["status"] == F.PASS
    assert r["elements"]["FW-L4"]["status"] == F.PASS


def test_no_error_workflow_and_self_reference_fail():
    r = F.score_workflow(_direct_run_wf(error_workflow=None), _synthetic_ctx())
    assert r["elements"]["FW-M2"]["status"] == F.FAIL and r["elements"]["FW-A1"]["status"] == F.FAIL
    wf = _direct_run_wf(error_workflow=T.FABRIC_ERROR_ID)
    wf["id"] = T.FABRIC_ERROR_ID
    r = F.score_workflow(wf, _synthetic_ctx())
    assert r["elements"]["FW-A1"]["status"] == F.FAIL and "self-referencing" in r["elements"]["FW-A1"]["reason"]


def test_unknown_lane_and_unknown_route_fail_authz():
    wf = _direct_run_wf()
    wf["nodes"][1]["parameters"]["jsonBody"] = wf["nodes"][1]["parameters"]["jsonBody"].replace("lane-a", "lane-x")
    r = F.score_workflow(wf, _synthetic_ctx())
    assert r["elements"]["FW-S2"]["status"] == F.FAIL and "lane-x" in r["elements"]["FW-S2"]["reason"]
    wf = _direct_run_wf()
    wf["nodes"][1]["parameters"]["url"] = "={{ $json.TRADEAI_N8N_RUN_URL }}/sql"
    assert F.score_workflow(wf, _synthetic_ctx())["elements"]["FW-S2"]["status"] == F.FAIL


def test_secrets_credentials_and_node_types():
    wf = _direct_run_wf()
    wf["nodes"].append(
        {
            "name": "tg",
            "type": "n8n-nodes-base.telegram",
            "parameters": {},
            "credentials": {"telegramApi": {"name": "bot"}},
        }
    )
    r = F.score_workflow(wf, _synthetic_ctx())
    assert r["elements"]["FW-S4"]["status"] == F.FAIL
    assert r["elements"]["FW-S3"]["status"] == F.FAIL
    wf = _direct_run_wf()
    wf["nodes"].append(
        {
            "name": "c",
            "type": "n8n-nodes-base.code",
            "parameters": {"jsCode": "const dsn = '" + "postgres" + "ql://h/db';"},
        }
    )
    assert F.score_workflow(wf, _synthetic_ctx())["elements"]["FW-S3"]["status"] == F.FAIL


def test_http_node_without_relay_credential_fails_authn():
    wf = _direct_run_wf()
    wf["nodes"][1].pop("credentials")
    assert F.score_workflow(wf, _synthetic_ctx())["elements"]["FW-S1"]["status"] == F.FAIL


def test_live_lane_without_effect_key_fails_idempotency():
    wf = _direct_run_wf()
    r = F.score_workflow(wf, _synthetic_ctx(effect_lanes=set()), entry={"mode": "live", "stage": "cutover"})
    assert r["elements"]["FW-R6"]["status"] == F.FAIL
    r = F.score_workflow(wf, _synthetic_ctx(effect_lanes=set()), entry={"mode": "dry_run", "stage": "shadow"})
    assert r["elements"]["FW-R6"]["status"] == F.PASS


def test_business_critical_past_shadow_needs_reviewed_contract():
    c = copy.deepcopy(_contract())
    c["status"] = "DRAFT"
    c["workflow_id"] = "wf-direct"
    c["kind"] = "generic_workflow"
    r = F.score_workflow(
        _direct_run_wf(),
        _synthetic_ctx(contracts=[c]),
        entry={"class": "business-critical", "stage": "cutover", "mode": "live"},
    )
    assert r["elements"]["FW-C3"]["status"] == F.FAIL
    r = F.score_workflow(
        _direct_run_wf(),
        _synthetic_ctx(contracts=[c]),
        entry={"class": "monitoring-compliance", "stage": "cutover", "mode": "live"},
    )
    assert r["elements"]["FW-C3"]["status"] == F.PARTIAL


def test_ai_workflow_must_declare_its_llm_steps(ctx):
    wf = _ref()
    wf["meta"]["framework"]["class"] = "ai-llm"
    r = F.score_workflow(wf, ctx)
    assert all(r["elements"][k]["status"] == F.FAIL for k in ("FW-G1", "FW-G2", "FW-G4"))
    # Audit 2026-10-15 (DD15): metadata for a node that does not exist used to satisfy every AI element. It fails
    # now; the positive case (a real, reachable POST /llm_step node) is in the adversarial test file.
    wf["meta"]["framework"]["llm_steps"] = [
        {
            "node": "Judge",
            "process_id": "n8n_lane_failure_diagnosis",
            "template_id": "lane_failure_diagnosis.v1",
            "output_schema_id": "lane_failure_decision/v1",
            "branch_fields": ["action_id"],
            "offpeak_tier": "standard",
            "hitl": "none",
            "exception_branch": "Judge refused",
        }
    ]
    r = F.score_workflow(wf, ctx)
    assert all(r["elements"][k]["status"] == F.FAIL for k in ("FW-W4", "FW-A5", "FW-G1", "FW-G2", "FW-G4", "FW-G5")), r[
        "elements"
    ]


def test_platform_elements_are_reported_not_scored(ctx):
    facts = json.loads((ROOT / F.DEFAULT_PLATFORM).read_text())
    rep = F.build_report([(REF_FILE, None)], ctx, facts, source="t")
    assert rep["platform"]["FW-P2"]["status"] == F.FAIL  # n8n DB role superuser, measured
    assert rep["workflows"][0]["score"]["pct"] == 100.0


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_cli_default_reports_and_strict_fails_on_active_set(capsys):
    assert F.main([]) == 0
    assert "Fleet:" in capsys.readouterr().out
    assert F.main(["--strict"]) == 1
    capsys.readouterr()
    assert F.main(["--strict", "--json", "--workflow", str(REF_FILE)]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == F.REPORT_SCHEMA and doc["fleet"]["pct"] == 100.0


def test_cli_unreadable_input_exits_2(tmp_path, capsys):
    bad = tmp_path / "active.json"
    bad.write_text(json.dumps({"schema": "nope"}))
    assert F.main(["--active", str(bad)]) == 2


def test_all_mode_scores_every_committed_workflow(capsys):
    assert F.main(["--all", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    ids = {r["id"] for r in doc["workflows"]}
    assert REF.WID in ids and T.RUN_LANE_ID in ids


# ── the scorecard and the design doc stay true ──────────────────────────────────────────────────────────────────


def test_scorecard_matches_the_checker(ctx):
    active = json.loads((ROOT / F.DEFAULT_ACTIVE).read_text())
    rep = F.build_report([(ROOT / w["file"], w) for w in active["workflows"]], ctx, None, source="t")
    card = (ROOT / "docs/implementation/n8n-maturity/N8N_FRAMEWORK_SCORECARD_20261015.md").read_text()
    f = rep["fleet"]
    assert f"{f['points']:g}/{f['of']} = {f['pct']}%" in card
    for r in rep["workflows"]:
        assert f"`{r['name']}`" in card


_E_IDS = {
    "scripts/n8n_workflow_templates.py": [
        "N8nWorkflowSet@v1",
        "N8nGenericWorkflowSet@v1",
        "N8nFabricManifest@v1",
        "FabricStepResult@v1",
        "FabricProcessResult@v1",
        "N8nFabricProcesses@v1",
        "RunLaneResult@v1",
    ],
    "scripts/lib/n8n_coordination_gateway.py": ["RunRequested@v1", "N8nCoordinationReceipt@v1"],
    "scripts/n8n_run_executor.py": ["RunReceipt@v1", "RunReceipt@v2", "ExecutorStatus@v1", "N8nExecutorConfig@v1"],
    "scripts/lib/n8n_fabric_store.py": ["RunOutcome@v1", "CommsIntentReceipt@v1", "N8nCommsIntentRoutes@v1"],
    "scripts/n8n_run_relay.py": ["N8nRunRelayLast@v1", "N8nRunRelayRoutes@v1"],
    "scripts/lib/n8n_due.py": ["DueResponse@v1", "N8nDueConfig@v1", "N8nRunAllowlist@v1"],
    "scripts/lib/effect_claim.py": ["EffectClaim@v1", "N8nEffectKeys@v1"],
    "scripts/lib/n8n_health_contracts.py": ["N8nHealthContracts@v1"],
    "config/n8n_health_contracts.json": ["N8nHealthContract@v1"],
    "scripts/lib/lane_last_receipt.py": ["LaneRunReceipt@v1"],
    "scripts/lib/bridge_llm_step.py": ["LlmStepResult@v1", "LlmStepAudit@v1", "N8nLlmStepOutputSchemas@v1"],
    "scripts/lib/n8n_model_job.py": ["N8nPromptTemplate@v1", "N8nModelJobReceipt@v1"],
    "scripts/lib/n8n_comms_intent_consumption.py": ["N8nCommsIntentConsumption@v1"],
    "scripts/n8n_incident_fanin.py": ["N8nIncidentFanin@v1"],
    "scripts/check_n8n_workflow_drift.py": ["N8nWorkflowDriftReceipt@v1"],
    "scripts/check_n8n_activation_grants.py": ["N8nActivationAttribution@v1"],
    "scripts/supervisor_breach_detector.py": ["Breach@v1"],
    "config/lane_registry.json": ["LaneRegistry@v1"],
    "config/n8n_retry_policies.json": ["N8nRetryPolicies@v1"],
    "scripts/lib/approval_package.py": ["ApprovalPackage@v1"],
    "scripts/check_n8n_workflow_framework.py": ["N8nWorkflowFrameworkReport@v2"],
}


def test_contracts_design_schema_ids_exist_in_their_owner_files():
    doc = (ROOT / "docs/architecture/n8n/N8N_CONTRACTS_DESIGN.md").read_text()
    for rel, ids in _E_IDS.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        for sid in ids:
            assert sid in text, f"{sid} not in {rel}"
            assert sid in doc, f"{sid} not in the contracts design"


def test_contracts_design_catalogue_matches_the_checker():
    doc = (ROOT / "docs/architecture/n8n/N8N_CONTRACTS_DESIGN.md").read_text()
    for eid in F.ELEMENTS:
        if not eid.startswith("FW-G"):
            assert f"| {eid} |" in doc, eid
    assert "FW-G1..G7" in doc and "FW-P1..P6" in doc
    assert set(F.PLATFORM_ELEMENTS) == {f"FW-P{i}" for i in range(1, 7)}


def test_reference_architecture_routes_match_the_relay():
    from n8n_run_relay import ROUTES

    doc = (ROOT / "docs/architecture/n8n/N8N_REFERENCE_ARCHITECTURE.md").read_text()
    for method, path in ROUTES:
        assert re.search(rf"`{method} {re.escape(path)}", doc), (method, path)


# ── the reference graph, interpreted (node.js runs the Code nodes) ──────────────────────────────────────────────

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node.js not on PATH")
HARNESS = r"""
const fs = require('fs');
const spec = JSON.parse(fs.readFileSync(0, 'utf8'));
const custom = {};
const items = spec.input.map((j) => ({ json: j }));
globalThis.$input = { first: () => items[0] || { json: {} }, all: () => items };
globalThis.$ = (name) => {
  if (!(name in spec.nodes)) throw new Error("Referenced node is unexecuted: " + name);
  return { first: () => ({ json: spec.nodes[name] }), last: () => ({ json: spec.nodes[name] }) };
};
globalThis.$now = { setZone: (tz) => ({ toFormat: (f) => spec.slot }) };
globalThis.$execution = { id: '77', customData: { set: (k, v) => { custom[k] = v; } } };
(async () => {
  try {
    const fn = new Function('return (async () => {' + spec.code + '\n})();');
    const out = await fn();
    process.stdout.write(JSON.stringify({ ok: true, out: out.map((i) => i.json), custom }));
  } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, error: String(e.message), custom }));
  }
})();
"""


def _js(name: str, items: list[dict], nodes: dict) -> dict:
    code = next(n for n in _ref()["nodes"] if n["name"] == name)["parameters"]["jsCode"]
    proc = subprocess.run(
        [NODE, "-e", HARNESS],
        capture_output=True,
        text=True,
        timeout=30,
        input=json.dumps({"code": code, "input": items, "nodes": nodes, "slot": "20261015T1900"}),
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@needs_node
def test_reference_graph_behaviour():
    ctx_out = _js(REF.N_CTX, [{}], {})
    assert ctx_out["ok"], ctx_out
    c = ctx_out["out"][0]
    assert c["idempotency_key"] == "p:aegis-nightly-ingestion:dry_run:20261015T1900" and c["mode"] == "dry_run"
    rec = _js(REF.N_RECORD, [{"schema": "RunLaneResult@v1", "run_id": "p:x", "status": "success"}], {REF.N_CTX: c})
    assert rec["ok"] and rec["custom"] == {
        "run_id": "p:x",
        "lane_id": REF.LANE,
        "process_id": REF.WID,
        "slot": "20261015T1900",
    }
    bad = _js(REF.N_RECORD, [{"status": "success"}], {REF.N_CTX: c})
    assert bad["out"][0]["status"] == "failed" and bad["out"][0]["reason"] == "no_run_lane_result"
    data = _js(REF.N_DATA, [{"status": "refused_policy", "reason": "effect:effect_fenced_owner"}], {REF.N_CTX: c})
    assert data["ok"] and data["out"][0]["status"] == "refused_policy"  # a refusal is data, not an error
    fail = _js(REF.N_FAIL, [{"lane_id": REF.LANE, "status": "failed", "reason": "exit_1"}], {})
    assert fail["ok"] is False and "failed" in fail["error"]


def test_reference_switch_routes_refusals_to_data_and_failures_to_fail():
    wf = _ref()
    outs = wf["connections"][REF.N_ROUTE]["main"]
    names = [o[0]["node"] for o in outs]
    want = {"success": REF.N_OK, "failed": REF.N_FAIL, "refused_policy": REF.N_DATA, "skipped_lock": REF.N_DATA}
    assert names == [want[s] for s in T.RUN_LANE_TERMINAL] + [REF.N_FAIL]
