#!/usr/bin/env python3
"""PACKET E — Phase 10 promotion gate (PREPARE-ONLY / DEFAULT-DISABLED).

Preflight-only promotion *gate* for reflective SHADOW agents. This packet:

  * NEVER marks any agent OPERATIONAL (hard invariant; Phase 11 is required).
  * NEVER enables timers/cron, broker, orders, approvals, 2FA, or production
    ``trade_ai`` writes.
  * NEVER logs a DSN or any secret material.
  * Default-disabled: without the typed ack + explicit agent list + an action
    flag, prints PREPARE-ONLY and exits non-zero.

Actions:
  --self-check   Prove guards fire (no DB, no files written).
  --preflight    Evaluate Packet D / LAB evidence gates for the listed agents.
  --execute      STILL refuses OPERATIONAL mutation. Optionally writes a signed
                 *intent* record under docs/operations/promotion_intents/ that
                 documents the request; Phase 11 human sign-off is still required.

Exit codes: 0 ok · 2 usage/gate/disabled refusal · 3 prepare-only · 4 preflight fail
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

ACK_TOKEN = "PROMOTE-AGENT-OPERATIONAL-E"
PACKET = "E"
PHASE = "10"
PHASE11_REFUSAL = (
    "promotion execute not enabled until Phase 11 human sign-off file"
)
ENVIRONMENT = "SHADOW"

# Known SHADOW fleet ids that may appear in an intent (never auto-promoted).
ALLOWED_AGENT_IDS = frozenset({
    "sentinel",
    "darwin",
    "iris",
    "reflection",
    "maria",
    "vega",
    "risk_agent",
    "aegis",
    # Packet D stable ids (SHADOW acceptance producer/reviewer/scorer)
    "watch_producer_shadow",
    "sentinel_shadow",
    "darwin_shadow",
    "iris_shadow",
    "nightly_reflection_shadow",
})

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INTENT_DIR = _REPO_ROOT / "docs" / "operations" / "promotion_intents"
_SIGN_OFF_DIR = _REPO_ROOT / "docs" / "operations" / "promotion_signoffs"

# Forbidden tokens that would indicate authority expansion in this packet.
FORBIDDEN_MUTATIONS = (
    "OPERATIONAL",
    "deployment_state",
    "systemctl enable",
    "timer enable",
    "crontab",
    "broker",
    "submit_order",
    "place_order",
)


class PromotionGateError(RuntimeError):
    """Hard refusal (usage, ack, authority, or Phase 11 block)."""


class PreflightFailed(RuntimeError):
    """Evidence gates did not pass."""


# ---------------------------------------------------------------------------
# Pure helpers (no secrets, no DSN logging)
# ---------------------------------------------------------------------------

def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _content_hash(obj: Any) -> str:
    return hashlib.sha256(_canonical_json(obj).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _print_disabled(reason: str) -> None:
    print(f"=== PACKET {PACKET} === PREPARE-ONLY / DEFAULT-DISABLED ===")
    print(f"[E] {reason}")
    print(
        f"[E] usage: {os.path.basename(sys.argv[0])} --preflight "
        f"--agent-id <ID> [--agent-id <ID> ...] --ack {ACK_TOKEN} "
        f"[--packet-d-report PATH] [--lab-counts PATH]"
    )
    print(
        f"[E]         {os.path.basename(sys.argv[0])} --execute "
        f"--agent-id <ID> ... --ack {ACK_TOKEN} "
        f"[--packet-d-report PATH] [--lab-counts PATH] [--write-intent]"
    )
    print(f"[E]         {os.path.basename(sys.argv[0])} --self-check")
    print(
        "[E] NEVER marks any agent OPERATIONAL. Timers/cron stay disabled. "
        "CANDIDATE lessons are not production policy. DSN never logged."
    )


def parse_agent_ids(raw: list[str] | None, agents_csv: str | None = None) -> list[str]:
    """Normalize --agent-id / --agents into a de-duplicated ordered list."""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        aid = str(item).strip()
        if not aid or aid in seen:
            continue
        seen.add(aid)
        out.append(aid)
    if agents_csv:
        for part in str(agents_csv).split(","):
            aid = part.strip()
            if not aid or aid in seen:
                continue
            seen.add(aid)
            out.append(aid)
    return out


def validate_agent_ids(agent_ids: list[str]) -> None:
    if not agent_ids:
        raise PromotionGateError(
            "explicit AGENT_ID list required (--agent-id ID and/or --agents a,b)"
        )
    unknown = [a for a in agent_ids if a not in ALLOWED_AGENT_IDS]
    if unknown:
        raise PromotionGateError(
            f"unknown/disallowed agent id(s): {', '.join(unknown)} "
            f"(allowed: {', '.join(sorted(ALLOWED_AGENT_IDS))})"
        )
    # Refuse strings that look like DSN / secrets
    for aid in agent_ids:
        if re.search(r"(password|secret|://|@)", aid, re.I):
            raise PromotionGateError("agent id looks like secret material; refused")


def require_ack(ack: str) -> None:
    if ack != ACK_TOKEN:
        raise PromotionGateError(
            f"--ack must equal {ACK_TOKEN} (typed acknowledgement)"
        )


# ---------------------------------------------------------------------------
# Evidence loading (file-based; optional LAB counts JSON — never a DSN log)
# ---------------------------------------------------------------------------

def load_packet_d_report(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    if not path.is_file():
        raise PromotionGateError(f"packet-d report not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PromotionGateError("packet-d report must be a JSON object")
    return data


def load_lab_counts(path: Path | None) -> dict[str, Any]:
    """Load operator-supplied LAB/SHADOW counts JSON.

    Expected shape (all optional ints/bools)::

        {
          "reviews": 120,
          "self_review": 0,
          "kb_lessons_candidate": 20,
          "read_only_api": true
        }
    """
    if path is None:
        return {}
    if not path.is_file():
        raise PromotionGateError(f"lab-counts file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PromotionGateError("lab-counts must be a JSON object")
    return data


def _metrics_from_packet_d(report: Mapping[str, Any]) -> dict[str, Any]:
    """Extract gate-relevant numbers from a Packet D report JSON."""
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else report
    persisted = (
        metrics.get("persisted")
        if isinstance(metrics.get("persisted"), dict)
        else report.get("persisted") if isinstance(report.get("persisted"), dict) else {}
    )
    reviews = int(persisted.get("reviews") or 0)
    # Packet D reports independence as rates; self_review count derived if present
    self_review = int(
        metrics.get("self_review")
        or metrics.get("self_reviews")
        or report.get("self_review")
        or 0
    )
    # Independence = 1.0 implies self_review=0 when reviews>0
    ri = metrics.get("reviewer_independence")
    if ri is not None and float(ri) >= 1.0 and self_review == 0:
        self_review = 0
    elif ri is not None and float(ri) < 1.0:
        self_review = max(self_review, 1)

    kb_cand = int(
        persisted.get("kb_lessons")
        or metrics.get("candidate_lessons")
        or report.get("candidate_lessons")
        or 0
    )
    agents_op = int(
        metrics.get("agents_marked_operational")
        or report.get("agents_marked_operational")
        or 0
    )
    accepted = bool(report.get("accepted_thresholds", metrics.get("accepted_thresholds", False)))
    return {
        "reviews": reviews,
        "self_review": self_review,
        "kb_lessons_candidate": kb_cand,
        "agents_marked_operational": agents_op,
        "accepted_thresholds": accepted,
        "source": "packet_d_report",
    }


def verify_read_only_api_contract() -> dict[str, Any]:
    """Static check: read plane is GET-only and zero-authority (no DSN)."""
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    try:
        from agent_runtime.read_api import READ_ROUTES, ReadOnlyAgentRuntimeAPI
        from agent_runtime import read_http
    except Exception as exc:  # pragma: no cover - import environment issues
        return {
            "ok": False,
            "detail": f"read_api import failed: {type(exc).__name__}",
        }

    bad_methods = [r.method for r in READ_ROUTES if r.method.upper() != "GET"]
    methods = {m for m in dir(ReadOnlyAgentRuntimeAPI) if not m.startswith("_")}
    mutation_verbs = {
        "create", "update", "delete", "promote", "execute", "approve",
        "schedule", "enable", "write", "insert", "mutate",
    }
    leak = sorted(m for m in methods if any(v in m.lower() for v in mutation_verbs))
    envelope = read_http.zero_authority_envelope("probe", "packet-e-preflight")
    ro = bool(envelope.get("read_only") is True)
    auth = envelope.get("authority") if isinstance(envelope.get("authority"), dict) else {}
    zero = all(not bool(v) for v in auth.values()) if auth else False
    ok = (not bad_methods) and (not leak) and ro and zero
    return {
        "ok": ok,
        "get_only": not bad_methods,
        "no_mutation_methods": not leak,
        "read_only_envelope": ro and zero,
        "detail": "read_only API contract holds" if ok else "read_only API contract broken",
    }


def merge_evidence(
    packet_d: Mapping[str, Any],
    lab_counts: Mapping[str, Any],
) -> dict[str, Any]:
    """Combine Packet D report + LAB counts; lab_counts override when present."""
    base: dict[str, Any] = {
        "reviews": 0,
        "self_review": 0,
        "kb_lessons_candidate": 0,
        "agents_marked_operational": 0,
        "accepted_thresholds": False,
        "read_only_api": False,
        "sources": [],
    }
    if packet_d:
        extracted = _metrics_from_packet_d(packet_d)
        base.update({k: extracted[k] for k in (
            "reviews", "self_review", "kb_lessons_candidate",
            "agents_marked_operational", "accepted_thresholds",
        )})
        base["sources"].append("packet_d_report")
    if lab_counts:
        for key in (
            "reviews", "self_review", "kb_lessons_candidate",
            "agents_marked_operational",
        ):
            if key in lab_counts and lab_counts[key] is not None:
                base[key] = int(lab_counts[key])
        if "accepted_thresholds" in lab_counts:
            base["accepted_thresholds"] = bool(lab_counts["accepted_thresholds"])
        if "read_only_api" in lab_counts:
            base["read_only_api"] = bool(lab_counts["read_only_api"])
        base["sources"].append("lab_counts")
    return base


def run_preflight(
    agent_ids: list[str],
    *,
    packet_d_report: Path | None = None,
    lab_counts_path: Path | None = None,
    require_evidence: bool = True,
) -> dict[str, Any]:
    """Evaluate promotion preflight gates. Does not mutate agent status."""
    validate_agent_ids(agent_ids)
    report = load_packet_d_report(packet_d_report)
    lab = load_lab_counts(lab_counts_path)
    evidence = merge_evidence(report, lab)
    read_api = verify_read_only_api_contract()
    if evidence.get("read_only_api") is not True:
        # Prefer static contract when lab_counts did not assert it
        evidence["read_only_api"] = bool(read_api.get("ok"))

    gates: list[dict[str, Any]] = []
    fails: list[str] = []

    def _gate(name: str, ok: bool, detail: str) -> None:
        gates.append({"gate": name, "ok": ok, "detail": detail})
        if not ok:
            fails.append(f"{name}: {detail}")

    has_source = bool(evidence.get("sources"))
    if require_evidence and not has_source:
        _gate(
            "evidence_source",
            False,
            "need --packet-d-report and/or --lab-counts (no live DSN required for preflight)",
        )
    else:
        _gate("evidence_source", True if has_source else not require_evidence, "ok")

    reviews = int(evidence.get("reviews") or 0)
    _gate("reviews_gt_0", reviews > 0, f"reviews={reviews}")

    self_review = int(evidence.get("self_review") or 0)
    _gate("self_review_eq_0", self_review == 0, f"self_review={self_review}")

    kb = int(evidence.get("kb_lessons_candidate") or 0)
    _gate("kb_candidate_exists", kb > 0, f"kb_lessons_candidate={kb}")

    _gate(
        "read_only_api",
        bool(evidence.get("read_only_api")),
        read_api.get("detail") or "read_only_api",
    )

    agents_op = int(evidence.get("agents_marked_operational") or 0)
    _gate(
        "no_operational_from_packet_d",
        agents_op == 0,
        f"agents_marked_operational={agents_op}",
    )

    # Phase 9 independence: if Packet D report present, require independence rates
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    if metrics:
        ri = float(metrics.get("reviewer_independence") or 0.0)
        si = float(metrics.get("scorer_independence") or 0.0)
        _gate("phase9_reviewer_independence", ri >= 1.0, f"reviewer_independence={ri}")
        _gate("phase9_scorer_independence", si >= 1.0, f"scorer_independence={si}")

    # Catalog: none of the requested agents may already claim OPERATIONAL in config
    catalog_path = _REPO_ROOT / "config" / "agent_runtime_mvl.json"
    if catalog_path.is_file():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        agents = catalog.get("agents") if isinstance(catalog.get("agents"), dict) else {}
        for aid in agent_ids:
            entry = agents.get(aid) if isinstance(agents.get(aid), dict) else None
            if entry is None:
                # Packet D shadow ids are not catalog entries — skip
                continue
            state = str(entry.get("deployment_state") or "")
            _gate(
                f"catalog_not_operational:{aid}",
                state != "OPERATIONAL",
                f"deployment_state={state}",
            )

    # Phase 11 sign-off file must NOT be required here — we only note absence
    signoff_present = any(_SIGN_OFF_DIR.glob("*.json")) if _SIGN_OFF_DIR.is_dir() else False
    _gate(
        "phase11_signoff_absent_expected",
        True,  # informational — never auto-promote even if present in Phase 10
        f"phase11_signoff_files_present={signoff_present} (Phase 10 never promotes)",
    )

    ok = not fails
    result = {
        "packet": PACKET,
        "phase": PHASE,
        "environment": ENVIRONMENT,
        "agent_ids": list(agent_ids),
        "ok": ok,
        "gates": gates,
        "failures": fails,
        "evidence": {
            "reviews": reviews,
            "self_review": self_review,
            "kb_lessons_candidate": kb,
            "read_only_api": bool(evidence.get("read_only_api")),
            "agents_marked_operational": agents_op,
            "sources": list(evidence.get("sources") or []),
        },
        "invariants": {
            "agents_marked_operational": 0,
            "timers_enabled": False,
            "broker_authority": "DENIED",
            "lesson_lifecycle_promoted": False,
            "production_trade_ai_writes": False,
        },
        "note": (
            "PREFLIGHT ONLY — no agent marked OPERATIONAL; "
            "CANDIDATE lessons ≠ production policy; timers/cron remain disabled"
        ),
    }
    if not ok:
        raise PreflightFailed("; ".join(fails))
    return result


# ---------------------------------------------------------------------------
# Execute path — NEVER sets OPERATIONAL; optional signed intent only
# ---------------------------------------------------------------------------

def assert_no_operational_mutation() -> None:
    """Hard invariant for this packet's process: never claim OPERATIONAL set."""
    # Placeholder for future hooks — intentionally empty side-effect free.
    return None


