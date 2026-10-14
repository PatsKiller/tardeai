#!/usr/bin/env python3
"""Operator probe: one governed llm_step through the RUNNING bridge, printing its route receipts.

Proves one route per run (docs/runbooks/BRIDGE_OAUTH_TRANSPORTS_ACTIVATION.md): the bridge's
CIO_BRIDGE_OAUTH_TRANSPORTS decides which lanes may serve, and the receipt names the lane that did.

  python scripts/bridge_llm_step_probe.py --expect grok            # dry run: prints the request, sends nothing
  python scripts/bridge_llm_step_probe.py --expect grok --send     # one call; exit 0 only if grok served

Sends a synthetic, non-portfolio facts pack for n8n_lane_failure_diagnosis (template lane_failure_diagnosis.v1,
closed schema lane_failure_decision/v1). Spend: OAuth lanes are free; a DeepSeek-served probe is one Flash call
inside the process's $0.05 per-call ceiling and $0.10/day cap. The bridge writes the LlmStepAudit@v1 row; this
script writes nothing. Caller key: sent only when TRADEAI_BRIDGE_CALLER_KEY_N8N_MODEL_JOB is already in the
operator's environment (never read from a file here).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

CALLER = "n8n_model_job"
KEY_ENV = "TRADEAI_BRIDGE_CALLER_KEY_N8N_MODEL_JOB"
DEFAULT_URL = "http://127.0.0.1:8766/v1/llm_step"


def build_request(expect: str, now: dt.datetime) -> dict:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    return {
        "process_id": "n8n_lane_failure_diagnosis",
        "template_id": "lane_failure_diagnosis.v1",
        "output_schema_id": "lane_failure_decision/v1",
        "run_id": f"probe-{expect}-{stamp}",
        "execution_id": f"probe-exec-{expect}-{stamp}",
        "facts": {
            "lane": "synthetic-probe-lane",
            "note": "Synthetic route probe. No real lane failed.",
            "allowed_action_ids": ["suggest_only"],
            "evidence": [{"id": "probe-1", "kind": "log_line", "text": "probe: exit 1 after 2.0s (synthetic)"}],
        },
        "allowed_values": {"action_id": ["suggest_only"]},
        "budget": {"max_tokens": 512},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--expect",
        required=True,
        choices=("grok", "chatgpt", "deepseek"),
        help="the provider this run must be served by",
    )
    ap.add_argument("--send", action="store_true", help="actually POST (default: dry run)")
    ap.add_argument("--url", default=os.environ.get("TRADEAI_LLM_STEP_URL", DEFAULT_URL))
    ap.add_argument("--timeout", type=float, default=170.0)
    args = ap.parse_args(argv)
    body = build_request(args.expect, dt.datetime.now(dt.timezone.utc))
    if not args.send:
        print(json.dumps({"dry_run": True, "url": args.url, "caller": CALLER, "request": body}, indent=1))
        return 0
    headers = {"Content-Type": "application/json", "X-TradeAI-Agent": CALLER}
    if os.environ.get(KEY_ENV):
        headers["Authorization"] = "Bearer " + os.environ[KEY_ENV]
    req = urllib.request.Request(args.url, data=json.dumps(body).encode(), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:400]}")
        return 2
    except (urllib.error.URLError, OSError) as exc:
        print(f"bridge unreachable: {type(exc).__name__}")
        return 2
    receipts = result.get("route_receipts") or []
    print(
        json.dumps(
            {
                "status": result.get("status"),
                "refusal": result.get("refusal"),
                "provider": result.get("provider"),
                "model_id": result.get("model_id"),
                "decision": result.get("decision"),
                "run_id": result.get("run_id"),
                "execution_id": result.get("execution_id"),
                "audit": result.get("audit"),
                "route_receipts": [
                    {
                        k: r.get(k)
                        for k in (
                            "lane",
                            "provider",
                            "model",
                            "outcome",
                            "latency_ms",
                            "cost_usd",
                            "auth_failure",
                            "http_status",
                            "retry_after_s",
                        )
                    }
                    for r in receipts
                ],
            },
            indent=1,
        )
    )
    served = [r for r in receipts if r.get("outcome") == "ok"]
    ok = result.get("status") == "ok" and len(served) == 1 and served[0].get("provider") == args.expect
    print("PROBE_PASS" if ok else "PROBE_FAIL", args.expect)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
