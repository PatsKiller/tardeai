#!/usr/bin/env python3
"""Stamp organic (non-canary) LLM volume onto SecurityResearchSpine.

Uses production notify_llm_curation with NO canary/backfill extra_tags.
Default subject HPE (gap_resolution llm_curation history exists).
READ_ONLY_ADVISORY tip content — not a fact source.
"""
from __future__ import annotations

NO_CONSUMER_REASON = (
    "ops CLI for organic LLM volume close; operator/agent invokes; "
    "spine tip + organic metric JSON are consumer artifacts"
)

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_TEXT = (
    "Organic llm_curation onto SecurityResearchSpine from desk/gap history: "
    "GapResolutionReceipt vector=llm_curation model=deepseek-flash recorded "
    "partial curation of gathered evidence. CIO-owned tip; "
    "curation_of_gathered_evidence_not_a_fact_source; READ_ONLY_ADVISORY."
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--symbol", default="HPE")
    ap.add_argument("--text", default=DEFAULT_TEXT)
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--source", default="llm_curation")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = args.root or Path(
        os.environ.get("TRADEAI_PRIMARY_ROOT")
        or "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
    )
    os.environ.setdefault("CROSS_ASSET_SPINE", "1")
    from scripts.lib.cross_asset.hooks import notify_llm_curation
    from scripts.ops.spine_llm_organic_metric import measure

    out = notify_llm_curation(
        [str(args.symbol).upper()],
        text=str(args.text)[:800],
        source=str(args.source),
        model=args.model,
        curated_from=["gap_resolution_receipts", "organic_volume_close"],
        root=root,
    )
    metric = measure(root)
    payload = {"notify": out, "metric": metric}
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(
            f"notify ok={out.get('ok')} written={out.get('written')} "
            f"organic={metric.get('organic_latest_llm')} "
            f"canary={metric.get('canary_or_backfill_latest_llm')} "
            f"sample={metric.get('organic_symbols_sample')}"
        )
    return 0 if out.get("ok") and int(metric.get("organic_latest_llm") or 0) >= 1 else 2


if __name__ == "__main__":
    raise SystemExit(main())
