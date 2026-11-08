"""The record: ``MarketOutlookRecord@v1`` (§4.6), field for field.

The schema is a contract with the brief builder that cc-deepseek-9 is writing in parallel: field names here are the
contract, so nothing is renamed and nothing is dropped. A correction is a NEW record whose ``supersedes`` names the
one it replaces — records are immutable.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from . import SCHEMA_RECORD
from . import sessions_shim

ET = ZoneInfo("America/New_York")
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def engine_commit() -> str:
    """The commit the engine ran from, or ``""`` when git cannot answer — never a guessed sha."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10, check=False
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def record_id(now: datetime, mode: str, seq: int) -> str:
    day = now.astimezone(ET).date().isoformat()
    return f"outlook:{day}:{mode}:{int(seq)}"


def snapshot_hash(categories: Sequence[Any]) -> str:
    rows: list[dict[str, Any]] = []
    for cat in categories:
        d = cat.to_dict() if hasattr(cat, "to_dict") else cat
        for ind in d.get("indicators") or []:
            rows.append(
                {
                    "category": d.get("key"),
                    "key": ind.get("key"),
                    "raw": ind.get("raw"),
                    "normalized": ind.get("normalized"),
                    "as_of": ind.get("as_of"),
                    "source": ind.get("source"),
                    "table": ind.get("table"),
                    "stale": ind.get("stale"),
                    "refused_reason": ind.get("refused_reason"),
                }
            )
    rows.sort(key=lambda r: f"{r['category']}/{r['key']}")
    blob = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _indicator_dict(ind: Any) -> dict[str, Any]:
    d = ind.to_dict() if hasattr(ind, "to_dict") else dict(ind)
    return {
        "key": d.get("key"),
        "raw": d.get("raw"),
        "normalized": d.get("normalized"),
        "as_of": d.get("as_of"),
        "source": d.get("source"),
        "table": d.get("table"),
        "stale": bool(d.get("stale")),
        "refused_reason": d.get("refused_reason"),
    }


def _category_dict(cat: Any) -> dict[str, Any]:
    d = cat.to_dict() if hasattr(cat, "to_dict") else dict(cat)
    return {
        "key": d.get("key"),
        "weight_prior": d.get("weight_prior"),
        "weight_effective": d.get("weight_effective"),
        "subscore": None if d.get("subscore") is None else round(float(d["subscore"]), 4),
        "coverage": round(float(d.get("coverage") or 0.0), 4),
        "state": d.get("state"),
        "indicators": [_indicator_dict(i) for i in d.get("indicators") or []],
    }


