"""Workflow health contracts for n8n lanes and workflows (N8nHealthContract@v1) — schema, targets and validation.

Operator 2026-10-10 ~16:45 ET: "there should be something that's developed for each particular workflow: What is it
supposed to do? What does it connect to? What does positive mean? What does degraded mean? What is it measuring
against if it doesn't know?"

A contract answers those five questions per lane / workflow in ``config/n8n_health_contracts.json``:

* ``purpose``        what it is supposed to do (one sentence) and its business function;
* ``connects_to``    every edge (upstream input, downstream output, relay/gateway/executor, external provider) with
                     its direction (``read`` / ``write``) and where the fact came from;
* ``healthy`` / ``degraded`` / ``failed``   concrete observable criteria, each ``{"check", "text"}``;
* ``baseline``       what the criteria are measured against: ``OPERATOR_SLO`` (an operator-set number),
                     ``LEARNED_PROVISIONAL`` (>= MIN_LEARNED_RUNS finished live runs in the coordination ledger:
                     p50/p95 duration, failure rate; freshness = 2x cadence) or ``CLASS_DEFAULT_PROVISIONAL``
                     (fewer runs: conservative defaults per class, always with a ``review_by`` date);
* ``alerting``       SIEM severity and notifier priority for degraded vs failed;
* ``remediation``    the lane's catalogue entry (config/n8n_remediation_catalogue.json), auto actions, and whether
                     it is excluded from LLM diagnosis;
* ``owner``, ``evidence`` (where to look and the read-only queries), ``review_by``.

Why a separate file and not a block on each ``config/lane_registry.json`` row:
1. ``scripts/reconcile_lane_registry.py`` regenerates generated rows; a block on 55 rows would force each one to be
   ``adopted_from_generator`` and land through the one-registry-PR-at-a-time train (AGENTS.md §23.11), colliding with
   every wave PR;
2. the six generic workflows are not registry lanes (they are declared by ``workflows/INDEX.json``), and a contract
   must exist for them too;
3. a contract is reviewed by the lane's owner, on its own cadence (``review_by``), not by the registry train.
The gate (``scripts/check_n8n_health_contracts.py``) joins the two files, so nothing can drift silently.

Pure: no network, no DB, no send. ``MBI_BEHAVIOR = 0``.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

SCHEMA = "N8nHealthContract@v1"
FILE_SCHEMA = "N8nHealthContracts@v1"
ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_PATH = ROOT / "config" / "n8n_health_contracts.json"
REGISTRY_PATH = ROOT / "config" / "lane_registry.json"
GENERIC_INDEX_PATH = ROOT / "docs" / "implementation" / "n8n-maturity" / "workflows" / "INDEX.json"

UNKNOWN = "UNKNOWN — needs owner"
STATUSES = ("DRAFT", "REVIEWED")
BASELINE_BASES = ("OPERATOR_SLO", "LEARNED_PROVISIONAL", "CLASS_DEFAULT_PROVISIONAL")
KINDS = ("lane", "generic_workflow", "host_monitor")
DIRECTIONS = ("read", "write", "read_write", "calls")
STAGES_NEEDING_CONTRACT = ("shadow", "canary", "cutover")
STAGES_NEEDING_REVIEW = ("canary", "cutover")
MIN_LEARNED_RUNS = 14
#: Host monitors of the n8n chain: they watch n8n, so they need a contract even though no n8n workflow fires them.
HOST_MONITOR_LANES = ("n8n-siem-bridge", "n8n-failure-diagnosis", "incident-notifier")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def generic_workflow_ids(index: Mapping[str, Any]) -> list[str]:
    return sorted(str(w["id"]) for w in index.get("workflows") or [] if w.get("id"))


def registry_targets(registry: Mapping[str, Any]) -> dict[str, str]:
    """lane_id -> why it needs a contract. Every lane n8n fires or is about to fire, plus the host monitors.

    * ``stage:<s>``          ``scheduler.stage`` in shadow / canary / cutover (the §23.11 / 4.4.0 rows);
    * ``dispatch:<mode>``    a ``dispatch`` block with mode other than ``off``;
    * ``r1_pending``         a staged wave-3 row (activated by a later registry PR into shadow);
    * ``n8n:<state>``        ``scheduler.kind == "n8n"`` and not RETIRED (per-lane live workflows, dispatcher rows);
    * ``host_monitor``       one of HOST_MONITOR_LANES.
    """
    out: dict[str, str] = {}
    for row in registry.get("lanes") or []:
        lane = str(row.get("lane_id") or "")
        if not lane:
            continue
        sched = row.get("scheduler") or {}
        stage = sched.get("stage")
        mode = (row.get("dispatch") or {}).get("mode")
        if stage in STAGES_NEEDING_CONTRACT:
            out[lane] = f"stage:{stage}"
        elif mode and mode != "off":
            out[lane] = f"dispatch:{mode}"
        elif "r1_pending" in row:
            out[lane] = "r1_pending"
        elif sched.get("kind") == "n8n" and str(row.get("state") or "").upper() != "RETIRED":
            out[lane] = f"n8n:{row.get('state')}"
        elif lane in HOST_MONITOR_LANES:
            out[lane] = "host_monitor"
    return out


def stage_of(row: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not row:
        return None
    s = (row.get("scheduler") or {}).get("stage")
    if s:
        return str(s)
    pend = ((row.get("r1_pending") or {}).get("scheduler") or {}).get("stage")
    return str(pend) if pend else None


def _criteria_errors(name: str, crit: Any) -> list[str]:
    if not isinstance(crit, list) or not crit:
        return [f"{name} is empty"]
    errs = []
    for i, c in enumerate(crit):
        if not isinstance(c, Mapping) or not str(c.get("check") or "").strip() or not str(c.get("text") or "").strip():
            errs.append(f"{name}[{i}] needs non-empty check and text")
    return errs


def validate_contract(c: Mapping[str, Any]) -> list[str]:
    """Structural errors of one contract (empty list = valid)."""
    errs: list[str] = []
    if c.get("schema") != SCHEMA:
        errs.append(f"schema must be {SCHEMA}")
    if c.get("kind") not in KINDS:
        errs.append(f"kind must be one of {KINDS}")
    if c.get("status") not in STATUSES:
        errs.append(f"status must be one of {STATUSES}")
    purpose = c.get("purpose") or {}
    if not str(purpose.get("text") or "").strip():
        errs.append("purpose.text is empty (write UNKNOWN — needs owner, never leave it blank)")
    if not str(c.get("owner") or "").strip():
        errs.append("owner is empty")
    edges = c.get("connects_to")
    if not isinstance(edges, list) or not edges:
        errs.append("connects_to is empty")
    else:
        for i, e in enumerate(edges):
            if not isinstance(e, Mapping) or not e.get("name") or e.get("direction") not in DIRECTIONS:
                errs.append(f"connects_to[{i}] needs name and direction in {DIRECTIONS}")
    for name in ("healthy", "degraded", "failed"):
        errs += _criteria_errors(name, c.get(name))
    base = c.get("baseline") or {}
    if base.get("basis") not in BASELINE_BASES:
        errs.append(f"baseline.basis must be one of {BASELINE_BASES}")
    if base.get("basis") != "OPERATOR_SLO" and not _DATE_RE.match(str(c.get("review_by") or "")):
        errs.append("a provisional baseline needs review_by (YYYY-MM-DD)")
    al = c.get("alerting") or {}
    for k in ("degraded", "failed"):
        if not str((al.get(k) or {}).get("notifier_priority") or "").strip():
            errs.append(f"alerting.{k}.notifier_priority is empty")
    if "remediation" not in c or not isinstance(c.get("remediation"), Mapping):
        errs.append("remediation block missing")
    ev = c.get("evidence") or {}
    if not ev.get("verify"):
        errs.append("evidence.verify is empty")
    return errs


def unknown_fields(c: Mapping[str, Any]) -> list[str]:
    """Dotted paths whose value carries the UNKNOWN marker (for counts and the review gate)."""
    found: list[str] = []

    def walk(v: Any, path: str) -> None:
        if isinstance(v, Mapping):
            for k, x in v.items():
                walk(x, f"{path}.{k}" if path else str(k))
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")
        elif isinstance(v, str) and "UNKNOWN" in v:
            found.append(path)

    walk(c, "")
    return found


def check(
    contracts_doc: Mapping[str, Any],
    registry: Mapping[str, Any],
    index: Mapping[str, Any],
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Join contracts with the registry and the generic INDEX. Returns {errors, warnings, counts}.

    Errors (the gate fails):
      * MISSING_CONTRACT     a registry target (registry_targets) or a generic workflow has no contract;
      * INVALID_CONTRACT     a contract fails validate_contract;
      * DRAFT_NOT_GRANDFATHERED  a DRAFT contract for a lane not in the file's ``grandfathered_draft`` list
                             (a new lane writes and gets its contract REVIEWED before its registry PR);
      * DRAFT_AT_LIVE_STAGE  a lane at canary or cutover whose contract is not REVIEWED, or still has UNKNOWN fields;
      * ORPHAN_CONTRACT      a lane contract whose lane_id is no registry row.
    Warnings: a review_by date in the past (stale provisional baseline).
    """
    today = today or date.today()
    rows = {str(r.get("lane_id")): r for r in registry.get("lanes") or []}
    contracts = {str(c.get("id")): c for c in contracts_doc.get("contracts") or []}
    grandfathered = set(contracts_doc.get("grandfathered_draft") or [])
    errors: list[str] = []
    warnings: list[str] = []
    targets = registry_targets(registry)
    generic = generic_workflow_ids(index)
    for lane, why in sorted(targets.items()):
        if lane not in contracts:
            errors.append(f"MISSING_CONTRACT {lane} ({why}): write its health contract before its registry PR")
    for wf in generic:
        if wf not in contracts:
            errors.append(f"MISSING_CONTRACT {wf} (generic workflow)")
    for cid, c in sorted(contracts.items()):
        for e in validate_contract(c):
            errors.append(f"INVALID_CONTRACT {cid}: {e}")
        if c.get("kind") in ("lane", "host_monitor") and cid not in rows:
            errors.append(f"ORPHAN_CONTRACT {cid}: no config/lane_registry.json row")
        if c.get("status") == "DRAFT" and cid not in grandfathered:
            errors.append(f"DRAFT_NOT_GRANDFATHERED {cid}: a new lane's contract must be REVIEWED")
        st = stage_of(rows.get(cid))
        if st in STAGES_NEEDING_REVIEW and (c.get("status") != "REVIEWED" or unknown_fields(c)):
            errors.append(f"DRAFT_AT_LIVE_STAGE {cid}: stage {st} needs a REVIEWED contract with no UNKNOWN field")
        rb = str(c.get("review_by") or "")
        if _DATE_RE.match(rb) and date.fromisoformat(rb) < today:
            warnings.append(f"REVIEW_OVERDUE {cid}: review_by {rb}")
    counts = {
        "contracts": len(contracts),
        "targets": len(targets) + len(generic),
        "draft": sum(1 for c in contracts.values() if c.get("status") == "DRAFT"),
        "reviewed": sum(1 for c in contracts.values() if c.get("status") == "REVIEWED"),
        "unknown_fields": sum(len(unknown_fields(c)) for c in contracts.values()),
        "by_baseline": _count((c.get("baseline") or {}).get("basis") for c in contracts.values()),
        "by_kind": _count(c.get("kind") for c in contracts.values()),
    }
    return {"errors": errors, "warnings": warnings, "counts": counts}


def _count(values: Iterable[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return dict(sorted(out.items()))
