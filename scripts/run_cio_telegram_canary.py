#!/usr/bin/env python3
"""run_cio_telegram_canary.py — Phase 10 CIO Telegram canary (DRY default).

Default: ``--dry-run`` — prepare a SCHD-trim package via the real CIO
transport, measure general-bot isolation, write
``data/audit/cio_telegram_canary_receipt.json`` with sent=false. Never HTTP.

Live send requires ALL of:
  * ``--live``
  * ``AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1``  (must already be set; this
    script never sets it)
  * ``CIO_TELEGRAM_CANARY_ENABLE=1``
  * ``CIO_TELEGRAM_CANARY_APPROVAL=I_APPROVE_CIO_CANARY_SEND``
  * not under pytest / CIO_TELEGRAM_INTERDICT

If any live requirement is missing, the run stays dry.

Authority: READ_ONLY_ADVISORY. Never send Telegram from the default path.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_telegram_canary import (  # noqa: E402
    DEFAULT_RECEIPT_PATH,
    run_canary,
)


def _parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="CIO Telegram canary — dry-run default, never HTTP unless fully gated.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Prepare + measure only (default). Never HTTP.",
    )
    p.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Request a live send (still requires env + operator approval).",
    )
    p.add_argument(
        "--receipt-path",
        default="",
        help=f"Override receipt path (default: {DEFAULT_RECEIPT_PATH})",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    # --dry-run is default True. --live without an explicit dry-run request
    # still stays dry unless every live gate is already set in the environment.
    # Passing both: dry wins.
    want_live = bool(args.live) and "--dry-run" not in (argv or sys.argv[1:])
    dry_run = not want_live
    receipt_path = Path(args.receipt_path) if args.receipt_path else None
    result = run_canary(
        dry_run=dry_run,
        want_live=want_live,
        receipt_path=receipt_path,
    )
    # Never print tokens / secrets
    safe = {
        "ok": result.get("ok"),
        "dry_run": result.get("dry_run"),
        "receipt_path": result.get("receipt_path"),
        "receipt": {
            k: (result.get("receipt") or {}).get(k)
            for k in (
                "sent", "dry_run", "operator_approved", "cio_chat_confirmed",
                "general_sends", "release_sha", "duplicate", "proof",
                "would_send_path", "chat_target_type", "duplicate_key",
                "decision_id", "symbol", "http_calls", "live_gate_reason",
            )
        },
        "measurement": result.get("measurement"),
        "live_gate_reason": result.get("live_gate_reason"),
        "authority": result.get("authority"),
    }
    print(json.dumps(safe, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
