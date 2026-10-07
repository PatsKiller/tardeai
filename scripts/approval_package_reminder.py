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
import fcntl
import json
import os
import sys
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts" / "lib"))
sys.path.insert(0, str(PROJ / "scripts"))

NO_CONSUMER_REASON = (
    "hourly lane body; NOTE/DECIDED rows are package-ledger events, not a run receipt. "
    "data/governance/approval_packages.jsonl stays unchanged when the plan is empty, so its mtime "
    "is not proof the hour ran. A crontab command line is not proof a person received the reminder. "
    "The run receipt is data/runtime/approval_package_reminder_last.json."
)


def receipt_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("TRADEAI_APPROVAL_REMINDER_RECEIPT")
    if env:
        return Path(env)
    return PROJ / "data" / "runtime" / "approval_package_reminder_last.json"


def same_runtime_target(left: Path, right: Path) -> bool:
    """True when two paths are the same file after resolving symlinks."""
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def next_hourly_due(now: _dt.datetime) -> str:
    """The live crontab fires at minute 5 of every hour, America/New_York."""
    local = now.astimezone(ZoneInfo("America/New_York"))
    candidate = local.replace(minute=5, second=0, microsecond=0)
    if local >= candidate:
        candidate += _dt.timedelta(hours=1)
    return candidate.isoformat()


def liveness(receipt: dict, *, now: _dt.datetime, max_age_s: float) -> str:
    raw = receipt.get("ended_at") or receipt.get("as_of")
    try:
        ended = _dt.datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return "STALE"
    if ended.tzinfo is None:
        return "STALE"
    age = (now - ended).total_seconds()
    if age < 0 or age > max_age_s:
        return "STALE"
    return "FRESH"


class UncertainSend(RuntimeError):
    """The adapter may have sent. The receipt must not call that delivery."""


def _served_sha() -> str | None:
    raw = os.environ.get("TRADEAI_SERVED_SHA", "").strip().lower()
    if len(raw) == 40 and all(ch in "0123456789abcdef" for ch in raw):
        return raw
    return None


def build_run_receipt(
    actions: list[dict],
    *,
    now: _dt.datetime,
    send_requested: bool,
    recorded: bool,
    sent: bool,
    started_at: _dt.datetime | None = None,
    run_id: str | None = None,
    error_class: str | None = None,
    send_attempt_count: int | None = None,
    refused_count: int = 0,
    delivery_status: str | None = None,
) -> dict:
    """Counts only. Reminder text, tokens, and package ids stay out of this file.

    ``sent`` means the sender adapter returned. It is not a recipient receipt.
    An empty plan is NO_ACTION. This builder never emits SUCCESS.
    """
    started = started_at or now
    action_count = len(actions)
    attempts = action_count if send_requested and action_count else 0
    if send_attempt_count is not None:
        attempts = send_attempt_count
    if action_count == 0:
        planner_status = "NO_ACTION"
        outcome = "NO_ACTION"
        delivery = "NO_ACTION"
        attempts = 0
        error_class = None
        if delivery_status not in (None, "NO_ACTION"):
            raise ValueError("empty plan is not delivery")
    elif recorded:
        planner_status = "ACTIONS_PLANNED"
        outcome = "PACKAGE_WRITTEN"
        delivery = "DELIVERY_UNMEASURED"
    else:
        planner_status = "ACTIONS_PLANNED"
        outcome = "RUN_OBSERVED"
        delivery = "DELIVERY_UNMEASURED"
    if action_count and error_class == "sender_timeout":
        delivery = "UNCERTAIN"
    elif action_count and error_class == "sender_refusal":
        delivery = "DELIVERY_UNMEASURED"
    if action_count and delivery_status:
        if delivery_status in {"SUCCESS", "DELIVERED", "DELIVERY_OBSERVED"}:
            raise ValueError("planner does not observe delivery")
        delivery = delivery_status
    if planner_status == "SUCCESS" or outcome == "SUCCESS" or delivery == "SUCCESS":
        raise ValueError("refusing SUCCESS")
    return {
        "schema": "ApprovalReminderReceipt@v1",
        "run_id": run_id or uuid.uuid4().hex,
        "served_sha": _served_sha(),
        "started_at": started.isoformat(),
        "ended_at": now.isoformat(),
        "as_of": now.isoformat(),
        "planner_status": planner_status,
        "outcome": outcome,
        "run_observed": True,
        "actions": action_count,
        "action_count": action_count,
        "eligible_count": action_count,
        "suppressed_count": 0,
        "refused_count": refused_count,
        "kinds": sorted({str(a.get("kind")) for a in actions}),
        "send_requested": bool(send_requested),
        "send_attempt_count": attempts,
        "delivery_receipt_count": 0,
        "delivery_status": delivery,
        "error_class": error_class,
        "next_due": next_hourly_due(now),
        "recorded": bool(recorded),
        "sent": bool(sent),
        "adapter_return_is_delivery": False,
        "consumer_receipt": None,
        "package_ledger_is_run_receipt": False,
    }


