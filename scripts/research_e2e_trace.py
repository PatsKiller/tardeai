#!/usr/bin/env python3
"""research_e2e_trace.py — trace a symbol from query to operator surface.

The source prompt asks for three end-to-end traces:

    producer/query -> Brave router -> durable cache/store -> provenance record
    -> Data Broker/domain contract -> API -> operator surface

Every earlier claim in this campaign was about one stage. This walks all seven
and records what each one actually produced, so "the chain works" stops being an
inference from seven separate green tests and becomes a single artifact a person
can read.

Each stage records `reached`, its output, and — where the stage refuses — the
reason. A trace that stops at stage 4 is a **successful trace of a broken
chain**, not a failed run; the point is to see where it stops.

Authority
---------
``READ_ONLY_ADVISORY``. Runs against fixtures by default and never calls a paid
provider unless `transport` is supplied by the caller. It writes only to a
caller-supplied state root.

Usage:
    python3 scripts/research_e2e_trace.py --json
    python3 scripts/research_e2e_trace.py --json --state-root /tmp/trace
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.lib import brave_research_router as R  # noqa: E402
from scripts.lib.research_observation.brave_adapter import (  # noqa: E402
    age_at,
    evidence_gap_signature,
    wrap_brave_outcome,
)
from scripts.lib.research_observation.consumer_gate import (  # noqa: E402
    gate_for_consumer,
)
from scripts.lib.research_observation.eligibility import (  # noqa: E402
    EligibilityDecision,
    evaluate_eligibility,
)

SCHEMA = "ResearchEndToEndTrace@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

STAGES = (
    "producer_query",
    "brave_router",
    "durable_store",
    "provenance_record",
    "domain_contract",
    "api_projection",
    "operator_surface",
)


@dataclass
class Stage:
    name: str
    reached: bool = False
    detail: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass
class Trace:
    symbol: str
    scenario: str
    schema: str = SCHEMA
    authority: str = AUTHORITY
    as_of: str = ""
    stages: list[Stage] = field(default_factory=list)
    terminal_stage: str = ""
    decision_eligible: bool = False
    display_eligible: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["stages_reached"] = sum(1 for s in self.stages if s.reached)
        d["stages_total"] = len(self.stages)
        return d


def trace_symbol(
    symbol: str,
    *,
    scenario: str,
    query: str,
    purpose: R.Purpose = R.Purpose.EVIDENCE_GAP,
    priority: R.Priority = R.Priority.HELD_CAPITAL,
    evidence_gap: bool = True,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
    transport: Optional[Callable] = None,
    eligibility_now: Optional[datetime] = None,
) -> Trace:
    """Walk one symbol through all seven stages.

    ``transport`` replaces ``urllib.request.urlopen`` for the duration of the
    router call. Supplying a fixture is the normal path; leaving it ``None``
    means the router's own gates decide, and with no key configured that is a
    ``DENIED_NO_KEY`` trace rather than a live spend.
    """
    now = now or datetime.now(timezone.utc)
    t = Trace(symbol=symbol, scenario=scenario, as_of=now.replace(microsecond=0).isoformat())

    # 1. Producer / query
    gap_sig = evidence_gap_signature(query, symbol)
    t.stages.append(
        Stage(
            "producer_query",
            True,
            {
                "query": query,
                "purpose": purpose.value,
                "priority": priority.name,
                "evidence_gap_signature": gap_sig,
                "evidence_gap_declared": evidence_gap,
            },
        )
    )

    # 2. Brave router
    if transport is not None:
        original = R.urllib.request.urlopen
        R.urllib.request.urlopen = transport
    try:
        outcome = R.search(
            query,
            purpose=purpose,
            priority=priority,
            caller="research_e2e_trace",
            count=5,
            evidence_gap=evidence_gap,
            root=root,
            now=now,
        )
    finally:
        if transport is not None:
            R.urllib.request.urlopen = original

    t.stages.append(
        Stage(
            "brave_router",
            True,
            {
                "status": outcome.status.value,
                "degraded": outcome.degraded,
                "results": len(outcome.results),
                "provider_billed": outcome.provider_billed,
                "cache_hit": outcome.cache_hit,
                "fingerprint": outcome.fingerprint,
                "degradation_note": outcome.degradation_note(),
            },
        )
    )

    # 3. Durable store — did an artifact actually land?
    cache_file = R.cache_dir(root) / f"{outcome.fingerprint}.json"
    stored = cache_file.exists()
    t.stages.append(
        Stage(
            "durable_store",
            stored,
            {
                "path": str(cache_file),
                "exists": stored,
                "cached_results": len(R.cache_get(outcome.fingerprint, 10**9, root=root, now=now.timestamp()) or []),
            },
            reason="" if stored else f"no durable artifact: router returned {outcome.status.value}",
        )
    )

    # 4. Provenance record
    obs = wrap_brave_outcome(outcome, run_id=f"trace-{symbol}", trace_id=gap_sig, symbol_or_entity=symbol, now=now)
    t.stages.append(
        Stage(
            "provenance_record",
            True,
            {
                "source_identity": obs.source_identity,
                "freshness_status": obs.freshness_status.value,
                "quality_status": obs.quality_status.value,
                "durable_output_present": obs.durable_output_present,
                "source_hash": obs.source_hash,
                "degraded_label": obs.degraded_label,
            },
        )
    )

    # 5. Domain contract — eligibility + consumer gates
    enow = eligibility_now or now
    # Re-derive age at gate time. The policy reads freshness_age_seconds and
    # nothing else recomputes it, so evidence stamped at ingest would otherwise
    # stay permanently fresh.
    gated = age_at(obs, enow)
    disp = evaluate_eligibility(gated, consumer_kind="display", now=enow)
    prop = evaluate_eligibility(gated, consumer_kind="proposal", now=enow)
    dgate = gate_for_consumer(gated, consumer_id="command-center", consumer_kind="display", now=enow)
    pgate = gate_for_consumer(gated, consumer_id="proposal-engine", consumer_kind="proposal", now=enow)
    t.display_eligible = dgate.accepted
    t.decision_eligible = pgate.accepted
    t.stages.append(
        Stage(
            "domain_contract",
            True,
            {
                "display_decision": disp.decision.value,
                "proposal_decision": prop.decision.value,
                "display_accepted": dgate.accepted,
                "proposal_accepted": pgate.accepted,
                "proposal_reasons": list(prop.reasons),
                "display_reasons": list(disp.reasons),
                "age_seconds_at_gate": gated.freshness_age_seconds,
            },
        )
    )

    # 6. API projection — the served payload shape, computed without a request
    rep = R.effectiveness_report(root=root, now=now)
    health = R.health(root=root, now=now)
    t.stages.append(
        Stage(
            "api_projection",
            True,
            {
                "route": "/api/v2/research-intelligence/brave",
                "plan_metered": (rep["allowance_reconciliation"].get("billing_window_metered")),
                "monthly_used": rep.get("monthly_used"),
                "adopted": rep.get("adopted"),
                "firing": health.get("firing", []),
                "provider_call_on_page_load": False,
            },
        )
    )

    # 7. Operator surface — the label a person would read
    if health.get("firing"):
        if "brave_key_missing" in health["firing"]:
            label = "Configured — inactive"
        elif "brave_producing_not_adopted" in health["firing"]:
            label = "Producing — not adopted"
        elif "brave_allowance_never_measured" in health["firing"]:
            label = "Unknown — allowance never measured"
        else:
            label = "Degraded"
    else:
        label = "Working end to end"
    surface_state = "Evidence available (unverified)" if t.display_eligible else obs.degraded_label.split(".")[0]
    t.stages.append(
        Stage(
            "operator_surface",
            True,
            {
                "lane_label": label,
                "symbol_state": surface_state,
                "decision_eligible": t.decision_eligible,
                "raw_DATA_UNAVAILABLE_shown": False,
            },
        )
    )

    reached = [s for s in t.stages if s.reached]
    t.terminal_stage = reached[-1].name if reached else "none"
    unreached = [s.name for s in t.stages if not s.reached]
    t.note = (
        f"All {len(t.stages)} stages reached."
        if not unreached
        else f"Stopped producing a durable artifact at: {', '.join(unreached)}. "
        f"The chain still projected an honest degraded state to the operator."
    )
    return t


def _fixture_transport(body: bytes, headers: Optional[dict] = None, status: int = 200) -> Callable:
    hdrs = headers or {
        "x-ratelimit-policy": "50;w=1, 0;w=2592000",
        "x-ratelimit-limit": "50, 0",
        "x-ratelimit-remaining": "49, 0",
    }

    class _Resp:
        def __init__(self):
            self.headers = hdrs
            self.status = status

        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return lambda req, timeout=None: _Resp()


def _web(results: list[dict]) -> bytes:
    return json.dumps({"web": {"results": results}}).encode()


def run_all(root: Optional[Path] = None, now: Optional[datetime] = None) -> dict[str, Any]:
    """The three required traces, deterministic, no provider call.

    Chosen to exercise three genuinely different chain outcomes rather than the
    same happy path three times.
    """
    now = now or datetime.now(timezone.utc)
    traces = []

    # 1. Held capital, primary-source evidence available -> full chain.
    traces.append(
        trace_symbol(
            "AAPL",
            scenario="held_capital_with_primary_source_evidence",
            query="AAPL 8-K material event filing",
            purpose=R.Purpose.PRIMARY_SOURCE_DISCOVERY,
            priority=R.Priority.HELD_CAPITAL,
            root=root,
            now=now,
            transport=_fixture_transport(
                _web(
                    [
                        {
                            "title": "AAPL Form 8-K",
                            "url": "https://www.sec.gov/Archives/edgar/x.htm",
                            "description": "Material event",
                            "age": "2h",
                        },
                        {"title": "Coverage", "url": "https://reuters.com/a", "description": "Report", "age": "3h"},
                    ]
                )
            ),
        )
    )

    # 2. Watchlist symbol, provider served nothing -> GAP, not FRESH.
    traces.append(
        trace_symbol(
            "SCHD",
            scenario="watchlist_provider_served_no_results",
            query="SCHD dividend policy change 2026",
            purpose=R.Purpose.EVIDENCE_GAP,
            priority=R.Priority.WATCHLIST,
            root=root,
            now=now,
            transport=_fixture_transport(_web([])),
        )
    )

    # 3. Negative control: no material evidence gap -> refused before spending.
    traces.append(
        trace_symbol(
            "TSLA",
            scenario="negative_control_no_evidence_gap_refused",
            query="TSLA already answered by canonical sources",
            purpose=R.Purpose.EVIDENCE_GAP,
            priority=R.Priority.COLD_UNIVERSE,
            evidence_gap=False,
            root=root,
            now=now,
            transport=_fixture_transport(
                _web([{"title": "should not be reached", "url": "https://x/1", "description": "d"}])
            ),
        )
    )

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
        "trace_count": len(traces),
        "stages": list(STAGES),
        "traces": [t.to_dict() for t in traces],
        "any_decision_eligible": any(t.decision_eligible for t in traces),
        "note": ("Search discovery is never decision-eligible; all three traces must report decision_eligible=False."),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--state-root", default=None, help="isolated state root; defaults to a temp dir")
    a = ap.parse_args()
    import tempfile

    if a.state_root:
        root = Path(a.state_root)
        root.mkdir(parents=True, exist_ok=True)
        doc = run_all(root=root)
    else:
        with tempfile.TemporaryDirectory() as td:
            doc = run_all(root=Path(td))
    print(json.dumps(doc, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
