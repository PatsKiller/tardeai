#!/usr/bin/env python3
"""Dry report: delivery receipts, lesson binds, 1-hop graph, EDGAR proof.

    python3 scripts/cio_wave3c_report.py --root CURRENT [--json] [--fetch-edgar]

Sends nothing and, unless `--fetch-edgar` is passed, reaches no network. The
EDGAR fetch is capped at one request for one symbol.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.lib import cio_delivery_receipt as receipt  # noqa: E402
from scripts.lib import cio_lesson_bind as lesson  # noqa: E402
from scripts.lib import cio_notification_policy as policy  # noqa: E402
from scripts.lib.cio_edgar_proof import build_proof  # noqa: E402
from scripts.lib.cio_graph_impact_held import build as graph_build  # noqa: E402

NO_CONSUMER_REASON = (
    "operator-run CLI entry point: Wave3CReport@v1 is the shape this script "
    "prints and its consumer is a person. The library schemas it exercises — "
    "DeliveryReceipt@v1, LessonBind@v1, CIOGraphImpactHeld@v1, "
    "EdgarFilingProof@v1 — are consumed here."
)

OPEN_STATUS = {"draft", "proposed"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("TRADEAI_ROOT") or ".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fetch-edgar", action="store_true")
    ap.add_argument("--symbol", default="V")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    now = datetime.now(timezone.utc)

    try:
        doc = json.loads((root / "data" / "cio" / "cio_plans_projection.json")
                         .read_text(encoding="utf-8"))
        plans = [p for p in (doc.get("plans") or {}).values() if isinstance(p, dict)]
    except Exception:
        plans = []

    seen: set[tuple] = set()
    receipts = []
    for p in plans:
        if str(p.get("status")) not in OPEN_STATUS:
            continue
        syms = p.get("symbols") or []
        key = (str(p.get("situation_type")), syms[0] if syms else None)
        dup = key in seen
        seen.add(key)
        d = policy.decide(p, duplicate_subject=dup, now=now)
        receipts.append(receipt.build(d, now=now))

    channels = Counter(r["would_channel"] for r in receipts)

    holdings = {}
    held: set[str] = set()
    dust: set[str] = set()
    try:
        from scripts.lib.holdings_universe import (
            held_dust_tickers, held_equity_tickers_nondust,
        )
        holdings = json.loads((root / "data" / "portfolios" / "state"
                               / "holdings.json").read_text(encoding="utf-8"))
        held = set(held_equity_tickers_nondust(root=root) or [])
        dust = set(held_dust_tickers(root=root) or [])
    except Exception:
        pass
    graph = graph_build(symbols=sorted(held) + ["CASH"], holdings=holdings,
                        held=held, dust=dust)

    edgar = build_proof(args.symbol, repo_root=REPO, fetch=args.fetch_edgar)

    out = {
        "schema": "Wave3CReport@v1",
        "as_of": now.isoformat(),
        "authority": "READ_ONLY_ADVISORY",
        "receipts": len(receipts),
        "by_would_channel": dict(channels),
        "would_send_any": any(r["would_send"] for r in receipts),
        "graph": graph["counts"],
        "edgar": {"symbol": args.symbol, "status": edgar["status"],
                  "fetches": edgar["fetches_performed"]},
        "env": policy.notify_env_state(),
    }
    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0

    print(f"Wave 3C dry report — root={root}")
    print(f"  delivery receipts : {out['receipts']}")
    for k, v in channels.most_common():
        print(f"    would_channel {k:<10} {v}")
    print(f"  WOULD SEND ANY    : {out['would_send_any']}")
    print()
    print(f"  graph 1-hop       : {graph['counts']}")
    print(f"  edgar {args.symbol:<12}: {edgar['status']} "
          f"(fetches {edgar['fetches_performed']}/{edgar['max_fetches']})")
    print(f"  notify_enabled    : {out['env']['notify_enabled']}   "
          f"interdicted: {out['env']['interdicted']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
