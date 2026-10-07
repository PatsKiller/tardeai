#!/usr/bin/env python3
"""n8n_pilot_dispatch.py — turn the five pilots' REAL receipts into gateway events.

Roadmap Phase 1 (2026-10-07). Source-side dispatcher: reads each pilot's durable
artifact through scripts/lib/n8n_pilot_observations (the same builders the contract
tests use), evaluates the pilot contract, and mirrors what already happened into the
coordination ledger: accept_event → claim → start → artifact(ref) → consumer_ack when a
consumer receipt exists, or `refuse` with the typed contract reason. Nothing is sent,
charged, or written outside the ledger and this script's own receipt.

    python3 scripts/n8n_pilot_dispatch.py --dry-run            # plan only, no gateway call
    python3 scripts/n8n_pilot_dispatch.py --apply [--lane X]   # post to the gateway

Receipt: $TRADEAI_STATE_ROOT/data/runtime/n8n_pilot_dispatch_last.json (N8nPilotDispatchRun@v1)
Env:     TRADEAI_N8N_GATEWAY_HMAC_KEY (rendered from Bitwarden SM), TRADEAI_N8N_GATEWAY_URL,
         TRADEAI_SERVED_SHA (optional), TRADEAI_STATE_ROOT

Idempotency keys are derived from the artifact itself (run_id, report key, session key,
change_guid, hermes run id), so a re-run after the same fire is a duplicate, not a new event.

AUTHORITY: READ_ONLY_ADVISORY. Lane registry: n8n-pilot-dispatch (NEVER_SCHEDULED until cron grant).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.n8n_gateway_client import GatewayClient, walk_to_artifact  # noqa: E402
from scripts.lib.n8n_pilot_contracts import PILOT_IDS, evaluate_pilot  # noqa: E402
from scripts.lib.n8n_pilot_observations import BUILDERS, event_reference, served_sha, state_root  # noqa: E402

SCHEMA = "N8nPilotDispatchRun@v1"
AUTHORITY = "READ_ONLY_ADVISORY"


def _sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _key(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts if p is not None)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _stable_time(*candidates: Any, fallback: datetime) -> datetime:
    """The event's source_timestamp must not move between runs, or the payload hash changes and the
    gateway answers idempotency_conflict. Prefer a timestamp carried by the artifact itself."""
    for c in candidates:
        if not c:
            continue
        try:
            d = datetime.fromisoformat(str(c).replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return fallback


def plan_lane(lane_id: str, observation: Mapping[str, Any], root: Path) -> dict[str, Any]:
    """Decide the idempotency key, subject, artifact ref and whether anything fired."""
    o = observation
    if lane_id == "approval-package-reminder":
        rr = o.get("run_receipt") or {}
        if not rr.get("run_id"):
            return {"fired": False, "why": "no run receipt"}
        rel = "data/runtime/approval_package_reminder_last.json"
        return {"fired": True, "idempotency_key": "apr-" + _key(rr["run_id"]), "subject_key": f"approval-reminder:{rr['run_id']}",
                "artifact_rel": rel, "store": "data/runtime", "at": rr.get("started_at") or rr.get("ended_at")}
    if lane_id == "llm-spend-report-daily":
        if o.get("artifact_status") != "OBSERVED" or not o.get("report_key"):
            return {"fired": False, "why": "no daily spend receipt"}
        rel = "data/runtime/llm_spend_report_last_daily.json"
        return {"fired": True, "idempotency_key": "llm-" + _key(o["report_key"]), "subject_key": f"llm-spend:{o['report_key']}",
                "artifact_rel": rel, "store": "data/runtime", "at": o.get("ran_at")}
    if lane_id == "morning-brief-0730":
        if o.get("artifact_status") != "OBSERVED" or not o.get("session_date"):
            return {"fired": False, "why": "no publish claim for the session"}
        rel = "data/cio/morning_brief_semantic_state.json"
        return {"fired": True, "idempotency_key": "mb-" + _key(o["session_date"], o.get("claimed_at")),
                "subject_key": f"morning-brief:{o['session_date']}", "artifact_rel": rel, "store": "data/cio", "at": o.get("claimed_at")}
    if lane_id == "material-change-digest":
        if not o.get("detector_event_id"):
            return {"fired": False, "why": o.get("detector_status") or "no detector event"}
        return {"fired": True, "idempotency_key": "mcd-" + _key(o["detector_event_id"]),
                "subject_key": f"material-change:{o.get('symbol')}:{o['detector_event_id']}",
                "artifact_rel": f"material_changes/{o['detector_event_id']}", "store": "postgres:material_changes", "no_file": True,
                "at": o.get("notified_at") or o.get("created_at")}
    if lane_id == "research-scheduler-holdings":
        if not o.get("hermes_run_id"):
            return {"fired": False, "why": (o.get("typed_refusal") or {}).get("code") or "no holdings run"}
        rel = "data/cio/research_call_accounting.jsonl"
        return {"fired": True, "idempotency_key": "rsh-" + _key(o["hermes_run_id"]),
                "subject_key": f"research-holdings:{o['hermes_run_id']}", "artifact_rel": rel, "store": "data/cio"}
    return {"fired": False, "why": "unknown lane"}


def dispatch_lane(lane_id: str, *, client: GatewayClient | None, root: Path, sha: str, now: datetime,
                  db_query=None) -> dict[str, Any]:
    builder = BUILDERS[lane_id]
    observation = builder(db_query=db_query, root=root) if lane_id == "material-change-digest" else builder(root)
    plan = plan_lane(lane_id, observation, root)
    row: dict[str, Any] = {"lane_id": lane_id, "fired": plan.get("fired", False), "why": plan.get("why"),
                           "observation_status": observation.get("artifact_status") or observation.get("detector_status"),
                           "ops": []}
    if not plan.get("fired"):
        row["outcome"] = "NO_FIRE"
        return row
    idem = plan["idempotency_key"]
    artifact_ref_str = f"{plan['store']}:{plan['artifact_rel']}"
    at = _stable_time(plan.get("at"), fallback=now)
    event = event_reference(lane_id, idempotency_key=idem, subject_key=plan["subject_key"], artifact_ref=artifact_ref_str,
                            now=at, deadline_hours=24.0, origin_sha=sha)
    row.update({"idempotency_key": idem, "event_id": event["event_id"], "subject_key": plan["subject_key"]})
    # local contract verdict (no socket): the gateway is not consulted for the lane rule
    verdict_input = {"route": "coordination/event", "operation": "accept_event", "event": event}
    row["contract"] = _local_contract(lane_id, verdict_input, observation, sha)
    if client is None:
        row["outcome"] = "DRY_RUN"
        row["planned_ops"] = ["accept_event", "claim", "start", "artifact"] + (["consumer_ack"] if observation.get("consumer_receipt") else []) \
            if row["contract"]["state"] != "REFUSED" else ["accept_event", "refuse"]
        return row
    # status first: an event the ledger already holds is never re-accepted (its payload hash may differ
    # when a timestamp could not be made stable; the ledger's row is the truth)
    st = client.status(idem)
    if st.get("state") in {"UNREACHABLE"}:
        row["ops"].append({"op": "status", "state": "UNREACHABLE", "reason": st.get("reason")})
        row["outcome"] = "GATEWAY_UNREACHABLE"
        return row
    if st.get("state") not in {None, "REFUSED"} or (st.get("state") == "REFUSED" and st.get("reason") != "unknown_event"):
        acc = {"state": st.get("state"), "reason": st.get("reason"), "duplicate": True, "durable": st.get("durable")}
    else:
        acc = client.accept_event(event)
    row["ops"].append({"op": "accept_event", "state": acc.get("state"), "reason": acc.get("reason"), "duplicate": acc.get("duplicate"),
                       "durable": acc.get("durable")})
    if acc.get("state") in {"UNREACHABLE"}:
        row["outcome"] = "GATEWAY_UNREACHABLE"
        return row
    if acc.get("state") == "REFUSED":
        row["outcome"] = "GATEWAY_REFUSED" if not acc.get("duplicate") else "REFUSED"   # a stored refusal is final
        return row
    if acc.get("state") == "CONSUMED":
        row["outcome"] = "CONSUMED"
        return row
    if row["contract"]["state"] == "REFUSED" and not acc.get("duplicate"):
        r = client.transition("refuse", idem, reason="typed_refusal:" + str(row["contract"]["reason"]))
        row["ops"].append({"op": "refuse", "state": r.get("state"), "reason": r.get("reason")})
        row["outcome"] = "REFUSED_BY_CONTRACT"
        return row
    ref: dict[str, Any] = {"store": plan["store"], "ref": plan["artifact_rel"], "as_of": now.isoformat()}
    if not plan.get("no_file"):
        digest = _sha256_file(root / plan["artifact_rel"])
        if digest:
            ref["sha256"] = digest
    row["ops"].extend(walk_to_artifact(client, idem, ref))
    final = row["ops"][-1].get("state") if row["ops"] else None
    cr = observation.get("consumer_receipt")
    if final == "ARTIFACT_WRITTEN" and isinstance(cr, Mapping) and cr.get("consumer") and cr.get("receipt_id"):
        r = client.transition("consumer_ack", idem, consumer_receipt={"consumer": cr["consumer"], "receipt_id": str(cr["receipt_id"])})
        row["ops"].append({"op": "consumer_ack", "state": r.get("state"), "reason": r.get("reason")})
        final = r.get("state") or final
    row["outcome"] = final or "UNKNOWN"
    return row


def _local_contract(lane_id: str, request: Mapping[str, Any], observation: Mapping[str, Any], sha: str) -> dict[str, Any]:
    """Run the pilot contract with a throwaway key so the lane rule is recorded without a socket."""
    from scripts.lib.n8n_coordination_gateway import sign_claim
    key = b"local-contract-check-key-not-a-secret-0000"
    now = datetime.now(timezone.utc)
    claim = {"v": 1, "caller_id": "local-check", "project": "trade-ai", "iat": now.timestamp(), "exp": now.timestamp() + 60,
             "nonce": "localcheck" + hashlib.sha1(json.dumps(request.get("event"), sort_keys=True).encode()).hexdigest()[:8],
             "scope": "coordination_read"}
    req = {**request, "claim": claim, "signature": sign_claim(claim, key)}
    v = evaluate_pilot(lane_id, request=req, observation=observation, key=key, now=now, nonce_store={}, idempotency_store={},
                       expected_origin_sha=sha)
    return {"state": v.get("state"), "reason": v.get("reason")}


def _db_query_factory():
    """Read-only psycopg2 query for material_changes, only if a DSN is in the environment."""
    dsn = os.environ.get("TRADEAI_READ_DSN") or os.environ.get("TRADE_AI_DSN") or os.environ.get("DATABASE_URL")
    if not dsn:
        return None
    try:
        import psycopg2  # type: ignore
    except Exception:
        return None

    def q(sql: str, params: tuple) -> list[tuple]:
        with psycopg2.connect(dsn) as conn:
            conn.set_session(readonly=True)
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())
    return q


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--lane", action="append", default=[], help="restrict to lane id(s); default all five pilots")
    ap.add_argument("--receipt", default=None)
    args = ap.parse_args(argv)
    root = state_root()
    sha = served_sha() or ""
    now = datetime.now(timezone.utc)
    lanes = args.lane or list(PILOT_IDS)
    client = None
    gateway: dict[str, Any] = {"url": None, "healthz": None}
    if args.apply:
        client = GatewayClient()
        gateway = {"url": client.url, "has_key": client.has_key, "healthz": client.healthz()}
    rows = [dispatch_lane(l, client=client, root=root, sha=sha, now=now, db_query=_db_query_factory()) for l in lanes]
    receipt = {"schema": SCHEMA, "authority": AUTHORITY, "as_of": now.isoformat(), "mode": "apply" if args.apply else "dry-run",
               "served_sha": sha or None, "state_root": str(root), "gateway": gateway, "lanes": rows,
               "fired": sum(1 for r in rows if r["fired"]),
               "ok": (not args.apply) or all(r.get("outcome") not in {"GATEWAY_UNREACHABLE", "GATEWAY_REFUSED", "UNKNOWN"} for r in rows)}
    out = Path(args.receipt) if args.receipt else (root / "data" / "runtime" / "n8n_pilot_dispatch_last.json")
    if args.apply:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(receipt, indent=1, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, out)
        receipt["receipt_path"] = str(out)
    print(json.dumps({k: receipt[k] for k in ("mode", "served_sha", "fired", "ok")} | {"lanes": [(r["lane_id"], r.get("outcome"), r.get("why")) for r in rows]}, default=str))
    return 0 if (not args.apply or receipt["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