def build(
    *,
    now: datetime,
    mode: str,
    seq: int,
    policy_version: str,
    score: Any,
    confidence: Any,
    regime: Any,
    categories: Sequence[Any],
    scenarios: dict[str, Any],
    levels: dict[str, Any],
    catalysts: Sequence[dict[str, Any]],
    what_would_change_view: Sequence[dict[str, Any]],
    actions_template: dict[str, Any],
    prior_record_id: str | None,
    supersedes: str | None = None,
    grading: dict[str, Any] | None = None,
    delivery: dict[str, Any] | None = None,
    commit: str | None = None,
) -> dict[str, Any]:
    """Build the record dict. Every top-level key of the schema is present even when its value is null."""
    sc = score.to_dict() if hasattr(score, "to_dict") else dict(score)
    conf = confidence.to_dict() if hasattr(confidence, "to_dict") else dict(confidence)
    reg = regime.to_dict() if hasattr(regime, "to_dict") else dict(regime)
    rid = record_id(now, mode, seq)
    et_now = now.astimezone(ET)
    return {
        "schema": SCHEMA_RECORD,
        "record_id": rid,
        "as_of": now.isoformat(),
        "mode": mode,
        "session_clock": f"{sessions_shim.session_label_et(now)} @ {et_now.isoformat()}",
        "engine_commit": commit if commit is not None else engine_commit(),
        "policy_version": policy_version,
        "score": None if sc.get("score") is None else round(float(sc["score"]), 2),
        "band": sc.get("band"),
        "confidence": {
            "value": conf.get("value"),
            "band": conf.get("band"),
            "coverage": conf.get("coverage"),
            "freshness": conf.get("freshness"),
            "agreement": conf.get("agreement"),
            "u_event": conf.get("u_event"),
            "hitrate": conf.get("hitrate"),
        },
        "regime": {
            "vix_band": reg.get("vix_band"),
            "vix_value": reg.get("vix_value"),
            "vix_source": reg.get("vix_source"),
            "mre_tier": reg.get("mre_tier"),
            "mre_score": reg.get("mre_score"),
            "mre_as_of": reg.get("mre_as_of"),
            "episode_id": reg.get("episode_id"),
        },
        "categories": [_category_dict(c) for c in categories],
        "scenarios": scenarios,
        "key_levels": {
            k: {
                "support": v.get("support") or [],
                "resistance": v.get("resistance") or [],
                "basis": v.get("basis"),
            }
            for k, v in (levels or {}).items()
        },
        "catalysts": [
            {
                "date_et": c.get("date_et"),
                "time_et": c.get("time_et"),
                "event": c.get("event"),
                "impact": c.get("impact"),
                "consensus": c.get("consensus"),
                "prior": c.get("prior"),
                "held_flag_per_account_id": list(c.get("held_flag_per_account_id") or []),
            }
            for c in catalysts
        ],
        "what_would_change_view": list(what_would_change_view),
        "actions_template": actions_template,
        "prior_record_id": prior_record_id,
        "supersedes": supersedes,
        "grading": grading,
        "inputs_snapshot_hash": snapshot_hash(categories),
        "delivery": {"email": None, "text": None, "telegram": None, **(delivery or {})},
    }


def validate(record: dict[str, Any]) -> list[str]:
    """Structural checks before a write. Returns the problems; an empty list means the row may be written."""
    problems: list[str] = []
    required = (
        "record_id", "as_of", "mode", "session_clock", "engine_commit", "policy_version", "score", "band",
        "confidence", "regime", "categories", "scenarios", "key_levels", "catalysts", "what_would_change_view",
        "actions_template", "prior_record_id", "supersedes", "grading", "inputs_snapshot_hash", "delivery",
    )
    for key in required:
        if key not in record:
            problems.append(f"missing {key}")
    if record.get("schema") != SCHEMA_RECORD:
        problems.append(f"schema is {record.get('schema')!r}, expected {SCHEMA_RECORD}")
    cats = record.get("categories") or []
    if len(cats) != 11:
        problems.append(f"{len(cats)} categories, expected 11")
    for c in cats:
        if set(c) != {"key", "weight_prior", "weight_effective", "subscore", "coverage", "state", "indicators"}:
            problems.append(f"category {c.get('key')!r} has keys {sorted(c)}")
        for i in c.get("indicators") or []:
            if set(i) != {"key", "raw", "normalized", "as_of", "source", "table", "stale", "refused_reason"}:
                problems.append(f"indicator {i.get('key')!r} has keys {sorted(i)}")
    conf = record.get("confidence") or {}
    if set(conf) != {"value", "band", "coverage", "freshness", "agreement", "u_event", "hitrate"}:
        problems.append(f"confidence keys {sorted(conf)}")
    reg = record.get("regime") or {}
    if set(reg) != {"vix_band", "vix_value", "vix_source", "mre_tier", "mre_score", "mre_as_of", "episode_id"}:
        problems.append(f"regime keys {sorted(reg)}")
    score, band = record.get("score"), record.get("band")
    if score is not None and band not in ("RISK_OFF", "DEFENSIVE", "NEUTRAL", "RISK_ON"):
        problems.append(f"band {band!r} is not a member of the band vocabulary")
    if record.get("band") is None and score is not None:
        problems.append("a score without a band")
    return problems


__all__ = ["build", "validate", "record_id", "snapshot_hash", "engine_commit"]
