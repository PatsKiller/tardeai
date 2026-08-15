"""R4 decision-use audit — what research was shown to a decision.

In-process, immutable records. HMAC-signed via R1 ReceiptAuthority.
A live research use without a verifying audit FAILS RG-10.

READ_ONLY_ADVISORY. Does not send Telegram or change broker state.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Optional

from .enums import EvidenceGrade, InfluenceClass
from .models import ResearchEvidence, _stable_hash
from .receipts import AUTHORITY as RECEIPT_AUTHORITY

AUTHORITY = "READ_ONLY_ADVISORY"
MAX_INFLUENCE_PCT = 10.0
FORBIDDEN_ACTIONS = frozenset({
    "standalone_sell",
    "create_trim_from_seasonality",
    "broker_order",
    "stop_change",
    "telegram_send",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DecisionUseRecord:
    decision_id: str
    query: dict
    fact_ids: tuple
    grades: tuple
    influence_class: str
    influence_cap_pct: float
    forbidden_actions: tuple
    as_of: str
    authority: str = AUTHORITY
    issuer_id: Optional[str] = None
    signature: Optional[str] = None
    record_digest: Optional[str] = None

    def payload(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "query": self.query,
            "fact_ids": list(self.fact_ids),
            "grades": list(self.grades),
            "influence_class": self.influence_class,
            "influence_cap_pct": self.influence_cap_pct,
            "forbidden_actions": list(self.forbidden_actions),
            "as_of": self.as_of,
            "authority": self.authority,
            "issuer_id": self.issuer_id,
        }

    def verify(self) -> bool:
        if self.record_digest != _stable_hash(self.payload()):
            return False
        return RECEIPT_AUTHORITY.verify(self.payload(), self.signature, self.issuer_id)


class DecisionUseLedger:
    """Append-only in-process ledger (durable store deferred)."""

    def __init__(self) -> None:
        self._rows: list[DecisionUseRecord] = []

    def record(
        self,
        *,
        decision_id: str,
        query: dict,
        evidence: list[ResearchEvidence],
        influence_class: str = InfluenceClass.CONTEXT_MODIFIER.value,
        influence_cap_pct: float = MAX_INFLUENCE_PCT,
        as_of: Optional[str] = None,
    ) -> DecisionUseRecord:
        if not decision_id or not str(decision_id).strip():
            raise ValueError("decision_id required")
        if influence_cap_pct > MAX_INFLUENCE_PCT:
            raise ValueError(f"influence cap {influence_cap_pct} exceeds {MAX_INFLUENCE_PCT}")
        if influence_class != InfluenceClass.CONTEXT_MODIFIER.value:
            # Seasonality / narrative cannot escalate via the audit path.
            if any(e.evidence_type.value == "SEASONALITY" for e in evidence):
                raise ValueError("seasonality cannot escalate influence via audit")
        rec = DecisionUseRecord(
            decision_id=str(decision_id),
            query=dict(query or {}),
            fact_ids=tuple(e.fact_id for e in evidence),
            grades=tuple(e.evidence_grade.value for e in evidence),
            influence_class=influence_class,
            influence_cap_pct=float(influence_cap_pct),
            forbidden_actions=tuple(sorted(FORBIDDEN_ACTIONS)),
            as_of=as_of or _now(),
            issuer_id=RECEIPT_AUTHORITY.issuer_id,
        )
        rec = replace(rec, signature=RECEIPT_AUTHORITY.sign(rec.payload()))
        rec = replace(rec, record_digest=_stable_hash(rec.payload()))
        self._rows.append(rec)
        return rec

    def for_decision(self, decision_id: str) -> list[DecisionUseRecord]:
        return [r for r in self._rows if r.decision_id == decision_id]

    def all(self) -> list[DecisionUseRecord]:
        return list(self._rows)


def is_authentic_audit(rec: Any) -> bool:
    return isinstance(rec, DecisionUseRecord) and rec.verify() is True


# Module-level dry ledger (tests inject their own).
LEDGER = DecisionUseLedger()
