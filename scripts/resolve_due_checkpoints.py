#!/usr/bin/env python3
"""Resolve due outcome checkpoints into recorded outcomes.

    python scripts/resolve_due_checkpoints.py              # dry run (SCHEDULED + PENDING triage)
    python scripts/resolve_due_checkpoints.py --json
    python scripts/resolve_due_checkpoints.py --apply      # SCHEDULED only (cron path)
    python scripts/resolve_due_checkpoints.py --limit 5    # probe a few first
    TRADEAI_PENDING_DATA_APPLY=1 \\
      python scripts/resolve_due_checkpoints.py --apply-pending-data

The learning loop compares what was decided against what happened. That
comparison had never run: `process_due_checkpoint` and `persist_observation`
existed unused, so 183 checkpoints accumulated with 50 already past their
`due_at` and none ever resolved. This is the caller.

Both ends of the comparison come from `ticker_prices`, because the decision
state records no price of its own. If either end is missing the checkpoint is
recorded as OUTCOME_PENDING_DATA — a fabricated outcome teaches the system
something untrue and leaves no later signal that it was wrong.

Wave D2: OUTCOME_PENDING_DATA must not sit forever. Every dry run censuses
pending rows into future_dated / obtainable / stuck_waiting_data /
never_resolvable. `--apply-pending-data` (env-gated) resolves obtainable
rows and expires never-resolvable ones with an explicit reason. Cron
`--apply` still only touches SCHEDULED due rows.

Writes are append-only: resolving or expiring appends a new version; the
original row stays exactly as written.

AUTHORITY: READ_ONLY_ADVISORY. Observational only; no trading, no authority.
"""
from __future__ import annotations

SCHEDULED_ENTRYPOINT = (
    'cron: 20 * * * * -- hourly, --apply (wired 2026-08-27, Phase 2)'
)

import argparse
import json
import os
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
    CLASS_FUTURE,
    CLASS_NEVER,
    CLASS_OBTAINABLE,
    CLASS_STUCK,
    PENDING_APPLY_ENV,
    STATUS_EXPIRED,
    STATUS_NOT_PRICE_RESOLVABLE,
    STATUS_PENDING_DATA,
    STATUS_RESOLVED,
    due_checkpoints,
    pending_data_checkpoints,
    price_resolvable,
    realized_state,
    resolution_row,
    triage_pending_data,
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


def pending_apply_armed() -> bool:
    """True only when TRADEAI_PENDING_DATA_APPLY=1 (exact)."""
    return os.environ.get(PENDING_APPLY_ENV) == "1"


def run_scheduled(apply: bool = False, limit: int | None = None) -> dict[str, Any]:
    """Existing SCHEDULED-due path. Cron uses --apply here; unchanged semantics."""
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


