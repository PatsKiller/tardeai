#!/usr/bin/env python3
"""Resolve due outcome checkpoints into recorded outcomes.

    python scripts/resolve_due_checkpoints.py              # dry run
    python scripts/resolve_due_checkpoints.py --json
    python scripts/resolve_due_checkpoints.py --apply
    python scripts/resolve_due_checkpoints.py --limit 5    # probe a few first

The learning loop compares what was decided against what happened. That
comparison had never run: `process_due_checkpoint` and `persist_observation`
existed unused, so 183 checkpoints accumulated with 50 already past their
`due_at` and none ever resolved. This is the caller.

Both ends of the comparison come from `ticker_prices`, because the decision
state records no price of its own. If either end is missing the checkpoint is
recorded as OUTCOME_PENDING_DATA and stays due — a fabricated outcome teaches
the system something untrue and leaves no later signal that it was wrong.

Writes are append-only: resolving appends a new version of the checkpoint
carrying its `outcome_id`, and the original row stays exactly as written.

AUTHORITY: READ_ONLY_ADVISORY. Observational only; no trading, no authority.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.cio_institutional_learning import (  # noqa: E402
    CHECKPOINT_PATH,
    _append,
    _jsonl,
    persist_observation,
    process_due_checkpoint,
)
from scripts.lib.outcome_resolution import (  # noqa: E402
    STATUS_NOT_PRICE_RESOLVABLE,
    STATUS_PENDING_DATA,
    STATUS_RESOLVED,
    due_checkpoints,
    price_resolvable,
    realized_state,
    resolution_row,
)


def _state_root() -> Path:
    from scripts.lib.canonical_store_registry import production_state_root
    return Path(production_state_root())


def _price_lookup_factory():
    """Close on or before a date, from ticker_prices. None when absent."""
    try:
        from price_db_sync import _get_conn  # type: ignore
        conn = _get_conn()
    except Exception:
        return lambda symbol, on_or_before: None

    def lookup(symbol: str, on_or_before: str):
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT close_price, price_date FROM ticker_prices "
                "WHERE symbol = %s AND price_date <= %s "
                "ORDER BY price_date DESC LIMIT 1",
                (symbol, on_or_before),
            )
            row = cur.fetchone()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return None
        if not row or row[0] is None:
            return None
        return float(row[0]), str(row[1])

    return lookup


def _registry_lookup_factory():
    """True when a symbol is a registered entity. Absent registry => allow."""
    try:
        from scripts.lib.identity_registry import load_cached, lookup_symbol
        registry = load_cached()
    except Exception:
        return None
    return lambda symbol: bool(lookup_symbol(registry, symbol))


def run(apply: bool = False, limit: int | None = None) -> dict[str, Any]:
    root = _state_root()
    rows = _jsonl(root / CHECKPOINT_PATH)
    due = due_checkpoints(rows)
    if limit:
        due = due[:limit]

    lookup = _price_lookup_factory()
    registry_lookup = _registry_lookup_factory()
    resolved = pending = not_resolvable = 0
    reasons: dict[str, int] = {}
    samples: list[dict[str, Any]] = []

    for cp in due:
        # A cash-sleeve or pseudo-symbol decision is not a price comparison.
        # Pricing it against a same-named ticker is how 37 confident wrong
        # outcomes would have entered the learning loop on the first run.
        ok, reason = price_resolvable(cp, registry_lookup)
        if not ok:
            not_resolvable += 1
            reasons[reason or "unknown"] = reasons.get(reason or "unknown", 0) + 1
            if apply:
                _append(root / CHECKPOINT_PATH,
                        resolution_row(cp, None, STATUS_NOT_PRICE_RESOLVABLE, reason=reason))
            continue

        available, realized, source_refs = realized_state(cp, lookup)
        processed = process_due_checkpoint(
            checkpoint=cp,
            source_available=available,
            realized_state=realized,
            source_refs=source_refs,
        )
        if processed.get("status") != "OBSERVED":
            pending += 1
            if apply:
                _append(root / CHECKPOINT_PATH,
                        resolution_row(cp, None, STATUS_PENDING_DATA,
                                       reason="no_price_history_for_comparison"))
            continue

        observation = processed["observation"]
        if apply:
            persist_observation(root, observation)
            _append(root / CHECKPOINT_PATH,
                    resolution_row(cp, observation["outcome_id"], STATUS_RESOLVED))
        resolved += 1
        if len(samples) < 10:
            samples.append({
                "checkpoint_id": cp.get("checkpoint_id"),
                "decision_id": cp.get("decision_id"),
                "symbol": realized.get("symbol"),
                "recommendation": realized.get("recommendation"),
                "change_pct": realized.get("change_pct"),
                "outcome_id": observation["outcome_id"],
            })

    return {
        "schema": "DueCheckpointResolution@v1",
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
        "applied": bool(apply),
        "due": len(due),
        "resolved": resolved,
        "pending_data": pending,
        "not_price_resolvable": not_resolvable,
        "not_resolvable_reasons": reasons,
        "samples": samples,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Resolve due outcome checkpoints")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    result = run(apply=args.apply, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        for key in ("due", "resolved", "pending_data", "not_price_resolvable", "applied"):
            print(f"{key:22} {result[key]}")
        for reason, n in sorted(result["not_resolvable_reasons"].items(), key=lambda kv: -kv[1]):
            print(f"  not resolvable: {n:3}x  {reason}")
        for s in result["samples"]:
            print(f"  {s['symbol'] or '?':6} {str(s['recommendation'] or ''):8} "
                  f"{s['change_pct']:+.2f}%  -> {s['outcome_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
