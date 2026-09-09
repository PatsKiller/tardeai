"""Lane I — priors / calibration only after Lane H valid evaluated commitments."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import hashlib

SCHEMA = "PriorCalibration@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MIN_SAMPLES = 5


@dataclass
class CalibrationStore:
    cohort: str
    samples: list[dict[str, Any]] = field(default_factory=list)
    source_sha: str = ""

    def add_outcome(self, *, commitment_id: str, confidence: float, outcome: str, lesson_provenance: str) -> None:
        if outcome not in ("CONFIRMED", "REFUTED", "EXPIRED"):
            raise ValueError("scoring_requires_settled_outcome")
        if lesson_provenance not in ("OUTCOME_DERIVED", "RESEARCH_DERIVED"):
            raise ValueError("illegal_lesson_provenance")
        if lesson_provenance == "OUTCOME_DERIVED" and outcome == "REFUTED":
            # REFUTED never hidden
            pass
        self.samples.append(
            {
                "commitment_id": commitment_id,
                "confidence": float(confidence),
                "outcome": outcome,
                "lesson_provenance": lesson_provenance,
            }
        )

    def summary(self) -> dict[str, Any]:
        n = len(self.samples)
        if n == 0:
            status = "absent"
        elif n < MIN_SAMPLES:
            status = "insufficient_sample"
        else:
            status = "live"
        refuted = sum(1 for s in self.samples if s["outcome"] == "REFUTED")
        confirmed = sum(1 for s in self.samples if s["outcome"] == "CONFIRMED")
        return {
            "schema_version": SCHEMA,
            "cohort": self.cohort,
            "n": n,
            "status": status,
            "confirmed": confirmed,
            "refuted": refuted,
            "refuted_hidden": False,
            "min_samples": MIN_SAMPLES,
            "authority": AUTHORITY,
            "source_sha": self.source_sha,
            "produced_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "store_id": hashlib.sha256(f"{self.cohort}|{n}".encode()).hexdigest()[:16],
        }


def gate_scoring_allowed(*, valid_evaluated_commitments: int) -> bool:
    return int(valid_evaluated_commitments) > 0
