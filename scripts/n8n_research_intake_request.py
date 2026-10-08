#!/usr/bin/env python3
"""n8n_research_intake_request.py — post ONE research_request/v1 event to the coordination gateway.

    python3 scripts/n8n_research_intake_request.py --subject <topic_id> --type topic --by operator \
        --reason "why" [--priority P2] [--dry-run | --apply]

``--dry-run`` (default) prints the signed envelope's event and the sidecar and posts nothing.
``--apply`` writes the sidecar under $TRADEAI_STATE_ROOT/data/runtime/n8n_research_intake/requests/ and
posts the event; the gateway answers ACCEPTED, a same-day duplicate, or a typed refusal. Nothing here
runs research: the consumer (n8n_research_intake_consumer.py) enqueues through the platform's writer.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_research_intake as contract  # noqa: E402
from scripts.lib.n8n_gateway_client import GatewayClient  # noqa: E402
from scripts.lib.n8n_pilot_observations import served_sha, state_root  # noqa: E402

CALLER = "research-intake-producer"


def main(argv: list[str] | None = None, *, client: GatewayClient | None = None, now: datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--subject", "--symbol", dest="subject", required=True, help="topic_id (type topic) or symbol")
    ap.add_argument("--type", dest="request_type", required=True, choices=sorted(contract.REQUEST_TYPES))
    ap.add_argument("--by", dest="requested_by", required=True, choices=sorted(contract.REQUESTERS))
    ap.add_argument("--reason", required=True)
    ap.add_argument("--priority", default="P2", choices=list(contract.PRIORITIES))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true", help="default")
    args = ap.parse_args(argv)
    now = now or datetime.now(timezone.utc)
    sha = served_sha() or ""
    try:
        event, sidecar = contract.build_request(subject=args.subject, request_type=args.request_type,
                                                requested_by=args.requested_by, reason=args.reason,
                                                priority=args.priority, origin_sha=sha, now=now)
    except contract.RequestError as exc:
        print(json.dumps({"state": "REFUSED", "reason": exc.reason}))
        return 2
    out = {"mode": "apply" if args.apply else "dry-run", "event": event, "sidecar": sidecar}
    if not args.apply:
        print(json.dumps(out, indent=1))
        return 0
    root = state_root()
    path = root / "data" / "runtime" / contract.sidecar_rel(event["idempotency_key"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sidecar, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    client = client or GatewayClient(caller_id=CALLER)
    r = client.accept_event(event)
    out["gateway"] = {k: r.get(k) for k in ("state", "reason", "duplicate", "durable")}
    out["sidecar_path"] = str(path)
    print(json.dumps(out, indent=1, default=str))
    return 0 if r.get("state") in {"ACCEPTED"} or r.get("duplicate") else 1


if __name__ == "__main__":
    raise SystemExit(main())
