"""Ask the CIO — Phase 11: re-answer tracked questions when something material changes. READ_ONLY_ADVISORY.

Each tracked security (``AskEventStore.tracked_entities``) is subscribed to the house's existing material-change
feeds, keyed by ``security_guid``:

* ``sec_filing_events`` — ``data/cio/sec_filing_events.jsonl`` (``scripts/sec_filings_feed.py``; ``subject_guid``)
* ``material_changes``  — Postgres ``material_changes`` (``scripts/material_change_detector.py``; ``subject_guid``)

When an event fires for a tracked thread, the CIO asks the thread's original question again through the same converse
path (channel ``event``), with the event as the trigger, and posts the new answer version in the same thread (CC via
the ledger, Telegram as a message in the thread) with "What changed".

Guards, in order: one re-answer per (thread, event) ever (idempotent); at most one per thread per
``min_hours_between_per_thread``; at most ``max_per_day`` overall; the cost gate (the $5/day cap awaits approval —
until APPROVED every re-answer is refused before spend). ``mode`` is ``shadow`` by default: candidates are recorded
as ``ask.reanswer_skipped`` (reason ``shadow``), nothing is spent or sent.

Not scheduled by this change (cron freeze; n8n-first): the proposed lane is ``cio-ask-reanswer`` at shadow,
``scripts/cio_ask_reanswer.py --once``. Operator approval required.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from scripts.lib.cio_ask_core import AskDeps, _deps, cc_chat_id, link_channel
from scripts.lib.cio_ask_store import event_id_for

REPO_ROOT = Path(__file__).resolve().parents[2]


class EventSource(Protocol):
    name: str

    def fetch(self, guids: set[str], since: datetime) -> list[dict[str, Any]]: ...


def _parse(ts: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


class SecFilingEventsFile:
    name = "sec_filing_events"

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else REPO_ROOT / "data" / "cio" / "sec_filing_events.jsonl"

    def fetch(self, guids: set[str], since: datetime) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not self.path.exists():
            return out
        with self.path.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                g = str(r.get("subject_guid") or "")
                at = _parse(r.get("filed_at") or r.get("observed_at"))
                if g not in guids or not at or at < since:
                    continue
                out.append(
                    {
                        "event_id": str(r.get("event_guid") or r.get("accession")),
                        "security_guid": g,
                        "symbol": r.get("symbol"),
                        "kind": f"sec_filing:{r.get('form')}",
                        "observed_at": at.isoformat(),
                        "summary": f"{r.get('symbol')} filed {r.get('form')}"
                        + (f" ({r.get('catalyst_type')})" if r.get("catalyst_type") else "")
                        + (f" — severity {r.get('severity')}" if r.get("severity") else ""),
                        "url": r.get("sec_url"),
                        "source": self.name,
                    }
                )
        return out


class MaterialChangesTable:
    name = "material_changes"
    SQL = (
        "SELECT change_guid::text AS change_guid, subject_guid::text AS subject_guid, symbol, kind, magnitude, "
        "observed_at FROM material_changes WHERE subject_guid = ANY(%s::uuid[]) AND observed_at > %s "
        "ORDER BY observed_at ASC LIMIT 200"
    )

    def __init__(self, db_query: Optional[Callable[..., list[dict]]] = None):
        self.db_query = db_query

    def fetch(self, guids: set[str], since: datetime) -> list[dict[str, Any]]:
        q = self.db_query
        if q is None:
            from scripts.lib.comms_editor import default_db_query as q  # noqa: PLC0415
        rows = q(self.SQL, (sorted(guids), since)) or []
        out = []
        for r in rows:
            at = r.get("observed_at")
            out.append(
                {
                    "event_id": str(r.get("change_guid")),
                    "security_guid": str(r.get("subject_guid")),
                    "symbol": r.get("symbol"),
                    "kind": f"material_change:{r.get('kind')}",
                    "observed_at": at.isoformat() if hasattr(at, "isoformat") else str(at),
                    "summary": f"{r.get('symbol')} material change: {r.get('kind')}"
                    + (f" (magnitude {r.get('magnitude')})" if r.get("magnitude") is not None else ""),
                    "source": self.name,
                }
            )
        return out


def default_sources(cfg: dict) -> list[EventSource]:
    names = (cfg.get("reanswer") or {}).get("sources") or ["sec_filing_events", "material_changes"]
    out: list[EventSource] = []
    if "sec_filing_events" in names:
        out.append(SecFilingEventsFile())
    if "material_changes" in names:
        out.append(MaterialChangesTable())
    return out


def _processed(store, thread_id: str, event_id: str) -> bool:
    for e in store.events(thread_id=thread_id):
        if (
            e.get("kind") in ("ask.reanswer_triggered", "ask.reanswer_skipped")
            and (e.get("trigger") or {}).get("event_id") == event_id
            and e.get("final", True)
        ):
            return True
    return False


def _last_reanswer_at(store, thread_id: str) -> Optional[datetime]:
    ts = [_parse(e.get("at")) for e in store.events(thread_id=thread_id) if e.get("kind") == "ask.reanswer_triggered"]
    ts = [t for t in ts if t]
    return max(ts) if ts else None


def _reanswers_today(store, now: datetime) -> int:
    d = now.date().isoformat()
    return sum(1 for e in store.events() if e.get("kind") == "ask.reanswer_triggered" and str(e.get("at"))[:10] == d)


def run_once(
    *,
    deps: Optional[AskDeps] = None,
    sources: Optional[list[EventSource]] = None,
    mode: Optional[str] = None,
    dry_run: bool = False,
    now: Optional[datetime] = None,
    converse: Optional[Callable[..., dict]] = None,
) -> dict[str, Any]:
    """One pass. ``dry_run`` reads and reports only (no ledger writes, no spend, no send)."""
    d = _deps(deps)
    if d is None:
        return {"ok": False, "error": "ASK_DISABLED"}
    cfg = d.config.get("reanswer") or {}
    mode = mode or str(cfg.get("mode") or "shadow")
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=float(cfg.get("lookback_hours") or 48))
    tracked = [e for e in d.store.tracked_entities() if e.get("security_guid")]
    by_guid: dict[str, list[dict]] = {}
    for e in tracked:
        by_guid.setdefault(str(e["security_guid"]), []).append(e)
    report: dict[str, Any] = {
        "ok": True,
        "mode": mode,
        "dry_run": dry_run,
        "tracked": len(tracked),
        "events": 0,
        "candidates": [],
        "reanswered": [],
        "skipped": [],
        "errors": [],
    }
    if not by_guid:
        return report
    events: list[dict] = []
    for src in sources if sources is not None else default_sources(d.config):
        try:
            events += src.fetch(set(by_guid), since)
        except Exception as exc:  # noqa: BLE001 — one dead feed is reported, the others still run
            report["errors"].append(f"{getattr(src, 'name', 'source')}: {type(exc).__name__}")
    report["events"] = len(events)
    min_gap = timedelta(hours=float(cfg.get("min_hours_between_per_thread") or 6))
    max_day = int(cfg.get("max_per_day") or 10)
    done_today = _reanswers_today(d.store, now)
    for ev in sorted(events, key=lambda x: str(x.get("observed_at"))):
        for ent in by_guid.get(str(ev.get("security_guid")), []):
            tid = ent["thread_id"]
            cand = {
                "thread_id": tid,
                "event_id": ev["event_id"],
                "symbol": ev.get("symbol"),
                "kind": ev.get("kind"),
                "summary": ev.get("summary"),
            }
            if _processed(d.store, tid, ev["event_id"]):
                continue
            report["candidates"].append(cand)
            reason = None
            last = _last_reanswer_at(d.store, tid)
            if last and now - last < min_gap:
                reason = "RATE_LIMIT_THREAD"
            elif done_today >= max_day:
                reason = "RATE_LIMIT_DAILY"
            elif mode != "live":
                reason = "SHADOW"
            else:
                gate = d.cost.allow(float((d.config.get("cost") or {}).get("projected_usd_reanswer") or 0.05))
                if not gate["allow"]:
                    reason = gate["reason"]
            if dry_run:
                report["skipped" if reason else "reanswered"].append({**cand, "reason": reason, "dry_run": True})
                continue
            if reason:
                final = reason in ("SHADOW", "CAP_AWAITING_APPROVAL")
                d.store.append(
                    "ask.reanswer_skipped",
                    {"thread_id": tid, "trigger": ev, "reason": reason, "final": final},
                    event_id=event_id_for(
                        "ask.reanswer_skipped", tid, ev["event_id"], reason, "" if final else now.date().isoformat()
                    ),
                )
                report["skipped"].append({**cand, "reason": reason})
                continue
            res = reanswer(tid, ev, deps=d, converse=converse)
            if res.get("ok"):
                done_today += 1
                report["reanswered"].append({**cand, "version": res.get("version")})
            else:
                report["errors"].append(f"{tid}: {res.get('error')}")
    return report


def reanswer(
    thread_id: str,
    event: dict[str, Any],
    *,
    deps: Optional[AskDeps] = None,
    converse: Optional[Callable[..., dict]] = None,
) -> dict[str, Any]:
    d = _deps(deps)
    t = d.store.thread(thread_id) if d else None
    if not t or not t["turns"]:
        return {"ok": False, "error": "THREAD_NOT_FOUND"}
    root = t["turns"][0]
    prior = None
    for turn in t["turns"]:
        for a in turn["answers"]:
            prior = a
    d.store.append(
        "ask.reanswer_triggered",
        {"thread_id": thread_id, "trigger": event},
        event_id=event_id_for("ask.reanswer_triggered", thread_id, event["event_id"]),
    )
    question = f"{root['question']} {thread_id}"
    trigger = {**event, "previous_answer": (prior or {}).get("answer_id")}
    captured: dict[str, Any] = {}

    def _capture(_cid: str, body: str, reply_to: Optional[str] = None) -> dict:
        captured["text"] = body
        return {"ok": True, "message_id": None}

    if converse is None:
        from scripts.lib.cio_converse_core import process_operator_message as converse  # noqa: PLC0415
    cid = cc_chat_id()
    out = converse(
        channel="event",
        chat_id=cid,
        message_id=f"evt_{event['event_id']}",
        text=question,
        allowlist={cid},
        converse_on=True,
        send_fn=_capture,
        ask_options={
            "thread_id": thread_id,
            "turn_kind": "reanswer",
            "trigger": trigger,
            "deps": d,
            "what_changed": _what_changed(event, prior),
        },
    )
    text = captured.get("text") or ""
    d.cost.record(
        thread_id=thread_id,
        ask_id=(out.get("ask") or {}).get("ask_id") or thread_id,
        usd=float((d.config.get("cost") or {}).get("projected_usd_reanswer") or 0.05),
        kind="reanswer",
    )
    if text and d.telegram_send:
        try:
            res = d.telegram_send(f"Updated answer — {event.get('summary')}\n\n{text}") or {}
            if res.get("message_id") is not None:
                link_channel(
                    d.store, thread_id=thread_id, channel="telegram", chat_id=cid, message_id=res["message_id"]
                )
        except Exception:  # noqa: BLE001
            pass
    return {
        "ok": bool(text),
        "version": (out.get("ask") or {}).get("version"),
        "text": text,
        "error": None if text else "NO_ANSWER",
    }


def _what_changed(event: dict[str, Any], prior: Optional[dict]) -> str:
    when = str(event.get("observed_at") or "")[:16].replace("T", " ")
    base = f"{event.get('summary')} ({when} UTC, {event.get('source')})"
    if prior:
        excerpt = " ".join(str(prior.get("summary") or "").split())[:200]
        base += f'. Previous answer (v{prior.get("version")}, {str(prior.get("produced_at"))[:10]}): "{excerpt}…"'
    return base


__all__ = ["run_once", "reanswer", "SecFilingEventsFile", "MaterialChangesTable", "default_sources"]
