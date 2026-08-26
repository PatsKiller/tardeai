#!/usr/bin/env python3
"""Stage one operator-authorized canon source; never downloads source material."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.cio_canon_v1 import admit_canon_source  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--lawful-basis", required=True, choices=["LAWFUL_PRIVATE", "PUBLIC_DOMAIN", "LICENSED"])
    parser.add_argument("--edition", required=True)
    parser.add_argument("--operator-authorized", action="store_true", required=True)
    parser.add_argument("--catalog", default=str(ROOT / "config/cio_research_source_catalog.json"))
    parser.add_argument("--output-dir", default=str(ROOT / "data/cio/canon_extracted"))
    args = parser.parse_args()
    source, chunks = admit_canon_source(
        source_id=args.source_id,
        source_path=args.source_path,
        catalog_path=args.catalog,
        lawful_basis=args.lawful_basis,
        operator_authorized=args.operator_authorized,
        edition=args.edition,
    )
    destination = Path(args.output_dir) / args.source_id / source["source_hash"]
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "source.json").write_text(json.dumps(source, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (destination / "chunks.jsonl").open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk, sort_keys=True) + "\n")
    print(json.dumps({
        "ok": True,
        "source_id": source["source_id"],
        "source_hash": source["source_hash"],
        "chunk_count": len(chunks),
        "output": str(destination),
        "rag_target": "content_embeddings",
        "rag_status": "STAGED_NOT_INDEXED",
        "authority": source["authority"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
