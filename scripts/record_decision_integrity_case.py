#!/usr/bin/env python3
"""Record a decision-integrity contradiction as a durable case (dry-run default).

A Watch/desk contradiction (an invalidated plan shown as actionable, a house
hold labelled as a wash-sale block, an alert offered but never armed) becomes
an immutable case row in data/cio/cio_production_cases.jsonl through the
existing case store — never a second store. The case links the inbound
message lineage, release SHA, plan version, quote versions, the states the
validator returned and the corrected answer. A case records that the
contradiction happened and was corrected; it is not evidence that any trade
outcome or learned behaviour change occurred.

Writes only with --apply (operator-authorized data write). Dry run prints the
exact row.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CASE_TYPE = "watch_contradiction"          # v3.3 §10.2 case type
NO_CONSUMER_REASON = (
    "writes through cio_production_case (the case store is the consumer); the payload schema names this recorder's rows inside that store"
)
SCHEMA = "DecisionIntegrityCase@v1"


def build_case_payload(spec: dict) -> dict:
    """Deterministic payload from a spec dict (see --spec JSON)."""
    lineage = spec.get("lineage") or {}
    digest_src = json.dumps({k: spec.get(k) for k in ("symbol", "lineage", "plan", "quotes", "integrity")},
                            sort_keys=True, default=str)
    return {
        "schema": SCHEMA,
        "case_type": CASE_TYPE,
        "symbol": str(spec.get("symbol") or "").upper(),
        "opened_at": spec.get("opened_at") or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "lineage": {
            "inbound_channel": lineage.get("inbound_channel"),
            "inbound_message_ref": lineage.get("inbound_message_ref"),
            "inbound_at": lineage.get("inbound_at"),
            "outbound_at": lineage.get("outbound_at"),
            "producer_chain": list(lineage.get("producer_chain") or []),
            "prose_author": lineage.get("prose_author"),
        },
        "release": {"served_sha": spec.get("served_sha"), "answering_tree": spec.get("answering_tree")},
        "plan": spec.get("plan") or {},
        "quotes": spec.get("quotes") or {},
        "positions": spec.get("positions") or [],
        "tax": spec.get("tax") or {},
        "alert": spec.get("alert") or {},
        "integrity": spec.get("integrity") or {},
        "defects": list(spec.get("defects") or []),
        "corrected_answer": spec.get("corrected_answer"),
        "operator_correction": spec.get("operator_correction"),
        "financial_consequence_observed": spec.get("financial_consequence_observed"),
        "not_evidence_of": ["trade_outcome", "learned_behavior_change"],
        "authority": "READ_ONLY_ADVISORY",
        "content_hash": hashlib.sha256(digest_src.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spec", required=True, help="JSON file describing the contradiction")
    ap.add_argument("--apply", action="store_true", help="append to the case store (operator-authorized)")
    ap.add_argument("--path", default=None, help="case store path override (tests)")
    args = ap.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    payload = build_case_payload(spec)
    decision_id = f"decision_integrity:{payload['symbol']}:{payload['content_hash'][:16]}"
    print(json.dumps({"decision_id": decision_id, "payload": payload}, indent=2, default=str))
    if not args.apply:
        print("DRY RUN — no case written (pass --apply under operator authorization)", file=sys.stderr)
        return 0
    from scripts.lib import cio_production_case as pc
    rec = pc.append_case({"decision_id": decision_id, **payload}, path=Path(args.path) if args.path else None)
    print(json.dumps({"written": True, "case_id": (rec or {}).get("case_id")}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
