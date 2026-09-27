#!/usr/bin/env python3
"""check_contract_manifest.py — contract drift detector (05 §5). Compares docs/contracts/*_v1.md hashes with
config/contract_manifest.json. Exit 1 on drift or a missing contract; --update rewrites the manifest (review the diff)."""
from __future__ import annotations
import hashlib, json, sys, datetime
from pathlib import Path
PROJ = Path(__file__).resolve().parents[1]
MAN = PROJ / "config" / "contract_manifest.json"

def current() -> dict:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((PROJ / "docs" / "contracts").glob("*_v1.md"))}

def main() -> int:
    cur = current()
    if "--update" in sys.argv:
        MAN.write_text(json.dumps({"schema": "ContractManifest@v1", "as_of": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                   "_note": "Content hashes of the standard interface contracts (05 §5 contract drift). Regenerate: python3 scripts/check_contract_manifest.py --update; CI compares.",
                                   "contracts": cur}, indent=2) + "\n"); print(f"manifest updated ({len(cur)} contracts)"); return 0
    if not MAN.exists():
        print("no manifest", file=sys.stderr); return 1
    want = json.loads(MAN.read_text())["contracts"]
    drift = [k for k in want if cur.get(k) != want[k]] + [k for k in cur if k not in want]
    if drift:
        print(f"contract drift: {drift} — a contract changed without its manifest (and its consumers) — run --update after review", file=sys.stderr); return 1
    print(f"contracts: OK ({len(cur)})"); return 0

if __name__ == "__main__":
    sys.exit(main())
