"""Home v008 piece D — approval requests reach the operator as ONE batched Telegram nudge.

Spec (SPEC_HOME_V008_NEEDS_YOU_APPROVALS_20261103.md §4): "Telegram: ONE short message per new
request ('1 decision needs you: Merge #2518 · open Home'), batched and never repeated more than every
2 h. Quiet hours 22:00–07:00: only P0 pages; everything else waits on the dashboard."

This lane is the Telegram *edge* only. It never approves anything, never executes an action and never
writes to the request store: the store belongs to the backend (cc5), the buttons belong to the Home UI
(cc4), and a click is only ever an operator session against the API. Here we read the request events
those writers publish, select the ones that are due, and send one message through
``scripts/lib/telegram_batch.py`` — the same batching, 2 h floor and quiet window the incident digest
uses, so the operator sees one notification style, not two.

PRIMARY SOURCE — the published event stream (coordinated with the store owner, PR #2550):
``persistent-state/data/approvals/requests.jsonl``. "approved" is written BEFORE the action runs, so a
slow or failed merge is never re-asked as if still undecided; "updated" (a question, a moved fact)
leaves the request open. ``requester`` is a plain string there.

FALLBACK — the store's own files, ``<state-root>/needs_you/requests/<id>.json`` (``HomeApprovalRequest@v1``,
``state == "open"``, ``requester`` a mapping), used when the stream does not exist yet. Also tested:

    {"schema": "ApprovalRequestEvent@v1", "event": "created" | "updated" | "resolved" | "expired",
     "id": "apr_...", "type": "merge_pr", "title": "Merge #2518",
     "why": "the reviewed head must not move", "requester": "cc-deepseek-7",
     "created_at": "...Z", "expires_at": "...Z", "facts": {...,"head_sha": "..."}}

A plain request row (no ``event``) is accepted too and treated as created. Status words are read from
either ``event`` or ``status``. Anything resolved/declined/approved/expired, or past ``expires_at``,
is never nudged — the dashboard owns it; Telegram must not ask about a decision already taken.

Usage:
    python scripts/approvals_notify.py                 # dry run: prints what it would send
    python scripts/approvals_notify.py --apply         # sends at most ONE message
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from lib.telegram_batch import (  # noqa: E402
    DEFAULT_FLOOR_MINUTES, FOOTER_DEFAULT, PRIORITY_P1, PRIORITY_P2, NudgeState, batch_text, nudge_decision,
)

SCHEMA = "ApprovalsNotifyReceipt@v1"
PROJ = Path(__file__).resolve().parent.parent
DEFAULT_REQUESTS = PROJ / "persistent-state" / "data" / "approvals" / "requests.jsonl"
DEFAULT_STATE_ROOT = PROJ / "persistent-state"
DEFAULT_STATE_DIR = PROJ / "data" / "runtime" / "approvals_notify"
DEFAULT_CONFIG = PROJ / "config" / "approvals_notify.json"

UNREADABLE_KEY = "__unreadable__"
OPEN_EVENTS = {"created", "updated", "pending", "open", "requested"}
CLOSED_EVENTS = {"resolved", "declined", "approved", "expired", "cancelled", "canceled", "done"}
OPEN_STATUS = {"open", "pending", "requested", "awaiting_operator", "needs_you"}
CLOSED_STATUS = CLOSED_EVENTS


def _now_dt(value: str | None) -> datetime:
    if value:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _dt(value) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_requests(path: Path) -> dict[str, dict]:
    """Newest state per request id. Unreadable lines are skipped (a partial write must not stop the loud path)."""
    rows: dict[str, dict] = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        req_id = str(row.get("id") or row.get("request_id") or "").strip()
        if not req_id:
            continue
        kind = str(row.get("event") or row.get("status") or "").strip().lower()
        if kind in CLOSED_EVENTS or (not kind and row.get("closed_at")):
            rows[req_id] = {**rows.get(req_id, {}), **row, "id": req_id, "closed": True}
        else:
            # An update that does not say it closed leaves the decision open.
            merged = {**rows.get(req_id, {}), **row, "id": req_id}
            merged["closed"] = bool(rows.get(req_id, {}).get("closed")) and kind not in OPEN_EVENTS
            rows[req_id] = merged
    return rows


def open_requests(rows: dict[str, dict], now: datetime) -> list[dict]:
    """Requests still awaiting the operator at ``now`` — never an expired or already-decided one."""
    out = []
    for req in rows.values():
        if req.get("closed"):
            continue
        status = str(req.get("status") or "").strip().lower()
        if status in CLOSED_STATUS or status == "closed":
            continue
        if status and status not in OPEN_STATUS and str(req.get("event") or "").strip().lower() not in OPEN_EVENTS:
            # Unknown status: leave it to the dashboard rather than nudge about something unclassified.
            continue
        expires = _dt(req.get("expires_at"))
        if expires is not None and expires <= now:
            continue
        out.append(req)
    out.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("id"))))
    return out


def load_store_requests(state_root: Path, now: datetime) -> list[dict] | None:
    """Open, unexpired records from the backend store. None when the store is not there (use the fallback).

    A record we cannot parse is skipped AND counted by the caller: one corrupt file must not silence the
    nudge for every other open request, and it must not be invisible either.
    """
    d = Path(state_root) / "needs_you" / "requests"
    if not d.is_dir():
        return None
    rows = []
    for path in sorted(d.glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows.append({"_unreadable": path.name})
            continue
        if not isinstance(rec, dict) or str(rec.get("state") or "").strip().lower() != "open":
            continue
        expires = _dt(rec.get("expires_at"))
        if expires is not None and expires <= now:
            continue
        rec.setdefault("id", path.stem)
        rows.append(rec)
    return rows


def _requester(req: dict) -> str:
    who = req.get("requester")
    if isinstance(who, dict):
        return str(who.get("session") or who.get("claim") or who.get("actor") or "").strip()
    return str(who or "").strip()


def _label(req: dict) -> str:
    title = str(req.get("title") or "").strip()
    if title:
        return title
    kind = str(req.get("type") or "").strip()
    facts = req.get("facts") if isinstance(req.get("facts"), dict) else {}
    if kind == "merge_pr" and facts.get("pr"):
        return f"Merge #{facts['pr']}"
    if kind == "rerun_ci" and facts.get("run_id"):
        return f"Re-run CI run {facts['run_id']}"
    if kind == "grant":
        return f"Grant {facts.get('tier') or 'access'} for {facts.get('duration') or 'the requested window'}"
    if kind == "stop_job" and facts.get("pid"):
        return f"Stop stuck job pid {facts['pid']}"
    if kind == "install_schedule":
        return f"Install schedule {facts.get('lane') or ''}".strip()
    if kind == "restore_store":
        return "Restore a store from the reviewed packet"
    if kind == "policy_approval":
        return f"Record APPROVE for policy PR #{facts.get('pr')}" if facts.get("pr") else "Record a policy APPROVE"
    return f"{kind.replace('_', ' ') or 'Approval'} request {req.get('id')}"


def _item(req: dict) -> dict:
    why = str(req.get("why") or "").strip()
    who = _requester(req)
    detail = " · ".join(x for x in (why, f"asked by {who}" if who else "") if x)
    return {"title": _label(req), "detail": detail, "next": "Approve or decline on Home"}


def unreadable_item(unreadable: list[str]) -> dict:
    """A store record nothing could parse, said to the operator — silence is the failure mode to kill."""
    names = sorted(str(x) for x in unreadable)
    n = len(names)
    return {"title": f"{n} decision could not be read" if n == 1 else f"{n} decisions could not be read",
            "detail": "unreadable record(s): " + ", ".join(names[:3]) + ("…" if n > 3 else ""),
            "next": "Open Home — the card shows the error, not a green board"}


def compose(requests: list[dict], home_url: str = "", unreadable: list[str] | None = None) -> str:
    items = [_item(r) for r in requests]
    if unreadable:
        items.append(unreadable_item(unreadable))
    if len(requests) == 1:
        header = "1 decision needs you"
    elif requests:
        header = f"{len(requests)} decisions need you"
    else:
        header = unreadable_item(unreadable or [])["title"]
    footer = f"Open Home: {home_url}" if home_url else FOOTER_DEFAULT
    return batch_text(header=header, items=items, footer=footer)


def _config(path: Path) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def run(*, requests_path: Path = DEFAULT_REQUESTS, state_root: Path | None = None,
        state_dir: Path = DEFAULT_STATE_DIR, config_path: Path = DEFAULT_CONFIG, now: str | None = None,
        dry_run: bool = True, notify=None) -> dict:
    """One cycle: read requests, decide dues, send at most ONE message. Pure apart from the state file."""
    cfg = _config(config_path)
    home_url = str(cfg.get("home_url") or "").strip()
    floor = int(cfg.get("repeat_floor_minutes", DEFAULT_FLOOR_MINUTES))
    priority = str(cfg.get("priority") or PRIORITY_P2).upper()
    now_dt = _now_dt(now)

    root = Path(state_root or os.environ.get("TRADEAI_STATE_ROOT") or DEFAULT_STATE_ROOT)
    unreadable: list[str] = []
    if Path(requests_path).is_file():
        # The store publishes this stream (coordinated 2026-11-03, PR #2550): one line per transition,
        # "approved" written BEFORE the action runs so a slow/failed merge is never re-asked. It is the
        # contract, so it wins when present.
        source = "events"
        open_now = open_requests(load_requests(requests_path), now_dt)
    else:
        store_rows = load_store_requests(root, now_dt)
        if store_rows is not None:
            source = "store"
            unreadable = [str(r.get("_unreadable")) for r in store_rows if r.get("_unreadable")]
            open_now = [r for r in store_rows if not r.get("_unreadable")]
            open_now.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("id"))))
        else:
            source, open_now = "none", []
    state = NudgeState(Path(state_dir) / "nudge_state.json")
    keys = [str(r["id"]) for r in open_now]
    if unreadable:
        keys.append(UNREADABLE_KEY)
    decision = nudge_decision(keys=keys, state=state, now=now_dt, priority=priority, floor_minutes=floor)

    receipt = {
        "schema": SCHEMA, "at": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "dry_run": bool(dry_run),
        "source": source, "requests_path": str(requests_path), "state_root": str(root),
        "unreadable": unreadable, "open": len(open_now), "send": False,
        "reason": decision["reason"], "keys": [], "message": None, "priority": priority,
    }
    if not decision["send"]:
        return receipt

    due_ids = set(decision["keys"])
    due = [r for r in open_now if str(r["id"]) in due_ids]
    # The unreadable record reaches the operator in the SAME message, exactly once per floor: a corrupt
    # file that only ever appears in a receipt is silent to the person who has to act on it.
    shown_unreadable = sorted(unreadable) if UNREADABLE_KEY in due_ids else []
    text = compose(due, home_url, shown_unreadable)
    receipt.update({"keys": [str(r["id"]) for r in due] + [UNREADABLE_KEY] * bool(shown_unreadable),
                    "unreadable_reported": shown_unreadable, "message": text})
    if dry_run:
        receipt["reason"] = "would send (dry run)"
        return receipt

    if notify is None:  # pragma: no cover - exercised only against the real transport
        from telegram_alert import send_telegram  # type: ignore

        def notify(body: str, *, priority: str = PRIORITY_P2) -> bool:
            return bool(send_telegram(body, priority=priority))
    ok = bool(notify(text, priority=priority))
    receipt["sent"] = ok
    if ok:
        state.save(state.note(receipt["keys"], now_dt))
        receipt.update({"send": True, "reason": "sent"})
    else:
        # A failed send consumes nothing: the keys stay due, so the next cycle retries the same batch.
        receipt["reason"] = "send failed; keys stay due"
    return receipt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ONE batched Telegram nudge for approvals that need the operator")
    ap.add_argument("--requests", default=str(DEFAULT_REQUESTS))
    ap.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--state-root", default=None,
                    help="backend store root (default: $TRADEAI_STATE_ROOT or ./persistent-state)")
    ap.add_argument("--now", default=None, help="ISO timestamp; default is the real clock")
    ap.add_argument("--apply", action="store_true", help="send; without it the cycle is a dry run")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    receipt = run(requests_path=Path(args.requests), state_root=Path(args.state_root) if args.state_root else None,
                  state_dir=Path(args.state_dir),
                  config_path=Path(args.config), now=args.now, dry_run=not args.apply)
    if args.json:
        print(json.dumps(receipt, indent=1, sort_keys=True))
    else:
        print(f"{receipt['reason']}: {len(receipt['keys'])} request(s)")
        if receipt.get("message"):
            print(receipt["message"])
    return 0 if receipt.get("reason") != "send failed; keys stay due" else 1


if __name__ == "__main__":
    raise SystemExit(main())
