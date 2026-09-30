"""CIO Desk scorecard — READ_ONLY_ADVISORY live ops projection.

Aggregates existing collectors into Overview tiles (working vs not).
Never invents investable cash, never claims OBSERVED for canary/absent data.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "CIOScorecard@v1"

STATUSES = ("working", "degraded", "blocked", "dark")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _tile(
    *,
    id: str,
    title: str,
    status: str,
    verdict: str,
    metrics: list[dict[str, Any]] | None = None,
    evidence_refs: list[dict[str, Any]] | None = None,
    working: bool | None = None,
    href: str | None = None,
) -> dict[str, Any]:
    st = status if status in STATUSES else "dark"
    if working is None:
        working = True if st == "working" else (False if st in ("blocked", "dark") else None)
    return {
        "id": id,
        "title": title,
        "status": st,
        "verdict": verdict[:240],
        "metrics": metrics or [],
        "evidence_refs": evidence_refs or [],
        "working": working,
        "href": href,
    }


def _read_json(path: Path) -> Any:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def _tail_jsonl(path: Path, *, limit: int = 200, since_hours: float | None = None) -> list[dict]:
    rows: list[dict] = []
    if not path.is_file():
        return rows
    cutoff = None
    if since_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return rows
    for line in reversed(lines[-max(limit * 4, 800):]):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if cutoff is not None:
            ts = row.get("ts") or row.get("as_of") or row.get("created_at") or row.get("finished") or row.get("at")
            if ts:
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                except ValueError:
                    pass
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _desk_telegram_tile(root: Path) -> dict[str, Any]:
    receipts = _tail_jsonl(root / "data" / "cio" / "cio_telegram_receipts.jsonl", limit=80, since_hours=72)
    sends = _tail_jsonl(root / "data" / "cio" / "system_telegram_sends.jsonl", limit=80, since_hours=72)
    delivery = _tail_jsonl(root / "data" / "cio" / "cio_delivery_receipts.jsonl", limit=40, since_hours=72)
    n = len(receipts) + len(sends) + len(delivery)
    suppressed = sum(1 for r in sends if str(r.get("status") or "").lower() in ("suppressed", "denied", "failed"))
    failed = sum(1 for r in receipts if str(r.get("ok") or r.get("status") or "").lower() in ("false", "failed", "error"))
    evidence = [{"kind": "receipt", "summary": str(r)[:120]} for r in (receipts[:3] + sends[:2])]
    if n == 0:
        return _tile(
            id="desk_telegram",
            title="Desk / Telegram",
            status="dark",
            verdict="No Telegram desk receipts in the last 72h — channel idle or unobserved.",
            metrics=[{"label": "Receipts 72h", "value": 0}],
            evidence_refs=evidence,
            href="/v3/cio?tab=evidence-comms&sub=telegram-receipts",
        )
    if failed or suppressed:
        return _tile(
            id="desk_telegram",
            title="Desk / Telegram",
            status="degraded",
            verdict=f"{n} desk/Telegram events in 72h; {failed + suppressed} failed or suppressed.",
            metrics=[
                {"label": "Events 72h", "value": n},
                {"label": "Failed/suppressed", "value": failed + suppressed},
            ],
            evidence_refs=evidence,
            href="/v3/cio?tab=evidence-comms&sub=telegram-receipts",
        )
    return _tile(
        id="desk_telegram",
        title="Desk / Telegram",
        status="working",
        verdict=f"{n} desk/Telegram events in 72h with no failed/suppressed sample in the tail.",
        metrics=[{"label": "Events 72h", "value": n}],
        evidence_refs=evidence,
        href="/v3/cio?tab=evidence-comms&sub=telegram-receipts",
    )


def _hermes_tile(root: Path) -> dict[str, Any]:
    lane_doc = _read_json(root / "data" / "runtime" / "research_lane_health.json") or {}
    lanes = lane_doc.get("lanes") or {}
    if isinstance(lanes, list):
        lanes = {str(r.get("lane")): r for r in lanes if isinstance(r, dict)}
    deepseek = lanes.get("deepseek") if isinstance(lanes, dict) else {}
    hermes_q = lanes.get("cio-hermes-queue") if isinstance(lanes, dict) else {}
    coverage = lanes.get("coverage-stall") if isinstance(lanes, dict) else {}
    ok_ds = bool((deepseek or {}).get("ok", True)) if deepseek else None
    ok_hq = bool((hermes_q or {}).get("ok", True)) if hermes_q else None
    firing = list((deepseek or {}).get("firing") or []) + list((hermes_q or {}).get("firing") or [])
    cov_fire = list((coverage or {}).get("firing") or [])
    ok_24 = int((deepseek or {}).get("non_error_24h") or 0)
    attempts = int((deepseek or {}).get("attempts_24h") or 0)
    metrics = [
        {"label": "DeepSeek ok 24h", "value": ok_24},
        {"label": "Attempts 24h", "value": attempts},
    ]
    evidence = [{"kind": "lane", "id": k, "firing": (lanes.get(k) or {}).get("firing")} for k in ("deepseek", "cio-hermes-queue", "coverage-stall") if k in (lanes or {})]
    if deepseek is None and hermes_q is None and not lane_doc:
        return _tile(
            id="hermes_research",
            title="Hermes / research",
            status="dark",
            verdict="Research lane monitor status missing — cannot score Hermes health.",
            metrics=metrics,
            href="/v3/cio?tab=research",
        )
    if ok_hq is False or (ok_ds is False and ok_24 == 0):
        return _tile(
            id="hermes_research",
            title="Hermes / research",
            status="blocked",
            verdict="Research heartbeat firing: " + (", ".join(str(x) for x in firing[:4]) or "lane not ok"),
            metrics=metrics,
            evidence_refs=evidence,
            href="/v3/cio?tab=research",
        )
    if cov_fire or firing:
        return _tile(
            id="hermes_research",
            title="Hermes / research",
            status="degraded",
            verdict="Research delivering with warnings: " + (", ".join(str(x) for x in (firing + cov_fire)[:3]) or "partial"),
            metrics=metrics,
            evidence_refs=evidence,
            working=None,
            href="/v3/cio?tab=research",
        )
    if ok_24 > 0 or ok_hq is True:
        return _tile(
            id="hermes_research",
            title="Hermes / research",
            status="working",
            verdict=f"Research lanes ok — DeepSeek non-error 24h={ok_24}.",
            metrics=metrics,
            evidence_refs=evidence,
            href="/v3/cio?tab=research",
        )
    return _tile(
        id="hermes_research",
        title="Hermes / research",
        status="dark",
        verdict="No recent DeepSeek successes observed in lane status.",
        metrics=metrics,
        href="/v3/cio?tab=research",
    )


def _spine_tile(root: Path) -> dict[str, Any]:
    organic = _read_json(root / "data" / "runtime" / "spine_llm_organic.json")
    if not isinstance(organic, dict):
        try:
            from scripts.ops.spine_llm_organic_metric import measure
            organic = measure(root)
        except Exception:
            organic = {}
    org_n = int(organic.get("organic_latest_llm") or 0) if organic else 0
    canary_n = int(organic.get("canary_or_backfill_latest_llm") or 0) if organic else 0
    with_llm = int(organic.get("tips_with_latest_llm") or 0) if organic else 0
    tips = int(organic.get("spine_symbols") or 0) if organic else 0
    spine_path = root / "data" / "cio" / "security_research_spine.jsonl"
    if tips == 0 and spine_path.is_file():
        try:
            tips = sum(1 for _ in spine_path.open(encoding="utf-8", errors="ignore") if _.strip())
        except OSError:
            tips = 0
    metrics = [
        {"label": "Spine tips", "value": tips},
        {"label": "Organic LLM", "value": org_n},
        {"label": "Canary/backfill LLM", "value": canary_n},
    ]
    evidence = [{"kind": "organic_metric", "sample": (organic or {}).get("organic_symbols_sample") or []}]
    if tips == 0 and with_llm == 0 and not organic:
        return _tile(
            id="shared_spine",
            title="Shared spine",
            status="dark",
            verdict="Security research spine not observed on this host.",
            metrics=metrics,
            href="/v3/cio?tab=research",
        )
    if org_n >= 1:
        return _tile(
            id="shared_spine",
            title="Shared spine",
            status="working",
            verdict=f"Organic LLM volume OBSERVED ({org_n}); canary/backfill={canary_n}; tips≈{tips}.",
            metrics=metrics,
            evidence_refs=evidence,
            href="/v3/cio?tab=research",
        )
    if canary_n >= 1 or with_llm >= 1:
        return _tile(
            id="shared_spine",
            title="Shared spine",
            status="degraded",
            verdict=f"LLM tips present but organic=0 (canary/backfill={canary_n}) — not counted as OBSERVED organic.",
            metrics=metrics,
            evidence_refs=evidence,
            working=False,
            href="/v3/cio?tab=research",
        )
    return _tile(
        id="shared_spine",
        title="Shared spine",
        status="degraded",
        verdict=f"Spine has ~{tips} tips but no latest_llm organic volume yet.",
        metrics=metrics,
        working=None,
        href="/v3/cio?tab=research",
    )


def _decisions_tile(home: dict[str, Any] | None) -> dict[str, Any]:
    home = home or {}
    now = home.get("cio_now") or home.get("now") or {}
    decisions = now.get("decisions") if isinstance(now, dict) else None
    if decisions is None:
        decisions = home.get("decisions") or []
    if not isinstance(decisions, list):
        decisions = []
    attn = (now.get("attention") if isinstance(now, dict) else None) or home.get("attention") or {}
    material = int(attn.get("material_today") or now.get("material_today_count") or home.get("material_today_count") or 0)
    open_plans = int(attn.get("open_plans") or now.get("open_plans_count") or home.get("open_plans_count") or 0)
    n = len(decisions) if decisions else int(now.get("decision_count") or 0)
    metrics = [
        {"label": "Decisions", "value": n},
        {"label": "Material today", "value": material},
        {"label": "Open plans", "value": open_plans},
    ]
    if not home.get("ok") and not decisions and n == 0 and open_plans == 0:
        return _tile(
            id="decisions",
            title="Decisions",
            status="dark",
            verdict="CIO home projection unavailable — decisions not scored.",
            metrics=metrics,
            href="/v3/cio?tab=decisions",
        )
    stale = 0
    for d in decisions:
        if not isinstance(d, dict):
            continue
        fr = d.get("freshness")
        if isinstance(fr, dict) and str(fr.get("state") or "").upper() in ("STALE", "EXPIRED", "DARK"):
            stale += 1
        elif isinstance(fr, str) and fr.upper() in ("STALE", "EXPIRED", "DARK"):
            stale += 1
    if stale:
        return _tile(
            id="decisions",
            title="Decisions",
            status="degraded",
            verdict=f"{n} decisions surfaced; {stale} marked stale/expired freshness.",
            metrics=metrics,
            href="/v3/cio?tab=decisions",
        )
    if n or material or open_plans:
        return _tile(
            id="decisions",
            title="Decisions",
            status="working",
            verdict=f"{n} decisions · {material} material today · {open_plans} open plans.",
            metrics=metrics,
            href="/v3/cio?tab=decisions",
        )
    return _tile(
        id="decisions",
        title="Decisions",
        status="working",
        verdict="Nothing material needs a decision right now.",
        metrics=metrics,
        href="/v3/cio?tab=decisions",
    )


def _outcomes_tile(brain: dict[str, Any] | None) -> dict[str, Any]:
    brain = brain or {}
    cockpit = brain.get("learning_cockpit") or {}
    learning = brain.get("learning") or {}
    outcomes = learning.get("outcomes") or cockpit.get("outcomes") or {}
    due = int(cockpit.get("outcomes_due") or outcomes.get("due") or outcomes.get("outcomes_due") or 0)
    matured = int(outcomes.get("matured") or cockpit.get("matured_outcomes") or 0)
    frozen = int(outcomes.get("frozen") or cockpit.get("frozen_outcomes") or 0)
    influence = brain.get("memory_behavior_influence")
    if influence is None:
        influence = (brain.get("memory") or {}).get("behavior_influence") or 0
    metrics = [
        {"label": "Outcomes due", "value": due},
        {"label": "Matured", "value": matured},
        {"label": "MBI", "value": influence},
    ]
    if not brain:
        return _tile(
            id="outcomes_learning",
            title="Outcomes / learning",
            status="dark",
            verdict="Brain projection unavailable — outcomes not scored.",
            metrics=metrics,
            href="/v3/cio?tab=evidence-comms",
        )
    if due > 100 and matured == 0:
        return _tile(
            id="outcomes_learning",
            title="Outcomes / learning",
            status="degraded",
            verdict=f"{due} outcomes due; matured={matured}; memory influence stays {influence} (non-authoritative).",
            metrics=metrics,
            working=None,
            href="/v3/cio?tab=evidence-comms",
        )
    return _tile(
        id="outcomes_learning",
        title="Outcomes / learning",
        status="working" if matured or due == 0 else "degraded",
        verdict=f"Due={due} · matured={matured} · frozen={frozen} · influence={influence} (lessons stay candidates).",
        metrics=metrics,
        href="/v3/cio?tab=evidence-comms",
    )


def _platform_tile(brain: dict[str, Any] | None, health: dict[str, Any] | None) -> dict[str, Any]:
    brain = brain or {}
    serving = brain.get("_serving") or {}
    pin_match = serving.get("pin_match")
    loaded = serving.get("loaded_pin_sha") or ""
    current = serving.get("current_pin_sha") or ""
    health = health or {}
    data = health.get("data") if isinstance(health.get("data"), dict) else health
    score = data.get("overall_score") if isinstance(data, dict) else None
    status = data.get("status") if isinstance(data, dict) else None
    counts = data.get("counts") if isinstance(data, dict) else {}
    crit = int((counts or {}).get("critical") or 0)
    if crit == 0 and isinstance(data, dict):
        findings = data.get("findings") or []
        if isinstance(findings, list):
            crit = sum(1 for f in findings if isinstance(f, dict) and str(f.get("severity") or "").lower() == "critical")
    metrics = [
        {"label": "Health score", "value": score if score is not None else "n/a"},
        {"label": "Criticals", "value": crit},
        {"label": "Pin match", "value": bool(pin_match) if pin_match is not None else "n/a"},
    ]
    evidence = [{
        "kind": "pin",
        "loaded": str(loaded)[:12],
        "current": str(current)[:12],
        "health_status": status,
    }]
    if score is None and pin_match is None:
        return _tile(
            id="platform_pin",
            title="Platform / pin",
            status="dark",
            verdict="Health and pin serving metadata unavailable.",
            metrics=metrics,
            href="/v3/health",
        )
    if crit > 0 or status == "unhealthy":
        return _tile(
            id="platform_pin",
            title="Platform / pin",
            status="blocked",
            verdict=f"Health {status or 'unknown'} {score}/100 · {crit} critical · pin_match={pin_match}.",
            metrics=metrics,
            evidence_refs=evidence,
            href="/v3/health",
        )
    if status == "degraded" or pin_match is False:
        return _tile(
            id="platform_pin",
            title="Platform / pin",
            status="degraded",
            verdict=f"Health {status} {score}/100 · pin_match={pin_match}.",
            metrics=metrics,
            evidence_refs=evidence,
            href="/v3/health",
        )
    return _tile(
        id="platform_pin",
        title="Platform / pin",
        status="working",
        verdict=f"Health {status or 'ok'} {score}/100 · 0 critical · pin_match={pin_match}.",
        metrics=metrics,
        evidence_refs=evidence,
        href="/v3/health",
    )


def _blockers_top(brain: dict[str, Any] | None, limit: int = 6) -> list[str]:
    brain = brain or {}
    ov = brain.get("operator_value") or {}
    situation = brain.get("capital_situation") or {}
    raw = list(ov.get("uncertainty") or []) + list(situation.get("blockers") or []) + list(ov.get("missing_policy") or [])[:3]
    out: list[str] = []
    for item in raw:
        s = str(item or "").strip()
        if s and s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def build_scorecard(
    *,
    root: Path | None = None,
    home: dict[str, Any] | None = None,
    brain: dict[str, Any] | None = None,
    health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure-ish builder. Callers may inject home/brain/health for hermetic tests."""
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    tiles = [
        _desk_telegram_tile(root),
        _hermes_tile(root),
        _spine_tile(root),
        _decisions_tile(home),
        _outcomes_tile(brain),
        _platform_tile(brain, health),
    ]
    working_n = sum(1 for t in tiles if t.get("status") == "working")
    blocked_n = sum(1 for t in tiles if t.get("status") in ("blocked", "dark"))
    return {
        "ok": True,
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": _now_iso(),
        "memory_behavior_influence": 0,
        "financial_action": False,
        "tiles": tiles,
        "summary": {
            "working": working_n,
            "degraded": sum(1 for t in tiles if t.get("status") == "degraded"),
            "blocked_or_dark": blocked_n,
            "tile_count": len(tiles),
        },
        "blockers_top": _blockers_top(brain),
        "pin": (brain or {}).get("_serving") or {},
        "health_summary": {
            "status": ((health or {}).get("data") or health or {}).get("status") if isinstance(health, dict) else None,
            "overall_score": ((health or {}).get("data") or health or {}).get("overall_score") if isinstance(health, dict) else None,
            "counts": ((health or {}).get("data") or health or {}).get("counts") if isinstance(health, dict) else None,
        },
        "judgment_href": "/v3/cio?tab=overview",
        "note": "Ops scorecard from live receipts/lanes; gap walls are not success signals.",
    }


