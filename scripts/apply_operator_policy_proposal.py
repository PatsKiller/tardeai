#!/usr/bin/env python3
"""Show, then (only with --apply) ratify fields from an operator policy proposal.

    python3 scripts/apply_operator_policy_proposal.py                       # dry run, all fields
    python3 scripts/apply_operator_policy_proposal.py --only concentration_hierarchy
    python3 scripts/apply_operator_policy_proposal.py --apply --only fixed_income_range_pct

Ratification goes through cio_operator_investment_policy.ratify_policy_field,
the same governed path the Command Center ratify button uses. Run it only on
the operator's explicit instruction; the dry run changes nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_operator_investment_policy import (  # noqa: E402
    FIELD_SPECS,
    _validate_value,
    build_operator_investment_policy,
    ratify_policy_field,
)

DEFAULT_PROPOSAL = ROOT / "config" / "policy_proposals" / "operator_policy_proposal_20261003.json"
STORE_RELPATH = Path("data") / "cio" / "operator_profile.jsonl"


def default_store() -> Path:
    """The store the served Command Center reads: production state, not this tree.

    2026-10-04: the old default (<this tree>/data/cio) is only production inside a
    release, where data/cio is a symlink. From a worktree or the dev tree it was a
    dead copy, and a ratification there would never have reached the capital plan.
    """
    try:
        from scripts.lib.canonical_store_registry import production_state_root
        return Path(production_state_root()) / STORE_RELPATH
    except Exception:  # noqa: BLE001
        return Path.home() / "trade-ai-releases" / "persistent-state" / STORE_RELPATH


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--proposal", default=str(DEFAULT_PROPOSAL))
    ap.add_argument("--store", default=None, help="operator profile store (default: production state)")
    ap.add_argument("--only", nargs="*", default=None, help="field names to include (default: all)")
    ap.add_argument("--apply", action="store_true", help="ratify (default: dry run)")
    args = ap.parse_args(argv)
    args.store = str(args.store or default_store())

    proposal = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
    current = build_operator_investment_policy(store_path=args.store, repo_root=ROOT)["fields"]
    rows = [r for r in proposal.get("fields") or [] if not args.only or r["field"] in args.only]
    out = []
    for row in rows:
        name = row["field"]
        if name not in FIELD_SPECS:
            out.append({"field": name, "error": "unknown field"})
            continue
        value = _validate_value(FIELD_SPECS[name]["kind"], row["value"])
        entry = {"field": name, "status": row.get("status"), "current": current[name]["value"],
                 "new": value, "required": FIELD_SPECS[name]["required"]}
        if args.apply:
            receipt = ratify_policy_field(name, value, store_path=args.store, actor="operator",
                                          source=f"operator_policy_proposal:{Path(args.proposal).name}")
            entry["ratified"] = {"event_id": receipt["event_id"], "confirmed_at": receipt["confirmed_at"]}
        out.append(entry)
    print(json.dumps({"applied": bool(args.apply), "store": args.store, "fields": out}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
