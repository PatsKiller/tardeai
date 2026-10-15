#!/usr/bin/env python3
"""check_n8n_workflow_framework.py — score n8n workflows against the AGENTS.md §23.24 mandatory framework.

Offline and read-only. Reads the committed workflow JSON (generic set, fabric set, per-lane set, reference set),
their generator manifests, ``config/n8n_health_contracts.json`` (or a contract named by the workflow's
``meta.framework.health_contract_ref``), ``config/n8n_run_allowlist.json``, ``config/n8n_effect_keys.json``,
``config/n8n_retry_policies.json``, the relay route table (``scripts/n8n_run_relay.py`` ``ROUTES``), the generator's
node-type policy and, for the platform elements, a cited platform-facts file. Writes nothing unless ``--out`` /
``--markdown`` name a file.

Each element of the catalogue (docs/architecture/n8n/N8N_CONTRACTS_DESIGN.md §12) yields ``pass``, ``partial``,
``fail`` or ``n/a`` with a reason. Workflow elements score the workflow (pass 1, partial 0.5, n/a excluded).
Platform elements (instance-wide facts: DB role, instance success saving, drift schedule, relay firewall, dead-man)
are reported once and are not counted in any workflow's score — no workflow PR can fix them.

The operator rule of 2026-10-15 is element FW-M6: a run that exits 0 but produces nothing is a FAILURE, so a
workflow whose health contract declares no ``expected_output`` rule FAILS the monitoring area.

    python3 scripts/check_n8n_workflow_framework.py                    # active set, markdown summary to stdout
    python3 scripts/check_n8n_workflow_framework.py --json             # N8nWorkflowFrameworkReport@v1
    python3 scripts/check_n8n_workflow_framework.py --all              # every committed workflow
    python3 scripts/check_n8n_workflow_framework.py --workflow PATH    # one or more files
    python3 scripts/check_n8n_workflow_framework.py --strict           # exit 1 if any workflow element fails

Exit: 0 report (default, whatever the scores); 1 ``--strict`` and a workflow element failed; 2 an input could not
be read. AUTHORITY: READ_ONLY_ADVISORY. No n8n, no relay, no gateway, no DB, no send.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

REPORT_SCHEMA = "N8nWorkflowFrameworkReport@v1"
META_SCHEMA = "N8nWorkflowFrameworkMeta@v1"
EXPECTED_OUTPUT_SCHEMA = "N8nExpectedOutput@v1"
ACTIVE_SET_SCHEMA = "N8nActiveWorkflowSet@v1"
PLATFORM_FACTS_SCHEMA = "N8nPlatformFacts@v1"

CLASSES = ("business-critical", "resilience", "ai-llm", "monitoring-compliance")
STAGES = ("shadow", "canary", "cutover")
EXPECTED_OUTPUT_RULES = ("min_produced", "per_window", "empty_allowed")
PASS, PARTIAL, FAIL, NA = "pass", "partial", "fail", "n/a"
POINTS = {PASS: 1.0, PARTIAL: 0.5, FAIL: 0.0}

WORKFLOWS_DIR = Path("docs/implementation/n8n-maturity/workflows")
FABRIC_DIR = WORKFLOWS_DIR / "fabric"
PER_LANE_DIR = Path("docs/implementation/n8n-parallel/workflows/generated")
REFERENCE_DIR = Path("docs/implementation/n8n-parallel/workflows/reference")
DEFAULT_ACTIVE = Path("docs/implementation/n8n-maturity/data/n8n_active_workflows_20261015.json")
DEFAULT_PLATFORM = Path("docs/implementation/n8n-maturity/data/n8n_platform_facts_20261015.json")
CONTRACTS = Path("config/n8n_health_contracts.json")
ALLOWLIST = Path("config/n8n_run_allowlist.json")
EFFECT_KEYS = Path("config/n8n_effect_keys.json")
RETRY_POLICIES = Path("config/n8n_retry_policies.json")
PROCESSES = Path("config/n8n_fabric_processes.json")
PROMPT_TEMPLATES = Path("config/n8n_prompt_templates.json")
LLM_SCHEMAS = Path("config/schemas/n8n_llm_step_outputs.json")
LLM_PROCESSES = Path("config/llm_process_registry.json")

AREAS = ("scope", "monitoring", "alerting", "logging", "recovery", "security", "ai_llm")
ELEMENTS: dict[str, tuple[str, str]] = {
    "FW-C1": ("scope", "class declared in generator metadata"),
    "FW-C2": ("scope", "owner declared in generator metadata"),
    "FW-C3": ("scope", "health contract (REVIEWED for business-critical / AI)"),
    "FW-M1": ("monitoring", "success evidence joinable by run_id"),
    "FW-M2": ("monitoring", "failure: settings.errorWorkflow"),
    "FW-M3": ("monitoring", "performance: executionTimeout + contract duration bound"),
    "FW-M4": ("monitoring", "capacity: contract class under executor class caps"),
    "FW-M5": ("monitoring", "dependency: connects_to"),
    "FW-M6": ("monitoring", "expected output: exit 0 with nothing produced is a failure"),
    "FW-A1": ("alerting", "failure routed to the incident path"),
    "FW-A2": ("alerting", "SLA breach: freshness bound + priority"),
    "FW-A3": ("alerting", "performance degradation: duration bound + slow check"),
    "FW-A4": ("alerting", "integration failure: refusals are data"),
    "FW-A5": ("alerting", "AI/LLM exception branch"),
    "FW-A6": ("alerting", "runbook id"),
    "FW-L1": ("logging", "execution: successes saved"),
    "FW-L2": ("logging", "error: failures saved"),
    "FW-L4": ("logging", "security: every host call through the relay"),
    "FW-L5": ("logging", "change: generated from git, manifest hash"),
    "FW-R1": ("recovery", "retry has one owner"),
    "FW-R2": ("recovery", "breaker / dead letter"),
    "FW-R3": ("recovery", "fallback declared"),
    "FW-R5": ("recovery", "manual recovery runbook resolves"),
    "FW-R6": ("recovery", "idempotency: effect key for live work"),
    "FW-S1": ("security", "authN: relay credential / webhook header auth"),
    "FW-S2": ("security", "authZ: allowlisted lanes, known relay routes"),
    "FW-S3": ("security", "secrets: one credential, no secret literals"),
    "FW-S4": ("security", "node types inside the fabric allowlist"),
    "FW-G1": ("ai_llm", "prompt: registered template id"),
    "FW-G2": ("ai_llm", "model selection: registered process id only"),
    "FW-G3": ("ai_llm", "cost: per-process caps"),
    "FW-G4": ("ai_llm", "response validation: closed output schema"),
    "FW-G5": ("ai_llm", "hallucination control: enumerated branch fields"),
    "FW-G6": ("ai_llm", "deferral tier declared"),
    "FW-G7": ("ai_llm", "HITL gate declared"),
}
PLATFORM_ELEMENTS: dict[str, str] = {
    "FW-P1": "instance saves successful executions (FW-M1/L1 need it per workflow until it does)",
    "FW-P2": "n8n DB role is not superuser (§23.24 Logging (3), Security audit trail)",
    "FW-P3": "drift check runs on a host schedule and pages P1 (§23.23 governance (2))",
    "FW-P4": "relay docker-bridge bind is firewalled (§23.24 Security (4))",
    "FW-P5": "image pinned, env access blocked in nodes, community packages off (§23.24 Security (3))",
    "FW-P6": "a dead-man outside n8n watches n8n (§23.23 Independence)",
}

_SECRET_RES = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{8,}"),
    re.compile(r"(?i)postgres(?:ql)?://"),
    re.compile(r"(?<![A-Za-z])sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|password|passwd|secret|token)\b\s*[:=]\s*['\"][^'\"$]{8,}['\"]"),
)
_RUN_BODY_IDS = ("workflow_id", "execution_id")


# ---------------------------------------------------------------------------------------------------------------
# inputs


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


@dataclass
class Context:
    """Everything the scoring reads besides the workflow itself. Tests build one directly."""

    root: Path
    contracts: list[dict]
    allowlist_lanes: set[str]
    effect_lanes: set[str]
    class_caps: set[str]
    relay_routes: set[tuple[str, str]]
    allowed_node_types: frozenset[str]
    forbidden_node_types: frozenset[str]
    credential_name: str
    run_lane_id: str
    error_workflow_ids: frozenset[str]
    process_lanes: dict[str, list[str]] = field(default_factory=dict)
    manifests: dict[str, dict] = field(default_factory=dict)  # repo-relative file -> manifest row (+ "_manifest")
    prompt_templates: set[str] = field(default_factory=set)
    llm_schemas: set[str] = field(default_factory=set)
    llm_processes: dict[str, dict] = field(default_factory=dict)
    intent_runbooks: dict[str, str] = field(default_factory=dict)


def _manifest_rows(root: Path) -> dict[str, dict]:
    """Every committed workflow file listed by a generator manifest -> its row (sha256 when the manifest has one)."""
    out: dict[str, dict] = {}
    for d in (WORKFLOWS_DIR, FABRIC_DIR, REFERENCE_DIR):
        idx = root / d / "INDEX.json"
        if not idx.exists():
            continue
        doc = _load(idx)
        for row in doc.get("workflows") or []:
            if row.get("file"):
                out[str(d / row["file"])] = dict(row, _manifest=f"{d}/INDEX.json ({doc.get('schema')})")
    idx = root / PER_LANE_DIR / "INDEX.json"
    if idx.exists():
        doc = _load(idx)
        for row in doc.get("lanes") or []:
            for key in ("live_file", "shadow_file"):
                if row.get(key):  # pending lanes carry their "pending/" prefix in the row
                    out[str(PER_LANE_DIR / row[key])] = {
                        "file": row[key],
                        "lane_id": row.get("lane_id"),
                        "_manifest": f"{PER_LANE_DIR}/INDEX.json ({doc.get('schema')}); byte equality is "
                        "`scripts/n8n_workflow_templates.py --check`",
                    }
    return out


def build_context(root: Path = ROOT) -> Context:
    """The real repository context. Imports the generator and relay only for their constants."""
    import n8n_workflow_templates as T  # noqa: PLC0415 — constants only
    from n8n_run_relay import ROUTES  # noqa: PLC0415

    contracts = _load(root / CONTRACTS).get("contracts") or []
    allow = _load(root / ALLOWLIST)
    effect = _load(root / EFFECT_KEYS)
    retry = _load(root / RETRY_POLICIES)
    procs = _load(root / PROCESSES).get("processes") or {}
    process_lanes = {
        str(spec.get("workflow_id")): [str(s.get("lane_id")) for s in (spec.get("steps") or {}).values()]
        for spec in procs.values()
    }
    templates = {
        str(t.get("template_id") or t.get("id")) for t in _load(root / PROMPT_TEMPLATES).get("templates") or []
    }
    schemas = set((_load(root / LLM_SCHEMAS).get("schemas") or {}).keys())
    llm_procs = {str(p.get("id")): p for p in _load(root / LLM_PROCESSES).get("processes") or []}
    routes_doc = _load(root / "config" / "n8n_comms_intent_routes.json")
    intent_runbooks = {f"{r['domain']}:{r['kind']}": str(r.get("runbook_id")) for r in routes_doc.get("routes") or []}
    return Context(
        root=root,
        contracts=contracts,
        allowlist_lanes={str(x.get("lane_id")) for x in allow.get("lanes") or []},
        effect_lanes=set((effect.get("lanes") or {}).keys()),
        class_caps=set((retry.get("class_caps") or {}).keys()) - {"global", "reserved_priority_max"},
        relay_routes=set(ROUTES),
        allowed_node_types=frozenset(T.FABRIC_ALLOWED_NODE_TYPES),
        forbidden_node_types=frozenset(T.FABRIC_FORBIDDEN_NODE_TYPES),
        credential_name=T.CREDENTIAL_NAME,
        run_lane_id=T.RUN_LANE_ID,
        error_workflow_ids=frozenset({T.FABRIC_ERROR_ID, T.INCIDENT_ROUTER_ID}),
        process_lanes=process_lanes,
        manifests=_manifest_rows(root),
        prompt_templates=templates,
        llm_schemas=schemas,
        llm_processes=llm_procs,
        intent_runbooks=intent_runbooks,
    )


# ---------------------------------------------------------------------------------------------------------------
# workflow facts


def _nodes(wf: Mapping) -> list[dict]:
    return [n for n in wf.get("nodes") or [] if isinstance(n, dict)]


def _of_type(wf: Mapping, suffix: str) -> list[dict]:
    return [n for n in _nodes(wf) if str(n.get("type", "")).endswith("." + suffix)]


def framework_meta(wf: Mapping) -> dict:
    meta = (wf.get("meta") or {}).get("framework")
    return meta if isinstance(meta, dict) else {}


_PATH_RE = re.compile(r"\}\}\s*(/[^\s?\"']*)")


def relay_calls(wf: Mapping) -> list[tuple[str, str]]:
    """(METHOD, route) for every HTTP node, the route normalised to the relay table's shape."""
    out = []
    for n in _of_type(wf, "httpRequest"):
        p = n.get("parameters") or {}
        url = str(p.get("url") or "")
        m = _PATH_RE.search(url)
        path = m.group(1) if m else url
        if re.fullmatch(r"/runs/[^/]+/last", path):
            path = "/runs/<lane_id>/last"
        out.append((str(p.get("method") or "GET").upper(), path))
    return out


