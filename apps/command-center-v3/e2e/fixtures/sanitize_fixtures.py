#!/usr/bin/env python3
"""Sanitize captured Defense/Sectors API payloads into committable render-gate fixtures.

The render gate needs the real SHAPE of the payloads — including the awkward states that
the UI must handle correctly (stale dates, withheld hedges, thin coverage, missing CIO
views, empty get-into lists) — without carrying anything operator-sensitive into the
repository.

Masked: account aliases and identifiers, dollar amounts, share/contract counts, equity
balances, private notes, order/ticket identifiers, internal URLs and anything
credential-shaped.

Preserved deliberately: JSON structure, sector and industry labels, state
classifications, as_of/captured_at dates (staleness is a thing the gate must assert on),
quality and provenance blocks, empty collections, and the withheld/thin/missing markers.

Usage:  sanitize_fixtures.py <raw_dir> <out_dir>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Keys whose VALUE is a monetary or size quantity. Replaced with a fixed placeholder so
# layout still exercises realistic digit widths without disclosing a real position.
MONEY_KEYS = re.compile(
    r"(equity|equities|dollars?|value|market_value|cost_basis|notional|amount|"
    r"balance|cash|proceeds|pnl|p_l|gain|loss|premium)", re.I)
SIZE_KEYS = re.compile(r"(shares|qty|quantity|contracts|position_size|size)$", re.I)
# Keys that are free-text operator content or routing identifiers.
# Identifier/free-text keys. Deliberately anchored: a bare "ticket" also matched
# "sell_ticket", which is a STRUCTURE carrying the display line, not an identifier.
DROP_TEXT_KEYS = re.compile(
    r"^(note|notes|comment|memo|rationale_private|ticket_id|ticket_no|order_id|"
    r"client_order_id|broker_ref|account_id|account_key|account_alias)$", re.I)
URL_RE = re.compile(r"https?://[^\s\"']+")
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|Bearer\s+\S+)", re.I)

_account_map: dict[str, str] = {}


def _account_alias(original: str) -> str:
    if original not in _account_map:
        _account_map[original] = f"ACCOUNT_{chr(ord('A') + len(_account_map))}"
    return _account_map[original]


# Only these containers are genuinely KEYED BY account identifier. Matching any key
# containing "account" was too broad: it renamed the children of account_capabilities
# (whose children are "_comment" and "accounts", not account ids), which silently
# destroyed the payload shape and blanked the Defense page.
ACCOUNT_KEYED_MAPS = {"accounts", "account_equities", "account_aliases", "account_labels"}


def _looks_like_account(key: str) -> bool:
    return key in ACCOUNT_KEYED_MAPS


def scrub(node, key: str = ""):
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            # Account-keyed maps: rename the KEY, keep the structure and the count.
            if _looks_like_account(key) and not k.startswith("_"):
                out[_account_alias(k)] = scrub(v, k)
                continue
            if DROP_TEXT_KEYS.search(k):
                # Only a string is replaced. A dict or list is recursed into instead of
                # being nulled: nulling a structure changes the payload SHAPE, which is
                # exactly what the render gate is supposed to hold constant.
                if isinstance(v, str):
                    out[k] = "REDACTED"
                    continue
                if not isinstance(v, (dict, list)):
                    out[k] = None
                    continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if MONEY_KEYS.search(k):
                    out[k] = 10000.0 if isinstance(v, float) else 10000
                    continue
                if SIZE_KEYS.search(k):
                    out[k] = 100
                    continue
            out[k] = scrub(v, k)
        return out
    if isinstance(node, list):
        return [scrub(v, key) for v in node]
    if isinstance(node, str):
        s = SECRET_RE.sub("REDACTED", node)
        s = URL_RE.sub("https://example.invalid/redacted", s)
        # Dollar figures embedded in display strings.
        s = re.sub(r"\$\s?[\d,]+(?:\.\d+)?", "$10,000", s)
        return s
    return node


def collect_account_ids(node, key: str = "", found: set[str] | None = None) -> set[str]:
    """Every key of an account-keyed map, before any renaming.

    Renaming the map keys alone is not enough: account identifiers are also embedded in
    composite strings elsewhere in the payload (ladder ids such as
    "XLI-<account>-2026-07-24"), which leaked real account names into a committed
    fixture. Those have to be substituted globally in a second pass.
    """
    found = set() if found is None else found
    if isinstance(node, dict):
        for k, v in node.items():
            if key in ACCOUNT_KEYED_MAPS and not k.startswith("_"):
                found.add(k)
            collect_account_ids(v, k, found)
    elif isinstance(node, list):
        for v in node:
            collect_account_ids(v, key, found)
    return found


def substitute_account_ids(node, ids: dict[str, str]):
    """Replace every remaining occurrence of a real account id, in keys and in strings."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            nk = k
            for real, alias in ids.items():
                if real in nk:
                    nk = nk.replace(real, alias)
            out[nk] = substitute_account_ids(v, ids)
        return out
    if isinstance(node, list):
        return [substitute_account_ids(v, ids) for v in node]
    if isinstance(node, str):
        for real, alias in ids.items():
            node = node.replace(real, alias)
        return node
    return node


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    raw_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(raw_dir.glob("raw_*.json")):
        payload = json.loads(src.read_text())
        for account_id in sorted(collect_account_ids(payload), key=len, reverse=True):
            _account_alias(account_id)
        cleaned = scrub(payload)
        # Longest-first so a shorter id cannot partially rewrite a longer one.
        cleaned = substitute_account_ids(
            cleaned, dict(sorted(_account_map.items(), key=lambda kv: -len(kv[0]))))
        dest = out_dir / (src.name.replace("raw_", "") )
        dest.write_text(json.dumps(cleaned, indent=1, sort_keys=True))
        print(f"{src.name} -> {dest.name} ({dest.stat().st_size} bytes)")
    if _account_map:
        print(f"account aliases assigned: {len(_account_map)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
