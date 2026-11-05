"""Incident supervisor — one governed model call per open incident, allowlisted actions only (operator 2026-10-27).

Operator, 2026-10-27: "Could the LLM API monitor these processes if something goes wrong in terms of deployment,
that it will fix it automatically … or tell the agents what to do?"

For each unresolved IncidentRecord@v1 (oldest first, at most ``max_incidents_per_cycle``):

1. **Refused scope (deterministic, before any model):** a §0 class (orders/stops/sizing, broker writes, secrets) or a
   §28.14 item 4 scope (guard, policy, hooks, AGENTS.md, credentials) → ``needs_operator``. No model, no action.
2. **Attempts cap:** ``max_attempts_per_incident`` supervisor attempts → ``blocked`` with a handoff + one P1.
3. **Time box:** unresolved longer than ``escalate_after_minutes`` with no escalation yet → one P1.
4. **Model triage** (process ``incident_supervisor``: Anthropic credit, Sonnet 5.5 tier ``mid``, ≤ $1/day in the
   process registry; the governed walk falls back to OAuth grok/chatgpt; DeepSeek is not in ``allowed_lanes``, and an
   answer from any provider in ``never_providers`` is discarded). Output ``{class, action, params, rationale}``.
   * ``runbook`` → the harness runs the action ONLY if it is in config/incident_runbook_actions.json, enabled, applies
     to the incident's watcher and every param matches its regex.
   * ``code_defect`` → the §28.14 Claude Code fixer (scripts/self_heal_fixer.py) once per EPISODE (a ``reopen``
     starts a new episode; attempts before it are history); it opens a PR and never merges, releases or deploys.
   * ``needs_operator`` → ``blocked`` with the model's action as the handoff + one P1 through the chokepoint
     (scripts/telegram_alert.send_telegram) carrying the incident id.
   A fallback-provider answer is read-only triage: recorded, never executed.

A cycle budget (``cycle_budget_s``, default 7500s, under the unit's ``TimeoutStartSec=8100``) caps each
fixer dispatch at ``min(fixer timeout, remaining)`` and defers a dispatch when too little remains; the
incident stays unresolved and drains on a later cycle (never silently dropped). Escalation suppression is
per DELIVERED reason key per EPISODE, and a blocked incident whose latest page was not delivered is retried
(delivery only, no model and no dispatch) on a later cycle.

The supervisor never merges, pushes, promotes, deletes, orders, stops, sizes, writes a broker or reads a secret.
AUTHORITY: READ_ONLY_ADVISORY for every decision; the only side effects are the allowlisted argv, the fixer dispatch
and the P1. MBI_BEHAVIOR=0.
"""
from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

try:
    from scripts.lib import incidents as L
except ImportError:  # noqa: SIM105
    import incidents as L  # type: ignore[no-redef]

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
ACTOR = "incident_supervisor"
RECEIPT_SCHEMA = "IncidentSupervisorReceipt@v1"
CLASSES = ("runbook", "code_defect", "needs_operator")
ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "incident_runbook_actions.json"
CC_INCIDENT_URL = "https://ms01-openclaw.tail163d14.ts.net/v3/ops/incidents?detail={id}"

ModelCall = Callable[[str], tuple[str, str]]
Runner = Callable[[list, str, dict, float], tuple[int, str]]
#: ``notify(text, producer, priority="P1"|"P2")`` — the batch sends once per cycle (ONBOARDING §12 rule 3).
Notifier = Callable[..., bool]

#: The fixer states that prove it actually worked the job (scripts/lib/self_heal_fixer.py STATES).
#: ``fix_requested`` is only an admission, and ``fix_failed`` / ``fix_refused`` / ``fix_interrupted``
#: are terminal failures: none of them is proof, so they page a person instead of hiding the incident.
WORKING_OUTCOMES = frozenset({
    "fixing", "fix_attempting", "fix_ready_local", "fix_pr_opened", "fix_deployed",
    "output_recovered", "incident_resolved",
})

#: The supervisor unit runs ``TimeoutStartSec=8100``; ``max_incidents_per_cycle`` (5) x the fixer
#: timeout (7500s) could run for 37,500s and systemd would kill the cycle mid-fixer. The attempt row
#: is written only AFTER the fixer returns, so a kill loses the attempt. The cycle budget keeps the
#: whole cycle under the unit timeout and leaves the queue to drain on later cycles (2026-11-03).
CYCLE_BUDGET_DEFAULT_S = 7500.0
CYCLE_BUDGET_MARGIN_S = 300.0
CYCLE_BUDGET_FLOOR_S = 600.0

#: The governed model call in ``default_model(...)`` uses ``timeout=120``. The cycle budget is
#: re-checked against this before every model call, so the supervisor never starts a call it cannot
#: finish inside the unit's ``TimeoutStartSec=8100`` and lose the attempt row to a SIGKILL.
MODEL_TIMEOUT_DEFAULT_S = 120.0


@dataclass
class Deps:
    model: ModelCall
    run: Runner
    notify: Notifier
    fixer: Callable[..., dict]


# ---------------------------------------------------------------- defaults (side effects live here only)


def default_model(prompt: str) -> tuple[str, str]:
    try:
        from scripts.lib.governed_cloud_generation import generate_cloud
    except ImportError:
        from lib.governed_cloud_generation import generate_cloud  # type: ignore
    return generate_cloud(prompt, process_id="incident_supervisor", task_summary="incident triage",
                          timeout=120, max_tokens=700, response_json=True)


def default_run(argv: list, cwd: str, env: dict, timeout: float) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except UnicodeDecodeError as exc:  # a non-UTF8 byte in a tool's output must not crash the cycle
        return 127, f"{type(exc).__name__}: {exc}"
    except OSError as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return p.returncode, ((p.stdout or "") + ("\n" + p.stderr if p.stderr else ""))[-2000:]


def default_notify(text: str, producer: str, priority: str = "P2") -> bool:
    try:
        from scripts.telegram_alert import send_telegram
    except ImportError:
        from telegram_alert import send_telegram  # type: ignore
    return bool(send_telegram(text, priority=priority, dedupe_minutes=0, producer=producer))


# ---------------------------------------------------------------- pure decisions


def refused_scope(rec: Mapping[str, Any], policy: Mapping[str, Any]) -> Optional[str]:
    rx = re.compile(policy["refused_scope_regex"])
    src = rec.get("source") or {}
    hay = " ".join(str(x) for x in (rec.get("title"), rec.get("where"), src.get("job"), src.get("lane")))
    m = rx.search(hay)
    return m.group(0) if m else None