def calls_run_lane(wf: Mapping, run_lane_id: str) -> bool:
    for n in _of_type(wf, "executeWorkflow"):
        wid = ((n.get("parameters") or {}).get("workflowId") or {}).get("value")
        if wid == run_lane_id:
            return True
    return False


def requests_runs(wf: Mapping, ctx: Context) -> bool:
    return (
        wf.get("id") == ctx.run_lane_id
        or calls_run_lane(wf, ctx.run_lane_id)
        or any(c == ("POST", "/run") for c in relay_calls(wf))
    )


def direct_run_nodes(wf: Mapping) -> list[dict]:
    return [n for n in _of_type(wf, "httpRequest") if relay_calls({"nodes": [n]}) == [("POST", "/run")]]


_LANE_LIT_RE = re.compile(r"lane_id:\s*\"([A-Za-z0-9._-]+)\"")


def named_lanes(wf: Mapping, ctx: Context) -> list[str]:
    """Lanes the workflow names statically. Dispatcher-style workflows take lanes from /due (none named here)."""
    lanes: list[str] = []
    meta = wf.get("meta") or {}
    fw = framework_meta(wf)
    lanes += [str(x) for x in fw.get("lanes") or []]
    if meta.get("lane_id"):
        lanes.append(str(meta["lane_id"]))
    for n in _of_type(wf, "httpRequest"):
        lanes += _LANE_LIT_RE.findall(str((n.get("parameters") or {}).get("jsonBody") or ""))
    lanes += ctx.process_lanes.get(str(wf.get("id")), [])
    seen: list[str] = []
    for x in lanes:
        if x not in seen:
            seen.append(x)
    return seen


