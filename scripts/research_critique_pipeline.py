"""research_critique_pipeline.py — Librarian + taxonomy critique and scoring.

The Hermes librarian (quality/evidence rules) and Iris taxonomy (3-axis fit) jointly
rate curator outputs: watch_directives, staged prospects, and fresh research rows.
Scores are persisted on directive spec + hermes_validation_findings for review/reject.

The librarian flags stale data, auto-archives curator-owned rows, and purges archived
rows after retention (hermes_validation_findings.stale_data for audit trail).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "runtime" / "research_critique_state.json"
CRITIQUE_LATEST = ROOT / "data" / "runtime" / "research_critique_latest.json"
CONSCIOUSNESS = ROOT / "data" / "runtime" / "hermes_consciousness_latest.json"
PY = str(ROOT / ".venv" / "bin" / "python")

CRITIQUE_SPEC_KEYS = (
    "librarian_score", "librarian_verdict", "librarian_critique",
    "taxonomy_score", "taxonomy_verdict", "taxonomy_tags", "taxonomy_critique",
    "composite_score", "composite_verdict", "critique_rated_at",
    "librarian_stale_flag", "stale_reasons", "removal_recommended_at",
)

GENERIC_LABELS = frozenset({
    "earnings", "news momentum", "youtube discovery", "regulatory", "analyst", "manda", "sector", "social",
})
RETIREMENT_NOISE = re.compile(
    r"\b(medicare|medicaid|ssdi|roth|irmaa|retirement|estate|trust|mapt|annuit)\b", re.I,
)
MARKET_SECTOR_SLUGS = {
    "technology", "ai_chips", "ai_datacenter", "defense", "energy", "healthcare",
    "financials", "real_estate", "industrials", "consumer", "utilities", "materials",
}

STALE_FRESHNESS_DAYS = 14
STALE_UNSERVICED_DAYS = 30
STALE_NO_HITS_DAYS = 45
STALE_STAGING_DAYS = 21
STALE_PAUSED_COLD_DAYS = 30
STALE_LOW_CONF_DAYS = 30
LOW_CONFIDENCE = 0.35

CURATOR_CREATORS = frozenset({"think_tank", "sector_universe"})
RETENTION_DIRECTIVE_DAYS = 60
RETENTION_RESEARCH_DAYS = 45
RETENTION_STAGING_DAYS = 14
RETENTION_FINDING_DAYS = 30
ARCHIVE_AGENT = "librarian_auto"


def _clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


def librarian_score(*, kind: str, label: str, spec: dict, rationale: str = "") -> dict:
    """Rule-based librarian quality score (0-100) + critique notes."""
    score = 62.0
    critiques: list[str] = []
    blob = f"{label} {rationale} {' '.join(spec.get('keywords') or [])}".lower()
    norm_label = re.sub(r"^(trend|sector|industry)\s+", "", label.lower()).strip()

    if norm_label in GENERIC_LABELS:
        score -= 35
        critiques.append("Generic pipeline label — weak investable theme")
    if RETIREMENT_NOISE.search(blob) and kind in ("sector", "trend") and "sector_universe" in str(spec.get("think_tank_source", "")):
        score -= 25
        critiques.append("Retirement/tax noise in market curator directive")
    if not (spec.get("keywords") or []):
        score -= 15
        critiques.append("Missing keywords")
    elif len(spec.get("keywords") or []) >= 4:
        score += 8
    if spec.get("seed_symbols"):
        score += 6
    if spec.get("finviz_sector") or spec.get("finviz_industry"):
        score += 10
    if spec.get("evidence") or spec.get("think_tank_source"):
        score += 4
    if spec.get("change_pct") is not None:
        score += 5
    if len(norm_label) < 5:
        score -= 20
        critiques.append("Label too short/vague")
    if "think_tank_source" in spec and "llm" in str(spec.get("think_tank_source", "")):
        score += 5

    score = _clamp(score)
    verdict = "approve" if score >= 65 else "review" if score >= 40 else "reject"
    return {"librarian_score": round(score, 1), "librarian_critique": critiques, "librarian_verdict": verdict}


def taxonomy_score(*, kind: str, label: str, spec: dict) -> dict:
    """Taxonomy axis fit score (0-100) using classify_fast."""
    import taxonomy

    text = f"{label} {' '.join(spec.get('keywords') or [])} {spec.get('finviz_sector') or ''} {spec.get('finviz_industry') or ''}"
    tags = taxonomy.classify_fast(text)
    score = 55.0
    critiques: list[str] = []

    content = tags.get("content")
    sector = tags.get("sector")
    lifecycle = tags.get("lifecycle")

    is_market = kind in ("sector", "trend") and (
        spec.get("finviz_sector") or spec.get("finviz_industry")
        or "sector_universe" in str(spec.get("think_tank_source", ""))
        or "rs_" in str(spec.get("think_tank_source", ""))
    )

    if is_market:
        if content in ("retirement_planning", "tax_strategy", "disability_retirement", "estate_trust"):
            score -= 30
            critiques.append(f"Taxonomy misfit: market theme classified as {content}")
        elif content in ("catalyst_news", "technical_analysis", "macro_economics", "etf_indexing"):
            score += 12
        if kind == "sector" and (sector or spec.get("finviz_sector")):
            score += 15
        if "industry" in label.lower() and (sector or content):
            score += 10
        if not any(tags.values()):
            score -= 12
            critiques.append("No taxonomy axis matched")
    else:
        if any(tags.values()):
            score += 10

    if lifecycle and is_market and lifecycle not in ("accumulation", "income_generation"):
        score -= 8
        critiques.append(f"Lifecycle {lifecycle} unusual for market rotation theme")

    score = _clamp(score)
    verdict = "approve" if score >= 60 else "review" if score >= 38 else "reject"
    return {
        "taxonomy_score": round(score, 1),
        "taxonomy_tags": tags,
        "taxonomy_critique": critiques,
        "taxonomy_verdict": verdict,
    }


def composite_score(librarian: dict, taxonomy: dict) -> dict:
    ls = librarian.get("librarian_score", 50)
    ts = taxonomy.get("taxonomy_score", 50)
    composite = round(ls * 0.55 + ts * 0.45, 1)
    verdict = "approve" if composite >= 62 else "review" if composite >= 42 else "reject"
    return {"composite_score": composite, "composite_verdict": verdict}


def _norm_theme_label(label: str) -> str:
    return re.sub(r"^(trend|sector|industry)\s+", "", (label or "").lower()).strip()


def _days_since(dt, *, now: datetime | None = None) -> float | None:
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    if hasattr(dt, "tzinfo") and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() / 86400.0


def directive_stale_reasons(
    *,
    label: str,
    spec: dict,
    status: str,
    ttl_days: int | None,
    created_at,
    updated_at,
    last_serviced_at,
    cold_since,
    hits_30d: int = 0,
    now: datetime | None = None,
) -> list[str]:
    """Pure stale checks for curator-managed watch_directives."""
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    spec = spec or {}
    norm = _norm_theme_label(label)

    if ttl_days and created_at:
        expires = created_at + timedelta(days=int(ttl_days))
        if expires < now:
            reasons.append(f"TTL expired ({ttl_days}d mandate)")

    serviced_ref = last_serviced_at or updated_at
    unserviced_days = _days_since(serviced_ref, now=now)
    if status == "active" and unserviced_days is not None and unserviced_days >= STALE_UNSERVICED_DAYS:
        reasons.append(f"Not serviced in {int(unserviced_days)}d")

    age_days = _days_since(created_at, now=now)
    if status == "active" and hits_30d == 0 and age_days is not None and age_days >= STALE_NO_HITS_DAYS:
        reasons.append(f"No directive hits in 30d (created {int(age_days)}d ago)")

    cold_days = _days_since(cold_since, now=now)
    if status == "paused" and cold_days is not None and cold_days >= STALE_PAUSED_COLD_DAYS:
        reasons.append(f"Paused and cold for {int(cold_days)}d — archive candidate")

    verdict = spec.get("composite_verdict")
    if verdict == "reject":
        reasons.append(f"Composite critique reject ({spec.get('composite_score')})")
    if norm in GENERIC_LABELS and verdict in ("review", "reject"):
        reasons.append(f"Generic pipeline label '{norm}' with {verdict} verdict")

    return reasons


def research_stale_reasons(*, freshness_date, confidence_score, status: str, created_at, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    if freshness_date:
        age = (now.date() - freshness_date).days
        if age > STALE_FRESHNESS_DAYS:
            reasons.append(f"Freshness date {freshness_date} is {age}d old")
    age_days = _days_since(created_at, now=now)
    if status == "staged" and (confidence_score or 0) < LOW_CONFIDENCE and age_days is not None and age_days >= STALE_LOW_CONF_DAYS:
        reasons.append(f"Staged low-confidence row ({confidence_score or 0:.2f}) for {int(age_days)}d")
    return reasons


def staging_stale_reasons(*, proposed_at, directive_status: str | None, source_detail: dict, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    detail = source_detail or {}
    age_days = _days_since(proposed_at, now=now)
    if age_days is not None and age_days >= STALE_STAGING_DAYS:
        reasons.append(f"Undrained staging hit for {int(age_days)}d")
    if directive_status and directive_status not in ("active",):
        reasons.append(f"Parent directive status={directive_status}")
    if detail.get("composite_verdict") == "reject":
        reasons.append(f"Prospect critique reject ({detail.get('composite_score')})")
    return reasons


def extract_critique_fields(spec: dict | None) -> dict:
    """Pull librarian/taxonomy critique fields from a watch_directives.spec blob."""
    spec = spec or {}
    return {k: spec[k] for k in CRITIQUE_SPEC_KEYS if k in spec}


def is_removal_flagged(spec: dict | None) -> bool:
    return bool((spec or {}).get("librarian_stale_flag"))


def load_critique_snapshot() -> dict:
    """Shared read path for Trade AI scripts, API, and coordinator processes."""
    if CRITIQUE_LATEST.exists():
        try:
            return json.loads(CRITIQUE_LATEST.read_text())
        except Exception:
            pass
    return {}


def _build_shared_index(conn) -> dict:
    """Lightweight DB index so processes can skip stale rows without re-parsing all specs."""
    cur = conn.cursor()
    cur.execute(
        """SELECT id, label, status, created_by,
                  spec->>'composite_verdict' AS composite_verdict,
                  spec->>'composite_score' AS composite_score,
                  COALESCE((spec->>'librarian_stale_flag')::boolean, false) AS librarian_stale_flag
           FROM watch_directives
           WHERE status IN ('active', 'paused')
             AND (
               spec ? 'composite_verdict'
               OR COALESCE((spec->>'librarian_stale_flag')::boolean, false)
             )
           ORDER BY updated_at DESC NULLS LAST
           LIMIT 80"""
    )
    directives = [
        {
            "id": r[0],
            "label": (r[1] or "")[:80],
            "status": r[2],
            "created_by": r[3],
            "composite_verdict": r[4],
            "composite_score": float(r[5]) if r[5] is not None else None,
            "librarian_stale_flag": bool(r[6]),
        }
        for r in cur.fetchall()
    ]
    cur.execute(
        """SELECT id, finding_type, severity, affected_table, affected_id,
                  LEFT(description, 200) AS description, recommended_action, created_at
           FROM hermes_validation_findings
           WHERE source='hermes'
             AND hermes_agent_name='research_critique_pipeline'
             AND status='open'
           ORDER BY created_at DESC
           LIMIT 40"""
    )
    findings = [
        {
            "id": r[0],
            "finding_type": r[1],
            "severity": r[2],
            "affected_table": r[3],
            "affected_id": r[4],
            "description": r[5],
            "recommended_action": r[6],
            "created_at": str(r[7]),
        }
        for r in cur.fetchall()
    ]
    stale_ids = [d["id"] for d in directives if d.get("librarian_stale_flag")]
    reject_ids = [d["id"] for d in directives if d.get("composite_verdict") == "reject"]
    return {
        "directives_scored": directives,
        "stale_directive_ids": stale_ids,
        "reject_directive_ids": reject_ids,
        "open_findings": findings,
        "open_findings_count": len(findings),
    }


def publish_critique_snapshot(conn, report: dict, *, apply: bool) -> dict:
    """Write shared runtime JSON consumed by api_v2, watch_directives_service, and discovery."""
    dr = report.get("directives") or {}
    sr = report.get("stale_removal") or {}
    aa = report.get("auto_archive") or {}
    rp = report.get("retention_purge") or {}
    flagged = sr.get("flagged") or {}
    archived = aa.get("archived") or {}
    purged = rp.get("purged") or {}
    critique_body = {k: v for k, v in report.items() if k != "shared_snapshot"}
    snapshot = {
        "updated_at": report.get("updated_at") or datetime.now(timezone.utc).isoformat(),
        "source": "research_critique_pipeline",
        "apply": apply,
        "critique": critique_body,
        "summary": {
            "directives_rated": dr.get("rated", 0),
            "directives_approve": dr.get("approve", 0),
            "directives_review": dr.get("review", 0),
            "directives_reject": dr.get("reject", 0),
            "stale_flagged_total": sr.get("total", 0),
            "stale_directives": flagged.get("directives", 0),
            "stale_research": flagged.get("research", 0),
            "stale_staging": flagged.get("staging", 0),
            "archived_directives": archived.get("directives", 0),
            "archived_research": archived.get("research", 0),
            "staging_drained": archived.get("staging_drained", 0),
            "purged_total": rp.get("total", 0),
            "purged_directives": purged.get("directives", 0),
            "purged_research": purged.get("research", 0),
        },
        "shared_paths": {
            "critique_latest": str(CRITIQUE_LATEST.relative_to(ROOT)),
            "critique_state": str(STATE.relative_to(ROOT)),
            "consciousness": str(CONSCIOUSNESS.relative_to(ROOT)),
        },
    }
    if conn is not None:
        try:
            snapshot["index"] = _build_shared_index(conn)
        except Exception as e:
            snapshot["index_error"] = str(e)[:120]
    if apply:
        CRITIQUE_LATEST.parent.mkdir(parents=True, exist_ok=True)
        CRITIQUE_LATEST.write_text(json.dumps(snapshot, indent=2, default=str))
    return snapshot


def _load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            pass
    return {"directive_offset": 0}


def _save_state(state: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, default=str))


def _resolve_stale_findings(cur, *, affected_table: str, affected_id: int, apply: bool):
    if not apply:
        return
    cur.execute(
        """UPDATE hermes_validation_findings
           SET status='resolved', resolved_at=NOW(), resolved_by=%s, updated_at=NOW()
           WHERE finding_type='stale_data' AND affected_table=%s AND affected_id=%s
             AND status='open'""",
        (ARCHIVE_AGENT, affected_table, affected_id),
    )


def auto_archive_stale(
    conn,
    *,
    apply: bool,
    directive_limit: int = 25,
    research_limit: int = 20,
    staging_limit: int = 20,
) -> dict:
    """Archive curator-owned stale/reject rows flagged by the librarian (no operator step)."""
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    archived = {"directives": 0, "research": 0, "staging_drained": 0}
    detail: list[dict] = []

    cur.execute(
        """SELECT id, label, spec, status, created_by
           FROM watch_directives
           WHERE status IN ('active', 'paused')
             AND created_by = ANY(%s)
             AND (
               COALESCE((spec->>'librarian_stale_flag')::boolean, false)
               OR spec->>'composite_verdict' = 'reject'
             )
           ORDER BY updated_at ASC NULLS FIRST
           LIMIT %s""",
        (list(CURATOR_CREATORS), directive_limit),
    )
    for did, label, spec, status, created_by in cur.fetchall():
        spec = spec if isinstance(spec, dict) else json.loads(spec or "{}")
        if created_by not in CURATOR_CREATORS:
            continue
        merged = dict(spec)
        merged["archived_at"] = now.isoformat()
        merged["archived_by"] = ARCHIVE_AGENT
        merged["archive_reason"] = merged.get("stale_reasons") or [f"composite_{merged.get('composite_verdict', 'reject')}"]
        if apply:
            cur.execute(
                """UPDATE watch_directives
                   SET status='archived', spec=%s::jsonb, updated_at=NOW()
                   WHERE id=%s""",
                (json.dumps(merged), did),
            )
            _resolve_stale_findings(cur, affected_table="watch_directives", affected_id=did, apply=True)
            cur.execute(
                """UPDATE hermes_directive_hits_staging
                   SET drained=true, drained_at=NOW()
                   WHERE directive_id=%s AND drained=false""",
                (did,),
            )
        archived["directives"] += 1
        detail.append({"table": "watch_directives", "id": did, "label": (label or "")[:50]})

    cur.execute(
        """SELECT h.id, h.symbol, h.source_detail
           FROM hermes_directive_hits_staging h
           WHERE h.drained = false
             AND (
               COALESCE((h.source_detail->>'librarian_stale_flag')::boolean, false)
               OR (h.source_detail->>'composite_verdict') = 'reject'
               OR h.proposed_at < NOW() - %s * INTERVAL '1 day'
             )
           ORDER BY h.proposed_at ASC
           LIMIT %s""",
        (STALE_STAGING_DAYS, staging_limit),
    )
    for hid, symbol, source_detail in cur.fetchall():
        if apply:
            cur.execute(
                "UPDATE hermes_directive_hits_staging SET drained=true, drained_at=NOW() WHERE id=%s",
                (hid,),
            )
            _resolve_stale_findings(cur, affected_table="hermes_directive_hits_staging", affected_id=hid, apply=True)
        archived["staging_drained"] += 1
        detail.append({"table": "hermes_directive_hits_staging", "id": hid, "symbol": symbol})

    cur.execute(
        """SELECT id, topic, symbol, status
           FROM hermes_research_intelligence
           WHERE status IN ('staged', 'promoted')
             AND (
               id IN (
                 SELECT affected_id FROM hermes_validation_findings
                 WHERE finding_type='stale_data' AND affected_table='hermes_research_intelligence'
                   AND status='open' AND hermes_agent_name='research_critique_pipeline'
               )
               OR (status='staged' AND COALESCE(confidence_score, 0) < %s
                   AND created_at < NOW() - %s * INTERVAL '1 day')
             )
           ORDER BY created_at ASC
           LIMIT %s""",
        (LOW_CONFIDENCE, STALE_LOW_CONF_DAYS, research_limit),
    )
    for rid, topic, symbol, status in cur.fetchall():
        if apply:
            cur.execute(
                """UPDATE hermes_research_intelligence
                   SET status='archived', updated_at=NOW()
                   WHERE id=%s""",
                (rid,),
            )
            _resolve_stale_findings(cur, affected_table="hermes_research_intelligence", affected_id=rid, apply=True)
        archived["research"] += 1
        detail.append({"table": "hermes_research_intelligence", "id": rid, "topic": (topic or "")[:50], "symbol": symbol})

    if apply and any(archived.values()):
        conn.commit()
    return {
        "archived": archived,
        "total": sum(archived.values()),
        "detail": detail[:12],
        "archived_at": now.isoformat(),
    }


def retention_purge(conn, *, apply: bool) -> dict:
    """Delete archived / drained rows past retention windows (curator-owned only)."""
    cur = conn.cursor()
    purged = {"directives": 0, "research": 0, "staging": 0, "findings": 0}

    cur.execute(
        """DELETE FROM watch_directives
           WHERE status='archived'
             AND created_by = ANY(%s)
             AND COALESCE((spec->>'archived_at')::timestamptz, updated_at)
                 < NOW() - %s * INTERVAL '1 day'""",
        (list(CURATOR_CREATORS), RETENTION_DIRECTIVE_DAYS),
    )
    purged["directives"] = cur.rowcount

    cur.execute(
        """DELETE FROM hermes_research_intelligence
           WHERE status='archived'
             AND updated_at < NOW() - %s * INTERVAL '1 day'""",
        (RETENTION_RESEARCH_DAYS,),
    )
    purged["research"] = cur.rowcount

    cur.execute(
        """DELETE FROM hermes_directive_hits_staging
           WHERE drained = true
             AND drained_at < NOW() - %s * INTERVAL '1 day'""",
        (RETENTION_STAGING_DAYS,),
    )
    purged["staging"] = cur.rowcount

    cur.execute(
        """UPDATE hermes_validation_findings
           SET status='dismissed', resolved_at=NOW(), resolved_by=%s, updated_at=NOW()
           WHERE hermes_agent_name='research_critique_pipeline'
             AND status IN ('resolved', 'open')
             AND finding_type='stale_data'
             AND created_at < NOW() - %s * INTERVAL '1 day'""",
        (ARCHIVE_AGENT, RETENTION_FINDING_DAYS),
    )
    purged["findings"] = cur.rowcount

    if apply and any(purged.values()):
        conn.commit()
    return {"purged": purged, "total": sum(purged.values())}


def _write_finding(
    cur,
    *,
    affected_table: str,
    affected_id: int,
    label: str,
    severity: str,
    ftype: str,
    desc: str,
    evidence: dict,
    apply: bool,
    recommended_action: str,
    symbol: str | None = None,
):
    if not apply:
        return
    cur.execute(
        """SELECT 1 FROM hermes_validation_findings
           WHERE finding_type=%s AND affected_table=%s AND affected_id=%s
             AND status='open' AND created_at > NOW() - INTERVAL '7 days' LIMIT 1""",
        (ftype, affected_table, affected_id),
    )
    if cur.fetchone():
        return
    cur.execute(
        """INSERT INTO hermes_validation_findings
           (source, hermes_agent_name, finding_type, severity, symbol, affected_table, affected_id,
            description, evidence_json, recommended_action, auto_fixable, status, created_at, updated_at)
           VALUES ('hermes', 'research_critique_pipeline', %s, %s, %s, %s, %s,
                   %s, %s::jsonb, %s, false, 'open', NOW(), NOW())""",
        (
            ftype,
            severity,
            symbol,
            affected_table,
            affected_id,
            desc[:500],
            json.dumps(evidence, default=str),
            recommended_action[:240],
        ),
    )


def critique_directives(conn, *, apply: bool, batch_size: int = 15) -> dict:
    """Rate a rotating batch of curator-managed watch_directives."""
    cur = conn.cursor()
    cur.execute(
        """SELECT id, kind, label, spec, rationale, priority, created_by
           FROM watch_directives
           WHERE status='active'
             AND created_by IN ('think_tank', 'sector_universe')
           ORDER BY updated_at DESC NULLS LAST, id DESC"""
    )
    rows = cur.fetchall()
    if not rows:
        return {"rated": 0, "note": "no_curator_directives"}

    state = _load_state()
    offset = int(state.get("directive_offset") or 0) % max(len(rows), 1)
    batch = rows[offset: offset + batch_size]
    if len(batch) < batch_size:
        batch += rows[: batch_size - len(batch)]

    rated = approve = review = reject = 0
    detail = []
    for did, kind, label, spec, rationale, priority, created_by in batch:
        spec = spec if isinstance(spec, dict) else json.loads(spec or "{}")
        lib = librarian_score(kind=kind, label=label or "", spec=spec, rationale=rationale or "")
        tax = taxonomy_score(kind=kind, label=label or "", spec=spec)
        comp = composite_score(lib, tax)

        merged = dict(spec)
        merged.update(lib)
        merged.update(tax)
        merged.update(comp)
        merged["critique_rated_at"] = datetime.now(timezone.utc).isoformat()

        new_priority = priority
        if comp["composite_verdict"] == "reject" and priority != "low":
            new_priority = "low"
        elif comp["composite_verdict"] == "approve" and priority == "low":
            new_priority = "normal"

        if apply:
            cur.execute(
                "UPDATE watch_directives SET spec=%s::jsonb, priority=%s, updated_at=NOW() WHERE id=%s",
                (json.dumps(merged), new_priority, did),
            )
            if comp["composite_verdict"] in ("review", "reject"):
                ftype = "weak_evidence" if comp["composite_verdict"] == "reject" else "unsupported_thesis"
                if tax.get("taxonomy_verdict") == "reject":
                    ftype = "scoring_inconsistency"
                _write_finding(
                    cur,
                    affected_table="watch_directives",
                    affected_id=did,
                    label=label,
                    severity="warning" if comp["composite_verdict"] == "reject" else "info",
                    ftype=ftype,
                    desc=f"{label[:80]} — composite {comp['composite_score']} ({comp['composite_verdict']})",
                    evidence={**lib, **tax, **comp, "created_by": created_by},
                    apply=True,
                    recommended_action="Review directive keywords/seeds or pause if reject",
                )

        rated += 1
        if comp["composite_verdict"] == "approve":
            approve += 1
        elif comp["composite_verdict"] == "review":
            review += 1
        else:
            reject += 1
        detail.append({
            "id": did,
            "label": (label or "")[:60],
            "composite_score": comp["composite_score"],
            "verdict": comp["composite_verdict"],
        })

    if apply:
        conn.commit()
    state["directive_offset"] = (offset + batch_size) % max(len(rows), 1)
    state["last_critique_at"] = datetime.now(timezone.utc).isoformat()
    if apply:
        _save_state(state)

    return {
        "directives_total": len(rows),
        "rated": rated,
        "approve": approve,
        "review": review,
        "reject": reject,
        "detail": detail[:8],
    }


def critique_staged_prospects(conn, *, apply: bool, limit: int = 10) -> dict:
    """Librarian score on unstaged directive hits (narrative strength overlay)."""
    cur = conn.cursor()
    cur.execute(
        """SELECT h.id, h.symbol, h.thesis, h.narrative_strength, h.source_detail, d.label
           FROM hermes_directive_hits_staging h
           JOIN watch_directives d ON d.id = h.directive_id
           WHERE h.drained = false
           ORDER BY h.id DESC LIMIT %s""",
        (limit,),
    )
    rows = cur.fetchall()
    scored = 0
    low_quality = 0
    for hid, sym, thesis, strength, detail, dlabel in rows:
        det = detail if isinstance(detail, dict) else json.loads(detail or "{}")
        spec = {"keywords": [thesis or ""], "think_tank_source": det.get("source", "prospect")}
        lib = librarian_score(kind="trend", label=f"prospect {sym}", spec=spec, rationale=thesis or "")
        tax = taxonomy_score(kind="trend", label=f"{dlabel} {thesis}", spec=spec)
        comp = composite_score(lib, tax)
        if apply:
            merged = dict(det)
            merged.update({**lib, **tax, **comp})
            cur.execute(
                "UPDATE hermes_directive_hits_staging SET source_detail=%s::jsonb WHERE id=%s",
                (json.dumps(merged), hid),
            )
        scored += 1
        if comp["composite_verdict"] == "reject":
            low_quality += 1
    if apply and scored:
        conn.commit()
    return {"prospects_scored": scored, "low_quality": low_quality}


def critique_research_rows(conn, *, apply: bool, limit: int = 8) -> dict:
    """Taxonomy-tag + librarian score recent staged Hermes research."""
    cur = conn.cursor()
    cur.execute(
        """SELECT id, topic, summary, confidence_score, research_type
           FROM hermes_research_intelligence
           WHERE status IN ('staged', 'promoted')
             AND created_at > NOW() - INTERVAL '3 days'
           ORDER BY created_at DESC LIMIT %s""",
        (limit,),
    )
    import taxonomy

    tagged = 0
    for rid, topic, summary, conf, rtype in cur.fetchall():
        text = f"{topic or ''} {summary or ''}"
        tags = taxonomy.classify_fast(text)
        lib = librarian_score(
            kind="trend",
            label=topic or rtype,
            spec={"keywords": [topic or ""]},
            rationale=summary or "",
        )
        q = lib["librarian_score"]
        if (conf or 0) < 0.35:
            q -= 15
        if apply:
            cur.execute(
                """UPDATE hermes_research_intelligence
                   SET category_content=%s, category_sector=%s, category_lifecycle=%s,
                       quality_score=%s
                   WHERE id=%s""",
                (tags.get("content"), tags.get("sector"), tags.get("lifecycle"), q / 100.0, rid),
            )
        tagged += 1
    if apply and tagged:
        conn.commit()
    return {"research_tagged": tagged}


def flag_stale_for_removal(
    conn,
    *,
    apply: bool,
    directive_limit: int = 20,
    research_limit: int = 12,
    staging_limit: int = 15,
) -> dict:
    """Librarian flags stale curator data for operator removal via hermes_validation_findings."""
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    flagged = {"directives": 0, "research": 0, "staging": 0}
    detail: list[dict] = []

    cur.execute(
        """SELECT d.id, d.kind, d.label, d.spec, d.status, d.ttl_days, d.created_at, d.updated_at,
                  d.last_serviced_at, d.cold_since, d.created_by,
                  COALESCE(h.hits_30d, 0) AS hits_30d
           FROM watch_directives d
           LEFT JOIN (
               SELECT directive_id, count(*) AS hits_30d
               FROM watch_directive_hits
               WHERE surfaced_at > NOW() - INTERVAL '30 days'
               GROUP BY directive_id
           ) h ON h.directive_id = d.id
           WHERE d.status IN ('active', 'paused')
             AND d.created_by IN ('think_tank', 'sector_universe')
           ORDER BY d.updated_at ASC NULLS FIRST, d.id ASC
           LIMIT %s""",
        (directive_limit,),
    )
    for row in cur.fetchall():
        did, kind, label, spec, status, ttl_days, created_at, updated_at, last_serviced_at, cold_since, created_by, hits_30d = row
        spec = spec if isinstance(spec, dict) else json.loads(spec or "{}")
        reasons = directive_stale_reasons(
            label=label or "",
            spec=spec,
            status=status,
            ttl_days=ttl_days,
            created_at=created_at,
            updated_at=updated_at,
            last_serviced_at=last_serviced_at,
            cold_since=cold_since,
            hits_30d=int(hits_30d or 0),
            now=now,
        )
        if not reasons:
            continue
        severity = "warning" if any("TTL" in r or "reject" in r or "cold" in r for r in reasons) else "info"
        if apply:
            merged = dict(spec)
            merged["librarian_stale_flag"] = True
            merged["stale_reasons"] = reasons
            merged["removal_recommended_at"] = now.isoformat()
            cur.execute(
                "UPDATE watch_directives SET spec=%s::jsonb, updated_at=NOW() WHERE id=%s",
                (json.dumps(merged), did),
            )
            _write_finding(
                cur,
                affected_table="watch_directives",
                affected_id=did,
                label=label or "",
                severity=severity,
                ftype="stale_data",
                desc=f"{(label or '')[:80]} — stale for removal: {'; '.join(reasons)}",
                evidence={"reasons": reasons, "status": status, "created_by": created_by, "hits_30d": hits_30d},
                apply=True,
                recommended_action="Auto-archived by librarian on next critique tick",
            )
        flagged["directives"] += 1
        detail.append({"table": "watch_directives", "id": did, "label": (label or "")[:50], "reasons": reasons[:2]})

    cur.execute(
        """SELECT id, topic, symbol, freshness_date, confidence_score, status, created_at
           FROM hermes_research_intelligence
           WHERE status IN ('staged', 'promoted')
             AND (
               (freshness_date IS NOT NULL AND freshness_date < CURRENT_DATE - %s * INTERVAL '1 day')
               OR (status='staged' AND COALESCE(confidence_score, 0) < %s
                   AND created_at < NOW() - %s * INTERVAL '1 day')
             )
           ORDER BY created_at ASC
           LIMIT %s""",
        (STALE_FRESHNESS_DAYS, LOW_CONFIDENCE, STALE_LOW_CONF_DAYS, research_limit),
    )
    for rid, topic, symbol, freshness_date, confidence_score, status, created_at in cur.fetchall():
        reasons = research_stale_reasons(
            freshness_date=freshness_date,
            confidence_score=confidence_score,
            status=status,
            created_at=created_at,
            now=now,
        )
        if not reasons:
            continue
        if apply:
            _write_finding(
                cur,
                affected_table="hermes_research_intelligence",
                affected_id=rid,
                label=topic or "research",
                severity="warning" if any("Freshness" in r for r in reasons) else "info",
                ftype="stale_data",
                desc=f"{(topic or '')[:80]} — stale research for removal: {'; '.join(reasons)}",
                evidence={"reasons": reasons, "status": status, "confidence_score": confidence_score},
                apply=True,
                recommended_action="Auto-archived by librarian on next critique tick",
                symbol=symbol,
            )
        flagged["research"] += 1
        detail.append({"table": "hermes_research_intelligence", "id": rid, "topic": (topic or "")[:50], "reasons": reasons[:2]})

    cur.execute(
        """SELECT h.id, h.symbol, h.proposed_at, h.source_detail, d.status, d.label
           FROM hermes_directive_hits_staging h
           LEFT JOIN watch_directives d ON d.id = h.directive_id
           WHERE h.drained = false
             AND (
               h.proposed_at < NOW() - %s * INTERVAL '1 day'
               OR d.status IN ('paused', 'archived')
               OR (h.source_detail->>'composite_verdict') = 'reject'
             )
           ORDER BY h.proposed_at ASC
           LIMIT %s""",
        (STALE_STAGING_DAYS, staging_limit),
    )
    for hid, symbol, proposed_at, source_detail, directive_status, dlabel in cur.fetchall():
        detail_json = source_detail if isinstance(source_detail, dict) else json.loads(source_detail or "{}")
        reasons = staging_stale_reasons(
            proposed_at=proposed_at,
            directive_status=directive_status,
            source_detail=detail_json,
            now=now,
        )
        if not reasons:
            continue
        if apply:
            merged = dict(detail_json)
            merged["librarian_stale_flag"] = True
            merged["stale_reasons"] = reasons
            merged["removal_recommended_at"] = now.isoformat()
            cur.execute(
                "UPDATE hermes_directive_hits_staging SET source_detail=%s::jsonb WHERE id=%s",
                (json.dumps(merged), hid),
            )
            _write_finding(
                cur,
                affected_table="hermes_directive_hits_staging",
                affected_id=hid,
                label=f"{symbol} @ {dlabel or 'directive'}",
                severity="warning" if directive_status in ("paused", "archived") else "info",
                ftype="stale_data",
                desc=f"{symbol} staging hit — remove: {'; '.join(reasons)}",
                evidence={"reasons": reasons, "directive_status": directive_status, "directive_label": dlabel},
                apply=True,
                recommended_action="Auto-drained by librarian on next critique tick",
                symbol=symbol,
            )
        flagged["staging"] += 1
        detail.append({"table": "hermes_directive_hits_staging", "id": hid, "symbol": symbol, "reasons": reasons[:2]})

    if apply and any(flagged.values()):
        conn.commit()
    state = _load_state()
    state["last_stale_scan_at"] = now.isoformat()
    state["last_stale_flagged"] = flagged
    if apply:
        _save_state(state)

    return {
        "flagged": flagged,
        "total": sum(flagged.values()),
        "detail": detail[:10],
        "scanned_at": now.isoformat(),
    }


def run_taxonomy_tagger(*, apply: bool, limit: int = 15) -> dict:
    if not apply:
        return {"ran": False, "dry_run": True}
    try:
        r = subprocess.run(
            [PY, str(ROOT / "scripts" / "taxonomy_tagger.py"), "--table", "hermes", "--limit", str(limit)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120,
        )
        return {"ran": True, "ok": r.returncode == 0, "tail": (r.stdout or r.stderr or "")[-200:]}
    except Exception as e:
        return {"ran": True, "ok": False, "error": str(e)[:80]}


def run_critique_pipeline(
    conn,
    *,
    apply: bool,
    directive_batch: int = 15,
    prospect_limit: int = 10,
    research_limit: int = 8,
    run_tagger: bool = False,
    tagger_limit: int = 15,
    stale_scan: bool = True,
    auto_archive: bool = True,
    retention_purge_enabled: bool = True,
) -> dict:
    """Full librarian + taxonomy critique pass for one curator tick."""
    out = {
        "directives": critique_directives(conn, apply=apply, batch_size=directive_batch),
        "prospects": critique_staged_prospects(conn, apply=apply, limit=prospect_limit),
        "research": critique_research_rows(conn, apply=apply, limit=research_limit),
        "taxonomy_tagger": run_taxonomy_tagger(apply=apply, limit=tagger_limit) if run_tagger else {"ran": False},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if stale_scan:
        out["stale_removal"] = flag_stale_for_removal(conn, apply=apply)
    if auto_archive:
        out["auto_archive"] = auto_archive_stale(conn, apply=apply)
    if retention_purge_enabled:
        out["retention_purge"] = retention_purge(conn, apply=apply)
    out["shared_snapshot"] = publish_critique_snapshot(conn, out, apply=apply)
    return out


def _env():
    for ln in (ROOT / ".env").read_text().splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, _, v = ln.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def main():
    parser = argparse.ArgumentParser(description="Librarian + taxonomy critique and stale-data flags")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--stale-only", action="store_true", help="Stale scan + auto-archive + retention purge")
    parser.add_argument("--no-archive", action="store_true", help="Skip auto-archive and retention purge")
    parser.add_argument("--directive-batch", type=int, default=15)
    args = parser.parse_args()
    _env()
    sys.path.insert(0, str(ROOT / "scripts"))
    import psycopg2

    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )
    if args.stale_only:
        sr = flag_stale_for_removal(conn, apply=args.apply)
        report = {
            "stale_removal": sr,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if not args.no_archive:
            report["auto_archive"] = auto_archive_stale(conn, apply=args.apply)
            report["retention_purge"] = retention_purge(conn, apply=args.apply)
        report["shared_snapshot"] = publish_critique_snapshot(conn, report, apply=args.apply)
    else:
        report = run_critique_pipeline(
            conn,
            apply=args.apply,
            directive_batch=args.directive_batch,
            auto_archive=not args.no_archive,
            retention_purge_enabled=not args.no_archive,
        )
    conn.close()
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())