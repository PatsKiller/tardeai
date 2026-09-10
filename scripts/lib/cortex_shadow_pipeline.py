#!/usr/bin/env python3
"""cortex_shadow_pipeline.py — Phase 8 AgentView + scoring shadow (default OFF).

Flag gate (either enables the pipeline; both default OFF):
  AGENT_VIEW_V1_ENABLED
  CORTEX_SHADOW_ENABLED

Pipeline (shadow only, MBI_BEHAVIOR=0):
  produce_agent_view_v1 → critic_pass → append agent_views.jsonl under state_root
  if critic_pass and GOVERNED_COMMITMENT_ENABLED:
      build_governed_commitment → append commitments.jsonl
  if an evaluated (settled) commitment is present:
      write calibration_shadow.json via prior_calibration_v1

Refuses trade verbs via the existing AgentView critic. Never sizes, orders,
stops, or writes broker state.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from scripts.lib.agent_view_v1 import critic_pass, persist_allowed, produce_agent_view_v1
from scripts.lib.governed_commitment import (
    FEATURE_FLAG as COMMITMENT_FLAG,
    build_governed_commitment,
    evaluate_outcome,
    feature_enabled as commitment_enabled,
)
from scripts.lib.prior_calibration_v1 import CalibrationStore, gate_scoring_allowed

SCHEMA = "CortexShadowPipeline@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0
AGENT_VIEW_FLAG = "AGENT_VIEW_V1_ENABLED"
CORTEX_SHADOW_FLAG = "CORTEX_SHADOW_ENABLED"
SETTLED = frozenset({"CONFIRMED", "REFUTED", "EXPIRED"})


def _truthy(val: Any) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def enabled(env: Mapping[str, str] | None = None) -> bool:
    src = env if env is not None else os.environ
    return _truthy(src.get(AGENT_VIEW_FLAG)) or _truthy(src.get(CORTEX_SHADOW_FLAG))


def source_sha(env: Mapping[str, str] | None = None) -> str:
    src = env if env is not None else os.environ
    return (
        src.get("TRADEAI_SOURCE_SHA")
        or src.get("BUILD_SHA")
        or src.get("SOURCE_COMMIT")
        or "unknown"
    )


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _write_json(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(row, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


@dataclass
class CortexShadowResult:
    ok: bool
    outcome: str
    disabled: bool = False
    view: dict[str, Any] | None = None
    commitment: dict[str, Any] | None = None
    evaluation: dict[str, Any] | None = None
    calibration: dict[str, Any] | None = None
    paths: dict[str, str] = field(default_factory=dict)
    reason: str | None = None
    mbi_behavior: int = MBI_BEHAVIOR
    schema: str = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ok": self.ok,
            "outcome": self.outcome,
            "disabled": self.disabled,
            "view": self.view,
            "commitment": self.commitment,
            "evaluation": self.evaluation,
            "calibration": self.calibration,
            "paths": dict(self.paths),
            "reason": self.reason,
            "mbi_behavior": self.mbi_behavior,
            "authority": AUTHORITY,
        }


def run_cortex_shadow(
    *,
    subject: str,
    summary: str,
    citations: list[str],
    confidence: float,
    state_root: Path | str,
    source_sha_value: str | None = None,
    stance: str | None = None,
    uncertainty: str = "",
    falsifier: str = "observation contradicts claim within horizon",
    horizon: str = "7d",
    due_at: datetime | str | None = None,
    observation: dict[str, Any] | None = None,
    evaluated_commitment: dict[str, Any] | None = None,
    dry_run: bool = True,
    env: Mapping[str, str] | None = None,
) -> CortexShadowResult:
    """Run one shadow pass. Flag OFF ⇒ no-op. dry_run ⇒ no durable writes."""
    env_map = dict(env if env is not None else os.environ)
    root = Path(state_root)

    if not enabled(env_map):
        return CortexShadowResult(
            ok=True,
            outcome="disabled",
            disabled=True,
            reason="feature_flag_off",
        )

    sha = source_sha_value or source_sha(env_map)
    view = produce_agent_view_v1(
        subject=subject,
        summary=summary,
        citations=list(citations),
        confidence=float(confidence),
        source_sha=sha,
        stance=stance,
        uncertainty=uncertainty,
    )
    # Explicit second critic gate (produce already runs critic_pass).
    view = critic_pass(view)

    if int(view.mbi_behavior) != 0:
        return CortexShadowResult(
            ok=False,
            outcome="refused",
            view=view.to_dict(),
            reason="mbi_behavior_nonzero",
        )

    if not persist_allowed(view):
        return CortexShadowResult(
            ok=False,
            outcome="critic_refused",
            view=view.to_dict(),
            reason=";".join(view.critic_notes) or "critic_failed",
        )

    paths: dict[str, str] = {}
    view_row = view.to_dict()
    views_path = root / "agent_views.jsonl"
    paths["agent_views"] = str(views_path)
    if not dry_run:
        _append_jsonl(views_path, view_row)

    commitment_row: dict[str, Any] | None = None
    evaluation: dict[str, Any] | None = None
    calibration: dict[str, Any] | None = None

    if commitment_enabled(env_map) and view.critic_pass:
        now = datetime.now(timezone.utc)
        due = due_at or (now + timedelta(days=7))
        commitment_row = build_governed_commitment(
            claim=view.summary,
            confidence=view.confidence,
            horizon=horizon,
            due_at=due,
            falsifier=falsifier,
            evidence_refs=list(view.citations) or [f"view:{view.view_id}"],
            source_identity="cortex_shadow_pipeline",
            source_sha=sha,
            served_sha=sha,
            subject_guid=subject,
            trigger_provenance={
                "producer": "cortex_shadow_pipeline",
                "trigger": "agent_view_v1",
                "view_id": view.view_id,
            },
            created_at=now,
            frozen_at=now,
        )
        cpath = root / "commitments.jsonl"
        paths["commitments"] = str(cpath)
        if not dry_run:
            _append_jsonl(cpath, commitment_row)
        evaluation = evaluate_outcome(commitment_row, observation=observation)

    # Prefer an explicitly supplied evaluated commitment (settled outcome).
    settled_row = evaluated_commitment
    if settled_row is None and evaluation and evaluation.get("outcome") in SETTLED:
        settled_row = {**(commitment_row or {}), **evaluation}

    if settled_row and settled_row.get("outcome") in SETTLED:
        if gate_scoring_allowed(valid_evaluated_commitments=1):
            store = CalibrationStore(cohort="cortex_shadow", source_sha=sha)
            store.add_outcome(
                commitment_id=str(settled_row.get("commitment_id") or ""),
                confidence=float(settled_row.get("confidence") or view.confidence),
                outcome=str(settled_row["outcome"]),
                lesson_provenance="OUTCOME_DERIVED",
            )
            calibration = store.summary()
            cal_path = root / "calibration_shadow.json"
            paths["calibration_shadow"] = str(cal_path)
            if not dry_run:
                _write_json(cal_path, calibration)

    return CortexShadowResult(
        ok=True,
        outcome="dry_run" if dry_run else "shadow_written",
        view=view_row,
        commitment=commitment_row,
        evaluation=evaluation,
        calibration=calibration,
        paths=paths,
    )


__all__ = [
    "SCHEMA",
    "AGENT_VIEW_FLAG",
    "CORTEX_SHADOW_FLAG",
    "COMMITMENT_FLAG",
    "CortexShadowResult",
    "enabled",
    "run_cortex_shadow",
]