def supervisor_attempts(rec: Mapping[str, Any]) -> list[dict]:
    return [a for a in rec.get("attempts") or [] if a.get("actor") == ACTOR]


def current_attempts(rec: Mapping[str, Any]) -> list[dict]:
    """Attempts in the current EPISODE (2026-11-03).

    Causal rule: a ``reopen`` event starts a new episode; attempts/dispatch rows before it are history
    for the dispatch guard and for the attempt cap. Nothing is deleted — the old rows stay on the record.
    """
    rows = supervisor_attempts(rec)
    start = L.parse_ts(rec.get("reopened_at"))
    if start is None:
        return rows
    out = []
    for a in rows:
        t = L.parse_ts(a.get("at"))
        if t is not None and t >= start:
            out.append(a)
    return out


def counted_attempts(rec: Mapping[str, Any]) -> int:
    """Attempts that count toward the cap in THIS episode: executed actions and fixer dispatches."""
    return sum(1 for a in current_attempts(rec) if a.get("action") not in ("triage", "triage_readonly", "refused"))


def _is_budget_deferral(row: Mapping[str, Any]) -> bool:
    """A cycle-budget deferral row: nothing ran, so it must not start the model cooldown.

    The gate records a non-counting ``triage`` row (so the deferral is never lost) before it skips
    an incident. If that row advanced ``model_cooldown_minutes``, the incident would then be skipped
    for 30 minutes on the next cycle even though no model call and no action happened.
    """
    return (row.get("action") == "triage"
            and str(row.get("result") or "").startswith("deferred: cycle budget"))


