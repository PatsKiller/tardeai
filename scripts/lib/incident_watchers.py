"""Deterministic incident watchers — no model, host timer every 5 minutes (operator 2026-10-27).

Each watcher reads an EXISTING producer's output and returns ``WatchResult(findings, gap)``:

* ``findings`` — the conditions that are true now, each with a fingerprint carrying its distinguishing token
  (SHA, job, lane, symbol). The comms-editor lesson of 2026-10-26/27 (386 deploy alerts suppressed because the
  fingerprint stripped SHAs) is why the SHA is IN the fingerprint here.
* ``gap`` — a reason the input could not be read. A watcher with a gap opens nothing and resolves nothing.

``run(...)`` opens one IncidentRecord@v1 per new fingerprint and auto-resolves this watcher's unresolved incidents
whose fingerprint is no longer present. Inputs are read-only; the only writes are the incident ledger (through
scripts/lib/incidents.py) and this lane's own ``watchers_state.json`` / ``watchers_last.json``.
AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

try:
    from scripts.lib import incidents as L
except ImportError:  # noqa: SIM105  # scripts/lib on sys.path
    import incidents as L  # type: ignore[no-redef]

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
RECEIPT_SCHEMA = "IncidentWatchersReceipt@v1"
ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "incident_watchers.json"


@dataclass
class Finding:
    fingerprint: str
    title: str
    where: str
    evidence: list = field(default_factory=list)
    severity: str = "P2"
    job: str = ""


@dataclass
class WatchResult:
    findings: list = field(default_factory=list)
    gap: Optional[str] = None
    detail: dict = field(default_factory=dict)


@dataclass
class Ctx:
    state_root: Path
    now: datetime
    cfg: Mapping[str, Any]
    state: dict  # this lane's own memory (first-seen times)
    gh: Callable[[list], tuple[int, str]]
    git: Callable[[str, list], tuple[int, str]]
    llm_queue: Callable[[], Optional[dict]]


# ---------------------------------------------------------------- helpers


def _load(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"__unreadable__": True}


def _age_min(now: datetime, ts: Any) -> Optional[float]:
    t = L.parse_ts(ts)
    return None if t is None else (now - t).total_seconds() / 60.0


def _stale(now: datetime, ts: Any, minutes: float) -> bool:
    age = _age_min(now, ts)
    return age is None or age > minutes


def _ev(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def default_gh(args: list) -> tuple[int, str]:
    """Read-only gh (``run list``/``api`` GET only)."""
    if not args or args[0] not in ("run", "api") or (args[0] == "run" and args[1:2] != ["list"]):
        raise ValueError(f"gh call not allowlisted: {args[:2]}")
    if args[0] == "api" and any(a in ("-X", "--method", "-f", "-F", "--input") for a in args):
        raise ValueError("gh api must be a GET")
    p = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout if p.returncode == 0 else p.stderr


def default_git(repo: str, args: list) -> tuple[int, str]:
    if not args or args[0] not in ("status", "rev-parse", "symbolic-ref"):
        raise ValueError("git call not allowlisted")
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout if p.returncode == 0 else p.stderr


def default_llm_queue() -> Optional[dict]:
    try:
        try:
            from scripts.lib import llm_deferral  # type: ignore
        except ImportError:
            import llm_deferral  # type: ignore
        return llm_deferral.queue_summary()
    except Exception:  # psycopg2 absent / DB down: a collection gap, not an incident
        return None


# ---------------------------------------------------------------- watchers


def _deploy_receipts(ctx: Ctx, rel: str, tail: int = 60) -> Optional[list[tuple[str, dict]]]:
    d = ctx.state_root / rel
    if not d.is_dir():
        return None
    names = sorted(n.name for n in d.glob("2*_*.json"))[-tail:]
    out = []
    for n in names:
        doc = _load(d / n)
        if isinstance(doc, dict) and not doc.get("__unreadable__"):
            out.append((n, doc))
    return out


def w_deploy_failures(ctx: Ctx, c: Mapping[str, Any]) -> WatchResult:
    rows = _deploy_receipts(ctx, c["receipts_rel"])
    if rows is None:
        return WatchResult(gap="deploy_on_main receipts dir missing")
    fails = set(c.get("failure_outcomes") or ["deploy_failed", "verify_failed"])
    streak = []
    for name, doc in reversed(rows):
        if doc.get("outcome") in fails:
            streak.append((name, doc))
        elif doc.get("outcome") in ("noop", "verified", "would_promote") or (
            doc.get("outcome") == "refuse" and doc.get("reason") == "already_served"
        ):
            break
        # a refuse (lock busy, STOP, fetch) neither extends nor breaks a failure streak
    res = WatchResult(detail={"streak": len(streak)})
    if len(streak) >= int(c.get("consecutive_failures", 3)):
        last_name, last = streak[0]
        sha = str(last.get("main_sha") or "")
        reason = str(last.get("reason") or "")
        tail = str((last.get("detail") or {}).get("log_tail") or (last.get("detail") or {}).get("verify_tail") or "")
        res.findings.append(Finding(
            fingerprint=L.fingerprint_of("deploy_failures", sha),
            title=f"deploy_on_main: {len(streak)} consecutive failures promoting {sha[:12]} ({reason})",
            where="tradeai-deploy-on-main.timer → scripts/deploy_on_main_poll.py",
            evidence=[f"receipt:{c['receipts_rel']}/{n}" for n, _ in streak[:5]] + ([f"log_tail:{tail[-400:]}"] if tail else []),
            severity=c.get("severity", "P1"), job="deploy-on-main"))
    return res


def w_deploy_stuck(ctx: Ctx, c: Mapping[str, Any]) -> WatchResult:
    rows = _deploy_receipts(ctx, c["receipts_rel"], tail=200)
    if rows is None:
        return WatchResult(gap="deploy_on_main receipts dir missing")
    if not rows:
        return WatchResult(gap="no deploy_on_main receipts")
    name, last = rows[-1]
    age = _age_min(ctx.now, last.get("as_of"))
    if age is None or age > 30:
        return WatchResult(gap=f"latest deploy_on_main receipt stale ({age} min)")
    main, cur = str(last.get("main_sha") or ""), str(last.get("current_sha_after") or last.get("current_sha_before") or "")
    if not main or not cur:
        return WatchResult(gap="receipt lacks main_sha/current_sha")
    if main.startswith(cur) or cur.startswith(main):
        return WatchResult(detail={"main": main[:12], "current": cur[:12]})
    first = None
    for n, doc in rows:
        if str(doc.get("main_sha") or "") == main:
            first = first or doc.get("as_of")
    stuck = _age_min(ctx.now, first) or 0.0
    res = WatchResult(detail={"main": main[:12], "current": cur[:12], "stuck_min": round(stuck, 1)})
    if stuck > float(c.get("stuck_minutes", 30)):
        res.findings.append(Finding(
            fingerprint=L.fingerprint_of("deploy_stuck", main),
            title=f"main {main[:12]} not live after {int(stuck)} min (CURRENT {cur[:12]}; last: {last.get('outcome')} {last.get('reason')})",
            where="deploy_on_main poller / CURRENT pin",
            evidence=[f"receipt:{c['receipts_rel']}/{name}"],
            severity=c.get("severity", "P1"), job="deploy-on-main"))
    return res


def w_health_tick(ctx: Ctx, c: Mapping[str, Any]) -> WatchResult:
    p = ctx.state_root / c["receipt_rel"]
    doc = _load(p)
    if not isinstance(doc, dict) or doc.get("__unreadable__"):
        return WatchResult(gap="health_tick receipt missing/unreadable")
    res = WatchResult()
    age = _age_min(ctx.now, doc.get("as_of"))
    if age is None or age > float(c.get("stale_minutes", 30)):
        res.findings.append(Finding(
            fingerprint=L.fingerprint_of("health_tick", "stale"),
            title=f"health tick receipt stale ({'unknown' if age is None else int(age)} min old)",
            where="tradeai-health-tick.timer → scripts/health_tick.py", evidence=[f"receipt:{c['receipt_rel']}"],
            severity="P1", job="health-tick"))
        return res
    steps = {s.get("step_id"): s for s in doc.get("steps") or [] if isinstance(s, dict)}
    for lst in c.get("step_lists") or []:
        for sid in doc.get(lst) or []:
            sid = sid.get("step_id") if isinstance(sid, dict) else sid
            s = steps.get(sid) or {}
            res.findings.append(Finding(
                fingerprint=L.fingerprint_of("health_tick", lst, sid),
                title=f"health tick step {sid} {lst} (rc={s.get('rc')})",
                where=f"scripts/health_tick.py step {sid}",
                evidence=[f"receipt:{c['receipt_rel']}"] + ([f"stderr:{s.get('stderr_first_line')}"] if s.get("stderr_first_line") else []),
                severity=c.get("severity", "P2"), job=str(sid)))
    return res


def w_expected_services(ctx: Ctx, c: Mapping[str, Any]) -> WatchResult:
    doc = _load(ctx.state_root / c["receipt_rel"])
    if not isinstance(doc, dict) or doc.get("__unreadable__"):
        return WatchResult(gap="expected services receipt missing/unreadable")
    age = _age_min(ctx.now, doc.get("ran_at"))
    if age is None or age > float(c.get("stale_minutes", 180)):
        return WatchResult(gap=f"expected services receipt stale ({age} min)")
    res = WatchResult()
    ignore = set(c.get("ignore_items") or [])
    for item in doc.get("off_items") or []:
        if item in ignore:
            continue
        res.findings.append(Finding(
            fingerprint=L.fingerprint_of("expected_services", item),
            title=f"expected service off: {item}", where="scripts/check_expected_services.py",
            evidence=[f"receipt:{c['receipt_rel']}"], severity=c.get("severity", "P2"), job=item.split(":", 1)[-1]))
    return res


def w_lane_health(ctx: Ctx, c: Mapping[str, Any]) -> WatchResult:
    res = WatchResult()
    doc = _load(ctx.state_root / c["research_rel"])
    gaps = []
    if not isinstance(doc, dict) or doc.get("__unreadable__"):
        gaps.append("research_lane_health missing")
    elif _stale(ctx.now, doc.get("as_of"), float(c.get("stale_minutes", 120))):
        gaps.append("research_lane_health stale")
    else:
        for lane, row in sorted((doc.get("lanes") or {}).items()):
            if isinstance(row, dict) and row.get("ok") is False:
                firing = [str(f) for f in row.get("firing") or []]
                res.findings.append(Finding(
                    fingerprint=L.fingerprint_of("lane_health", lane),
                    title=f"lane {lane} unhealthy: {', '.join(firing[:3])}"[:200],
                    where="scripts/research_lane_health.py", evidence=[f"receipt:{c['research_rel']}"] + firing[:8],
                    severity=c.get("severity", "P2"), job=lane))
    cw = _load(ctx.state_root / c["cron_watchdog_rel"])
    if isinstance(cw, dict) and not cw.get("__unreadable__") and \
            not _stale(ctx.now, cw.get("observed_at"), float(c.get("stale_minutes", 120))):
        for lane in cw.get("missed_lane_ids") or []:
            res.findings.append(Finding(
                fingerprint=L.fingerprint_of("cron_outage", lane), title=f"cron/lane outage: {lane} missed its schedule",
                where="scripts/cron_outage_watchdog.py", evidence=[f"receipt:{c['cron_watchdog_rel']}"],
                severity="P1", job=lane))
    if gaps and not res.findings:
        res.gap = "; ".join(gaps)
    return res


def w_main_ci(ctx: Ctx, c: Mapping[str, Any]) -> WatchResult:
    try:
        rc, out = ctx.gh(["run", "list", "--repo", c["repo"], "--branch", "main", "--limit", str(c.get("limit", 40)),
                          "--json", "headSha,status,conclusion,workflowName,url,createdAt,event"])
    except Exception as exc:  # noqa: BLE001
        return WatchResult(gap=f"gh unavailable: {type(exc).__name__}")
    if rc != 0:
        return WatchResult(gap=f"gh run list rc={rc}: {out[:120]}")
    try:
        runs = [r for r in json.loads(out or "[]") if r.get("event") in (None, "push", "workflow_dispatch", "schedule")]
    except ValueError:
        return WatchResult(gap="gh run list output not JSON")
    if not runs:
        return WatchResult(gap="no main runs")
    runs.sort(key=lambda r: str(r.get("createdAt") or ""), reverse=True)
    tip = next((r["headSha"] for r in runs if r.get("event") in (None, "push")), runs[0]["headSha"])
    latest_by_wf: dict[str, dict] = {}
    for r in runs:
        if r.get("headSha") == tip:
            latest_by_wf.setdefault(r.get("workflowName") or "?", r)
    res = WatchResult(detail={"tip": tip[:12], "workflows": len(latest_by_wf)})
    for wf, r in sorted(latest_by_wf.items()):
        if r.get("status") == "completed" and r.get("conclusion") in ("failure", "timed_out", "startup_failure"):
            res.findings.append(Finding(
                fingerprint=L.fingerprint_of("main_ci", tip, wf),
                title=f"main CI red: {wf} {r.get('conclusion')} on {tip[:12]}",
                where=f"GitHub Actions {wf} (main)", evidence=[f"url:{r.get('url')}"],
                severity=c.get("severity", "P1"), job=wf))
    return res


def w_prospectus_queue(ctx: Ctx, c: Mapping[str, Any]) -> WatchResult:
    doc = _load(ctx.state_root / c["queue_rel"])
    if doc is None:
        return WatchResult()  # no queue yet = nothing running
    if not isinstance(doc, dict) or doc.get("__unreadable__"):
        return WatchResult(gap="prospectus queue unreadable")
    res = WatchResult()
    limit = float(c.get("running_hours", 2)) * 60
    for it in doc.get("items") or []:
        if not isinstance(it, dict) or it.get("state") != "running":
            continue
        age = _age_min(ctx.now, it.get("started_at"))
        if age is not None and age > limit:
            sym = str(it.get("symbol") or "?")
            res.findings.append(Finding(
                fingerprint=L.fingerprint_of("prospectus_queue", sym, it.get("started_at")),
                title=f"prospectus job {sym} running {age / 60:.1f} h (attempts {it.get('attempts')})",
                where="scripts/lib/prospectus/store.py queue", evidence=[f"store:{c['queue_rel']}"],
                severity=c.get("severity", "P2"), job=f"prospectus:{sym}"))
    return res


def w_llm_backlog(ctx: Ctx, c: Mapping[str, Any]) -> WatchResult:
    q = ctx.llm_queue()
    if not isinstance(q, dict):
        return WatchResult(gap="llm deferral queue unavailable (DB/psycopg2)")
    pending = int(q.get("pending") or 0)
    res = WatchResult(detail={"pending": pending})
    if pending >= int(c.get("pending_threshold", 200)):
        res.findings.append(Finding(
            fingerprint=L.fingerprint_of("llm_backlog", ctx.now.astimezone(timezone.utc).date().isoformat()),
            title=f"LLM deferral backlog {pending} pending (threshold {c.get('pending_threshold')})",
            where="Postgres llm_deferred_requests (scripts/lib/llm_deferral.py)",
            evidence=[f"queue_summary:{json.dumps(q, default=str)[:300]}"], severity=c.get("severity", "P2"),
            job="llm-deferral"))
    return res


def w_cap_hits(ctx: Ctx, c: Mapping[str, Any]) -> WatchResult:
    p = ctx.state_root / c["journal_rel"]
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-int(c.get("tail_lines", 4000)):]
    except FileNotFoundError:
        return WatchResult()
    except OSError:
        return WatchResult(gap="credit journal unreadable")
    reasons = set(c.get("reasons") or [])
    since = ctx.now - timedelta(minutes=float(c.get("window_minutes", 60)))
    hits: dict[str, int] = {}
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("event") == "fallback" and row.get("reason") in reasons:
            t = L.parse_ts(row.get("at"))
            if t and t >= since:
                hits[row["reason"]] = hits.get(row["reason"], 0) + 1
    res = WatchResult(detail={"hits": hits})
    for reason, n in sorted(hits.items()):
        if n >= int(c.get("min_hits", 3)):
            res.findings.append(Finding(
                fingerprint=L.fingerprint_of("cap_hits", reason, ctx.now.astimezone(timezone.utc).date().isoformat()),
                title=f"Anthropic credit cap hit: {reason} x{n} in {c.get('window_minutes')} min",
                where="scripts/lib/anthropic_credit.py CreditBook", evidence=[f"journal:{c['journal_rel']}"],
                severity=c.get("severity", "P2"), job="anthropic-credit"))
    return res


def w_dirty_checkout(ctx: Ctx, c: Mapping[str, Any]) -> WatchResult:
    repo = c["repo"]
    try:
        rc, out = ctx.git(repo, ["status", "--porcelain=v1", "--untracked-files=normal"])
    except Exception as exc:  # noqa: BLE001
        return WatchResult(gap=f"git unavailable: {type(exc).__name__}")
    if rc != 0:
        return WatchResult(gap=f"git status rc={rc}")
    paths = sorted(line[3:] for line in out.splitlines() if line.strip())
    mem = ctx.state.setdefault("dirty_checkout", {})
    if not paths:
        mem.clear()
        return WatchResult()
    key = L.fingerprint_of("dirty_checkout", repo, *paths)
    first = mem.get(key) or L.iso(ctx.now)
    mem.clear()
    mem[key] = first
    age = _age_min(ctx.now, first) or 0.0
    res = WatchResult(detail={"paths": len(paths), "dirty_min": round(age, 1)})
    if age >= float(c.get("dirty_minutes", 30)):
        res.findings.append(Finding(
            fingerprint=key, title=f"canonical checkout dirty for {int(age)} min ({len(paths)} paths)",
            where=repo, evidence=[f"path:{p}" for p in paths[:20]], severity=c.get("severity", "P2"),
            job="canonical-checkout"))
    return res


WATCHERS: dict[str, Callable[[Ctx, Mapping[str, Any]], WatchResult]] = {
    "deploy_failures": w_deploy_failures,
    "deploy_stuck": w_deploy_stuck,
    "health_tick": w_health_tick,
    "expected_services": w_expected_services,
    "lane_health": w_lane_health,
    "main_ci": w_main_ci,
    "prospectus_queue": w_prospectus_queue,
    "llm_backlog": w_llm_backlog,
    "cap_hits": w_cap_hits,
    "dirty_checkout": w_dirty_checkout,
}


# ---------------------------------------------------------------- the run


def run(
    *,
    state_root: Path,
    incidents_dir: Path,
    cfg: Mapping[str, Any],
    apply: bool,
    now: Optional[datetime] = None,
    gh: Callable[[list], tuple[int, str]] = default_gh,
    git: Callable[[str, list], tuple[int, str]] = default_git,
    llm_queue: Callable[[], Optional[dict]] = default_llm_queue,
    only: Optional[list[str]] = None,
) -> dict:
    now = now or L.utcnow()
    state_p = incidents_dir / "watchers_state.json"
    state = _load(state_p) if apply else None
    state = state if isinstance(state, dict) and not state.get("__unreadable__") else {}
    ctx = Ctx(state_root=state_root, now=now, cfg=cfg, state=state, gh=gh, git=git, llm_queue=llm_queue)
    recs = L.load_records(incidents_dir)
    receipt: dict[str, Any] = {"schema": RECEIPT_SCHEMA, "as_of": L.iso(now), "mode": "apply" if apply else "dry_run",
                               "watchers": {}, "opened": [], "resolved": [], "would_open": [], "would_resolve": []}
    for wid, fn in WATCHERS.items():
        wc = (cfg.get("watchers") or {}).get(wid) or {}
        if only and wid not in only:
            continue
        if not wc.get("enabled", False):
            receipt["watchers"][wid] = {"enabled": False}
            continue
        try:
            res = fn(ctx, wc)
        except Exception as exc:  # noqa: BLE001 — one broken watcher never stops the others
            res = WatchResult(gap=f"watcher_error:{type(exc).__name__}:{str(exc)[:120]}")
        receipt["watchers"][wid] = {"findings": len(res.findings), "gap": res.gap, "detail": res.detail}
        live = {f.fingerprint for f in res.findings}
        for f in res.findings:
            if L.find_unresolved_by_fingerprint(recs, f.fingerprint):
                continue
            row = {"watcher": wid, "fingerprint": f.fingerprint, "title": f.title}
            if not apply:
                receipt["would_open"].append(row)
                continue
            rec, created = L.open_incident(
                source={"kind": "watcher", "watcher": wid, "job": f.job}, title=f.title, where=f.where,
                evidence=f.evidence, fingerprint=f.fingerprint, severity=f.severity, actor=f"watcher:{wid}",
                d=incidents_dir, now=now)
            if created:
                receipt["opened"].append({**row, "id": rec["id"]})
                recs[rec["id"]] = rec
        if res.gap:
            continue  # unreadable input: resolve nothing
        for r in list(recs.values()):
            src = r.get("source") or {}
            if src.get("kind") != "watcher" or src.get("watcher") != wid or r["status"] in L.TERMINAL:
                continue
            if r.get("fingerprint") in live:
                continue
            row = {"watcher": wid, "id": r["id"], "title": r["title"]}
            if not apply:
                receipt["would_resolve"].append(row)
                continue
            recs[r["id"]] = L.resolve(r["id"], actor=f"watcher:{wid}",
                                      note=f"condition cleared at {L.iso(now)} ({wid} collected without a gap)",
                                      d=incidents_dir, now=now)
            receipt["resolved"].append(row)
    if apply:
        incidents_dir.mkdir(parents=True, exist_ok=True)
        for name, body in (("watchers_state.json", state), ("watchers_last.json", receipt)):
            p = incidents_dir / name
            tmp = p.with_name(f".{name}.tmp")
            tmp.write_text(json.dumps(body, indent=1, default=str) + "\n", encoding="utf-8")
            tmp.replace(p)
    return receipt
