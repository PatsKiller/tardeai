#!/usr/bin/env python3
"""Preview one tiny governed Opus call; --apply is operator-run only.

No secret resolution, policy mutation, direct provider access or cap overrides.
Tests inject the bridge and state. Live execution must use the CURRENT source.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PROCESS = "cio_operator_reply"
PROMPT = 'Operator-requested connectivity check. Return only {"status":"ANTHROPIC_CANARY_OK"}.'
OUTPUT_TOKENS = 64


def preview(root: Path) -> dict:
    from scripts.lib.anthropic_transport import load_policy

    policy = load_policy(root)
    return {
        "status": "DRY_RUN", "dispatch": False, "writes": False,
        "source_root": str(root.resolve()), "process_id": PROCESS,
        "caller": "advisory_desk", "task_type": "operator_reply",
        "manual_trigger": True, "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": OUTPUT_TOKENS, "expected_model": policy["models"]["standard"],
        "enabled": policy["enabled"], "provider_enabled": policy["provider_enabled"],
        "total_cap_usd": policy["total_cap_usd"], "daily_cap_usd": policy["daily_cap_usd"],
        "per_call_cap_usd": policy["per_call_caps_usd"]["standard"],
        "expires_at": policy["expires_at"],
    }


def prove_response(response: dict, plan: dict, request_id: str, state: Path) -> dict:
    from scripts.lib.anthropic_credit import CreditBook, amount
    from scripts.lib.anthropic_transport import load_policy

    info = response.get("_tradeai") or {}
    if response.get("error"):
        raise RuntimeError("BRIDGE_REFUSED:" + str(response["error"].get("code", "UNKNOWN")))
    if (info.get("governance_pass") is not True or info.get("mock") is not False
            or info.get("process_id") != PROCESS or not info.get("reservation_id")
            or info.get("provider") != "anthropic"
            or info.get("request_id") != request_id
            or response.get("model") != plan["expected_model"]):
        raise RuntimeError("ANTHROPIC_RESPONSE_NOT_PROVEN")
    try:
        content = json.loads(response["choices"][0]["message"]["content"])
        cost = amount(info["cost_estimate"])
        usage = response["usage"]["anthropic_usage"]
        if (content != {"status": "ANTHROPIC_CANARY_OK"}
                or cost <= 0 or cost > Decimal(plan["per_call_cap_usd"])
                or not isinstance(usage, dict)):
            raise ValueError("invalid answer or cost")
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise RuntimeError("ANTHROPIC_USAGE_NOT_PROVEN") from exc
    provider_id = info.get("provider_request_id")
    if not isinstance(provider_id, str) or not provider_id:
        raise RuntimeError("PROVIDER_REQUEST_ID_MISSING")
    book = CreditBook(state, load_policy(Path(plan["source_root"])))
    key = hashlib.sha256(request_id.encode()).hexdigest()
    # _read verifies the complete hash chain, without creating a lock or writing.
    settled = [r for r in book._read() if r.get("event") == "settle"
               and r.get("request") == key and r.get("promotion_id") == book.promotion]
    events_path = state / "data/runtime/provider_cost/events.jsonl"
    matching = []
    with events_path.open(encoding="utf-8") as handle:
        for line in handle:
            event = json.loads(line)
            if (event.get("provider") == "anthropic" and event.get("request_id") == provider_id
                    and event.get("source_process") == PROCESS and not event.get("is_test")
                    and event.get("model") == plan["expected_model"]
                    and str(event.get("reservation_id")) == str(info["reservation_id"])
                    and event.get("outcome") == "success"):
                matching.append(event)
    if (len(settled) != 1 or amount(settled[0]["actual"]) != cost or len(matching) != 1
            or amount(matching[0]["calculated_cost_usd"]) != cost):
        raise RuntimeError("CREDIT_AND_PROVIDER_COST_NOT_RECONCILED")
    return {"status": "ANTHROPIC_CANARY_VERIFIED", "provider": "anthropic",
            "model": response["model"], "process_id": PROCESS, "request_id": request_id,
            "provider_request_id": provider_id, "reservation_id": info["reservation_id"],
            "actual_cost_usd": str(cost), "usage": usage,
            "credit_settlement_verified": True, "provider_cost_verified": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    plan = preview(ROOT)
    print(json.dumps(plan, indent=2))
    if not args.apply:
        return 0
    if os.environ.get("ANTHROPIC_CANARY_OPERATOR_RUN") != "1":
        print("REFUSED: operator-run confirmation required", file=sys.stderr)
        return 2
    current = Path.home() / "trade-ai-releases/portfolio-server/CURRENT"
    if ROOT.resolve() != current.resolve():
        print("REFUSED: run the deployed CURRENT script", file=sys.stderr)
        return 2
    if not plan["enabled"] or not plan["provider_enabled"]:
        print("REFUSED: deployed policy is disabled", file=sys.stderr)
        return 2
    from scripts.lib.anthropic_monitoring import configuration_evidence
    if configuration_evidence()[0] is not True:
        print("REFUSED: key-name presence not confirmed", file=sys.stderr)
        return 2
    from scripts.lib.anthropic_routing import state_root
    from scripts.lib.n8n_model_job import bridge_governed_call

    request_id = "anthropic-canary-" + uuid.uuid4().hex
    state = state_root()
    receipt = {"observed_at": datetime.now(timezone.utc).isoformat(),
               "request_id": request_id, "status": "ATTEMPT_STARTED"}
    # Write intent before dispatch, so an interruption cannot hide the attempt.
    target = state / "data/runtime/provider_cost/canaries" / (request_id + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    try:
        response = bridge_governed_call(
            plan["messages"], process_id=PROCESS, caller=plan["caller"], task_type=plan["task_type"],
            max_tokens=OUTPUT_TOKENS, request_id=request_id, timeout_s=90, manual_trigger=True,
        )
        receipt.update(prove_response(response, plan, request_id, state))
        status = 0
    except Exception as exc:
        # Never print raw provider/HTTP errors or bodies; the native bridge owns those.
        receipt.update(status="CANARY_NOT_VERIFIED", error_type=type(exc).__name__)
        if isinstance(exc, RuntimeError) and str(exc).startswith(("BRIDGE_REFUSED:", "ANTHROPIC_", "CREDIT_", "PROVIDER_")):
            receipt["reason"] = str(exc).splitlines()[0][:120]
        status = 2
    target.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**receipt, "receipt": str(target)}, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
