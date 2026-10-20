#!/usr/bin/env python3
"""Report gaps nobody is trying to close, vectors that keep failing, and any
vector that ran a retired provider. Read-only.

WHY
---
Phase 7 of One Source of Truth turned "stale or missing" into a declared,
budgeted, receipted sequence of attempts (scripts/lib/gap_resolver.py). A
sequence that is declared and never run is the same as no sequence -- that is
the recurring defect in this repository (check_dark_contracts.py exists because
of it). So this measures the receipts against the gaps:

    OPEN_NO_ATTEMPT   a gap queued or registered more than 2h ago with no receipt
    VECTOR_FAILING    a vector whose receipts show >= 3 errors today
    RETIRED_RAN       a receipt whose provider is retired and whose outcome is
                      not retired_skipped -- the registry said never, and it ran
    REFUSED_NOWHERE   a search the budget refused that NO lane answered: the
                      denial receipt's spilled_to is null. Measured 2026-09-16
                      on the live ledger: 129 of them, every one
                      CALLER_DAILY_CAP, and nobody was ever told. A refusal is
                      a governance success only if the question went somewhere.

RETIRED_RAN must always be 0. It is a [DATA_INTEGRITY] finding because the
catalyst chain fell through four dead slots for seven weeks and nothing said so.

2026-10-18 (data-integrity fix PR):
  * OPEN_NO_ATTEMPT could never clear for a research gap: research_gap.gap_id
    (uuid5 of security_guid|reason|question) is never the gap_resolver
    DataGap.gap_id (uuid5 of domain|subject|question), so no receipt ever
    matched. An attempt is now ALSO any touch for the gap's symbol after it was
    created: a gap_resolver receipt for that subject, a TickerResearchState
    circulation/curation touch (updated_at / last_free_refresh /
    last_model_assisted_curation), or a completed Hermes research result.
  * the alert fingerprint is counts/hashes per finding class, and only
    RETIRED_RAN and VECTOR_FAILING are IMMEDIATE ([DATA_INTEGRITY], P2). A
    VECTOR_FAILING set that empties at the UTC day boundary is NOT news (it
    sent a "Cleared" every midnight); only a RETIRED_RAN clearing is reported.
  * OPEN_NO_ATTEMPT and REFUSED_NOWHERE go to the DIGEST (P3 notification
    intent, no sentinel; operator_alert_policy_v2 routes it as job telemetry),
    on change of their count/hash.
  * ``--notify queue`` (the n8n lane) queues host comms intents instead of
    calling a sender; ``--lane-receipt`` writes LaneRunReceipt@v2 for lane
    n8n-gap-resolution-audit and exits 0 when the run completed.

The receipt data/runtime/gap_resolution_last_run.json is written every run,
findings or not, so a stopped timer does not look like a clean result. The
alert state under ~/.local/state/tradeai/ makes the Telegram fire on CHANGE only.

USAGE
-----
    python scripts/check_gap_resolution.py            # human-readable
    python scripts/check_gap_resolution.py --json
    python scripts/check_gap_resolution.py --alert    # notify on change
    python scripts/check_gap_resolution.py --dry-run  # collect + print; writes nothing
    ... --lane-receipt [--alert --notify queue]       # the n8n lane argv

EXIT CODES
----------
    0  nothing to report
    1  at least one finding
    2  could not run
  with --lane-receipt: 0 the run completed (findings or not), 1 could not run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SCHEMA = "GapResolutionReport@v1"
RECEIPT_NAME = "gap_resolution_last_run.json"
STATE_PATH = Path.home() / ".local/state/tradeai/gap_resolution_last_alert.json"
SENTINEL = "[DATA_INTEGRITY]"

#: n8n lane id (config/lane_registry.json, config/n8n_run_allowlist.json, config/n8n_health_contracts.json).
LANE_ID = "n8n-gap-resolution-audit"
#: Host comms-intent routes this producer owns (config/host_comms_intent_routes.json).
INTENT_PRODUCER = "check_gap_resolution"
INTENT_DOMAIN = "data"
INTENT_KIND_IMMEDIATE = "gap_resolution_finding"
INTENT_KIND_DIGEST = "gap_resolution_digest"
NOTIFY_MODES = ("send", "queue")
#: Finding classes that interrupt (sentinel, P2). Everything else is digest material (P3).
IMMEDIATE_CLASSES = ("RETIRED_RAN", "VECTOR_FAILING")
DIGEST_CLASSES = ("OPEN_NO_ATTEMPT", "REFUSED_NOWHERE")
#: LaneRunReceipt@v2 reasons.
SKIP_DEPENDENCY = "dependency_unavailable"
EMPTY_NO_INPUT = "no_new_input"
#: Touch sources (relative to the project root) that count as an attempt on a research gap.
TICKER_STATE_REL = "data/cio/ticker_research_state.jsonl"
HERMES_RESULTS_REL = "data/cio/hermes_research_results.jsonl"

OPEN_HOURS = 2.0
FAIL_THRESHOLD = 3
#: Refusals-into-silence per caller per day before this is worth an operator's
#: attention. One or two is a cap doing its job at the margin; a handful every
#: day is a lane whose questions are never being asked anywhere.
REFUSED_THRESHOLD = 5
#: How far back REFUSED_NOWHERE looks. NOT "today": the first version of that
#: finding filtered to the current date and therefore reported 0 while 129
#: standing `spilled_to: null` receipts sat in the ledger -- the exact condition
#: it exists to catch. A refusal that went nowhere does not stop mattering at
#: midnight; it matters until something answers it.
REFUSED_WINDOW_DAYS = 7

#: Measured 2026-09-16, not asserted: `systemctl --user list-timers` shows this
#: timer ACTIVE, last run 11:38 EDT, next 12:07. The previous value of this
#: string said "(proposed, not installed)" and had drifted -- a declaration the
#: dark-contract gate accepts as fact and never probes, which is the same class
#: of defect this script exists to report. Re-verify before editing.
SCHEDULED_ENTRYPOINT = "systemd: tradeai-gap-resolution.timer -- every 30 min at :07/:37 (INSTALLED, active; verified 2026-09-16)"


def _parse_ts(v) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


def symbol_touches(receipts: list[dict], state_rows: list[dict] | None = None,
                   hermes_rows: list[dict] | None = None) -> dict[str, datetime]:
    """SYMBOL -> the latest moment anything worked on it. Pure (2026-10-18).

    Sources: a gap_resolver receipt's ``subject`` (``started``); a
    TickerResearchState row (``updated_at`` / ``last_free_refresh`` /
    ``last_model_assisted_curation`` -- the circulation / curation touch); a
    COMPLETED Hermes research result (``completed_ts``).
    """
    out: dict[str, datetime] = {}

    def _bump(sym, ts):
        sym = str(sym or "").strip().upper()
        t = _parse_ts(ts) if ts else None
        if not sym or sym == "BOOK" or t is None:
            return
        if sym not in out or t > out[sym]:
            out[sym] = t

    for r in receipts or []:
        _bump(r.get("subject"), r.get("started") or r.get("finished"))
    for r in state_rows or []:
        for k in ("updated_at", "last_free_refresh", "last_model_assisted_curation"):
            _bump(r.get("symbol"), r.get(k))
    for r in hermes_rows or []:
        if str(r.get("status") or "").lower() not in ("completed", "done", "ok"):
            continue
        _bump(r.get("symbol"), r.get("completed_ts") or r.get("completed_at"))
    return out


def open_gaps(queue_rows: list[dict], research_rows: list[dict], receipts: list[dict], *,
              now: datetime, open_hours: float = OPEN_HOURS,
              touches: dict[str, datetime] | None = None) -> list[dict]:
    """Gaps older than `open_hours` with no attempt. Pure.

    An attempt is a receipt against the gap_id, or (2026-10-18) a touch for the
    gap's symbol AFTER the gap was created (``touches``, see symbol_touches):
    research_gap ids and gap_resolver ids are different uuid5 namespaces, so an
    id match alone could never clear a research gap.
    """
    attempted = {str(r.get("gap_id")) for r in receipts if r.get("gap_id")}
    touched = touches or {}

    def _touched_after(sym, ts) -> bool:
        t = touched.get(str(sym or "").strip().upper())
        return t is not None and ts is not None and t > ts

    cutoff = now - timedelta(hours=open_hours)
    out: list[dict] = []
    seen: set[str] = set()
    for r in queue_rows:
        gid = str(r.get("gap_id") or "")
        ts = _parse_ts(r.get("ts"))
        if not gid or gid in seen or r.get("status") not in (None, "open") or ts is None or ts > cutoff:
            continue
        seen.add(gid)
        if gid not in attempted and not _touched_after(r.get("subject"), ts):
            out.append({"gap_id": gid, "domain": r.get("domain"), "subject": r.get("subject"),
                        "age_hours": round((now - ts).total_seconds() / 3600, 1), "origin": "gap_queue"})
    for r in research_rows:
        gid = str(r.get("gap_id") or "")
        ts = _parse_ts(r.get("created_at"))
        if not gid or gid in seen or str(r.get("status")) != "OPEN" or ts is None or ts > cutoff:
            continue
        seen.add(gid)
        if gid not in attempted and not _touched_after(r.get("symbol"), ts):
            out.append({"gap_id": gid, "domain": "research_thesis", "subject": r.get("symbol"),
                        "age_hours": round((now - ts).total_seconds() / 3600, 1), "origin": "research_gaps"})
    return out


def failing_vectors(receipts: list[dict], *, now: datetime, threshold: int = FAIL_THRESHOLD) -> list[dict]:
    """Vectors with >= threshold `error` receipts today (UTC). Pure."""
    day = now.date().isoformat()
    counts: dict[str, int] = {}
    for r in receipts:
        if r.get("outcome") != "error" or str(r.get("started") or "")[:10] != day:
            continue
        v = str(r.get("vector") or "?")
        counts[v] = counts.get(v, 0) + 1
    return [{"vector": v, "errors_today": n} for v, n in sorted(counts.items()) if n >= threshold]


def retired_ran(receipts: list[dict], retired: frozenset[str]) -> list[dict]:
    """Receipts that RAN a retired provider. Refusals (retired_skipped) are correct. Pure."""
    out: list[dict] = []
    for r in receipts:
        p = str(r.get("provider") or "").strip().lower()
        if p and p in retired and r.get("outcome") != "retired_skipped":
            out.append({"gap_id": r.get("gap_id"), "vector": r.get("vector"), "provider": p,
                        "outcome": r.get("outcome"), "started": r.get("started")})
    return out


def refused_nowhere(rows: list[dict], *, now: datetime,
                    threshold: int = REFUSED_THRESHOLD,
                    window_days: int = REFUSED_WINDOW_DAYS) -> list[dict]:
    """Search denials in the last ``window_days`` that went nowhere. Pure.

    ``spilled_to: null`` is the ledger saying this question was refused and then
    asked of no one. Grouped by caller+reason so one cron shape does not print
    seventy identical lines; a group is reported once it clears ``threshold``.

    **Why the window is not "today" (fixed 2026-09-16).** The first version of
    this finding filtered ``ts[:10] != now.date()``, so it reported **0** while
    129 standing ``spilled_to: null`` receipts sat in the ledger — the exact
    condition it was written to catch. A refusal that went nowhere does not stop
    mattering at midnight; it matters until something answers it. The window is
    a parameter so the caller may narrow it, and it defaults to a week.
    """
    # N days means today plus the N-1 days before it, so window_days=1 is "today
    # only" and window_days=7 is a calendar week including today. Computing
    # `now - N days` instead would make "1 day" silently span two dates.
    cutoff = (now - timedelta(days=max(1, int(window_days)) - 1)).date().isoformat()
    counts: dict[tuple[str, str], int] = {}
    for r in rows:
        ts = str(r.get("ts") or "")[:10]
        if not ts or ts < cutoff or r.get("spilled_to"):
            continue
        key = (str(r.get("caller") or "?"), str(r.get("reason") or "?"))
        counts[key] = counts.get(key, 0) + 1
    return [{"caller": c, "reason": rs, "refused_in_window": n,
             "window_days": int(window_days)}
            for (c, rs), n in sorted(counts.items()) if n >= threshold]


def collect(*, now: datetime | None = None, receipts_path: Path | None = None,
            queue_path: Path | None = None, research_path: Path | None = None,
            retired: frozenset[str] | None = None,
            denials: list[dict] | None = None,
            state_path: Path | None = None, hermes_path: Path | None = None) -> dict:
    from scripts.lib.gap_resolver import RECEIPTS_PATH
    # data_broker is spelled `lib.data_broker` by its own __init__; importing it
    # as scripts.lib.data_broker loads the package twice (dual-import guard).
    from lib.data_broker.gap_hook import QUEUE_PATH
    from scripts.lib.research_gap import PATH as RESEARCH_REL

    now = now or datetime.now(timezone.utc)
    receipts = _jsonl(receipts_path or RECEIPTS_PATH)
    queue = _jsonl(queue_path or QUEUE_PATH)
    research = _jsonl(research_path or (PROJECT_ROOT / RESEARCH_REL))
    # Touch sources. An injected research_path (tests) without injected touch paths reads NO production
    # touch file: a hermetic run must never depend on the real machine's ledgers.
    hermetic = research_path is not None
    state_rows = _jsonl(state_path) if state_path is not None else (
        [] if hermetic else _jsonl(PROJECT_ROOT / TICKER_STATE_REL))
    hermes_rows = _jsonl(hermes_path) if hermes_path is not None else (
        [] if hermetic else _jsonl(PROJECT_ROOT / HERMES_RESULTS_REL))
    touches = symbol_touches(receipts, state_rows, hermes_rows)
    if retired is None:
        from scripts.lib.retired_providers import retired_providers
        retired = retired_providers()
    if denials is None:
        # Read-only, and never a reason this monitor cannot run: an unreadable
        # budget ledger means "no receipts to judge", not a crash.
        try:
            from scripts.lib.search_budget import denial_receipts
            denials = denial_receipts()
        except Exception:
            denials = []
    findings = {
        "OPEN_NO_ATTEMPT": open_gaps(queue, research, receipts, now=now, touches=touches),
        "VECTOR_FAILING": failing_vectors(receipts, now=now),
        "RETIRED_RAN": retired_ran(receipts, retired),
        "REFUSED_NOWHERE": refused_nowhere(denials, now=now),
    }
    return {
        "schema": SCHEMA,
        "ran_at": now.isoformat(),
        "receipts": len(receipts),
        "search_denials": len(denials),
        "queued_gaps": len(queue),
        "research_gaps": len(research),
        "touch_rows": {"ticker_research_state": len(state_rows), "hermes_results": len(hermes_rows),
                       "symbols_touched": len(touches)},
        "findings": findings,
        "finding_count": sum(len(v) for v in findings.values()),
    }


def _write_run_receipt(report: dict) -> None:
    """Prove this ran, every run. The alert state only changes on change."""
    path = PROJECT_ROOT / "data" / "runtime" / RECEIPT_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    except OSError as exc:
        print(f"  receipt: could not write {path} ({exc})", file=sys.stderr)


def _hash(keys) -> str:
    raw = "\n".join(sorted(str(k) for k in keys))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _class_keys(findings: dict) -> dict[str, list[str]]:
    """The identity of each finding class: what makes one run's set different from another's. Pure."""
    return {
        # names only: errors_today grows through the day and is not news by itself
        "VECTOR_FAILING": [f"vector:{v['vector']}" for v in findings.get("VECTOR_FAILING", [])],
        "RETIRED_RAN": sorted({f"retired:{r['vector']}:{r['provider']}" for r in findings.get("RETIRED_RAN", [])}),
        "OPEN_NO_ATTEMPT": [f"open:{g['gap_id']}" for g in findings.get("OPEN_NO_ATTEMPT", [])],
        # .get: a report is also read back from a receipt written by an EARLIER
        # version of this script, which has no such key. A monitor that crashes on
        # a shape it can otherwise read is a monitor that stops reporting.
        "REFUSED_NOWHERE": [f"refused:{r['caller']}:{r['reason']}" for r in findings.get("REFUSED_NOWHERE", [])],
    }


def _fp_from_keys(keys: dict[str, list[str]]) -> dict[str, dict[str, str]]:
    imm = {c: _hash(keys[c]) for c in IMMEDIATE_CLASSES if keys.get(c)}
    dig = {c: f"{len(keys[c])}:{_hash(keys[c])}" for c in DIGEST_CLASSES if keys.get(c)}
    return {"immediate": imm, "digest": dig}


def fingerprint(report: dict) -> dict[str, dict[str, str]]:
    """{"immediate": {class: hash}, "digest": {class: "count:hash"}}. Pure (2026-10-18).

    The previous fingerprint was one key per finding, so every new or closed gap
    and every UTC-midnight reset of VECTOR_FAILING re-sent the whole message as
    an interrupt. Per class now, and split by route.
    """
    return _fp_from_keys(_class_keys(report["findings"]))


def _normalise_previous(prev: dict) -> dict[str, dict[str, str]]:
    """Read a stored fingerprint, including the pre-2026-10-18 flat {key: CLASS} shape."""
    if not isinstance(prev, dict):
        return {"immediate": {}, "digest": {}}
    if "immediate" in prev or "digest" in prev:
        return {"immediate": dict(prev.get("immediate") or {}), "digest": dict(prev.get("digest") or {})}
    keys: dict[str, list[str]] = {c: [] for c in (*IMMEDIATE_CLASSES, *DIGEST_CLASSES)}
    for k, cls in prev.items():
        if cls in keys:
            keys[cls].append(str(k))
    return _fp_from_keys(keys)


def alert_plan(current: dict, previous: dict) -> dict:
    """What to tell whom. Pure.

    immediate: a RETIRED_RAN or VECTOR_FAILING class whose hash is NEW or CHANGED
    (a class that empties is silent -- VECTOR_FAILING empties every UTC midnight);
    recovered: RETIRED_RAN was set and is now clear (a real repair, said once);
    digest: the OPEN_NO_ATTEMPT / REFUSED_NOWHERE count:hash changed and is non-empty.
    """
    imm_now, imm_prev = current["immediate"], previous["immediate"]
    changed = [c for c in IMMEDIATE_CLASSES if c in imm_now and imm_now[c] != imm_prev.get(c)]
    recovered = "RETIRED_RAN" in imm_prev and "RETIRED_RAN" not in imm_now
    dig_now, dig_prev = current["digest"], previous["digest"]
    digest = bool(dig_now) and dig_now != dig_prev
    return {"immediate": changed, "recovered": recovered, "digest": digest}


def intent_execution_id(run_id: str | None = None) -> str:
    """The run id in the comms-intent execution_id alphabet ([A-Za-z0-9_-], <= 40; the store refuses others). Pure."""
    import re as _re

    raw = run_id if run_id is not None else os.environ.get("TRADEAI_RUN_ID", "")
    safe = _re.sub(r"[^A-Za-z0-9_-]", "_", str(raw or ""))[-40:].strip("_")
    return safe or "host"


def _deliver_queue(body: str, *, priority: str, kind: str) -> bool:
    """n8n lane: QUEUE a host comms intent, never send (config/n8n_run_allowlist.json never-list; AGENTS.md §24.1).
    Raises on refusal so the state does not advance."""
    from scripts.lib.host_comms_intents import queue_intent

    head = body.split("\n", 1)[0]
    rest = " ".join(line.strip() for line in body.split("\n")[1:] if line.strip().startswith("•"))
    queue_intent(producer=INTENT_PRODUCER, domain=INTENT_DOMAIN, kind=kind, subject=head,
                 summary=rest or head, execution_id=intent_execution_id(), node=LANE_ID)
    return True


def _deliver_send(body: str, *, priority: str, kind: str) -> bool:
    """systemd unit: the host chokepoint (notification intent). Never reachable from the n8n entry (lane_main)."""
    from telegram_alert import send_telegram

    return bool(send_telegram(body, message_class="operator_alert", priority=priority, producer="check_gap_resolution"))


def _immediate_body(report: dict, classes: list[str], recovered: bool) -> str:
    f = report["findings"]
    if not classes and recovered:
        return f"{SENTINEL} ✅ Gap resolution: no retired provider ran since the last report."
    # The sentinel is what operator_alert_policy_v2 routes on. Without it this
    # would wait in the digest, and a retired provider running is not a digest item.
    head = f"{SENTINEL} 🚨 Gap resolution: "
    head += "a RETIRED provider RAN" if f["RETIRED_RAN"] else "vectors failing"
    lines = [head, ""]
    for r in f["RETIRED_RAN"]:
        lines.append(f"• [RETIRED_RAN] {r['vector']} ran {r['provider']} → {r['outcome']} ({r['started']})")
    for v in f["VECTOR_FAILING"]:
        lines.append(f"• [VECTOR_FAILING] {v['vector']}: {v['errors_today']} errors today")
    lines += ["", f"NEW or changed: {', '.join(classes)}" if classes else ""]
    lines += ["Receipts: data/cio/gap_resolution_receipts.jsonl · docs/GAP_RESOLUTION.md"]
    return "\n".join(x for x in lines if x is not None)


def _digest_body(report: dict) -> str:
    """No sentinel: this is digest material (P3), not an interrupt."""
    f = report["findings"]
    opened, refused = f["OPEN_NO_ATTEMPT"], f.get("REFUSED_NOWHERE", [])
    lines = [f"Gap resolution digest: {len(opened)} gap(s) open >{OPEN_HOURS:g}h with no attempt, "
             f"{len(refused)} search group(s) refused and asked nowhere", ""]
    for r in refused:
        lines.append(f"• [REFUSED_NOWHERE] {r['caller']}: {r['refused_in_window']} searches refused in {r['window_days']}d "
                     f"({r['reason']}) and asked of no other lane")
    for g in opened[:12]:
        lines.append(f"• [OPEN_NO_ATTEMPT] {g['domain']}:{g['subject']} open {g['age_hours']}h, no attempt ({g['origin']})")
    if len(opened) > 12:
        lines.append(f"  … and {len(opened) - 12} more")
    lines += ["", "Receipts: data/cio/gap_resolution_receipts.jsonl · docs/GAP_RESOLUTION.md"]
    return "\n".join(lines)


def _alert(report: dict, *, notify: str = "send") -> dict:
    """The systemd/CLI spelling: picks the channel by ``notify`` and runs :func:`_alert_core`."""
    return _alert_core(report, deliver=_deliver_queue if notify == "queue" else _deliver_send, channel=notify)


def _alert_core(report: dict, *, deliver, channel: str) -> dict:
    """Notify on CHANGE only, routed by class. Never raises.

    RETIRED_RAN / VECTOR_FAILING -> immediate (sentinel, P2); OPEN_NO_ATTEMPT /
    REFUSED_NOWHERE -> digest (P3, no sentinel). State advances only after every
    needed delivery was accepted, so a failed send is retried next run.
    """
    notify = channel
    fp = fingerprint(report)
    previous: dict = {}
    try:
        previous = json.loads(STATE_PATH.read_text()).get("fingerprint", {})
    except (OSError, ValueError, AttributeError):
        pass
    prev = _normalise_previous(previous)
    plan = alert_plan(fp, prev)
    out = {"plan": plan, "sent": [], "channel": notify}

    if not plan["immediate"] and not plan["recovered"] and not plan["digest"]:
        print("\n  alert: suppressed — no new immediate finding and no digest change"
              " (a VECTOR_FAILING set clearing at the UTC day boundary is not news).")
    try:
        if plan["immediate"] or plan["recovered"]:
            ok = deliver(_immediate_body(report, plan["immediate"], plan["recovered"]),
                         priority="P2", kind=INTENT_KIND_IMMEDIATE)
            out["sent"].append("immediate")
            print(f"\n  alert: immediate {'accepted' if ok else 'NOT accepted'} by the platform ({notify})")
        if plan["digest"]:
            ok = deliver(_digest_body(report), priority="P3", kind=INTENT_KIND_DIGEST)
            out["sent"].append("digest")
            print(f"  alert: digest {'accepted' if ok else 'NOT accepted'} ({notify})")
    except Exception as exc:
        print(f"\n  alert: FAILED to {notify} ({exc}). The findings above still stand.", file=sys.stderr)
        out["error"] = type(exc).__name__
        return out

    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({"fingerprint": fp}, indent=2))
    except OSError as exc:
        print(f"  alert: could not record state ({exc}).", file=sys.stderr)
    return out


def lane_output(report: dict | None, *, error: str | None = None) -> dict:
    """LaneRunReceipt@v2 output fields (unit: gap/receipt ledgers measured). Pure.

    produced = ledgers that held rows (receipts, gap queue, research gaps, search
    denials); no ledger at all is the allowed empty ``no_new_input``; a collect
    that raised is the fatal skip ``dependency_unavailable``.
    """
    if error or report is None:
        return {"produced_count": 0, "attempted_count": 0, "skipped_reasons": {SKIP_DEPENDENCY: 1},
                "empty_reason": None}
    sources = {k: int(report.get(k) or 0) for k in ("receipts", "queued_gaps", "research_gaps", "search_denials")}
    produced = sum(1 for v in sources.values() if v)
    skipped = {"ledger_empty": len(sources) - produced} if produced < len(sources) else {}
    return {"produced_count": produced, "attempted_count": len(sources), "skipped_reasons": skipped,
            "empty_reason": EMPTY_NO_INPUT if produced == 0 else None}


#: The LaneRunReceipt@v2 output fields of the last receipt this process wrote (the n8n entry prints them).
LAST_LANE_OUTPUT: dict = {}


def _write_lane_receipt(*, ok: bool, started_at: str, summary: dict, output: dict, error: str | None = None):
    LAST_LANE_OUTPUT.clear()
    LAST_LANE_OUTPUT.update(output)
    from scripts.lib import lane_last_receipt as lr

    return lr.write_lane_receipt(LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=started_at,
                                 script="scripts/check_gap_resolution.py", summary=summary, error=error,
                                 output=output)


def _parser(lane: bool = False) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--alert", action="store_true", help="notify the operator when the finding-set changes")
    if not lane:
        ap.add_argument("--notify", choices=NOTIFY_MODES, default="send",
                        help="send = chokepoint send (systemd unit); queue = host comms intents (no sender)")
        ap.add_argument("--lane-receipt", action="store_true",
                        help=f"write the LaneRunReceipt@v2 for lane {LANE_ID}; exit 0 when the run completed")
    ap.add_argument("--dry-run", action="store_true",
                    help="collect and print; write no receipt and no alert state, notify nobody")
    return ap


def main(argv: list[str] | None = None, *, collect_fn=None) -> int:
    """systemd unit / operator CLI. ``--notify send`` (default) uses the chokepoint; ``queue`` host intents."""
    args = _parser().parse_args(argv)
    return _run(args, collect_fn=collect_fn, deliver=_deliver_queue if args.notify == "queue" else _deliver_send)


def lane_main(argv: list[str] | None = None, *, collect_fn=None) -> int:
    """n8n lane n8n-gap-resolution-audit (entry scripts/n8n_gap_resolution_audit.py).

    Always writes the LaneRunReceipt@v2 (unless --dry-run) and, with --alert, QUEUES host comms intents. It never
    references the chokepoint send (dispatcher sender gate, scripts/lib/advisory_lane_guard.py).
    """
    args = _parser(lane=True).parse_args(argv)
    args.notify, args.lane_receipt = "queue", not args.dry_run
    return _run(args, collect_fn=collect_fn, deliver=_deliver_queue)


def _run(args, *, collect_fn=None, deliver) -> int:
    if args.dry_run and (args.alert or args.lane_receipt):
        print("ERROR: --dry-run writes nothing; it cannot be combined with --alert or --lane-receipt", file=sys.stderr)
        return 2
    started_at = datetime.now(timezone.utc).isoformat()

    try:
        report = (collect_fn or collect)()
    except Exception as exc:  # noqa: BLE001 -- cannot-run is exit 2, never a green 0
        print(f"ERROR: could not collect: {type(exc).__name__}: {exc}", file=sys.stderr)
        if args.lane_receipt:
            _write_lane_receipt(ok=False, started_at=started_at, summary={"error": type(exc).__name__},
                                output=lane_output(None, error=type(exc).__name__), error=type(exc).__name__)
            return 1
        return 2

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        f = report["findings"]
        print("Gap resolution — is anything trying to close the gaps?")
        print("=" * 74)
        print(f"  receipts={report.get('receipts', 0)}  queued_gaps={report.get('queued_gaps', 0)}  "
              f"research_gaps={report.get('research_gaps', 0)}  search_denials={report.get('search_denials', 0)}")
        for r in f["RETIRED_RAN"]:
            print(f"  [RETIRED_RAN     ] {r['vector']} ran {r['provider']} → {r['outcome']}")
        for r in f.get("REFUSED_NOWHERE", []):
            print(f"  [REFUSED_NOWHERE ] {r['caller']}: {r['refused_in_window']} refused in {r['window_days']}d ({r['reason']})")
        for v in f["VECTOR_FAILING"]:
            print(f"  [VECTOR_FAILING  ] {v['vector']}: {v['errors_today']} errors today")
        for g in f["OPEN_NO_ATTEMPT"]:
            print(f"  [OPEN_NO_ATTEMPT ] {g['domain']}:{g['subject']} open {g['age_hours']}h ({g['origin']})")
        if not report["finding_count"]:
            print("  nothing to report.")
        print("-" * 74)
        print(f"  findings={report['finding_count']}")

    if args.dry_run:
        print(f"\n  DRY RUN — nothing written; fingerprint would be {json.dumps(fingerprint(report), sort_keys=True)}")
        return 1 if report["finding_count"] else 0

    _write_run_receipt(report)
    alert = _alert_core(report, deliver=deliver, channel=args.notify) if args.alert else None
    if args.lane_receipt:
        f = report["findings"]
        summary = {k: len(f.get(k, [])) for k in (*IMMEDIATE_CLASSES, *DIGEST_CLASSES)}
        summary.update({"finding_count": report["finding_count"], "notify": args.notify if args.alert else None,
                        "alert_sent": (alert or {}).get("sent")})
        ok = not (alert and alert.get("error"))
        _write_lane_receipt(ok=ok, started_at=started_at, summary=summary, output=lane_output(report),
                            error=None if ok else "alert_delivery_failed")
        return 0 if ok else 1
    return 1 if report["finding_count"] else 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
