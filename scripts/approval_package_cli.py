#!/usr/bin/env python3
"""approval_package_cli.py — create, submit, decide and show ApprovalPackage@v1 records (13).

    create   --from FILE.json --campaign C --wave W [--ledger PATH]        → package_id (DRAFT)
    render   PKG_ID                                                         → the message text (no send)
    submit   PKG_ID --message-ids 54472,54473 --chat-id ID                  → SUBMITTED (records the ids; does NOT send)
    decide   "APPROVE PKG all" --by "operator:<id>:typed"                   → applies the typed reply
    show     PKG_ID                                                         → folded package JSON
    verify                                                                  → hash-chain check

Sending is deliberately NOT here: the message goes through telegram_alert.send_telegram_with_id
(bypass_router=True) from the caller that owns the send, after a dry run (AGENTS.md §6).
Dry-run by default for ``create``/``decide`` unless ``--apply``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts" / "lib"))
sys.path.insert(0, str(PROJ / "scripts"))

from approval_package import Ledger, apply_reply, ledger_path, new_package, parse_reply, render_message, chunks  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["create", "render", "submit", "decide", "show", "verify"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--from", dest="src")
    ap.add_argument("--campaign"); ap.add_argument("--wave"); ap.add_argument("--summary", default="")
    ap.add_argument("--pr", type=int); ap.add_argument("--sha")
    ap.add_argument("--message-ids"); ap.add_argument("--chat-id")
    ap.add_argument("--by", default="operator:unknown:typed")
    ap.add_argument("--ledger"); ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    led = Ledger(Path(a.ledger) if a.ledger else ledger_path())
    if a.cmd == "create":
        spec = json.loads(Path(a.src).read_text(encoding="utf-8"))
        pkg = new_package(a.campaign or spec.get("campaign"), a.wave or spec.get("wave"), a.summary or spec.get("summary", ""),
                          spec["items"], binds={"pr": a.pr or spec.get("pr"), "sha": a.sha or spec.get("sha")},
                          reviews=spec.get("reviews"), package_id=spec.get("package_id"))
        if not a.apply:
            print(json.dumps(pkg, indent=1)); print("dry run: not written (add --apply)", file=sys.stderr); return 0
        led.append({"event": "PACKAGE_CREATED", "package_id": pkg["package_id"], "package": pkg})
        print(pkg["package_id"]); return 0
    if a.cmd == "render":
        pkg = led.package(a.arg)
        if not pkg:
            print("unknown package", file=sys.stderr); return 1
        text = render_message(pkg); print(text); print(f"\n[{len(text)} chars, {len(chunks(text))} chunk(s)]", file=sys.stderr); return 0
    if a.cmd == "submit":
        if not a.apply:
            print("dry run: would mark SUBMITTED", file=sys.stderr); return 0
        led.append({"event": "SUBMITTED", "package_id": a.arg, "telegram": {"message_ids": (a.message_ids or "").split(","), "chat_id": a.chat_id}})
        print("SUBMITTED"); return 0
    if a.cmd == "decide":
        rep = parse_reply(a.arg or "")
        if not rep:
            print("unparseable reply", file=sys.stderr); return 1
        if not a.apply:
            print(json.dumps(rep)); print("dry run: not applied (add --apply)", file=sys.stderr); return 0
        parts = a.by.split(":")
        pkg = apply_reply(led, rep, decided_by={"who": parts[0], "from_id": parts[1] if len(parts) > 1 else None,
                                                 "via": parts[2] if len(parts) > 2 else "typed", "text": a.arg})
        print(json.dumps({"package_id": pkg["package_id"], "state": pkg["state"],
                          "items": {it["item_no"]: it["state"] for it in pkg["items"]}}, indent=1)); return 0
    if a.cmd == "show":
        pkg = led.package(a.arg); print(json.dumps(pkg, indent=1) if pkg else "unknown package"); return 0 if pkg else 1
    if a.cmd == "verify":
        ok, n, err = led.verify_chain(); print(json.dumps({"ok": ok, "rows": n, "error": err})); return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