def find_contract(wf: Mapping, ctx: Context, entry: Mapping | None) -> tuple[dict | None, str]:
    """The health contract that governs this workflow, and where it came from."""
    fw = framework_meta(wf)
    ref = fw.get("health_contract_ref")
    if ref:
        path = ctx.root / str(ref)
        if path.exists():
            doc = _load(path)
            c = doc.get("contract") if isinstance(doc.get("contract"), dict) else doc
            return c, str(ref)
        return None, f"health_contract_ref {ref} does not exist"
    wid = str(wf.get("id"))
    ids = {wid, str((entry or {}).get("live_id") or wid)}
    want = fw.get("health_contract_id")
    for c in ctx.contracts:
        if want and c.get("id") == want:
            return c, f"{CONTRACTS} id={want}"
    for c in ctx.contracts:
        if c.get("kind") == "generic_workflow" and c.get("workflow_id") in ids:
            return c, f"{CONTRACTS} id={c.get('id')}"
    for c in ctx.contracts:
        if c.get("kind") == "lane" and c.get("workflow_id") in ids - {"tradeai-dispatcher"}:
            return c, f"{CONTRACTS} id={c.get('id')} (workflow_id)"
    lane = str((wf.get("meta") or {}).get("lane_id") or "")
    for c in ctx.contracts:
        if lane and c.get("id") == lane:
            return c, f"{CONTRACTS} id={lane} (lane contract)"
    return None, "no contract for the workflow id, its live id or its lane"