def get_cio_scorecard(*, root: Path | None = None) -> dict[str, Any]:
    """Live aggregation for GET /api/v3/cio/scorecard."""
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    home: dict[str, Any] | None = None
    brain: dict[str, Any] | None = None
    health: dict[str, Any] | None = None
    try:
        from scripts import api_v3_cio as cio
        try:
            home = cio.get_cio_home()
        except Exception:
            home = {"ok": False}
        try:
            brain = cio.get_cio_brain_v1()
        except Exception:
            brain = {}
    except Exception:
        home, brain = {"ok": False}, {}
    try:
        # Prefer same sources Health hub uses so "1 crit" cannot silently diverge.
        candidates = [
            root / "data" / "portfolios" / "state" / "health_agent_status.json",
            root / "data" / "runtime" / "health_agent_latest.json",
            root / "data" / "runtime" / "health_agent_status.json",
        ]
        for path in candidates:
            snap = _read_json(path)
            if isinstance(snap, dict) and (snap.get("overall_score") is not None or snap.get("status")):
                health = snap
                break
        if health is None:
            # Optional DB snapshot — fail-soft if psycopg/env unavailable
            try:
                import os
                import psycopg2
                import psycopg2.extras

                dsn = os.environ.get("DATABASE_URL") or os.environ.get("TRADEAI_DSN")
                if dsn:
                    with psycopg2.connect(dsn) as conn:
                        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                            cur.execute(
                                "SELECT overall_score, status, findings, captured_at "
                                "FROM health_agent_snapshots ORDER BY captured_at DESC LIMIT 1"
                            )
                            row = cur.fetchone()
                            if row:
                                findings = row.get("findings") or []
                                if isinstance(findings, str):
                                    try:
                                        findings = json.loads(findings)
                                    except Exception:
                                        findings = []
                                crit = sum(
                                    1
                                    for f in (findings if isinstance(findings, list) else [])
                                    if isinstance(f, dict)
                                    and str(f.get("severity") or "").lower() == "critical"
                                )
                                health = {
                                    "overall_score": row.get("overall_score"),
                                    "status": row.get("status"),
                                    "counts": {"critical": crit},
                                    "captured_at": str(row.get("captured_at") or ""),
                                }
            except Exception:
                health = None
    except Exception:
        health = None
    return build_scorecard(root=root, home=home, brain=brain, health=health)


__all__ = ["build_scorecard", "get_cio_scorecard", "SCHEMA", "AUTHORITY"]
