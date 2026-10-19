#!/usr/bin/env python3
"""check_n8n_workflow_framework.py — STATIC CONFORMANCE of n8n workflows to the AGENTS.md §23.24 framework.

Offline and read-only. Reads the committed workflow JSON (generic set, fabric set, per-lane set, reference set),
their generator manifests and a fresh in-process render of each generator, ``config/n8n_health_contracts.json``
(or a contract named by the workflow's ``meta.framework.health_contract_ref``), ``config/n8n_run_allowlist.json``,
``config/n8n_effect_keys.json``, ``config/n8n_retry_policies.json``, ``config/lane_registry.json``, the LLM
registries, the relay route table (``scripts/n8n_run_relay.py`` ``ROUTES``), the generator's node-type policy and,
for the platform elements, a cited platform-facts file. Writes nothing unless ``--out`` / ``--markdown`` name a file.

What the number means (third-party audit 2026-10-15, DD09/DD15/DD16): the per-workflow percentage is **static
conformance** — the share of the offline predicates in the element catalogue
(docs/architecture/n8n/N8N_CONTRACTS_DESIGN.md §12) that the committed artifact satisfies. It is NOT operational
maturity: it does not prove that a run succeeded, that an effect was safe, that recovery works or that the deployed
copy equals the committed one. Every §23.24 obligation is mapped in ``OBLIGATIONS`` to a static element, a platform
fact, or ``not_checkable_offline`` with the evidence that would prove it; the latter are reported per workflow as
``UNPROVEN`` until runtime evidence is supplied (``--runtime-evidence``). Each workflow row carries five separate
fields: ``artifact_integrity``, ``design_coverage`` (= the static score), ``deployed_parity``, ``runtime_outcome``
and ``activation_eligibility``.

Structural checks stand on the graph alone (FW-W1..W4): connections reference real nodes, every node is reachable
from a trigger, the Run Lane call / error route / refusal branch lie on a trigger path, and the metadata matches the
graph. A manifest hash or ``meta.graph_sha256`` match never substitutes for them (a hand edit can re-stamp both);
FW-L5 compares the file with a fresh render of its generator, not with the manifest.

    python3 scripts/check_n8n_workflow_framework.py                    # active set, markdown summary to stdout
    python3 scripts/check_n8n_workflow_framework.py --json             # N8nWorkflowFrameworkReport@v2
    python3 scripts/check_n8n_workflow_framework.py --all              # every committed workflow
    python3 scripts/check_n8n_workflow_framework.py --workflow PATH    # one or more files
    python3 scripts/check_n8n_workflow_framework.py --strict           # exit 1 if any workflow element FAILS
    python3 scripts/check_n8n_workflow_framework.py --gate activation [--runtime-evidence F] [--exceptions F]
                                                                       # FAIL-CLOSED promotion gate (DD16)

``--strict`` is a CI lint (workflow FAIL only). ``--gate activation`` is the promotion gate: it exits 1 unless every
workflow has no FAIL, no PARTIAL on a critical element, every platform element PASS, and evidence for every runtime
obligation that applies. Runtime v2 requires authenticated host evidence; v1 references remain historical
and unverified exceptions cannot waive a control. Offline, without trusted evidence, nothing is eligible.

Exit: 0 report; 1 ``--strict`` and a workflow element failed, or ``--gate`` and a workflow is not eligible; 2 an
input could not be read. AUTHORITY: READ_ONLY_ADVISORY. No n8n, no relay, no gateway, no DB, no send.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import re
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

REPORT_SCHEMA = "N8nWorkflowFrameworkReport@v2"
META_SCHEMA = "N8nWorkflowFrameworkMeta@v1"
EXPECTED_OUTPUT_SCHEMA = "N8nExpectedOutput@v1"
ACTIVE_SET_SCHEMA = "N8nActiveWorkflowSet@v1"
PLATFORM_FACTS_SCHEMA = "N8nPlatformFacts@v1"
EXCEPTIONS_SCHEMA = "N8nFrameworkExceptions@v1"
RUNTIME_EVIDENCE_SCHEMA = "N8nFrameworkRuntimeEvidence@v2"
LEGACY_RUNTIME_EVIDENCE_SCHEMA = "N8nFrameworkRuntimeEvidence@v1"
MEASURE = "static_conformance"
MEASURE_NOTE = (
    "static conformance: the share of offline predicates the committed artifact satisfies; not operational "
    "maturity, not runtime success, not deployed parity"
)

CLASSES = ("business-critical", "resilience", "ai-llm", "monitoring-compliance")
STAGES = ("shadow", "canary", "cutover")
EXPECTED_OUTPUT_RULES = ("min_produced", "per_window", "empty_allowed")
#: Closed vocabularies of the expected-output rule (N8nExpectedOutput@v1). A reason outside them is refused.
FATAL_SKIP_REASONS = frozenset(
    {
        "no_runner",
        "no_credentials",
        "disabled",
        "unconfigured",
        "universe_empty_unexpected",
        "no_input_unexpected",
        "upstream_stale",
        "dependency_unavailable",
    }
)
EMPTY_ALLOWED_REASONS = frozenset({"market_closed", "holiday", "no_new_input", "nothing_due", "window_not_reached"})
EVIDENCE_KINDS = frozenset({"store_rows", "receipt_field", "ledger_row", "file_artifact"})
EXPECTED_OUTPUT_KEYS = frozenset(
    {
        "schema",
        "unit",
        "rule",
        "min_produced",
        "window_h",
        "produced_field",
        "fatal_skip_reasons",
        "empty_allowed_reasons",
        "evidence",
        "applies_to",
        "on_violation",
    }
)
MAX_WINDOW_H = 24 * 31
_FIELD_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
PASS, PARTIAL, FAIL, NA = "pass", "partial", "fail", "n/a"
POINTS = {PASS: 1.0, PARTIAL: 0.5, FAIL: 0.0}
UNPROVEN, EVIDENCED = "UNPROVEN", "EVIDENCED"

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
LANE_REGISTRY = Path("config/lane_registry.json")
INCIDENT_RUNBOOK = Path("docs/runbooks/INCIDENT_RESPONSE.md")

AREAS = ("structure", "scope", "monitoring", "alerting", "logging", "recovery", "security", "ai_llm")
ELEMENTS: dict[str, tuple[str, str]] = {
    "FW-W1": ("structure", "connections reference existing nodes; node names unique"),
    "FW-W2": ("structure", "every node reachable from a trigger (none disabled)"),
    "FW-W3": ("structure", "required nodes on a trigger path: run request, result routing, error route"),
    "FW-W4": ("structure", "metadata matches the graph (lanes, effect process, LLM nodes, manifest claims)"),
    "FW-C1": ("scope", "class declared in generator metadata"),
    "FW-C2": ("scope", "owner declared in generator metadata"),
    "FW-C3": ("scope", "health contract bound to this workflow (REVIEWED for business-critical / AI)"),
    "FW-M1": ("monitoring", "success evidence: saved + run_id carried on a reachable path (join itself is runtime)"),
    "FW-M2": ("monitoring", "failure: settings.errorWorkflow"),
    "FW-M3": ("monitoring", "performance: executionTimeout + contract duration bound"),
    "FW-M4": ("monitoring", "capacity: contract class under executor class caps"),
    "FW-M5": ("monitoring", "dependency: connects_to names every graph dependency"),
    "FW-M6": ("monitoring", "expected output: closed executable rule (exit 0 with nothing produced is a failure)"),
    "FW-A1": ("alerting", "failure routed to the incident path"),
    "FW-A2": ("alerting", "SLA breach: freshness bound + priority"),
    "FW-A3": ("alerting", "performance degradation: duration bound + slow check"),
    "FW-A4": ("alerting", "integration failure: refusals routed as data, never to an error"),
    "FW-A5": ("alerting", "AI/LLM exception branch wired from the LLM node"),
    "FW-A6": ("alerting", "runbook id resolves to a runbook"),
    "FW-L1": ("logging", "execution: successes saved"),
    "FW-L2": ("logging", "error: failures saved"),
    "FW-L4": ("logging", "security: every HTTP node addressed to the approved relay origin"),
    "FW-L5": ("logging", "change: byte-equal to a fresh render of its generator"),
    "FW-R1": ("recovery", "retry has one owner"),
    "FW-R2": ("recovery", "breaker / dead letter (executor-owned)"),
    "FW-R3": ("recovery", "fallback declared and resolvable"),
    "FW-R5": ("recovery", "manual recovery runbook resolves and names the runbook id"),
    "FW-R6": ("recovery", "idempotency: effect key ARMED for live lanes; effect_process real"),
    "FW-S1": ("security", "authN: effective relay header auth on every HTTP node / webhook"),
    "FW-S2": ("security", "authZ: allowlisted lanes, served relay routes, parseable URLs"),
    "FW-S3": ("security", "secrets: exactly the relay credential; no secret literal; no $env"),
    "FW-S4": ("security", "node types inside the fabric allowlist"),
    "FW-G1": ("ai_llm", "prompt: registered template bound to the step's process, referenced by the node"),
    "FW-G2": ("ai_llm", "model selection: registered process id only, no model/provider in the node"),
    "FW-G3": ("ai_llm", "cost: per-process caps declared"),
    "FW-G4": ("ai_llm", "response validation: closed output schema registered for the process"),
    "FW-G5": ("ai_llm", "branches on enumerated schema decision fields only"),
    "FW-G6": ("ai_llm", "deferral tier declared (off-peak rule; NOT the §23.24 AI(6) output guardrail)"),
    "FW-G7": ("ai_llm", "HITL declared; an approval gate needs a served approval route on the path"),
}
#: A PARTIAL on one of these blocks the activation gate (a FAIL on any element always blocks).
CRITICAL_ELEMENTS = frozenset(
    {"FW-W1", "FW-W2", "FW-W3", "FW-W4", "FW-C3", "FW-M2", "FW-M6", "FW-A1", "FW-A4", "FW-L5", "FW-R6"}
    | {"FW-S1", "FW-S2", "FW-S3", "FW-S4"}
    | {f"FW-G{i}" for i in range(1, 8)}
)
PLATFORM_ELEMENTS: dict[str, str] = {
    "FW-P1": "instance saves successful executions (FW-M1/L1 need it per workflow until it does)",
    "FW-P2": "n8n DB role is not superuser (§23.24 Logging (3), Security audit trail)",
    "FW-P3": "drift check runs on a host schedule and pages P1 (§23.24 Logging (5))",
    "FW-P4": "relay docker-bridge bind is firewalled (§23.24 Security (4))",
    "FW-P5": "image pinned by digest, env access blocked in nodes, community packages off (§23.24 Security (3))",
    "FW-P6": "a dead-man outside n8n watches n8n (§23.23 Independence; §23.24 Alerting (2))",
}

# §23.24 line by line (AGENTS.md 11.0.0). kind: static (scored element), platform (instance fact, reported, gated),
# not_checkable_offline (UNPROVEN until the named evidence exists; never PASS offline). applies: all | runs | ai.
OBLIGATIONS: list[dict] = [
    {
        "id": "23.24-SC1",
        "area": "scope",
        "text": "every workflow in m8m-n8n is in scope (inventory complete)",
        "kind": "not_checkable_offline",
        "applies": "fleet",
        "evidence": "live SELECT of workflow_entity (id, active) equal to the scored active set",
    },
    {
        "id": "23.24-SC2",
        "area": "scope",
        "text": "one class in generator metadata",
        "kind": "static",
        "elements": ["FW-C1"],
    },
    {"id": "23.24-SC3", "area": "scope", "text": "one owner", "kind": "static", "elements": ["FW-C2"]},
    {
        "id": "23.24-SC4",
        "area": "scope",
        "text": "BC/AI need a REVIEWED health contract before leaving shadow",
        "kind": "static",
        "elements": ["FW-C3"],
    },
    {
        "id": "23.24-SC5",
        "area": "scope",
        "text": "relay routes, lanes, LLM steps and approvals it calls are in scope",
        "kind": "static",
        "elements": ["FW-S2", "FW-W4", "FW-G7"],
    },
    {
        "id": "23.24-M1a",
        "area": "monitoring",
        "text": "every run joins a host ledger receipt by run_id",
        "kind": "not_checkable_offline",
        "applies": "runs",
        "evidence": "ledger runs rows joined to n8n execution custom data run_id for the window (no orphan either side)",
    },
    {
        "id": "23.24-M1b",
        "area": "monitoring",
        "text": "successful executions saved with run_id custom data",
        "kind": "static",
        "elements": ["FW-M1", "FW-L1"],
    },
    {
        "id": "23.24-M1c",
        "area": "monitoring",
        "text": "instance saves successes",
        "kind": "platform",
        "elements": ["FW-P1"],
    },
    {
        "id": "23.24-M2",
        "area": "monitoring",
        "text": "settings.errorWorkflow set",
        "kind": "static",
        "elements": ["FW-M2"],
    },
    {
        "id": "23.24-M3a",
        "area": "monitoring",
        "text": "executionTimeout + contract duration bound",
        "kind": "static",
        "elements": ["FW-M3"],
    },
    {
        "id": "23.24-M3b",
        "area": "monitoring",
        "text": "p95 duration measured against the contract bound",
        "kind": "not_checkable_offline",
        "applies": "all",
        "evidence": "p95 of execution durations over the contract window, from saved executions or ledger runs",
    },
    {
        "id": "23.24-M4a",
        "area": "monitoring",
        "text": "run class has an executor class cap",
        "kind": "static",
        "elements": ["FW-M4"],
    },
    {
        "id": "23.24-M4b",
        "area": "monitoring",
        "text": "start lag measured; caps actually enforced",
        "kind": "not_checkable_offline",
        "applies": "runs",
        "evidence": "executor receipts with admitted_at - requested_at, and a cap-refusal row under load",
    },
    {
        "id": "23.24-M5",
        "area": "monitoring",
        "text": "connects_to names every route and store",
        "kind": "static",
        "elements": ["FW-M5"],
    },
    {
        "id": "23.24-M5b",
        "area": "monitoring",
        "text": "stores written by the lane are all named",
        "kind": "not_checkable_offline",
        "applies": "runs",
        "evidence": "lane receipt store list (LaneRunReceipt@v2) compared with connects_to",
    },
    {
        "id": "23.24-M6",
        "area": "monitoring",
        "text": "exit 0 with nothing produced is a failure (operator 2026-10-15)",
        "kind": "static",
        "elements": ["FW-M6"],
    },
    {
        "id": "23.24-M6b",
        "area": "monitoring",
        "text": "an empty success fails the run at the host",
        "kind": "not_checkable_offline",
        "applies": "runs",
        "evidence": "RunReceipt with output_verdict empty_output -> RUN_FAILED for a forced empty run",
    },
    {
        "id": "23.24-A1a",
        "area": "alerting",
        "text": "failure routed to the incident router / fan-in (design)",
        "kind": "static",
        "elements": ["FW-A1", "FW-W3"],
    },
    {
        "id": "23.24-A1b",
        "area": "alerting",
        "text": "a forced failure reaches the fan-in and an incident",
        "kind": "not_checkable_offline",
        "applies": "all",
        "evidence": "comms_intents / incident row for a forced failure execution id",
    },
    {
        "id": "23.24-A2a",
        "area": "alerting",
        "text": "freshness bound + priority in the contract",
        "kind": "static",
        "elements": ["FW-A2"],
    },
    {
        "id": "23.24-A2b",
        "area": "alerting",
        "text": "SLA breach watched by a monitor outside n8n",
        "kind": "platform",
        "elements": ["FW-P6"],
    },
    {
        "id": "23.24-A3a",
        "area": "alerting",
        "text": "duration bound + slow check declared",
        "kind": "static",
        "elements": ["FW-A3"],
    },
    {
        "id": "23.24-A3b",
        "area": "alerting",
        "text": "p95 over the bound raises a P2",
        "kind": "not_checkable_offline",
        "applies": "all",
        "evidence": "P2 incident row raised by a slow-run drill",
    },
    {
        "id": "23.24-A4",
        "area": "alerting",
        "text": "refusals routed by class; a policy refusal is data",
        "kind": "static",
        "elements": ["FW-A4"],
    },
    {
        "id": "23.24-A5",
        "area": "alerting",
        "text": "AI/LLM exception is a typed event",
        "kind": "static",
        "elements": ["FW-A5"],
    },
    {
        "id": "23.24-A5b",
        "area": "alerting",
        "text": "AI exception becomes a typed event, P1 on a BC stall",
        "kind": "not_checkable_offline",
        "applies": "ai",
        "evidence": "typed event row for a forced bridge refusal / cap hit on the step",
    },
    {
        "id": "23.24-A6",
        "area": "alerting",
        "text": "every page carries a runbook_id",
        "kind": "static",
        "elements": ["FW-A6"],
    },
    {
        "id": "23.24-A7",
        "area": "alerting",
        "text": "delivery stays with the host comms gateway (no send node)",
        "kind": "static",
        "elements": ["FW-S3", "FW-S4"],
    },
    {
        "id": "23.24-L1",
        "area": "logging",
        "text": "RunRequested/RunReceipt with requested_by n8n:workflow:<id>",
        "kind": "not_checkable_offline",
        "applies": "runs",
        "evidence": "ledger rows with schema RunRequested@v1/RunReceipt@v2 and requested_by = n8n:workflow:<id>",
    },
    {"id": "23.24-L2", "area": "logging", "text": "errors saved", "kind": "static", "elements": ["FW-L2"]},
    {
        "id": "23.24-L3",
        "area": "logging",
        "text": "ledger is the audit of record; n8n DB role not superuser",
        "kind": "platform",
        "elements": ["FW-P2"],
    },
    {
        "id": "23.24-L3b",
        "area": "logging",
        "text": "ledger audit actually records each run",
        "kind": "not_checkable_offline",
        "applies": "runs",
        "evidence": "coordination ledger audit rows for the workflow's runs in the window",
    },
    {
        "id": "23.24-L4",
        "area": "logging",
        "text": "relay / CC auth refusals logged (all calls through the relay)",
        "kind": "static",
        "elements": ["FW-L4"],
    },
    {
        "id": "23.24-L4b",
        "area": "logging",
        "text": "auth refusals appear in relay_log.jsonl",
        "kind": "not_checkable_offline",
        "applies": "all",
        "evidence": "relay_log.jsonl refusal row for a bad-bearer probe",
    },
    {"id": "23.24-L5a", "area": "logging", "text": "generated from git", "kind": "static", "elements": ["FW-L5"]},
    {
        "id": "23.24-L5b",
        "area": "logging",
        "text": "deployed copy never edited in the UI (parity)",
        "kind": "not_checkable_offline",
        "applies": "all",
        "evidence": "N8nWorkflowDriftReceipt@v1 for this workflow id with no drift, from a host-scheduled read",
    },
    {
        "id": "23.24-L5c",
        "area": "logging",
        "text": "drift check scheduled outside n8n, pages P1",
        "kind": "platform",
        "elements": ["FW-P3"],
    },
    {"id": "23.24-R1", "area": "recovery", "text": "retry has one owner", "kind": "static", "elements": ["FW-R1"]},
    {
        "id": "23.24-R2a",
        "area": "recovery",
        "text": "breaker + dead letter (runs go to the executor)",
        "kind": "static",
        "elements": ["FW-R2"],
    },
    {
        "id": "23.24-R2b",
        "area": "recovery",
        "text": "breaker half-open behaviour",
        "kind": "not_checkable_offline",
        "applies": "runs",
        "evidence": "ledger breakers transition open -> half_open -> closed in a drill (WS1-05)",
    },
    {
        "id": "23.24-R3",
        "area": "recovery",
        "text": "declared fallback (cron line or ROLLBACK_COMMANDS)",
        "kind": "static",
        "elements": ["FW-R3"],
    },
    {
        "id": "23.24-R3b",
        "area": "recovery",
        "text": "fallback executed successfully",
        "kind": "not_checkable_offline",
        "applies": "all",
        "evidence": "rollback drill receipt (CutoverReceipt@v1 rollback) for the workflow",
    },
    {"id": "23.24-R4", "area": "recovery", "text": "dead-letter", "kind": "static", "elements": ["FW-R2"]},
    {
        "id": "23.24-R5",
        "area": "recovery",
        "text": "manual recovery runbook_id resolves",
        "kind": "static",
        "elements": ["FW-R5", "FW-A6"],
    },
    {
        "id": "23.24-R6a",
        "area": "recovery",
        "text": "semantic effect key armed for live work",
        "kind": "static",
        "elements": ["FW-R6"],
    },
    {
        "id": "23.24-R6b",
        "area": "recovery",
        "text": "both schedulers respect the key; owner row present",
        "kind": "not_checkable_offline",
        "applies": "runs",
        "evidence": "effect_owners row + an effect_already_claimed refusal for a duplicate fire",
    },
    {
        "id": "23.24-SEC1",
        "area": "security",
        "text": "authN: relay bearer / webhook header auth",
        "kind": "static",
        "elements": ["FW-S1"],
    },
    {
        "id": "23.24-SEC1b",
        "area": "security",
        "text": "bearer rotation slot + gateway HMAC claim enforced",
        "kind": "not_checkable_offline",
        "applies": "all",
        "evidence": "relay refusal for an old/forged bearer and gateway refusal for a bad HMAC claim",
    },
    {
        "id": "23.24-SEC2",
        "area": "security",
        "text": "authZ: allowlist + relay routes",
        "kind": "static",
        "elements": ["FW-S2"],
    },
    {
        "id": "23.24-SEC2b",
        "area": "security",
        "text": "one reconciled live authority (allowlist/relay/registry)",
        "kind": "not_checkable_offline",
        "applies": "runs",
        "evidence": "reconciler receipt (WS1-07) agreeing for every lane this workflow fires",
    },
    {
        "id": "23.24-SEC3",
        "area": "security",
        "text": "only the relay credential; no secret literal",
        "kind": "static",
        "elements": ["FW-S3", "FW-S4"],
    },
    {
        "id": "23.24-SEC3b",
        "area": "security",
        "text": "env access blocked, community packages off, pinned image",
        "kind": "platform",
        "elements": ["FW-P5"],
    },
    {
        "id": "23.24-SEC4",
        "area": "security",
        "text": "loopback / bridge binds; bridge bind firewalled",
        "kind": "platform",
        "elements": ["FW-P4"],
    },
    {
        "id": "23.24-SEC4b",
        "area": "security",
        "text": "ingested text treated as data",
        "kind": "not_checkable_offline",
        "applies": "ai",
        "evidence": "prompt-injection drill: injected instruction in facts yields no branch change",
    },
    {
        "id": "23.24-SEC5",
        "area": "security",
        "text": "activation grants name workflow ids",
        "kind": "not_checkable_offline",
        "applies": "all",
        "evidence": "scripts/check_n8n_activation_grants.py attribution row naming this workflow id",
    },
    {
        "id": "23.24-AI1",
        "area": "ai_llm",
        "text": "registered template, never an inline prompt",
        "kind": "static",
        "elements": ["FW-G1"],
    },
    {
        "id": "23.24-AI2",
        "area": "ai_llm",
        "text": "process id only; model/fallback from the registry",
        "kind": "static",
        "elements": ["FW-G2"],
    },
    {"id": "23.24-AI3", "area": "ai_llm", "text": "per-process caps declared", "kind": "static", "elements": ["FW-G3"]},
    {
        "id": "23.24-AI3b",
        "area": "ai_llm",
        "text": "caps enforced; consumption ledger rows",
        "kind": "not_checkable_offline",
        "applies": "ai",
        "evidence": "LlmStepAudit@v1 rows and an over_cap refusal under a cap drill",
    },
    {
        "id": "23.24-AI4",
        "area": "ai_llm",
        "text": "closed output schema; branches on enumerated fields only",
        "kind": "static",
        "elements": ["FW-G4", "FW-G5"],
    },
    {
        "id": "23.24-AI5",
        "area": "ai_llm",
        "text": "host re-checks recommended actions; numbers grounded",
        "kind": "not_checkable_offline",
        "applies": "ai",
        "evidence": "gateway re-check refusal for an out-of-catalogue action; grounding refusal for an unsupported number",
    },
    {
        "id": "23.24-AI6",
        "area": "ai_llm",
        "text": "output guardrails: behaviour-field + prompt-injection scans",
        "kind": "not_checkable_offline",
        "applies": "ai",
        "evidence": "bridge step-9b behaviour-field refusal and an output injection-scan refusal (P) for the process",
    },
    {
        "id": "23.24-AI7",
        "area": "ai_llm",
        "text": "HITL: side effects behind an approval request",
        "kind": "static",
        "elements": ["FW-G7"],
    },
    {
        "id": "23.24-AI7b",
        "area": "ai_llm",
        "text": "approval authority = host record; fail closed when n8n down",
        "kind": "not_checkable_offline",
        "applies": "ai",
        "evidence": "forged / expired / replayed approval refused before effect (DD13 fixtures) and n8n-down drill",
    },
    {
        "id": "23.24-BAR",
        "area": "activation",
        "text": "no activation/promotion unless every element passes or has an operator-accepted exception",
        "kind": "not_checkable_offline",
        "applies": "all",
        "evidence": "--gate activation exit 0 recorded by the import/activation packet, plus live active flag history",
    },
    {
        "id": "23.24-BAR2",
        "area": "activation",
        "text": "the check runs live (SELECT only) on a host schedule, receipt read by the fan-in",
        "kind": "not_checkable_offline",
        "applies": "fleet",
        "evidence": "host timer receipt of this checker in live mode read by scripts/n8n_incident_fanin.py",
    },
    {
        "id": "23.24-DEV",
        "area": "scope",
        "text": "extra: deferral tier (off-peak rule, not a §23.24 line)",
        "kind": "static",
        "elements": ["FW-G6"],
    },
    {
        "id": "23.24-STRUCT",
        "area": "scope",
        "text": "extra (audit DD09): graph validity — reachability, required nodes on a path, metadata = graph",
        "kind": "static",
        "elements": ["FW-W1", "FW-W2", "FW-W3", "FW-W4"],
    },
]

_SECRET_RES = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{8,}"),
    re.compile(r"(?i)postgres(?:ql)?://"),
    re.compile(r"(?<![A-Za-z])sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|password|passwd|secret|token)\b\s*[:=]\s*['\"][^'\"$]{8,}['\"]"),
)
_ENV_RE = re.compile(r"\$env\b|process\.env\b")
_RUN_BODY_IDS = ("workflow_id", "execution_id")
#: The only relay URL shapes: the relay base from a Set node, then a path. Anything else is not the relay.
_RELAY_URL_RE = re.compile(
    r"=\{\{\s*\$(?:\('Relay'\)\.first\(\)\.json|json)\.TRADEAI_N8N_RUN_URL\s*\}\}"
    r"(/(?!/)[A-Za-z0-9_./<>-]*)(\?.*)?",
    re.S,
)
_PROMPT_KEYS_RE = re.compile(r"\b(prompt|system|messages|user_template)\s*:")
_MODEL_KEYS_RE = re.compile(r"\b(model|provider|api_key|base_url)\s*:")
APPROVAL_ROUTE = ("POST", "/approval/request")
LLM_ROUTE = ("POST", "/llm_step")
REFUSAL_STATUSES = ("refused_policy", "skipped_lock")
FAILURE_STATUSES = ("failed",)


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
    #: repo-relative file -> text of a fresh in-process render by its generator (FW-L5)
    renders: dict[str, str] = field(default_factory=dict)
    #: lane -> {"process", "n8n_claim", "cron_claim"} (config/n8n_effect_keys.json; n8n_claim defaults True)
    effect_specs: dict[str, dict] = field(default_factory=dict)
    #: lane -> scheduler kind in config/lane_registry.json (cron = the cron line is the fallback)
    lane_schedulers: dict[str, str] = field(default_factory=dict)
    template_specs: dict[str, dict] = field(default_factory=dict)
    schema_specs: dict[str, dict] = field(default_factory=dict)
    relay_origins: frozenset[str] = frozenset({"http://RELAY_HOST:18092", "http://172.19.0.1:18092"})

    def __post_init__(self) -> None:
        for lane in self.effect_lanes:
            self.effect_specs.setdefault(lane, {"process": lane, "n8n_claim": True, "cron_claim": False})
        self.effect_lanes = set(self.effect_specs)
        for t in self.prompt_templates:
            self.template_specs.setdefault(t, {})
        self.prompt_templates = set(self.template_specs)
        for s in self.llm_schemas:
            self.schema_specs.setdefault(s, {})
        self.llm_schemas = set(self.schema_specs)


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
                        "_manifest": f"{PER_LANE_DIR}/INDEX.json ({doc.get('schema')})",
                    }
    return out


def fresh_renders() -> dict[str, str]:
    """repo-relative path -> text, rendered now by each generator in-process (independent of every manifest)."""
    import build_n8n_reference_workflow as REF  # noqa: PLC0415
    import n8n_workflow_templates as T  # noqa: PLC0415

    out: dict[str, str] = {}
    for d, files in (
        (WORKFLOWS_DIR, T.render_generic()),
        (FABRIC_DIR, T.render_fabric()),
        (PER_LANE_DIR, T.render(T.select_lanes("all"))),
        (REFERENCE_DIR, REF.render()),
    ):
        for name, text in files.items():
            if name != "INDEX.json":
                out[str(d / name)] = text
    return out


def build_context(root: Path = ROOT) -> Context:
    """The real repository context. Imports the generators and relay only for their constants and renders."""
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
        str(t.get("template_id") or t.get("id")): t for t in _load(root / PROMPT_TEMPLATES).get("templates") or []
    }
    schemas = dict(_load(root / LLM_SCHEMAS).get("schemas") or {})
    llm_procs = {str(p.get("id")): p for p in _load(root / LLM_PROCESSES).get("processes") or []}
    routes_doc = _load(root / "config" / "n8n_comms_intent_routes.json")
    intent_runbooks = {f"{r['domain']}:{r['kind']}": str(r.get("runbook_id")) for r in routes_doc.get("routes") or []}
    effect_specs = {
        str(lane): {
            "process": spec.get("process"),
            "n8n_claim": spec.get("n8n_claim", True) is True,
            "cron_claim": spec.get("cron_claim", False) is True,
        }
        for lane, spec in (effect.get("lanes") or {}).items()
        if isinstance(spec, dict)
    }
    reg = _load(root / LANE_REGISTRY)
    reg_lanes = reg.get("lanes") if isinstance(reg, dict) else reg
    rows = reg_lanes.values() if isinstance(reg_lanes, dict) else (reg_lanes or [])
    lane_schedulers = {
        str(r.get("lane_id")): str((r.get("scheduler") or {}).get("kind")) for r in rows if isinstance(r, dict)
    }
    return Context(
        root=root,
        contracts=contracts,
        allowlist_lanes={str(x.get("lane_id")) for x in allow.get("lanes") or []},
        effect_lanes=set(),
        effect_specs=effect_specs,
        class_caps=set((retry.get("class_caps") or {}).keys()) - {"global", "reserved_priority_max"},
        relay_routes=set(ROUTES),
        allowed_node_types=frozenset(T.FABRIC_ALLOWED_NODE_TYPES),
        forbidden_node_types=frozenset(T.FABRIC_FORBIDDEN_NODE_TYPES),
        credential_name=T.CREDENTIAL_NAME,
        run_lane_id=T.RUN_LANE_ID,
        error_workflow_ids=frozenset({T.FABRIC_ERROR_ID, T.INCIDENT_ROUTER_ID}),
        process_lanes=process_lanes,
        manifests=_manifest_rows(root),
        template_specs=templates,
        schema_specs=schemas,
        llm_processes=llm_procs,
        intent_runbooks=intent_runbooks,
        renders=fresh_renders(),
        lane_schedulers=lane_schedulers,
        relay_origins=frozenset({T.RELAY_URL_PLACEHOLDER, T.GENERIC_RELAY_URL}),
    )


# ---------------------------------------------------------------------------------------------------------------
# graph facts (independent of every manifest, hash and generator)


def _nodes(wf: Mapping) -> list[dict]:
    return [
        n for n in wf.get("nodes") or [] if isinstance(n, dict) and not str(n.get("type", "")).endswith(".stickyNote")
    ]


def _of_type(wf: Mapping, suffix: str, among: Iterable[dict] | None = None) -> list[dict]:
    pool = _nodes(wf) if among is None else list(among)
    return [n for n in pool if str(n.get("type", "")).endswith("." + suffix)]


def framework_meta(wf: Mapping) -> dict:
    meta = (wf.get("meta") or {}).get("framework")
    return meta if isinstance(meta, dict) else {}


def is_trigger(n: Mapping) -> bool:
    t = str(n.get("type", ""))
    return t.endswith("Trigger") or t.endswith(".webhook") or t.endswith(".cron") or t.endswith(".interval")


def edges(wf: Mapping) -> list[tuple[str, int, str]]:
    """(source, output index, target) for every connection of every connection type."""
    out = []
    for src, types in (wf.get("connections") or {}).items():
        if not isinstance(types, dict):
            out.append((str(src), 0, "<malformed>"))
            continue
        for outputs in types.values():
            for idx, conns in enumerate(outputs or []):
                for c in conns or []:
                    out.append((str(src), idx, str((c or {}).get("node")) if isinstance(c, dict) else "<malformed>"))
    return out


def _adjacency(wf: Mapping) -> dict[str, list[tuple[int, str]]]:
    adj: dict[str, list[tuple[int, str]]] = {}
    for src, idx, dst in edges(wf):
        adj.setdefault(src, []).append((idx, dst))
    return adj


def _bfs(adj: Mapping[str, list[tuple[int, str]]], starts: Iterable[str], blocked: set[str] = frozenset()) -> set[str]:
    seen: set[str] = set()
    q = deque(s for s in starts if s not in blocked)
    while q:
        cur = q.popleft()
        if cur in seen:
            continue
        seen.add(cur)
        for _, nxt in adj.get(cur, []):
            if nxt not in seen and nxt not in blocked:
                q.append(nxt)
    return seen


def reachable(wf: Mapping) -> set[str]:
    """Names reachable from a trigger, never passing through a disabled node."""
    nodes = _nodes(wf)
    disabled = {str(n.get("name")) for n in nodes if n.get("disabled") is True}
    return _bfs(_adjacency(wf), [str(n.get("name")) for n in nodes if is_trigger(n)], disabled)


def downstream(wf: Mapping, name: str, output: int | None = None) -> set[str]:
    adj = _adjacency(wf)
    firsts = [dst for idx, dst in adj.get(name, []) if output is None or idx == output]
    return _bfs(adj, firsts)


def throws(n: Mapping) -> bool:
    if str(n.get("type", "")).endswith(".stopAndError"):
        return True
    return bool(re.search(r"\bthrow\b", js_code(n)))


_JS_COMMENT_RE = re.compile(r"/\*.*?\*/|(?<![:\\])//[^\n]*", re.S)
_RUN_ID_SET_RE = re.compile(r"\$execution\.customData\.set\(\s*['\"]run_id['\"]")
_SUCCESS_LITERAL_RE = re.compile(r"status\s*:\s*['\"]success['\"]")


def js_code(n: Mapping) -> str:
    """A Code node's JavaScript with comments removed (a comment never counts as behaviour)."""
    return _JS_COMMENT_RE.sub("", str((n.get("parameters") or {}).get("jsCode") or ""))


