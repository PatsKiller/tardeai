#!/usr/bin/env python3
"""cio_telegram_bot.py — Dedicated CIO Telegram long-poll worker.

Separate from Maria/general TELEGRAM_BOT_TOKEN.
Uses TELEGRAM_CIO_BOT_TOKEN + TELEGRAM_CIO_CHAT_IDS allowlist.

Usage:
  .venv/bin/python scripts/cio_telegram_bot.py --once
  .venv/bin/python scripts/cio_telegram_bot.py --loop
  .venv/bin/python scripts/cio_telegram_bot.py --once --json

Env:
  TELEGRAM_CIO_BOT_TOKEN
  TELEGRAM_CIO_CHAT_IDS (or TELEGRAM_CIO_ALLOWLIST)
  CIO_TELEGRAM_CONVERSE=0|1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.chdir(ROOT)

from scripts.lib.cio_telegram_converse import (  # noqa: E402
    DEFAULT_OFFSET,
    allowlist_chat_ids,
    cio_bot_token,
    converse_enabled,
    process_telegram_message,
)


def _get_offset(path: Path = DEFAULT_OFFSET) -> int:
    try:
        return int(path.read_text().strip())
    except Exception:
        return 0


def _save_offset(offset: int, path: Path = DEFAULT_OFFSET) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(offset))


def poll_updates(token: str, offset: int, timeout: int = 25) -> list[dict]:
    params = urlencode({
        "offset": offset + 1 if offset else 0,
        "timeout": timeout,
        "allowed_updates": json.dumps(["message"]),
    })
    url = f"https://api.telegram.org/bot{token}/getUpdates?{params}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout + 15) as resp:
        data = json.loads(resp.read())
    if not data.get("ok"):
        return []
    return data.get("result") or []


def process_once(*, timeout: int = 25, dry_run: bool = False) -> dict:
    out = {
        "processed": 0,
        "results": [],
        "errors": [],
        "enabled": converse_enabled(),
        "allowlist_n": len(allowlist_chat_ids()),
        "token_set": bool(cio_bot_token()),
    }
    token = cio_bot_token()
    if not token:
        out["errors"].append("TELEGRAM_CIO_BOT_TOKEN unset")
        return out
    if not allowlist_chat_ids():
        out["errors"].append("TELEGRAM_CIO_CHAT_IDS/ALLOWLIST empty — fail closed")
        return out

    offset = _get_offset()
    try:
        updates = poll_updates(token, offset, timeout=timeout)
    except Exception as exc:
        out["errors"].append(f"getUpdates:{type(exc).__name__}:{exc}")
        return out

    for upd in updates:
        uid = upd.get("update_id")
        if uid is not None:
            _save_offset(int(uid))
        msg = upd.get("message")
        if not msg:
            continue
        try:
            res = process_telegram_message(msg, dry_run=dry_run)
            out["results"].append(res)
            out["processed"] += 1
        except Exception as exc:
            out["errors"].append(f"msg:{msg.get('message_id')}:{type(exc).__name__}:{exc}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="CIO Telegram bot (dedicated)")
    ap.add_argument("--once", action="store_true", help="Single poll then exit")
    ap.add_argument("--loop", action="store_true", help="Long-poll forever")
    ap.add_argument("--timeout", type=int, default=25)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.loop:
        from scripts.lib.cio_telegram_converse import send_cio_message
        from scripts.lib.cio_operator_desk_loop import try_fulfill_pending_replies
        _fulfill_every = 0
        while True:
            res = process_once(timeout=args.timeout, dry_run=args.dry_run)
            # Periodically fulfill deferred operator asks when Trade-AI data lands
            _fulfill_every += 1
            if not args.dry_run and _fulfill_every % 3 == 0:
                try:
                    def _send(cid, body, reply_to=None):
                        return send_cio_message(str(cid), str(body), reply_to=reply_to)
                    fr = try_fulfill_pending_replies(_send, limit=8)
                    res["pending_fulfilled"] = fr.get("fulfilled")
                except Exception as exc:
                    res.setdefault("errors", []).append(
                        f"pending_fulfill:{type(exc).__name__}:{exc}"
                    )
            if args.json:
                print(json.dumps(res, default=str))
            else:
                print(
                    f"[cio-tg] processed={res['processed']} "
                    f"errors={len(res['errors'])} enabled={res['enabled']}"
                    + (
                        f" fulfilled={res.get('pending_fulfilled')}"
                        if res.get("pending_fulfilled")
                        else ""
                    )
                )
                for e in res["errors"][:3]:
                    print(f"  ERR {e}")
            time.sleep(0.5)
    else:
        res = process_once(timeout=args.timeout if not args.once else min(args.timeout, 5), dry_run=args.dry_run)
        if args.json:
            print(json.dumps(res, indent=2, default=str))
        else:
            print(
                f"[cio-tg] processed={res['processed']} "
                f"errors={len(res['errors'])} token_set={res['token_set']} "
                f"allowlist_n={res['allowlist_n']}"
            )
            for r in res.get("results") or []:
                print(f"  {r.get('kind') or r.get('reason')} plan={r.get('plan_id')}")
            for e in res.get("errors") or []:
                print(f"  ERR {e}")
        return 0 if not res.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
