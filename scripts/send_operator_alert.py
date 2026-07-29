#!/usr/bin/env python3
"""Read an operator alert body from stdin and publish it. Shell-safe entry point.

Callers used to inline the body into a Python heredoc:

    python3 - <<PY
    send_telegram(\"\"\"${MSG}\"\"\")
    PY

which is a code-injection vector, not merely a quoting bug: a body containing a
triple quote, a backslash, a backtick or a ${...} expansion terminates the literal
and the remainder executes as Python. Report text is attacker-influenced in practice
(symbols, broker strings, headlines), so this had to stop being interpolation.

The body now arrives on stdin as bytes and is never parsed by a shell or by Python
source. Safe for quotes, triple quotes, dollar signs, backticks, backslashes,
newlines and non-ASCII.

    printf '%s' "$MSG" | /abs/.venv/bin/python /abs/scripts/send_operator_alert.py
    /abs/.venv/bin/python /abs/scripts/send_operator_alert.py --file /tmp/body.txt

Exit codes: 0 accepted (delivered, queued, or recorded), 1 not accepted, 2 empty body.
Prints nothing on success so cron logs stay quiet.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Publish an operator alert read from stdin.")
    ap.add_argument("--file", help="read the body from this path instead of stdin")
    ap.add_argument("--bypass-router", action="store_true",
                    help="legacy P0 flag; recorded as metadata")
    ap.add_argument("--source-producer", default="shell_operator_alert")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.file:
        try:
            body = Path(args.file).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"[send_operator_alert] cannot read {args.file}: {e}", file=sys.stderr)
            return 2
    else:
        body = sys.stdin.buffer.read().decode("utf-8", errors="replace")

    if not body.strip():
        if not args.quiet:
            print("[send_operator_alert] empty body — nothing published", file=sys.stderr)
        return 2

    try:
        from telegram_alert import publish_operator_message
        result = publish_operator_message(
            body, bypass_router=args.bypass_router, source_producer=args.source_producer)
        accepted = bool(result.get("accepted"))
        if not accepted and not args.quiet:
            print(f"[send_operator_alert] not accepted: {result.get('reason')}", file=sys.stderr)
        return 0 if accepted else 1
    except Exception as e:
        print(f"[send_operator_alert] publish failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
