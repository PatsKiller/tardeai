from __future__ import annotations

from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

from .contracts import assert_no_secret_material, canonical_hash
from .sentinel import SentinelReport

_ALLOWED_VERDICTS = {"PASS", "CAUTION", "REJECT", "ABSTAIN", "INSUFFICIENT_EVIDENCE"}


@dataclass(frozen=True)
class CriticLane:
    lane_id: str
    provider_family: str
    model: str
    max_cost_usd: float = 0.0
    enabled: bool = True

    def validate(self) -> None:
        if not self.lane_id.strip() or not self.provider_family.strip() or not self.model.strip():
            raise ValueError("critic lane requires id, provider family and model")
        if self.max_cost_usd < 0:
            raise ValueError("critic lane cost budget must be non-negative")


@dataclass(frozen=True)
class CriticResult:
    lane_id: str
    provider_family: str
    model: str
    verdict: str
    findings: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    cost_usd: float
    duration_ms: float
    output_hash: str
    error: str | None = None


@dataclass(frozen=True)
class CriticReconciliation:
    state: str
    operator_action: str
    deterministic_verdict: str
    deterministic_release_allowed: bool
    results: tuple[CriticResult, ...]
    disagreements: tuple[str, ...]
    failed_lanes: tuple[str, ...]
    panel_version: str = "critic-panel-v1"

    @property
    def reconciliation_hash(self) -> str:
        return canonical_hash(asdict(self))


CriticProvider = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class CriticPanel:
    """Run independent reflective lanes without voting or fallback.

    Each configured provider is called at most once. A failed or mismatched lane
    is retained as an error result; it is never replaced by another provider.
    """

    def __init__(self, lanes: Sequence[CriticLane], providers: Mapping[str, CriticProvider]) -> None:
        lane_ids: set[str] = set()
        for lane in lanes:
            lane.validate()
            if lane.lane_id in lane_ids:
                raise ValueError(f"duplicate critic lane: {lane.lane_id}")
            lane_ids.add(lane.lane_id)
        extra = set(providers).difference(lane_ids)
        if extra:
            raise ValueError(f"providers configured for unknown lanes: {sorted(extra)}")
        self.lanes = tuple(lanes)
        self.providers = dict(providers)

    def review(self, request: Mapping[str, Any], deterministic: SentinelReport) -> CriticReconciliation:
        assert_no_secret_material(request)
        if not deterministic.release_allowed:
            return CriticReconciliation(
                state="BLOCK_DETERMINISTIC",
                operator_action="Do not call reflective critics; inspect deterministic findings.",
                deterministic_verdict=deterministic.verdict,
                deterministic_release_allowed=False,
                results=(),
                disagreements=(),
                failed_lanes=(),
            )

        results = tuple(self._run_lane(lane, request) for lane in self.lanes if lane.enabled)
        return reconcile_critics(results, deterministic)

    def _run_lane(self, lane: CriticLane, request: Mapping[str, Any]) -> CriticResult:
        provider = self.providers.get(lane.lane_id)
        if provider is None:
            return _error_result(lane, "provider not configured", 0.0)
        started = perf_counter()
        try:
            raw = dict(provider(request))
            assert_no_secret_material(raw)
        except Exception as exc:
            duration = (perf_counter() - started) * 1000
            return _error_result(lane, f"{type(exc).__name__}: {exc}", duration)
        duration = (perf_counter() - started) * 1000

        reported_family = str(raw.get("provider_family") or "").strip()
        reported_model = str(raw.get("model") or "").strip()
        if reported_family != lane.provider_family or reported_model != lane.model:
            return _error_result(
                lane,
                f"provider provenance mismatch: expected {lane.provider_family}/{lane.model}, got {reported_family or 'missing'}/{reported_model or 'missing'}",
                duration,
            )

        verdict = str(raw.get("verdict") or "").replace("-", "_").replace(" ", "_").upper()
        findings = _strings(raw.get("findings"))
        evidence_refs = _strings(raw.get("evidence_refs"))
        try:
            cost_usd = float(raw.get("cost_usd") or 0.0)
        except (TypeError, ValueError):
            return _error_result(lane, "invalid cost_usd", duration)
        if cost_usd < 0 or cost_usd > lane.max_cost_usd:
            return _error_result(lane, f"cost budget exceeded: {cost_usd} > {lane.max_cost_usd}", duration)
        if verdict not in _ALLOWED_VERDICTS:
            return _error_result(lane, f"unsupported verdict: {verdict or 'missing'}", duration)
        if verdict in {"PASS", "CAUTION", "REJECT"} and not evidence_refs:
            verdict = "INSUFFICIENT_EVIDENCE"
            findings = findings + ("Verdict downgraded because no evidence references were supplied.",)

        payload = {
            "lane_id": lane.lane_id,
            "provider_family": lane.provider_family,
            "model": lane.model,
            "verdict": verdict,
            "findings": findings,
            "evidence_refs": evidence_refs,
            "cost_usd": cost_usd,
        }
        return CriticResult(
            lane_id=lane.lane_id,
            provider_family=lane.provider_family,
            model=lane.model,
            verdict=verdict,
            findings=findings,
            evidence_refs=evidence_refs,
            cost_usd=cost_usd,
            duration_ms=round(duration, 3),
            output_hash=canonical_hash(payload),
        )