def relay_route(n: Mapping) -> tuple[str, str] | None:
    """(METHOD, route) of an HTTP node addressed to the relay origin, or None when the URL is not that shape."""
    p = n.get("parameters") or {}
    m = _RELAY_URL_RE.fullmatch(str(p.get("url") or ""))
    if not m or ".." in m.group(1):
        return None
    path = m.group(1)
    if re.fullmatch(r"/runs/[^/]+/last", path):
        path = "/runs/<lane_id>/last"
    return str(p.get("method") or "GET").upper(), path


def relay_calls(wf: Mapping, among: Iterable[dict] | None = None) -> list[tuple[str, str]]:
    """(METHOD, route) for every HTTP node; an unparseable URL is reported as its literal (never a relay route)."""
    out = []
    for n in _of_type(wf, "httpRequest", among):
        r = relay_route(n)
        out.append(
            r
            if r
            else (
                str((n.get("parameters") or {}).get("method") or "GET").upper(),
                f"<not relay> {str((n.get('parameters') or {}).get('url'))[:80]}",
            )
        )
    return out


def relay_origin_values(wf: Mapping) -> list[str]:
    vals = []
    for n in _nodes(wf):
        for a in ((n.get("parameters") or {}).get("assignments") or {}).get("assignments") or []:
            if isinstance(a, dict) and a.get("name") == "TRADEAI_N8N_RUN_URL":
                vals.append(str(a.get("value")))
    return vals