def build_intent_record(
    agent_ids: list[str],
    preflight: Mapping[str, Any],
    *,
    operator: str = "operator",
) -> dict[str, Any]:
    """Build a signed promotion *intent* (not a promotion)."""
    body = {
        "packet": PACKET,
        "phase": PHASE,
        "kind": "PROMOTION_INTENT_ONLY",
        "not_operational": True,
        "agents_marked_operational": 0,
        "agent_ids": list(agent_ids),
        "requested_at": _utc_now(),
        "operator": operator,
        "ack_token_name": "PROMOTE-AGENT-OPERATIONAL-E",
        "preflight_ok": bool(preflight.get("ok")),
        "preflight_evidence": preflight.get("evidence"),
        "phase11_required": True,
        "phase11_message": PHASE11_REFUSAL,
        "constraints": {
            "timers_cron_remain_disabled": True,
            "broker_denied": True,
            "production_trade_ai_writes": False,
            "candidate_lessons_not_policy": True,
            "dsn_never_logged": True,
        },
    }
    body["content_hash"] = _content_hash({k: v for k, v in body.items() if k != "content_hash"})
    return body


def write_intent_record(record: Mapping[str, Any], dest_dir: Path | None = None) -> Path:
    """Write intent under docs/operations/promotion_intents/. Never touches agent status."""
    d = dest_dir or _INTENT_DIR
    d.mkdir(parents=True, exist_ok=True)
    agents = "-".join(record.get("agent_ids") or ["unknown"])[:80]
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = d / f"INTENT_{ts}_{agents}.json"
    # Refuse to write if payload claims OPERATIONAL mutation
    blob = _canonical_json(record)
    if '"agents_marked_operational":1' in blob or '"deployment_state":"OPERATIONAL"' in blob:
        raise PromotionGateError("intent payload must not claim OPERATIONAL mutation")
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def run_execute(
    agent_ids: list[str],
    *,
    packet_d_report: Path | None = None,
    lab_counts_path: Path | None = None,
    write_intent: bool = False,
    intent_dir: Path | None = None,
    operator: str = "operator",
) -> dict[str, Any]:
    """Execute path: preflight, then refuse OPERATIONAL; optional intent file.

    Phase 10 hard rule: agent deployment_state is never updated to OPERATIONAL.
    """
    assert_no_operational_mutation()
    preflight = run_preflight(
        agent_ids,
        packet_d_report=packet_d_report,
        lab_counts_path=lab_counts_path,
        require_evidence=True,
    )

    out: dict[str, Any] = {
        "packet": PACKET,
        "phase": PHASE,
        "action": "execute",
        "agent_ids": list(agent_ids),
        "preflight": preflight,
        "agents_marked_operational": 0,
        "operational_mutation": False,
        "phase11_required": True,
        "message": PHASE11_REFUSAL,
        "intent_path": None,
    }

    # Explicit: do NOT update any agent catalog / DB status.
    # (No code path here opens a DB connection or rewrites config.)

    if write_intent:
        record = build_intent_record(agent_ids, preflight, operator=operator)
        path = write_intent_record(record, dest_dir=intent_dir)
        out["intent_path"] = str(path.relative_to(_REPO_ROOT)) if path.is_relative_to(_REPO_ROOT) else str(path)
        out["intent_hash"] = record.get("content_hash")
        out["message"] = (
            f"{PHASE11_REFUSAL}; wrote signed intent only at {out['intent_path']} "
            "(agents remain SHADOW; no OPERATIONAL status change)"
        )
    else:
        out["message"] = (
            f"{PHASE11_REFUSAL} "
            "(re-run with --write-intent to record a signed intent under "
            "docs/operations/promotion_intents/ without promoting anyone)"
        )

    assert out["agents_marked_operational"] == 0
    assert out["operational_mutation"] is False
    return out


