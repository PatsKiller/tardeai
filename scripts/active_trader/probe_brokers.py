#!/usr/bin/env python3
"""Active Trader Stage 2 — safe read-only multi-broker discovery probe.

Usage:
  python scripts/active_trader/probe_brokers.py --dry-run
  python scripts/active_trader/probe_brokers.py --brokers alpaca,schwab,moomoo \
      [--lab-dsn-env ACTIVE_TRADER_TEST_DATABASE_DSN] [--json OUT.json] [--md OUT.md]

Safety properties:
  * method allowlist is READ-ONLY by construction — the discovery modules expose
    no write method, and this runner additionally verifies the plan;
  * --dry-run prints the method plan (safe method names + endpoint classes) and exits;
  * no production persistence: results are written to the lab DB ONLY when
    --persist is given AND the DSN passes the production-refusing guard;
  * identifiers masked; headers/secrets never logged; bounded timeout;
    reads retried at most once; auth failures never retried;
  * Moomoo NOT_INSTALLED never fails the run; a safety violation exits nonzero.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from active_trader.discovery import (  # noqa: E402
    BrokerDiscoveryResult, build_projection, persist_capabilities,
)

METHOD_PLAN = {
    "alpaca": [
        ("GET", "account (v2/account)"), ("GET", "positions (v2/positions)"),
        ("GET", "open orders (v2/orders?status=open)"), ("GET", "market clock (v2/clock)"),
        ("GET", "asset lookup (v2/assets/AAPL)"),
    ],
    "schwab": [
        ("READ", "get_account via schwab_transport"), ("READ", "get_positions via schwab_transport"),
        ("READ", "get_orders via schwab_transport"), ("READ", "get_market_hours via schwab_transport"),
    ],
    "moomoo": [("NONE", "no call — connector NOT_INSTALLED is recorded")],
}
ALLOWED_VERBS = {"GET", "READ", "NONE"}
DEFAULT_BROKERS = ("alpaca", "schwab", "moomoo")


def _source_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parents[2]).stdout.strip()
    except Exception:
        return "unknown"


def run_probe(brokers, timeout: float) -> list[BrokerDiscoveryResult]:
    results = []
    for broker in brokers:
        try:
            if broker == "alpaca":
                from active_trader.discovery_alpaca import discover
                results.append(discover(timeout=timeout))
            elif broker == "schwab":
                from active_trader.discovery_schwab import discover
                results.append(discover())
            elif broker == "moomoo":
                from active_trader.discovery import MoomooDiscovery
                results.append(MoomooDiscovery().discover())
        except Exception as exc:  # one broker's failure never kills the fleet
            results.append(BrokerDiscoveryResult(
                broker=broker, connector_state="ERROR", account_discovery="UNAVAILABLE",
                errors=[f"{type(exc).__name__}: {str(exc)[:160]}"],
                observed_at=datetime.now(timezone.utc).isoformat()))
    return results


def to_markdown(projection: dict, results, sha: str) -> str:
    lines = [f"# Broker discovery probe — {datetime.now(timezone.utc).date()}",
             f"source SHA: {sha}", ""]
    for res in results:
        lines.append(f"## {res.broker}: connector={res.connector_state} discovery={res.account_discovery}")
        for e in res.errors:
            lines.append(f"- error: {e}")
    lines.append("")
    lines.append("| broker | account | masked id | env | status | read | auth |")
    lines.append("|---|---|---|---|---|---|---|")
    for a in projection["accounts"]:
        lines.append(f"| {a['broker']} | {a['account_label']} | {a['masked_account_id']} | "
                     f"{a['environment']} | {a['status']} | {a['read_state']} | {a['authentication_state']} |")
    lines.append("")
    lines.append(f"Discrepancies: {len(projection['discrepancies'])}")
    for d in projection["discrepancies"]:
        lines.append(f"- {d['kind']}: {d.get('broker')}/{d.get('account_label')}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--brokers", default=",".join(DEFAULT_BROKERS))
    ap.add_argument("--dry-run", action="store_true", help="print method plan and exit")
    ap.add_argument("--persist", action="store_true",
                    help="write normalized capabilities to the LAB database (guarded)")
    ap.add_argument("--lab-dsn-env", default="ACTIVE_TRADER_TEST_DATABASE_DSN")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--md", dest="md_out")
    args = ap.parse_args(argv)

    brokers = [b.strip() for b in args.brokers.split(",") if b.strip()]
    unknown = [b for b in brokers if b not in DEFAULT_BROKERS]
    if unknown:
        print(f"ERROR: brokers not in allowlist: {unknown}", file=sys.stderr)
        return 2

    print("METHOD PLAN (read-only):")
    violation = False
    for b in brokers:
        for verb, what in METHOD_PLAN[b]:
            marker = "" if verb in ALLOWED_VERBS else "  <-- NOT READ-ONLY, REMOVED"
            if verb not in ALLOWED_VERBS:
                violation = True
            print(f"  {b:8s} {verb:5s} {what}{marker}")
    if violation:
        print("ERROR: non-read method in plan — refused", file=sys.stderr)
        return 3
    if args.dry_run:
        print("dry-run: no broker call made, nothing persisted")
        return 0

    sha = _source_sha()
    results = run_probe(brokers, args.timeout)

    configured = []
    try:
        import yaml
        acct_yaml = Path(__file__).resolve().parents[2] / "assets" / "portfolio_accounts.yaml"
        data = yaml.safe_load(acct_yaml.read_text()) or {}
        for key, row in (data.get("accounts") or {}).items():
            configured.append({"account_key": key, **(row or {})})
    except Exception as exc:
        print(f"warning: configured-account load failed: {type(exc).__name__}", file=sys.stderr)

    projection = build_projection(configured, results)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "source_sha": sha,
               "brokers": brokers, "projection": projection,
               "broker_states": [{"broker": r.broker, "connector_state": r.connector_state,
                                  "account_discovery": r.account_discovery, "errors": r.errors}
                                 for r in results]}
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, indent=2, default=str))
    if args.md_out:
        Path(args.md_out).write_text(to_markdown(projection, results, sha))
    if args.persist:
        dsn = os.environ.get(args.lab_dsn_env, "")
        written = persist_capabilities(dsn, results)
        print(f"persisted {written} capability rows to the lab database")
    print(json.dumps({"brokers": {r.broker: r.account_discovery for r in results},
                      "accounts": len(projection["accounts"]),
                      "discrepancies": len(projection["discrepancies"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