def run_lane_nodes(wf: Mapping, run_lane_id: str) -> list[dict]:
    return [
        n
        for n in _of_type(wf, "executeWorkflow")
        if ((n.get("parameters") or {}).get("workflowId") or {}).get("value") == run_lane_id
    ]


def calls_run_lane(wf: Mapping, run_lane_id: str) -> bool:
    return bool(run_lane_nodes(wf, run_lane_id))


def direct_run_nodes(wf: Mapping) -> list[dict]:
    return [n for n in _of_type(wf, "httpRequest") if relay_route(n) == ("POST", "/run")]


def llm_nodes(wf: Mapping) -> list[dict]:
    return [n for n in _of_type(wf, "httpRequest") if relay_route(n) == LLM_ROUTE]


def requests_runs(wf: Mapping, ctx: Context) -> bool:
    return wf.get("id") == ctx.run_lane_id or calls_run_lane(wf, ctx.run_lane_id) or bool(direct_run_nodes(wf))


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


def _switch_outputs(n: Mapping) -> dict[int, str]:
    p = n.get("parameters") or {}
    vals = ((p.get("rules") or {}).get("values")) or []
    out: dict[int, str] = {}
    for i, r in enumerate(vals):
        key = r.get("outputKey")
        if not key:
            conds = ((r.get("conditions") or {}).get("conditions")) or [{}]
            key = conds[0].get("rightValue")
        out[i] = str(key)
    if (p.get("options") or {}).get("fallbackOutput") == "extra":
        out[len(vals)] = "<fallback>"
    return out