# ---------------------------------------------------------------------------------------------------------------
# scoring


def _r(status: str, reason: str) -> dict:
    return {"status": status, "reason": reason}


def _check_expected_output(c: Mapping | None) -> dict:
    if not c:
        return _r(FAIL, "no health contract, so no expected-output rule (an exit-0 run that produced nothing passes)")
    eo = c.get("expected_output")
    if not isinstance(eo, dict):
        return _r(
            FAIL,
            f"contract {c.get('id')} declares no expected_output rule: exit 0 with nothing produced "
            "would read as success (operator rule 2026-10-15)",
        )
    problems = []
    if eo.get("schema") != EXPECTED_OUTPUT_SCHEMA:
        problems.append(f"schema != {EXPECTED_OUTPUT_SCHEMA}")
    rule = eo.get("rule")
    if rule not in EXPECTED_OUTPUT_RULES:
        problems.append(f"rule {rule!r} not in {EXPECTED_OUTPUT_RULES}")
    if rule in ("min_produced", "per_window") and not (
        isinstance(eo.get("min_produced"), int) and eo["min_produced"] >= 1
    ):
        problems.append("min_produced must be an int >= 1")
    if rule == "per_window" and not (isinstance(eo.get("window_h"), (int, float)) and eo["window_h"] > 0):
        problems.append("per_window needs window_h > 0")
    if not eo.get("produced_field"):
        problems.append("produced_field missing")
    if not eo.get("unit"):
        problems.append("unit missing")
    if not isinstance(eo.get("fatal_skip_reasons"), list):
        problems.append("fatal_skip_reasons list missing")
    if not (isinstance(eo.get("evidence"), list) and eo["evidence"]):
        problems.append("evidence list empty")
    if problems:
        return _r(FAIL, "expected_output invalid: " + "; ".join(problems))
    return _r(PASS, f"expected_output rule {rule} on {eo.get('produced_field')} ({eo.get('unit')})")


