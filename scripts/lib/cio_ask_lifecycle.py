"""Hourly Ask research lifecycle. One ledger, bounded work, no provider calls on reads/dry runs.

The native n8n executor calls run_once; the operator endpoint calls request_deep.
All durable business state is appended through AskEventStore. No broker mutations.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import inspect
import json
import re
import threading
from typing import Any

from scripts.lib.cio_ask_store import event_id_for

SCHEMA = "CioAskLifecycleReceipt@v1"
AUTO_PROCESS = "cio_ask_reanswer"
REQUEST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


def clock(value=None):
    value = value or datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("ASK_CLOCK_UNZONED")
    return value.astimezone(timezone.utc)


def stamp(value=None):
    return clock(value).isoformat().replace("+00:00", "Z")


def parsed(value):
    try:
        return clock(value) if value else None
    except (TypeError, ValueError):
        return None


def next_hour(value):
    return clock(value).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def latest_answer(thread):
    rows = [a for t in thread.get("turns", []) for a in t.get("answers", [])]
    return max(rows, key=lambda a: str(a.get("produced_at") or ""), default=None)


def latest_turn(thread, ask_id=None):
    rows = [t for t in thread.get("turns", []) if t.get("turn_kind") != "reanswer"]
    if ask_id:
        return next((t for t in rows if t.get("ask_id") == ask_id), None)
    return rows[-1] if rows else None


def project_lifecycle(thread, events, *, now=None):
    """Read-only additive projection; observation clocks never borrow a cache clock."""
    now = clock(now)
    answer = latest_answer(thread) or {}
    provenance = answer.get("provenance") or {}
    checks = [e for e in events if e.get("kind") == "ask.check_finished"]
    checked = [e for e in checks if parsed(e.get("checked_at"))]
    last = checks[-1] if checks else {}
    completed = checked[-1] if checked else {}
    started = [e for e in events if e.get("kind") in ("ask.check_started", "ask.research_started")]
    pending = [
        e
        for e in events
        if e.get("kind") == "ask.check_requested"
        and not any(c.get("request_id") == e.get("request_id") for c in checks)
    ]
    state = last.get("state") or ("partial" if provenance.get("partial") else "not_checked")
    reason = last.get("reason") if last else ("RESEARCH_PARTIAL" if provenance.get("partial") else "NO_CHECK_RECORDED")
    if pending:
        state, reason = "deferred", "QUEUED"
        active = next((e for e in reversed(started) if e.get("request_id") == pending[-1].get("request_id")), None)
        if active:
            state, reason = "checking", None
            if parsed(active.get("at")) and now - clock(active["at"]) > timedelta(minutes=10):
                state, reason = "failed", "INTERRUPTED_OR_TIMED_OUT"
    due = next_hour(completed["checked_at"]) if completed else None
    if due and now > due + timedelta(minutes=15) and state in ("current", "not_checked"):
        state, reason = "overdue", "HOURLY_CHECK_OVERDUE"
    memory = [e for e in events if e.get("kind") == "ask.memory_synced"]
    deliveries = [e for e in events if e.get("kind") == "ask.delivery_status"]
    return {
        "state": state,
        "reason": reason,
        "blocker": reason,
        "last_checked_at": completed.get("checked_at"),
        "last_answer_at": answer.get("produced_at"),
        "next_check_at": stamp(due) if due else None,
        "next_eligible_at": last.get("next_eligible_at"),
        "last_check_outcome": last.get("outcome"),
        "monitoring_active": bool(
            completed.get("automated") and now <= clock(completed["checked_at"]) + timedelta(minutes=75)
        ),
        "memory_sync": memory[-1].get("memory_sync", {})
        if memory
        else {"state": "not_measured", "reason": "NO_MEMORY_RECEIPT"},
        "delivery": deliveries[-1].get("delivery", {})
        if deliveries
        else {"state": "not_measured", "reason": "NO_DELIVERY_RECEIPT"},
        "sources": last.get("sources") or provenance.get("source_runs") or [],
        "providers": last.get("providers") or provenance.get("panel") or [],
        "request_id": (pending[-1] if pending else last).get("request_id"),
    }


def append(store, kind, payload, *, key, now):
    return store.append(kind, {"at": stamp(now), **payload}, event_id=event_id_for(kind, *key))


def _amount(value):
    try:
        result = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError("ASK_COST_UNKNOWN") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("ASK_COST_UNKNOWN")
    return result


def reserve(store, *, thread_id, ask_id, request_id, job_id, projected, config, now, process_id):
    """Atomic aggregate admission across manual/automatic/critique requests."""
    projected = _amount(projected)
    cost = config.get("cost") or {}
    if str((cost.get("approval") or {}).get("status") or "").upper() != "APPROVED":
        return None, "CAP_AWAITING_APPROVAL"
    day = stamp(now)[:10]

    def guard(rows):
        terminal = {r.get("request_id"): r for r in rows if r.get("kind") == "ask.research_finished"}
        actual = sum(
            (_amount(r.get("usd", 0)) for r in rows if r.get("kind") == "ask.cost" and str(r.get("at"))[:10] == day),
            Decimal(0),
        )
        held = sum(
            (
                _amount(r.get("reserved_usd", 0))
                for r in rows
                if r.get("kind") == "ask.research_started"
                and str(r.get("at"))[:10] == day
                and not (terminal.get(r.get("request_id")) or {}).get("usage_known")
            ),
            Decimal(0),
        )
        job_spent = Decimal(0)
        for r in rows:
            if r.get("kind") != "ask.research_started" or r.get("job_id") != job_id:
                continue
            end = terminal.get(r.get("request_id")) or {}
            job_spent += _amount(end.get("actual_usd", 0) if end.get("usage_known") else r.get("reserved_usd", 0))
        used_slots = 0
        for row in rows:
            if row.get("kind") == "ask.research_started" and str(row.get("at"))[:10] == day:
                end = terminal.get(row.get("request_id")) or {}
                used_slots += int(end.get("native_requests", row.get("reserved_requests", 4)))
        if used_slots + 4 > int((config.get("lifecycle") or {}).get("daily_request_cap", 30)):
            return "DAILY_REQUEST_CAP"
        if projected <= 0 or projected + job_spent > _amount(cost.get("per_question_cap_usd", 0)):
            return "PER_QUESTION_CAP"
        if actual + held + projected > _amount(cost.get("daily_cap_usd", 0)):
            return "DAILY_CAP"
        return None

    row, created, reason = store.append_guarded(
        "ask.research_started",
        {
            "thread_id": thread_id,
            "ask_id": ask_id,
            "request_id": request_id,
            "job_id": job_id,
            "reserved_usd": str(projected),
            "reserved_requests": 4,
            "process_id": process_id,
            "at": stamp(now),
        },
        event_id=event_id_for("ask.research_started", request_id),
        guard=guard,
    )
    return row if created else None, reason or ("REQUEST_ALREADY_STARTED" if row is not None else None)


def settle(
    store,
    *,
    thread_id,
    ask_id,
    request_id,
    job_id,
    actual,
    now,
    automated=False,
    published=False,
    answer_id=None,
    native_requests=None,
    fingerprint=None,
):
    known = actual is not None
    if known:
        value = _amount(actual)
        append(
            store,
            "ask.cost",
            {
                "thread_id": thread_id,
                "ask_id": ask_id,
                "request_id": request_id,
                "job_id": job_id,
                "usd": float(value),
                "cost_kind": "reanswer" if automated else "deep",
            },
            key=(request_id, "settled_actual"),
            now=now,
        )
    append(
        store,
        "ask.research_finished",
        {
            "thread_id": thread_id,
            "ask_id": ask_id,
            "request_id": request_id,
            "job_id": job_id,
            "usage_known": known,
            "actual_usd": str(actual) if known else None,
            "automated": automated,
            "published": published,
            "answer_id": answer_id,
            "native_requests": 4 if native_requests is None else native_requests,
            "fingerprint": fingerprint,
        },
        key=(request_id,),
        now=now,
    )


def finish_check(
    d,
    thread_id,
    request_id,
    *,
    now,
    outcome,
    state,
    reason=None,
    checked=True,
    automated=False,
    sources=None,
    providers=None,
    fingerprint=None,
    next_eligible_at=None,
):
    payload = {
        "thread_id": thread_id,
        "request_id": request_id,
        "outcome": outcome,
        "state": state,
        "reason": reason,
        "checked_at": stamp(now) if checked else None,
        "automated": automated,
        "sources": sources or [],
        "providers": providers or [],
        "fingerprint": fingerprint,
        "next_eligible_at": next_eligible_at,
    }
    append(d.store, "ask.check_finished", payload, key=(request_id, stamp(now), outcome), now=now)
    return project_lifecycle(d.store.thread(thread_id) or {}, d.store.events(thread_id=thread_id), now=now)


def _provider(d, context, *, manual_trigger, process_id, prepared_evidence=None):
    fn = d.deep_provider
    if fn is None:
        return None
    parameters = inspect.signature(fn).parameters
    options = {
        "manual_trigger": manual_trigger,
        "process_id": process_id,
        "memory_apply": bool((d.config.get("lifecycle") or {}).get("memory_apply", False)),
    }
    if prepared_evidence is not None:
        options["prepared_evidence"] = prepared_evidence
    variadic = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    return fn(context, **{k: v for k, v in options.items() if variadic or k in parameters})


def request_deep(
    thread_id,
    ask_id,
    *,
    deps,
    request_id=None,
    automated=False,
    prepared_evidence=None,
    job_id=None,
    now=None,
    thread_locked=False,
    process_id=None,
):
    """Existing operator Deep route, with idempotent durable work and actual-cost settlement."""
    from scripts.lib import cio_ask_core as core
    from scripts.lib.cio_ask_contract import (
        AskAnswer,
        AskRequest,
        AskResearchContext,
        ResearchBudget,
        EntityRef,
        mbi_guard_payload,
        research_context_for_model,
    )

    d = deps
    now = clock(now)
    thread = d.store.thread(thread_id)
    turn = latest_turn(thread or {}, ask_id)
    if not thread or not turn:
        return {"ok": False, "error": "ASK_NOT_FOUND"}
    prior = latest_answer(thread)
    request_id = request_id or event_id_for("manual_refresh", thread_id, ask_id, (prior or {}).get("answer_id"))
    if not isinstance(request_id, str) or not REQUEST_RE.fullmatch(request_id):
        return {"ok": False, "error": "BAD_REQUEST_ID"}
    job_id = job_id or request_id
    old = next(
        (
            e
            for e in reversed(d.store.events(thread_id=thread_id))
            if e.get("kind") == "ask.check_finished" and e.get("request_id") == request_id
        ),
        None,
    )
    if old:
        return {
            "ok": True,
            "status": "deep_done",
            "request_id": request_id,
            "reason": old.get("reason"),
            "lifecycle": project_lifecycle(thread, d.store.events(thread_id=thread_id), now=now),
        }
    _, created = append(
        d.store,
        "ask.check_requested",
        {
            "thread_id": thread_id,
            "ask_id": ask_id,
            "request_id": request_id,
            "job_id": job_id,
            "manual_trigger": not automated,
        },
        key=(request_id,),
        now=now,
    )
    if not created and not thread_locked:
        return {
            "ok": True,
            "status": "deep_running",
            "request_id": request_id,
            "lifecycle": project_lifecycle(thread, d.store.events(thread_id=thread_id), now=now),
        }
    result = {"ok": True, "status": "deep_running", "request_id": request_id}

    def execute():
        nonlocal thread, turn, prior
        lock = nullcontext(True) if thread_locked else d.store.thread_lock(thread_id)
        with lock as acquired:
            if not acquired:
                result.update(status="queued", reason="THREAD_BUSY")
                return
            # The API and scheduler share this lock; never admit against a pre-lock snapshot.
            thread = d.store.thread(thread_id) or {}
            turn = latest_turn(thread, ask_id)
            prior = latest_answer(thread)
            history = d.store.events(thread_id=thread_id)
            final = next(
                (
                    e
                    for e in reversed(history)
                    if e.get("kind") == "ask.check_finished" and e.get("request_id") == request_id
                ),
                None,
            )
            if final:
                result.update(status="deep_done", lifecycle=project_lifecycle(thread, history, now=now))
                return
            started = next(
                (e for e in history if e.get("kind") == "ask.research_started" and e.get("request_id") == request_id),
                None,
            )
            if started:
                # A crash may leave a dispatch with unknown usage. Retain its hold and never repeat it.
                result.update(
                    status="blocked",
                    reason="INTERRUPTED_USAGE_RECONCILIATION_REQUIRED",
                    lifecycle=finish_check(
                        d,
                        thread_id,
                        request_id,
                        now=now,
                        outcome="blocked",
                        state="blocked",
                        reason="INTERRUPTED_USAGE_RECONCILIATION_REQUIRED",
                        checked=False,
                        automated=automated,
                    ),
                )
                return
            append(
                d.store,
                "ask.check_started",
                {"thread_id": thread_id, "request_id": request_id},
                key=(request_id,),
                now=now,
            )
            projected = float((d.config.get("cost") or {}).get("projected_usd_deep", 0.25))
            execution_process = process_id or (
                AUTO_PROCESS if automated else str((d.config.get("cost") or {}).get("process_id"))
            )
            try:
                native = d.cost.allow(projected)
            except Exception as exc:
                native = {"allow": False, "reason": "COST_GATE_UNAVAILABLE", "detail": type(exc).__name__}
            reserved, reason = (None, native.get("reason"))
            if native.get("allow"):
                reserved, reason = reserve(
                    d.store,
                    thread_id=thread_id,
                    ask_id=ask_id,
                    request_id=request_id,
                    job_id=job_id,
                    projected=projected,
                    config=d.config,
                    now=now,
                    process_id=execution_process,
                )
            if not reserved:
                reason = reason or "COST_GATE_UNAVAILABLE"
                version = d.store.next_version(ask_id)
                if not automated:
                    core.record_answer(
                        AskAnswer(
                            ask_id=ask_id,
                            thread_id=thread_id,
                            version=version,
                            depth="deep",
                            status="capped",
                            summary="Deep research not run — "
                            + (
                                "the research spend cap awaits your approval"
                                if reason == "CAP_AWAITING_APPROVAL"
                                else reason
                            )
                            + ". The previous answer stands.",
                            entities=[EntityRef.from_dict(e) for e in thread.get("entities", [])],
                            provenance={"cost_gate": native},
                        ),
                        deps=d,
                    )
                life = finish_check(
                    d,
                    thread_id,
                    request_id,
                    now=now,
                    outcome="blocked",
                    state="blocked",
                    reason=reason,
                    automated=automated,
                    checked=prepared_evidence is not None,
                )
                result.update(status="capped", reason=reason, gate=native, lifecycle=life)
                return
            if d.deep_provider is None:
                if not automated:
                    core.record_answer(
                        AskAnswer(
                            ask_id=ask_id,
                            thread_id=thread_id,
                            version=d.store.next_version(ask_id),
                            depth="deep",
                            status="deep_pending",
                            summary="Deep research is not installed yet; the previous answer stands.",
                            entities=[EntityRef.from_dict(e) for e in thread.get("entities", [])],
                        ),
                        deps=d,
                    )
                settle(
                    d.store,
                    thread_id=thread_id,
                    ask_id=ask_id,
                    request_id=request_id,
                    job_id=job_id,
                    actual=0,
                    native_requests=0,
                    now=now,
                )
                life = finish_check(
                    d,
                    thread_id,
                    request_id,
                    now=now,
                    outcome="blocked",
                    state="blocked",
                    reason="RESEARCH_PROVIDER_UNAVAILABLE",
                    checked=False,
                    automated=automated,
                )
                result.update(status="deep_pending", lifecycle=life)
                return
            version = d.store.next_version(ask_id)
            entities = [EntityRef.from_dict(e) for e in thread.get("entities", [])]
            req = AskRequest(
                question=turn["question"],
                channel="event" if automated else (turn.get("channel") or "cc"),
                source_ref=("auto:" if automated else "deep:") + request_id,
                depth="deep",
                thread_id=thread_id,
                entities=entities,
            )
            recall = []
            for entity in entities:
                recall += research_context_for_model(d.memory.recall(entity=entity, limit=6, exclude_refs=()) or [])
            context = AskResearchContext(
                request=req,
                thread_id=thread_id,
                version=version,
                recall=recall,
                quick_answer=(prior or {}).get("summary"),
                budget=ResearchBudget(max_usd=projected, process_id=execution_process),
            )
            published = False
            try:
                answer = _provider(
                    d,
                    context,
                    manual_trigger=not automated,
                    process_id=execution_process,
                    prepared_evidence=prepared_evidence,
                )
                raw, findings = mbi_guard_payload(answer.to_dict(allow_size_suggestion=False))
                answer = AskAnswer.from_dict(raw)
                answer.ask_id, answer.thread_id, answer.version, answer.depth = ask_id, thread_id, version, "deep"
                answer.status = "reanswer" if automated and answer.status != "failed" else answer.status
                answer.mbi_guard = {
                    "stripped": len(findings) + int((answer.mbi_guard or {}).get("stripped") or 0),
                    "findings": findings + list((answer.mbi_guard or {}).get("findings") or []),
                }
                known = (answer.provenance or {}).get("cost_usage_known") is True
                actual = answer.cost_usd if known else None
                core.record_answer(answer, deps=d)
                published = True
                memory = core.sync_answer_memory(answer, deps=d)
                append(
                    d.store,
                    "ask.memory_synced",
                    {
                        "thread_id": thread_id,
                        "request_id": request_id,
                        "answer_id": answer.answer_id,
                        "memory_sync": memory,
                    },
                    key=(answer.answer_id, memory.get("state")),
                    now=now,
                )
                partial = bool((answer.provenance or {}).get("partial"))
                state = "failed" if answer.status == "failed" else "partial" if partial else "current"
                label = "Updated answer" if automated else "Deep answer"
                delivery = core._post_to_telegram(d, thread_id, f"{label} (v{version})\n\n{answer.summary}")
                append(
                    d.store,
                    "ask.delivery_status",
                    {
                        "thread_id": thread_id,
                        "request_id": request_id,
                        "answer_id": answer.answer_id,
                        "delivery": delivery,
                    },
                    key=(answer.answer_id, delivery.get("state")),
                    now=now,
                )
                settle(
                    d.store,
                    thread_id=thread_id,
                    ask_id=ask_id,
                    request_id=request_id,
                    job_id=job_id,
                    actual=actual,
                    now=now,
                    automated=automated,
                    published=published,
                    answer_id=answer.answer_id,
                    native_requests=(answer.provenance or {}).get("native_request_count")
                    if (answer.provenance or {}).get("native_request_count_known")
                    else None,
                    fingerprint=(answer.provenance or {}).get("evidence_fingerprint")
                    or (prepared_evidence or {}).get("fingerprint"),
                )
                life = finish_check(
                    d,
                    thread_id,
                    request_id,
                    now=now,
                    outcome="answered" if not partial else "partial",
                    state=state,
                    reason="RESEARCH_PARTIAL" if partial else None,
                    automated=automated,
                    sources=(answer.provenance or {}).get("source_runs"),
                    providers=(answer.provenance or {}).get("panel"),
                    fingerprint=(answer.provenance or {}).get("evidence_fingerprint")
                    or (prepared_evidence or {}).get("fingerprint"),
                )
                result.update(status="deep_done", lifecycle=life, version=version)
            except Exception as exc:
                # A dispatch may already have spent money. Never release its hold without usage evidence.
                settle(
                    d.store,
                    thread_id=thread_id,
                    ask_id=ask_id,
                    request_id=request_id,
                    job_id=job_id,
                    actual=None,
                    now=now,
                    automated=automated,
                    published=published,
                )
                life = finish_check(
                    d,
                    thread_id,
                    request_id,
                    now=now,
                    outcome="failed",
                    state="failed",
                    reason="RESEARCH_FAILED:" + type(exc).__name__,
                    automated=automated,
                    checked=False,
                )
                result.update(status="failed", reason=life["reason"], lifecycle=life)

    if d.run_async and not thread_locked:
        threading.Thread(target=execute, name="ask-refresh-" + request_id[:20], daemon=True).start()
    else:
        execute()
    return result


def _request(thread, turn):
    return {
        "request_id": turn["ask_id"],
        "question": turn["question"],
        "thread_id": thread["thread_id"],
        "entities": thread.get("entities") or [],
        "subjects": [e.get("symbol") or e.get("name") for e in thread.get("entities", [])],
    }


def _fingerprint(evidence):
    if evidence.get("fingerprint"):
        return str(evidence["fingerprint"])
    return hashlib.sha256(json.dumps(evidence.get("facts", []), sort_keys=True, default=str).encode()).hexdigest()


def _retry_publication(d, thread, events, *, now):
    """Retry only the failed sinks from persisted answer bytes; never recollect or call models."""
    from scripts.lib import cio_ask_core as core
    from scripts.lib.cio_ask_contract import AskAnswer

    answer = latest_answer(thread)
    if not answer:
        return
    aid, tid = answer.get("answer_id"), thread["thread_id"]
    minute_slot = stamp(now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0))
    memories = [e for e in events if e.get("kind") == "ask.memory_synced" and e.get("answer_id") == aid]
    deliveries = [e for e in events if e.get("kind") == "ask.delivery_status" and e.get("answer_id") == aid]
    # Older answers with no acknowledgement are pending, never assumed synced.
    if not memories or memories[-1].get("memory_sync", {}).get("state") != "synced":
        key = event_id_for("memory_retry", aid, minute_slot)
        if not any(e.get("event_id") == key for e in events):
            receipt = core.sync_answer_memory(AskAnswer.from_dict(answer), deps=d)
            d.store.append(
                "ask.memory_synced",
                {"thread_id": tid, "answer_id": aid, "at": stamp(now), "memory_sync": receipt},
                event_id=key,
            )
    if deliveries and deliveries[-1].get("delivery", {}).get("state") == "failed":
        key = event_id_for("delivery_retry", aid, minute_slot)
        if not any(e.get("event_id") == key for e in events):
            receipt = core._post_to_telegram(d, tid, f"Deep answer (v{answer['version']})\n\n{answer['summary']}")
            d.store.append(
                "ask.delivery_status",
                {"thread_id": tid, "answer_id": aid, "at": stamp(now), "delivery": receipt},
                event_id=key,
            )


def run_once(*, deps=None, dry_run=False, events_only=False, now=None, collect=None, event_sources=None, run_id=None):
    """Hourly source checks plus material-event polling. Dry run never constructs live dependencies."""
    from scripts.lib import cio_ask_core as core
    from scripts.lib.cio_ask_store import AskEventStore

    now = clock(now)
    config = deps.config if deps is not None else core.load_config()
    store = deps.store if deps is not None else AskEventStore()
    threads = store.threads()
    tracked = [
        t
        for t in threads.values()
        if any((e.get("tracking") or {}).get("state") == "tracked" for e in t.get("entities", []))
    ]
    report = {
        "schema": SCHEMA,
        "observed_at": stamp(now),
        "run_id": run_id,
        "mode": "dry_run" if dry_run else "live",
        "dry_run": dry_run,
        "ok": True,
        "trigger": {
            "kind": "material_poll" if events_only else "hourly",
            "slot": stamp(now.replace(minute=0, second=0, microsecond=0)),
        },
        "tracked_threads": len(tracked),
        "checked_count": 0,
        "research_count": 0,
        "no_change_count": 0,
        "blocked_count": 0,
        "failed_count": 0,
        "deferred_count": 0,
        "threads": [],
        "source_errors": [],
        "output_receipts": [],
    }
    if dry_run:
        report["would_check"] = [t["thread_id"] for t in tracked]
        report["would_write"] = [
            "Ask lifecycle/check events",
            "CIO research memory acknowledgements",
            "native lane receipt",
        ]
        report["would_call"] = [
            "governed source/search readers",
            "governed research only on material change or incomplete initial answer",
        ]
        return report
    if not (config.get("lifecycle") or {}).get("enabled", False):
        report.update(ok=False, reason="LIFECYCLE_DISABLED")
        return report
    d = deps or core.default_deps()
    # Strict replay prevents malformed accounting evidence from being silently ignored.
    try:
        events = list(store._iter_raw(strict=True))
    except (OSError, ValueError) as exc:
        report.update(ok=False, reason="ASK_LEDGER_UNAVAILABLE", source_errors=[type(exc).__name__])
        return report
    from scripts.lib.cio_ask_reanswer import default_sources

    sources = event_sources if event_sources is not None else default_sources(config)
    by_guid = {e.get("security_guid") for t in tracked for e in t.get("entities", []) if e.get("security_guid")}
    for source in sources:
        checkpoints = [e for e in events if e.get("kind") == "ask.source_checkpoint" and e.get("source") == source.name]
        since = parsed((checkpoints[-1] if checkpoints else {}).get("watermark"))
        since = since or min((parsed(t.get("created_at")) or now for t in tracked), default=now)
        try:
            found = source.fetch(by_guid, since)
            # Requests are persisted before moving the cursor, below; a full page cannot advance beyond its last event.
            watermark = max((parsed(x.get("observed_at")) or since for x in found), default=now)
            for event in found:
                for thread in tracked:
                    if event.get("security_guid") not in {e.get("security_guid") for e in thread.get("entities", [])}:
                        continue
                    turn = latest_turn(thread)
                    if not turn:
                        continue
                    request_id = event_id_for("material_check", thread["thread_id"], event.get("event_id"))
                    append(
                        store,
                        "ask.check_requested",
                        {
                            "thread_id": thread["thread_id"],
                            "ask_id": turn["ask_id"],
                            "request_id": request_id,
                            "job_id": request_id,
                            "manual_trigger": False,
                            "trigger": event,
                        },
                        key=(request_id,),
                        now=now,
                    )
            append(
                store,
                "ask.source_checkpoint",
                {"source": source.name, "watermark": stamp(watermark)},
                key=(source.name, stamp(watermark)),
                now=now,
            )
        except Exception as exc:
            report["source_errors"].append(source.name + ":" + type(exc).__name__)
    if collect is None:
        from scripts.lib.cio_ask_research import collect_current_evidence

        collect = collect_current_evidence
    slot = stamp(now.replace(minute=0, second=0, microsecond=0))
    for snapshot in tracked:
        tid = snapshot["thread_id"]
        with store.thread_lock(tid) as acquired:
            if not acquired:
                report["deferred_count"] += 1
                continue
            thread = store.thread(tid) or {}
            turn = latest_turn(thread)
            if not turn or not any(
                (e.get("tracking") or {}).get("state") == "tracked" for e in thread.get("entities", [])
            ):
                continue
            tevents = store.events(thread_id=tid)
            _retry_publication(d, thread, tevents, now=now)
            tevents = store.events(thread_id=tid)
            endings = {e.get("request_id"): e for e in tevents if e.get("kind") == "ask.check_finished"}
            pending = []
            for event in tevents:
                if event.get("kind") != "ask.check_requested":
                    continue
                end = endings.get(event.get("request_id"))
                if not end:
                    pending.append(event)
                elif end.get("outcome") == "deferred" and (
                    not parsed(end.get("next_eligible_at")) or now >= clock(end["next_eligible_at"])
                ):
                    pending.append(event)
            last = project_lifecycle(thread, tevents, now=now)
            hourly_due = not events_only and (
                not parsed(last.get("last_checked_at")) or clock(last["last_checked_at"]) < clock(slot)
            )
            if not pending and not hourly_due:
                continue
            requested = (
                pending[0]
                if pending
                else {"request_id": event_id_for("hourly_check", tid, slot), "manual_trigger": False}
            )
            rid = requested["request_id"]
            append(
                store,
                "ask.check_requested",
                {"thread_id": tid, "ask_id": turn["ask_id"], **requested},
                key=(rid,),
                now=now,
            )
            append(store, "ask.check_started", {"thread_id": tid, "request_id": rid}, key=(rid,), now=now)
            try:
                evidence = collect(_request(thread, turn))
                fingerprint = _fingerprint(evidence)
                source_rows = evidence.get("source_runs") or []
                errors = [x for x in source_rows if x.get("status") not in ("ok", "no_data", "not_applicable")]
                if errors:
                    raise ValueError("SOURCE_CHECK_INCOMPLETE")
                prior_checks = [
                    e
                    for e in tevents
                    if e.get("kind") == "ask.research_finished" and e.get("published") and e.get("fingerprint")
                ]
                answer = latest_answer(thread)
                prior_fp = ((answer or {}).get("provenance") or {}).get("evidence_fingerprint") or (
                    prior_checks[-1].get("fingerprint") if prior_checks else None
                )
                incomplete = (
                    not answer
                    or answer.get("status") in ("failed", "capped", "deep_pending")
                    or bool((answer.get("provenance") or {}).get("partial"))
                )
                changed = fingerprint != prior_fp
                if not incomplete and not changed and not requested.get("manual_trigger"):
                    life = finish_check(
                        d,
                        tid,
                        rid,
                        now=now,
                        outcome="no_change",
                        state="current",
                        automated=True,
                        sources=source_rows,
                        fingerprint=fingerprint,
                    )
                    report["no_change_count"] += 1
                else:
                    published = [
                        e
                        for e in tevents
                        if e.get("kind") == "ask.research_finished" and e.get("automated") and e.get("published")
                    ]
                    min_gap = timedelta(
                        hours=float((config.get("reanswer") or {}).get("min_hours_between_per_thread", 6))
                    )
                    eligible = clock(published[-1]["at"]) + min_gap if published else now
                    daily = sum(
                        e.get("kind") == "ask.research_finished"
                        and e.get("automated")
                        and e.get("published")
                        and str(e.get("at"))[:10] == stamp(now)[:10]
                        for e in store.events()
                    )
                    if not requested.get("manual_trigger") and (
                        now < eligible or daily >= int((config.get("reanswer") or {}).get("max_per_day", 10))
                    ):
                        reason = "ANSWER_COOLDOWN" if now < eligible else "DAILY_ANSWER_LIMIT"
                        life = finish_check(
                            d,
                            tid,
                            rid,
                            now=now,
                            outcome="deferred",
                            state="deferred",
                            reason=reason,
                            automated=True,
                            sources=source_rows,
                            fingerprint=fingerprint,
                            next_eligible_at=stamp(eligible)
                            if now < eligible
                            else stamp(now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)),
                        )
                        report["deferred_count"] += 1
                    else:
                        # The hourly/event check id and research id are distinct, so a queued check never suppresses its own dispatch.
                        job_id = event_id_for("evidence_budget", tid, turn["ask_id"], fingerprint, stamp(now)[:10])
                        attempts = [
                            e for e in tevents if e.get("kind") == "ask.research_started" and e.get("job_id") == job_id
                        ]
                        if len(attempts) >= int((config.get("lifecycle") or {}).get("max_attempts_per_evidence", 2)):
                            life = finish_check(
                                d,
                                tid,
                                rid,
                                now=now,
                                outcome="blocked",
                                state="blocked",
                                reason="EVIDENCE_RETRY_LIMIT",
                                automated=True,
                                sources=source_rows,
                                fingerprint=fingerprint,
                            )
                            report["blocked_count"] += 1
                            report["checked_count"] += 1
                            report["threads"].append(
                                {
                                    "thread_id": tid,
                                    "lifecycle": life,
                                    "consumer_readback": {
                                        "state": "verified",
                                        "answer_id": (latest_answer(thread) or {}).get("answer_id"),
                                    },
                                }
                            )
                            continue
                        research_id = (
                            rid
                            if requested.get("manual_trigger") and not endings.get(rid)
                            else event_id_for("checked_research", rid, len(attempts))
                        )
                        cfg = {**d.config, "cost": {**d.config.get("cost", {}), "process_id": AUTO_PROCESS}}
                        synchronous = replace(
                            d, run_async=False, config=cfg, cost=core.CostGate(cfg, store, d.cost.global_check)
                        )
                        res = request_deep(
                            tid,
                            turn["ask_id"],
                            deps=synchronous,
                            request_id=research_id,
                            automated=not requested.get("manual_trigger"),
                            prepared_evidence=evidence,
                            job_id=job_id,
                            now=now,
                            thread_locked=True,
                            process_id=AUTO_PROCESS,
                        )
                        life = res.get("lifecycle") or project_lifecycle(
                            store.thread(tid) or thread, store.events(thread_id=tid), now=now
                        )
                        child = next(
                            (
                                e
                                for e in reversed(store.events(thread_id=tid))
                                if e.get("kind") == "ask.check_finished" and e.get("request_id") == research_id
                            ),
                            {},
                        )
                        append(
                            store,
                            "ask.check_finished",
                            {
                                "thread_id": tid,
                                "request_id": rid,
                                "checked_at": stamp(now),
                                "state": child.get("state", life["state"]),
                                "outcome": child.get("outcome", life.get("last_check_outcome")),
                                "reason": child.get("reason", life.get("reason")),
                                "automated": True,
                                "fingerprint": fingerprint,
                                "sources": source_rows,
                                "providers": life.get("providers", []),
                            },
                            key=(rid, stamp(now)),
                            now=now,
                        )
                        life = project_lifecycle(store.thread(tid) or thread, store.events(thread_id=tid), now=now)
                        report["research_count"] += int(res.get("status") == "deep_done")
                        report["blocked_count"] += int(res.get("status") in ("capped", "deep_pending", "blocked"))
                        report["failed_count"] += int(res.get("status") == "failed")
                report["checked_count"] += 1
                readback = store.thread(tid)
                report["threads"].append(
                    {
                        "thread_id": tid,
                        "lifecycle": life,
                        "consumer_readback": {
                            "state": "verified" if readback else "failed",
                            "answer_id": (latest_answer(readback or {}) or {}).get("answer_id"),
                        },
                    }
                )
            except Exception as exc:
                life = finish_check(
                    d,
                    tid,
                    rid,
                    now=now,
                    outcome="failed",
                    state="failed",
                    reason="CHECK_FAILED:" + type(exc).__name__,
                    checked=False,
                    automated=True,
                )
                report["failed_count"] += 1
                report["source_errors"].append(tid + ":" + type(exc).__name__)
                report["threads"].append(
                    {"thread_id": tid, "lifecycle": life, "consumer_readback": {"state": "not_measured"}}
                )
    report["ok"] = not report["source_errors"] and report["failed_count"] == 0
    return report