def run_result_routing(wf: Mapping, ctx: Context, live: set[str]) -> dict:
    """How the result of a reachable Run Lane call is routed. Only a Switch on ``status`` downstream of the call
    counts. Refusals must reach no throwing node; a failure (and the fallback) must reach one (error route)."""
    by_name = {str(n.get("name")): n for n in _nodes(wf)}
    calls = [str(n.get("name")) for n in run_lane_nodes(wf, ctx.run_lane_id) if str(n.get("name")) in live]
    if not calls:
        return {"routed": False, "reason": "no Run Lane call on a trigger path"}
    after = set().union(*(downstream(wf, c) for c in calls))
    switches = [
        by_name[s]
        for s in sorted(after)
        if s in by_name
        and str(by_name[s].get("type", "")).endswith(".switch")
        and "status" in json.dumps(by_name[s].get("parameters") or {})
    ]
    if not switches:
        return {"routed": False, "reason": "the Run Lane result is not routed by a Switch on status"}
    sw = switches[0]
    name = str(sw.get("name"))
    outs = _switch_outputs(sw)
    keys = {v: k for k, v in outs.items()}
    refusal_bad, refusal_missing = [], []
    for st in REFUSAL_STATUSES:
        if st not in keys:
            refusal_missing.append(st)
            continue
        reach = downstream(wf, name, keys[st])
        if not reach:
            refusal_missing.append(st)
        elif any(throws(by_name[x]) for x in reach if x in by_name):
            refusal_bad.append(st)
    failure_ok = all(
        st in keys and any(throws(by_name[x]) for x in downstream(wf, name, keys[st]) if x in by_name)
        for st in FAILURE_STATUSES
    )
    fabricated = []
    if "success" in keys:
        for x in sorted(downstream(wf, name, keys["success"])):
            n = by_name.get(x) or {}
            if str(n.get("type", "")).endswith(".code") and _SUCCESS_LITERAL_RE.search(js_code(n)):
                fabricated.append(x)
    fallback_ok = "<fallback>" not in keys or any(
        throws(by_name[x]) for x in downstream(wf, name, keys["<fallback>"]) if x in by_name
    )
    return {
        "routed": True,
        "switch": name,
        "refusal_to_error": refusal_bad,
        "refusal_unrouted": refusal_missing,
        "failure_to_error": failure_ok,
        "fallback_to_error": fallback_ok,
        "success_fabricated": fabricated,
    }


def find_contract(wf: Mapping, ctx: Context, entry: Mapping | None) -> tuple[dict | None, str]:
    """The health contract that governs this workflow, and where it came from. A DECLARED ref or id must exist and
    bind to this workflow — it never falls back to another contract."""
    fw = framework_meta(wf)
    wid = str(wf.get("id"))
    ids = {wid, str((entry or {}).get("live_id") or wid)}
    ref = fw.get("health_contract_ref")
    if ref:
        path = ctx.root / str(ref)
        if not path.exists():
            return None, f"health_contract_ref {ref} does not exist"
        doc = _load(path)
        c = doc.get("contract") if isinstance(doc.get("contract"), dict) else doc
        if c.get("workflow_id") not in ids:
            return None, f"health_contract_ref {ref} binds workflow {c.get('workflow_id')!r}, not {wid!r}"
        return c, str(ref)
    want = fw.get("health_contract_id")
    if want:
        lanes = set(str(x) for x in fw.get("lanes") or [])
        for c in ctx.contracts:
            if c.get("id") == want:
                if c.get("workflow_id") in ids or (c.get("kind") == "lane" and c.get("id") in lanes):
                    return c, f"{CONTRACTS} id={want}"
                return None, f"health_contract_id {want} binds workflow {c.get('workflow_id')!r}, not {wid!r}"
        return None, f"health_contract_id {want} does not exist in {CONTRACTS}"
    for c in ctx.contracts:
        if c.get("kind") == "generic_workflow" and c.get("workflow_id") in ids:
            return c, f"{CONTRACTS} id={c.get('id')}"
    for c in ctx.contracts:
        if c.get("kind") == "lane" and c.get("workflow_id") in ids - {"tradeai-dispatcher"}:
            return c, f"{CONTRACTS} id={c.get('id')} (workflow_id)"
    lane = str((wf.get("meta") or {}).get("lane_id") or "")
    for c in ctx.contracts:
        if lane and c.get("id") == lane and c.get("kind") == "lane" and not fw:
            return c, f"{CONTRACTS} id={lane} (lane contract of a per-lane workflow)"
    return None, "no contract for the workflow id, its live id or its lane"


# ---------------------------------------------------------------------------------------------------------------
# scoring


def _r(status: str, reason: str) -> dict:
    return {"status": status, "reason": reason}


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _check_expected_output(c: Mapping | None) -> dict:
    """FW-M6: a CLOSED, executable N8nExpectedOutput@v1 rule."""
    if not c:
        return _r(FAIL, "no health contract, so no expected-output rule (an exit-0 run that produced nothing passes)")
    eo = c.get("expected_output")
    if not isinstance(eo, dict):
        return _r(
            FAIL,
            f"contract {c.get('id')} declares no expected_output rule: exit 0 with nothing produced "
            "would read as success (operator rule 2026-10-15)",
        )
    # 2026-10-15 train 3: both the shared runtime validator (scripts/lib/n8n_output_verdict.py, audit DD07) and the
    # checker's stricter closed-schema checks (audit DD15) apply; either one failing fails FW-M6.
    try:
        from scripts.lib.n8n_output_verdict import validate_expected_output  # noqa: PLC0415
    except ImportError:  # scripts/ on sys.path
        from lib.n8n_output_verdict import validate_expected_output  # type: ignore[no-redef]  # noqa: PLC0415
    p: list[str] = list(validate_expected_output(eo))
    extra = sorted(set(eo) - EXPECTED_OUTPUT_KEYS)
    if extra:
        p.append(f"unknown keys {extra} (closed schema)")
    if eo.get("schema") != EXPECTED_OUTPUT_SCHEMA:
        p.append(f"schema != {EXPECTED_OUTPUT_SCHEMA}")
    rule = eo.get("rule")
    if rule not in EXPECTED_OUTPUT_RULES:
        p.append(f"rule {rule!r} not in {EXPECTED_OUTPUT_RULES}")
    mp, wh = eo.get("min_produced"), eo.get("window_h")
    if rule in ("min_produced", "per_window") and not (_is_int(mp) and mp >= 1):
        p.append("min_produced must be an integer >= 1 (booleans refused)")
    if rule == "empty_allowed" and mp is not None and not (_is_int(mp) and mp >= 0):
        p.append("min_produced must be null or an integer >= 0")
    if rule == "per_window":
        if not (_is_num(wh) and 0 < wh <= MAX_WINDOW_H):
            p.append(f"per_window needs a finite window_h in (0, {MAX_WINDOW_H}]")
    elif wh is not None:
        p.append("window_h is only valid for per_window")
    pf = eo.get("produced_field")
    if not (isinstance(pf, str) and _FIELD_RE.fullmatch(pf)):
        p.append("produced_field must be a field-name string")
    if not (isinstance(eo.get("unit"), str) and eo["unit"].strip()):
        p.append("unit must be a non-empty string")
    fatal = eo.get("fatal_skip_reasons")
    if not (isinstance(fatal, list) and fatal and all(isinstance(x, str) for x in fatal)):
        p.append("fatal_skip_reasons must be a non-empty list of strings")
    else:
        unknown = sorted(set(fatal) - FATAL_SKIP_REASONS)
        if unknown:
            p.append(f"fatal_skip_reasons outside the closed enum: {unknown}")
        if "no_runner" not in fatal:
            p.append("no_runner must be fatal (operator rule 2026-10-15)")
    empty = eo.get("empty_allowed_reasons", [])
    if not (isinstance(empty, list) and all(isinstance(x, str) for x in empty)):
        p.append("empty_allowed_reasons must be a list of strings")
        empty = []
    unknown = sorted(set(empty) - EMPTY_ALLOWED_REASONS)
    if unknown:
        p.append(f"empty_allowed_reasons outside the closed enum: {unknown}")
    if rule == "empty_allowed" and not (set(empty) & EMPTY_ALLOWED_REASONS):
        p.append("empty_allowed needs at least one valid empty_allowed_reason")
    if isinstance(fatal, list) and set(empty) & set(fatal):
        p.append("a reason cannot be both fatal and allowed-empty")
    ev = eo.get("evidence")
    good_ev = [
        e
        for e in (ev if isinstance(ev, list) else [])
        if isinstance(e, dict)
        and e.get("kind") in EVIDENCE_KINDS
        and isinstance(e.get("ref"), str)
        and e["ref"].strip()
    ]
    if not (isinstance(ev, list) and ev and len(good_ev) == len(ev)):
        p.append(f"every evidence item needs kind in {sorted(EVIDENCE_KINDS)} and a non-empty ref")
    if isinstance(pf, str) and not any(e["kind"] == "receipt_field" and pf in e["ref"] for e in good_ev):
        p.append(f"no receipt_field evidence names produced_field {pf!r} (nothing would read the count)")
    ov = eo.get("on_violation")
    if not (
        isinstance(ov, dict)
        and ov.get("run_state") == "RUN_FAILED"
        and ov.get("reason") == "empty_output"
        and ov.get("notifier_priority") in ("P1", "P2")
    ):
        p.append("on_violation must be {run_state: RUN_FAILED, reason: empty_output, notifier_priority: P1|P2}")
    if p:
        return _r(FAIL, "expected_output invalid: " + "; ".join(dict.fromkeys(p)))
    return _r(PASS, f"expected_output rule {rule} on {pf} ({eo.get('unit')}); enforcement is runtime (23.24-M6b)")


