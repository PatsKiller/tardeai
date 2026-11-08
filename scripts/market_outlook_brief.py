#!/usr/bin/env python3
"""market-outlook-weekly: the Sunday/Monday brief of the Market Outlook desk (FABLE-OUTLOOK-METHODOLOGY-LQ-946, WU-3).

Reads one ``MarketOutlookRecord@v1`` (the engine's record, never a model call) and renders it three ways:

* email    - the full report as HTML (§4.3's eleven sections) plus a plain-text alternative;
* Telegram - the same report compacted to plain text, with the Monday-plan brief folded in so the operator
             receives ONE message where two used to arrive;
* Fi text  - one advisory sentence of at most ``max_chars`` (class ``market_outlook``; D1 set 300), sent through
             ``scripts/lib/critical_texts.send_critical_text``. This file never addresses a phone or a gateway.

It also writes the §4.6 ``cio_decisions`` row for the record (idempotent on ``decision_id``) so the CIO carries the stance.

Dedupe: one ``notification_log`` row per ``record_id:channel``. A channel already ``sent`` is skipped and its receipt is
left untouched; a channel that failed is retried, because a failed attempt is not a delivery.

Advisory only. Nothing here sizes, orders, stops, weights or writes to a broker (MBI_BEHAVIOR = 0). Default mode is a
dry-run: it prints the three renderings, sends nothing and writes no durable state. ``--deliver`` delivers.

Usage:
  python3 scripts/market_outlook_brief.py --record-file tests/fixtures/market_weekly_outlook_record_sample.json
  python3 scripts/market_outlook_brief.py --deliver --channels email,telegram,text
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (PROJECT_ROOT, PROJECT_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

LANE_ID = "market-outlook-weekly"
RECEIPT_REL = f"data/runtime/{LANE_ID}_last.json"
SCHEMA = "MarketOutlookBriefRun@v1"
TEXT_CLASS = "market_outlook"
SCRIPT_REL = "scripts/market_outlook_brief.py"


# --------------------------------------------------------------------------- state root
def _state_root(override: Optional[str] = None) -> Path:
    if override:
        return Path(override)
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env)
    from lib.persistent_state_root import good_persistent_root  # noqa: PLC0415 — call time

    return good_persistent_root()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- inputs
def _load_record(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    """The record and the source that supplied it. Every absence is named, never guessed."""
    from lib.market_outlook_brief import (  # noqa: PLC0415
        BriefError, load_record_file, normalize_record, validate_record)

    if args.record_file:
        record = load_record_file(Path(args.record_file))
        return record, f"file:{Path(args.record_file).name}"

    if not args.record and not args.latest:
        raise BriefError("no record named: pass --record <id>, --latest, or --record-file <path>")

    from db_adapter import _execute  # noqa: PLC0415 — the lane's only DB read

    probe = _execute("SELECT to_regclass('public.market_outlook_records') AS present", fetch="one")
    if probe is None:
        raise BriefError("record store unavailable: the database is not reachable")
    if not probe.get("present"):
        raise BriefError("record store missing: market_outlook_records does not exist yet "
                         "(the engine writer WU-2 has not landed); use --record-file")
    if args.latest:
        row = _execute("SELECT record_id, record FROM market_outlook_records ORDER BY as_of DESC LIMIT 1", fetch="one")
    else:
        row = _execute("SELECT record_id, record FROM market_outlook_records WHERE record_id = %s",
                       (args.record,), fetch="one")
    if row is None:
        raise BriefError(f"no record {args.record or '(latest)'} in market_outlook_records")
    record = row.get("record")
    if isinstance(record, str):
        record = json.loads(record)
    record = normalize_record(record)
    errors = validate_record(record)
    if errors:
        raise BriefError("record refused: " + "; ".join(errors))
    return record, f"db:{row.get('record_id')}"


def _monday_plan(now: datetime, state_root: Path) -> tuple[str, str]:
    """The folded Monday-plan brief: (text, status). Status is named so a missing section is visible, not silent."""
    try:
        from monday_plan_brief import build  # noqa: PLC0415 — import cost paid only when folding

        text = build(now=now, data_root=PROJECT_ROOT, state_root=state_root)
    except Exception as exc:  # noqa: BLE001 — the outlook brief stands without it; the run reports why it is absent
        return "", f"unavailable: {type(exc).__name__}: {str(exc)[:160]}"
    if not str(text).strip():
        return "", "unavailable: the Monday-plan brief rendered empty"
    return str(text), "folded"


def _context(args: argparse.Namespace, record: dict[str, Any], state_root: Path) -> tuple[Any, dict[str, Any]]:
    from lib.market_outlook_brief import BriefContext  # noqa: PLC0415

    raw: dict[str, Any] = {}
    if args.context:
        path = Path(args.context)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"context file unreadable: {path.name} ({type(exc).__name__})") from exc
    status: dict[str, Any] = {"source": f"file:{Path(args.context).name}" if args.context else "none"}

    want_plan = args.monday_plan if args.monday_plan is not None else str(record.get("mode")) in ("sunday", "monday")
    if want_plan and not raw.get("monday_plan"):
        text, plan_status = _monday_plan(datetime.now(timezone.utc), state_root)
        raw["monday_plan"] = text
        status["monday_plan"] = plan_status
    elif want_plan:
        status["monday_plan"] = "supplied by the context file"
    else:
        status["monday_plan"] = "switched off"
    return BriefContext.from_mapping(raw), status


# --------------------------------------------------------------------------- senders
def _email_target() -> tuple[str, str]:
    """The operator's email, read from the private contact file. Absence is refused, never defaulted."""
    try:
        from lib.critical_delivery import email_target, load_operator_contact  # noqa: PLC0415

        return email_target(load_operator_contact()), ""
    except Exception as exc:  # noqa: BLE001 — a refusal that names itself
        return "", f"{type(exc).__name__}: {str(exc)[:160]}"


