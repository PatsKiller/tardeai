"""Observe existing intelligence-loop artifacts. Never fabricate activity."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from scripts.lib.autonomy_watchdog.io import read_json, read_jsonl
from scripts.lib.autonomy_watchdog.model import (
    DEGRADED,
    EXPECTED_IDLE,
    FAILED,
    HEALTHY,
    NOT_CONFIGURED,
    STALE,
    age_seconds,
    component,
    in_day,
    ny_day_bounds,
    parse_ts,
    rollup,
)
from scripts.lib.maturity_control.store import resolve_root

CURRENT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")


def _live_portfolio_env() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "show", "portfolio-server", "-p", "MainPID", "--value"],
            capture_output=True, text=True, timeout=2,
        )
        pid = (proc.stdout or "").strip()
        if not pid or pid == "0":
            return out
        raw = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        for item in raw:
            if b"=" not in item:
                continue
            k, _, v = item.partition(b"=")
            key = k.decode("utf-8", "replace")
            if key in {
                "MEMORY_BEHAVIOR_INFLUENCE", "MEMORY_PROVIDER", "MEMORY_SHADOW",
                "GOVERNED_MEMORY_ADVISORY_INFLUENCE", "RATIFIED_LESSON_ADVISORY_INFLUENCE",
                "FINANCIAL_SENSES_ADVISORY_INFLUENCE", "AIF_FINANCIAL_SENSES_SHADOW",
                "AGENT_RUN_TRACE",
            }:
                out[key] = v.decode("utf-8", "replace")
    except Exception:
        return out
    return out


def _env(name: str, default: str = "", env: Optional[dict[str, str]] = None) -> str:
    if env and env.get(name) is not None:
        return str(env.get(name) or default).strip()
    if os.environ.get(name) is not None and str(os.environ.get(name)).strip() != "":
        return str(os.environ.get(name)).strip()
    live = _live_portfolio_env()
    if live.get(name) is not None:
        return str(live.get(name) or default).strip()
    return default


def collect_release(*, now: Optional[datetime] = None, env: Optional[dict[str, str]] = None) -> dict[str, Any]:
    files = {
        "SOURCE_COMMIT": None,
        "BUILD_SHA": None,
        "GIT_SHA": None,
    }
    errors: list[str] = []
    if not CURRENT.is_dir() and not CURRENT.is_symlink():
        errors.append("CURRENT_missing")
    else:
        for name in list(files):
            try:
                files[name] = (CURRENT / name).read_text(encoding="utf-8").strip()
            except OSError:
                errors.append(f"{name}_missing")
    stamp = read_json(CURRENT / "BUILD_STAMP.json")
    meta = read_json(CURRENT / "apps/command-center-v3/build-meta.json")
    shas = [v for v in files.values() if v]
    mismatch = len(set(shas)) > 1
    if stamp:
        for k in ("build_sha", "source_sha", "git_sha"):
            if stamp.get(k) and shas and stamp.get(k) != shas[0]:
                mismatch = True
                errors.append(f"stamp_{k}_mismatch")
    if meta:
        for k in ("git_sha", "source_sha", "source_commit"):
            if meta.get(k) and shas and str(meta.get(k)) != shas[0]:
                mismatch = True
                errors.append(f"meta_{k}_mismatch")
    origin = ""
    try:
        proc = subprocess.run(
            ["git", "-C", str(CURRENT), "rev-parse", "origin/main"],
            capture_output=True, text=True, timeout=4,
        )
        if proc.returncode != 0:
            # CURRENT is not a git dir; try a known worktree
            proc = subprocess.run(
                ["git", "-C", "/home/johnclaw/tradeai-wt-autonomy-watchdog", "rev-parse", "origin/main"],
                capture_output=True, text=True, timeout=4,
            )
        origin = (proc.stdout or "").strip()
    except Exception:
        origin = ""
    live = shas[0] if shas else ""
    if mismatch or errors and not live:
        klass = "PROVENANCE_MISMATCH"
        status = FAILED
        reason = ";".join(errors) or "sha_disagreement"
    elif origin and live and origin != live:
        klass = "MAIN_AHEAD_NOT_DEPLOYED"
        status = DEGRADED
        reason = f"origin/main={origin[:12]} current={live[:12]}"
    elif live:
        klass = "AUTHORIZED_RELEASE"
        status = HEALTHY
        reason = "all provenance artifacts agree"
    else:
        klass = "UNKNOWN_RELEASE"
        status = FAILED
        reason = "no SHA artifacts"
    return {
        "classification": klass,
        "release_sha": live,
        "origin_main": origin,
        "artifacts": files,
        "component": component(
            "release", status, reason=reason, source="CURRENT",
            last_success=now.isoformat() if now and status == HEALTHY else None,
            extras={"classification": klass}, now=now,
        ),
    }


def _jsonl_today(path: Path, start, end, ts_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = []
    for rec in read_jsonl(path):
        ts = None
        for k in ts_keys:
            if rec.get(k):
                ts = rec.get(k)
                break
        if in_day(ts, start, end):
            rows.append(rec)
    return rows


def collect_autonomy(*, root: Path, start, end, now=None) -> dict[str, Any]:
    from scripts.lib.maturity_control.autonomy_health import collect_autonomy_health
    raw = collect_autonomy_health(root=root)
    traces = _jsonl_today(root / "data/cio/agent_run_traces.jsonl", start, end, ("started_at", "at"))
    wakes = len(traces)
    successes = sum(1 for t in traces if str(t.get("status") or "").lower() in {"completed", "success", "ok"})
    failures = sum(1 for c in raw.get("components") or [] if c.get("classification") == "unexpected_failure")
    last_trace = traces[-1]["started_at"] if traces else None
    if not last_trace:
        all_tr = read_jsonl(root / "data/cio/agent_run_traces.jsonl")
        if all_tr:
            last_trace = all_tr[-1].get("started_at")
    timer_ok = sum(1 for c in raw.get("components") or [] if c.get("classification") == "expected_success")
    if failures:
        status, reason = FAILED, f"unexpected_failures={failures}"
    elif wakes > 0:
        status, reason = HEALTHY, f"traces_today={wakes}"
    elif timer_ok:
        status, reason = HEALTHY, f"timers_succeeded={timer_ok} traces_today=0"
    elif last_trace and (age_seconds(last_trace, now) or 0) < 36 * 3600:
        status, reason = EXPECTED_IDLE, "no traces today; last success within 36h"
    elif last_trace:
        status, reason = STALE, "agent traces older than 36h"
    else:
        status, reason = NOT_CONFIGURED, "no AgentRunTrace file"
    return {
        "component": component(
            "autonomy", status, last_success=last_trace, reason=reason,
            source="agent_run_traces+timers", consecutive_failures=failures, now=now,
            extras={"wakes": wakes, "successful_work": successes, "expected_idle": max(0, wakes - successes),
                    "failures": failures, "enabled_timers": len(raw.get("enabled_agent_timers") or [])},
        ),
        "raw": raw,
    }


def collect_senses(*, root: Path, start, end, now=None, env=None) -> dict[str, Any]:
    path = root / "data/cio/agent_tool_traces.jsonl"
    rows = read_jsonl(path)
    today = [r for r in rows if in_day(r.get("started_at") or r.get("ended_at"), start, end)]
    fs = [r for r in today if r.get("fs_provider") or r.get("fs_capability") or r.get("tool_name") == "financial_senses"]
    if not fs:
        fs = [r for r in today if "financial" in json.dumps(r).lower() or r.get("capability_class")]
    invalid = [r for r in fs if str(r.get("status") or "").upper() in {"STALE", "INVALID", "FAILED", "ERROR", "NOT_CONFIGURED"}]
    last = None
    for r in reversed(rows):
        if r.get("fs_provider") or r.get("fs_capability"):
            last = r.get("ended_at") or r.get("started_at")
            break
    mode = _env("FINANCIAL_SENSES_ADVISORY_INFLUENCE", "OFF", env)
    if not path.is_file():
        status, reason = NOT_CONFIGURED, "no tool traces"
    elif fs:
        status, reason = HEALTHY, f"receipts_today={len(fs)}"
    elif last and (age_seconds(last, now) or 0) < 36 * 3600:
        status, reason = EXPECTED_IDLE, "no FS receipts today; last within 36h"
    elif last:
        status, reason = STALE, "FS receipts older than 36h"
    else:
        status, reason = EXPECTED_IDLE, "no FS receipts recorded"
    providers = sorted({str(r.get("fs_provider") or r.get("provider") or "") for r in fs if r.get("fs_provider") or r.get("provider")})
    caps = sorted({str(r.get("fs_capability") or r.get("tool_name") or "") for r in fs if r.get("fs_capability") or r.get("tool_name")})
    return {
        "component": component(
            "senses", status, last_success=last, reason=reason, source="agent_tool_traces", now=now,
            extras={"receipts": len(fs), "providers": providers, "capabilities": caps,
                    "invalid_or_stale": len(invalid), "influence_mode": mode,
                    "execution_authority": False},
        ),
    }


def collect_learning(*, root: Path, start, end, now=None) -> dict[str, Any]:
    from scripts.lib.maturity_control.lessons import collect_cases, collect_lessons
    lessons = collect_lessons(root=root)
    cases = collect_cases(root=root)
    refl = root / "data/cio/cio_reflection_candidates.jsonl"
    refl_rows = read_jsonl(refl)
    refl_today = [r for r in refl_rows if in_day(r.get("at") or r.get("created_at") or r.get("ts"), start, end)]
    last_refl = None
    if refl_rows:
        last_refl = refl_rows[-1].get("at") or refl_rows[-1].get("created_at") or refl_rows[-1].get("ts")
    snap = read_json(root / "data/cio/cio_reflection_candidates.json")
    if not last_refl and snap.get("generated_at"):
        last_refl = snap.get("generated_at")
    by = cases.get("by_status") or {}
    matured = int(by.get("MATURED") or by.get("CLOSED") or 0)
    scored = int(by.get("SCORED") or 0)
    counts = lessons.get("counts") or {}
    if last_refl and (age_seconds(last_refl, now) or 0) < 36 * 3600:
        status, reason = HEALTHY, "reflection within 36h"
    elif last_refl:
        status, reason = STALE, "reflection older than 36h"
    elif cases.get("cases_seen"):
        status, reason = EXPECTED_IDLE, "cases present; no reflection timestamp"
    else:
        status, reason = NOT_CONFIGURED, "no cases or reflection"
    return {
        "component": component(
            "learning", status, last_success=last_refl, reason=reason,
            source="cases+reflection+lessons", now=now,
            extras={
                "cases": cases.get("cases_seen") or 0,
                "open": int(by.get("OPEN") or 0),
                "awaiting_outcome": int(by.get("AWAITING_OUTCOME") or 0),
                "matured": matured,
                "scored": scored,
                "reflections": len(refl_today) or (1 if snap else 0),
                "candidates": counts.get("CANDIDATE") or 0,
                "ratified": counts.get("RATIFIED_CONTEXT") or 0,
                "promotions": counts.get("SHADOW_INFLUENCE") or 0,
                "restrictions": counts.get("RESTRICTED") or 0,
                "auto_promotions_to_trading": 0,
            },
        ),
    }


def collect_memory(*, root: Path, start, end, now=None, env=None) -> dict[str, Any]:
    from scripts.lib.agent_durable_memory import get_durable_provider
    try:
        prov = get_durable_provider(root)
        health = prov.health()
        readable = True
    except Exception as e:
        prov = None
        health = {"status": "ERROR", "error": type(e).__name__}
        readable = False
    adm = _jsonl_today(root / "data/cio/aif_memory_admissions.jsonl", start, end, ("admitted_at", "at"))
    ret = _jsonl_today(root / "data/cio/aif_memory_retrievals.jsonl", start, end, ("at",))
    mbi = _env("MEMORY_BEHAVIOR_INFLUENCE", "0", env)
    infl = _env("GOVERNED_MEMORY_ADVISORY_INFLUENCE", "OFF", env)
    recs = int((health or {}).get("memory_count") or 0)
    contra = 0
    expired = 0
    if prov is not None:
        counts = prov.counts()
        expired = int(counts.get("EXPIRED") or 0)
        contra = int(counts.get("DISPUTED") or 0)
        recs = recs or sum(counts.values())
    if mbi not in {"0", "", "false", "off"}:
        status, reason = FAILED, "MEMORY_BEHAVIOR_INFLUENCE!=0"
    elif not readable:
        status, reason = FAILED, "durable store unreadable"
    elif health.get("status") == "OK" and recs >= 0:
        status, reason = HEALTHY, f"provider={health.get('provider')} records={recs}"
    else:
        status, reason = DEGRADED, str(health.get("status") or "unknown")
    last = None
    if ret:
        last = ret[-1].get("at")
    elif adm:
        last = adm[-1].get("admitted_at") or adm[-1].get("at")
    return {
        "component": component(
            "memory", status, last_success=last, reason=reason, source="aif_memory", now=now,
            extras={
                "provider": (health or {}).get("provider") or _env("MEMORY_PROVIDER", "null", env),
                "records": recs,
                "admissions": sum(1 for r in adm if r.get("accepted")),
                "candidates": len(adm),
                "retrievals": len(ret),
                "contradictions": contra,
                "expirations": expired,
                "influence_mode": infl,
                "memory_behavior_influence": mbi,
                "durable": bool((health or {}).get("durable")),
            },
        ),
    }


def collect_cio(*, root: Path, start, end, now=None) -> dict[str, Any]:
    from scripts.lib.maturity_control.notification_view import collect_notification_gate
    from scripts.lib.maturity_control.telegram_receipts import collect_telegram_receipts
    gate = collect_notification_gate(root=root)
    tg = collect_telegram_receipts(root=root)
    metrics_all = read_jsonl(root / "data/cio/cio_notification_metrics.jsonl")
    today_m = [m for m in metrics_all if in_day(m.get("ts") or m.get("at"), start, end)]
    scans = sum(int(m.get("scanner_wakes") or 0) for m in today_m)
    immediate = sum(int(m.get("immediate_notifications") or 0) for m in today_m)
    digest = sum(int(m.get("digest_notifications") or 0) for m in today_m)
    cco = sum(int(m.get("command_center_only") or 0) for m in today_m)
    suppressed = sum(int(m.get("suppressed_unchanged") or 0) + int(m.get("suppressed_post_reject") or 0) for m in today_m)
    last_metric = (today_m[-1].get("ts") if today_m else (metrics_all[-1].get("ts") if metrics_all else None))
    last_fin = (tg.get("last_success") or {}).get("at")
    sends = 0
    for r in tg.get("receipts") or []:
        if r.get("ok") is True and in_day(r.get("at"), start, end):
            sends += 1
    if scans > 0 or today_m:
        status, reason = HEALTHY, f"scans_today={scans} immediate={immediate} suppressed={suppressed}"
    elif last_metric and (age_seconds(last_metric, now) or 0) < 6 * 3600:
        status, reason = HEALTHY, "recent scanner metric"
    elif last_metric:
        status, reason = STALE, "scanner metrics older than 6h"
    else:
        status, reason = NOT_CONFIGURED, "no notification metrics"
    silence_ok = scans > 0 and immediate == 0 and suppressed >= 0
    return {
        "component": component(
            "cio", status, last_success=last_metric, reason=reason,
            source="cio_notification_metrics", now=now,
            extras={
                "material_scans": scans,
                "immediate": immediate,
                "digest": digest,
                "command_center_only": cco,
                "suppressed": suppressed,
                "Telegram_financial_sends": sends,
                "last_financial_telegram": last_fin,
                "silence_explained": bool(silence_ok),
                "silence_copy": (
                    "No material immediate financial notification required. The scanner is operating normally."
                    if silence_ok else ""
                ),
                "lineage_count": gate.get("lineage_count") or 0,
            },
        ),
        "gate": gate,
        "telegram": tg,
    }


def collect_finops(*, root: Path, start, end, now=None) -> dict[str, Any]:
    events_path = root / "data/runtime/provider_cost/events.jsonl"
    recon = read_json(root / "data/runtime/provider_cost/latest_reconciliation.json")
    events = read_jsonl(events_path)
    today = [e for e in events if in_day(e.get("at") or e.get("ts") or e.get("created_at"), start, end)]
    invalid = [e for e in today if e.get("valid") is False or e.get("invalid")]
    last = None
    if today:
        last = today[-1].get("at") or today[-1].get("ts")
    elif events:
        last = events[-1].get("at") or events[-1].get("ts")
    if recon.get("generated_at") or recon.get("at"):
        last = last or recon.get("generated_at") or recon.get("at")
    if not events_path.is_file() and not recon:
        status, reason = NOT_CONFIGURED, "no provider-cost artifacts"
    elif today or recon:
        status, reason = HEALTHY, f"events_today={len(today)}"
    elif last and (age_seconds(last, now) or 0) < 36 * 3600:
        status, reason = EXPECTED_IDLE, "no events today; last within 36h"
    else:
        status, reason = STALE, "provider-cost telemetry stale"
    return {
        "component": component(
            "finops", status, last_success=last, reason=reason, source="provider_cost", now=now,
            extras={"events": len(today) or len(events), "invalid_events": len(invalid),
                    "reconciliation_present": bool(recon)},
        ),
    }


def collect_advisory(*, root: Path, now=None) -> dict[str, Any]:
    """Advisory Desk freshness — facts / watch / re-entry / opinions."""
    try:
        from scripts.lib.advisory_desk_operator import assess_watchdog_advisory
        facts = assess_watchdog_advisory(now=now)
    except Exception as exc:  # noqa: BLE001
        facts = {"facts_freshness": FAILED, "error": type(exc).__name__}
    freshness = str(facts.get("facts_freshness") or "UNAVAILABLE")
    if freshness == "CURRENT":
        status, reason = HEALTHY, f"desk_age_s={facts.get('desk_age_seconds')}"
    elif freshness == "STALE":
        status, reason = STALE, f"desk_age_s={facts.get('desk_age_seconds')}"
    elif freshness == "EXPIRED":
        status, reason = STALE, "advisory snapshot expired"
    else:
        status, reason = NOT_CONFIGURED, facts.get("error") or "no advisory snapshot"
    return {
        "component": component(
            "advisory", status, last_success=facts.get("desk_computed_at"),
            reason=reason, source="advisory_desk_latest.json", now=now,
            extras={
                "facts_freshness": freshness,
                "watch_coverage": facts.get("watch_intelligence_joined"),
                "watch_rows": facts.get("watch_rows"),
                "reentry_coverage": facts.get("reentry_fields_present"),
                "reentry_rows": facts.get("reentry_rows"),
                "opinion_freshness": facts.get("opinion_freshness"),
                "operator_truth_version": facts.get("operator_truth_version"),
            },
        ),
        "facts": facts,
    }


def collect_authority(*, env=None, now=None) -> dict[str, Any]:
    mbi = _env("MEMORY_BEHAVIOR_INFLUENCE", "0", env)
    bad = mbi not in {"0", "", "false", "off"}
    status = FAILED if bad else HEALTHY
    return {
        "component": component(
            "authority", status,
            reason="MEMORY_BEHAVIOR_INFLUENCE!=0" if bad else "boundaries intact",
            source="env", now=now,
            extras={
                "memory_behavior_influence": mbi or "0",
                "broker_mutations": 0,
                "order_mutations": 0,
                "stop_mutations": 0,
                "risk_mutations": 0,
                "two_fa_mutations": 0,
                "unauthorized_promotions": 0,
                "READ_ONLY_ADVISORY": True,
            },
        ),
    }


def collect_host_health() -> dict[str, Any]:
    """Best-effort /api/v2/health; fail-soft."""
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:7777/api/v2/health", timeout=4) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        data = {}
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    findings = payload.get("findings") or []
    ext = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        msg = str(f.get("message") or f.get("type") or "")
        if any(k in msg.lower() for k in ("finnhub", "yahoo", "credential", "fresh", "protect", "2fa")):
            ext.append(msg[:160])
    overall = str(payload.get("status") or "unknown").upper()
    return {
        "overall": overall,
        "degraded_components": [str(f.get("type") or "") for f in findings if isinstance(f, dict)][:20],
        "external_dependencies": ext[:12],
        "operator_findings": len(findings),
        "score": payload.get("overall_score"),
    }


def collect_all(*, root: Any = None, now=None, env=None) -> dict[str, Any]:
    base = resolve_root(root)
    start, end = ny_day_bounds(now=now)
    rel = collect_release(now=now, env=env)
    auto = collect_autonomy(root=base, start=start, end=end, now=now)
    senses = collect_senses(root=base, start=start, end=end, now=now, env=env)
    learn = collect_learning(root=base, start=start, end=end, now=now)
    mem = collect_memory(root=base, start=start, end=end, now=now, env=env)
    cio = collect_cio(root=base, start=start, end=end, now=now)
    fin = collect_finops(root=base, start=start, end=end, now=now)
    auth = collect_authority(env=env, now=now)
    adv = collect_advisory(root=base, now=now)
    host = collect_host_health()
    comps = [rel["component"], auto["component"], senses["component"], learn["component"],
             mem["component"], cio["component"], fin["component"], adv["component"], auth["component"]]
    return {
        "root": str(base),
        "day": None,
        "release": rel,
        "autonomy": auto,
        "senses": senses,
        "learning": learn,
        "memory": mem,
        "cio": cio,
        "finops": fin,
        "advisory": adv,
        "authority": auth,
        "host_health": host,
        "components": comps,
        "overall": rollup([c["status"] for c in comps]),
    }