# ---------------------------------------------------------------------------
# Self-check (unit-testable, no DB)
# ---------------------------------------------------------------------------

def self_check() -> dict[str, Any]:
    """Prove default-disabled, missing-ack refuse, execute never sets OPERATIONAL."""
    results: list[dict[str, Any]] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        results.append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            raise PromotionGateError(f"self-check failed: {name}: {detail}")

    # 1) missing ack refuses
    try:
        require_ack("")
        _check("missing_ack_refuses", False, "should have raised")
    except PromotionGateError:
        _check("missing_ack_refuses", True)

    try:
        require_ack("WRONG-TOKEN")
        _check("wrong_ack_refuses", False)
    except PromotionGateError:
        _check("wrong_ack_refuses", True)

    # 2) empty agent list refuses
    try:
        validate_agent_ids([])
        _check("empty_agents_refuses", False)
    except PromotionGateError:
        _check("empty_agents_refuses", True)

    # 3) execute without evidence fails preflight (not promote)
    try:
        run_execute(["sentinel"], write_intent=False)
        _check("execute_without_evidence_refuses", False)
    except PreflightFailed:
        _check("execute_without_evidence_refuses", True)

    # 4) execute with good evidence still leaves agents_marked_operational=0
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        lab = {
            "reviews": 120,
            "self_review": 0,
            "kb_lessons_candidate": 20,
            "agents_marked_operational": 0,
            "read_only_api": True,
            "accepted_thresholds": True,
        }
        counts_path = tdp / "counts.json"
        counts_path.write_text(json.dumps(lab), encoding="utf-8")
        # Synthetic Packet D report with independence
        pd = {
            "accepted_thresholds": True,
            "metrics": {
                "reviewer_independence": 1.0,
                "scorer_independence": 1.0,
                "agents_marked_operational": 0,
                "candidate_lessons": 20,
                "persisted": {"reviews": 120, "kb_lessons": 20},
            },
            "persisted": {"reviews": 120, "kb_lessons": 20},
        }
        pd_path = tdp / "packet_d.json"
        pd_path.write_text(json.dumps(pd), encoding="utf-8")
        intent_dir = tdp / "intents"
        out = run_execute(
            ["sentinel", "darwin"],
            packet_d_report=pd_path,
            lab_counts_path=counts_path,
            write_intent=True,
            intent_dir=intent_dir,
        )
        _check(
            "execute_never_sets_operational",
            out.get("agents_marked_operational") == 0
            and out.get("operational_mutation") is False,
            str(out.get("message")),
        )
        _check(
            "execute_writes_intent_only",
            out.get("intent_path") is not None and PHASE11_REFUSAL in str(out.get("message")),
        )
        # Intent file must not claim OPERATIONAL
        intent_files = list(intent_dir.glob("INTENT_*.json"))
        _check("intent_file_written", len(intent_files) == 1)
        if intent_files:
            body = intent_files[0].read_text(encoding="utf-8")
            _check(
                "intent_not_operational",
                "OPERATIONAL" not in body or "not_operational" in body,
            )
            parsed = json.loads(body)
            _check(
                "intent_agents_marked_operational_zero",
                parsed.get("agents_marked_operational") == 0,
            )

    # 5) catalog file not rewritten (still no OPERATIONAL for wave-1 agents)
    catalog = _REPO_ROOT / "config" / "agent_runtime_mvl.json"
    if catalog.is_file():
        data = json.loads(catalog.read_text(encoding="utf-8"))
        for aid, entry in (data.get("agents") or {}).items():
            if not isinstance(entry, dict):
                continue
            _check(
                f"catalog_{aid}_not_operational",
                entry.get("deployment_state") != "OPERATIONAL",
                str(entry.get("deployment_state")),
            )

    return {
        "packet": PACKET,
        "self_check": "OK",
        "checks": results,
        "agents_marked_operational": 0,
        "note": "default-disabled; missing ack refuses; execute never sets OPERATIONAL",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        add_help=True,
        description="Packet E Phase 10 promotion gate (prepare-only; never OPERATIONAL)",
    )
    p.add_argument("--self-check", action="store_true", help="prove guards; no DB")
    p.add_argument("--preflight", action="store_true", help="run evidence gates only")
    p.add_argument(
        "--execute",
        action="store_true",
        help="still refuses OPERATIONAL; optional --write-intent for signed intent only",
    )
    p.add_argument("--ack", default="", help=f"typed acknowledgement ({ACK_TOKEN})")
    p.add_argument(
        "--agent-id",
        action="append",
        default=[],
        dest="agent_ids",
        help="agent id to gate (repeatable; required for preflight/execute)",
    )
    p.add_argument(
        "--agents",
        default="",
        help="comma-separated agent ids (alternative/additive to --agent-id)",
    )
    p.add_argument(
        "--packet-d-report",
        default="",
        help="path to Packet D metrics JSON report",
    )
    p.add_argument(
        "--lab-counts",
        default="",
        help="path to LAB/SHADOW counts JSON (reviews, self_review, kb_lessons_candidate, ...)",
    )
    p.add_argument(
        "--write-intent",
        action="store_true",
        help="with --execute: write signed intent under docs/operations/promotion_intents/",
    )
    p.add_argument(
        "--intent-dir",
        default="",
        help="override intent output directory (tests)",
    )
    p.add_argument("--report-json", default="", help="optional path to write result JSON")
    args = p.parse_args(argv)

    # --self-check first (no ack required for proving guards)
    if args.self_check:
        try:
            out = self_check()
        except PromotionGateError as exc:
            print(f"[E][SELF-CHECK FAILED] {exc}", file=sys.stderr)
            return 4
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0

    # No action flag => prepare-only
    if not args.preflight and not args.execute:
        _print_disabled(
            "refused: neither --preflight nor --execute supplied (default-disabled)."
        )
        return 3

    try:
        require_ack(args.ack)
        agent_ids = parse_agent_ids(args.agent_ids, args.agents or None)
        validate_agent_ids(agent_ids)
    except PromotionGateError as exc:
        _print_disabled(f"refused: {exc}")
        return 2

    pd_path = Path(args.packet_d_report) if args.packet_d_report else None
    lab_path = Path(args.lab_counts) if args.lab_counts else None
    intent_dir = Path(args.intent_dir) if args.intent_dir else None

    # Never print env DSN if present
    if "SHADOW_DSN" in os.environ or "LAB_DSN" in os.environ:
        # Intentionally do not read or log values — presence alone is fine.
        pass

    try:
        if args.execute:
            out = run_execute(
                agent_ids,
                packet_d_report=pd_path,
                lab_counts_path=lab_path,
                write_intent=bool(args.write_intent),
                intent_dir=intent_dir,
            )
            # Execute always returns non-zero without Phase 11 when not write-intent?
            # Spec: still refuse with clear message OR write intent.
            # Exit 2 when pure refuse (no intent); exit 0 when intent written (still not OPERATIONAL).
            text = json.dumps(out, indent=2, sort_keys=True)
            print(text)
            if args.report_json:
                Path(args.report_json).write_text(text + "\n", encoding="utf-8")
            if not args.write_intent:
                print(f"[E][REFUSED] {PHASE11_REFUSAL}", file=sys.stderr)
                return 2
            print(
                "[E] Intent recorded only — agents remain SHADOW; "
                "no OPERATIONAL status change; Phase 11 sign-off still required."
            )
            return 0

        # preflight
        out = run_preflight(
            agent_ids,
            packet_d_report=pd_path,
            lab_counts_path=lab_path,
            require_evidence=True,
        )
        text = json.dumps(out, indent=2, sort_keys=True)
        print(text)
        if args.report_json:
            Path(args.report_json).write_text(text + "\n", encoding="utf-8")
        return 0
    except PreflightFailed as exc:
        print(f"[E][PREFLIGHT FAIL] {exc}", file=sys.stderr)
        return 4
    except PromotionGateError as exc:
        print(f"[E][REFUSED] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover
        print(f"[E][ERROR] {type(exc).__name__}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
