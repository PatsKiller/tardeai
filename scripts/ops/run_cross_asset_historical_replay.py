#!/usr/bin/env python3
"""Historical replay scaffolding — honest INSUFFICIENT_DATA until archives wired.

Usage:
  .venv/bin/python scripts/ops/run_cross_asset_historical_replay.py --days 30 --out /tmp/cadi_metrics.json
"""
from __future__ import annotations

# CLI-only until Phase 9 scheduler owns a continuous replay consumer.
NO_CONSUMER_REASON = (
    "CrossAssetHistoricalReplayMetrics@v1 is emitted by this CLI only until "
    "CADI Phase 9 wires a scheduled consumer; refuse invented counterfactuals without archives."
)

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def run_window(days: int, *, archive_dir: Path | None) -> dict:
    """Replay window. Without signal/price archives, return honest insufficient metrics."""
    has_signals = bool(archive_dir and (archive_dir / "signals.jsonl").exists())
    has_prices = bool(archive_dir and (archive_dir / "prices.jsonl").exists())
    has_chains = bool(archive_dir and (archive_dir / "option_chains").exists())
    if not (has_signals and has_prices):
        return {
            "window_days": days,
            "data_quality": "INSUFFICIENT_DATA",
            "signals_evaluated": 0,
            "shares_chosen": 0,
            "options_would_be_superior": 0,
            "options_superior_rate": None,
            "note": "Signal/price archives not present — refusing to invent counterfactuals",
            "archives": {
                "signals": has_signals,
                "prices": has_prices,
                "option_chains": has_chains,
                "archive_dir": str(archive_dir) if archive_dir else None,
            },
            "as_of": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "authority": "READ_ONLY_ADVISORY",
        }
    # Future: walk signals and compare expressions using archives.
    return {
        "window_days": days,
        "data_quality": "AVAILABLE",
        "signals_evaluated": 0,
        "note": "Archive present but replay engine not yet implemented",
        "authority": "READ_ONLY_ADVISORY",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, nargs="+", default=[30, 60, 90])
    ap.add_argument("--archive-dir", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    archive = Path(args.archive_dir) if args.archive_dir else None
    metrics = {
        "schema": "CrossAssetHistoricalReplayMetrics@v1",
        "windows": [run_window(d, archive_dir=archive) for d in args.days],
        "authority": "READ_ONLY_ADVISORY",
    }
    text = json.dumps(metrics, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(json.dumps({"ok": True, "wrote": args.out}))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