def score_workflow(wf: Mapping, ctx: Context, *, entry: Mapping | None = None, file: str | None = None) -> dict:
    """Score one workflow. ``entry`` is its active-set row (class, mode, stage), when it has one."""
    entry = entry or {}
    fw = framework_meta(wf)
    settings = wf.get("settings") or {}
    wid = str(wf.get("id"))
    wclass = fw.get("class") if fw.get("class") in CLASSES else entry.get("class")
    stage = fw.get("stage") if fw.get("stage") in STAGES else entry.get("stage")
    contract, contract_src = find_contract(wf, ctx, entry)
    base = (contract or {}).get("baseline") or {}
    alerting = (contract or {}).get("alerting") or {}
    is_run_lane = wid == ctx.run_lane_id
    uses_run_lane = calls_run_lane(wf, ctx.run_lane_id)
    runs = requests_runs(wf, ctx)
    direct_runs = direct_run_nodes(wf)
    http = _of_type(wf, "httpRequest")
    calls = relay_calls(wf)
    lanes = named_lanes(wf, ctx)
    llm_steps = [s for s in fw.get("llm_steps") or [] if isinstance(s, dict)]
    is_ai = bool(llm_steps) or wclass == "ai-llm" or any(path == "/llm_step" for _, path in calls)
    code_text = "\n".join(str((n.get("parameters") or {}).get("jsCode") or "") for n in _of_type(wf, "code"))
    el: dict[str, dict] = {}

    # Scope -------------------------------------------------------------------------------------------------
    if fw.get("class") in CLASSES:
        el["FW-C1"] = _r(PASS, f"meta.framework.class = {fw['class']}")
    elif entry.get("class"):
        el["FW-C1"] = _r(
            FAIL,
            f"no meta.framework.class (class '{entry['class']}' is recorded only in the gap "
            "assessment, not in generator metadata)",
        )
    else:
        el["FW-C1"] = _r(FAIL, "no meta.framework.class")
    el["FW-C2"] = (
        _r(PASS, f"meta.framework.owner = {fw['owner']}") if fw.get("owner") else _r(FAIL, "no meta.framework.owner")
    )
    if contract is None:
        el["FW-C3"] = _r(FAIL, f"no health contract ({contract_src})")
    elif contract.get("status") == "REVIEWED":
        el["FW-C3"] = _r(PASS, f"REVIEWED contract {contract.get('id')} ({contract_src})")
    elif wclass in ("business-critical", "ai-llm") and stage in ("canary", "cutover"):
        el["FW-C3"] = _r(FAIL, f"{wclass} past shadow with a {contract.get('status')} contract {contract.get('id')}")
    else:
        el["FW-C3"] = _r(PARTIAL, f"{contract.get('status')} contract {contract.get('id')} ({contract_src})")

    # Monitoring ----------------------------------------------------------------------------------------------
    saved = settings.get("saveDataSuccessExecution") == "all"
    custom = "customData.set('run_id'" in code_text or 'customData.set("run_id"' in code_text
    ids_in_body = bool(direct_runs) and all(
        all(k in str((n.get("parameters") or {}).get("jsonBody") or "") for k in _RUN_BODY_IDS) for n in direct_runs
    )
    joinable = custom or (ids_in_body and not uses_run_lane)
    if not runs and http:
        bodies = [
            str((n.get("parameters") or {}).get("jsonBody") or "")
            for n in http
            if n.get("parameters", {}).get("jsonBody")
        ]
        joinable = joinable or (bool(bodies) and all(all(k in b for k in _RUN_BODY_IDS) for b in bodies))
    if saved and joinable:
        el["FW-M1"] = _r(PASS, "successes saved; run_id carried (custom data or request body)")
    elif saved or joinable:
        el["FW-M1"] = _r(
            PARTIAL,
            ("successes saved" if saved else "successes NOT saved (instance default none)")
            + "; "
            + ("run_id joinable" if joinable else "no run_id custom data on this execution"),
        )
    else:
        el["FW-M1"] = _r(FAIL, "successes not saved and no run_id join")
    ew = settings.get("errorWorkflow")
    el["FW-M2"] = (
        _r(PASS, f"errorWorkflow = {ew}")
        if ew in ctx.error_workflow_ids
        else _r(FAIL, f"errorWorkflow = {ew!r} (not a known error workflow)")
        if ew
        else _r(FAIL, "settings.errorWorkflow not set")
    )
    timeout = isinstance(settings.get("executionTimeout"), int) and settings["executionTimeout"] > 0
    bound = isinstance(base.get("duration_degraded_above_s"), (int, float))
    el["FW-M3"] = (
        _r(
            PASS,
            f"executionTimeout {settings.get('executionTimeout')} s; duration bound "
            f"{base.get('duration_degraded_above_s')} s",
        )
        if timeout and bound
        else _r(PARTIAL, "executionTimeout set; contract has no duration bound")
        if timeout
        else _r(PARTIAL, "contract duration bound; no executionTimeout")
        if bound
        else _r(FAIL, "no executionTimeout and no contract duration bound")
    )
    klass = base.get("class")
    if not runs:
        el["FW-M4"] = _r(NA, "requests no lane run")
    elif klass in ctx.class_caps:
        el["FW-M4"] = _r(PASS, f"class {klass} has an executor class cap")
    elif klass:
        el["FW-M4"] = _r(PARTIAL, f"class {klass!r} has no class_caps row; only the global cap applies")
    else:
        el["FW-M4"] = _r(FAIL, "no contract baseline class")
    deps = (contract or {}).get("connects_to") or fw.get("connects_to") or []
    el["FW-M5"] = _r(PASS, f"{len(deps)} connects_to edges") if deps else _r(FAIL, "no connects_to")
    el["FW-M6"] = _check_expected_output(contract)

    # Alerting ------------------------------------------------------------------------------------------------
    if ew and ew == wid:
        el["FW-A1"] = _r(
            FAIL, "self-referencing error workflow: its own failure alerts nothing in n8n (host fan-in must catch it)"
        )
    elif ew in ctx.error_workflow_ids:
        el["FW-A1"] = _r(PASS, f"failures → {ew} → incident path")
    else:
        el["FW-A1"] = _r(FAIL, "failures are not routed (no error workflow)")
    fresh = isinstance(base.get("freshness_failed_after_h"), (int, float))
    prio = bool((alerting.get("failed") or {}).get("notifier_priority"))
    el["FW-A2"] = (
        _r(
            PASS,
            f"freshness failed after {base.get('freshness_failed_after_h')} h, "
            f"{alerting['failed']['notifier_priority']}",
        )
        if fresh and prio
        else _r(PARTIAL, "freshness bound or priority missing")
        if (fresh or prio)
        else _r(FAIL, "no SLA bound in a contract")
    )
    slow = any(d.get("check") == "slow" for d in (contract or {}).get("degraded") or [])
    el["FW-A3"] = (
        _r(PASS, "duration bound + slow degraded check")
        if bound and slow
        else _r(PARTIAL, "duration bound without a slow check" if bound else "slow check without a bound")
        if (bound or slow)
        else _r(FAIL, "no performance bound")
    )
    if is_run_lane or uses_run_lane:
        el["FW-A4"] = _r(PASS, "runs go through Run Lane: refused_policy / skipped_lock are data")
    elif direct_runs:
        el["FW-A4"] = _r(
            FAIL,
            f"{len(direct_runs)} direct POST /run node(s): a refusal (RUN_REFUSED, already "
            "RUNNING) becomes an n8n error (WS1b-07)",
        )
    else:
        el["FW-A4"] = _r(NA, "requests no lane run")
    if not is_ai:
        el["FW-A5"] = _r(NA, "no LLM step")
    else:
        missing = [s.get("node") for s in llm_steps if not s.get("exception_branch")]
        el["FW-A5"] = (
            _r(PASS, "every LLM step has an exception branch")
            if llm_steps and not missing
            else _r(FAIL, f"LLM step(s) without exception branch: {missing or 'undeclared'}")
        )
    intent_kinds = re.findall(r"kind:\s*'([a-z_]+)'", code_text)
    if fw.get("runbook_id"):
        el["FW-A6"] = _r(PASS, f"runbook_id = {fw['runbook_id']}")
    elif any(path == "/intent" for _, path in calls) and any(
        f"fabric:{k}" in ctx.intent_runbooks for k in intent_kinds
    ):
        el["FW-A6"] = _r(
            PARTIAL,
            "its intents carry runbook_id via config/n8n_comms_intent_routes.json; the workflow metadata names none",
        )
    else:
        el["FW-A6"] = _r(FAIL, "no runbook_id")

    # Logging -------------------------------------------------------------------------------------------------
    el["FW-L1"] = (
        _r(PASS, "saveDataSuccessExecution = all") if saved else _r(FAIL, "successes not saved (instance default none)")
    )
    el["FW-L2"] = (
        _r(PASS, "saveDataErrorExecution = all")
        if settings.get("saveDataErrorExecution") == "all"
        else _r(PARTIAL, "relies on instance EXECUTIONS_DATA_SAVE_ON_ERROR=all")
    )
    if not http:
        el["FW-L4"] = (
            _r(PASS, "no HTTP node: every host call goes through Run Lane") if uses_run_lane else _r(NA, "no host call")
        )
    else:
        bad = [n.get("name") for n in http if "TRADEAI_N8N_RUN_URL" not in str((n.get("parameters") or {}).get("url"))]
        el["FW-L4"] = (
            _r(PASS, f"{len(http)} HTTP node(s), all to the relay (relay_log.jsonl)")
            if not bad
            else _r(FAIL, f"HTTP node(s) not addressed to the relay: {bad}")
        )
    rel = file
    row = ctx.manifests.get(rel or "")
    if row is None:
        el["FW-L5"] = _r(FAIL, f"{rel} is not listed by a generator manifest")
    elif row.get("sha256"):
        digest = hashlib.sha256((ctx.root / rel).read_bytes()).hexdigest() if rel else ""
        el["FW-L5"] = (
            _r(PASS, f"listed in {row['_manifest']}; sha256 matches")
            if digest == row["sha256"]
            else _r(FAIL, f"sha256 differs from {row['_manifest']} (regenerate)")
        )
    else:
        el["FW-L5"] = _r(PASS, f"listed in {row['_manifest']}")

    # Recovery ------------------------------------------------------------------------------------------------
    retry_http = bool(http) and all(n.get("retryOnFail") for n in http)
    if is_run_lane:
        el["FW-R1"] = _r(PASS, "is the retry owner (Run Lane)")
    elif uses_run_lane:
        el["FW-R1"] = _r(PASS, "retries owned by Run Lane")
    elif direct_runs:
        el["FW-R1"] = (
            _r(PARTIAL, "legacy retryOnFail on HTTP nodes; not Run Lane")
            if retry_http
            else _r(FAIL, "no retry: direct POST /run without retryOnFail or Run Lane")
        )
    elif http:
        el["FW-R1"] = (
            _r(PASS, "transport retries on every HTTP node (no lane run)")
            if retry_http
            else _r(FAIL, "HTTP node(s) without retryOnFail")
        )
    else:
        el["FW-R1"] = _r(NA, "no host call")
    el["FW-R2"] = (
        _r(PASS, "runs go to the executor: ledger breakers + dead_letters (half-open P, WS1-05)")
        if runs
        else _r(NA, "requests no lane run")
    )
    el["FW-R3"] = (
        _r(PASS, f"rollback: {fw['rollback']}") if fw.get("rollback") else _r(FAIL, "no declared fallback in metadata")
    )
    rb = fw.get("runbook_path")
    if rb and (ctx.root / str(rb)).exists():
        el["FW-R5"] = _r(PASS, f"runbook {rb}")
    elif rb:
        el["FW-R5"] = _r(FAIL, f"runbook_path {rb} does not exist")
    elif el["FW-A6"]["status"] == PARTIAL:
        el["FW-R5"] = _r(PARTIAL, "runbook ids come from the intent route table only")
    else:
        el["FW-R5"] = _r(FAIL, "no runbook")
    live = stage in ("canary", "cutover") or entry.get("mode") == "live"
    if not runs:
        el["FW-R6"] = _r(NA, "requests no lane run")
    elif not lanes:
        el["FW-R6"] = _r(NA, "lanes come from /due; the executor applies effect keys per lane")
    elif not live:
        el["FW-R6"] = _r(PASS, f"stage {stage or 'shadow'}: dry runs claim no effect key")
    else:
        miss = [x for x in lanes if x not in ctx.effect_lanes]
        el["FW-R6"] = (
            _r(PASS, "every live lane listed in config/n8n_effect_keys.json")
            if not miss
            else _r(FAIL, f"live lane(s) without an effect key: {miss}")
        )

    # Security ------------------------------------------------------------------------------------------------
    bad_auth = []
    for n in http:
        cred = (n.get("credentials") or {}).get("httpHeaderAuth") or {}
        if (
            cred.get("name") != ctx.credential_name
            or (n.get("parameters") or {}).get("genericAuthType") != "httpHeaderAuth"
        ):
            bad_auth.append(n.get("name"))
    for n in _of_type(wf, "webhook"):
        cred = (n.get("credentials") or {}).get("httpHeaderAuth") or {}
        if not cred:
            bad_auth.append(n.get("name"))
    if not http and not _of_type(wf, "webhook"):
        el["FW-S1"] = (
            _r(PASS, "no inbound or outbound HTTP surface") if uses_run_lane or wf.get("nodes") else _r(NA, "empty")
        )
    else:
        el["FW-S1"] = (
            _r(PASS, f"relay credential {ctx.credential_name} on every HTTP node; webhooks header-auth")
            if not bad_auth
            else _r(FAIL, f"node(s) without relay header auth: {bad_auth}")
        )
    unknown_lanes = [x for x in lanes if x not in ctx.allowlist_lanes]
    unknown_routes = sorted({f"{m} {p}" for m, p in calls if (m, p) not in ctx.relay_routes})
    if unknown_lanes or unknown_routes:
        el["FW-S2"] = _r(
            FAIL,
            "; ".join(
                ([f"lane(s) not in the run allowlist: {unknown_lanes}"] if unknown_lanes else [])
                + ([f"route(s) not served by the relay: {unknown_routes}"] if unknown_routes else [])
            ),
        )
    else:
        el["FW-S2"] = _r(PASS, f"{len(lanes)} lane(s) allowlisted; {len(calls)} relay call(s) in ROUTES")
    creds = sorted({(t, (c or {}).get("name")) for n in _nodes(wf) for t, c in (n.get("credentials") or {}).items()})
    other = [c for c in creds if c != ("httpHeaderAuth", ctx.credential_name)]
    params_text = json.dumps([n.get("parameters") for n in _nodes(wf)])
    leaks = [r.pattern for r in _SECRET_RES if r.search(params_text)]
    el["FW-S3"] = (
        _r(FAIL, f"credential(s) other than the relay's: {other}")
        if other
        else _r(FAIL, f"secret-like literal in parameters ({leaks})")
        if leaks
        else _r(PASS, "only the relay credential; no secret literal")
    )
    types = sorted({str(n.get("type")) for n in _nodes(wf)})
    forbidden = [t for t in types if t in ctx.forbidden_node_types]
    unlisted = [t for t in types if t not in ctx.allowed_node_types]
    el["FW-S4"] = (
        _r(FAIL, f"forbidden node type(s): {forbidden}")
        if forbidden
        else _r(FAIL, f"node type(s) outside the fabric allowlist: {unlisted}")
        if unlisted
        else _r(PASS, f"{len(types)} node types, all allowed")
    )

    # AI / LLM governance ---------------------------------------------------------------------------------------
    for eid in ("FW-G1", "FW-G2", "FW-G3", "FW-G4", "FW-G5", "FW-G6", "FW-G7"):
        el[eid] = _r(NA, "no LLM step")
    if is_ai:
        _score_llm(el, llm_steps, ctx)

    areas: dict[str, dict] = {}
    for area in AREAS:
        ids = [k for k, (a, _) in ELEMENTS.items() if a == area]
        scored = [el[k]["status"] for k in ids if el[k]["status"] != NA]
        if not scored:
            verdict = NA
        elif all(s == PASS for s in scored):
            verdict = "Y"
        elif any(s in (PASS, PARTIAL) for s in scored):
            verdict = "P"
        else:
            verdict = "N"
        areas[area] = {"verdict": verdict, "points": sum(POINTS[s] for s in scored), "of": len(scored)}
    points = sum(a["points"] for a in areas.values())
    of = sum(a["of"] for a in areas.values())
    return {
        "id": wid,
        "name": wf.get("name"),
        "file": file,
        "class": wclass,
        "class_source": "meta.framework"
        if fw.get("class") in CLASSES
        else ("active set" if entry.get("class") else None),
        "stage": stage,
        "mode": entry.get("mode"),
        "contract": (contract or {}).get("id"),
        "contract_source": contract_src,
        "elements": {k: dict(v, area=ELEMENTS[k][0], title=ELEMENTS[k][1]) for k, v in el.items()},
        "areas": areas,
        "score": {"points": points, "of": of, "pct": round(100.0 * points / of, 1) if of else None},
        "failing": [k for k, v in el.items() if v["status"] == FAIL],
    }


