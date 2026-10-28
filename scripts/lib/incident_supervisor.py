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
   * ``code_defect`` → the §28.14 Claude Code fixer (scripts/self_heal_fixer.py) once per incident; it opens a PR and
     never merges, releases or deploys.
   * ``needs_operator`` → ``blocked`` with the model's action as the handoff + one P1 through the chokepoint
     (scripts/telegram_alert.send_telegram) carrying the incident id.
   A fallback-provider answer is read-only triage: recorded, never executed.

The supervisor never merges, pushes, promotes, deletes, orders, stops, sizes, writes a broker or reads a secret.
AUTHORITY: READ_ONLY_ADVISORY for every decision; the only side effects are the allowlisted argv, the fixer dispatch
and the P1. MBI_BEHAVIOR=0.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
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
Notifier = Callable[[str, str], bool]


@dataclass
class Deps:
    model: ModelCall
    run: Runner
    notify: Notifier
    fixer: Callable[[Path, bool], dict]


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
        p = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except OSError as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return p.returncode, ((p.stdout or "") + ("\n" + p.stderr if p.stderr else ""))[-2000:]


def default_notify(text: str, producer: str) -> bool:
    try:
        from scripts.telegram_alert import send_telegram
    except ImportError:
        from telegram_alert import send_telegram  # type: ignore
    return bool(send_telegram(text, priority="P1", dedupe_minutes=0, producer=producer))


# ---------------------------------------------------------------- pure decisions


def refused_scope(rec: Mapping[str, Any], policy: Mapping[str, Any]) -> Optional[str]:
    rx = re.compile(policy["refused_scope_regex"])
    src = rec.get("source") or {}
    hay = " ".join(str(x) for x in (rec.get("title"), rec.get("where"), src.get("job"), src.get("lane")))
    m = rx.search(hay)
    return m.group(0) if m else None


def supervisor_attempts(rec: Mapping[str, Any]) -> list[dict]:
    return [a for a in rec.get("attempts") or [] if a.get("actor") == ACTOR]


def counted_attempts(rec: Mapping[str, Any]) -> int:
    """Attempts that count toward the cap: executed actions and fixer dispatches (triage-only rows do not)."""
    return sum(1 for a in supervisor_attempts(rec) if a.get("action") not in ("triage", "triage_readonly", "refused"))


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
        "Do not repeat an action already in attempts that failed.\n\n"
        f"INCIDENT:\n{json.dumps(slim, default=str)[:3000]}\n\nALLOWLISTED ACTIONS:\n{json.dumps(acts)}\n\n"
        f"EVIDENCE:\n{evidence[:5000]}\n\nRUNBOOKS:\n{runbooks[:4000]}\n"
    )


