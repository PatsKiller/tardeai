#!/usr/bin/env python3
"""Fetch durable identifiers from Schwab for the symbols identity cannot confirm.

    python scripts/sweep_schwab_instruments.py                # dry run
    python scripts/sweep_schwab_instruments.py --json
    python scripts/sweep_schwab_instruments.py --apply        # write the evidence
    python scripts/sweep_schwab_instruments.py --limit 5      # probe a few first

Phase A minted 400 entities and could confirm 17 of them, because a CUSIP only
existed for symbols we had traded. The active watch universe — the names
decisions are actually being formed about — had no durable identifier anywhere
in the system.

Schwab's `/marketdata/v1/instruments?projection=fundamental` returns a CUSIP for
a symbol we have never held. Alpaca cannot: `cusip` is absent from its
`/v2/assets` schema entirely (checked against all 14,281 active US equities),
so this sweep is the only path to confirming the watch tail.

This writes evidence only. It does not mint, does not touch identity, and holds
no authority over anything: run `mint_identity_registry.py --apply` afterwards to
fold the result into the registry, where the usual upgrade rules apply and old
GUIDs stay resolvable.

Nothing is invented. A symbol Schwab does not resolve is recorded as a miss with
its reason so a later run can tell "asked, nothing there" from "never asked".

AUTHORITY: READ_ONLY_ADVISORY. Reads market-data reference only; no order path.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.lib.identity_registry import load as load_registry  # noqa: E402
from scripts.lib.schwab_instrument_evidence import (  # noqa: E402
    empty_evidence,
    evidence_path,
    load as load_evidence,
    record_instrument,
    record_miss,
    save as save_evidence,
)

BASE_URL = os.getenv("SCHWAB_BASE_URL", "https://api.schwabapi.com")
# Schwab publishes 120 requests/minute for market data. Default leaves headroom
# so a sweep never competes a co-running quote refresh into a 429.
MIN_INTERVAL = float(os.getenv("SCHWAB_INSTRUMENT_MIN_INTERVAL", "0.6"))
ACCOUNT_KEY = os.getenv("SCHWAB_INSTRUMENT_ACCOUNT_KEY", "schwab_taxable")
# A full sweep is ~5,200 broker calls. Saving only at the end means a token
# expiry, a network blip or an operator Ctrl-C throws away the whole run, so the
# store is checkpointed and every completed symbol is skipped on the next pass.
CHECKPOINT_EVERY = int(os.getenv("SCHWAB_INSTRUMENT_CHECKPOINT_EVERY", "100"))
# Statuses that still need a durable identifier. CONFIRMED already has one, and
# re-asking would spend rate limit to learn nothing.
NEEDS_IDENTIFIER = ("UNRESOLVED_WITH_REASON", "CANDIDATE")


def symbols_needing_identifiers(registry: dict[str, Any]) -> list[str]:
    """Active entities that no durable identifier has confirmed yet.

    Superseded entities are skipped: their GUID still resolves forward, and the
    live one is what a fresh identifier should upgrade.
    """
    out = []
    for entity in (registry.get("entities") or {}).values():
        if not entity.get("active", True):
            continue
        if entity.get("identity_status") not in NEEDS_IDENTIFIER:
            continue
        sym = str(entity.get("ticker_alias") or "").strip().upper()
        # A CUSIP-shaped "ticker" is not a symbol the broker can look up.
        if sym and sym.isalpha() and 1 <= len(sym) <= 5:
            out.append(sym)
    return sorted(set(out))


def fetch_instrument(session: Any, token: str, symbol: str, timeout: float = 20.0) -> dict[str, Any]:
    """One reference lookup. Returns {} when the broker resolves nothing."""
    query = urllib.parse.urlencode({"symbol": symbol, "projection": "fundamental"})
    resp = session.get(
        f"{BASE_URL}/marketdata/v1/instruments?{query}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=timeout,
    )
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()
    payload = resp.json() or {}
    instruments = payload.get("instruments") or []
    if not instruments:
        return {}
    # `fundamental` returns the exact-symbol match first.
    return instruments[0] or {}


def already_swept(doc: dict[str, Any], retry_failures: bool = True) -> set[str]:
    """Symbols this store already answered for.

    A miss the broker genuinely returned is an answer and is not re-asked. A
    fetch that failed on our side is not an answer, so by default it is retried.
    """
    done = set(doc.get("instruments") or {})
    for sym, miss in (doc.get("misses") or {}).items():
        if retry_failures and str(miss.get("reason", "")).startswith("fetch_failed"):
            continue
        done.add(sym)
    return done


def run(limit: int | None = None, apply: bool = False, resume: bool = True) -> dict[str, Any]:
    import requests
    from schwab_token_manager import get_access_token

    registry = load_registry()
    targets = symbols_needing_identifiers(registry)
    if limit:
        targets = targets[:limit]

    doc = load_evidence() if apply else empty_evidence()
    session = requests.Session()

    skipped = 0
    if resume:
        done = already_swept(doc)
        before = len(targets)
        targets = [t for t in targets if t not in done]
        skipped = before - len(targets)

    confirmed = misses = errors = 0
    token = get_access_token(ACCOUNT_KEY)
    if not token:
        return {
            "schema": "SchwabInstrumentSweep@v1",
            "authority": "READ_ONLY_ADVISORY",
            "ok": False,
            "error": f"no Schwab access token for account_key={ACCOUNT_KEY}",
            "targets": len(targets),
        }

    last_call = 0.0
    for i, sym in enumerate(targets):
        wait = MIN_INTERVAL - (time.monotonic() - last_call)
        if wait > 0:
            time.sleep(wait)
        # The sweep outlives a single access token; re-read periodically rather
        # than let a long run die at the expiry boundary.
        if i and i % 100 == 0:
            token = get_access_token(ACCOUNT_KEY) or token
        try:
            payload = fetch_instrument(session, token, sym)
            last_call = time.monotonic()
        except Exception as exc:  # noqa: BLE001 — one bad symbol must not end the sweep
            last_call = time.monotonic()
            errors += 1
            record_miss(doc, sym, f"fetch_failed:{type(exc).__name__}")
            continue
        if payload.get("cusip"):
            record_instrument(doc, sym, payload)
            confirmed += 1
        else:
            record_miss(doc, sym, "broker_returned_no_identifier")
            misses += 1
        if apply and CHECKPOINT_EVERY and (i + 1) % CHECKPOINT_EVERY == 0:
            save_evidence(doc)

    result = {
        "schema": "SchwabInstrumentSweep@v1",
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
        "ok": True,
        "applied": bool(apply),
        "account_key": ACCOUNT_KEY,
        "targets": len(targets),
        "skipped_already_swept": skipped,
        "identifiers_found": confirmed,
        "no_identifier": misses,
        "errors": errors,
        "path": str(evidence_path()),
    }
    if apply:
        save_evidence(doc)
    else:
        result["path"] = "(dry run — nothing written)"
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fetch Schwab durable identifiers for unconfirmed identities")
    ap.add_argument("--apply", action="store_true", help="write the evidence store (default: dry run)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="only sweep the first N symbols")
    ap.add_argument("--no-resume", action="store_true",
                    help="re-ask symbols the evidence store already answered for")
    args = ap.parse_args()

    result = run(limit=args.limit, apply=args.apply, resume=not args.no_resume)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for key in ("targets", "skipped_already_swept", "identifiers_found",
                    "no_identifier", "errors", "path"):
            if key in result:
                print(f"{key:20} {result[key]}")
        if not result.get("ok"):
            print(f"ERROR: {result.get('error')}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
