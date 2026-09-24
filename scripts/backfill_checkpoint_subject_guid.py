#!/usr/bin/env python3
"""Backfill subject identity onto UNRESOLVED outcome checkpoints (append-only).

Agentic-memory tranche 1 (2026-09-24), R5. 171 of 174 RESOLVED checkpoints and
~12,000 SCHEDULED ones carried ``entity_type: UNRESOLVED`` with a subject_id
like ``UNRESOLVED:position:MCD:RESEARCH`` because the binder only echoed a GUID
already present on the decision dict. New checkpoints are bound at mint through
``cio_institutional_learning.identity_safe_subject`` (identity-registry lookup).
This script binds the rows written before that.

The checkpoint store is APPEND-ONLY EVIDENCE: nothing is rewritten. For each
checkpoint whose latest row is UNRESOLVED and whose symbol the identity
registry knows, one AMENDMENT row is appended — the latest row's fields plus
``subject_guid`` / ``entity_type: SECURITY`` / ``subject_id`` / ``subject_key``
and ``amendment_of`` (sha of the row it amends), ``amended_at``,
``amendment_reason``. Readers that project "latest row per checkpoint_id"
(``outcome_resolution.latest_checkpoints``) see the bound identity; the
original row stays in the file.

Nothing is invented: a symbol the registry does not know stays UNRESOLVED and
is counted under ``unresolvable``.

SAFE BY DEFAULT
  * dry-run is the default (read-only; reports what WOULD be appended).
  * ``--apply`` appends. Idempotent: a checkpoint whose latest row already
    carries a subject_guid is skipped, so a second run appends 0.
  * ``--limit N`` caps the appends per run.
  * Running ``--apply`` against production is an operator action (§17).

Usage:
  python scripts/backfill_checkpoint_subject_guid.py                 # dry run
  python scripts/backfill_checkpoint_subject_guid.py --json
  python scripts/backfill_checkpoint_subject_guid.py --apply --limit 2000
  TRADEAI_STATE_ROOT=/tmp/x python scripts/backfill_checkpoint_subject_guid.py --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.cio_institutional_learning import (  # noqa: E402
    AUTHORITY,
    CHECKPOINT_PATH,
    MBI,
    _append,
    _jsonl,
    identity_safe_subject,
)

SCHEMA = "CheckpointSubjectBackfill@v1"
AMENDMENT_REASON = "subject_guid_backfill_20260924"
# One-shot operator-run backfill (dry-run default, --apply is a §17 action on
# production evidence). Its report is read by the operator, not by a scheduled
# consumer, by design: after the historical rows are bound, new checkpoints are
# bound at mint (r17_checkpoint_binding.canonical_checkpoint_subject).
NO_CONSUMER_REASON = (
    "one-shot operator backfill of historical UNRESOLVED checkpoints; new rows "
    "bind at mint, so no scheduled consumer exists by design"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_sha(row: dict[str, Any]) -> str:
    raw = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _symbol_of(cp: dict[str, Any]) -> str | None:
    for src in (cp.get("context_receipt") or {}, cp.get("original_decision_state") or {}, cp):
        sym = str((src or {}).get("symbol") or "").strip().upper()
        if sym:
            return sym
    sid = str(cp.get("subject_id") or "")
    # UNRESOLVED:position:MCD:RESEARCH -> MCD (lineage shape, best effort, still a lookup)
    parts = sid.split(":")
    if len(parts) >= 3 and parts[0] == "UNRESOLVED" and parts[1] == "position":
        return parts[2].strip().upper() or None
    return None


def latest_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        cid = r.get("checkpoint_id")
        if cid:
            out[str(cid)] = r
    return out


def plan_backfill(rows: list[dict[str, Any]], *, registry: Any = None,
                  subject_key_lookup=None, limit: int | None = None,
                  now: str | None = None) -> dict[str, Any]:
    """Pure planner: which checkpoints get an amendment row, and the rows."""
    now = now or _now_iso()
    latest = latest_rows(rows)
    amendments: list[dict[str, Any]] = []
    already_bound = 0
    unresolvable: dict[str, int] = {}
    no_symbol = 0
    cache: dict[str, str | None] = {}
    for cid, cp in latest.items():
        if cp.get("subject_guid"):
            already_bound += 1
            continue
        sym = _symbol_of(cp)
        if not sym:
            no_symbol += 1
            continue
        if sym not in cache:
            cache[sym] = identity_safe_subject({"symbol": sym}, registry=registry)
        guid = cache[sym]
        if not guid:
            unresolvable[sym] = unresolvable.get(sym, 0) + 1
            continue
        if limit is not None and len(amendments) >= limit:
            break
        skey = None
        if subject_key_lookup is not None:
            try:
                skey = subject_key_lookup(sym)
            except Exception:  # noqa: BLE001
                skey = None
        amended = dict(cp)
        amended.update({
            "subject_guid": guid,
            "entity_type": "SECURITY",
            "subject_id": guid,
            "subject_key": skey,
            "ticker_guid_is_not_security": False,
            "amendment_of": _row_sha(cp),
            "amended_at": now,
            "amendment_reason": AMENDMENT_REASON,
            "authority": AUTHORITY,
            "memory_behavior_influence": MBI,
        })
        amendments.append(amended)
    return {
        "schema": SCHEMA,
        "as_of": now,
        "checkpoints": len(latest),
        "already_bound": already_bound,
        "no_symbol": no_symbol,
        "unresolvable_symbols": len(unresolvable),
        "unresolvable_rows": sum(unresolvable.values()),
        "unresolvable_top": sorted(unresolvable.items(), key=lambda kv: -kv[1])[:15],
        "would_append": len(amendments),
        "amendments": amendments,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def run(root: Path | str, *, apply: bool, limit: int | None, registry: Any = None) -> dict[str, Any]:
    path = Path(root) / CHECKPOINT_PATH
    rows = _jsonl(path)
    try:
        from scripts.lib.cio_instrument_record import subject_key_for_symbol

        def _skey(sym: str) -> str | None:
            return subject_key_for_symbol(sym, root=root)
    except Exception:  # noqa: BLE001
        _skey = None  # type: ignore[assignment]
    plan = plan_backfill(rows, registry=registry, subject_key_lookup=_skey, limit=limit)
    appended = 0
    if apply:
        for row in plan["amendments"]:
            _append(path, row)
            appended += 1
    plan["applied"] = apply
    plan["appended"] = appended
    plan["store"] = str(path)
    # The amendments themselves are large; the report keeps a sample.
    plan["amendments_sample"] = plan["amendments"][:3]
    del plan["amendments"]
    return plan


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="append amendment rows (default: dry run)")
    ap.add_argument("--limit", type=int, default=None, help="max amendments per run")
    ap.add_argument("--root", default=None, help="state root (default: canonical production_state_root)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.root:
        root = Path(args.root)
    else:
        from scripts.lib.canonical_store_registry import production_state_root
        root = production_state_root()
    out = run(root, apply=args.apply, limit=args.limit)
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        mode = "APPLIED" if args.apply else "DRY-RUN"
        print(f"[{mode}] checkpoints={out['checkpoints']} already_bound={out['already_bound']} "
              f"would_append={out['would_append']} appended={out['appended']} "
              f"unresolvable_rows={out['unresolvable_rows']} ({out['unresolvable_symbols']} symbols) "
              f"no_symbol={out['no_symbol']} store={out['store']}")
        for sym, n in out["unresolvable_top"]:
            print(f"    unresolvable {sym}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
