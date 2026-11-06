#!/usr/bin/env python3
"""Validate design/ (AGENTS.md §28.13): registry, page folders, version status files, fingerprints, privacy.

    python3 scripts/check_design_registry.py                       # CI: structure + privacy patterns
    python3 scripts/check_design_registry.py --private-root DIR    # host: every private fingerprint still matches
    python3 scripts/check_design_registry.py --holdings FILE [--account-names FILE]
                                                                   # host: no real ticker / account name in design text
    python3 scripts/check_design_registry.py --scan PATH ...       # privacy-scan extra paths (e.g. fixture baselines' text)

The repository is public. Committed design text may not carry money amounts, grouped amounts, account-number shapes
or (when the host supplies them) real tickers and account names. Exit 0 clean, 1 findings, 2 could not run.

AUTHORITY: READ_ONLY_ADVISORY — reads repo files and, with --private-root, the private design store.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import design_pages as dp  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--private-root", type=Path, help="private design store (persistent-state/data/design)")
    ap.add_argument("--holdings", type=Path, help="host holdings.json: refuse its tickers in committed text")
    ap.add_argument("--account-names", type=Path, help="account display-name map: refuse those names")
    ap.add_argument("--scan", type=Path, nargs="*", default=[], help="extra paths to privacy-scan")
    args = ap.parse_args(argv)
    try:
        errors = dp.validate(args.root)
        terms: set[str] = set()
        if args.holdings:
            terms = dp.holdings_terms(args.holdings, args.account_names)
        privacy = dp.privacy_scan([dp.design_dir(args.root), *args.scan], terms)
        private = dp.verify_private(args.root, args.private_root) if args.private_root else []
    except (OSError, ValueError) as exc:
        print(f"check_design_registry: could not run: {exc}", file=sys.stderr)
        return 2
    for line in errors + privacy + private:
        print(line)
    pages = len(dp.load_registry(args.root).get("pages") or [])
    versions = sum(1 for _ in dp.iter_versions(args.root))
    verdict = "FAIL" if errors or privacy or private else "PASS"
    extra = f"; {len(terms)} private terms" if args.holdings else ""
    extra += "; private fingerprints verified" if args.private_root and not private else ""
    print(f"check_design_registry: {verdict} — {pages} pages, {versions} versions, "
          f"{len(errors)} structure, {len(privacy)} privacy, {len(private)} private-store findings{extra}")
    return 1 if verdict == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
