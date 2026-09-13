"""Translate the health agent's output into the CIO boundary's HealthSnapshot.

CL-63. `CIOHealthBoundary` was constructed with no snapshot and nothing ever
called `load_snapshot()`, so it evaluated with no evidence on every production
run. This is the feed.

It is an ADAPTER, not a pass-through, because the two sides do not share a
vocabulary. Measured 2026-09-12 against the live artifact:

    health agent emits  data_quality, execution_health, infra,
                        intelligence_quality, pipeline_freshness,
                        retirement_planning, risk_protection
    boundary maps       market_data, broker, database, backup, agent_jobs,
                        indicators, shadow_batch, llm, api, file_integrity,
                        watchlist

No overlap at all, and the health agent's severities are strings where the
boundary compares integers -- passing a finding through raw raises TypeError
inside evaluate(). So the translation is mandatory, and because it decides what
can block CIO advisory output it lives in config/cio_health_snapshot_feed.json
rather than here.

This module never fabricates coverage. A health category mapped to nothing, or a
boundary category no health category maps to, simply carries no evidence, and
cio_health_boundary.evaluate() reports UNKNOWN for the domains it governs rather
than READY.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_health_boundary import HealthSnapshot

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "cio_health_snapshot_feed.json"


def load_feed_config(path: Optional[Path] = None) -> dict[str, Any]:
    """Read the translation policy. Missing or unreadable config disables the
    feed rather than guessing a mapping."""
    p = path or CONFIG_PATH
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("health snapshot feed config unavailable (%s): %s", p, exc)
        return {}


def enforcement_enabled(cfg: Optional[dict[str, Any]] = None) -> bool:
    """Whether the boundary's decision may BLOCK a run.

    Defaults to False on any doubt: absent config, absent key, non-bool value.
    Being fed is not the same as being allowed to gate, and the second is an
    operator decision.
    """
    cfg = load_feed_config() if cfg is None else cfg
    return cfg.get("enforce") is True


def _parse_ts(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_health_snapshot(
    cfg: Optional[dict[str, Any]] = None,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Optional[HealthSnapshot]:
    """Build a HealthSnapshot from the health agent artifact.

    Returns None -- meaning the boundary stays evidence-free and answers
    UNKNOWN -- when the config is missing, the artifact is absent or malformed,
    or the artifact is older than max_age_minutes. None is the honest outcome in
    every one of those cases; a stale or unreadable file is not evidence about
    now.
    """
    cfg = load_feed_config() if cfg is None else cfg
    if not cfg:
        return None

    root = root or PROJECT_ROOT
    src = root / cfg.get("source_path", "")
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("health snapshot unreadable (%s): %s", src, exc)
        return None

    captured_at = raw.get("captured_at") or raw.get("observed_at")
    ts = _parse_ts(captured_at)
    if ts is None:
        log.warning("health snapshot has no usable timestamp; refusing to use it")
        return None

    max_age = cfg.get("max_age_minutes")
    if isinstance(max_age, (int, float)) and max_age > 0:
        age = (now or datetime.now(timezone.utc)) - ts
        if age > timedelta(minutes=max_age):
            log.warning(
                "health snapshot is %.1f min old (max %s); treating as no evidence",
                age.total_seconds() / 60.0,
                max_age,
            )
            return None

    category_map: dict[str, list[str]] = cfg.get("category_map") or {}
    severity_map: dict[str, int] = cfg.get("severity_map") or {}

    # Scores: a boundary category inherits the WORST score among the health
    # categories mapped onto it. Worst, not mean: averaging a failing category
    # against a healthy one manufactures a passing grade neither one earned.
    category_scores: dict[str, float] = {}
    for health_cat, score in (raw.get("category_scores") or {}).items():
        if not isinstance(score, (int, float)):
            continue
        for bcat in category_map.get(health_cat, []):
            prev = category_scores.get(bcat)
            category_scores[bcat] = score if prev is None else min(prev, score)

    findings: list[dict[str, Any]] = []
    for f in raw.get("findings") or []:
        targets = category_map.get(f.get("category"), [])
        if not targets:
            continue
        sev = f.get("severity")
        if isinstance(sev, str):
            sev = severity_map.get(sev.lower())
        if not isinstance(sev, int):
            # An unrecognised severity is dropped rather than guessed. Guessing
            # low hides a real problem; guessing high blocks on a typo.
            log.debug("dropping finding with unmappable severity: %r", f.get("severity"))
            continue
        for bcat in targets:
            findings.append(
                {
                    "category": bcat,
                    "severity": sev,
                    "finding_id": f.get("finding_id") or f.get("type"),
                    "message": f.get("message", ""),
                }
            )

    return HealthSnapshot(
        health_snapshot_id=f"health-agent-{ts.strftime('%Y%m%dT%H%M%SZ')}",
        observed_at=ts.isoformat(),
        overall_score=raw.get("overall_score", 0),
        overall_status=str(raw.get("status") or raw.get("overall_status") or "UNKNOWN"),
        category_scores=category_scores,
        findings=findings,
    )
