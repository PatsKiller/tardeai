#!/usr/bin/env python3
"""Immediate P1 failure paging for delivery / deploy failures (AGENTS.md §28.12 step 10).

Best-effort: Telegram via send_telegram when available; always appends a durable
receipt so silence is detectable. Never raises into the caller.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _receipts_dir() -> Path:
    root = Path(os.environ.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))
    return root / "data" / "runtime" / "delivery_failure_alerts"


def page_p1(*, kind: str, message: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send a P1 (dedupe off) and write a receipt. Returns the receipt body."""
    text = f"[P1] {kind}: {message}"
    delivered: bool | None = None
    err = ""
    try:
        from scripts.telegram_alert import send_telegram  # type: ignore

        delivered = bool(
            send_telegram(
                text,
                priority="P1",
                dedupe_minutes=0,
                producer=f"delivery_failure_alerts:{kind}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        delivered = None
        err = f"{type(exc).__name__}:{exc}"[:200]

    row = {
        "schema": "DeliveryFailureAlert@v1",
        "as_of": _utc(),
        "kind": kind,
        "message": message,
        "delivered": delivered,
        "error": err,
        "detail": detail or {},
    }
    out = _receipts_dir()
    try:
        out.mkdir(parents=True, exist_ok=True)
        (out / "latest.json").write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        stamp = _utc().replace(":", "").replace("-", "")
        (out / f"{stamp}_{kind}.json").write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass
    return row


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="manual_test")
    ap.add_argument("--message", default="delivery_failure_alerts dry probe")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        print(json.dumps({"would_page": True, "kind": args.kind, "message": args.message}))
        return 0
    row = page_p1(kind=args.kind, message=args.message)
    print(json.dumps(row, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
