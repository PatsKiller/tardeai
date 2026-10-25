"""W1 copied-state endpoint consistency check. No DB, providers or store writes."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.lib import cio_truth


def fingerprint(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def check(root: Path, now: datetime) -> dict:
    before = fingerprint(root)
    document = cio_truth.resolve(root, now)
    header = cio_truth.overview_payload({}, document=document)
    holdings = cio_truth.holdings_payload({}, document=document)
    risk = cio_truth.risk_payload(document=document)
    scorecard = cio_truth.scorecard_payload(root=root, canonical_status=document["cio_status"])
    observations = cio_truth.observability_payload(root=root, canonical_status=document["cio_status"])
    assert document["portfolio"]["holdings"], "no real holding rows in copied state"
    assert header["portfolio_value"] == holdings["total_value"]
    assert header["position_count"] == holdings["position_count"] == risk["position_count"]
    assert header["today_change"] == holdings["today_change"] == header["periods"]["1D"]["change"]
    assert sum(a["total_usd"] for a in document["portfolio"]["accounts"]) == header["portfolio_value"]
    by_key = {(r["account_id"], r["symbol"]): r for r in holdings["holdings"]}
    for row in risk["positions"]:
        other = by_key[row["account_id"], row["symbol"]]
        assert row["stop_price"] == other["stop_price"] and row["stop_state"] == other["stop_state"]
    clocks = document["portfolio"]["clock_provenance"]
    for name, clock in clocks.items():
        if clock["raw"] is not None:
            assert clock["as_of"] or clock["gap"], f"{name} clock silently lost"
        if clock["as_of"]:
            assert datetime.fromisoformat(clock["as_of"]).utcoffset() is not None, f"{name} clock lacks offset"
    assert before == fingerprint(root), "resolver modified the copied input tree"
    outputs = {"overview": header, "holdings": holdings, "risk": risk,
               "scorecard": scorecard, "observability": observations}
    return {"ok": True, "as_of": now.isoformat(), "source_files": before,
            "holdings_rows": len(holdings["holdings"]), "position_count": risk["position_count"],
            "company_records": len(document["companies"]["by_guid"]), "writes": 0,
            "clock_provenance": clocks,
            "response_bytes": {name: len(json.dumps(value, default=str).encode()) for name, value in outputs.items()},
            "gaps": {name: section.get("gap") for name, section in document.items() if isinstance(section, dict) and section.get("gap")}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="private COPY containing data/, never production")
    parser.add_argument("--now", required=True, help="pinned ISO timestamp with offset")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    from scripts.lib.canonical_store_registry import production_state_root
    root = args.root.resolve()
    if root == production_state_root().resolve() or any(p.is_symlink() for p in root.rglob("*")):
        parser.error("a private copied tree without symlinks is required")
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    if now.tzinfo is None:
        parser.error("--now requires an explicit UTC offset")
    output = json.dumps(check(root, now), indent=2, default=str) + "\n"
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