def _runbook_resolves(ctx: Context, rid: str, path: str | None) -> str | None:
    """The file in which ``rid`` resolves (its runbook_path or the incident runbook), else None."""
    for p in [path, str(INCIDENT_RUNBOOK)]:
        if p and (ctx.root / p).is_file() and rid in (ctx.root / p).read_text(encoding="utf-8", errors="replace"):
            return p
    return None


def _http_auth_problem(n: Mapping, ctx: Context) -> str | None:
    p = n.get("parameters") or {}
    creds = n.get("credentials") or {}
    want = {"httpHeaderAuth": {"id": ctx.credential_name, "name": ctx.credential_name}}
    got = {k: {kk: (v or {}).get(kk) for kk in ("id", "name")} for k, v in creds.items() if isinstance(v, dict)}
    if got != want or len(creds) != 1:
        return f"credentials {got} != {want}"
    if p.get("authentication") != "genericCredentialType" or p.get("genericAuthType") != "httpHeaderAuth":
        return f"authentication={p.get('authentication')!r} genericAuthType={p.get('genericAuthType')!r} (stored credential not used)"
    hdrs = json.dumps(p.get("headerParameters") or {}).lower()
    if "authorization" in hdrs or "x-tradeai" in hdrs:
        return "an auth header is set by hand (overrides the credential)"
    opts = p.get("options") or {}
    if "redirect" in opts or "proxy" in opts:
        return "redirect/proxy override in options"
    return None


