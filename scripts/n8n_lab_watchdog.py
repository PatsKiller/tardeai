#!/usr/bin/env python3
"""Outside-n8n liveness check for the lab bench.

GETs the lab health URL and writes a local receipt. A non-200 or a closed
port exits non-zero. This process does not send mail or Telegram, and it
does not start, stop, or restart the container.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:5678/healthz"
RECEIPT_SCHEMA = "N8nLabWatchdogReceipt@v1"


def check(url: str, *, timeout_s: float = 3.0, now: datetime | None = None) -> dict:
    instant = now or datetime.now(timezone.utc)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "checked_at": instant.isoformat(),
        "url": url,
        "http_status": None,
        "ok": False,
        "error": None,
        "sends": False,
    }
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as response:
            status = int(response.status)
            response.read(256)
    except urllib.error.HTTPError as exc:
        receipt["http_status"] = int(exc.code)
        receipt["error"] = "http_error"
        return receipt
    except Exception as exc:  # noqa: BLE001 — the receipt records the class, not a secret
        receipt["error"] = type(exc).__name__
        return receipt
    receipt["http_status"] = status
    receipt["ok"] = status == 200
    if status != 200:
        receipt["error"] = "unexpected_status"
    return receipt


def write_receipt(path: Path, receipt: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check lab n8n from outside the container")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args(argv)
    receipt = check(args.url, timeout_s=args.timeout)
    write_receipt(Path(args.receipt), receipt)
    print(json.dumps({"ok": receipt["ok"], "http_status": receipt["http_status"], "error": receipt["error"]}))
    return 0 if receipt["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
