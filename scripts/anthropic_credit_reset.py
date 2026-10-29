#!/usr/bin/env python3
"""Operator recovery for promotional-credit refusals, with an append-only audit.

Dry run is the default. After confirming the promotional organization/key and
accounting health, an operator may append a reset with --apply and the exact
promotion-specific confirmation shown by the dry run. A reset never removes
settled spend, reservations, total-cap exhaustion, or the verified history of an
older promotion. A corrupt hash chain must be reconciled; it cannot be reset.

Example (use the same roots for both invocations)::

    python scripts/anthropic_credit_reset.py --scope billing_error
    python scripts/anthropic_credit_reset.py --scope billing_error --apply \
        --confirm 'RESET_ANTHROPIC_CREDIT operator-promo-20261025 billing_error'
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib.anthropic_credit import CreditBook, CreditDenied, RESET_SCOPES
from scripts.lib.anthropic_transport import load_policy


ROOT = Path(__file__).resolve().parents[1]


def confirmation(promotion_id: str, scope: str) -> str:
    return f"RESET_ANTHROPIC_CREDIT {promotion_id} {scope}"


def default_state_root() -> Path:
    supplied = os.environ.get("PROJECT_ROOT") or os.environ.get("TRADEAI_STATE_ROOT")
    if supplied:
        return Path(supplied)
    from scripts.lib.lane_registry import state_root
    return state_root()


def run(book: CreditBook, *, scope: str, apply: bool = False, confirm: str | None = None,
        note_code: str = "operator", now: datetime | None = None) -> dict[str, Any]:
    if scope not in RESET_SCOPES:
        raise CreditDenied("CREDIT_RESET_SCOPE_INVALID")
    expected = confirmation(book.promotion, scope)
    before = book.snapshot(now=now or datetime.now(timezone.utc))
    if apply and confirm != expected:
        raise CreditDenied("CREDIT_RESET_CONFIRMATION_REQUIRED")
    after = book.operator_reset(scope, now=now or datetime.now(timezone.utc), note_code=note_code) if apply else before
    return {"dry_run": not apply, "promotion_id": book.promotion, "scope": scope,
            "required_confirmation": expected, "before": before, "after": after,
            "preserves_spend_and_holds": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT, help="Code/configuration root")
    parser.add_argument("--state-root", type=Path, help="Journal root; defaults to governed runtime state")
    parser.add_argument("--scope", choices=sorted(RESET_SCOPES), required=True)
    parser.add_argument("--note-code", default="operator", help="Short non-secret audit code; never include credentials")
    parser.add_argument("--apply", action="store_true", help="Append the operator reset event")
    parser.add_argument("--confirm", help="Exact promotion/scope confirmation emitted by dry run")
    args = parser.parse_args(argv)
    try:
        book = CreditBook(args.state_root or default_state_root(), load_policy(args.project_root))
        result = run(book, scope=args.scope, apply=args.apply, confirm=args.confirm, note_code=args.note_code)
    except CreditDenied as exc:
        print(json.dumps({"error": exc.reason}), file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        # Stable output only: paths, provider bodies, and configuration values are
        # not echoed by the recovery command.
        print(json.dumps({"error": "CREDIT_CONFIGURATION_INVALID"}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