def score_workflow(wf: Mapping, ctx: Context, *, entry: Mapping | None = None, file: str | None = None) -> dict:
    """Score one workflow. ``entry`` is its active-set row (class, mode, stage), when it has one."""
    entry = entry or {}
    fw = framework_meta(wf)
    settings = wf.get("settings") or {}
    wid = str(wf.get("id"))
    wclass = fw.get("class") if fw.get("class") in CLASSES else entry.get("class")
    stage = fw.get("stage") if fw.get("stage") in STAGES else entry.get("stage")
    live_stage = stage in ("canary", "cutover") or entry.get("mode") == "live"
    contract, contract_src = find_contract(wf, ctx, entry)
    base = (contract or {}).get("baseline") or {}
    alerting = (contract or {}).get("alerting") or {}
    nodes = _nodes(wf)
    by_name = {str(n.get("name")): n for n in nodes}
    live = reachable(wf)
    live_nodes = [n for n in nodes if str(n.get("name")) in live]
    is_run_lane = wid == ctx.run_lane_id
    rl_nodes = run_lane_nodes(wf, ctx.run_lane_id)
    uses_run_lane = any(str(n.get("name")) in live for n in rl_nodes)
    direct_runs = direct_run_nodes(wf)
    direct_live = [n for n in direct_runs if str(n.get("name")) in live]
    runs_any = is_run_lane or bool(rl_nodes) or bool(direct_runs)
    http = _of_type(wf, "httpRequest")
    calls = relay_calls(wf)
    lanes = named_lanes(wf, ctx)
    llm_steps = [s for s in fw.get("llm_steps") or [] if isinstance(s, dict)]
    graph_llm = llm_nodes(wf)
    is_ai = bool(llm_steps) or wclass == "ai-llm" or bool(graph_llm)
    live_code = "\n".join(js_code(n) for n in _of_type(wf, "code", live_nodes))
    el: dict[str, dict] = {}

    # Structure (graph alone) ------------------------------------------------------------------------------------
    names = [str(n.get("name")) for n in nodes]
    dup = sorted({x for x in names if names.count(x) > 1})
    dangling = sorted({f"{s}->{d}" for s, _, d in edges(wf) if s not in by_name or d not in by_name})
    if not nodes:
        el["FW-W1"] = _r(FAIL, "no nodes")
    elif dup or dangling:
        el["FW-W1"] = _r(
            FAIL,
            "; ".join(
                ([f"duplicate names {dup}"] if dup else [])
                + ([f"connections to/from missing nodes {dangling}"] if dangling else [])
            ),
        )
    else:
        el["FW-W1"] = _r(PASS, f"{len(nodes)} nodes, {len(edges(wf))} connections, all to existing nodes")
    triggers = [str(n.get("name")) for n in nodes if is_trigger(n)]
    disabled = sorted(str(n.get("name")) for n in nodes if n.get("disabled") is True)
    unreach = sorted(set(names) - live)
    if not triggers:
        el["FW-W2"] = _r(FAIL, "no trigger node: nothing can start this graph")
    elif unreach or disabled:
        el["FW-W2"] = _r(
            FAIL, f"unreachable from every trigger: {unreach}" + (f"; disabled {disabled}" if disabled else "")
        )
    else:
        el["FW-W2"] = _r(PASS, f"all {len(nodes)} nodes reachable from {len(triggers)} trigger(s)")
    w3: list[str] = []
    declares_runs = bool(fw.get("lanes")) or bool(fw.get("effect_process"))
    routing: dict = {}
    if declares_runs and not runs_any:
        w3.append("metadata declares lanes/effect_process but the graph has no Run Lane call or POST /run")
    unreachable_runs = sorted(str(n.get("name")) for n in rl_nodes + direct_runs if str(n.get("name")) not in live)
    if unreachable_runs:
        w3.append(f"run request node(s) on no trigger path: {unreachable_runs}")
    no_wait = sorted(
        str(n.get("name"))
        for n in rl_nodes
        if not ((n.get("parameters") or {}).get("options") or {}).get("waitForSubWorkflow")
    )
    if no_wait:
        w3.append(f"Run Lane call(s) {no_wait} do not wait for the sub-workflow: the result is never routed")
    if rl_nodes and not is_run_lane:
        routing = run_result_routing(wf, ctx, live)
        if not routing["routed"]:
            w3.append(routing["reason"])
        else:
            if not routing["failure_to_error"]:
                w3.append(f"'failed' output of {routing['switch']} reaches no throwing node (no error route)")
            if not routing["fallback_to_error"]:
                w3.append(f"fallback output of {routing['switch']} reaches no throwing node")
            if routing["refusal_unrouted"]:
                w3.append(f"refusal status(es) {routing['refusal_unrouted']} not routed to a node")
            if routing["success_fabricated"]:
                w3.append(
                    f"success branch node(s) {routing['success_fabricated']} assert status 'success' instead "
                    "of forwarding the run result"
                )
    if direct_live and not any(throws(n) or n.get("onError") == "stopWorkflow" for n in live_nodes):
        w3.append("direct POST /run with no error route on a trigger path")
    if w3:
        el["FW-W3"] = _r(FAIL, "; ".join(w3))
    elif runs_any or declares_runs:
        el["FW-W3"] = _r(PASS, "run request, result routing and error route all on a trigger path")
    else:
        el["FW-W3"] = _r(NA, "requests no lane run and declares none")

    w4: list[str] = []
    checked_meta = False
    meta = wf.get("meta") or {}
    import n8n_workflow_templates as T  # noqa: PLC0415

    if meta.get("graph_sha256"):
        checked_meta = True
        if meta["graph_sha256"] != T.graph_hash(wf):
            w4.append("meta.graph_sha256 does not match the graph (metadata copied or graph edited)")
    if meta.get("policy_sha256"):
        checked_meta = True
        if meta["policy_sha256"] != T.policy_hash():
            w4.append("meta.policy_sha256 does not match the current fabric policy")
    if fw:
        checked_meta = True
        graph_text = json.dumps([n.get("parameters") for n in live_nodes])
        missing_lanes = [
            x
            for x in fw.get("lanes") or []
            if not re.search(rf"(?<![A-Za-z0-9_.-]){re.escape(str(x))}(?![A-Za-z0-9_.-])", graph_text)
        ]
        if missing_lanes:
            w4.append(f"declared lane(s) {missing_lanes} appear in no reachable node")
        ep = fw.get("effect_process")
        if ep and ep not in {(ctx.effect_specs.get(x) or {}).get("process") for x in fw.get("lanes") or []}:
            w4.append(f"effect_process {ep!r} is not the effect-key process of any declared lane")
        llm_names = {str(n.get("name")) for n in graph_llm}
        for s in llm_steps:
            nn = str(s.get("node"))
            if nn not in by_name:
                w4.append(f"llm_steps node {nn!r} does not exist")
            elif nn not in llm_names:
                w4.append(f"llm_steps node {nn!r} is not an LLM call (POST relay /llm_step)")
            elif nn not in live:
                w4.append(f"llm_steps node {nn!r} is on no trigger path")
        undeclared = sorted(llm_names - {str(s.get("node")) for s in llm_steps})
        if undeclared:
            w4.append(f"LLM call node(s) not declared in llm_steps: {undeclared}")
    elif graph_llm:
        checked_meta = True
        w4.append(f"LLM call node(s) with no meta.framework.llm_steps: {[n.get('name') for n in graph_llm]}")
    row = ctx.manifests.get(file or "") or {}
    if row.get("node_types") is not None:
        checked_meta = True
        if sorted(row["node_types"]) != sorted({str(n.get("type")) for n in nodes}):
            w4.append("manifest node_types differ from the graph")
    if row.get("error_workflow") is not None:
        checked_meta = True
        if row["error_workflow"] != settings.get("errorWorkflow"):
            w4.append("manifest error_workflow differs from settings.errorWorkflow")
    if row.get("relay_calls") is not None:
        checked_meta = True
        claimed = {
            re.sub(r"^(\S+ )/runs/[^/]+/last$", r"\1/runs/<lane_id>/last", str(c).split("?", 1)[0])
            for c in row["relay_calls"]
        }
        if sorted(claimed) != sorted({f"{m} {p}" for m, p in calls}):
            w4.append("manifest relay_calls differ from the graph's HTTP nodes")
    el["FW-W4"] = (
        _r(FAIL, "; ".join(w4))
        if w4
        else _r(PASS, "metadata, graph hash and manifest claims agree with the graph")
        if checked_meta
        else _r(NA, "no metadata or manifest claims to cross-check")
    )

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
    custom = bool(_RUN_ID_SET_RE.search(live_code))
    if custom and rl_nodes:  # the run_id must be recorded AFTER the Run Lane call, on its path
        after = set().union(*(downstream(wf, str(n.get("name"))) for n in rl_nodes))
        custom = any(_RUN_ID_SET_RE.search(js_code(by_name[x])) for x in after & live if x in by_name)
    ids_in_body = bool(direct_live) and all(
        all(k in str((n.get("parameters") or {}).get("jsonBody") or "") for k in _RUN_BODY_IDS) for n in direct_live
    )
    joinable = custom or (ids_in_body and not uses_run_lane)
    if not runs_any and http:
        bodies = [
            str((n.get("parameters") or {}).get("jsonBody") or "")
            for n in http
            if str(n.get("name")) in live and (n.get("parameters") or {}).get("jsonBody")
        ]
        joinable = joinable or (bool(bodies) and all(all(k in b for k in _RUN_BODY_IDS) for b in bodies))
    note = " (the ledger join itself is runtime: 23.24-M1a UNPROVEN)"
    if saved and joinable:
        el["FW-M1"] = _r(PASS, "successes saved; run_id carried on a reachable path" + note)
    elif saved or joinable:
        el["FW-M1"] = _r(
            PARTIAL,
            ("successes saved" if saved else "successes NOT saved (instance default none)")
            + "; "
            + ("run_id joinable" if joinable else "no run_id recorded on a reachable path"),
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
    timeout = _is_int(settings.get("executionTimeout")) and settings["executionTimeout"] > 0
    bound = _is_num(base.get("duration_degraded_above_s")) and base["duration_degraded_above_s"] > 0
    p95 = base.get("p95_duration_bound_s")
    p95_ok = _is_num(p95) and p95 > 0 and (not timeout or p95 <= settings["executionTimeout"])
    if timeout and p95_ok:
        el["FW-M3"] = _r(
            PASS,
            f"executionTimeout {settings['executionTimeout']} s >= contract p95 bound {p95} s "
            "(the p95 measurement is runtime: 23.24-M3b)",
        )
    elif timeout and (bound or p95 is not None):
        el["FW-M3"] = _r(PARTIAL, "executionTimeout set; contract has no valid p95_duration_bound_s (<= timeout)")
    elif timeout:
        el["FW-M3"] = _r(PARTIAL, "executionTimeout set; contract has no duration bound")
    elif bound or p95_ok:
        el["FW-M3"] = _r(PARTIAL, "contract duration bound; no executionTimeout")
    else:
        el["FW-M3"] = _r(FAIL, "no executionTimeout and no contract duration bound")
    klass = base.get("class")
    if not runs_any:
        el["FW-M4"] = _r(NA, "requests no lane run")
    elif klass in ctx.class_caps:
        el["FW-M4"] = _r(PASS, f"class {klass} has an executor class cap (start lag / enforcement: 23.24-M4b)")
    elif klass:
        el["FW-M4"] = _r(PARTIAL, f"class {klass!r} has no class_caps row; only the global cap applies")
    else:
        el["FW-M4"] = _r(FAIL, "no contract baseline class")
    deps = (contract or {}).get("connects_to") or fw.get("connects_to") or []
    if not deps:
        el["FW-M5"] = _r(FAIL, "no connects_to")
    else:
        dep_text = json.dumps(deps) + json.dumps(fw.get("connects_to") or [])
        need = []
        if rl_nodes:
            need.append(ctx.run_lane_id)
        if ew:
            need.append(str(ew))
        need += sorted({p for _, p in calls if not p.startswith("<")})
        need += [x for x in lanes if x]
        miss = [x for x in dict.fromkeys(need) if x not in dep_text]
        el["FW-M5"] = (
            _r(PARTIAL, f"connects_to omits graph dependencies: {miss}")
            if miss
            else _r(PASS, f"{len(deps)} connects_to edges name every graph dependency (stores: 23.24-M5b)")
        )
    el["FW-M6"] = _check_expected_output(contract)

    # Alerting ------------------------------------------------------------------------------------------------
    if ew and ew == wid:
        el["FW-A1"] = _r(
            FAIL, "self-referencing error workflow: its own failure alerts nothing in n8n (host fan-in must catch it)"
        )
    elif ew in ctx.error_workflow_ids:
        el["FW-A1"] = _r(PASS, f"failures → {ew} → incident path (delivery: 23.24-A1b)")
    else:
        el["FW-A1"] = _r(FAIL, "failures are not routed (no error workflow)")
    fresh = _is_num(base.get("freshness_failed_after_h"))
    prio = bool((alerting.get("failed") or {}).get("notifier_priority"))
    el["FW-A2"] = (
        _r(
            PASS,
            f"freshness failed after {base.get('freshness_failed_after_h')} h, "
            f"{alerting['failed']['notifier_priority']} (outside-n8n watcher: FW-P6)",
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
    if is_run_lane:
        el["FW-A4"] = _r(PASS, "is Run Lane: classifies refused_policy / skipped_lock as data")
    elif rl_nodes:
        if not routing.get("routed"):
            el["FW-A4"] = _r(FAIL, f"refusals not routed as data: {routing.get('reason')}")
        elif routing["refusal_to_error"]:
            el["FW-A4"] = _r(
                FAIL,
                f"refusal status(es) {routing['refusal_to_error']} reach a throwing node: "
                "a refusal becomes an n8n error (WS1b-07)",
            )
        elif routing["refusal_unrouted"]:
            el["FW-A4"] = _r(FAIL, f"refusal status(es) {routing['refusal_unrouted']} not routed")
        else:
            el["FW-A4"] = _r(PASS, f"{routing['switch']}: refused_policy / skipped_lock reach no throwing node")
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
        bad = []
        for s in llm_steps:
            nn, eb = str(s.get("node")), s.get("exception_branch")
            if not eb or eb not in by_name:
                bad.append(f"{nn}: exception_branch {eb!r} is not a node")
            elif nn not in by_name or eb not in downstream(wf, nn):
                bad.append(f"{nn}: exception_branch {eb!r} is not wired from the LLM node")
        el["FW-A5"] = (
            _r(PASS, "every LLM step has an exception branch wired from its node")
            if llm_steps and not bad
            else _r(FAIL, f"LLM exception branches: {bad or 'no llm_steps declared'}")
        )
    intent_kinds = re.findall(r"kind:\s*'([a-z_]+)'", live_code)
    rid, rb = fw.get("runbook_id"), fw.get("runbook_path")
    if rid:
        where = _runbook_resolves(ctx, str(rid), str(rb) if rb else None)
        el["FW-A6"] = (
            _r(PASS, f"runbook_id {rid} resolves in {where}")
            if where
            else _r(FAIL, f"runbook_id {rid} resolves to no runbook (runbook_path or {INCIDENT_RUNBOOK})")
        )
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
    origins = relay_origin_values(wf)
    bad_origin = sorted(set(origins) - ctx.relay_origins)
    if not http:
        el["FW-L4"] = (
            _r(PASS, "no HTTP node: every host call goes through Run Lane") if uses_run_lane else _r(NA, "no host call")
        )
    else:
        bad = [n.get("name") for n in http if relay_route(n) is None]
        if bad:
            el["FW-L4"] = _r(FAIL, f"HTTP node(s) not addressed to the relay origin by the approved URL shape: {bad}")
        elif not origins or bad_origin:
            el["FW-L4"] = _r(
                FAIL, f"relay base not an approved origin: {bad_origin or 'no TRADEAI_N8N_RUN_URL assignment'}"
            )
        else:
            el["FW-L4"] = _r(PASS, f"{len(http)} HTTP node(s), all to the approved relay origin (relay_log.jsonl)")
    rel = file
    mrow = ctx.manifests.get(rel or "")
    integrity = {
        "listed_in_manifest": mrow is not None,
        "manifest_sha_matches": None,
        "regenerated_byte_equal": None,
        "graph_hash_matches": None,
    }
    digest = hashlib.sha256((ctx.root / rel).read_bytes()).hexdigest() if rel and (ctx.root / rel).exists() else None
    if mrow is not None and mrow.get("sha256"):
        integrity["manifest_sha_matches"] = digest == mrow["sha256"]
    if meta.get("graph_sha256"):
        integrity["graph_hash_matches"] = meta["graph_sha256"] == T.graph_hash(wf)
    if rel and rel in ctx.renders and digest is not None:
        integrity["regenerated_byte_equal"] = (ctx.root / rel).read_bytes() == ctx.renders[rel].encode("utf-8")
    if mrow is None:
        el["FW-L5"] = _r(FAIL, f"{rel} is not listed by a generator manifest")
    elif integrity["regenerated_byte_equal"] is True:
        el["FW-L5"] = _r(PASS, f"byte-equal to a fresh render of its generator ({mrow['_manifest']})")
    elif integrity["regenerated_byte_equal"] is False:
        el["FW-L5"] = _r(
            FAIL,
            "differs from a fresh render of its generator (hand-edited or generator changed; "
            "a re-stamped manifest hash does not count)",
        )
    else:
        el["FW-L5"] = _r(
            PARTIAL,
            f"listed in {mrow['_manifest']}; no in-process render to compare (a manifest "
            "hash alone is not evidence of generation)",
        )
    integrity["status"] = el["FW-L5"]["status"]

    # Recovery ------------------------------------------------------------------------------------------------
    retry_http = bool(http) and all(n.get("retryOnFail") for n in http)
    if is_run_lane:
        el["FW-R1"] = _r(PASS, "is the retry owner (Run Lane)")
    elif uses_run_lane and any(n.get("retryOnFail") for n in rl_nodes):
        el["FW-R1"] = _r(FAIL, "retryOnFail on the Run Lane call: two retry owners (n8n node retry + Run Lane)")
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
        _r(PASS, "runs go to the executor: ledger breakers + dead_letters (half-open: 23.24-R2b)")
        if (is_run_lane or uses_run_lane or direct_live)
        else _r(FAIL, "run request on no trigger path")
        if runs_any
        else _r(NA, "requests no lane run")
    )
    rbk = fw.get("rollback")
    if not rbk:
        el["FW-R3"] = _r(FAIL, "no declared fallback in metadata")
    else:
        fw_lanes = [str(x) for x in fw.get("lanes") or []]
        cron_fallback = bool(fw_lanes) and all(ctx.lane_schedulers.get(x) == "cron" for x in fw_lanes)
        cited = [
            p for p in re.findall(r"(?:docs|scripts|config)/[A-Za-z0-9_./-]+", str(rbk)) if (ctx.root / p).exists()
        ]
        el["FW-R3"] = (
            _r(
                PASS,
                "fallback resolves: every lane's cron line is the registry scheduler (" + ", ".join(fw_lanes) + ")",
            )
            if cron_fallback
            else _r(PARTIAL, f"rollback cites {cited}; no cron-line fallback in the registry")
            if cited
            else _r(FAIL, "rollback text resolves to no cron line and no existing file")
        )
    if rb and (ctx.root / str(rb)).is_file():
        if rid and str(rid) not in (ctx.root / str(rb)).read_text(encoding="utf-8", errors="replace"):
            el["FW-R5"] = _r(FAIL, f"runbook_path {rb} exists but never names runbook_id {rid}")
        else:
            el["FW-R5"] = _r(PASS, f"runbook {rb}")
    elif rb:
        el["FW-R5"] = _r(FAIL, f"runbook_path {rb} does not exist")
    elif el["FW-A6"]["status"] == PARTIAL:
        el["FW-R5"] = _r(PARTIAL, "runbook ids come from the intent route table only")
    else:
        el["FW-R5"] = _r(FAIL, "no runbook")
    ep = fw.get("effect_process")
    known_processes = {(s or {}).get("process") for s in ctx.effect_specs.values()}
    if ep and ep not in known_processes:
        el["FW-R6"] = _r(FAIL, f"effect_process {ep!r} is not a process in config/n8n_effect_keys.json")
    elif not runs_any:
        el["FW-R6"] = _r(NA, "requests no lane run")
    elif not lanes:
        el["FW-R6"] = _r(NA, "lanes come from /due; the executor applies effect keys per lane (runtime: 23.24-R6b)")
    elif not live_stage:
        unarmed = [x for x in lanes if not (ctx.effect_specs.get(x) or {}).get("n8n_claim")]
        el["FW-R6"] = _r(
            PASS,
            f"stage {stage or 'shadow'}: dry runs claim no effect key"
            + (f"; NOT armed (n8n_claim) for {unarmed} — must be armed before canary" if unarmed else ""),
        )
    else:
        bad = []
        for x in lanes:
            spec = ctx.effect_specs.get(x)
            if not spec:
                bad.append(f"{x}: no effect key")
            elif not spec.get("n8n_claim"):
                bad.append(f"{x}: n8n_claim false (staged, not armed)")
            elif stage == "canary" and not spec.get("cron_claim"):
                bad.append(f"{x}: cron_claim false while the cron line can still fire (canary)")
            elif ep and spec.get("process") != ep:
                bad.append(f"{x}: effect process {spec.get('process')!r} != effect_process {ep!r}")
        el["FW-R6"] = (
            _r(PASS, "every live lane's effect key is armed on the sides that can fire (owner row: 23.24-R6b)")
            if not bad
            else _r(FAIL, f"live lane(s) without an armed effect key: {bad}")
        )

    # Security ------------------------------------------------------------------------------------------------
    bad_auth = []
    for n in http:
        prob = _http_auth_problem(n, ctx)
        if prob:
            bad_auth.append(f"{n.get('name')}: {prob}")
    for n in _of_type(wf, "webhook"):
        cred = (n.get("credentials") or {}).get("httpHeaderAuth") or {}
        if (
            (n.get("parameters") or {}).get("authentication") != "headerAuth"
            or cred.get("name") != ctx.credential_name
            or cred.get("id") != ctx.credential_name
        ):
            bad_auth.append(f"{n.get('name')}: webhook without effective relay header auth")
    if not http and not _of_type(wf, "webhook"):
        el["FW-S1"] = _r(PASS, "no inbound or outbound HTTP surface") if nodes else _r(NA, "empty")
    else:
        el["FW-S1"] = (
            _r(PASS, f"effective relay credential {ctx.credential_name} on every HTTP node; webhooks header-auth")
            if not bad_auth
            else _r(FAIL, f"node(s) without effective relay header auth: {bad_auth}")
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
    want_cred = ("httpHeaderAuth", ctx.credential_name, ctx.credential_name)
    creds = sorted(
        {
            (t, (c or {}).get("id"), (c or {}).get("name"))
            for n in nodes
            for t, c in (n.get("credentials") or {}).items()
        }
    )
    other = [c for c in creds if c != want_cred]
    params_text = json.dumps([n.get("parameters") for n in nodes])
    leaks = [r.pattern for r in _SECRET_RES if r.search(params_text)]
    el["FW-S3"] = (
        _r(FAIL, f"credential(s) other than the relay's (type, id, name): {other}")
        if other
        else _r(FAIL, f"secret-like literal in parameters ({leaks})")
        if leaks
        else _r(FAIL, "reads the environment ($env / process.env) in a node")
        if _ENV_RE.search(params_text)
        else _r(PASS, "only the relay credential; no secret literal; no env read")
    )
    types = sorted({str(n.get("type")) for n in nodes})
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
        _score_llm(el, llm_steps, ctx, by_name, live, wf)

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
    score = {"measure": MEASURE, "points": points, "of": of, "pct": round(100.0 * points / of, 1) if of else None}
    runtime = runtime_obligations(runs_any, is_ai)
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
        "score": score,
        "failing": [k for k, v in el.items() if v["status"] == FAIL],
        # the five separate fields (audit §10): never folded into one number
        "integrity": integrity,
        "artifact_integrity": integrity,
        "evidence_identity": {"workflow_id": str(wf.get("id")), "graph_sha256": T.graph_hash(wf),
                              "policy_sha256": T.policy_hash()},
        "design_coverage": dict(score, note=MEASURE_NOTE),
        "deployed_parity": {
            "status": UNPROVEN,
            "evidence_required": "23.24-L5b: N8nWorkflowDriftReceipt@v1 for this id from a host-scheduled live read",
        },
        "runtime": runtime,
        "runtime_outcome": {"status": UNPROVEN, "obligations": [o["id"] for o in runtime]},
        "activation_eligibility": {"eligible": False, "blocking": ["not gated: run --gate activation"]},
    }


def runtime_obligations(runs: bool, ai: bool) -> list[dict]:
    out = []
    for o in OBLIGATIONS:
        if o["kind"] != "not_checkable_offline" or o.get("applies") == "fleet":
            continue
        if o.get("applies") == "runs" and not runs:
            continue
        if o.get("applies") == "ai" and not ai:
            continue
        out.append({"id": o["id"], "text": o["text"], "status": UNPROVEN, "evidence_required": o["evidence"]})
    return out


def _score_llm(el: dict, steps: list[dict], ctx: Context, by_name: Mapping, live: set[str], wf: Mapping) -> None:
    if not steps:
        for eid in ("FW-G1", "FW-G2", "FW-G3", "FW-G4", "FW-G5", "FW-G6", "FW-G7"):
            el[eid] = _r(FAIL, "AI workflow declares no meta.framework.llm_steps")
        return

    def body(s: Mapping) -> str:
        n = by_name.get(str(s.get("node"))) or {}
        if relay_route(n) != LLM_ROUTE or str(s.get("node")) not in live:
            return ""
        return str((n.get("parameters") or {}).get("jsonBody") or "")

    def every(pred: Callable[[Mapping], str | None], ok: str) -> dict:
        bad = []
        for s in steps:
            if not body(s):
                bad.append(f"{s.get('node')}: not a reachable POST /llm_step node")
                continue
            why = pred(s)
            if why:
                bad.append(f"{s.get('node')}: {why}")
        return _r(PASS, ok) if not bad else _r(FAIL, "; ".join(bad))

    def g1(s):
        t = ctx.template_specs.get(str(s.get("template_id")))
        if t is None:
            return "template not in config/n8n_prompt_templates.json"
        if t.get("process_id") and t["process_id"] != s.get("process_id"):
            return f"template {s.get('template_id')} is bound to process {t['process_id']}, not {s.get('process_id')}"
        b = body(s)
        if json.dumps(str(s.get("template_id"))) not in b:
            return "the node does not send the declared template_id"
        if _PROMPT_KEYS_RE.search(b):
            return "the node sends an inline prompt"
        return None

    def g2(s):
        if s.get("process_id") not in ctx.llm_processes:
            return "process not in config/llm_process_registry.json"
        b = body(s)
        if json.dumps(str(s.get("process_id"))) not in b:
            return "the node does not send the declared process_id"
        if _MODEL_KEYS_RE.search(b):
            return "the node names a model/provider"
        return None

    def g3(s):
        p = ctx.llm_processes.get(str(s.get("process_id"))) or {}
        if not (_is_num(p.get("daily_cost_cap_usd")) and p["daily_cost_cap_usd"] > 0):
            return "process without a positive daily_cost_cap_usd"
        if not all(_is_int(p.get(k)) and p[k] > 0 for k in ("max_input_tokens", "max_output_tokens")):
            return "process without positive max_input_tokens / max_output_tokens"
        return None

    def g4(s):
        sc = ctx.schema_specs.get(str(s.get("output_schema_id")))
        if sc is None:
            return "schema not in config/schemas/n8n_llm_step_outputs.json"
        if sc.get("process_ids") and s.get("process_id") not in sc["process_ids"]:
            return f"schema {s.get('output_schema_id')} is not registered for process {s.get('process_id')}"
        if json.dumps(str(s.get("output_schema_id"))) not in body(s):
            return "the node does not send the declared output_schema_id"
        props, dec = sc.get("properties") or {}, sc.get("decision_fields") or []
        if not props or not dec or any(not (props.get(f) or {}).get("enum") for f in dec):
            return "schema not closed: every decision field needs an enum"
        if not set(dec) <= set(sc.get("required") or []):
            return "schema not closed: decision fields must be required"
        return None

    def g5(s):
        sc = ctx.schema_specs.get(str(s.get("output_schema_id"))) or {}
        props = sc.get("properties") or {}
        enum_fields = {f for f in sc.get("decision_fields") or [] if (props.get(f) or {}).get("enum")}
        bf = s.get("branch_fields") or []
        if not bf:
            return "no branch_fields"
        bad = [f for f in bf if f not in enum_fields]
        return f"branch field(s) {bad} are not enumerated decision fields of the schema" if bad else None

    el["FW-G1"] = every(g1, "registered templates bound to the step's process, sent by the node; no inline prompt")
    el["FW-G2"] = every(g2, "registered process ids, sent by the node; no model/provider")
    el["FW-G3"] = every(g3, "per-process cost caps declared (enforcement: 23.24-AI3b)")
    el["FW-G4"] = every(g4, "closed output schemas registered for the process")
    el["FW-G5"] = every(g5, "branches on enumerated schema decision fields only (host re-check: 23.24-AI5)")
    el["FW-G6"] = every(
        lambda s: None if s.get("offpeak_tier") in ("critical", "standard", "deferred") else "no offpeak_tier",
        "deferral tier declared (off-peak rule; output guardrails are 23.24-AI6, runtime)",
    )

    partial_g7 = []

    def g7(s):
        h = s.get("hitl")
        if h == "none":
            sc = ctx.schema_specs.get(str(s.get("output_schema_id"))) or {}
            if any("action" in str(f) for f in sc.get("decision_fields") or []):
                partial_g7.append(str(s.get("node")))
            return None
        if h != "approval_request":
            return "hitl must be none | approval_request"
        if APPROVAL_ROUTE not in ctx.relay_routes:
            return "approval_request declared but the relay serves no POST /approval/request (P)"
        if not any(relay_route(n) == APPROVAL_ROUTE for n in _of_type(wf, "httpRequest") if str(n.get("name")) in live):
            return "approval_request declared but no reachable approval request node"
        return None

    el["FW-G7"] = every(g7, "HITL declared and wired (host-record authority: 23.24-AI7b)")
    if el["FW-G7"]["status"] == PASS and partial_g7:
        el["FW-G7"] = _r(
            PARTIAL,
            f"hitl none on action-bearing decision(s) at {partial_g7}: the host re-check "
            "(23.24-AI5, runtime) is the only control",
        )


def score_platform(facts: Mapping) -> dict:
    f = {k: (v or {}).get("value") for k, v in (facts.get("facts") or {}).items()}
    ev = {k: (v or {}).get("evidence") for k, v in (facts.get("facts") or {}).items()}
    image = str(f.get("image_pinned") or "")
    env_ok = f.get("block_env_access_in_node") is True and f.get("community_packages_disabled") is True
    p5 = PASS if (env_ok and "@sha256:" in image) else PARTIAL if (env_ok and image) else FAIL
    out = {
        "FW-P1": (
            PASS if f.get("executions_save_on_success_default") == "all" else FAIL,
            ev.get("executions_save_on_success_default"),
        ),
        "FW-P2": (PASS if f.get("n8n_db_role_superuser") is False else FAIL, ev.get("n8n_db_role_superuser")),
        "FW-P3": (PASS if f.get("drift_check_scheduled") is True else FAIL, ev.get("drift_check_scheduled")),
        "FW-P4": (
            PASS if f.get("relay_bind_firewall_verified") is True else FAIL,
            ev.get("relay_bind_firewall_verified"),
        ),
        "FW-P5": (
            p5,
            "; ".join(
                str(ev.get(k)) for k in ("image_pinned", "block_env_access_in_node", "community_packages_disabled")
            )
            + ("" if "@sha256:" in image else " — tag pin, not a digest"),
        ),
        "FW-P6": (PASS if f.get("host_dead_man_outside_n8n") is True else FAIL, ev.get("host_dead_man_outside_n8n")),
    }
    return {k: {"status": s, "title": PLATFORM_ELEMENTS[k], "evidence": e} for k, (s, e) in out.items()}


# ---------------------------------------------------------------------------------------------------------------
# the fail-closed activation gate (DD16)


def _excused(exceptions: Iterable[Mapping], wid: str, item: str, today: str) -> bool:
    # v1 accepted_by/pr/expiry metadata is not an authenticated host approval.
    # A future host approval consumer must verify exact intent/actor/expiry and atomic use.
    return False


def _verified_runtime(row: Mapping, runtime_evidence: Mapping, obligation: str, *, evidence_trust=None, now=None) -> dict:
    from scripts.lib import n8n_evidence_attestation as A
    if runtime_evidence.get("schema") != RUNTIME_EVIDENCE_SCHEMA:
        return {"ok": False, "state": "UNPROVEN", "reason": "legacy or unavailable host attestation"}
    try:
        A._closed(dict(runtime_evidence), {"schema", "workflows"}, "runtime evidence")
        workflows = runtime_evidence["workflows"]
        if not isinstance(workflows, dict):
            raise A.EvidenceError("runtime workflows must be an object")
        trust = evidence_trust if evidence_trust is not None else A.load_trust_policy()
        identity = dict(row.get("evidence_identity") or {})
        if identity.get("workflow_id") != str(row["id"]):
            raise A.EvidenceError("scored workflow identity unavailable")
        identity.update(served_sha=trust.served_sha, evaluation_id=trust.evaluation_id,
                        obligation_id=obligation, audience=A.AUDIENCE)
        have = workflows.get(str(row["id"])) or {}
        if not isinstance(have, dict):
            raise A.EvidenceError("runtime obligations must be an object")
        envelope = have.get(obligation)
        if not isinstance(envelope, dict):
            raise A.EvidenceError("signed host observation unavailable")
        return A.verify_attestation(envelope, expected=identity, trust=trust, now=now)
    except (A.EvidenceError, TypeError, ValueError, KeyError) as exc:
        return {"ok": False, "state": "UNPROVEN", "reason": str(exc)}


def gate_workflow(
    row: Mapping, *, platform: Mapping | None, runtime_evidence: Mapping,
    exceptions: Iterable[Mapping], today: str | None = None, evidence_trust=None, now=None,
) -> dict:
    """Fail closed on static/platform gaps or unavailable authenticated runtime proof.

    v1 references are historical only. Self-described exceptions cannot waive controls.
    Observations never create deployment, scheduler, approval or other authority.
    """
    today = today or _dt.date.today().isoformat()
    exceptions = list(exceptions)
    wid = str(row["id"])
    blocking: list[str] = []
    for k, v in row["elements"].items():
        if v["status"] == FAIL or (v["status"] == PARTIAL and k in CRITICAL_ELEMENTS):
            blocking.append(f"{k} {v['status']}: {v['reason']}")
    if platform is None:
        blocking.append("platform facts missing (fail closed)")
    else:
        for k, v in platform.items():
            if v["status"] != PASS:
                blocking.append(f"platform {k} {v['status']}: {v['title']}")
    if exceptions:
        blocking.append("exceptions UNVERIFIED: authenticated host approval consumer unavailable")
    for o in row.get("runtime") or []:
        verification = _verified_runtime(row, runtime_evidence, o["id"], evidence_trust=evidence_trust, now=now)
        if not verification["ok"]:
            blocking.append(f"runtime {o['id']} UNPROVEN: {verification['reason']}; needs {o['evidence_required']}")
    return {"workflow_id": wid, "eligible": not blocking, "blocking": blocking}


def apply_runtime_evidence(row: dict, runtime_evidence: Mapping, *, evidence_trust=None, now=None) -> None:
    workflows = runtime_evidence.get("workflows") or {}
    have = workflows.get(str(row["id"])) or {} if isinstance(workflows, dict) else {}
    for o in row.get("runtime") or []:
        # Clear previously applied proof before re-evaluation (revocation/expiry is effective).
        o["status"] = UNPROVEN
        o.pop("evidence", None)
        verification = _verified_runtime(row, runtime_evidence, o["id"], evidence_trust=evidence_trust, now=now)
        o["verification"] = verification
        if verification["ok"]:
            o["status"], o["evidence"] = EVIDENCED, verification
        elif runtime_evidence.get("schema") == LEGACY_RUNTIME_EVIDENCE_SCHEMA and isinstance(have, dict) and o["id"] in have:
            o["legacy_evidence"] = have[o["id"]]
    row["runtime_outcome"]["status"] = EVIDENCED if row.get("runtime") and all(o["status"] == EVIDENCED for o in row["runtime"]) else UNPROVEN
    verification = _verified_runtime(row, runtime_evidence, "23.24-L5b", evidence_trust=evidence_trust, now=now)
    row["deployed_parity"] = {"status": EVIDENCED if verification["ok"] else UNPROVEN, "verification": verification}


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
    targets: Iterable[tuple[Path, Mapping | None]],
    ctx: Context,
    platform: Mapping | None,
    *,
    source: str,
    gate: str | None = None,
    runtime_evidence: Mapping | None = None,
    exceptions: Iterable[Mapping] = (),
    evidence_trust=None,
    now=None,
) -> dict:
    runtime_evidence = runtime_evidence or {}
    exceptions = list(exceptions)
    plat = score_platform(platform) if platform else None
    rows = []
    for path, entry in targets:
        wf = _load(path)
        row = score_workflow(wf, ctx, entry=entry, file=_rel(path, ctx.root))
        apply_runtime_evidence(row, runtime_evidence, evidence_trust=evidence_trust, now=now)
        row["activation_eligibility"] = gate_workflow(
            row, platform=plat, runtime_evidence=runtime_evidence, exceptions=exceptions, evidence_trust=evidence_trust, now=now
        )
        rows.append(row)
    pts = sum(r["score"]["points"] for r in rows)
    of = sum(r["score"]["of"] for r in rows)
    fleet_areas = {}
    for area in AREAS:
        verdicts = [r["areas"][area]["verdict"] for r in rows]
        fleet_areas[area] = {v: verdicts.count(v) for v in ("Y", "P", "N", NA)}
    report = {
        "schema": REPORT_SCHEMA,
        "source": source,
        "authority": "READ_ONLY_ADVISORY",
        "measure": MEASURE,
        "measure_note": MEASURE_NOTE,
        "elements": {k: {"area": a, "title": t, "critical": k in CRITICAL_ELEMENTS} for k, (a, t) in ELEMENTS.items()},
        "obligations": OBLIGATIONS,
        "workflows": rows,
        "platform": plat,
        "fleet": {
            "workflows": len(rows),
            "fully_conformant_static": sum(
                1 for r in rows if not r["failing"] and all(a["verdict"] in ("Y", NA) for a in r["areas"].values())
            ),
            "activation_eligible": sum(1 for r in rows if r["activation_eligibility"]["eligible"]),
            "points": pts,
            "of": of,
            "pct": round(100.0 * pts / of, 1) if of else None,
            "areas": fleet_areas,
            "failing_elements": sum(len(r["failing"]) for r in rows),
        },
    }
    report["fleet"]["fully_compliant"] = report["fleet"]["fully_conformant_static"]
    if gate:
        report["gate"] = {
            "mode": gate,
            "eligible": bool(rows) and all(r["activation_eligibility"]["eligible"] for r in rows),
            "workflows": [r["activation_eligibility"] for r in rows],
        }
    return report


def render_markdown(report: Mapping) -> str:
    short = {
        "structure": "Graph",
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
        f"Measure: {report['measure_note']}.",
        "",
        "| Workflow | Class | "
        + " | ".join(short[a] for a in AREAS)
        + " | Static conformance | Runtime | Eligible | Failing elements |",
        "|---|---|" + "---|" * len(AREAS) + "---:|---|---|---|",
    ]
    for r in report["workflows"]:
        cells = [f"{r['areas'][a]['verdict']}" for a in AREAS]
        s = r["score"]
        lines.append(
            f"| `{r['name'] or r['id']}` | {r['class'] or '—'} | "
            + " | ".join(cells)
            + f" | {s['points']:g}/{s['of']} ({s['pct']}%) | {r['runtime_outcome']['status']} "
            f"({len(r['runtime'])}) | {'yes' if r['activation_eligibility']['eligible'] else 'no'} | "
            f"{', '.join(r['failing']) or '—'} |"
        )
    f = report["fleet"]
    lines += [
        "",
        f"**Fleet:** {f['workflows']} workflows, {f['fully_conformant_static']} statically conformant, "
        f"{f['activation_eligible']} activation-eligible; static conformance {f['points']:g}/{f['of']} = {f['pct']}%; "
        f"{f['failing_elements']} failing elements.",
    ]
    if report.get("platform"):
        lines += ["", "| Platform element | Status | Evidence |", "|---|---|---|"]
        for k, v in report["platform"].items():
            lines.append(f"| {k} {v['title']} | {v['status']} | {v['evidence']} |")
    if report.get("gate"):
        g = report["gate"]
        lines += ["", f"**Gate {g['mode']}:** {'ELIGIBLE' if g['eligible'] else 'REFUSED'}"]
        for w in g["workflows"]:
            if not w["eligible"]:
                lines.append(f"- `{w['workflow_id']}`: {len(w['blocking'])} blocking — {w['blocking'][0]}")
    return "\n".join(lines) + "\n"


def _load_optional(path: str | None, schema: str) -> dict:
    if not path:
        return {}
    from scripts.lib import n8n_evidence_attestation as A
    doc = A.strict_json(Path(path).read_bytes())
    versions = {RUNTIME_EVIDENCE_SCHEMA, LEGACY_RUNTIME_EVIDENCE_SCHEMA} if schema == RUNTIME_EVIDENCE_SCHEMA else {schema}
    if not isinstance(doc, dict) or doc.get("schema") not in versions:
        raise ValueError(f"{path}: unsupported version; supported {sorted(versions)}")
    if doc.get("schema") == RUNTIME_EVIDENCE_SCHEMA:
        A._closed(doc, {"schema", "workflows"}, "runtime evidence")
        if not isinstance(doc["workflows"], dict):
            raise ValueError("runtime workflows must be an object")
        for obligations in doc["workflows"].values():
            if not isinstance(obligations, dict):
                raise ValueError("runtime obligations must be an object")
            for envelope in obligations.values():
                A._closed(envelope, {"schema", "payload", "signature"}, "attestation")
                A._closed(envelope["payload"], A.PAYLOAD_FIELDS, "payload")
                A._closed(envelope["signature"], {"algorithm", "key_id", "value"}, "signature")
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--active", default=str(DEFAULT_ACTIVE), help="N8nActiveWorkflowSet@v1 file (default scope)")
    ap.add_argument("--all", action="store_true", help="score every committed workflow file instead")
    ap.add_argument("--workflow", nargs="+", default=None, help="score these workflow JSON files")
    ap.add_argument("--platform-facts", default=str(DEFAULT_PLATFORM))
    ap.add_argument("--json", action="store_true", help="print the JSON report instead of markdown")
    ap.add_argument("--out", default=None, help="also write the JSON report here")
    ap.add_argument("--markdown", default=None, help="also write the markdown summary here")
    ap.add_argument("--strict", action="store_true", help="CI lint: exit 1 when any workflow element fails")
    ap.add_argument(
        "--gate",
        choices=("activation",),
        default=None,
        help="fail-closed promotion gate: exit 1 unless every workflow is activation-eligible",
    )
    ap.add_argument("--runtime-evidence", default=None, help=f"{RUNTIME_EVIDENCE_SCHEMA} file (gate input)")
    ap.add_argument("--exceptions", default=None, help=f"{EXCEPTIONS_SCHEMA} file (operator-accepted, gate input)")
    a = ap.parse_args(argv)
    try:
        ctx = build_context(ROOT)
        platform = _load(Path(a.platform_facts)) if a.platform_facts and Path(a.platform_facts).exists() else None
        evidence = _load_optional(a.runtime_evidence, RUNTIME_EVIDENCE_SCHEMA)
        exc = _load_optional(a.exceptions, EXCEPTIONS_SCHEMA).get("exceptions") or []
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
        report = build_report(
            targets, ctx, platform, source=source, gate=a.gate, runtime_evidence=evidence, exceptions=exc
        )
    except (OSError, ValueError, KeyError) as exc_:
        print(f"check_n8n_workflow_framework: cannot read input: {type(exc_).__name__}: {exc_}", file=sys.stderr)
        return 2
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    md = render_markdown(report)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    if a.markdown:
        Path(a.markdown).write_text(md, encoding="utf-8")
    print(text if a.json else md, end="")
    if a.gate and not report["gate"]["eligible"]:
        return 1
    if a.strict and any(r["failing"] for r in report["workflows"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