def write_run_receipt(path: Path, receipt: dict, *, before_replace=None) -> None:
    if receipt.get("planner_status") == "SUCCESS" or receipt.get("outcome") == "SUCCESS":
        raise ValueError("refusing SUCCESS")
    if receipt.get("delivery_status") in {"SUCCESS", "DELIVERED"}:
        raise ValueError("refusing delivery claim")
    if receipt.get("outcome") == "NO_ACTION" and receipt.get("delivery_status") != "NO_ACTION":
        raise ValueError("empty plan is not delivery")
    if receipt.get("delivery_status") == "DELIVERY_OBSERVED" and int(receipt.get("delivery_receipt_count") or 0) <= 0:
        raise ValueError("delivery observed without a receipt")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    lock_path = path.with_suffix(path.suffix + ".lock")
    try:
        tmp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if before_replace is not None:
            before_replace()
        with lock_path.open("a", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                os.replace(tmp, path)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    finally:
        if tmp.exists():
            tmp.unlink()


def send_reminder_text(text: str) -> None:
    from telegram_alert import send_telegram  # type: ignore

    send_telegram(text, bypass_router=True)

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


def main(argv: list[str] | None = None, *, sender=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger")
    ap.add_argument("--receipt", help="run receipt path; default data/runtime/approval_package_reminder_last.json under this tree")
    ap.add_argument("--send", action="store_true", help="send reminders via telegram_alert (router bypassed); default dry run")
    ap.add_argument("--record", action="store_true", help="record NOTE/EXPIRED rows even without sending")
    a = ap.parse_args(argv)
    led = Ledger(Path(a.ledger) if a.ledger else ledger_path())
    started = _dt.datetime.now(_dt.timezone.utc)
    now = started
    run_id = uuid.uuid4().hex
    actions = plan(led, now=now)
    print(json.dumps({"schema": "ApprovalReminderRun@v1", "as_of": now.isoformat(), "actions": len(actions),
                      "kinds": sorted({x["kind"] for x in actions})}, indent=1))
    for x in actions:
        print(f"  {x['kind']:<12} {x['package_id']}: {x['text'][:120]}")
    sent = False
    error_class = None
    attempts = 0
    refused = 0
    deliver = sender or send_reminder_text
    if a.send and actions:
        try:
            for x in actions:
                attempts += 1
                deliver(x["text"])
            sent = True
        except (TimeoutError, UncertainSend) as exc:
            error_class = "sender_timeout"
            refused = len(actions)
            led.append({"event": "SEND_FAILED", "error": f"{type(exc).__name__}: uncertain",
                        "actions": len(actions), "at": now.isoformat()})
            print(f"send uncertain: {type(exc).__name__}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            error_class = "sender_refusal"
            refused = len(actions)
            led.append({"event": "SEND_FAILED", "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                        "actions": len(actions), "at": now.isoformat()})
            print(f"send failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    recorded = False
    if (a.send or a.record) and actions:
        record(led, actions, sent=sent)
        recorded = True
        print(f"recorded {len(actions)} action(s); sent={sent}")
    elif not actions:
        print("nothing due")
    else:
        print("dry run: nothing recorded or sent (add --record and/or --send)")
    ended = _dt.datetime.now(_dt.timezone.utc)
    receipt = build_run_receipt(
        actions,
        now=ended,
        started_at=started,
        run_id=run_id,
        send_requested=a.send,
        recorded=recorded,
        sent=sent,
        error_class=error_class,
        send_attempt_count=attempts,
        refused_count=refused,
    )
    try:
        write_run_receipt(receipt_path(a.receipt), receipt)
    except (OSError, ValueError) as exc:
        print(f"receipt write failed: {type(exc).__name__}", file=sys.stderr)
        if not sent:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
