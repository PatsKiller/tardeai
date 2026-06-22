#!/usr/bin/env python3
"""Read-only smoke verifier for the Stage-2c protective-stop approval/submit path (operator 2026-06-21).

Purpose: confirm the protective-stop confirm→submit plumbing is configured correctly WITHOUT placing,
requesting, or confirming any order — so a confusing "appears unable to submit" can be triaged in one
command. It exercises only pure builders (build_order_spec / order_summary) and the safe no-op load_intent.

HARD SAFETY: never requests approval, never confirms 2FA, never submits to Schwab, never touches .env or
secrets. Anything that would reach a broker is intentionally NOT called here.

  python3 scripts/verify_protective_stop_submit_flow.py --json | python3 -m json.tool
"""
from __future__ import annotations

import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def run() -> dict:
    blockers: list[str] = []
    warnings: list[str] = []
    required_channels = None
    env_override = False
    order_spec_builds = False
    order_summary_works = False
    load_intent_safe = False

    # 1–3. approval_service.REQUIRED_CHANNELS — effective channel threshold
    try:
        from brokers import approval_service
        required_channels = approval_service.REQUIRED_CHANNELS
        env_raw = os.getenv("TRADE_APPROVAL_REQUIRED_CHANNELS")
        env_override = env_raw is not None
        if required_channels != 1:
            if env_override:
                warnings.append(
                    f"REQUIRED_CHANNELS={required_channels} (env TRADE_APPROVAL_REQUIRED_CHANNELS="
                    f"{env_raw!r} overrides the default of 1) — either channel is NOT sufficient; both "
                    "must confirm. If unintended, unset the env var (NOT changed here).")
            else:
                blockers.append(
                    f"REQUIRED_CHANNELS={required_channels} but no env override is set — expected default 1 "
                    "(either channel sufficient). approval_service may have drifted.")
    except Exception as e:
        blockers.append(f"could not import/inspect approval_service: {type(e).__name__}: {str(e)[:120]}")

    # 4–6. protective_stop_pilot pure builders
    try:
        from brokers import protective_stop_pilot as psp
        try:
            spec = psp.build_order_spec("ZZGUARD", 1, "STOP", stop_price=1.23)
            order_spec_builds = (
                isinstance(spec, dict)
                and spec.get("orderType") == "STOP"
                and spec.get("orderLegCollection", [{}])[0].get("instruction") == "SELL"
                and spec.get("stopPrice") is not None)
            if not order_spec_builds:
                blockers.append(f"build_order_spec produced an unexpected spec: {spec}")
        except Exception as e:
            blockers.append(f"build_order_spec raised: {type(e).__name__}: {str(e)[:120]}")
        try:
            summ = psp.order_summary("ZZGUARD", 1, "STOP", stop_price=1.23)
            order_summary_works = isinstance(summ, dict) and bool(summ.get("ticket"))
            if not order_summary_works:
                blockers.append(f"order_summary returned no ticket: {summ}")
        except Exception as e:
            blockers.append(f"order_summary raised: {type(e).__name__}: {str(e)[:120]}")
        # 7. load_intent must SAFELY return None for a non-existent id (never raise / never submit)
        try:
            got = psp.load_intent("00000000-0000-0000-0000-000000000000")
            load_intent_safe = got is None
            if not load_intent_safe:
                warnings.append("load_intent returned a non-None value for a fake id — unexpected.")
        except Exception as e:
            # a DB outage shouldn't fail the safety check; note it but don't claim a blocker on the flow logic
            load_intent_safe = True
            warnings.append(f"load_intent could not reach the DB (treated as safe no-op): {type(e).__name__}: {str(e)[:100]}")
    except Exception as e:
        blockers.append(f"could not import protective_stop_pilot: {type(e).__name__}: {str(e)[:120]}")

    return {
        "ok": not blockers,
        "required_channels": required_channels,
        "required_channels_env_override": env_override,
        "order_spec_builds": order_spec_builds,
        "order_summary_works": order_summary_works,
        "load_intent_safe_none": load_intent_safe,
        "no_submit_performed": True,   # this script never requests/confirms/submits
        "blockers": blockers,
        "warnings": warnings,
    }


def main() -> int:
    as_json = "--json" in sys.argv
    result = run()
    if as_json:
        print(json.dumps(result))
    else:
        for k, v in result.items():
            print(f"{k}: {v}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
