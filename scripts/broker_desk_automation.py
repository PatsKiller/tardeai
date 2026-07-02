#!/usr/bin/env python3
"""broker_desk_automation.py — last-run + schedule metadata for the Proposals desk UI."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _iso_from_ts(ts: float | int | None) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()[:19]
    except Exception:
        return None


def _file_mtime_iso(path: Path) -> str | None:
    try:
        if path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()[:19]
    except Exception:
        pass
    return None


def get_desk_automation_state() -> dict:
    runtime = PROJECT_ROOT / "data" / "runtime"
    logs = PROJECT_ROOT / "logs"

    autocal_last: str | None = None
    autocal_updated = 0
    try:
        p = runtime / "broker_autocal_last.json"
        if p.exists():
            blob = json.loads(p.read_text(encoding="utf-8"))
            autocal_last = _iso_from_ts(blob.get("ts"))
            autocal_updated = int((blob.get("result") or {}).get("updated") or 0)
    except Exception:
        pass

    curator_last: str | None = None
    curator_curated = 0
    try:
        p = runtime / "broker_curator_last.json"
        if p.exists():
            blob = json.loads(p.read_text(encoding="utf-8"))
            curator_last = _iso_from_ts(blob.get("ts"))
            curator_curated = int(blob.get("curated") or 0)
    except Exception:
        pass

    enrich_last = _file_mtime_iso(logs / "enrich_proposal_technicals.log")

    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat()[:19],
        "jobs": [
            {
                "id": "prices_autocal",
                "label": "Prices + live R:R",
                "schedule": "Auto every 5m (9–16 ET weekdays) + on list poll",
                "manual": "↻ Refresh all + recalibrate",
                "last_at": autocal_last,
                "last_detail": f"{autocal_updated} row(s)" if autocal_updated else None,
                "automated": True,
            },
            {
                "id": "technicals_grade",
                "label": "Technical grade",
                "schedule": "Auto every 2h at :15 + health_agent remediation",
                "manual": "↻ Refresh prices + recalibrate (per card)",
                "last_at": enrich_last,
                "last_detail": "Finviz RSI/MA/ATR/RVOL/ADX → score 0–100",
                "automated": True,
            },
            {
                "id": "curator",
                "label": "Queue curator",
                "schedule": "Auto every 30m (9–16 ET weekdays)",
                "manual": None,
                "last_at": curator_last,
                "last_detail": f"{curator_curated} curated" if curator_curated else None,
                "automated": True,
            },
            {
                "id": "agent_reviews",
                "label": "Local agent reviews",
                "schedule": "Health agent every 30m (remediation) · no fixed queue cron",
                "manual": "☁ Run cloud · Queue steph",
                "last_at": None,
                "last_detail": "Maria · Risk · Steph on demand",
                "automated": False,
            },
            {
                "id": "reconcile_sleeves",
                "label": "Reconcile sleeves",
                "schedule": "Manual only",
                "manual": "Reconcile sleeves button",
                "last_at": None,
                "automated": False,
            },
            {
                "id": "llm_stage_2b",
                "label": "LLM stage 2b",
                "schedule": "Manual only",
                "manual": "LLM stage 2b button",
                "last_at": None,
                "automated": False,
            },
        ],
        "grade_methodology": (
            "Score 0–100: RSI posture (20) · MA trend stack (15) · ATR% band (15) · RVOL (10) · ADX trending (10). "
            "≥80 STRONG · ≥60 OK · ≥40 MIXED · ≥20 WEAK · else INCOMPLETE. Same Finviz feed as Entry helper."
        ),
    }