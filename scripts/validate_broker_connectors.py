#!/usr/bin/env python3
"""validate_broker_connectors.py — Validate every broker connector against the contract.

Only Alpaca is LIVE API trading today; Schwab/Tastytrade are programmed but not yet
connected. This harness validates each adapter WITHOUT needing live credentials:

  - imports cleanly
  - exposes the broker-agnostic interface (get_account, get_positions, get_open_orders,
    submit_entry, sync_positions, get_status)
  - instantiates safely (no creds -> enabled=False, never raises)
  - dry-run submit_entry returns a well-formed dict
  - get_status() reports config/auth state
  - reports whether credentials are present in the environment (masked — never printed)

It is read-only and side-effect-free: it never places orders (dry_run=True), never writes
to the DB, and never logs secret values. Use it as the source of truth for the v3 Admin
broker-connectors status panel and as a pre-flight check before wiring a new broker.

Usage:
    .venv/bin/python scripts/validate_broker_connectors.py            # human table
    .venv/bin/python scripts/validate_broker_connectors.py --json     # machine JSON
"""
import argparse
import importlib
import inspect
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# adapter module -> (class name, required env vars, broker key)
CONNECTORS = {
    "alpaca_paper_adapter": {
        "class": "AlpacaPaperAdapter",
        "broker": "alpaca",
        "env": ["ALPACA_API_KEY", "ALPACA_SECRET_KEY"],
        "live": True,
    },
    "schwab_adapter": {
        "class": "SchwabAdapter",
        "broker": "schwab",
        "env": ["SCHWAB_APP_KEY", "SCHWAB_APP_SECRET", "SCHWAB_REFRESH_TOKEN"],
        "live": False,
    },
    "tastytrade_adapter": {
        "class": "TastytradeAdapter",
        "broker": "tastytrade",
        "env": ["TASTYTRADE_USERNAME", "TASTYTRADE_PASSWORD"],
        "live": False,
    },
}

# The broker-agnostic interface every adapter must implement.
REQUIRED_METHODS = [
    "get_account", "get_positions", "get_open_orders",
    "submit_entry", "sync_positions", "get_status",
]


def _check_env(varnames):
    """Return {var: present_bool} — never returns the value itself."""
    return {v: bool(os.environ.get(v)) for v in varnames}


def validate_one(module_name, spec):
    result = {
        "module": module_name,
        "broker": spec["broker"],
        "live": spec["live"],
        "imports": False,
        "class_found": False,
        "missing_methods": [],
        "instantiates": False,
        "enabled": None,
        "dry_run_ok": False,
        "status": None,
        "env_present": _check_env(spec["env"]),
        "errors": [],
    }
    # 1. import
    try:
        mod = importlib.import_module(module_name)
        result["imports"] = True
    except Exception as e:
        result["errors"].append(f"import: {e}")
        return result
    # 2. class + interface
    cls = getattr(mod, spec["class"], None)
    if cls is None:
        result["errors"].append(f"class {spec['class']} not found")
        return result
    result["class_found"] = True
    result["missing_methods"] = [m for m in REQUIRED_METHODS if not callable(getattr(cls, m, None))]
    # 3. instantiate (no creds -> must NOT raise; enabled should be False)
    try:
        # pass account_label where the constructor accepts it (schwab/tastytrade)
        params = inspect.signature(cls.__init__).parameters
        kwargs = {"dry_run": True}
        if "account_label" in params:
            kwargs["account_label"] = f"{spec['broker']}_validate"
        inst = cls(**kwargs)
        result["instantiates"] = True
        result["enabled"] = bool(getattr(inst, "enabled", False))
    except Exception as e:
        result["errors"].append(f"instantiate: {e}")
        return result
    # 4. dry-run submit_entry returns a dict (no order placed)
    try:
        out = inst.submit_entry("TEST", 1, 10.0, 9.0, 12.0, "validate", None)
        result["dry_run_ok"] = isinstance(out, dict) and "status" in out
        if not result["dry_run_ok"]:
            result["errors"].append(f"submit_entry returned {type(out).__name__}, expected dict with 'status'")
    except Exception as e:
        result["errors"].append(f"submit_entry: {e}")
    # 5. get_status
    try:
        st = inst.get_status()
        if isinstance(st, dict):
            result["status"] = {k: st.get(k) for k in ("enabled", "authenticated", "configured", "dry_run")}
    except Exception as e:
        result["errors"].append(f"get_status: {e}")
    return result


def validate_all():
    results = [validate_one(m, s) for m, s in CONNECTORS.items()]
    for r in results:
        r["valid"] = (
            r["imports"] and r["class_found"] and not r["missing_methods"]
            and r["instantiates"] and r["dry_run_ok"] and not r["errors"]
        )
        configured = all(r["env_present"].values()) if r["env_present"] else False
        r["configured"] = configured
        # operational state: live+configured = connected; valid+not configured = ready (awaiting creds)
        if r["live"] and configured:
            r["connectivity"] = "connected"
        elif r["valid"] and not configured:
            r["connectivity"] = "ready_awaiting_creds"
        elif r["valid"]:
            r["connectivity"] = "validated"
        else:
            r["connectivity"] = "broken"
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    results = validate_all()
    if args.json:
        print(json.dumps({"connectors": results}, indent=2, default=str))
        return 0
    print("Broker Connector Validation")
    print("=" * 72)
    for r in results:
        mark = "OK " if r["valid"] else "FAIL"
        creds = "configured" if r["configured"] else "no creds"
        print(f"[{mark}] {r['broker']:11s} {r['connectivity']:22s} interface={'ok' if not r['missing_methods'] else 'MISSING:'+','.join(r['missing_methods'])}  creds={creds}")
        for e in r["errors"]:
            print(f"        ! {e}")
    broken = [r for r in results if not r["valid"]]
    print("=" * 72)
    print(f"{len(results)-len(broken)}/{len(results)} connectors valid"
          + (f" — {len(broken)} BROKEN" if broken else ""))
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