def reconcile_critics(results: Sequence[CriticResult], deterministic: SentinelReport) -> CriticReconciliation:
    if not deterministic.release_allowed:
        return CriticReconciliation(
            state="BLOCK_DETERMINISTIC",
            operator_action="Inspect deterministic findings.",
            deterministic_verdict=deterministic.verdict,
            deterministic_release_allowed=False,
            results=tuple(results),
            disagreements=(),
            failed_lanes=tuple(result.lane_id for result in results if result.error),
        )

    failed = tuple(result.lane_id for result in results if result.error)
    valid = [result for result in results if not result.error]
    verdicts = {result.verdict for result in valid}
    disagreements: list[str] = []

    if not valid:
        state = "PROVIDER_FAILURE"
        action = "Hold for operator review; no reflective lane completed."
    elif failed:
        state = "PARTIAL_PROVIDER_FAILURE"
        action = "Preserve completed reviews and inspect failed lanes; do not substitute providers."
    elif verdicts <= {"ABSTAIN", "INSUFFICIENT_EVIDENCE"}:
        state = "INSUFFICIENT_EVIDENCE"
        action = "Collect more evidence or accept an explicit abstention."
    elif "PASS" in verdicts and "REJECT" in verdicts:
        state = "DISAGREEMENT"
        action = "Escalate the preserved PASS/REJECT disagreement to the operator."
        disagreements.append("PASS and REJECT coexist; majority voting is prohibited.")
    elif "REJECT" in verdicts:
        state = "REFLECTIVE_REJECT"
        action = "Hold for operator review of the rejecting evidence."
    elif "CAUTION" in verdicts:
        state = "CAUTION"
        action = "Review cautions before using the deterministic ticket."
    elif verdicts == {"PASS"}:
        state = "REFLECTIVE_PASS"
        action = "Reflective critics found no supported contradiction; deterministic authority remains unchanged."
    else:
        state = "MIXED_ABSTENTION"
        action = "Review the passing and abstaining lanes independently."
        disagreements.append("Some lanes abstained or lacked evidence while others issued a verdict.")

    return CriticReconciliation(
        state=state,
        operator_action=action,
        deterministic_verdict=deterministic.verdict,
        deterministic_release_allowed=True,
        results=tuple(results),
        disagreements=tuple(disagreements),
        failed_lanes=failed,
    )


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),) if str(value).strip() else ()


def _error_result(lane: CriticLane, error: str, duration_ms: float) -> CriticResult:
    payload = {
        "lane_id": lane.lane_id,
        "provider_family": lane.provider_family,
        "model": lane.model,
        "error": error,
    }
    return CriticResult(
        lane_id=lane.lane_id,
        provider_family=lane.provider_family,
        model=lane.model,
        verdict="ERROR",
        findings=(),
        evidence_refs=(),
        cost_usd=0.0,
        duration_ms=round(duration_ms, 3),
        output_hash=canonical_hash(payload),
        error=error,
    )
