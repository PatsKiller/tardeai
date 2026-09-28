#!/usr/bin/env python3
"""approval_package_reminder.py — reminders at +4 h / +12 h and expiry for open approval packages (13 §6).

Lane approval-package-reminder (hourly). Reads the ledger, and for every package in SUBMITTED or
PARTIAL: records (once each) a REMINDER_4H / REMINDER_12H note with the reminder text, and at
expires_at marks the undecided items EXPIRED (package → EXPIRED when nothing decidable remains).
Sending goes through telegram_alert.send_telegram(bypass_router=True) — the chokepoint — and only
with --send; the default is a dry run that prints what it would send. Never re-mints guard requests.

Approval: pkg-20260927-cogx-w1-d9e1 item 4. Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts" / "lib"))
sys.path.insert(0, str(PROJ / "scripts"))

NO_CONSUMER_REASON = (
    "hourly lane body; its outputs are ledger NOTE/DECIDED rows read by approval_package_cli show and the "
    "Command Center governance panel (Wave 2); lane declared NEVER_SCHEDULED until the pkg cron grant"
)

from approval_package import Ledger, REMINDERS_HOURS, ledger_path  # noqa: E402


def _parse(ts):
    try:
        t = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def plan(ledger: Ledger, *, now: _dt.datetime) -> list[dict]:
    """Pure: what this run would record/send. Each action: {package_id, kind, text|items}."""
    actions: list[dict] = []
    pkg_ids = []
    for row in ledger.rows():
        pid = row.get("package_id")
        if row.get("event") == "PACKAGE_CREATED" and pid not in pkg_ids:
            pkg_ids.append(pid)
    for pid in pkg_ids:
        pkg = ledger.package(pid)
        if not pkg or pkg["state"] not in ("SUBMITTED", "PARTIAL"):
            continue
        notes = {n.get("note") for n in pkg.get("notes", [])}
        submitted = _parse(pkg.get("submitted_at") or pkg.get("created_at"))
        expires = _parse(pkg.get("expires_at"))
        undecided = [it for it in pkg["items"] if it["state"] in ("PENDING", "DEFERRED")]
        if expires and now >= expires and undecided:
            actions.append({"package_id": pid, "kind": "EXPIRE", "items": [it["item_no"] for it in undecided],
                            "text": f"⏳ {pid.replace('_', '-')}: {len(undecided)} item(s) undecided at expiry — marked EXPIRED. A re-request will carry only these."})
            continue
        if submitted and undecided:
            age_h = (now - submitted).total_seconds() / 3600
            for h in REMINDERS_HOURS:
                key = f"REMINDER_{h}H"
                if age_h >= h and key not in notes:
                    left = f"{max(0, int((expires - now).total_seconds() // 3600))}h" if expires else "?"
                    actions.append({"package_id": pid, "kind": key, "items": [it["item_no"] for it in undecided],
                                    "text": f"⏳ {pid.replace('_', '-')}: {len(undecided)} item(s) undecided ({', '.join(str(it['item_no']) for it in undecided[:12])}), expires in {left}. Reply APPROVE {pid} all | 1,2 · DENY · DEFER."})
                    break  # one reminder per run
    return actions


def record(ledger: Ledger, actions: list[dict], *, sent: bool) -> None:
    for a in actions:
        if a["kind"] == "EXPIRE":
            for n in a["items"]:
                ledger.append({"event": "DECIDED", "package_id": a["package_id"], "item_no": n, "state": "EXPIRED",
                               "decided_by": {"who": "approval-package-reminder", "via": "expiry"}, "reason": "answer window elapsed"})
            pkg = ledger.package(a["package_id"])
            if pkg and not any(it["state"] in ("PENDING", "DEFERRED") for it in pkg["items"]):
                ledger.append({"event": "STATE", "package_id": a["package_id"], "state": pkg["state"] if pkg["state"] in ("APPROVED", "DENIED") else "EXPIRED"})
        else:
            ledger.append({"event": "NOTE", "package_id": a["package_id"], "note": a["kind"], "sent": sent, "text": a["text"]})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger")
    ap.add_argument("--send", action="store_true", help="send reminders via telegram_alert (router bypassed); default dry run")
    ap.add_argument("--record", action="store_true", help="record NOTE/EXPIRED rows even without sending")
    a = ap.parse_args()
    led = Ledger(Path(a.ledger) if a.ledger else ledger_path())
    now = _dt.datetime.now(_dt.timezone.utc)
    actions = plan(led, now=now)
    print(json.dumps({"schema": "ApprovalReminderRun@v1", "as_of": now.isoformat(), "actions": len(actions),
                      "kinds": sorted({x["kind"] for x in actions})}, indent=1))
    for x in actions:
        print(f"  {x['kind']:<12} {x['package_id']}: {x['text'][:120]}")
    sent = False
    if a.send and actions:
        try:
            from telegram_alert import send_telegram  # type: ignore
            for x in actions:
                send_telegram(x["text"], bypass_router=True)
            sent = True
        except Exception as exc:  # noqa: BLE001
            # C3 (no swallowed alarms): a failed reminder send is recorded on the durable ledger,
            # not only on stderr — the NOTE rows below carry sent=False, this row carries WHY.
            led.append({"event": "SEND_FAILED", "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                        "actions": len(actions), "at": now.isoformat()})
            print(f"send failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    if (a.send or a.record) and actions:
        record(led, actions, sent=sent)
        print(f"recorded {len(actions)} action(s); sent={sent}")
    elif not actions:
        print("nothing due")
    else:
        print("dry run: nothing recorded or sent (add --record and/or --send)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