def run_pending_triage(
    *,
    apply: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Census PENDING_DATA; optionally resolve obtainable / expire never (env-gated)."""
    root = _state_root()
    rows = _jsonl(root / CHECKPOINT_PATH)
    lookup = _price_lookup_factory()
    registry_lookup = _registry_lookup_factory()
    triage = triage_pending_data(
        rows,
        price_lookup=lookup,
        registry_lookup=registry_lookup,
        limit=limit,
    )

    refused: dict[str, Any] | None = None
    resolved = expired = 0
    resolve_samples: list[dict[str, Any]] = []
    expire_samples: list[dict[str, Any]] = []

    if apply and not pending_apply_armed():
        refused = {
            "flag": "--apply-pending-data",
            "reason": "APPLY_REFUSED",
            "detail": (
                f"--apply-pending-data refused unless {PENDING_APPLY_ENV}=1. "
                "Even when armed, writes are append-only resolve/expire receipts."
            ),
            "env": PENDING_APPLY_ENV,
            "env_value": os.environ.get(PENDING_APPLY_ENV),
        }
        apply = False

    # Map checkpoint_id -> live row for writes.
    live = {str(cp.get("checkpoint_id")): cp for cp in pending_data_checkpoints(rows)}

    for item in triage["classified"]:
        klass = item["class"]
        cid = str(item.get("checkpoint_id") or "")
        cp = live.get(cid)
        if cp is None:
            continue

        if klass == CLASS_OBTAINABLE and item.get("action") == "resolve":
            realized = item.get("realized_state") or {}
            source_refs = item.get("source_refs") or []
            processed = process_due_checkpoint(
                checkpoint=cp,
                source_available=True,
                realized_state=realized,
                source_refs=source_refs,
            )
            if processed.get("status") != "OBSERVED":
                continue
            observation = processed["observation"]
            if apply:
                persist_observation(root, observation)
                _append(
                    root / CHECKPOINT_PATH,
                    resolution_row(cp, observation["outcome_id"], STATUS_RESOLVED,
                                   reason="pending_data_triage_prices_obtained"),
                )
            resolved += 1
            if len(resolve_samples) < 10:
                resolve_samples.append({
                    "checkpoint_id": cid,
                    "symbol": realized.get("symbol"),
                    "change_pct": realized.get("change_pct"),
                    "outcome_id": observation["outcome_id"],
                    "decision_price_date": realized.get("decision_price_date"),
                    "horizon_price_date": realized.get("horizon_price_date"),
                })
            continue

        if klass == CLASS_NEVER and item.get("action") == "expire":
            reason = f"pending_data_expired:{item.get('reason')}"
            if apply:
                _append(
                    root / CHECKPOINT_PATH,
                    resolution_row(cp, None, STATUS_EXPIRED, reason=reason),
                )
            expired += 1
            if len(expire_samples) < 10:
                expire_samples.append({
                    "checkpoint_id": cid,
                    "symbol": item.get("symbol"),
                    "reason": item.get("reason"),
                    "status": STATUS_EXPIRED,
                })

    counts = triage["counts"]
    return {
        "schema": triage["schema"],
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
        "observational_only": True,
        "as_of": triage["as_of"],
        "root": str(root),
        "checkpoint_path": CHECKPOINT_PATH,
        "applied": bool(apply),
        "apply_env": PENDING_APPLY_ENV,
        "apply_refused": refused,
        "pending_total": triage["pending_total"],
        "future_dated": counts.get(CLASS_FUTURE, 0),
        "obtainable": counts.get(CLASS_OBTAINABLE, 0),
        "stuck_waiting_data": counts.get(CLASS_STUCK, 0),
        "never_resolvable": counts.get(CLASS_NEVER, 0),
        "would_resolve": counts.get(CLASS_OBTAINABLE, 0),
        "would_expire": counts.get(CLASS_NEVER, 0),
        "resolved": resolved if apply else 0,
        "expired": expired if apply else 0,
        "reasons": triage["reasons"],
        "resolve_samples": resolve_samples,
        "expire_samples": expire_samples,
    }


def run(
    apply: bool = False,
    limit: int | None = None,
    *,
    apply_pending_data: bool = False,
) -> dict[str, Any]:
    """SCHEDULED due pass + always-on PENDING_DATA triage (dry unless gated)."""
    scheduled = run_scheduled(apply=apply, limit=limit)
    triage = run_pending_triage(apply=apply_pending_data, limit=limit)
    return {
        "schema": "DueCheckpointResolution@v2",
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
        "scheduled": scheduled,
        "pending_triage": triage,
        # Flat mirrors keep existing callers / cron log greps working.
        "applied": scheduled["applied"],
        "due": scheduled["due"],
        "resolved": scheduled["resolved"],
        "pending_data": scheduled["pending_data"],
        "not_price_resolvable": scheduled["not_price_resolvable"],
        "not_resolvable_reasons": scheduled["not_resolvable_reasons"],
        "samples": scheduled["samples"],
        "pending_total": triage["pending_total"],
        "pending_future": triage["future_dated"],
        "pending_obtainable": triage["obtainable"],
        "pending_stuck": triage["stuck_waiting_data"],
        "pending_never_resolvable": triage["never_resolvable"],
        "pending_applied": triage["applied"],
        "pending_resolved": triage["resolved"],
        "pending_expired": triage["expired"],
        "pending_apply_refused": triage["apply_refused"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Resolve due outcome checkpoints")
    ap.add_argument("--apply", action="store_true",
                    help="write SCHEDULED resolutions (default: dry run)")
    ap.add_argument(
        "--apply-pending-data",
        action="store_true",
        help=(
            f"resolve obtainable / expire never-resolvable PENDING_DATA "
            f"(requires {PENDING_APPLY_ENV}=1; append-only)"
        ),
    )
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    result = run(
        apply=args.apply,
        limit=args.limit,
        apply_pending_data=args.apply_pending_data,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        print("── SCHEDULED due ──")
        for key in ("due", "resolved", "pending_data", "not_price_resolvable", "applied"):
            print(f"{key:22} {result[key]}")
        for reason, n in sorted(result["not_resolvable_reasons"].items(), key=lambda kv: -kv[1]):
            print(f"  not resolvable: {n:3}x  {reason}")
        for s in result["samples"]:
            rec = str(s.get("recommendation") or "")
            if len(rec) > 24:
                rec = rec[:21] + "..."
            print(f"  {s['symbol'] or '?':6} {rec:24} "
                  f"{s['change_pct']:+.2f}%  -> {s['outcome_id']}")

        triage = result["pending_triage"]
        print("── PENDING_DATA triage ──")
        print(f"{'as_of':22} {triage['as_of']}")
        print(f"{'root':22} {triage['root']}")
        for key in (
            "pending_total", "future_dated", "obtainable",
            "stuck_waiting_data", "never_resolvable", "applied",
            "resolved", "expired",
        ):
            print(f"{key:22} {triage[key]}")
        if triage.get("apply_refused"):
            refused = triage["apply_refused"]
            print(f"  APPLY_REFUSED: {refused.get('detail')}")
        for reason, n in sorted(triage["reasons"].items(), key=lambda kv: -kv[1]):
            print(f"  pending reason: {n:3}x  {reason}")
        for s in triage["resolve_samples"]:
            print(f"  would-resolve {s.get('symbol') or '?':6} "
                  f"{s.get('change_pct'):+.2f}%  "
                  f"{s.get('decision_price_date')}→{s.get('horizon_price_date')}  "
                  f"cid={s.get('checkpoint_id')}")
        for s in triage["expire_samples"]:
            print(f"  would-expire  {s.get('symbol') or '?':6} "
                  f"{s.get('reason')}  cid={s.get('checkpoint_id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
