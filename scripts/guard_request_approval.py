#!/usr/bin/env python3
"""guard_request_approval.py — ask the operator, by Telegram, to open a guard scope.

Agent-callable. Grants nothing. It mints a PENDING request, sends the operator a
message describing exactly what is being asked for, and exits.

    python scripts/guard_request_approval.py git-push --for 30m --uses 8 \
        --reason "merge PR #871, CI green on af3349528"

The one-time code goes to Telegram and **is never printed here and never written
to disk**. That is deliberate: this process is the one an agent runs, so the code
must not be in its output. The operator replies in Telegram:

    /approve <CODE>      opens the scope for the requested window
    /deny <CODE>         refuses and burns the code

The reply is handled by the live callback poller, which already owns the single
`getUpdates` consumer — a second consumer would collide on HTTP 409, which is why
this does not poll for its own answer.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import guard_remote_approval as gra  # noqa: E402


def parse_duration(text: str) -> int:
    t = str(text).strip().lower()
    if t.endswith("m"):
        return int(float(t[:-1]) * 60)
    if t.endswith("h"):
        return int(float(t[:-1]) * 3600)
    if t.endswith("s"):
        return int(t[:-1])
    return int(t)


def _tailnet_base() -> str:
    """Public base for operator links — Tailscale HTTPS when available."""
    try:
        from notification_url_builder import get_public_base_url
    except ImportError:                                   # pragma: no cover
        try:
            from scripts.notification_url_builder import get_public_base_url  # type: ignore
        except ImportError:
            return ""
    try:
        return get_public_base_url().rstrip("/")
    except Exception:                                     # noqa: BLE001
        return ""


def _keyboard(request_id: str) -> dict:
    """Approve / Deny as CALLBACK buttons, plus a read-only tailnet link.

    The two authority buttons carry `callback_data`, not a URL. That is a
    deliberate security choice and the reason the tailnet button opens the
    dashboard rather than granting anything:

      * A callback is delivered by Telegram with the sender's own user id, from
        a chat on the allowlist. It originates at Telegram's servers, so holding
        the bot token does not let anything fabricate one. The lock moves from
        "knows a secret" to "is the operator", which is the property actually
        wanted — and it is why a tap needs no code.
      * A URL that grants authority is the opposite. Any holder of the link
        approves: a preview crawler, a prefetching browser, a mis-tap, anyone the
        message is forwarded to. Worse, this agent can read the HMAC key and
        mint its own signed token, so a signed approve-URL would let the agent
        walk through its own front door. The one guarantee this whole mechanism
        exists to provide would be gone.

    So the tailnet link is `/v3/` — somewhere to LOOK, never somewhere to ACT.
    """
    row = [
        {"text": "\u2705 Approve", "callback_data": f"gapprove:{request_id}"},
        {"text": "\U0001f6d1 Deny", "callback_data": f"gdeny:{request_id}"},
    ]
    keyboard = [row]
    base = _tailnet_base()
    if base.startswith("https://"):
        # Only a TLS tailnet URL is offered. A bare-LAN or plaintext link in a
        # chat message is a different kind of mistake.
        keyboard.append([{"text": "\U0001f517 Open dashboard", "url": f"{base}/v3/"}])
    return {"inline_keyboard": keyboard}


def _send(message: str, reply_markup: dict | None = None) -> tuple[bool, str]:
    """Send through the house chokepoint, INTERRUPT class. Never a digest.

    An approval prompt is not a notification. It is a question with a fifteen
    minute fuse, and a digested question is an expired one. The first version
    called `send_telegram(message)` with default routing and the alert router
    classified it P1_DIGEST:

        [telegram] Suppressed (P1_DIGEST): 🔐 *Approval requested* ...
        request_id=43c4ff0b6b4bc005 ... telegram=sent

    The operator never saw the code, and this process reported `telegram=sent`.
    That second part is the worse half. `send_telegram` documents that it
    "returns True when the event was ACCEPTED", and accepted explicitly includes
    archived-for-digest — so a truthy return was read as delivered. A confident
    line that is not true, in the tool whose whole purpose is asking a human a
    question.

    `bypass_router=True` is the same thing research_lane_health.py:251 does for
    its own alarms, and for the same reason: some messages are not summarisable.
    """
    try:
        from telegram_alert import send_telegram
    except ImportError:
        try:
            from scripts.telegram_alert import send_telegram  # type: ignore
        except ImportError as exc:
            return False, f"telegram_alert unavailable: {exc}"
    try:
        ok = send_telegram(message, bypass_router=True, reply_markup=reply_markup)
    except Exception as exc:                              # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    if not ok:
        return False, "send_telegram returned falsey — not accepted"
    # Truthy means ACCEPTED, which is a weaker claim than delivered. Say the
    # weaker thing rather than the flattering one.
    return True, "accepted for interrupt delivery (router bypassed)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scope", help="guard scope, e.g. git-push")
    ap.add_argument("--for", dest="window", default="30m",
                    help="grant window if approved (default 30m)")
    ap.add_argument("--uses", type=int, default=10, help="uses if approved (default 10)")
    ap.add_argument("--reason", required=True, help="what the grant is for — the operator reads this")
    ap.add_argument("--ttl", default="4h",
                    help="how long the operator has to answer (default 4h; max 12h). "
                         "15m was the old default and it expired unanswered overnight "
                         "on work the operator had explicitly asked for.")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be asked; mints nothing, sends nothing")
    args = ap.parse_args()

    seconds = parse_duration(args.window)
    ttl = parse_duration(args.ttl)

    if args.dry_run:
        print(f"WOULD REQUEST  scope={args.scope}  window={seconds}s  uses={args.uses}")
        print(f"               reason={args.reason}")
        print(f"               operator has {ttl}s to answer")
        print(f"               forbidden remotely: {sorted(gra.REMOTE_FORBIDDEN_SCOPES)}")
        print(f"               remote maximum window: {gra.MAX_GRANT_SECONDS}s")
        return 0

    try:
        req = gra.mint_request(args.scope, seconds=seconds, uses=args.uses,
                               reason=args.reason, ttl=ttl)
    except (ValueError, RuntimeError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    host = os.uname().nodename
    body = (
        f"\U0001f510 *Approval requested*\n\n"
        f"*Scope:*  `{req['scope']}`\n"
        f"*Window:* {seconds // 60} min\n"
        f"*Uses:*   {args.uses}\n"
        f"*Reason:* {args.reason}\n"
        f"*Host:*   {host}\n\n"
        f"Tap a button below, or reply:\n"
        f"`/approve {req['code']}`\n"
        f"`/deny {req['code']}`\n\n"
        f"_Code expires in {ttl // 60} min and works once._"
    )
    ok, detail = _send(body, reply_markup=_keyboard(req["request_id"]))

    # The code is NOT printed. An agent running this must not be able to read it
    # out of its own stdout — that is the property that keeps the approval the
    # operator's to give.
    print(f"request_id={req['request_id']} scope={req['scope']} "
          f"window={seconds}s uses={args.uses} telegram={detail if ok else 'FAILED'}")
    if not ok:
        print(f"TELEGRAM SEND FAILED: {detail}", file=sys.stderr)
        print("The request is minted but the operator was not notified. "
              "Nothing is approved. Tell the operator out of band.", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