def parse_verdict(text: str) -> Optional[dict]:
    s = str(text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?|```$", "", s).strip()
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        return None
    try:
        doc = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(doc, dict) or doc.get("class") not in CLASSES:
        return None
    params = doc.get("params") if isinstance(doc.get("params"), dict) else {}
    return {"class": doc["class"], "action": str(doc.get("action") or "")[:500],
            "params": {str(k): str(v)[:200] for k, v in params.items()},
            "rationale": str(doc.get("rationale") or "")[:1000]}


def validate_action(verdict: Mapping[str, Any], rec: Mapping[str, Any], cfg: Mapping[str, Any]) -> tuple[Optional[dict], str]:
    name = verdict.get("action")
    spec = (cfg.get("actions") or {}).get(name)
    if not spec:
        return None, f"action {name!r} not in the allowlist"
    if not spec.get("enabled"):
        return None, f"action {name!r} disabled: {spec.get('disabled_reason', '')}"[:200]
    watcher = (rec.get("source") or {}).get("watcher") or "*"
    applies = spec.get("applies_to") or []
    if "*" not in applies and watcher not in applies:
        return None, f"action {name!r} does not apply to watcher {watcher!r}"
    params = dict(verdict.get("params") or {})
    for p, rx in (spec.get("params") or {}).items():
        if not re.fullmatch(rx, params.get(p, "")):
            return None, f"param {p!r} fails {rx}"
    idle = (spec.get("precondition") or {}).get("dirty_paths_idle_minutes")
    if idle:
        why = _recently_touched(rec, cfg.get("canonical_repo", ""), float(idle))
        if why:
            return None, why
    extra = set(params) - set(spec.get("params") or {})
    if extra:
        params = {k: v for k, v in params.items() if k not in extra}
    return {"name": name, "spec": spec, "params": params}, "ok"


def _recently_touched(rec: Mapping[str, Any], repo: str, idle_min: float) -> Optional[str]:
    """Someone may still be working in the checkout: refuse while any listed dirty path changed recently."""
    import time
    cutoff = time.time() - idle_min * 60
    for e in rec.get("evidence") or []:
        kind, _, rel = str(e).partition(":")
        if kind != "path" or not rel:
            continue
        p = Path(repo) / rel.split(" -> ")[-1].strip().strip('"')
        try:
            if p.stat().st_mtime > cutoff:
                return f"dirty path {rel} changed within {int(idle_min)} min; a session may be working there"
        except OSError:
            continue
    return None


def render_argv(spec: Mapping[str, Any], params: Mapping[str, str], cfg: Mapping[str, Any]) -> list[str]:
    fill = {"python": cfg.get("python", "python3"), "canonical_repo": cfg.get("canonical_repo", ""), **params}
    return [re.sub(r"\{(\w+)\}", lambda m: str(fill[m.group(1)]) if m.group(1) in fill else m.group(0), a)
            for a in spec["argv"]]


def action_env(cfg: Mapping[str, Any], environ: Mapping[str, str]) -> dict:
    return {k: environ[k] for k in cfg.get("env_passthrough") or [] if k in environ}


def runbook_excerpt(rec: Mapping[str, Any], cfg: Mapping[str, Any], root: Path, limit: int = 1800) -> str:
    docs = cfg["policy"].get("runbook_docs") or {}
    watcher = (rec.get("source") or {}).get("watcher") or "*"
    out = []
    for rel in docs.get(watcher) or docs.get("*") or []:
        try:
            txt = (root / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        out.append(f"--- {rel} ---\n{txt[:limit]}")
    return "\n".join(out)


def evidence_excerpt(rec: Mapping[str, Any], state_root: Path, limit: int = 1500) -> str:
    out = []
    for e in (rec.get("evidence") or [])[:8]:
        e = str(e)
        kind, _, ref = e.partition(":")
        if kind in ("receipt", "store", "journal") and ref and ".." not in ref and not ref.startswith("/"):
            p = state_root / ref
            try:
                out.append(f"--- {ref} ---\n{p.read_text(encoding='utf-8', errors='replace')[-limit:]}")
                continue
            except OSError:
                pass
        out.append(e[:400])
    return "\n".join(out)


def build_prompt(rec: Mapping[str, Any], cfg: Mapping[str, Any], *, evidence: str, runbooks: str) -> str:
    acts = {k: {"description": v.get("description"), "applies_to": v.get("applies_to"), "params": v.get("params")}
            for k, v in (cfg.get("actions") or {}).items() if v.get("enabled")}
    slim = {k: rec.get(k) for k in ("id", "opened_at", "source", "title", "where", "status", "severity", "attempts",
                                     "notes", "recurrence_of")}
    return (
        "You are the Trade AI incident supervisor. Classify ONE incident and choose ONE next step.\n"
        "Rules (AGENTS.md §0): never orders, stops, sizing, broker writes, secrets, merges, pushes or promotions. "
        "You cannot run commands; you can only name an allowlisted action.\n"
        "Return ONLY JSON: {\"class\": \"runbook\"|\"code_defect\"|\"needs_operator\", \"action\": <for runbook: one "
        "allowlisted action id; otherwise one sentence telling a person or the fixer exactly what to do>, "
        "\"params\": {..}, \"rationale\": <two sentences citing the evidence>}.\n"
        "runbook = a listed action is likely to clear it; code_defect = a code bug a fix PR would solve (name the "
        "file/function if the evidence shows it); needs_operator = a decision, grant, credential or anything else.\n"
        "A runbook attempt that returned success but reported that it DID NOTHING (for example `acted: []`) is NOT "
        "a fix: if a code or config change would clear the incident, classify it code_defect and name the "
        "file/function; needs_operator is only for the operator-only classes above.\n"
        "Do not repeat an action already in attempts that failed.\n\n"
        f"INCIDENT:\n{json.dumps(slim, default=str)[:3000]}\n\nALLOWLISTED ACTIONS:\n{json.dumps(acts)}\n\n"
        f"EVIDENCE:\n{evidence[:5000]}\n\nRUNBOOKS:\n{runbooks[:4000]}\n"
    )



def _action_took_effect(spec, tail):
    """Did the runbook actually DO something? Recorded as evidence; the attempt cap still applies.

    ``cron_self_heal`` exits 0 with ``{"acted": []}`` for any lane it cannot manage. Recording that
    as a no-op is what lets the cap branch route it to the fixer instead of a person (2026-11-03).
    """
    contract = (spec or {}).get("success_when") or {}
    want = ((contract.get("json") or {}) if isinstance(contract, dict) else {}).get("acted")
    if not want:
        return True
    # None = cannot tell. An unparseable tail is NOT evidence that the runbook acted on nothing,
    # and must never route an incident to the fixer (2026-11-03).
    try:
        doc = json.loads(tail or "")
    except (TypeError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    acted = doc.get("acted")
    return len(acted) > 0 if isinstance(acted, list) else bool(acted)



def _last_action_was_noop(rec) -> bool:
    """The most recent runbook attempt in this episode reported that it acted on nothing."""
    rows = [a for a in current_attempts(rec)
            if str(a.get("action") or "") not in ("triage", "triage_readonly", "fixer_dispatch")]
    if not rows:
        return False
    last = max(rows, key=lambda a: str(a.get("at") or ""))
    # L.attempt() merges detail into the row, so production rows carry a top-level no_op.
    return bool(last.get("no_op", (last.get("detail") or {}).get("no_op")))


def disk_incident_route(rec: Mapping[str, Any], cfg: Mapping[str, Any]) -> Optional[dict]:
    """Which configured disk lane this incident came from, or None.

    Matched EXACTLY (case-insensitive) against the structured source fields — job, lane, watcher — never the free-text
    title, so an incident that merely mentions a disk is not swept in. Operator 2026-11-03 (disk permanent-fix item 4):
    a disk incident is never parked as needs_operator; the fixer lane owns it.
    """
    route = ((cfg.get("policy") or {}).get("disk_incident_routes")) or {}
    if not isinstance(route, dict):
        return None
    src = rec.get("source") or {}
    jobs = {str(x).strip().lower() for x in route.get("jobs") or [] if str(x).strip()}
    watchers = {str(x).strip().lower() for x in route.get("watchers") or [] if str(x).strip()}
    hit_job = sorted({str(src.get(k) or "").strip().lower() for k in ("job", "lane")} & jobs)
    hit_watcher = sorted({str(src.get("watcher") or "").strip().lower()} & watchers)
    if not (hit_job or hit_watcher):
        return None
    return {"job": hit_job, "watcher": hit_watcher, "class": "code_defect"}


def _fresh_ok_dispatch(rec: Mapping[str, Any], policy: Mapping[str, Any], now: datetime) -> bool:
    """Is a dispatch in THIS episode successful and still inside ``fixer_active_hours``?

    Causal rule (2026-11-03): only a fresh, proven-ok dispatch may suppress evaluation; a failed or
    stale dispatch must never hide the incident, and an older episode's dispatch is history.
    """
    rows = [a for a in current_attempts(rec) if a.get("action") == "fixer_dispatch"]
    if not rows:
        return False
    last = max(rows, key=lambda a: str(a.get("at") or ""))
    at = L.parse_ts(last.get("at"))
    active_for = float(policy.get("fixer_active_hours", 12))
    return bool(at and last.get("ok") is not False and now - at < timedelta(hours=active_for))


def fixer_request(rec: Mapping[str, Any], verdict: Mapping[str, Any], cfg: Mapping[str, Any]) -> dict:
    """An N8nCodeDefect@v1-shaped intake file for scripts/self_heal_fixer.py --incident (its own contract)."""
    src = rec.get("source") or {}
    lane = cfg["policy"]["fixer"].get("lane_prefix", "incident-") + re.sub(r"[^a-z0-9-]+", "-",
                                                                          str(src.get("job") or src.get("watcher") or "x").lower()).strip("-")[:48]
    # Root-cause dedupe (2026-11-03): two incidents for one cause must map to ONE fix job, so the
    # signature comes from the incident fingerprint (falling back to the lane) rather than the id.
    # Episode rule: a reopen starts a NEW episode, and the fixer keeps one job per defect_id ever.
    # Episode 1 keeps the established incident-scoped id; a later episode gets a distinct defect_id
    # AND a distinct signature (so the fixer's active-job dedupe and 72h retry cooldown cannot refuse
    # the person's explicit retry). Without this a reopened incident could never be fixed again.
    ep = int(rec.get("episode") or 1)
    sig_src = str(rec.get("fingerprint") or f"{lane}:{rec['id']}")
    if ep > 1:
        sig_src = f"{sig_src}|ep{ep}"
    sig = "sig-" + L.fingerprint_of(sig_src)[3:19]
    did = f"cd-{rec['id']}" if ep == 1 else f"cd-{rec['id']}-ep{ep}"
    return {
        "_why": f"incident supervisor dispatch for {rec['id']}: {verdict.get('action')}",
        "at": L.iso(L.utcnow()),
        "code_defect": {
            "schema": "N8nCodeDefect@v1", "consumer": "claude_code_iterative_fix", "consumer_status": "pending_consumer",
            "kind": "code_defect", "defect_id": did, "lane": lane, "signature": sig,
            "episode": ep,
            "failure_class": "code_error", "failure_kind": "code_error:incident",
            "evidence": {"incident_key": rec["id"], "event_type": "INCIDENT", "siem_id": None, "failed_run_id": None,
                         "evidence_pack": None, "receipt": None,
                         "incident_ledger": "data/coordination/incidents/events.jsonl"},
            "route": "fix_pr_release",
            "next": "fix branch -> PR -> CI green -> Mergify -> deploy_on_main (the fixer never merges or deploys)",
        },
        "receipt": {"stderr_tail": "\n".join([rec.get("title", ""), rec.get("where", ""), verdict.get("action", ""),
                                               verdict.get("rationale", ""), *[str(e) for e in rec.get("evidence") or []]])[-4000:]},
        "registry_row": None,
    }


# ---------------------------------------------------------------- the cycle


def _batch_text(rows: list[dict], priority: str) -> str:
    """ONE page for every escalation this run (ONBOARDING §12 rule 3), as a list.

    Each entry names the incident, how long it has been unresolved and the exact next action. The
    operator asked for one batched message per run, never six separate P1s; a batch pages P1 only
    when it carries an operator-only decision, otherwise P2.
    """
    lines = [f"[{priority}] Incident supervisor — {len(rows)} escalation(s) this run (batched once per run)", ""]
    for row in rows:
        age = row.get("age_min")
        unresolved = "unresolved age unknown" if age is None else f"unresolved {int(age)} min"
        lines.append(f"• {row['id']} — {str(row.get('title') or '')[:140]}")
        lines.append(f"  {str(row.get('reason') or '')[:180]} · {unresolved}")
        lines.append(f"  Next: {str(row.get('ask') or '')[:240]}")
        lines.append(f"  {CC_INCIDENT_URL.format(id=row['id'])}")
    if any(row.get("operator_only") for row in rows):
        lines += ["", "This batch contains an operator-only decision; no agent may act on it."]
    return "\n".join(lines)


def _current_escalations(rec: Mapping[str, Any]) -> list[dict]:
    """Escalations belonging to the current episode.

    A ``reopen`` starts a new episode (2026-11-03), and an escalation row is folded with the episode
    it was written in. Episode 1's delivered page must never suppress episode 2's page for the same
    reason class, so the delivered-row check is episode scoped. Rows written before episodes were
    folded carry ``episode: None``; for those, compare their timestamp with ``reopened_at``. An
    escalation with neither is treated as current only when the incident never reopened (failing to
    suppress is the safe direction: a person sees a duplicate page instead of never seeing the reopen).
    """
    cur = int(rec.get("episode") or 1)
    start = L.parse_ts(rec.get("reopened_at"))
    out = []
    for e in rec.get("escalations") or []:
        ep = e.get("episode")
        if ep is not None:
            try:
                if int(ep) == cur:
                    out.append(e)
            except (TypeError, ValueError):
                pass
            continue
        if start is None:
            out.append(e)
            continue
        at = L.parse_ts(e.get("at"))
        if at is not None and at >= start:
            out.append(e)
    return out


def _pending_escalation(rec: Mapping[str, Any]) -> Optional[dict]:
    """The latest undelivered reason in this episode; another reason's success cannot erase it."""
    rows = _current_escalations(rec)
    delivered = {str(row.get("key") or row.get("reason")) for row in rows if row.get("delivered") is True}
    for row in reversed(rows):
        if str(row.get("key") or row.get("reason")) not in delivered:
            return dict(row)
    return None


def _escalate(rec: dict, reason: str, ask: str, d: Path, deps: Deps, apply: bool, out: dict, now: datetime,
              key: Optional[str] = None, *, operator_only: bool = False) -> None:
    """Queue ONE escalation for a reason class, at most once per DELIVERED page IN THIS EPISODE.

    Causal rule (2026-11-03): suppress only an escalation that was delivered with the SAME key in the
    CURRENT episode (``reopen`` starts a new episode). An undelivered send (``delivered: False``)
    retries on the next evaluation, a different reason class (time box vs attempt cap vs refused
    scope) has its own key and still pages, and episode-1 history never hides an episode-2 page.

    Batching (ONBOARDING §12 rule 3): nothing is sent here. An undelivered ledger row is persisted
    before blocking, then ``_flush_escalations`` sends ONE message; ``operator_only`` decides P1 vs P2.
    """
    key = key or reason
    for e in _current_escalations(rec):
        # Rows written before keys existed carry no key: fall back to the exact reason text.
        if e.get("delivered") is True and (e.get("key") or e.get("reason")) == key:
            return
    opened = L.parse_ts(rec.get("opened_at"))
    row = {"id": rec["id"], "reason": reason, "key": key, "ask": ask, "title": rec.get("title"),
           "age_min": round((now - opened).total_seconds() / 60, 1) if opened else None,
           "operator_only": bool(operator_only), "episode": int(rec.get("episode") or 1)}
    if not apply:
        out["would_escalate"].append(row)
        return
    # The append is fsynced before this incident may become blocked. A later fault or process
    # interruption must leave a retry obligation even when the single batch send never starts.
    # Reuse an undelivered row for this episode/key; a retry must not invent another delivery.
    if not any((e.get("key") or e.get("reason")) == key for e in _current_escalations(rec)):
        L.escalate(row["id"], actor=ACTOR, reason=reason, delivered=False, key=key,
                   episode=row["episode"], d=d, now=now)
    out.setdefault("_pending_escalations", []).append(row)


def _flush_escalations(d: Path, deps: Deps, out: dict, now: datetime) -> None:
    """Send the run's escalations as ONE message; record each incident's delivered row.

    P1 only when the batch contains an operator-only decision, P2 otherwise (ONBOARDING §12 rule 3).
    Every queued reason already has a durable undelivered row. Success appends its delivery;
    failure leaves that obligation for the delivery-only retry, without inventing a successful send.
    """
    pending = out.pop("_pending_escalations", [])
    if not pending:
        return
    # Work later in the cycle may have closed, reopened or delivered an earlier obligation.
    # Re-read the ledger before notification; an old episode must not page for the new one.
    records = L.load_records(d)
    current_pending = []
    for row in pending:
        rec = records.get(row["id"])
        if (rec and rec.get("status") in (*L.UNRESOLVED, "blocked")
                and int(rec.get("episode") or 1) == row["episode"]
                and not any(e.get("delivered") is True and (e.get("key") or e.get("reason")) == row["key"]
                            for e in _current_escalations(rec))):
            current_pending.append(row)
        else:
            out["skipped"].append({"id": row["id"], "why": "escalation superseded"})
    pending = current_pending
    if not pending:
        return
    priority = "P1" if any(row.get("operator_only") for row in pending) else "P2"
    delivered = False
    try:
        delivered = bool(deps.notify(_batch_text(pending, priority), "incident_supervisor:batch", priority=priority))
    except Exception as exc:  # noqa: BLE001 — the durable undelivered obligations remain retryable
        out["notification_error"] = {"error_class": type(exc).__name__}
    for row in pending:
        if delivered:
            L.escalate(row["id"], actor=ACTOR, reason=row["reason"], delivered=True, key=row["key"],
                       episode=row["episode"], d=d, now=now)
        out["escalated"].append({"id": row["id"], "reason": row["reason"], "key": row["key"],
                                 "delivered": delivered, "operator_only": row["operator_only"],
                                 "priority": priority})


def _calls_today(d: Path, now: datetime) -> int:
    p = d / "supervisor_calls.json"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    return int(doc.get("count", 0)) if doc.get("date") == now.date().isoformat() else 0


def _bump_calls(d: Path, now: datetime) -> None:
    n = _calls_today(d, now) + 1
    p = d / "supervisor_calls.json"
    p.write_text(json.dumps({"date": now.date().isoformat(), "count": n}) + "\n", encoding="utf-8")


def _cycle_remaining_s(elapsed_s: float, budget_s: float, margin_s: float) -> float:
    """Seconds a dispatch may still run: the cycle budget minus elapsed time and a safety margin."""
    return budget_s - elapsed_s - margin_s


def _defer_budget(iid: str, stage: str, *, d: Path, now: datetime, apply: bool, out: dict,
                  remaining_s: float) -> None:
    """Record that an incident was left for a later cycle because the budget cannot cover the next step.

    The triage row is written only under ``apply`` (a dry run writes nothing), and it never counts
    toward the attempt cap. ``stage`` says which step was refused (``before model`` /
    ``before runbook``). The caller ``continue``s to the next incident.
    """
    if apply:
        L.attempt(iid, actor=ACTOR, action="triage", result="deferred: cycle budget", ok=None,
                  sets_fixing=False, detail={"deferred_at": stage}, d=d, now=now)
    out["skipped"].append({"id": iid, "why": "deferred: cycle budget", "stage": stage,
                           "remaining_s": int(remaining_s)})


def _call_fixer(deps: Deps, req: Path, apply: bool, timeout_s: float) -> dict:
    """Run the fixer with this cycle's remaining budget when it accepts a ``timeout``.

    The production factory takes ``timeout=`` so the cycle budget can shorten the fixer's own
    subprocess timeout (``min(fixer.timeout_s, remaining)``). Alternate/test fixers with the
    two-argument ``(request, apply)`` contract keep working unchanged.
    """
    try:
        sig = inspect.signature(deps.fixer)
    except (TypeError, ValueError):
        return deps.fixer(req, apply)
    if "timeout" in sig.parameters or any(p.kind is inspect.Parameter.VAR_KEYWORD
                                          for p in sig.parameters.values()):
        return deps.fixer(req, apply, timeout=timeout_s)
    return deps.fixer(req, apply)


def cycle(*, d: Path, state_root: Path, release_root: Path, cfg: Mapping[str, Any], deps: Deps, apply: bool,
          now: Optional[datetime] = None, environ: Optional[Mapping[str, str]] = None, root: Path = ROOT,
          clock: Callable[[], float] = time.monotonic) -> dict:
    """Flush one batch on every exit, including a failure in unrelated incident work."""
    now = now or L.utcnow()
    out: dict[str, Any] = {"schema": RECEIPT_SCHEMA, "as_of": L.iso(now), "mode": "apply" if apply else "dry_run",
                           "considered": [], "actions": [], "dispatched": [], "blocked": [], "escalated": [],
                           "would_escalate": [], "skipped": []}
    completed = False
    try:
        result = _run_cycle(d=d, state_root=state_root, release_root=release_root, cfg=cfg, deps=deps,
                            apply=apply, now=now, environ=environ, root=root, clock=clock, out=out)
        completed = True
        return result
    finally:
        if apply:
            _flush_escalations(d, deps, out, now)
            # Ops exposes only this receipt's as_of, not an error flag. Keep its last completed
            # clock on a failed cycle; the original exception still propagates to the caller.
            if completed:
                d.mkdir(parents=True, exist_ok=True)
                p = d / "supervisor_last.json"
                p.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")


def _run_cycle(*, d: Path, state_root: Path, release_root: Path, cfg: Mapping[str, Any], deps: Deps, apply: bool,
          now: Optional[datetime] = None, environ: Optional[Mapping[str, str]] = None, root: Path = ROOT,
          clock: Callable[[], float] = time.monotonic, out: dict) -> dict:
    now = now or L.utcnow()
    pol = cfg["policy"]
    environ = os.environ if environ is None else environ
    started = clock()
    budget_s = float(pol.get("cycle_budget_s", CYCLE_BUDGET_DEFAULT_S))
    margin_s = float(pol.get("cycle_budget_margin_s", CYCLE_BUDGET_MARGIN_S))
    floor_s = float(pol.get("cycle_budget_floor_s", CYCLE_BUDGET_FLOOR_S))
    fixer_timeout_s = float((pol.get("fixer") or {}).get("timeout_s", CYCLE_BUDGET_DEFAULT_S))
    model_timeout_s = float(pol.get("model_timeout_s", MODEL_TIMEOUT_DEFAULT_S))

    def spendable_s() -> float:
        """Budget minus elapsed minus the safety margin: what the NEXT step may still consume."""
        return _cycle_remaining_s(clock() - started, budget_s, margin_s)

    def dispatch_timeout() -> tuple[Optional[float], float]:
        remaining = spendable_s()
        if remaining < floor_s:
            return None, remaining
        return min(fixer_timeout_s, remaining), remaining

    recs = L.load_records(d)
    max_n = int(pol.get("max_incidents_per_cycle", 5))
    queue = sorted((r for r in recs.values() if r["status"] in L.UNRESOLVED), key=lambda r: r["opened_at"])
    # Delivery-only retries (2026-11-03): a blocking site blocks + pages in the same cycle, and the
    # queue below only carries UNRESOLVED incidents, so a failed page on a now-blocked incident would
    # never be retried. Retry only the send (never the model, never a dispatch) for blocked incidents
    # whose latest current-episode escalation is undelivered. Bounded by the same per-cycle cap.
    retries = sorted((r for r in recs.values()
                      if r["status"] == "blocked" and _pending_escalation(r)),
                     key=lambda r: r["opened_at"])[:max_n]
    # Stage already-durable delivery retries before fallible work. The public cycle's finally
    # flushes this same batch if an unresolved incident fails, without running a model for the retry.
    for rec in retries:
        pending = _pending_escalation(rec)
        if not pending:
            continue
        iid = rec["id"]
        out["considered"].append(iid)
        key = pending.get("key") or pending.get("reason")
        reason = pending.get("reason") or "incident blocked"
        ask = rec.get("handoff") or "A person must take this incident."
        _escalate(rec, reason, ask, d, deps, apply, out, now, key=key,
                  operator_only=key in ("needs_operator", "refused_scope"))
    for rec in queue[:max_n]:
        iid = rec["id"]
        out["considered"].append(iid)
        age_min = (now - (L.parse_ts(rec["opened_at"]) or now)).total_seconds() / 60
        # 1. refused scope: deterministic, before any model
        hit = refused_scope(rec, pol)
        if hit:
            ask = f"Refused scope ({hit!r}): AGENTS.md §0 / §28.14 item 4 — a person decides; no automated fix."
            if apply:
                L.attempt(iid, actor=ACTOR, action="refused", result=ask, ok=None, sets_fixing=False, d=d, now=now)
            _escalate(rec, f"refused scope {hit!r}", ask, d, deps, apply, out, now, key="refused_scope",
                     operator_only=True)
            if apply:
                rec = L.block(iid, actor=ACTOR, blocked_reason=f"needs_operator: refused scope {hit!r}",
                              handoff="operator/coordinator: review the evidence; no agent may act on this scope", d=d, now=now)
            out["blocked"].append({"id": iid, "why": f"refused_scope:{hit}"})
            continue
        # 2. attempts cap (counted within THIS episode: attempts before the last reopen are history)
        if counted_attempts(rec) >= int(pol.get("max_attempts_per_incident", 3)):
            why = f"max attempts ({pol.get('max_attempts_per_incident', 3)}) reached"
            if (apply and _last_action_was_noop(rec)
                    and not any(a.get("action") == "fixer_dispatch" for a in current_attempts(rec))):
                # The cap was reached on runbooks that reported acting on nothing: that is a code or
                # config defect, so it goes to the existing fixer path instead of a person (2026-11-03).
                verdict = {"class": "code_defect",
                           "action": "fix the code or configuration defect named in the evidence",
                           "rationale": "runbook attempts exhausted without acting (no_op)"}
                detail = {"provider": "cap_route", "class": "code_defect", "proposed": verdict["action"]}
                # Cycle budget (2026-11-03): never start a dispatch the unit timeout would kill.
                # The attempt row is written only after the fixer returns, so a kill loses it.
                timeout_s, remaining = dispatch_timeout()
                if timeout_s is None:
                    L.attempt(iid, actor=ACTOR, action="triage", result="deferred: cycle budget",
                              ok=None, sets_fixing=False, d=d, now=now)
                    out["skipped"].append({"id": iid, "why": "deferred: cycle budget",
                                           "remaining_s": int(remaining)})
                    continue
                req = fixer_request(rec, verdict, cfg)
                reqp = d / "fixer_requests" / f"{iid}.json"
                reqp.parent.mkdir(parents=True, exist_ok=True)
                reqp.write_text(json.dumps(req, indent=1) + "\n", encoding="utf-8")
                res = _call_fixer(deps, reqp, True, timeout_s)
                refs = [{"kind": "pr", "ref": str(u)} for u in res.get("prs") or []]
                L.attempt(iid, actor=ACTOR, action="fixer_dispatch",
                          result=f"fixer rc={res.get('rc')} admitted={res.get('admitted')} prs={res.get('prs')}",
                          ok=_dispatch_ok(res),
                          detail={**detail, "request": str(reqp), "fixer": res.get("summary")},
                          fix_refs=refs or None, d=d, now=now)
                out["dispatched"].append({"id": iid, "rc": res.get("rc"), "prs": res.get("prs")})
                continue
            # Causal rule (2026-11-03): ONLY a fresh, proven-ok dispatch in this episode owns the
            # incident and may suppress paging. A failed or stale dispatch (or history from an
            # earlier episode) falls through to a person instead of hiding the incident.
            if _fresh_ok_dispatch(rec, pol, now):
                out["skipped"].append({"id": iid, "why": "fixer job active"})
                continue
            _escalate(rec, why, "Supervisor attempts exhausted; a person must take it.", d, deps, apply, out, now,
                      key="max_attempts")
            if apply:
                rec = L.block(iid, actor=ACTOR, blocked_reason=why,
                              handoff="coordinator: read attempts[] and the evidence; fix by PR or record the operator decision", d=d, now=now)
            out["blocked"].append({"id": iid, "why": why})
            continue
        # 3. time box
        if age_min >= float(pol.get("escalate_after_minutes", 60)):
            _escalate(rec, f"unresolved {int(age_min)} min", "Open the incident; the supervisor is still working it.",
                      d, deps, apply, out, now, key="time_box")
        # 4. model triage (cooldown + daily call cap). Cooldown is per episode: a reopen is a person's
        # explicit retry, so an old attempt must not delay it (2026-11-03). A cycle-budget deferral
        # row is excluded: it ran nothing, so it must not starve this incident for 30 minutes.
        last = max((L.parse_ts(a.get("at")) for a in current_attempts(rec)
                    if a.get("at") and not _is_budget_deferral(a)), default=None)
        if last and now - last < timedelta(minutes=float(pol.get("model_cooldown_minutes", 30))):
            out["skipped"].append({"id": iid, "why": "cooldown"})
            continue
        # Cycle budget (2026-11-03): never start a model call the unit timeout could kill. The gate
        # sits after every cheap/deterministic path and before build_prompt/model.
        remaining = spendable_s()
        if remaining < model_timeout_s:
            _defer_budget(iid, "before model", d=d, now=now, apply=apply, out=out, remaining_s=remaining)
            continue
        # 3b. DISK INCIDENT — deterministic, BEFORE any model call (operator 2026-11-03, item 4: "the incident
        # supervisor must never park a disk incident as 'needs a person'; it dispatches the fixer"). Placed after
        # every cheap rail (refused scope, attempts cap, time box, cooldown, call cap, cycle budget) and before
        # build_prompt, so no model call can happen first and no model answer can change the class. The dispatch
        # itself is the existing hardened code_defect branch below — this only forces the classification.
        disk = disk_incident_route(rec, cfg)
        if disk and not apply:
            # A dry run never dispatches: it reports what it would have done and moves on.
            out["skipped"].append({"id": iid, "why": "dry_run: would dispatch the fixer", "route": "disk_incident"})
            continue
        if disk:
            verdict = {"class": "code_defect",
                       "action": f"fix the disk incident: {str(rec.get('title') or '')[:200]}",
                       "params": {}, "rationale": "disk incident routed to the fixer lane (operator 2026-11-03)"}
            detail = {"provider": "deterministic", "class": "code_defect", "route": "disk_incident",
                      "matched": disk, "proposed": verdict["action"]}
        else:
            # The daily model-call cap is a MODEL gate (cx-openai-3 F3): it must never park a deterministic disk
            # incident, which needs no model at all. It lives here, on the only branch that spends calls.
            if _calls_today(d, now) >= int(pol.get("max_model_calls_per_day", 40)):
                out["skipped"].append({"id": iid, "why": "daily model-call cap"})
                continue
            prompt = build_prompt(rec, cfg, evidence=evidence_excerpt(rec, state_root), runbooks=runbook_excerpt(rec, cfg, root))
            if not apply:
                out["skipped"].append({"id": iid, "why": "dry_run: would call model", "prompt_chars": len(prompt)})
                continue
            _bump_calls(d, now)
            try:
                text, provider = deps.model(prompt)
            except Exception as exc:  # noqa: BLE001 — a refused/failed call is recorded, the time box still escalates
                L.attempt(iid, actor=ACTOR, action="triage", result=f"model unavailable: {str(exc)[:200]}", ok=False,
                          sets_fixing=False, d=d, now=now)
                out["skipped"].append({"id": iid, "why": "model_error"})
                continue
            provider = str(provider or "").lower()
            if any(p in provider for p in pol.get("never_providers") or []):
                L.attempt(iid, actor=ACTOR, action="triage", result=f"answer from refused provider {provider} discarded",
                          ok=False, sets_fixing=False, d=d, now=now)
                out["skipped"].append({"id": iid, "why": f"refused_provider:{provider}"})
                continue
            verdict = parse_verdict(text)
            if not verdict:
                L.attempt(iid, actor=ACTOR, action="triage", result="unparseable model output", ok=False,
                          sets_fixing=False, detail={"provider": provider}, d=d, now=now)
                out["skipped"].append({"id": iid, "why": "unparseable"})
                continue
            detail = {"provider": provider, "class": verdict["class"], "proposed": verdict["action"],
                      "rationale": verdict["rationale"]}
            acts = any(p in provider for p in pol.get("act_on_providers") or ["anthropic"])
            if not acts:
                L.attempt(iid, actor=ACTOR, action="triage_readonly", result=f"{verdict['class']}: {verdict['action']}",
                          ok=None, sets_fixing=False, detail=detail, d=d, now=now)
                out["skipped"].append({"id": iid, "why": f"readonly_provider:{provider}"})
                continue
        if verdict["class"] == "runbook":
            chosen, why = validate_action(verdict, rec, cfg)
            if not chosen:
                L.attempt(iid, actor=ACTOR, action="triage", result=f"runbook refused: {why}", ok=False,
                          sets_fixing=False, detail=detail, d=d, now=now)
                out["skipped"].append({"id": iid, "why": why})
                continue
            spec = chosen["spec"]
            need_s = float(spec.get("timeout_s", 300))
            # Cycle budget (2026-11-03): a runbook action is all-or-nothing. Never shorten its own
            # timeout (a shortened kill could leave partial state); defer instead.
            remaining = spendable_s()
            if remaining < need_s:
                _defer_budget(iid, "before runbook", d=d, now=now, apply=apply, out=out, remaining_s=remaining)
                continue
            argv = render_argv(spec, chosen["params"], cfg)
            cwd = str(release_root if spec.get("cwd") == "release" else root)
            rc, tail = deps.run(argv, cwd, action_env(cfg, environ), need_s)
            L.attempt(iid, actor=ACTOR, action=chosen["name"], result=f"rc={rc}", ok=rc == 0,
                      detail={**detail, "argv": argv, "output_tail": tail[-1200:],
                              "no_op": _action_took_effect(spec, tail) is False}, d=d, now=now)
            out["actions"].append({"id": iid, "action": chosen["name"], "rc": rc})
        elif verdict["class"] == "code_defect":
            # Causal dispatch rule (2026-11-03): one dispatch per episode.
            #  * a FRESH, proven-ok dispatch owns the incident — the ONLY permitted skip;
            #  * any other prior dispatch in this episode is failed or stale: record an attempt row
            #    (so the model cooldown advances and nothing loops) then block + page;
            #  * otherwise dispatch now, ALWAYS record the attempt row, block + page on a failure.
            if _fresh_ok_dispatch(rec, pol, now):
                # The one permitted skip: a fresh, proven-ok job owns this episode. It still writes a
                # triage row (never counted toward the cap) so the model cooldown advances and the
                # supervisor does not re-triage the same incident every tick.
                L.attempt(iid, actor=ACTOR, action="triage",
                          result="fixer job active: fresh proven dispatch owns this episode",
                          ok=None, sets_fixing=False, detail={**detail, "fixer": "fresh_ok_dispatch"},
                          d=d, now=now)
                out["skipped"].append({"id": iid, "why": "fixer job active"})
                continue
            prior = [a for a in current_attempts(rec) if a.get("action") == "fixer_dispatch"]
            if prior:
                why = "prior fixer dispatch in this episode did not prove work; not redispatching"
                L.attempt(iid, actor=ACTOR, action="triage", result=why, ok=False, sets_fixing=False,
                          detail={**detail, "fixer": "stale_or_failed_dispatch"}, d=d, now=now)
                _escalate(rec, why, "The fixer did not prove work; a person must take it.",
                          d, deps, apply, out, now, key="fixer_dispatch_failed")
                rec = L.block(iid, actor=ACTOR, blocked_reason=why,
                              handoff="coordinator: inspect the fixer job; a retry needs an operator requeue",
                              d=d, now=now)
                out["blocked"].append({"id": iid, "why": why})
                continue
            # Cycle budget (2026-11-03): the fixer timeout is capped at the remaining budget, and a
            # dispatch is deferred (triage row only) when too little remains. The incident stays
            # unresolved and drains on a later cycle; it is never silently dropped.
            timeout_s, remaining = dispatch_timeout()
            if timeout_s is None:
                L.attempt(iid, actor=ACTOR, action="triage", result="deferred: cycle budget",
                          ok=None, sets_fixing=False, d=d, now=now)
                out["skipped"].append({"id": iid, "why": "deferred: cycle budget",
                                       "remaining_s": int(remaining)})
                continue
            req = fixer_request(rec, verdict, cfg)
            reqp = d / "fixer_requests" / f"{iid}.json"
            reqp.parent.mkdir(parents=True, exist_ok=True)
            reqp.write_text(json.dumps(req, indent=1) + "\n", encoding="utf-8")
            res = _call_fixer(deps, reqp, True, timeout_s)
            ok = _dispatch_ok(res)
            refs = [{"kind": "pr", "ref": str(u)} for u in res.get("prs") or []]
            L.attempt(iid, actor=ACTOR, action="fixer_dispatch",
                      result=f"fixer rc={res.get('rc')} admitted={res.get('admitted')} prs={res.get('prs')}",
                      ok=ok, detail={**detail, "request": str(reqp), "fixer": res.get("summary")},
                      fix_refs=refs or None, d=d, now=now)
            out["dispatched"].append({"id": iid, "rc": res.get("rc"), "prs": res.get("prs")})
            if not ok:
                why = f"fixer dispatch did not prove work (rc={res.get('rc')})"
                _escalate(rec, why, "The fixer did not prove work; a person must take it.",
                          d, deps, apply, out, now, key="fixer_dispatch_failed")
                rec = L.block(iid, actor=ACTOR, blocked_reason=why,
                              handoff="coordinator: inspect the fixer job; a retry needs an operator requeue",
                              d=d, now=now)
                out["blocked"].append({"id": iid, "why": why})
        else:  # needs_operator
            L.attempt(iid, actor=ACTOR, action="triage", result=f"needs_operator: {verdict['action']}", ok=None,
                      sets_fixing=False, detail=detail, d=d, now=now)
            _escalate(rec, "needs operator", verdict["action"], d, deps, apply, out, now, key="needs_operator",
                      operator_only=True)
            rec = L.block(iid, actor=ACTOR, blocked_reason=f"needs_operator: {verdict['rationale'][:300]}",
                          handoff=verdict["action"] or "operator decision required", d=d, now=now)
            out["blocked"].append({"id": iid, "why": "needs_operator"})
    return out


def _dispatch_ok(res: Mapping[str, Any]) -> bool:
    """True only when the fixer provably started (or already had) a job.

    A zero exit code is not evidence of work: the fixer returns 0 for "not armed", "busy" and
    "nothing to do". Callers that supply ``work_proven`` say so directly; otherwise an admitted job
    is the evidence. Anything else must page a person rather than hide the incident.
    """
    proven = res.get("work_proven")
    if proven is None:
        proven = bool(res.get("admitted"))
    return res.get("rc") == 0 and bool(proven)


def _request_identity(req: Path) -> tuple[Optional[str], Optional[str]]:
    """(defect_id, incident_key) named by the fix request, or (None, None) when it cannot be read.

    Proof must never be inferred from the fixer's GLOBAL admission book: a stale job for a different
    incident could otherwise prove work for this one (2026-11-03).
    """
    try:
        doc = json.loads(Path(req).read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None, None
    if not isinstance(doc, dict):
        return None, None
    cd = doc.get("code_defect") if isinstance(doc.get("code_defect"), dict) else {}
    ev = cd.get("evidence") if isinstance(cd.get("evidence"), dict) else {}
    top_ev = doc.get("evidence") if isinstance(doc.get("evidence"), dict) else {}
    did = cd.get("defect_id") or doc.get("defect_id")
    ikey = ev.get("incident_key") or top_ev.get("incident_key")
    return (str(did) if did else None, str(ikey) if ikey else None)


def default_fixer_factory(cfg: Mapping[str, Any], python: str, repo_root: Path) -> Callable[..., dict]:
    fx = cfg["policy"]["fixer"]

    def run_fixer(req: Path, apply: bool, timeout: Optional[float] = None) -> dict:
        argv = [python, str(repo_root / fx["script"]), "--cycle", "--incident", str(req)]
        argv.append("--apply" if apply else "--dry-run")
        defect_id, incident_key = _request_identity(req)
        # The cycle budget may shorten this below the fixer's own configured timeout:
        # ``min(fixer.timeout_s, remaining budget)`` (2026-11-03).
        limit_s = max(0.001, float(timeout if timeout is not None else fx.get("timeout_s", 7500)))
        try:
            p = subprocess.run(argv, cwd=str(repo_root), capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=limit_s)
        except subprocess.TimeoutExpired:
            return {"rc": 124, "summary": "timeout", "work_proven": False, "admitted": [],
                    "busy": False, "prs": []}
        except (OSError, UnicodeDecodeError) as exc:
            # A non-UTF8 byte or an exec failure is a failed dispatch, never a crash of the cycle.
            return {"rc": 127, "summary": f"{type(exc).__name__}: {exc}", "work_proven": False,
                    "admitted": [], "busy": False, "prs": []}
        # A report with a replacement character was not valid UTF-8: we cannot trust any of it, so
        # fail closed with rc 127 (a failed dispatch that pages) instead of reading a mangled report.
        raw = p.stdout or ""
        bad_decode = "�" in raw
        try:
            doc = json.loads(raw or "{}")
        except ValueError:
            doc = {}
        if not isinstance(doc, dict):
            doc = {}
        prs = re.findall(r"https://github\.com/[^\s\"']+/pull/\d+", raw)
        admitted = [a.get("job_id") for a in doc.get("admitted") or [] if isinstance(a, dict)]
        # Proof is scoped to THIS request (2026-11-03): only an ``admitted`` row carrying this
        # request's defect_id (or incident key) names this incident's job; only THAT job's
        # ``attempted`` outcome can prove work. A stale job for a different incident never counts.
        mine: set[str] = set()
        for row in doc.get("admitted") or []:
            if not isinstance(row, dict) or not isinstance(row.get("job_id"), str):
                continue
            same = ((defect_id and str(row.get("defect_id") or "") == defect_id)
                    or (incident_key and str(row.get("incident_key") or "") == incident_key))
            if same:
                mine.add(row["job_id"])
        # Admission alone is NOT proof: self_heal_fixer appends to ``admitted`` BEFORE it checks arming,
        # so a not_armed / no_backend / no_rails / not_claimed run reports an admitted job and then an
        # ``attempted`` entry naming the refusal. Only a POSITIVE allowlist of working states is proof;
        # every refusal prefix, ``dry_run_planned`` and the terminal failures page a person instead.
        outcomes: dict[str, str] = {}
        for row in doc.get("attempted") or []:
            if isinstance(row, dict) and isinstance(row.get("job_id"), str) and row["job_id"] in mine:
                outcomes[row["job_id"]] = str(row.get("outcome") or "")
        work_proven = (not bad_decode and not doc.get("busy")
                       and any(o in WORKING_OUTCOMES for o in outcomes.values()))
        return {"rc": 127 if bad_decode else p.returncode, "admitted": admitted, "work_proven": work_proven,
                "busy": bool(doc.get("busy")),
                "prs": sorted(set(prs)),
                "summary": (f"undecodable fixer report (non-UTF8): {raw[-600:]}" if bad_decode
                            else (raw or p.stderr or "")[-800:])}

    return run_fixer
