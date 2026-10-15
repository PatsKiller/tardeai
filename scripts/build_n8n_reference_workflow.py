#!/usr/bin/env python3
"""build_n8n_reference_workflow.py — the reference MATURE n8n workflow (AGENTS.md §23.24), generated, INERT.

One business step done the way every new workflow should do it, so a reviewer can diff a candidate against it:

    Schedule (19:00 ET) | Manual run  ->  Run context (p: key, lane, budgets)  ->  Run lane (Execute Workflow ->
    tradeai-fabric-run-lane: request, poll RunOutcome@v1, retry, timeout)  ->  Record run (execution custom data
    run_id / lane_id / process_id / slot)  ->  Route outcome (Switch on status)
        success                      -> Outcome success   (FabricStepResult@v1, status success)
        refused_policy, skipped_lock -> Outcome as data   (a refusal is data, never an n8n error)
        failed, fallback             -> Fail run          (throws -> errorWorkflow tradeai-fabric-error -> /intent)

It carries ``meta.framework`` (N8nWorkflowFrameworkMeta@v1: class, owner, stage, connects_to, runbook, contract
reference, rollback), sets every fabric-required setting, and makes no HTTP call of its own (Run Lane makes them),
so it passes the fabric generator's own invariants (``validate_fabric_workflow`` + ``process_problems``). Its health
contract draft (``<id>.health_contract.json``, with the expected-output rule: exit 0 with nothing produced is a
FAILURE) and its runbook sit beside it.

INERT: ``active: false``; it is never imported or activated by this repository. The lane it names
(``aegis-nightly-ingestion``) has no ``live_arg``, so even an import could only ever run a dry run.

    python3 scripts/build_n8n_reference_workflow.py            # write the JSON + INDEX.json
    python3 scripts/build_n8n_reference_workflow.py --check    # exit 1 if regeneration would change a byte

AUTHORITY: READ_ONLY_ADVISORY. Writes only under docs/implementation/n8n-parallel/workflows/reference/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import n8n_workflow_templates as T  # noqa: E402

NO_CONSUMER_REASON = (
    "Generator of the committed reference workflow (docs/implementation/n8n-parallel/workflows/reference/); run by "
    "hand and by its test's --check. Nothing imports it; the workflow is never imported into n8n."
)

OUT = ROOT / "docs" / "implementation" / "n8n-parallel" / "workflows" / "reference"
GENERATOR = "scripts/build_n8n_reference_workflow.py"
SET_SCHEMA = "N8nReferenceWorkflowSet@v1"
META_SCHEMA = "N8nWorkflowFrameworkMeta@v1"
WID = "tradeai-reference-mature-workflow"
LANE = "aegis-nightly-ingestion"
MODE = "dry_run"
SCHEDULE = "0 19 * * *"
LANE_TIMEOUT_S = 600  # config/n8n_run_allowlist.json timeout_s for the lane
MAX_ATTEMPTS = 2
OUTCOME_TIMEOUT_S = LANE_TIMEOUT_S + T.PROCESS_OUTCOME_MARGIN_S
EXECUTION_TIMEOUT_S = T.run_lane_worst_case_s(MAX_ATTEMPTS, OUTCOME_TIMEOUT_S) + 120
REL = "docs/implementation/n8n-parallel/workflows/reference"
CONTRACT_FILE = f"{WID}.health_contract.json"
RUNBOOK_FILE = f"RUNBOOK_{WID}.md"

N_SCHED, N_MANUAL, N_CTX, N_RUN = "Schedule 19:00 ET", "Manual run", "Run context", "Run lane"
N_RECORD, N_ROUTE, N_OK, N_DATA, N_FAIL = (
    "Record run",
    "Route outcome",
    "Outcome success",
    "Outcome as data",
    "Fail run",
)


def framework_meta() -> dict:
    return {
        "schema": META_SCHEMA,
        "class": "business-critical",
        "owner": "research",
        "stage": "shadow",
        "lanes": [LANE],
        "connects_to": [
            f"workflow:{T.RUN_LANE_ID} (Execute Workflow, waits)",
            "relay:POST /run, relay:GET /run_outcome (through Run Lane only)",
            f"lane:{LANE} (config/n8n_run_allowlist.json; dry_run only, live_arg null)",
            f"workflow:{T.FABRIC_ERROR_ID} (errorWorkflow) -> relay:POST /intent",
        ],
        "runbook_id": "n8n-reference-mature-workflow",
        "runbook_path": f"{REL}/{RUNBOOK_FILE}",
        "health_contract_ref": f"{REL}/{CONTRACT_FILE}",
        "effect_process": LANE,
        "rollback": "the lane's own cron line stays the owner (crontab L308); rollback = unpublish this workflow "
        "(docs/ops/ROLLBACK_COMMANDS.md); nothing to undo host-side",
        "llm_steps": [],
    }


def _context_js() -> str:
    return "\n".join(
        T._js_header()
        + [
            "// Reference mature workflow: one step through Run Lane. The p: key names the business slot (ET minute).",
            f"const LANE = {json.dumps(LANE)};",
            f"const MODE = {json.dumps(MODE)};",
            f"const slot = $now.setZone({json.dumps(T.TIMEZONE)}).toFormat(\"yyyyLLdd'T'HHmm\");",
            "return [{ json: { lane_id: LANE, mode: MODE, slot,",
            f"  idempotency_key: `{T.PROCESS_KEY_PREFIX}:${{LANE}}:${{MODE}}:${{slot}}`,",
            f"  max_attempts: {MAX_ATTEMPTS}, outcome_timeout_s: {OUTCOME_TIMEOUT_S}, process_id: {json.dumps(WID)} }} }}];",
            "",
        ]
    )


def _record_js() -> str:
    return "\n".join(
        T._js_header()
        + [
            "// Join key for the ledger (run_id <-> execution_id): saved with the successful execution (FW-M1).",
            f"const c = $('{N_CTX}').first().json;",
            "const r = $input.first().json || {};",
            "$execution.customData.set('run_id', String(r.run_id || c.idempotency_key));",
            "$execution.customData.set('lane_id', String(c.lane_id));",
            "$execution.customData.set('process_id', String(c.process_id));",
            "$execution.customData.set('slot', String(c.slot));",
            "if (r.schema !== 'RunLaneResult@v1') {",
            "  return [{ json: { ...r, status: 'failed', reason: 'no_run_lane_result' } }];",
            "}",
            "return [{ json: r }];",
            "",
        ]
    )


def _outcome_js(kind: str) -> str:
    return "\n".join(
        T._js_header()
        + [
            f"// {kind}: FabricStepResult@v1. Whether the run PRODUCED anything is decided host-side from the lane's",
            "// receipt against the contract's expected_output rule (exit 0 with nothing produced is a failure).",
            f"const c = $('{N_CTX}').first().json;",
            "const r = $input.first().json || {};",
            f"return [{{ json: {{ schema: {json.dumps(T.PROCESS_STEP_RESULT_SCHEMA)}, step_id: 'reference', lane_id: c.lane_id,",
            "  status: r.status, run_id: r.run_id ?? null, attempts: r.attempts ?? 0, reason: r.reason ?? null,",
            "  receipt_path: r.receipt_path ?? null, effect_key: r.effect_key ?? null } }];",
            "",
        ]
    )


def _fail_js() -> str:
    return "\n".join(
        T._js_header()
        + [
            "// A failed run (after Run Lane's retries) or an unrouted status fails the execution on purpose:",
            "// errorWorkflow tradeai-fabric-error turns it into one deduped send-INTENT with a runbook id.",
            "const r = $input.first().json || {};",
            "throw new Error('reference: ' + String(r.lane_id || '') + ' ' + String(r.status || 'unknown') + ' '",
            "  + String(r.reason || '').slice(0, 80));",
            "",
        ]
    )


def build() -> dict:
    nodes: list[dict] = [
        {
            "id": T._f_node_id(WID, N_SCHED),
            "name": N_SCHED,
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [0, 0],
            "parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": SCHEDULE}]}},
        },
        {
            "id": T._f_node_id(WID, N_MANUAL),
            "name": N_MANUAL,
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1,
            "position": [0, 240],
            "parameters": {},
        },
        T._f_code(WID, N_CTX, _context_js(), [240, 120]),
        T._p_run(WID, N_RUN, [480, 120]),
        T._f_code(WID, N_RECORD, _record_js(), [720, 120]),
        T._f_switch(WID, N_ROUTE, "={{ $json.status }}", T.RUN_LANE_TERMINAL, [960, 120]),
        T._f_code(WID, N_OK, _outcome_js("success"), [1200, 0]),
        T._f_code(WID, N_DATA, _outcome_js("refusal or lock skip as data"), [1200, 160]),
        T._f_code(WID, N_FAIL, _fail_js(), [1200, 320]),
    ]
    conns: dict = {}
    T._p_conn(conns, N_SCHED, [[(N_CTX, 0)]])
    T._p_conn(conns, N_MANUAL, [[(N_CTX, 0)]])
    T._p_conn(conns, N_CTX, [[(N_RUN, 0)]])
    T._p_conn(conns, N_RUN, [[(N_RECORD, 0)]])
    T._p_conn(conns, N_RECORD, [[(N_ROUTE, 0)]])
    by_status = {"success": N_OK, "failed": N_FAIL, "refused_policy": N_DATA, "skipped_lock": N_DATA}
    T._p_conn(conns, N_ROUTE, [[(by_status[s], 0)] for s in T.RUN_LANE_TERMINAL] + [[(N_FAIL, 0)]])
    nodes.sort(key=lambda n: n["name"])
    wf = {
        "id": WID,
        "name": WID,
        "active": False,
        "nodes": nodes,
        "connections": conns,
        "settings": T._fabric_settings(WID, EXECUTION_TIMEOUT_S),
        "meta": {
            "generator": GENERATOR,
            "kind": "reference",
            "design": "docs/architecture/n8n/N8N_REFERENCE_ARCHITECTURE.md; N8N_CONTRACTS_DESIGN.md §13 (AGENTS.md "
            "§23.23 + §23.24); INERT, never imported",
            "framework": framework_meta(),
        },
    }
    wf["meta"]["graph_sha256"] = T.graph_hash(wf)
    wf["meta"]["policy_sha256"] = T.policy_hash()
    return wf


def problems(wf: dict) -> list[str]:
    known = {WID, T.RUN_LANE_ID, T.FABRIC_ERROR_ID}
    return T.validate_fabric_workflow(wf, known) + T.process_problems(wf)


def render() -> dict[str, str]:
    wf = build()
    bad = problems(wf)
    if bad:
        raise ValueError(f"reference workflow refused by the fabric invariants: {bad}")
    text = T._dump(wf)
    index = {
        "schema": SET_SCHEMA,
        "generator": GENERATOR,
        "authority": "READ_ONLY_ADVISORY",
        "inert": "never imported or activated; a reference for reviewers and for scripts/check_n8n_workflow_framework.py",
        "workflows": [
            {
                "id": WID,
                "kind": "reference",
                "file": f"{WID}.json",
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "graph_sha256": wf["meta"]["graph_sha256"],
                "policy_sha256": wf["meta"]["policy_sha256"],
                "node_types": sorted({n["type"] for n in wf["nodes"]}),
                "error_workflow": wf["settings"]["errorWorkflow"],
                "relay_calls": [],
                "health_contract": CONTRACT_FILE,
                "runbook": RUNBOOK_FILE,
                "active": False,
            }
        ],
    }
    return {f"{WID}.json": text, "INDEX.json": T._dump(index)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--check", action="store_true", help="fail if regenerating would change any byte")
    a = ap.parse_args(argv)
    out = Path(a.out)
    files = render()
    if a.check:
        diffs = [
            rel
            for rel, text in sorted(files.items())
            if not (out / rel).exists() or (out / rel).read_bytes() != text.encode("utf-8")
        ]
        print(json.dumps({"mode": "check-reference", "files": len(files), "diffs": diffs}))
        return 1 if diffs else 0
    out.mkdir(parents=True, exist_ok=True)
    changed = []
    for rel, text in sorted(files.items()):
        path = out / rel
        if not path.exists() or path.read_bytes() != text.encode("utf-8"):
            path.write_bytes(text.encode("utf-8"))
            changed.append(rel)
    print(json.dumps({"mode": "write-reference", "files": len(files), "changed": changed}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
