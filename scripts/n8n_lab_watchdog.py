#!/usr/bin/env python3
"""Outside-n8n liveness check for the lab bench.

GETs the lab health URL and writes a local receipt. A non-200, a closed port,
a DNS failure, or a body that is not the healthz status exits non-zero.
HTTP 200 from /healthz does not prove workers, the queue, the database, a
webhook, a source producer, or a consumer. This process does not send mail or
Telegram, and it does not start, stop, or restart the container.

A check running on this host cannot observe this host being entirely down.
That limit is stated on the receipt and is not treated as a passing probe.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

NO_CONSUMER_REASON = (
    "Proposal only. The host timer is not installed and this script is not scheduled. "
    "A local receipt is not a production alert."
)

DEFAULT_URL = "http://127.0.0.1:5678/healthz"
RECEIPT_SCHEMA = "N8nLabWatchdogReceipt@v1"
HOST_FAILURE_LIMITATION = "a probe on this host cannot observe this host's total outage"
SECRET_VALUE_RE = re.compile(r"(postgres(?:ql)?://|(?<![A-Za-z])sk-|bearer\s)", re.I)


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.username or parts.password or "@" in parts.netloc:
        host = parts.hostname or "redacted"
        port = f":{parts.port}" if parts.port else ""
        return urlunsplit((parts.scheme, f"{host}{port}", parts.path, "", ""))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _body_ok(raw: bytes) -> tuple[bool, str | None]:
    if not raw:
        return True, None
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        return False, "body_undecodable"
    if SECRET_VALUE_RE.search(text):
        return False, "body_redacted"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return (text.strip().lower() == "ok"), (None if text.strip().lower() == "ok" else "unexpected_body")
    status = str(parsed.get("status") or "").lower() if isinstance(parsed, dict) else ""
    if status in {"ok", "healthy"}:
        return True, None
    return False, "unexpected_body"


def _error_class(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, urllib.error.HTTPError):
        return "http_error"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            return "timeout"
        if isinstance(reason, socket.gaierror):
            return "dns_failure"
        text = str(reason).lower()
        if "refused" in text or getattr(reason, "errno", None) in {111, 61}:
            return "connection_refused"
        return type(reason).__name__ if reason is not None else "URLError"
    return type(exc).__name__


def check(url: str, *, timeout_s: float = 3.0, now: datetime | None = None) -> dict:
    instant = now or datetime.now(timezone.utc)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "checked_at": instant.isoformat(),
        "url": redact_url(url),
        "http_status": None,
        "ok": False,
        "error": None,
        "sends": False,
        "auth_sent": False,
        "proves_workers": False,
        "proves_queue": False,
        "proves_database": False,
        "proves_webhook": False,
        "proves_producer": False,
        "proves_consumer": False,
        "healthz_is_process_liveness_only": True,
        "host_failure_limitation": HOST_FAILURE_LIMITATION,
        "failure_state": "NO_SEND",
        "body_checked": False,
    }
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            status = int(response.status)
            raw = response.read(512)
    except urllib.error.HTTPError as exc:
        receipt["http_status"] = int(exc.code)
        receipt["error"] = "http_error"
        return receipt
    except Exception as exc:  # noqa: BLE001 — class only, no body and no secret
        receipt["error"] = _error_class(exc)
        return receipt
    body_ok, body_error = _body_ok(raw)
    receipt["http_status"] = status
    receipt["body_checked"] = True
    receipt["ok"] = status == 200 and body_ok
    if status != 200:
        receipt["error"] = "unexpected_status"
    elif not body_ok:
        receipt["error"] = body_error or "unexpected_body"
    else:
        receipt["failure_state"] = None
    return receipt


def receipt_is_stale(receipt: dict, *, now: datetime, max_age_s: float) -> bool:
    raw = receipt.get("checked_at")
    try:
        checked = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return True
    if checked.tzinfo is None:
        return True
    age = (now - checked).total_seconds()
    return age < 0 or age > max_age_s


def write_receipt(path: Path, receipt: dict, *, before_replace=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if before_replace is not None:
            before_replace()
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check lab n8n from outside the container")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args(argv)
    receipt = check(args.url, timeout_s=args.timeout)
    try:
        write_receipt(Path(args.receipt), receipt)
    except OSError:
        print(json.dumps({"ok": False, "error": "receipt_write_failed", "sends": False}))
        return 1
    print(json.dumps({"ok": receipt["ok"], "http_status": receipt["http_status"], "error": receipt["error"], "sends": False}))
    return 0 if receipt["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
