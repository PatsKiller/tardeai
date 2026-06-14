#!/usr/bin/env python3
"""snaptrade_sync.py — read-only holdings sync from SnapTrade into holdings.json.

ADDITIVE + SAFE BY DEFAULT:
  • Dry run unless --apply (prints what WOULD change; writes nothing).
  • Only the accounts mapped in config/snaptrade_accounts.json are touched; every other account in
    holdings.json is preserved verbatim.
  • The write goes through schwab_position_sync.protected_holdings_write() — same sanity / no-wipe /
    catastrophic-drop guard as the Schwab sync.
  • No trading. Read only.

Setup: save client keys (UI modal) → `snaptrade_connect.py register/login` → map accounts in
config/snaptrade_accounts.json → run this (dry) → `--apply` once it looks right.

  python3 scripts/snaptrade_sync.py            # dry run
  python3 scripts/snaptrade_sync.py --apply    # merge mapped accounts into holdings.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "brokers"))

HOLDINGS_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
ACCOUNTS_MAP_PATH = PROJECT_ROOT / "config" / "snaptrade_accounts.json"


def _load_account_map() -> dict:
    """{ snaptrade_account_id: internal_account_key }."""
    if not ACCOUNTS_MAP_PATH.exists():
        return {}
    try:
        cfg = json.loads(ACCOUNTS_MAP_PATH.read_text())
        return cfg.get("accounts", cfg) if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _merge(current: dict, synced_by_account: dict[str, list[dict]]) -> dict:
    """Replace ONLY the synced accounts' positions; keep everything else untouched. Pure function."""
    owned = set(synced_by_account.keys())
    kept = [h for h in current.get("holdings", []) if h.get("account") not in owned]
    fresh = [pos for positions in synced_by_account.values() for pos in positions]
    out = dict(current)
    out["holdings"] = kept + fresh
    return out


def _summary(positions: list[dict]) -> str:
    n = len(positions)
    val = sum(float(p.get("market_value") or 0) for p in positions)
    return f"{n} positions, ${val:,.0f}"


def run(apply: bool = False) -> dict:
    from brokers import snaptrade_read as sr
    from brokers import snaptrade_credentials as creds

    if not creds.status().get("ready"):
        return {"ok": False, "error": "client keys not set (UI modal)"}
    if not creds.user_status().get("ready"):
        return {"ok": False, "error": "no connected user — run snaptrade_connect.py register/login"}

    acct_map = _load_account_map()
    if not acct_map:
        return {"ok": False, "error": f"no account mapping — fill {ACCOUNTS_MAP_PATH}"}

    try:
        user = sr.SnapTradeUser.from_env()
        accounts = sr.list_accounts(user)
    except Exception as e:
        return {"ok": False, "error": f"snaptrade read failed: {e}"}

    synced: dict[str, list[dict]] = {}
    report = []
    for a in accounts:
        aid = str(a.get("id") or a.get("account_id") or "")
        key = acct_map.get(aid)
        if not key:
            continue  # account not opted into the sync
        try:
            raw = sr.holdings(user, aid)
            positions = sr.normalize_positions(raw, key)
        except Exception as e:
            report.append(f"  {key} ({aid}): read error — {e}")
            continue
        synced[key] = positions
        report.append(f"  {key} ({aid}): {_summary(positions)}")

    print("SnapTrade read-only sync — mapped accounts:")
    print("\n".join(report) if report else "  (no mapped accounts matched the connected brokerages)")

    if not synced:
        return {"ok": True, "applied": False, "accounts": 0, "note": "nothing to sync"}

    if not apply:
        print("DRY RUN — nothing written. Re-run with --apply to merge into holdings.json.")
        return {"ok": True, "applied": False, "accounts": len(synced),
                "would_write": {k: len(v) for k, v in synced.items()}}

    # apply: merge only the synced accounts, write through the sanity gate
    import schwab_position_sync as sps
    current = json.loads(HOLDINGS_PATH.read_text()) if HOLDINGS_PATH.exists() else {"holdings": []}
    merged = _merge(current, synced)
    result = sps.protected_holdings_write(merged, source="snaptrade",
                                          account_key=",".join(sorted(synced.keys())), protect_basis=False)
    print(f"holdings write: {result.get('status')} (wrote={result.get('wrote')})")
    return {"ok": bool(result.get("wrote")), "applied": True, "accounts": len(synced), "write": result}


def main():
    ap = argparse.ArgumentParser(description="SnapTrade read-only holdings sync.")
    ap.add_argument("--apply", action="store_true", help="merge mapped accounts into holdings.json (default: dry run)")
    a = ap.parse_args()
    out = run(apply=a.apply)
    print(json.dumps(out, indent=2, default=str))
    sys.exit(0 if out.get("ok") else 1)


if __name__ == "__main__":
    main()
