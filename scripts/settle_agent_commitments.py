"""Deterministic, shadow-only post-decision loop.

This module deliberately has no database, network, broker, scheduler, or model
dependency.  The integration owner can replace the vendored identifiers with
``scripts.lib.campaign_interfaces`` without changing the state machine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import uuid
from typing import Any, Iterable

SCHEMA = "OutcomeSettlement@v1"
COMMITMENT_SCHEMA = "Commitment@v1"
OUTCOME_SCHEMA = "Outcome@v1"
PROPOSAL_SCHEMA = "BeliefProposal@v1"
CALIBRATION_SCHEMA = "Calibration@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MIN_SAMPLES = 5

# VENDORED: replaced by campaign_interfaces at integration.
_NS = uuid.UUID("4a6f7461-9d23-5f0e-8a3d-2d3ef4a7b6c1")
NS_OUTCOME = uuid.uuid5(_NS, "outcome")
NS_BELIEF = uuid.uuid5(_NS, "belief")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def _envelope(obj: dict[str, Any], *, parent_kind: str | None = None) -> dict[str, Any]:
    required = ("schema_version", "source_sha", "produced_at", "correlation_id",
                "idempotency_key", "retention_class", "lifecycle_state", "provenance")
    missing = [key for key in required if key not in obj]
    if missing:
        raise ValueError("missing_envelope:" + ",".join(missing))
    if parent_kind and obj.get("parent_kind") not in (None, parent_kind):
        raise ValueError("invalid_parent_kind")
    if not isinstance(obj["provenance"], dict) or not obj["provenance"].get("producer"):
        raise ValueError("missing_provenance")
    return obj


def validate_commitment(commitment: dict[str, Any]) -> dict[str, Any]:
    """Validate Lane A's frozen commitment; D never mints or repairs one."""
    _envelope(commitment, parent_kind="wake")
    for key in ("commitment_id", "wake_id", "subject_guid", "commitment_kind",
                "normalized_claim", "observation_window_start", "observation_window_end",
                "population", "horizon"):
        if not commitment.get(key):
            raise ValueError("missing_commitment_field:" + key)
    if not commitment["wake_id"]:
        raise ValueError("commitment_without_wake")
    if commitment.get("lifecycle_state", "OPEN") != "OPEN":
        raise ValueError("commitment_not_open")
    if _dt(commitment["observation_window_end"]) < _dt(commitment["observation_window_start"]):
        raise ValueError("invalid_observation_window")
    return commitment