def _send_email(record: dict[str, Any], *, policy: dict[str, Any], max_chars: int, context: Any) -> dict[str, Any]:
    from email_notifier import send_email_detailed  # noqa: PLC0415
    from lib.market_outlook_brief import render_email_text, render_html, subject  # noqa: PLC0415

    target, target_error = _email_target()
    if not target:
        return {"ok": False, "status": "failed", "error": f"no operator email target: {target_error}"}
    result = send_email_detailed(subject(record, policy), render_email_text(record, policy=policy, context=context),
                                 to=target, html=render_html(record, policy=policy, context=context))
    return {"ok": bool(result.get("ok")), "status": "sent" if result.get("ok") else "failed",
            "provider_id": result.get("provider_id"), "error": result.get("error"),
            "detail": {"sent_at": _now_iso(), "summary": f"{record['record_id']} {record['band']}"}}


def _send_telegram(record: dict[str, Any], *, policy: dict[str, Any], max_chars: int, context: Any) -> dict[str, Any]:
    from lib.comms.channel_adapters import send_via_gateway  # noqa: PLC0415
    from lib.market_outlook_brief import render_telegram  # noqa: PLC0415

    text = render_telegram(record, policy=policy, context=context)
    result = send_via_gateway(
        "telegram", body=text, subject="MARKET OUTLOOK", producer="market_outlook_brief",
        subject_key=f"market_outlook:{record['record_id']}", event_type="market_outlook_brief",
        message_class="operator_alert", retention_class="operational_30d", severity="info", deliver=True,
    )
    error = result.get("error")
    blocked = str(error or "").startswith("delivery_blocked")
    coordinates = result.get("provider_coordinates") or {}
    return {"ok": bool(result.get("delivered")),
            "status": "sent" if result.get("delivered") else ("blocked" if blocked else "failed"),
            "provider_id": result.get("provider_message_id"), "error": error,
            "detail": {"sent_at": _now_iso() if result.get("delivered") else None,
                       "summary": f"{record['record_id']} {record['band']}",
                       "chars": len(text), "chunks_held": len(coordinates.get("held") or []),
                       "gateway_event_id": result.get("event_id"),
                       "gateway_mode": result.get("gateway_mode")}}