def _score_llm(el: dict, steps: list[dict], ctx: Context) -> None:
    if not steps:
        for eid in ("FW-G1", "FW-G2", "FW-G3", "FW-G4", "FW-G5", "FW-G6", "FW-G7"):
            el[eid] = _r(FAIL, "AI workflow declares no meta.framework.llm_steps")
        return

    def every(pred, ok: str, bad: str) -> dict:
        miss = [s.get("node") for s in steps if not pred(s)]
        return _r(PASS, ok) if not miss else _r(FAIL, f"{bad}: {miss}")

    el["FW-G1"] = every(
        lambda s: s.get("template_id") in ctx.prompt_templates,
        "templates registered",
        "template not in config/n8n_prompt_templates.json",
    )
    el["FW-G2"] = every(
        lambda s: s.get("process_id") in ctx.llm_processes,
        "processes registered",
        "process not in config/llm_process_registry.json",
    )
    el["FW-G3"] = every(
        lambda s: (ctx.llm_processes.get(s.get("process_id")) or {}).get("daily_cost_cap_usd") is not None,
        "per-process cost caps",
        "process without daily_cost_cap_usd",
    )
    el["FW-G4"] = every(
        lambda s: s.get("output_schema_id") in ctx.llm_schemas,
        "closed output schemas",
        "schema not in config/schemas/n8n_llm_step_outputs.json",
    )
    el["FW-G5"] = every(
        lambda s: bool(s.get("branch_fields")), "branches on enumerated fields", "no enumerated branch fields"
    )
    el["FW-G6"] = every(
        lambda s: s.get("offpeak_tier") in ("critical", "standard", "deferred"),
        "deferral tier declared",
        "no offpeak_tier",
    )
    el["FW-G7"] = every(lambda s: s.get("hitl") in ("none", "approval_request"), "HITL declared", "no hitl")