def fixer_request(rec: Mapping[str, Any], verdict: Mapping[str, Any], cfg: Mapping[str, Any]) -> dict:
    """An N8nCodeDefect@v1-shaped intake file for scripts/self_heal_fixer.py --incident (its own contract)."""
    src = rec.get("source") or {}
    lane = cfg["policy"]["fixer"].get("lane_prefix", "incident-") + re.sub(r"[^a-z0-9-]+", "-",
                                                                          str(src.get("job") or src.get("watcher") or "x").lower()).strip("-")[:48]
    sig = "sig-" + L.fingerprint_of(rec["id"], rec.get("fingerprint"))[3:19]
    return {
        "_why": f"incident supervisor dispatch for {rec['id']}: {verdict.get('action')}",
        "at": L.iso(L.utcnow()),
        "code_defect": {
            "schema": "N8nCodeDefect@v1", "consumer": "claude_code_iterative_fix", "consumer_status": "pending_consumer",
            "kind": "code_defect", "defect_id": f"cd-{rec['id']}", "lane": lane, "signature": sig, "episode": 1,
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


def _p1_text(rec: Mapping[str, Any], reason: str, ask: str) -> str:
    return (f"[P1] Incident {rec['id']}: {rec.get('title', '')[:160]}\n"
            f"Why: {reason[:200]}\nNext: {ask[:300]}\n{CC_INCIDENT_URL.format(id=rec['id'])}")


def _escalate(rec: dict, reason: str, ask: str, d: Path, deps: Deps, apply: bool, out: dict, now: datetime) -> None:
    if rec.get("escalations"):
        return  # once per incident
    row = {"id": rec["id"], "reason": reason}
    if not apply:
        out["would_escalate"].append(row)
        return
    try:
        delivered = deps.notify(_p1_text(rec, reason, ask), f"incident_supervisor:{rec['id']}")
    except Exception as exc:  # noqa: BLE001
        delivered = False
        reason = f"{reason} (send error {type(exc).__name__})"
    L.escalate(rec["id"], actor=ACTOR, reason=reason, delivered=delivered, d=d, now=now)
    out["escalated"].append({**row, "delivered": delivered})


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


def cycle(*, d: Path, state_root: Path, release_root: Path, cfg: Mapping[str, Any], deps: Deps, apply: bool,
          now: Optional[datetime] = None, environ: Optional[Mapping[str, str]] = None, root: Path = ROOT) -> dict:
    now = now or L.utcnow()
    pol = cfg["policy"]
    environ = os.environ if environ is None else environ
    out: dict[str, Any] = {"schema": RECEIPT_SCHEMA, "as_of": L.iso(now), "mode": "apply" if apply else "dry_run",
                           "considered": [], "actions": [], "dispatched": [], "blocked": [], "escalated": [],
                           "would_escalate": [], "skipped": []}
    recs = L.load_records(d)
    queue = sorted((r for r in recs.values() if r["status"] in L.UNRESOLVED), key=lambda r: r["opened_at"])
    for rec in queue[: int(pol.get("max_incidents_per_cycle", 5))]:
        iid = rec["id"]
        out["considered"].append(iid)
        age_min = (now - (L.parse_ts(rec["opened_at"]) or now)).total_seconds() / 60
        # 1. refused scope: deterministic, before any model
        hit = refused_scope(rec, pol)
        if hit:
            ask = f"Refused scope ({hit!r}): AGENTS.md §0 / §28.14 item 4 — a person decides; no automated fix."
            if apply:
                L.attempt(iid, actor=ACTOR, action="refused", result=ask, ok=None, sets_fixing=False, d=d, now=now)
                rec = L.block(iid, actor=ACTOR, blocked_reason=f"needs_operator: refused scope {hit!r}",
                              handoff="operator/coordinator: review the evidence; no agent may act on this scope", d=d, now=now)
            out["blocked"].append({"id": iid, "why": f"refused_scope:{hit}"})
            _escalate(rec, f"refused scope {hit!r}", ask, d, deps, apply, out, now)
            continue
        # 2. attempts cap
        if counted_attempts(rec) >= int(pol.get("max_attempts_per_incident", 3)):
            why = f"max attempts ({pol.get('max_attempts_per_incident', 3)}) reached"
            if apply:
                rec = L.block(iid, actor=ACTOR, blocked_reason=why,
                              handoff="coordinator: read attempts[] and the evidence; fix by PR or record the operator decision", d=d, now=now)
            out["blocked"].append({"id": iid, "why": why})
            _escalate(rec, why, "Supervisor attempts exhausted; a person must take it.", d, deps, apply, out, now)
            continue
        # 3. time box
        if age_min >= float(pol.get("escalate_after_minutes", 60)):
            _escalate(rec, f"unresolved {int(age_min)} min", "Open the incident; the supervisor is still working it.",
                      d, deps, apply, out, now)
        # 4. model triage (cooldown + daily call cap)
        last = max((L.parse_ts(a.get("at")) for a in supervisor_attempts(rec) if a.get("at")), default=None)
        if last and now - last < timedelta(minutes=float(pol.get("model_cooldown_minutes", 30))):
            out["skipped"].append({"id": iid, "why": "cooldown"})
            continue
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
            argv = render_argv(spec, chosen["params"], cfg)
            cwd = str(release_root if spec.get("cwd") == "release" else root)
            rc, tail = deps.run(argv, cwd, action_env(cfg, environ), float(spec.get("timeout_s", 300)))
            L.attempt(iid, actor=ACTOR, action=chosen["name"], result=f"rc={rc}", ok=rc == 0,
                      detail={**detail, "argv": argv, "output_tail": tail[-1200:]}, d=d, now=now)
            out["actions"].append({"id": iid, "action": chosen["name"], "rc": rc})
        elif verdict["class"] == "code_defect":
            if any(a.get("action") == "fixer_dispatch" for a in supervisor_attempts(rec)):
                out["skipped"].append({"id": iid, "why": "fixer already dispatched"})
                continue
            req = fixer_request(rec, verdict, cfg)
            reqp = d / "fixer_requests" / f"{iid}.json"
            reqp.parent.mkdir(parents=True, exist_ok=True)
            reqp.write_text(json.dumps(req, indent=1) + "\n", encoding="utf-8")
            res = deps.fixer(reqp, True)
            refs = [{"kind": "pr", "ref": str(u)} for u in res.get("prs") or []]
            L.attempt(iid, actor=ACTOR, action="fixer_dispatch",
                      result=f"fixer rc={res.get('rc')} admitted={res.get('admitted')} prs={res.get('prs')}",
                      ok=res.get("rc") == 0, detail={**detail, "request": str(reqp), "fixer": res.get("summary")},
                      fix_refs=refs or None, d=d, now=now)
            out["dispatched"].append({"id": iid, "rc": res.get("rc"), "prs": res.get("prs")})
        else:  # needs_operator
            L.attempt(iid, actor=ACTOR, action="triage", result=f"needs_operator: {verdict['action']}", ok=None,
                      sets_fixing=False, detail=detail, d=d, now=now)
            rec = L.block(iid, actor=ACTOR, blocked_reason=f"needs_operator: {verdict['rationale'][:300]}",
                          handoff=verdict["action"] or "operator decision required", d=d, now=now)
            out["blocked"].append({"id": iid, "why": "needs_operator"})
            _escalate(rec, "needs operator", verdict["action"], d, deps, apply, out, now)
    if apply:
        p = d / "supervisor_last.json"
        p.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    return out


def default_fixer_factory(cfg: Mapping[str, Any], python: str, repo_root: Path) -> Callable[[Path, bool], dict]:
    fx = cfg["policy"]["fixer"]

    def run_fixer(req: Path, apply: bool) -> dict:
        argv = [python, str(repo_root / fx["script"]), "--cycle", "--incident", str(req)]
        argv.append("--apply" if apply else "--dry-run")
        try:
            p = subprocess.run(argv, cwd=str(repo_root), capture_output=True, text=True, timeout=float(fx.get("timeout_s", 3600)))
        except subprocess.TimeoutExpired:
            return {"rc": 124, "summary": "timeout"}
        try:
            doc = json.loads(p.stdout or "{}")
        except ValueError:
            doc = {}
        prs = re.findall(r"https://github\.com/[^\s\"']+/pull/\d+", p.stdout or "")
        return {"rc": p.returncode, "admitted": [a.get("job_id") for a in doc.get("admitted") or []] if isinstance(doc, dict) else None,
                "prs": sorted(set(prs)), "summary": (p.stdout or p.stderr or "")[-800:]}

    return run_fixer
