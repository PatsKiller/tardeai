#!/usr/bin/env python3
"""n8n_research_intake_consumer.py — Trade AI's consumer of research_request/v1 events (Phase 2 PR-D).

Lists lane ``research-intake`` events on the gateway ledger (ACCEPTED / CLAIMED), and for each one:
  * parses the typed request from ``subject_key`` (never from bytes),
  * refuses with a typed reason anything that cannot be enqueued (unknown type or requester, a type with
    no per-request enqueue path, an unknown topic, the daily intake cap),
  * otherwise enqueues through the platform's own writer (research_intelligence_queue.enqueue → the
    after-close drain, which runs under its own cap and LLM wrapper), then walks the event
    claim → start → artifact(ri_research_queue:queue_id=N) → consumer_ack.

    python3 scripts/n8n_research_intake_consumer.py --dry-run     # list + plan, writes nothing, no transitions
    python3 scripts/n8n_research_intake_consumer.py --apply

Receipt: $TRADEAI_STATE_ROOT/data/runtime/n8n_research_intake_last.json (N8nResearchIntake@v1).
The gateway must run with ``--allow-lane research-intake`` (TRADEAI_N8N_GATEWAY_EXTRA_LANES), otherwise
the producer's events are refused ``unknown_lane`` and this consumer finds nothing.

AUTHORITY: READ_ONLY_ADVISORY over the ledger; the only write is one ri_research_queue row per accepted
request, through the same function the RI desk button uses. No Hermes call, no LLM call, no send.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_research_intake as contract  # noqa: E402
from scripts.lib.n8n_gateway_client import GatewayClient, walk_to_artifact  # noqa: E402
from scripts.lib.n8n_pilot_observations import served_sha, state_root  # noqa: E402

SCHEMA = "N8nResearchIntake@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
CONSUMER = "research-intake-consumer"
RECEIPT_REL = "data/runtime/n8n_research_intake_last.json"
DAILY_CAP_ENV = "TRADEAI_RESEARCH_INTAKE_DAILY_CAP"
DAILY_CAP_DEFAULT = 10          # requests enqueued per UTC day across all requesters; the drain has its own cap
OPEN_STATES = ("ACCEPTED", "CLAIMED")

Enqueue = Callable[[str, str], dict[str, Any]]   # (topic_id, requested_by) -> research_intelligence_queue.enqueue result


def default_enqueue(topic_id: str, requested_by: str) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from research_intelligence_queue import enqueue  # the RI desk's own writer
    return enqueue(topic_id, requested_by=requested_by, source="n8n-research-intake")


def daily_cap() -> int:
    try:
        return max(0, int(os.environ.get(DAILY_CAP_ENV, DAILY_CAP_DEFAULT)))
    except ValueError:
        return DAILY_CAP_DEFAULT


def _load(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def enqueued_today(previous: dict[str, Any] | None, day: str) -> int:
    """Count of requests this consumer enqueued earlier today, from its own last receipt."""
    if not previous or previous.get("utc_day") != day:
        return 0
    return int(previous.get("enqueued_today") or 0)


def load_request(root: Path, key: str) -> dict[str, Any] | None:
    """The producer's sidecar for an idempotency key (the ledger receipt carries no subject_key)."""
    return _load(root / "data" / "runtime" / contract.sidecar_rel(key))


def plan(items: list[dict[str, Any]], *, already: int, cap: int, requests: dict[str, dict[str, Any] | None]) -> list[dict[str, Any]]:
    """Pure: decide per event what the consumer would do. No I/O (sidecars are passed in)."""
    rows: list[dict[str, Any]] = []
    budget = max(0, cap - already)
    for r in items:
        key = str(r.get("idempotency_key") or "")
        row: dict[str, Any] = {"idempotency_key": key, "state_before": r.get("state")}
        side = requests.get(key)
        if not side:
            row.update(action="refuse", reason="typed_refusal:missing_request_sidecar")
            rows.append(row)
            continue
        try:
            contract.validate(str(side.get("subject")), str(side.get("request_type")), str(side.get("requested_by")),
                              str(side.get("priority") or "P2"))
            req = {"subject": side["subject"], "request_type": side["request_type"], "requested_by": side["requested_by"],
                   "priority": side.get("priority") or "P2"}
        except contract.RequestError as exc:
            row.update(action="refuse", reason=exc.reason)
            rows.append(row)
            continue
        row.update(req)
        path = contract.enqueue_path(req["request_type"])
        if path is None:
            row.update(action="refuse", reason=f"typed_refusal:no_enqueue_path:{req['request_type']}")
        elif budget <= 0:
            row.update(action="refuse", reason=f"typed_refusal:intake_cap:{cap}")
        else:
            budget -= 1
            row.update(action="enqueue", path=path)
        rows.append(row)
    return rows


