"""needs_action.py — GET /api/v2/needs-action: one inbox of what needs the operator (audit 2026-10-21).

An audit found failures that were real but sat on pages the operator does not open (telegram_outbox failures only
in Coordination → Events outbox, the overnight LLM queue on no page, data plausibility with no API, pipeline_runs
failures behind 100 finviz successes). This module asks every source independently and returns one list.

Item shape: ``{severity: P0..P3, title, why, where (CC route), source, since, evidence}``.

Invariants (tests: tests/test_cc_needs_action_20261021.py):
* every source is probed on its own worker with a timeout; a probe that raises, times out or answers
  UNAVAILABLE becomes ONE item "source X unavailable" — a source is never silently dropped;
* ``all_sources_answered`` is true only when every source answered; the page shows "Nothing needs action"
  only then;
* ``rule_*`` functions are pure (payload → items) so each rule is tested without a database.

AUTHORITY: READ_ONLY_ADVISORY. Nothing here writes, sends, restarts or approves.
"""
from __future__ import annotations

import collections
import concurrent.futures as cf
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

SCHEMA = "NeedsAction@v1"
SEVERITIES = ("P0", "P1", "P2", "P3")
DEFAULT_TIMEOUT_S = 5.0

# Overnight LLM queue thresholds — mirrored in apps/command-center-v3/src/lib/overnightQueueHealth.ts.
QUEUE_WARN = {"pending": 500, "failed": 50, "nights": 3.0}
QUEUE_CRIT = {"pending": 1500, "failed": 200, "nights": 7.0}

HEALTH_STALE_H = 3.0
COMMS_STUCK_S = 15 * 60
N8N_WORKFLOW_ERRORS_MIN = 3
DATA_SOURCE_ITEMS_MAX = 8
FAILED_RUN_STATES = ("RUN_FAILED", "RUN_TIMEOUT", "RUN_REFUSED")

R_SYSTEM_JOBS = "/v3/system?tab=Jobs"
R_SYSTEM_PIPELINE = "/v3/system?tab=Pipeline"
R_SYSTEM_DATA = "/v3/system?tab=Data%20Sources"
R_COMMS = "/v3/communications"
R_COORD = "/v3/coordination"
R_HEALTH = "/v3/health"
R_PR_HYGIENE = R_COORD

# PR hygiene (2026-10-21, operator process plan): the lane pr-hygiene-audit (scripts/pr_hygiene_audit.py, n8n
# dispatcher daily 06:30) writes its LaneRunReceipt; this source only reads it.
PR_HYGIENE_LANE = "pr-hygiene-audit"
PR_HYGIENE_STALE_H = 36.0
PR_HYGIENE_ITEMS_MAX = 12
PR_HYGIENE_TITLES = {"CONFLICT": "conflicts with main", "SUPERSEDED": "looks superseded", "DUPLICATE": "duplicate work",
                     "STACKED": "stacked on a moved base", "STALE_HOLD": "stale hold"}


class SourceUnavailable(Exception):
    """A probe answered, but the answer says the source could not be measured."""


def item(severity: str, title: str, why: str, where: str, source: str, since: Optional[str] = None,
         evidence: Any = None) -> dict[str, Any]:
    assert severity in SEVERITIES, severity
    return {"severity": severity, "title": title, "why": why, "where": where, "source": source,
            "since": since, "evidence": evidence}


