#!/usr/bin/env python3
"""Deterministic anonymizer for public test fixtures: real portfolio identifiers -> synthetic ones.

The repository is public. Fixtures captured from the live desk carried the operator's held symbols, account ids and
account numbers. This rewrites such files in place with one consistent mapping across every file of a run, so a
fixture and the test that asserts on it stay in step:

  held symbols  -> ZQ.. tickers (letters only, so symbol validators still accept them), in an order keyed by a private
                   salt (no alphabetical leakage). 1-2 letter symbols are replaced only inside quotes, longer ones on
                   word boundaries.
  account ids   -> generic labels by kind (taxable_a, ira_a, roth_a, ...)
  account nos.  -> long digit runs next to an account word become 0000000
  numbers/dates -> NOT generic: bucket or perturb them per fixture so each test keeps its structural intent.

The real symbol and account sets are computed at run time from the host's persistent-state holdings (current and
every holdings backup) and are never written anywhere. The salt lives only under persistent-state (chmod 600).
`check` reports, by file and kind, what real identifiers remain -- counts only, never the values.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import string

NO_CONSUMER_REASON = "operator/agent CLI run once per fixture capture; tests/test_fixture_privacy_anonymize_20261025.py pins its rules"
STATE = Path(pwd.getpwuid(os.getuid()).pw_dir) / "trade-ai-releases/persistent-state"  # real home, not a test-redirected $HOME
HOLDINGS_GLOB = "data/portfolios/state/holdings*"
SALT_FILE = "data/privacy/fixture_anonymize.salt"
BROKERS = "schwab|moomoo|fidelity|alpaca|snaptrade|robinhood|vanguard|etrade|ibkr|webull"
ACCOUNT_WORD = re.compile(r"(?i)(?:\b(?:account|acct)[^\n\d]{0,12}|\b(?:ira|roth|rollover|brokerage|taxable)\W{0,3}#)"
                          r"(?!20\d{6}\b)(\d{6,12})\b")  # not CUSIPs or dates: an account word, or '#', must lead
NOT_SYMBOLS = {"CASH", "MMKT", "SWVXX", "SPAXX", "FDRXX", "SNSXX", "SNOXX", "USD"}  # cash sweeps: code treats them specially


def fake_tickers(n: int) -> list:
    letters = string.ascii_uppercase
    return ["ZQ" + a + b for a in letters for b in letters][:n]


def private_terms(state: Path = STATE) -> tuple:
    """(symbols, accounts) ever held on this host. Values stay in memory."""
    symbols, accounts = set(), set()
    for path in glob.glob(str(state / HOLDINGS_GLOB)):
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = doc.get("holdings") if isinstance(doc, dict) else doc
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            for key in ("account_id", "account"):
                value = str(row.get(key) or "")
                if re.search(r"[A-Za-z]", value) and len(value) >= 5:  # skip bare masked tails like "...123"
                    accounts.add(value)
            try:
                qty = float(row.get("quantity") or row.get("shares") or 0)
            except (TypeError, ValueError):
                qty = 0
            sym = str(row.get("symbol") or "").upper().strip()
            if sym and qty > 0 and not row.get("is_cash") and re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", sym):
                symbols.add(sym)
    return symbols, accounts


def salt(state: Path = STATE) -> str:
    path = state / SALT_FILE
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(16) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
    return path.read_text(encoding="utf-8").strip()


def symbol_map(symbols, salt_value: str) -> dict:
    order = sorted(symbols, key=lambda s: hashlib.sha256((salt_value + s).encode()).hexdigest())
    return dict(zip(order, fake_tickers(len(order))))


def account_map(accounts) -> dict:
    out, counts = {}, {}
    for real in sorted(accounts):
        low = real.lower()
        kind = ("roth" if "roth" in low else "ira" if "ira" in low or "rollover" in low
                else "taxable" if "taxable" in low or "individual" in low or "brokerage" in low else "account")
        out[real] = f"{kind}_{chr(ord('a') + counts.get(kind, 0))}"
        counts[kind] = counts.get(kind, 0) + 1
    return out


def symbol_pattern(sym: str) -> re.Pattern:
    if len(sym) <= 2:  # "V", "GE": only as a whole quoted token
        return re.compile(r"(?<=[\"'])" + re.escape(sym) + r"(?=[\"'])")
    return re.compile(r"(?<![A-Za-z0-9_$])" + re.escape(sym) + r"(?![A-Za-z0-9_])")


def anonymize_text(text: str, sym_map: dict, acct_map: dict) -> str:
    for real in sorted(acct_map, key=len, reverse=True):
        text = re.sub(r"(?<![A-Za-z0-9_])" + re.escape(real) + r"(?![A-Za-z0-9_])", acct_map[real], text)
    for real in sorted(set(sym_map) - NOT_SYMBOLS, key=len, reverse=True):
        text = symbol_pattern(real).sub(sym_map[real], text)
    return ACCOUNT_WORD.sub(lambda m: m.group(0)[: m.start(1) - m.start(0)] + "0" * 7, text)


def guard_pattern(sym: str) -> re.Pattern:
    """The privacy guard's test: any whole-word occurrence, quoted or not (stricter than apply's rule)."""
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(sym) + r"(?![A-Za-z0-9_])")


def leftovers(text: str, symbols, accounts) -> dict:
    found = {"symbols": sum(1 for s in set(symbols) - NOT_SYMBOLS if guard_pattern(s).search(text)),
             "accounts": sum(1 for a in accounts if guard_pattern(a).search(text)),
             "account_numbers": len([m for m in ACCOUNT_WORD.finditer(text) if set(m.group(1)) != {"0"}]),
             "account_slugs": len(re.findall(rf"(?i)\b({BROKERS})_[a-z0-9_]*(ira|roth|taxable|rollover|brokerage|"
                                             r"401k|hsa|individual|joint)[a-z0-9_]*\b", text))}
    return {k: v for k, v in found.items() if v}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("apply", "check"))
    parser.add_argument("files", nargs="+")
    args = parser.parse_args(argv)
    symbols, accounts = private_terms()
    if not symbols:
        print(json.dumps({"ok": False, "reason": "no host holdings: the real sets are host-only"}))
        return 2
    sym_map, acct_map = symbol_map(symbols, salt()), account_map(accounts)
    report = {}
    for name in args.files:
        path = Path(name)
        text = path.read_text(encoding="utf-8")
        if args.action == "apply":
            new = anonymize_text(text, sym_map, acct_map)
            if new != text:
                path.write_bytes(new.encode("utf-8"))
            text = new
        left = leftovers(text, symbols, accounts)
        if left:
            report[name] = left
    print(json.dumps({"ok": not report, "files": len(args.files), "remaining": report}, indent=1))
    return 0 if not report else 1


if __name__ == "__main__":
    raise SystemExit(main())
