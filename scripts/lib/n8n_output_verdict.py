"""Runtime output verdict: "a run that exits 0 but produces nothing is a FAILURE" (2026-10-15; audit DD07).

docs/architecture/n8n/N8N_CONTRACTS_DESIGN.md §5-§6. A health contract (config/n8n_health_contracts.json, kind
``lane``, id = lane id) may declare an ``expected_output`` block (``N8nExpectedOutput@v1``). For a LIVE run that
exited 0, scripts/n8n_run_executor.py reads the lane's IMMUTABLE per-attempt receipt
(scripts/lib/lane_last_receipt.attempt_receipt_path: written once by ``write_lane_receipt`` from the attempt id the
executor put in ``TRADEAI_RUN_ID``) and calls :func:`evaluate`:

=====================  ======================================================================================
verdict                meaning / run outcome
=====================  ======================================================================================
``no_rule``            no contract or no ``expected_output`` block: behaviour unchanged (RUN_DONE stays)
``declared_not_enforced``  (executor only) rule declared but the lane's allowlist entry lacks ``output_receipt: v2``:
                       recorded, run state unchanged (per-lane opt-in, 2026-10-15)
``dry_run_exempt``     a dry run writes no receipt (AGENTS.md §6); not checked (captured dry evidence is (P))
``produced``           ``produced_count >= min_produced`` on a receipt bound to THIS attempt
``empty_allowed``      zero produced with a typed, contract-listed ``empty_reason`` and no fatal skip
``empty_violation``    -> RUN_FAILED ``empty_output`` (fatal skip reasons win over allowed empty reasons)
``unverifiable``       -> RUN_FAILED ``output_unverifiable``: no attempt receipt, not v2, another run's / lane's
                       receipt, or malformed / inconsistent counts. Missing evidence is never success.
=====================  ======================================================================================

``validate_expected_output`` is the closed semantic schema the framework checker (FW-M6) and the executor share:
a malformed declaration (numeric ``produced_field``/``unit``, ``evidence: [{}]``, ``empty_allowed`` without
reasons...) is invalid everywhere, and an invalid declared rule makes the run ``unverifiable`` (fail closed).
Pure: no I/O. AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping

EXPECTED_OUTPUT_SCHEMA = "N8nExpectedOutput@v1"
RULES = ("min_produced", "per_window", "empty_allowed")
EVIDENCE_KINDS = ("store_rows", "file", "receipt_field", "ledger_row")
LANE_RECEIPT_V2 = "LaneRunReceipt@v2"
VERDICTS = (
    "no_rule",
    "declared_not_enforced",
    "dry_run_exempt",
    "produced",
    "empty_allowed",
    "empty_violation",
    "unverifiable",
)
FAILING = {"empty_violation": "empty_output", "unverifiable": "output_unverifiable"}
_REASON_RE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")


def _int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _reasons(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(r, str) and _REASON_RE.fullmatch(r) for r in v)


def validate_expected_output(eo: Any) -> list[str]:
    """Every defect of one ``expected_output`` block (empty = valid). Closed: unknown keys are defects."""
    if not isinstance(eo, Mapping):
        return ["expected_output is not an object"]
    allowed = {
        "schema",
        "unit",
        "rule",
        "min_produced",
        "window_h",
        "produced_field",
        "fatal_skip_reasons",
        "empty_allowed_reasons",
        "evidence",
        "on_violation",
        "receipt",
        "applies_to",
    }
    out = [f"unknown key {k!r}" for k in sorted(set(eo) - allowed)]
    if eo.get("schema") != EXPECTED_OUTPUT_SCHEMA:
        out.append(f"schema != {EXPECTED_OUTPUT_SCHEMA}")
    rule = eo.get("rule")
    if rule not in RULES:
        out.append(f"rule {rule!r} not in {RULES}")
    if rule in ("min_produced", "per_window") and not (_int(eo.get("min_produced")) and eo["min_produced"] >= 1):
        out.append("min_produced must be an int >= 1")
    if rule == "per_window":
        w = eo.get("window_h")
        if not (isinstance(w, (int, float)) and not isinstance(w, bool) and math.isfinite(w) and 0 < w <= 24 * 31):
            out.append("per_window needs a finite window_h in (0, 744]")
    if not (isinstance(eo.get("produced_field"), str) and _FIELD_RE.fullmatch(eo["produced_field"])):
        out.append("produced_field must be a field name string")
    if not (isinstance(eo.get("unit"), str) and eo["unit"].strip()):
        out.append("unit must be a non-empty string")
    if not _reasons(eo.get("fatal_skip_reasons")):
        out.append("fatal_skip_reasons must be a list of typed reasons")
    allowed_empty = eo.get("empty_allowed_reasons")
    if allowed_empty is not None and not _reasons(allowed_empty):
        out.append("empty_allowed_reasons must be a list of typed reasons")
    if rule in ("empty_allowed", "per_window") and not (_reasons(allowed_empty) and allowed_empty):
        out.append(f"{rule} needs a non-empty empty_allowed_reasons list")
    if _reasons(allowed_empty) and _reasons(eo.get("fatal_skip_reasons")):
        both = set(allowed_empty) & set(eo["fatal_skip_reasons"])
        if both:
            out.append(f"reasons both fatal and allowed: {sorted(both)}")
    ev = eo.get("evidence")
    if not (isinstance(ev, list) and ev):
        out.append("evidence list empty")
    else:
        for i, e in enumerate(ev):
            if not (
                isinstance(e, Mapping)
                and e.get("kind") in EVIDENCE_KINDS
                and isinstance(e.get("ref"), str)
                and e["ref"].strip()
            ):
                out.append(f"evidence[{i}] needs kind in {EVIDENCE_KINDS} and a ref")
    rec = eo.get("receipt")
    if rec is not None and not (isinstance(rec, str) and not rec.startswith("/") and ".." not in rec):
        out.append("receipt must be a relative path")
    return out


def evaluate(
    rule: Mapping[str, Any] | None,
    doc: Any,
    *,
    run_id: str,
    lane_id: str,
    mode: str,
) -> dict[str, Any]:
    """The ``output_verdict`` block for one finished attempt (see the module table)."""
    if rule is None:
        return {"verdict": "no_rule"}
    base: dict[str, Any] = {"rule": rule.get("rule"), "contract_id": lane_id}
    if mode != "live":
        return {**base, "verdict": "dry_run_exempt"}
    problems = validate_expected_output(rule)
    if problems:
        return {**base, "verdict": "unverifiable", "why": "rule_invalid", "problems": problems[:5]}

    def unverifiable(why: str) -> dict[str, Any]:
        return {**base, "verdict": "unverifiable", "why": why}

    if not isinstance(doc, Mapping):
        return unverifiable("attempt_receipt_missing")
    if doc.get("schema") != LANE_RECEIPT_V2:
        return unverifiable("receipt_not_v2")
    if doc.get("run_id") != run_id or doc.get("lane_id") != lane_id:
        return unverifiable("receipt_identity_mismatch")
    produced = doc.get(rule["produced_field"])
    attempted = doc.get("attempted_count")
    skipped = doc.get("skipped_reasons") or {}
    if not _int(produced) or produced < 0:
        return unverifiable("produced_count_invalid")
    if attempted is not None and (not _int(attempted) or attempted < produced):
        return unverifiable("counts_inconsistent")
    if not isinstance(skipped, Mapping) or not all(_int(v) and v >= 0 for v in skipped.values()):
        return unverifiable("skipped_reasons_invalid")
    base.update({"produced_count": produced, "attempted_count": attempted, "skipped_reasons": dict(skipped)})
    if doc.get("status") != "ok":
        return {**base, "verdict": "empty_violation", "why": "receipt_status_failed"}
    minimum = int(rule.get("min_produced") or 1)
    if produced >= minimum:
        return {**base, "verdict": "produced"}
    fatal = sorted(r for r, c in skipped.items() if c > 0 and r in set(rule["fatal_skip_reasons"]))
    if fatal:
        return {**base, "verdict": "empty_violation", "why": "fatal_skip", "fatal": fatal}
    if rule["rule"] == "min_produced":
        return {**base, "verdict": "empty_violation", "why": "below_min_produced"}
    reason = doc.get("empty_reason")
    if isinstance(reason, str) and reason in set(rule.get("empty_allowed_reasons") or ()):
        out = {**base, "verdict": "empty_allowed", "empty_reason": reason}
        if rule["rule"] == "per_window":
            out["window"] = "evaluated by the health monitors (P), not per run"
        return out
    return {**base, "verdict": "empty_violation", "why": "empty_reason_not_allowed"}