def _parse(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _unwrap(payload: Any) -> Any:
    """Accept either the bare model or an API envelope {ok, data}."""
    if isinstance(payload, dict) and "data" in payload and isinstance(payload.get("data"), dict) and "ok" in payload:
        return payload["data"]
    return payload


# ── rules (pure) ───────────────────────────────────────────────────────────────────────────────────────────────


def rule_health(p: Any, now: datetime) -> list[dict]:
    p = _unwrap(p)
    if not isinstance(p, dict) or not isinstance(p.get("findings"), list):
        raise SourceUnavailable("health agent snapshot has no findings list")
    out = []
    cap = _parse(p.get("captured_at"))
    if cap is None:
        raise SourceUnavailable("health agent snapshot has no captured_at")
    age_h = (now - cap).total_seconds() / 3600.0
    if age_h > HEALTH_STALE_H:
        out.append(item("P2", f"Health agent snapshot is {age_h:.1f} h old",
                        f"The health agent has not scored the system for more than {HEALTH_STALE_H:g} h; its findings may be out of date.",
                        R_HEALTH, "health", cap.isoformat(), {"captured_at": cap.isoformat()}))
    for f in p["findings"]:
        if not isinstance(f, dict) or str(f.get("severity") or "").lower() != "critical":
            continue
        cat = str(f.get("category") or "")
        sev = "P0" if cat in ("risk_protection",) else "P1"
        where = ((f.get("cta") or {}).get("route") if isinstance(f.get("cta"), dict) else None) or R_HEALTH
        if where.startswith("/") and not where.startswith("/v3"):
            where = "/v3" + where
        out.append(item(sev, str(f.get("message") or f.get("type") or "critical finding")[:160],
                        str(f.get("recommended_action") or f.get("why") or "Health agent critical finding")[:240],
                        where, "health", f.get("detected_at") or cap.isoformat(),
                        {"type": f.get("type"), "category": cat}))
    return out


def rule_systemd(p: Any, now: datetime) -> list[dict]:
    """p = {"failed_units": [{"unit", "load", "active", "sub", "description"}]} from the read-only systemctl list."""
    if not isinstance(p, dict) or not isinstance(p.get("failed_units"), list):
        raise SourceUnavailable("systemctl failed-unit list unavailable")
    return [item("P1", f"systemd unit {u.get('unit')} is failed",
                 f"{u.get('description') or u.get('unit')} — its scheduled work is not running until it is reset or fixed.",
                 R_SYSTEM_JOBS, "systemd", None, {"unit": u.get("unit"), "sub": u.get("sub")})
            for u in p["failed_units"] if isinstance(u, dict) and u.get("unit")]


def rule_n8n(p: Any, now: datetime) -> list[dict]:
    p = _unwrap(p)
    if not isinstance(p, dict) or p.get("status") in (None, "UNAVAILABLE"):
        raise SourceUnavailable(f"n8n-today projection {(p or {}).get('status') if isinstance(p, dict) else 'missing'}")
    out = []
    states = p.get("live_lane_states")
    fails_by_lane: dict[str, list] = collections.defaultdict(list)
    for f in p.get("failures") or []:
        if isinstance(f, dict) and f.get("mode") == "live":
            fails_by_lane[str(f.get("lane"))].append(f)
    if isinstance(states, dict):
        for lane, st in sorted(states.items()):
            st = st or {}
            failed = sum(int(st.get(s) or 0) for s in FAILED_RUN_STATES)
            done = int(st.get("RUN_DONE") or 0)
            if failed and not done:
                last = (fails_by_lane.get(lane) or [{}])[0]
                out.append(item("P1", f"n8n lane {lane}: every live run failed today ({failed}/{failed})",
                                f"No live run of {lane} succeeded today; last reason {last.get('reason') or 'unknown'}.",
                                R_COORD, "n8n", last.get("finished_at"),
                                {"states": st, "last_run_id": last.get("run_id"), "receipt": last.get("evidence")}))
    else:
        # Older projection without per-lane states: name the failures, never claim "every run".
        for lane, fl in sorted(fails_by_lane.items()):
            out.append(item("P2", f"n8n lane {lane}: {len(fl)} live run(s) failed today",
                            f"last reason {fl[0].get('reason') or 'unknown'}", R_COORD, "n8n", fl[0].get("finished_at"),
                            {"last_run_id": fl[0].get("run_id")}))
    errs = ((p.get("relay") or {}).get("workflow_errors")) or []
    by_wf: dict[str, list] = collections.defaultdict(list)
    for e in errs:
        if isinstance(e, dict) and not e.get("duplicate"):
            by_wf[str(e.get("workflow_id") or "?")].append(e)
    for wf, es in sorted(by_wf.items()):
        if len(es) >= N8N_WORKFLOW_ERRORS_MIN:
            last = max(es, key=lambda e: str(e.get("at") or ""))
            out.append(item("P2", f"n8n workflow {wf} errored {len(es)} times today",
                            f"Relay recorded workflow errors at node {last.get('node') or '?'}; see the n8n execution.",
                            R_COORD, "n8n", last.get("at"),
                            {"count": len(es), "last_execution_id": last.get("execution_id")}))
    return out


def rule_approvals(p: Any, now: datetime) -> list[dict]:
    p = _unwrap(p)
    if not isinstance(p, dict) or p.get("status") in (None, "UNAVAILABLE") or not isinstance(p.get("items"), list):
        raise SourceUnavailable(f"approval board {(p or {}).get('status') if isinstance(p, dict) else 'missing'}")
    out = []
    expiring = {(r.get("kind"), r.get("id")) for r in (p.get("expiring") or []) if isinstance(r, dict)}
    for r in p["items"]:
        if not isinstance(r, dict):
            continue
        kind, rid, state = r.get("kind"), r.get("id"), r.get("state")
        ttl = r.get("ttl_min_left")
        ev = {"kind": kind, "id": rid, "scope": r.get("scope"), "state": state, "ttl_min_left": ttl}
        if (kind, rid) in expiring:
            out.append(item("P1", f"{kind} {r.get('scope') or rid} expires in {ttl} min",
                            "An open approval or active grant is about to lapse; renew or let it expire deliberately.",
                            R_COORD, "approvals", r.get("expires_at"), ev))
        elif kind == "package" and state == "OPEN":
            out.append(item("P2", f"Approval package awaiting decision: {r.get('scope') or rid}",
                            f"{r.get('items_pending') or 0} item(s) pending operator decision.",
                            R_COORD, "approvals", r.get("created_at"), ev))
        elif state == "EXPIRED":
            exp = _parse(r.get("expires_at"))
            if exp is not None and timedelta(0) <= now - exp <= timedelta(hours=24):
                out.append(item("P3", f"{kind} {r.get('scope') or rid} expired", "Expired in the last 24 h.",
                                R_COORD, "approvals", exp.isoformat(), ev))
    srcs = p.get("sources") or {}
    for name, s in srcs.items() if isinstance(srcs, dict) else []:
        if isinstance(s, dict) and s.get("status") not in (None, "OK"):
            out.append(item("P2", f"approval board source {name} unavailable", str(s.get("error") or s.get("status")),
                            R_COORD, "approvals", None, s))
    return out


def queue_level(q: dict) -> str:
    pending, failed = int(q.get("pending") or 0), int(q.get("failed") or 0)
    nights = float(q.get("estimated_completion_nights") or 0)
    if pending >= QUEUE_CRIT["pending"] or failed >= QUEUE_CRIT["failed"] or nights >= QUEUE_CRIT["nights"]:
        return "CRIT"
    if pending >= QUEUE_WARN["pending"] or failed >= QUEUE_WARN["failed"] or nights >= QUEUE_WARN["nights"]:
        return "WARN"
    return "OK"


def rule_queue(p: Any, now: datetime) -> list[dict]:
    q = _unwrap(p)
    if not isinstance(q, dict) or q.get("measured") is False or "pending" not in q:
        raise SourceUnavailable("deep_overnight_llm_queue could not be read")
    lvl = queue_level(q)
    if lvl == "OK":
        return []
    return [item("P1" if lvl == "CRIT" else "P2",
                 f"Overnight LLM queue {lvl}: {q.get('pending')} pending, {q.get('failed')} failed",
                 f"{q.get('done_today')} done in 24 h; at {q.get('cap_tonight')}/night the backlog takes "
                 f"{q.get('estimated_completion_nights')} nights to drain.",
                 R_SYSTEM_JOBS, "queue", None,
                 {k: q.get(k) for k in ("pending", "failed", "done_today", "cap_tonight", "estimated_completion_nights")})]


def rule_plausibility(p: Any, now: datetime) -> list[dict]:
    v = _unwrap(p)
    if not isinstance(v, dict) or v.get("status") in (None, "UNAVAILABLE", "NO_RECEIPT"):
        raise SourceUnavailable(str((v or {}).get("note") if isinstance(v, dict) else "no view"))
    out = []
    if v["status"] == "STALE":
        out.append(item("P2", "Data plausibility monitor has not run recently", str(v.get("note") or ""),
                        R_SYSTEM_DATA, "data_plausibility", v.get("ran_at"), {"age_h": v.get("age_h")}))
    for name in v.get("blocking_items") or []:
        out.append(item("P1", f"Implausible data: {name}",
                        "A BLOCK rule found values that cannot be valid on the declared scale; the data or the contract is wrong.",
                        R_SYSTEM_DATA, "data_plausibility", v.get("ran_at"), {"rule": name}))
    return out


def rule_data_sources(p: Any, now: datetime) -> list[dict]:
    d = _unwrap(p)
    if not isinstance(d, dict) or not isinstance(d.get("sources"), list):
        raise SourceUnavailable("data-source-health has no sources list")
    bad = [s for s in d["sources"] if isinstance(s, dict) and str(s.get("status") or "").lower() in ("dead", "error")]
    out = []
    for s in bad[:DATA_SOURCE_ITEMS_MAX]:
        out.append(item("P2", f"Data source {s.get('source')} is {s.get('status')}",
                        str(s.get("last_error") or f"no update for {s.get('age_hours')} h (expected every {s.get('expected_fresh_h')} h)")[:240],
                        R_SYSTEM_DATA, "data_sources", s.get("last_update"),
                        {"category": s.get("category"), "age_hours": s.get("age_hours")}))
    if len(bad) > DATA_SOURCE_ITEMS_MAX:
        out.append(item("P2", f"{len(bad) - DATA_SOURCE_ITEMS_MAX} more data sources dead or in error",
                        "See the Data Sources tab for the full list.", R_SYSTEM_DATA, "data_sources", None,
                        {"total_bad": len(bad)}))
    return out


def rule_comms(p: Any, now: datetime) -> list[dict]:
    s = _unwrap(p)
    if not isinstance(s, dict) or s.get("status") != "OK":
        raise SourceUnavailable(str((s or {}).get("error") or "delivery summary unavailable") if isinstance(s, dict) else "no summary")
    out = []
    if int(s.get("failed") or 0) > 0:
        out.append(item("P2", f"{s['failed']} communication deliveries failed",
                        "communication_deliveries rows FAILED/BOUNCED/EXPIRED (not reaped copies).", R_COMMS, "comms",
                        None, {"failed": s.get("failed")}))
    age = s.get("oldest_unsettled_age_s")
    if int(s.get("unsettled") or 0) > 0 and isinstance(age, (int, float)) and age > COMMS_STUCK_S:
        out.append(item("P1", f"{s['unsettled']} deliveries stuck un-settled (oldest {int(age // 60)} min)",
                        "Reserved or sending deliveries nobody has settled.", R_COMMS, "comms",
                        s.get("oldest_unsettled_at"), {"unsettled": s.get("unsettled")}))
    tg = s.get("telegram_outbox_failed_24h")
    if tg is None:
        out.append(item("P2", "source comms/telegram_outbox unavailable",
                        str(s.get("telegram_outbox_error") or "telegram_outbox failures were not measured"), R_COMMS,
                        "comms", None, None))
    elif tg > 0:
        out.append(item("P2", f"{tg} Telegram sends failed in 24 h",
                        "telegram_outbox ok=false outside the reports archive: " +
                        ", ".join(f"{k} {n}" for k, n in sorted((s.get("telegram_outbox_failed_24h_by_channel") or {}).items())),
                        R_COMMS, "comms", None, {"by_channel": s.get("telegram_outbox_failed_24h_by_channel")}))
    return out


def rule_pipelines(p: Any, now: datetime) -> list[dict]:
    d = _unwrap(p)
    if not isinstance(d, dict) or d.get("status") != "OK" or not isinstance(d.get("pipelines"), list):
        raise SourceUnavailable(str((d or {}).get("note") or "pipeline failures unavailable") if isinstance(d, dict) else "no data")
    return [item("P2", f"Pipeline {r['pipeline']} failed {r['failed']}x in {d.get('window_hours', 24)} h",
                 (f"{r['zombie_cleared']} were runs that never finished (zombie cleared). " if r.get("zombie_cleared") else "")
                 + str(r.get("last_error") or "no error text recorded")[:240], R_SYSTEM_PIPELINE, "pipelines",
                 r.get("last_failed_at"), {"failed": r["failed"], "zombie_cleared": r.get("zombie_cleared")})
            for r in d["pipelines"]]


def rule_pr_hygiene(p: Any, now: datetime) -> list[dict]:
    """p = the pr-hygiene-audit LaneRunReceipt (or {"status": "NO_RECEIPT"} from :func:`probe_pr_hygiene`).

    CONFLICT / SUPERSEDED / DUPLICATE -> P2, STACKED / STALE_HOLD -> P3 (one item each for the first
    PR_HYGIENE_ITEMS_MAX, then one rollup); local unpushed branches -> one P3 rollup. Each item's evidence carries the
    PR url. No receipt yet -> one P3 (at shadow the lane runs dry and writes nothing); failed or stale -> P2."""
    if not isinstance(p, dict):
        raise SourceUnavailable("pr hygiene receipt is not an object")
    if p.get("status") == "NO_RECEIPT":
        return [item("P3", "PR hygiene audit has no receipt yet",
                     "The pr-hygiene-audit lane has not completed a real run (at shadow it runs dry and writes nothing); "
                     "run `python3 scripts/pr_hygiene_audit.py --report` for a read-only view.",
                     R_PR_HYGIENE, "pr_hygiene", None, {"receipt": p.get("path")})]
    if p.get("lane_id") != PR_HYGIENE_LANE:
        raise SourceUnavailable("pr hygiene receipt names another lane")
    out: list[dict] = []
    if p.get("status") != "ok":
        out.append(item("P2", "PR hygiene audit failed", str(p.get("error") or "the last run failed")[:240],
                        R_PR_HYGIENE, "pr_hygiene", p.get("finished_at"), {"ok_at": p.get("ok_at")}))
    ok_at = _parse(p.get("ok_at"))
    if ok_at is None or (now - ok_at).total_seconds() / 3600.0 > PR_HYGIENE_STALE_H:
        age = "never" if ok_at is None else f"{(now - ok_at).total_seconds() / 3600.0:.0f} h ago"
        out.append(item("P2", f"PR hygiene audit is stale (last ok {age})",
                        f"The daily audit has not completed for more than {PR_HYGIENE_STALE_H:g} h; PR findings may be out of date.",
                        R_PR_HYGIENE, "pr_hygiene", p.get("ok_at"), {"ok_at": p.get("ok_at")}))
    summary = p.get("summary") if isinstance(p.get("summary"), dict) else {}
    since = summary.get("as_of") or p.get("finished_at")
    findings = [f for f in summary.get("findings") or [] if isinstance(f, dict)]
    prs = [f for f in findings if f.get("kind") in PR_HYGIENE_TITLES]
    p2 = ("CONFLICT", "SUPERSEDED", "DUPLICATE")
    prs.sort(key=lambda f: (f.get("kind") not in p2, str(f.get("kind")), str(f.get("key"))))
    for f in prs[:PR_HYGIENE_ITEMS_MAX]:
        conf = f" (confidence {f['confidence']})" if f.get("confidence") else ""
        out.append(item("P2" if f.get("kind") in p2 else "P3", str(f.get("title") or f.get("key"))[:160],
                        f"PR hygiene: {PR_HYGIENE_TITLES[f['kind']]}{conf}. Open the PR and merge, rebase, close or "
                        "release the hold; the audit never acts on a PR.",
                        R_PR_HYGIENE, "pr_hygiene", since,
                        {"url": f.get("url"), "prs": f.get("prs"), "kind": f.get("kind"), "key": f.get("key")}))
    if len(prs) > PR_HYGIENE_ITEMS_MAX:
        out.append(item("P2", f"{len(prs) - PR_HYGIENE_ITEMS_MAX} more PR hygiene findings",
                        "See the pr-hygiene-audit receipt (summary.findings) for the full list.", R_PR_HYGIENE,
                        "pr_hygiene", since, {"total": len(prs)}))
    unpushed = [f for f in findings if f.get("kind") == "UNPUSHED"]
    if unpushed:
        names = ", ".join(str((f.get("detail") or {}).get("branch")) for f in unpushed[:5])
        out.append(item("P3", f"{len(unpushed)} local branch(es) hold commits on no remote",
                        f"Unpushed agent work: {names}{' …' if len(unpushed) > 5 else ''}. Push it on purpose or archive it.",
                        R_PR_HYGIENE, "pr_hygiene", since, {"branches": len(unpushed)}))
    return out


def probe_pr_hygiene(path: Any = None) -> dict:
    """Read the pr-hygiene-audit receipt (read-only). Missing -> {"status": "NO_RECEIPT"}; unreadable -> raises."""
    import json
    from pathlib import Path

    if path is None:
        try:
            from lib.lane_last_receipt import receipt_path
        except ImportError:  # pragma: no cover - repo root on sys.path instead of scripts/
            from scripts.lib.lane_last_receipt import receipt_path  # type: ignore[no-redef]
        path = receipt_path(PR_HYGIENE_LANE)
    p = Path(path)
    if not p.exists():
        return {"status": "NO_RECEIPT", "path": str(p)}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceUnavailable(f"pr hygiene receipt unreadable: {type(exc).__name__}") from exc
    if not isinstance(doc, dict):
        raise SourceUnavailable("pr hygiene receipt is not an object")
    return doc


RELEASE_WINDOW_RECENT_H = 36.0
# Mirrors scripts/release_window.py ALERT_PRIORITY (a failed window; routine stops are not items).
RELEASE_WINDOW_SEVERITY = {"ROLLBACK_FAILED": "P0", "ROLLED_BACK": "P1", "STOP_PREPARE_FAILED": "P1",
                           "STOP_CI_NOT_GREEN": "P2", "STOP_MAIN_MOVED": "P2"}


def read_release_window_state(root: Any = None) -> dict:
    """The release-window runner's STOP latch and last receipt (scripts/release_window.py; release train
    2026-10-21). A runner that never ran has neither file: that is an empty state, not an unavailable source."""
    import json
    import os
    from pathlib import Path

    if root is None:
        state_root = os.environ.get("TRADEAI_STATE_ROOT",
                                    str(Path.home() / "trade-ai-releases" / "persistent-state"))
        root = os.environ.get("TRADEAI_RELEASE_WINDOW_STATE_DIR",
                              str(Path(state_root) / "data" / "runtime" / "release_window"))
    root = Path(root)
    out: dict[str, Any] = {"latch": None, "last": None}
    latch = root / "STOP.json"
    if os.path.lexists(latch):
        # Present but unreadable is a STOP (the runner refuses REFUSED_STOP_UNREADABLE), never "no latch".
        try:
            body = json.loads(latch.read_text(encoding="utf-8"))
            out["latch"] = body if isinstance(body, dict) else {"unreadable": f"not an object: {type(body).__name__}"}
        except (OSError, ValueError) as exc:
            out["latch"] = {"unreadable": f"{type(exc).__name__}: {str(exc)[:160]}"}
    last = root / "last.json"
    if last.exists():
        out["last"] = json.loads(last.read_text(encoding="utf-8"))     # unreadable -> raises -> source unavailable
    return out


def rule_release_window(p: Any, now: datetime) -> list[dict]:
    p = p or {}
    items: list[dict] = []
    latch = p.get("latch")
    if isinstance(latch, dict) and "unreadable" in latch:
        items.append(item("P1", "Release windows halted: STOP latch unreadable",
                          f"STOP.json exists but cannot be read ({latch['unreadable']}); every window refuses "
                          "(REFUSED_STOP_UNREADABLE) until the operator inspects it and runs clear-stop",
                          R_SYSTEM_JOBS, "release_window", None, latch))
    elif isinstance(latch, dict):
        items.append(item("P1", "Release windows halted: STOP latched",
                          f"window {latch.get('window_id')} ended {latch.get('outcome')} for candidate "
                          f"{str(latch.get('candidate') or '')[:9]}; every later window refuses until the operator "
                          "reviews the receipt and runs scripts/release_window.py clear-stop",
                          R_SYSTEM_JOBS, "release_window", latch.get("latched_at"), latch))
    last = p.get("last")
    if isinstance(last, dict):
        sev = RELEASE_WINDOW_SEVERITY.get(str(last.get("outcome")))
        at = _parse(last.get("finished_at") or last.get("started_at"))
        if sev and at and now - at <= timedelta(hours=RELEASE_WINDOW_RECENT_H):
            cand = last.get("candidate") or {}
            items.append(item(sev, f"Release window {last.get('window_id')} {last.get('outcome')}",
                              f"candidate {str(cand.get('sha') or '')[:9]} ({cand.get('selected_by') or '?'}); "
                              "the next window retries unless STOP is latched",
                              R_SYSTEM_JOBS, "release_window", at.isoformat(),
                              {"window_id": last.get("window_id"), "outcome": last.get("outcome")}))
    return items


# Macro calendar (operator ruling 2026-10-21: FRED + a yearly overrides file, lane macro-calendar-refresh). The release
# train skips its 08:00 ET window when the calendar is missing, corrupt, stale (> 72 h) or does not cover the day
# (scripts/lib/macro_calendar.py, fail closed); this source says so. An 08:30 release day is an expected skip, no item.
MACRO_CALENDAR_LANE = "macro-calendar-refresh"


def next_0800_day(now: datetime) -> Any:
    """The ET date of the next 08:00 ET window at or after ``now`` (weekdays; after 08:00 ET it is the next one)."""
    from zoneinfo import ZoneInfo

    et = now.astimezone(ZoneInfo("America/New_York"))
    d = et.date() if et.hour < 8 else et.date() + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def probe_macro_calendar(path: Any = None, now: Optional[datetime] = None) -> dict:
    """The macro calendar's verdict for the next 08:00 ET window (read-only, no network). Never raises on a bad file:
    a missing / corrupt / stale calendar is the finding, returned as its verdict."""
    try:
        from lib.macro_calendar import verdict
    except ImportError:  # pragma: no cover - repo root on sys.path instead of scripts/
        from scripts.lib.macro_calendar import verdict  # type: ignore[no-redef]
    now = now or datetime.now(timezone.utc)
    day = next_0800_day(now)
    v, why = verdict(day, now, path=path)
    return {"day": day.isoformat(), "verdict": v, "reason": why}


def rule_macro_calendar(p: Any, now: datetime) -> list[dict]:
    """STALE / UNAVAILABLE -> one P2 "08:00 release window skipped: calendar stale|missing"; CLEAR / MACRO_DAY -> none."""
    if not isinstance(p, dict) or "verdict" not in p:
        raise SourceUnavailable("macro calendar probe answered no verdict")
    v = p.get("verdict")
    if v in ("CLEAR", "MACRO_DAY"):
        return []
    what = "stale" if v == "STALE" else "missing"
    return [item("P2", f"08:00 release window skipped: calendar {what}",
                 f"{p.get('reason')}. The release train fails closed and skips the 08:00 ET window on {p.get('day')} "
                 f"until the {MACRO_CALENDAR_LANE} lane writes a fresh calendar "
                 "(python3 scripts/macro_calendar_refresh.py --dry-run shows what it would write).",
                 R_SYSTEM_JOBS, "macro_calendar", None,
                 {"day": p.get("day"), "verdict": v, "lane": MACRO_CALENDAR_LANE})]


RULES: dict[str, Callable[[Any, datetime], list[dict]]] = {
    "health": rule_health, "systemd": rule_systemd, "n8n": rule_n8n, "approvals": rule_approvals,
    "queue": rule_queue, "data_plausibility": rule_plausibility, "data_sources": rule_data_sources,
    "comms": rule_comms, "pipelines": rule_pipelines, "pr_hygiene": rule_pr_hygiene,
    "release_window": rule_release_window, "macro_calendar": rule_macro_calendar,
}

_EXECUTOR: Optional[cf.ThreadPoolExecutor] = None


def _executor() -> cf.ThreadPoolExecutor:
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = cf.ThreadPoolExecutor(max_workers=16, thread_name_prefix="needs-action")
    return _EXECUTOR


def aggregate(probes: dict[str, Callable[[], Any]], *, now: Optional[datetime] = None,
              timeout_s: float = DEFAULT_TIMEOUT_S, rules: Optional[dict] = None,
              executor: Optional[cf.Executor] = None) -> dict[str, Any]:
    """Run every probe concurrently (each with its own deadline), apply its rule, never drop a source."""
    now = now or datetime.now(timezone.utc)
    rules = rules or RULES
    ex = executor or _executor()
    started = time.monotonic()
    futures = {name: ex.submit(fn) for name, fn in probes.items()}
    items: list[dict] = []
    sources: dict[str, dict] = {}
    for name, fut in futures.items():
        remaining = max(0.0, timeout_s - (time.monotonic() - started))
        t0 = time.monotonic()
        err = None
        try:
            payload = fut.result(timeout=remaining)
            got = rules[name](payload, now)
            sources[name] = {"status": "OK", "items": len(got)}
            items.extend(got)
        except cf.TimeoutError:
            fut.cancel()
            err = f"timed out after {timeout_s:g} s"
        except SourceUnavailable as exc:
            err = str(exc)[:200] or "unavailable"
        except Exception as exc:  # noqa: BLE001 — the reason is the item
            err = f"{type(exc).__name__}: {str(exc)[:160]}"
        if err is not None:
            sources[name] = {"status": "UNAVAILABLE", "error": err}
            items.append(item("P2", f"source {name} unavailable",
                              f"Needs-action could not read this source, so anything it would report is unknown: {err}",
                              _source_where(name), name, now.isoformat(), {"error": err}))
        sources[name]["ms"] = int((time.monotonic() - t0) * 1000)
    order = {s: i for i, s in enumerate(SEVERITIES)}
    items.sort(key=lambda i: (order[i["severity"]], i["source"], i["title"]))
    counts = {s: sum(1 for i in items if i["severity"] == s) for s in SEVERITIES}
    answered = all(s["status"] == "OK" for s in sources.values())
    return {"schema": SCHEMA, "authority": "READ_ONLY_ADVISORY", "as_of": now.isoformat(), "status": "OK" if answered else "PARTIAL",
            "all_sources_answered": answered, "counts": counts, "total": len(items), "items": items,
            "sources": sources, "timeout_s": timeout_s}


def _source_where(name: str) -> str:
    return {"health": R_HEALTH, "systemd": R_SYSTEM_JOBS, "n8n": R_COORD, "approvals": R_COORD,
            "queue": R_SYSTEM_JOBS, "data_plausibility": R_SYSTEM_DATA, "data_sources": R_SYSTEM_DATA,
            "comms": R_COMMS, "pipelines": R_SYSTEM_PIPELINE, "pr_hygiene": R_PR_HYGIENE,
            "macro_calendar": R_SYSTEM_JOBS}.get(name, "/v3/system")


def parse_failed_units(text: str) -> list[dict]:
    """Parse `systemctl --user list-units --state=failed --plain --no-legend` lines. Pure."""
    out = []
    for line in (text or "").splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4 and parts[0].startswith("tradeai"):
            out.append({"unit": parts[0], "load": parts[1], "active": parts[2], "sub": parts[3],
                        "description": parts[4] if len(parts) > 4 else ""})
    return out


def probe_failed_units(run: Optional[Callable[..., Any]] = None) -> dict:
    """Read-only: list failed tradeai* user units. Raises when systemctl cannot answer."""
    import os
    import subprocess

    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    run = run or subprocess.run
    r = run(["systemctl", "--user", "list-units", "tradeai*", "--state=failed", "--plain", "--no-legend",
             "--no-pager"], capture_output=True, text=True, timeout=4, env=env)
    if r.returncode != 0:
        raise SourceUnavailable(f"systemctl exit {r.returncode}: {(r.stderr or '').strip()[:120]}")
    return {"failed_units": parse_failed_units(r.stdout)}