def score_platform(facts: Mapping) -> dict:
    f = {k: (v or {}).get("value") for k, v in (facts.get("facts") or {}).items()}
    ev = {k: (v or {}).get("evidence") for k, v in (facts.get("facts") or {}).items()}
    out = {
        "FW-P1": (
            PASS if f.get("executions_save_on_success_default") == "all" else FAIL,
            ev.get("executions_save_on_success_default"),
        ),
        "FW-P2": (FAIL if f.get("n8n_db_role_superuser") is not False else PASS, ev.get("n8n_db_role_superuser")),
        "FW-P3": (PASS if f.get("drift_check_scheduled") else FAIL, ev.get("drift_check_scheduled")),
        "FW-P4": (PASS if f.get("relay_bind_firewall_verified") else FAIL, ev.get("relay_bind_firewall_verified")),
        "FW-P5": (
            PASS
            if (f.get("image_pinned") and f.get("block_env_access_in_node") and f.get("community_packages_disabled"))
            else FAIL,
            "; ".join(
                str(ev.get(k)) for k in ("image_pinned", "block_env_access_in_node", "community_packages_disabled")
            ),
        ),
        "FW-P6": (PASS if f.get("host_dead_man_outside_n8n") else FAIL, ev.get("host_dead_man_outside_n8n")),
    }
    return {k: {"status": s, "title": PLATFORM_ELEMENTS[k], "evidence": e} for k, (s, e) in out.items()}