def link_observation(commitment: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic link; early observations remain pending."""
    validate_commitment(commitment)
    if observation.get("commitment_id") != commitment["commitment_id"]:
        raise ValueError("observation_commitment_mismatch")
    for key in ("observation_id", "observed_at", "value", "evidence"):
        if key not in observation:
            raise ValueError("missing_observation_field:" + key)
    observed_at = _dt(observation["observed_at"])
    start, end = _dt(commitment["observation_window_start"]), _dt(commitment["observation_window_end"])
    state = "PENDING" if observed_at < start else ("MEASURED" if observed_at <= end else "LATE")
    return {"commitment_id": commitment["commitment_id"], "wake_id": commitment["wake_id"],
            "subject_guid": commitment["subject_guid"], "observation": observation,
            "observation_key": _digest({"commitment_id": commitment["commitment_id"],
                                         "observed_at": _iso(observed_at), "value": observation["value"]}),
            "window_state": state}


def outcome_id(commitment_id: str, observation_window_end: Any) -> str:
    return str(uuid.uuid5(NS_OUTCOME, f"{commitment_id}{_iso(observation_window_end)}"))


def _result(observations: list[dict[str, Any]]) -> str:
    values = {str(x["observation"]["value"]).upper() for x in observations}
    if len(values) > 1:
        return "AMBIGUOUS"
    return next(iter(values), "UNOBSERVABLE")


@dataclass
class SettlementLedger:
    commitments: dict[str, dict[str, Any]] = field(default_factory=dict)
    observations: dict[str, dict[str, Any]] = field(default_factory=dict)
    outcomes: dict[str, dict[str, Any]] = field(default_factory=dict)
    proposals: dict[str, dict[str, Any]] = field(default_factory=dict)
    shadow_state: dict[str, float] = field(default_factory=dict)

    def accept_commitment(self, commitment: dict[str, Any]) -> dict[str, Any]:
        validate_commitment(commitment)
        cid = commitment["commitment_id"]
        prior = self.commitments.get(cid)
        if prior:
            if _digest(prior) != _digest(commitment):
                raise ValueError("commitment_id_collision")
            return prior
        self.commitments[cid] = dict(commitment)
        return self.commitments[cid]

    def record_observation(self, observation: dict[str, Any]) -> dict[str, Any]:
        cid = observation.get("commitment_id")
        commitment = self.commitments.get(cid)
        if not commitment:
            raise ValueError("unknown_commitment")
        linked = link_observation(commitment, observation)
        prior = self.observations.get(linked["observation_key"])
        if prior:
            # The observation id is an arrival identity, not a measurement
            # identity. Equivalent evidence must collapse to one observation.
            return prior
        self.observations[linked["observation_key"]] = linked
        return linked

    def settle(self, commitment_id: str, *, now: Any) -> dict[str, Any]:
        commitment = self.commitments.get(commitment_id)
        if not commitment:
            raise ValueError("unknown_commitment")
        oid = outcome_id(commitment_id, commitment["observation_window_end"])
        if oid in self.outcomes:
            return self.outcomes[oid]
        if commitment.get("superseded_by"):
            status, reason = "SUPERSEDED", "superseded_by_new_commitment"
        elif commitment.get("invalidated"):
            status, reason = "INVALIDATED", "commitment_invalidated"
        elif _dt(now) < _dt(commitment["observation_window_end"]):
            status = "PENDING"
            reason = "evaluation_window_not_closed"
        else:
            rows = [row for row in self.observations.values() if row["commitment_id"] == commitment_id
                    and row["window_state"] == "MEASURED"]
            values = {str(row["observation"]["value"]).upper() for row in rows}
            if not rows:
                status, reason = "UNOBSERVABLE", "no_evidence_in_window"
            elif len(values) > 1:
                status, reason = "AMBIGUOUS", "contradictory_observations"
            else:
                value = next(iter(values))
                status = {"SUCCESS": "SUCCESSFUL", "SUCCESSFUL": "SUCCESSFUL",
                          "FAIL": "UNSUCCESSFUL", "UNSUCCESSFUL": "UNSUCCESSFUL",
                          "INVALIDATED": "INVALIDATED"}.get(value, "AMBIGUOUS")
                reason = "evidence_in_window"
        row = {"schema_version": OUTCOME_SCHEMA, "source_sha": commitment["source_sha"],
               "produced_at": _iso(now), "correlation_id": commitment["correlation_id"],
               "idempotency_key": oid, "parent_id": commitment_id, "parent_kind": "commitment",
               "retention_class": "evidence_2y", "lifecycle_state": status,
               "provenance": {"producer": "lane_d.settlement", "inputs": [commitment_id]},
               "outcome_id": oid, "commitment_id": commitment_id, "wake_id": commitment["wake_id"],
               "subject_guid": commitment["subject_guid"], "population": commitment["population"],
               "horizon": commitment["horizon"], "observation_window_end": commitment["observation_window_end"],
               "evaluation_reason": reason, "evidence_ids": sorted(r["observation"]["observation_id"]
                                                                       for r in self.observations.values()
                                                                       if r["commitment_id"] == commitment_id)}
        self.outcomes[oid] = row
        return row

    def calibration(self, outcomes: Iterable[dict[str, Any]], *, population: str, horizon: str) -> dict[str, Any]:
        outcomes = list(outcomes)
        rows = [row for row in outcomes if row.get("lifecycle_state") in {"SUCCESSFUL", "UNSUCCESSFUL"}
                and row.get("population") == population and row.get("horizon") == horizon]
        incompatible = [row for row in outcomes if row.get("lifecycle_state") in {"SUCCESSFUL", "UNSUCCESSFUL"}
                        and (row.get("population") != population or row.get("horizon") != horizon)]
        if incompatible:
            raise ValueError("mixed_population_or_horizon")
        successes = sum(row["lifecycle_state"] == "SUCCESSFUL" for row in rows)
        return {"schema_version": CALIBRATION_SCHEMA, "population": population, "horizon": horizon,
                "sample_size": len(rows), "successful": successes,
                "success_rate": round(successes / len(rows), 6) if rows else None,
                "outcome_ids": sorted(row["outcome_id"] for row in rows),
                "qualified": len(rows) >= MIN_SAMPLES}

    def propose_belief(self, *, belief_key: str, outcomes: list[dict[str, Any]], population: str,
                       horizon: str, revision: int = 1) -> dict[str, Any] | None:
        cal = self.calibration(outcomes, population=population, horizon=horizon)
        if not cal["qualified"]:
            return None
        ids = cal["outcome_ids"]
        pid = str(uuid.uuid5(NS_BELIEF, f"{ids[-1]}{belief_key}{revision}"))
        produced_at = max((str(x.get("produced_at", "")) for x in outcomes), default="")
        proposal = {"schema_version": PROPOSAL_SCHEMA, "source_sha": "lane-d", "produced_at":
                    produced_at or "1970-01-01T00:00:00+00:00", "correlation_id": pid,
                    "idempotency_key": pid, "parent_id": ids[-1], "parent_kind": "outcome",
                    "retention_class": "evidence_2y", "lifecycle_state": "PROPOSED",
                    "provenance": {"producer": "lane_d.shadow_learning", "outcome_ids": ids,
                                   "commitment_ids": sorted({x["commitment_id"] for x in outcomes}),
                                   "wake_ids": sorted({x["wake_id"] for x in outcomes}),
                                   "reason": "sample threshold crossed; deterministic success-rate update",
                                   "threshold": MIN_SAMPLES, "calibration": cal},
                    "belief_proposal_id": pid, "belief_key": belief_key, "proposed_value": cal["success_rate"],
                    "live_mutation": False, "financial_behavior_change": False}
        self.proposals[pid] = proposal
        return proposal

    def accept_shadow(self, proposal_id: str) -> dict[str, Any]:
        row = self.proposals[proposal_id]
        row = dict(row, lifecycle_state="ACCEPTED_SHADOW")
        self.proposals[proposal_id] = row
        self.shadow_state[row["belief_key"]] = row["proposed_value"]
        return row

    def rollback_shadow(self, proposal_id: str) -> None:
        row = self.proposals[proposal_id]
        self.shadow_state.pop(row["belief_key"], None)
        self.proposals[proposal_id] = dict(row, lifecycle_state="REJECTED", rollback_of=proposal_id)


def calibration_metrics(outcomes: Iterable[dict[str, Any]], *, population: str, horizon: str) -> dict[str, Any]:
    return SettlementLedger().calibration(list(outcomes), population=population, horizon=horizon)


def settle_commitment(ledger: SettlementLedger, commitment_id: str, *, now: Any) -> dict[str, Any]:
    """Small explicit entry point for callers; the ledger remains the owner of state."""
    return ledger.settle(commitment_id, now=now)