def list_open(client: GatewayClient) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    out: list[dict[str, Any]] = []
    last: dict[str, Any] = {}
    for state in OPEN_STATES:
        r = client.call("list", lane_id=contract.LANE, state=state)
        last = r
        if r.get("state") == "OK":
            out.extend(r.get("items") or [])
        elif r.get("state") in {"UNREACHABLE", "REFUSED"}:
            return out, r
    return out, last


def run(*, apply: bool, client: GatewayClient | None, enqueue: Enqueue, root: Path, now: datetime,
        receipt_path: Path) -> dict[str, Any]:
    sha = served_sha()
    day = contract.utc_day(now)
    previous = _load(receipt_path)
    already = enqueued_today(previous, day)
    cap = daily_cap()
    gateway: dict[str, Any] = {"url": client.url if client else None, "has_key": bool(client and client.has_key)}
    items: list[dict[str, Any]] = []
    if client is None:
        gateway["note"] = "no client (dry-run without a gateway key lists nothing)"
    else:
        items, last = list_open(client)
        gateway["list"] = {"state": last.get("state"), "reason": last.get("reason")}
    rows = plan(items, already=already, cap=cap,
                requests={str(r.get("idempotency_key") or ""): load_request(root, str(r.get("idempotency_key") or "")) for r in items})
    enqueued = 0
    for row in rows:
        if client is None or not apply:
            row["state"] = "DRY_RUN"
            continue
        key = row["idempotency_key"]
        ops: list[dict[str, Any]] = []
        if row["action"] == "refuse":
            r = client.transition("refuse", key, reason=row["reason"])
            ops.append({"op": "refuse", "state": r.get("state"), "reason": r.get("reason")})
        else:
            try:
                res = enqueue(row["subject"], row["requested_by"])
            except Exception as exc:  # noqa: BLE001 — the writer's failure is a typed outcome on the ledger
                res = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
            row["enqueue_result"] = {k: res.get(k) for k in ("ok", "queued", "already", "queue_id", "error", "note")}
            if not res.get("ok"):
                reason = "typed_refusal:unknown_topic" if "unknown topic" in str(res.get("error") or "") else "typed_refusal:enqueue_failed"
                r = client.transition("refuse", key, reason=reason)
                ops.append({"op": "refuse", "state": r.get("state"), "reason": r.get("reason")})
                row["reason"] = reason
            else:
                if res.get("queued"):
                    enqueued += 1
                ref = {"store": "ri_research_queue", "ref": f"queue_id={res.get('queue_id')}", "as_of": now.isoformat()}
                ops.extend(walk_to_artifact(client, key, ref))
                if ops and ops[-1].get("state") == "ARTIFACT_WRITTEN":
                    r = client.transition("consumer_ack", key, consumer_receipt={"consumer": CONSUMER, "receipt_id": f"{RECEIPT_REL}@{now.isoformat()}"})
                    ops.append({"op": "consumer_ack", "state": r.get("state"), "reason": r.get("reason")})
        row["ops"] = ops
        row["state"] = ops[-1].get("state") if ops else "UNKNOWN"
    receipt = {"schema": SCHEMA, "authority": AUTHORITY, "as_of": now.isoformat(), "utc_day": day,
               "mode": "apply" if apply else "dry-run", "served_sha": sha, "state_root": str(root), "gateway": gateway,
               "cap": cap, "enqueued_today": already + enqueued, "listed": len(items), "requests": rows,
               "ok": (not apply) or all(r.get("state") not in {"UNREACHABLE", "UNKNOWN"} for r in rows)}
    if apply:
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = receipt_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(receipt, indent=1, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, receipt_path)
    return receipt


def main(argv: list[str] | None = None, *, client: GatewayClient | None = None, enqueue: Enqueue | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true", help="default")
    ap.add_argument("--receipt", help="override the receipt path (tests)")
    args = ap.parse_args(argv)
    root = state_root()
    receipt_path = Path(args.receipt) if args.receipt else root / RECEIPT_REL
    if client is None:
        c = GatewayClient(caller_id=CONSUMER)
        client = c if c.has_key else None
    now = datetime.now(timezone.utc)
    receipt = run(apply=bool(args.apply), client=client, enqueue=enqueue or default_enqueue, root=root, now=now,
                  receipt_path=receipt_path)
    print(json.dumps({"mode": receipt["mode"], "listed": receipt["listed"], "cap": receipt["cap"],
                      "enqueued_today": receipt["enqueued_today"], "gateway": receipt["gateway"], "ok": receipt["ok"],
                      "sample": [(r.get("action"), r.get("request_type"), r.get("subject"), r.get("state")) for r in receipt["requests"][:8]]},
                     default=str))
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