def _send_text(record: dict[str, Any], *, policy: dict[str, Any], max_chars: int, context: Any) -> dict[str, Any]:
    from lib.critical_texts import send_critical_text  # noqa: PLC0415
    from lib.market_outlook_brief import render_text  # noqa: PLC0415

    body = render_text(record, policy=policy, max_chars=max_chars, context=context)
    result = send_critical_text({"alert_class": TEXT_CLASS, "event_id": record["record_id"], "body": body})
    return {"ok": bool(result.get("sent")), "status": "sent" if result.get("sent") else "failed",
            "provider_id": None, "error": result.get("reason"),
            "detail": {"sent_at": _now_iso() if result.get("sent") else None,
                       "summary": f"{record['record_id']} text {len(body)} chars",
                       "body": body, "gateways": result.get("gateways")}}


def _senders() -> dict[str, Any]:
    return {"email": _send_email, "telegram": _send_telegram, "text": _send_text}


# --------------------------------------------------------------------------- notification_log
def _read_status(key: str) -> dict[str, Any]:
    """``{ok, status}``. ``ok`` is False only when the store itself is unreachable — ``count(*)`` always returns a row."""
    from db_adapter import _execute  # noqa: PLC0415

    row = _execute("SELECT count(*) AS n, min(status) AS status FROM notification_log WHERE dedupe_key = %s",
                   (key,), fetch="one")
    if row is None:
        return {"ok": False, "status": None, "error": "notification_log is not reachable"}
    if int(row.get("n") or 0) == 0:
        return {"ok": True, "status": None}
    return {"ok": True, "status": str(row.get("status") or "")}


def _write_log(entry: dict[str, Any]) -> None:
    from db_adapter import save_notification_log_entry  # noqa: PLC0415

    save_notification_log_entry(entry)


# --------------------------------------------------------------------------- CIO
def _write_cio_row(record: dict[str, Any], policy: dict[str, Any]) -> str:
    """The §4.6 CIO row: ``inserted``, ``exists`` (this record already had one), or ``unavailable``."""
    from db_adapter import _execute  # noqa: PLC0415
    from lib.market_outlook_brief import cio_decision_row  # noqa: PLC0415

    row = cio_decision_row(record, policy)
    inserted = _execute(
        """INSERT INTO cio_decisions
             (decision_id, symbol, strategy_type, group_id, action, action_class, priority, confidence_raw,
              confidence_calibrated, decision_safety, human_review_required, rationale, status,
              supporting_signals, metadata, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb, now())
           ON CONFLICT (decision_id) DO NOTHING
           RETURNING decision_id""",
        (row["decision_id"], row["symbol"], row["strategy_type"], row["group_id"], row["action"],
         row["action_class"], row["priority"], row["confidence_raw"], row["confidence_calibrated"],
         row["decision_safety"], row["human_review_required"], row["rationale"], row["status"],
         json.dumps(row["supporting_signals"]), json.dumps(row["metadata"])),
        fetch="one")
    if inserted:
        return "inserted"
    probe = _execute("SELECT count(*) AS n FROM cio_decisions WHERE decision_id = %s",
                     (row["decision_id"],), fetch="one")
    if probe is None:
        return "unavailable"
    return "exists" if int(probe.get("n") or 0) else "unavailable"