# ---------------------------------------------------------------------------------------------------------------
# selection + report


def committed_workflow_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for d in (WORKFLOWS_DIR, FABRIC_DIR, PER_LANE_DIR, PER_LANE_DIR / "pending", REFERENCE_DIR):
        p = root / d
        if p.is_dir():
            files += sorted(
                f for f in p.glob("*.json") if f.name != "INDEX.json" and not f.name.endswith(".health_contract.json")
            )
    return files


def build_report(
    targets: Iterable[tuple[Path, Mapping | None]], ctx: Context, platform: Mapping | None, *, source: str
) -> dict:
    rows = []
    for path, entry in targets:
        wf = _load(path)
        rows.append(score_workflow(wf, ctx, entry=entry, file=_rel(path, ctx.root)))
    pts = sum(r["score"]["points"] for r in rows)
    of = sum(r["score"]["of"] for r in rows)
    fleet_areas = {}
    for area in AREAS:
        verdicts = [r["areas"][area]["verdict"] for r in rows]
        fleet_areas[area] = {v: verdicts.count(v) for v in ("Y", "P", "N", NA)}
    return {
        "schema": REPORT_SCHEMA,
        "source": source,
        "authority": "READ_ONLY_ADVISORY",
        "elements": {k: {"area": a, "title": t} for k, (a, t) in ELEMENTS.items()},
        "workflows": rows,
        "platform": score_platform(platform) if platform else None,
        "fleet": {
            "workflows": len(rows),
            "fully_compliant": sum(
                1 for r in rows if not r["failing"] and all(a["verdict"] in ("Y", NA) for a in r["areas"].values())
            ),
            "points": pts,
            "of": of,
            "pct": round(100.0 * pts / of, 1) if of else None,
            "areas": fleet_areas,
            "failing_elements": sum(len(r["failing"]) for r in rows),
        },
    }


def render_markdown(report: Mapping) -> str:
    short = {
        "scope": "Scope",
        "monitoring": "Mon",
        "alerting": "Alert",
        "logging": "Log",
        "recovery": "Recov",
        "security": "Sec",
        "ai_llm": "AI",
    }
    lines = [
        f"Framework report ({report['schema']}) — source: {report['source']}",
        "",
        "| Workflow | Class | " + " | ".join(short[a] for a in AREAS) + " | Score | Failing elements |",
        "|---|---|" + "---|" * len(AREAS) + "---:|---|",
    ]
    for r in report["workflows"]:
        cells = [f"{r['areas'][a]['verdict']}" for a in AREAS]
        s = r["score"]
        lines.append(
            f"| `{r['name'] or r['id']}` | {r['class'] or '—'} | "
            + " | ".join(cells)
            + f" | {s['points']:g}/{s['of']} ({s['pct']}%) | {', '.join(r['failing']) or '—'} |"
        )
    f = report["fleet"]
    lines += [
        "",
        f"**Fleet:** {f['workflows']} workflows, {f['fully_compliant']} fully compliant, "
        f"{f['points']:g}/{f['of']} = {f['pct']}%; {f['failing_elements']} failing elements.",
    ]
    if report.get("platform"):
        lines += ["", "| Platform element | Status | Evidence |", "|---|---|---|"]
        for k, v in report["platform"].items():
            lines.append(f"| {k} {v['title']} | {v['status']} | {v['evidence']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--active", default=str(DEFAULT_ACTIVE), help="N8nActiveWorkflowSet@v1 file (default scope)")
    ap.add_argument("--all", action="store_true", help="score every committed workflow file instead")
    ap.add_argument("--workflow", nargs="+", default=None, help="score these workflow JSON files")
    ap.add_argument("--platform-facts", default=str(DEFAULT_PLATFORM))
    ap.add_argument("--json", action="store_true", help="print the JSON report instead of markdown")
    ap.add_argument("--out", default=None, help="also write the JSON report here")
    ap.add_argument("--markdown", default=None, help="also write the markdown summary here")
    ap.add_argument("--strict", action="store_true", help="exit 1 when any workflow element fails")
    a = ap.parse_args(argv)
    try:
        ctx = build_context(ROOT)
        platform = _load(Path(a.platform_facts)) if a.platform_facts and Path(a.platform_facts).exists() else None
        if a.workflow:
            targets = [(Path(p), None) for p in a.workflow]
            source = "files: " + ", ".join(a.workflow)
        elif a.all:
            targets = [(p, None) for p in committed_workflow_files(ROOT)]
            source = "every committed workflow file"
        else:
            active = _load(Path(a.active))
            if active.get("schema") != ACTIVE_SET_SCHEMA:
                raise ValueError(f"{a.active}: not {ACTIVE_SET_SCHEMA}")
            targets = [(ROOT / w["file"], w) for w in active.get("workflows") or []]
            source = f"{a.active} (as_of {active.get('as_of')})"
        report = build_report(targets, ctx, platform, source=source)
    except (OSError, ValueError, KeyError) as exc:
        print(f"check_n8n_workflow_framework: cannot read input: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    md = render_markdown(report)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    if a.markdown:
        Path(a.markdown).write_text(md, encoding="utf-8")
    print(text if a.json else md, end="")
    if a.strict and any(r["failing"] for r in report["workflows"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
