#!/usr/bin/env python3
"""issuer_segments_shadow.py — SHADOW run of the EDGAR segment extractor (DSN-20261101 P1). Writes no store.

Finds each issuer's newest 10-K/10-Q through companyconcept, parses the filing's XBRL instance for segment-axis
revenue, maps the lines with config/issuer_segment_map.json and writes ONE receipt file under the temp directory (or
a ``data/runtime`` path given with --receipt). Nothing reads the receipt; the market-risk look-through keeps reading
config/issuer_segments.json (APPROVED entries) only. The issuer_segments store waits on the operator's §7A grant.

  --replay DIR   offline, from recorded fixtures (default tests/fixtures/edgar/<SYM>/)
  --live         network through scripts/lib/sec_edgar_client.py (declared contact, fails closed, rate-limited)
  --record DIR   with --live: also record every response (gzip-wrapped, sha256 of the original bytes) for fixtures
  --issuer SYM:CIK[:PROFILE_GROUP[:ACCESSION]]   repeatable; the CIK is the identity, the ticker is display only

Exit codes: 0 receipt written (per-issuer refusals are findings in it); 1 a fetch/contact failure for every issuer;
2 usage error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib import sec_edgar_client  # noqa: E402
from lib.issuer_segments import edgar_fetch, mapping, shadow  # noqa: E402

FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "edgar"


def _issuers(specs: list[str]) -> list[dict]:
    out = []
    for s in specs:
        parts = s.split(":")
        if len(parts) < 2 or not parts[0] or not parts[1].isdigit():
            raise SystemExit(f"--issuer wants SYM:CIK[:PROFILE_GROUP[:ACCESSION]], got {s!r}")
        out.append({"symbol": parts[0].upper(), "cik": parts[1],
                    "profile_group": (parts[2] or None) if len(parts) > 2 else None,
                    "accession": (parts[3] or None) if len(parts) > 3 else None})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--replay", nargs="?", const=str(FIXTURES), help="fixture root (per-symbol subdirectories)")
    g.add_argument("--live", action="store_true")
    ap.add_argument("--record", help="with --live: fixture root to record responses into")
    ap.add_argument("--issuer", action="append", required=True)
    ap.add_argument("--receipt", help="receipt path (temp or data/runtime only)")
    ap.add_argument("--map", help="mapping config (default config/issuer_segment_map.json)")
    a = ap.parse_args(argv)
    if a.record and not a.live:
        ap.error("--record needs --live")
    cfg = mapping.load_map(Path(a.map) if a.map else None)
    issuers = _issuers(a.issuer)
    results = []
    for i in issuers:
        if a.live:
            f = edgar_fetch.RecordingFetcher(Path(a.record) / i["symbol"]) if a.record else edgar_fetch.LiveFetcher()
        else:
            f = edgar_fetch.FixtureFetcher(Path(a.replay) / i["symbol"])
        try:
            results.append(shadow.extract_issuer(f, symbol=i["symbol"], cik=i["cik"], profile_group=i["profile_group"],
                                                 cfg=cfg, accession=i["accession"]))
        except sec_edgar_client.SecContactError as exc:
            results.append({"symbol": i["symbol"], "cik": edgar_fetch.cik10(i["cik"]), "status": "refused_no_contact",
                            "error": str(exc), "flags": ["no_filing_split"]})
    receipt = shadow.build_receipt(results, mode="live" if a.live else "replay")
    path = shadow.write_receipt(receipt, Path(a.receipt) if a.receipt else shadow.default_receipt_path())
    summary = [{"symbol": r["symbol"], "status": r.get("status"), "groups": r.get("groups"), "themes": r.get("themes"),
                "accession": (r.get("source") or {}).get("accession"), "flags": r.get("flags")} for r in results]
    print(json.dumps({"receipt": str(path), "issuers": summary}, indent=1))
    failed = {"fetch_failed", "refused_no_contact"}
    return 1 if results and all(r.get("status") in failed for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