# --------------------------------------------------------------------------- lane entry
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deliver", "--send", dest="send", action="store_true",
                    help="deliver (default is a dry-run: prints the three renderings, sends nothing, writes no state)")
    ap.add_argument("--dry-run", action="store_true", help="explicit dry run (same as the default)")
    ap.add_argument("--record", help="record id from market_outlook_records (the engine's store)")
    ap.add_argument("--latest", action="store_true", help="the most recent record in market_outlook_records")
    ap.add_argument("--record-file", help="a MarketOutlookRecord@v1 JSON file (synthetic fixtures, pre-engine)")
    ap.add_argument("--channels", default="email,telegram,text", help="comma list of email,telegram,text")
    ap.add_argument("--context", help="optional JSON with monday_plan / track_record / headlines / last_delivery")
    ap.add_argument("--monday-plan", dest="monday_plan", action="store_true", default=None,
                    help="fold the Monday-plan brief in (default: on for sunday and monday records)")
    ap.add_argument("--no-monday-plan", dest="monday_plan", action="store_false",
                    help="do not fold the Monday-plan brief in")
    ap.add_argument("--render-to", help="write the rendered email/telegram/text to this directory")
    ap.add_argument("--state-root", help="state root override (tests)")
    args = ap.parse_args(argv)
    send = args.send and not args.dry_run

    started = _now_iso()
    mode = "live" if send else "dry_run"
    from lib import lane_output  # noqa: PLC0415
    from lib.market_outlook_brief import (BriefError, deliver_channels, load_policy, parse_channels,  # noqa: PLC0415
                                          plan_channels, render_email_text, render_html, render_telegram,
                                          render_text, subject)

    state_root = _state_root(args.state_root)
    receipt_path = state_root / RECEIPT_REL

    def receipt(*, ok: bool, exit_code: int, produced: int, attempted: int, skipped: Optional[dict[str, int]],
                empty_reason: Optional[str], summary: dict[str, Any], error: Optional[str] = None) -> None:
        """The executor grades a live run only from the LaneRunReceipt@v2. A dry run writes nothing."""
        if not send:
            return
        from lib.lane_last_receipt import write_lane_receipt  # noqa: PLC0415

        write_lane_receipt(LANE_ID, ok=ok, exit_code=exit_code, started_at=started, script=SCRIPT_REL,
                           summary=summary, error=error, path=receipt_path, produced_count=produced,
                           attempted_count=attempted, skipped_reasons=skipped or {}, empty_reason=empty_reason)

    def fail(reason: str, *, exit_code: int = 1, summary: Optional[dict[str, Any]] = None) -> int:
        print(f"market-outlook-weekly: {reason}", file=sys.stderr)
        lane_output.emit(LANE_ID, mode, lane_output.output_block(
            produced=0, attempted=1, skipped={"refused": 1}, empty_reason=reason[:120], unit="briefs"), started_at=started)
        receipt(ok=False, exit_code=exit_code, produced=0, attempted=1, skipped={"refused": 1},
                empty_reason=reason[:120], summary=summary or {}, error=reason)
        return exit_code

    try:
        policy = load_policy()
        channels = parse_channels(args.channels)
        record, source = _load_record(args)
    except (BriefError, ValueError) as exc:
        return fail(f"record refused: {exc}")

    try:
        context, context_status = _context(args, record, state_root)
    except ValueError as exc:
        return fail(str(exc), summary={"source": source})

    # The text class's own allowlist decides the cap and whether the channel may speak at all.
    from lib.critical_texts import MAX_TEXT_CHARS, class_enabled, class_max_chars, load_policy as load_text_policy  # noqa: PLC0415

    text_policy = load_text_policy()
    text_max_chars = class_max_chars(text_policy, TEXT_CLASS) or MAX_TEXT_CHARS
    text_enabled = class_enabled(text_policy, TEXT_CLASS)

    try:
        rendered = {
            "subject": subject(record, policy),
            "html": render_html(record, policy=policy, context=context),
            "email_text": render_email_text(record, policy=policy, context=context),
            "telegram": render_telegram(record, policy=policy, context=context),
            "text": render_text(record, policy=policy, max_chars=text_max_chars, context=context),
        }
    except BriefError as exc:
        return fail(f"render refused: {exc}", summary={"source": source, "record_id": record.get("record_id")})

    # The delivery plan is decided before anything is sent, from the receipt store.
    existing: dict[str, str] = {}
    store_ok = True
    store_error = ""
    for channel in channels:
        status = _read_status(_dedupe(record, channel))
        if not status["ok"]:
            store_ok = False
            store_error = str(status.get("error"))
            continue
        if status.get("status"):
            existing[channel] = str(status["status"])
    plans = plan_channels(record, policy=policy, channels=channels, existing=existing, text_class_enabled=text_enabled)

    if args.render_to:
        out = Path(args.render_to)
        out.mkdir(parents=True, exist_ok=True)
        (out / "email.html").write_text(rendered["html"], encoding="utf-8")
        (out / "email.txt").write_text(f"SUBJECT: {rendered['subject']}\n\n{rendered['email_text']}\n", encoding="utf-8")
        (out / "telegram.txt").write_text(rendered["telegram"] + "\n", encoding="utf-8")
        (out / "text.txt").write_text(rendered["text"] + "\n", encoding="utf-8")

    print(f"record {record['record_id']} ({source}) - {record['band']} S {record['score']}")
    print(f"monday plan: {context_status.get('monday_plan')}")
    for plan in plans:
        print(f"  {plan.channel:9s} {plan.action:5s} {plan.reason}")
    print(f"  text cap {text_max_chars} chars; the sentence is {len(rendered['text'])} chars")
    print("\n==== HTML (first 40 lines) ====")
    print("\n".join(rendered["html"].split("\n")[:40]))
    print("\n==== TELEGRAM ====")
    print(rendered["telegram"])
    print("\n==== TEXT (%d chars) ====" % len(rendered["text"]))
    print(rendered["text"])

    if not send:
        sys.stdout.flush()  # the renderings above are the proof; keep them ahead of the machine line
        lane_output.emit(LANE_ID, mode, lane_output.output_block(
            produced=1, attempted=0, empty_reason=None, unit="briefs"), started_at=started)
        return 0

    if not store_ok:
        return fail(f"receipt store unavailable ({store_error}); nothing was sent because dedupe cannot be trusted",
                   summary={"source": source, "record_id": record["record_id"]})

    outcome = deliver_channels(
        record, policy=policy, plans=plans, senders=_senders(), read_status=lambda key: (_read_status(key) or {}).get("status"),
        write_log=_write_log, text_max_chars=text_max_chars, context=context)
    cio = _write_cio_row(record, policy)

    # The receipt must exist for every channel claimed as sent: a claimed send with no row is unverified.
    unverified = [r["channel"] for r in outcome["sent"]
                  if not (_read_status(_dedupe(record, r["channel"])) or {}).get("status") == "sent"]
    for channel in unverified:
        for result in outcome["results"]:
            if result["channel"] == channel:
                result["status"] = "sent_unverified"
                result["reason"] = "notification_log has no sent row for this channel"
    for result in outcome["results"]:
        print(f"  delivered {result['channel']}: {result['status']}"
              + (f" ({result['reason']})" if result.get("reason") else "")
              + (f" provider {result['provider_id']}" if result.get("provider_id") else ""))
    print(f"  cio_decisions: {cio}")

    produced = len([r for r in outcome["results"] if r["status"] == "sent"])
    attempted = len([r for r in outcome["results"] if r["status"] in ("sent", "failed", "sent_unverified")])
    skipped = {}
    for result in outcome["results"]:
        if result["status"] in ("skipped", "deduped", "blocked", "refused"):
            skipped[f"{result['channel']}:{result['status']}"] = 1
    if context_status.get("monday_plan", "").startswith("unavailable"):
        skipped["monday_plan_unavailable"] = 1
    failed = bool(unverified) or cio == "unavailable" or (attempted and produced == 0)
    empty_reason = None
    if produced == 0 and not failed:
        empty_reason = "all_channels_delivered_earlier"
    sys.stdout.flush()
    summary = {"schema": SCHEMA, "record_id": record["record_id"], "source": source, "band": record["band"],
               "channels": outcome["results"], "cio_row": cio, "monday_plan": context_status.get("monday_plan"),
               "text_chars": len(rendered["text"])}
    lane_output.emit(LANE_ID, mode, lane_output.output_block(
        produced=produced, attempted=attempted, skipped=skipped or None, empty_reason=empty_reason, unit="briefs"),
        started_at=started)
    if failed:
        reason = ("a channel claims a send with no receipt in notification_log" if unverified
                  else "the CIO row could not be written" if cio == "unavailable"
                  else "no delivery channel confirmed")
        receipt(ok=False, exit_code=1, produced=produced, attempted=attempted, skipped=skipped or None,
                empty_reason=reason, summary=summary, error=reason)
        return 1
    receipt(ok=True, exit_code=0, produced=produced, attempted=attempted, skipped=skipped or None,
            empty_reason=empty_reason, summary=summary)
    return 0


def _dedupe(record: dict[str, Any], channel: str) -> str:
    from lib.market_outlook_brief import dedupe_key  # noqa: PLC0415

    return dedupe_key(record["record_id"], channel)


if __name__ == "__main__":
    raise SystemExit(main())
