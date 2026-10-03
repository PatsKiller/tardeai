"""CIO Desk scorecard — READ_ONLY_ADVISORY live ops projection.

Aggregates existing collectors into Overview tiles (working vs not).
Never invents investable cash, never claims OBSERVED for canary/absent data.

IMPORTANT: get_cio_scorecard must stay FAST and must NOT call get_cio_home /
get_cio_brain_v1. Those are multi-second builders; nesting them under the
single-threaded portfolio-server wedges every feed (503 / "server busy").
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
    # Live lane JSON often parks 24h counts on coverage-stall (thesis-flat
    # monitor), while deepseek itself only carries ok/firing. Prefer deepseek
    # counts when present; fall back to coverage-stall so the tile matches the
    # verdict string (deepseek_ok_24h=N) instead of lying at 0.
    ok_24 = int((deepseek or {}).get("non_error_24h") or 0)
    attempts = int((deepseek or {}).get("attempts_24h") or 0)
    if ok_24 == 0 and attempts == 0 and coverage:
        ok_24 = int(
            (coverage or {}).get("non_error_24h")
            or (coverage or {}).get("deepseek_ok_24h")
            or 0
        )
        attempts = int((coverage or {}).get("attempts_24h") or ok_24 or 0)
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
    tips = int(organic.get("spine_symbols") or organic.get("tips") or 0) if organic else 0
    with_llm = int(organic.get("tips_with_latest_llm") or 0) if organic else 0
    metrics = [
        {"label": "Spine tips", "value": tips},
        {"label": "Organic LLM", "value": org_n},
        {"label": "Canary/backfill LLM", "value": canary_n},
    ]
    evidence = [{"kind": "organic_metric", "path": "data/runtime/spine_llm_organic.json", "sample": (organic or {}).get("organic_symbols_sample")}]
    if not organic:
        return _tile(
            id="shared_spine",
            title="Shared spine",
            status="dark",
            verdict="Organic LLM volume metric absent — spine not scored as live.",
            metrics=metrics,
            href="/v3/cio?tab=research",
        )
    if org_n >= 1:
        return _tile(
            id="shared_spine",
            title="Shared spine",
            status="working",
            verdict=f"Organic LLM volume {org_n} (tips with LLM={with_llm}; canary/backfill={canary_n} separate).",
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
    learning = brain.get("learning") or {}
    cockpit = brain.get("learning_cockpit") or {}
    outcomes = learning.get("outcomes") or cockpit.get("outcomes") or {}
    due = int(cockpit.get("outcomes_due") or outcomes.get("due") or outcomes.get("outcomes_due") or 0)
    matured = int(outcomes.get("matured") or cockpit.get("matured_outcomes") or 0)
    frozen = int(outcomes.get("frozen") or cockpit.get("frozen_outcomes") or 0)
    not_resolvable = int(cockpit.get("not_resolvable") or 0)
    influence = brain.get("memory_behavior_influence")
    if influence is None:
        influence = (brain.get("memory") or {}).get("behavior_influence") or 0
    metrics = [
        {"label": "Outcomes due", "value": due},
        {"label": "Matured", "value": matured},
        {"label": "Not price-resolvable", "value": not_resolvable},
        {"label": "MBI", "value": influence},
    ]
    if not brain or (not learning and not cockpit and "_serving" not in brain and "learning" not in brain):
        # Light path often only has _serving — outcomes stay dark honestly.
        if not learning and not cockpit:
            return _tile(
                id="outcomes_learning",
                title="Outcomes / learning",
                status="dark",
                verdict="Learning projection not loaded on the light scorecard path — open Full brain for detail.",
                metrics=metrics,
                href="/v3/cio?tab=evidence-comms&sub=full-brain",
            )
    if due > 100 and matured == 0:
        return _tile(
            id="outcomes_learning",
            title="Outcomes / learning",
            status="degraded",
            verdict=f"{due} outcomes due; matured={matured}; memory influence stays {influence} (non-authoritative).",
            metrics=metrics,
            working=None,
            href="/v3/cio?tab=evidence-comms&sub=full-brain",
        )
    return _tile(
        id="outcomes_learning",
        title="Outcomes / learning",
        status="working" if matured or due == 0 else "degraded",
        verdict=(f"Due={due} · matured={matured} · not price-resolvable={not_resolvable} · frozen={frozen} · "
                 f"influence={influence} (lessons stay candidates)."),
        metrics=metrics,
        href="/v3/cio?tab=evidence-comms&sub=full-brain",
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


def _light_serving(root: Path) -> dict[str, Any]:
    """Pin metadata without building the full brain projection."""
    source = None
    for p in (
        root / "SOURCE_COMMIT",
        root / "BUILD_SHA",
        root / "GIT_SHA",
    ):
        try:
            if p.is_file():
                source = p.read_text(encoding="utf-8").strip()[:40]
                break
        except OSError:
            continue
    current_link = Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT"
    current_sha = None
    try:
        resolved = current_link.resolve()
        name = resolved.name
        current_sha = name.split("-")[0] if name else None
        sc = resolved / "SOURCE_COMMIT"
        if sc.is_file():
            current_sha = sc.read_text(encoding="utf-8").strip()[:40] or current_sha
    except OSError:
        pass
    pin_match = None
    if source and current_sha:
        pin_match = source[:12] == current_sha[:12]
    return {
        "loaded_pin_sha": source,
        "current_pin_sha": current_sha,
        "pin_match": pin_match,
    }


def stamp_home_attention(home: dict[str, Any] | None, *, root: Path | None = None) -> None:
    """Best-effort write of a thin home attention slice for the light scorecard.

    Called after get_cio_home builds successfully. Never raises. Never nests
    get_cio_home / get_cio_brain — this is a side-effect stamp only.
    """
    if not isinstance(home, dict) or not home.get("ok", True):
        return
    try:
        root = Path(root) if root else Path(__file__).resolve().parents[2]
        now = home.get("cio_now") or home.get("now") or {}
        if not isinstance(now, dict):
            now = {}
        attn = now.get("attention") if isinstance(now.get("attention"), dict) else {}
        if not attn and isinstance(home.get("attention"), dict):
            attn = home["attention"]
        decision_count = int(now.get("decision_count") or 0)
        if not decision_count:
            decs = now.get("decisions")
            if isinstance(decs, list):
                decision_count = len(decs)
        material = int(
            attn.get("material_today")
            or now.get("material_today_count")
            or home.get("material_today_count")
            or 0
        )
        open_plans = int(
            attn.get("open_plans")
            or now.get("open_plans_count")
            or home.get("open_plans_count")
            or 0
        )
        slice_doc = {
            "ok": True,
            "as_of": home.get("as_of") or _now_iso(),
            "source": "stamp_home_attention",
            "cio_now": {
                "decision_count": decision_count,
                "material_today_count": material,
                "open_plans_count": open_plans,
                "attention": {
                    "material_today": material,
                    "open_plans": open_plans,
                    "investment_decisions": attn.get("investment_decisions", decision_count),
                },
            },
        }
        path = root / "data" / "runtime" / "cio_home_attention.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(slice_doc, separators=(",", ":")), encoding="utf-8")
    except Exception:
        return


def _light_home(root: Path) -> dict[str, Any]:
    """Optional attention snapshot from disk — never rebuilds CIO home."""
    for rel in (
        "data/runtime/cio_home_attention.json",
        "data/cio/cio_home_attention.json",
        "data/runtime/cio_scorecard_home_slice.json",
    ):
        doc = _read_json(root / rel)
        if isinstance(doc, dict) and doc:
            if "ok" not in doc:
                doc = {**doc, "ok": True}
            return doc
    return {"ok": False}


def _light_brain(root: Path) -> dict[str, Any]:
    """Learning/outcomes slice from disk + serving pin — never rebuilds brain."""
    brain: dict[str, Any] = {"_serving": _light_serving(root)}
    for rel in (
        "data/runtime/cio_brain_learning_slice.json",
        "data/cio/cio_brain_learning_slice.json",
        "data/runtime/learning_cockpit.json",
    ):
        doc = _read_json(root / rel)
        if isinstance(doc, dict) and doc:
            if "learning" in doc or "learning_cockpit" in doc:
                brain.update({k: doc[k] for k in ("learning", "learning_cockpit", "memory_behavior_influence", "operator_value", "capital_situation") if k in doc})
            else:
                brain["learning_cockpit"] = doc
            break
    return brain


def _light_health(root: Path) -> dict[str, Any] | None:
    """File-only health snapshot — no DB connect (can hang under wedge)."""
    for path in (
        root / "data" / "portfolios" / "state" / "health_agent_status.json",
        root / "data" / "runtime" / "health_agent_latest.json",
        root / "data" / "runtime" / "health_agent_status.json",
        Path.home() / "trade-ai-releases" / "persistent-state" / "data" / "portfolios" / "state" / "health_agent_status.json",
    ):
        snap = _read_json(path)
        if isinstance(snap, dict) and (snap.get("overall_score") is not None or snap.get("status")):
            return snap
    return None


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
        "path": "light",
    }


def get_cio_scorecard(*, root: Path | None = None) -> dict[str, Any]:
    """Live aggregation for GET /api/v3/cio/scorecard.

    Disk/runtime collectors only. Never nests get_cio_home / get_cio_brain_v1.
    """
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    home = _light_home(root)
    brain = _light_brain(root)
    health = _light_health(root)
    return build_scorecard(root=root, home=home, brain=brain, health=health)


__all__ = [
    "build_scorecard",
    "get_cio_scorecard",
    "stamp_home_attention",
    "SCHEMA",
    "AUTHORITY",
]
