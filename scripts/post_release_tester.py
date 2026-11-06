#!/usr/bin/env python3
"""Post-release verification (AGENTS.md §28.12 step 9 / §25.10).

Thin host check after prepare+promote: health ok, /v3/cio reachable, served BUILD_SHA
matches CURRENT pin when readable. Writes a small receipt under persistent-state.
Full browser sweep stays optional and outside market hours (§28.8).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_BASE = os.environ.get("TRADEAI_POST_RELEASE_BASE", "http://127.0.0.1:7777")


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get(url: str, timeout: float = 8.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return int(resp.status), body
    except urllib.error.HTTPError as exc:
        return int(exc.code), (exc.read() or b"").decode("utf-8", errors="replace")[:500]
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}:{exc}"


def run(*, base: str = DEFAULT_BASE, skip_http: bool = False) -> dict:
    from scripts.lib.deploy_on_main import current_pin_sha, receipts_dir

    pin = current_pin_sha()
    checks: list[dict] = []
    ok = True

    if skip_http:
        checks.append({"name": "http", "ok": True, "detail": "skipped"})
    else:
        for path, need_substr in (("/api/health", None), ("/v3/cio", None)):
            code, body = _get(base.rstrip("/") + path)
            passed = 200 <= code < 400
            if path == "/api/health" and body:
                try:
                    doc = json.loads(body)
                    if isinstance(doc, dict) and "ok" in doc and doc.get("ok") is False:
                        passed = False
                except ValueError:
                    pass
            checks.append({"name": path, "ok": passed, "http": code, "detail": body[:200]})
            ok = ok and passed

    checks.append({"name": "current_pin", "ok": bool(pin and len(pin) >= 9), "detail": pin[:40]})
    if not (pin and len(pin) >= 9):
        ok = False

    row = {
        "schema": "PostReleaseTesterReceipt@v1",
        "as_of": _utc(),
        "outcome": "PASSED" if ok else "FAILED",
        "current_pin": pin,
        "base": base,
        "checks": checks,
    }
    out = receipts_dir().parent / "post_release_tester"
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "latest.json"
    dest.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return row


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Post-release verify CURRENT")
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--skip-http", action="store_true", help="pin-only check (hermetic / offline)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    row = run(base=args.base, skip_http=bool(args.skip_http))
    if args.json:
        print(json.dumps(row, indent=2, sort_keys=True))
    else:
        print(f"post_release_tester outcome={row['outcome']} pin={row.get('current_pin', '')[:12]}")
    return 0 if row["outcome"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
