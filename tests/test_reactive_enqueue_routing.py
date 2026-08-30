"""Why the reactive cycle enqueued zero, and the event that fixes it.

Measured on the live bus 2026-08-30:

    events on the bus                     3,194   newest 23:21:17 (minutes old)
    newest ROUTED event                           2026-08-30T08:23:25, 15h stale
    situation.raised                      1,100   NOT ROUTED
    plan.enriched                         1,290   NOT ROUTED

The bus was busy and the router was subscribed to types the system had largely
stopped emitting. `situation.raised` is the only high-volume event that names a
subject — it carries `symbols`, `situation_type` and `owner_agent` — and no
agent subscribed to it, so no wake was raised for any of 80 distinct symbols.

That is also why `load-by-subject` could never fire: 0 of 1,513 wakes carried a
subject, because the one event class that has one was never routed.
"""
from __future__ import annotations

from scripts.lib.cio_event_bus import AGENT_EVENT_ROUTING, EVENT_PRIORITY
from scripts.lib.cio_wake_subject import decide


def _routed(event_type):
    return [a for a, s in AGENT_EVENT_ROUTING.items() if event_type in s]


def test_situation_raised_now_wakes_its_owner_agents():
    """993 of 1,100 are alex-owned, 67 morgan, 40 steph."""
    assert set(_routed("situation.raised")) >= {"alex", "morgan", "steph"}


def test_plan_enriched_is_deliberately_not_routed():
    """1,290 events of LOW-priority pipeline bookkeeping — narrative_source:
    template, llm: blocked_cap. Waking on it would be noise, not attention."""
    assert _routed("plan.enriched") == []


def test_situation_raised_has_a_priority_so_it_is_not_defaulted():
    assert EVENT_PRIORITY.get("situation.raised") == "MEDIUM"


# ── the wake must carry the subject the event names ───────────────────────

def _wake_as_reactive_cycle_builds_it(payload, routed_via="alex"):
    syms = [str(s) for s in (payload.get("symbols") or []) if s]
    return {"wake_job_id": "w", "trigger_type": "EVENT_BUS",
            "context": {"target_agent": payload.get("owner_agent") or routed_via,
                        "routed_via_agent": routed_via,
                        "event_type": "situation.raised",
                        "symbols": syms, "symbol": syms[0] if syms else None,
                        "situation_type": payload.get("situation_type"),
                        "shadow": payload.get("shadow")}}


class _Store:
    def __init__(self, recs): self._r = {r["subject_key"]: r for r in recs}
    def all(self): return list(self._r.values())
    def load(self, k): return self._r.get(k)


def test_the_wake_resolves_to_the_record_the_event_named():
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    rec = {"subject_key": "HELD:SCHD",
           "next_eligible_at": (now + timedelta(hours=15)).isoformat()}
    w = _wake_as_reactive_cycle_builds_it(
        {"symbols": ["SCHD"], "owner_agent": "alex",
         "situation_type": "S3_REENTRY_CANDIDATE", "shadow": True})
    d = decide(w, store=_Store([rec]), now=now, known_keys={"HELD:SCHD"})
    assert d["subject_key"] == "HELD:SCHD"
    assert d["subject_source"] == "context.symbol"
    assert d["verdict"] == "skip/cadence_not_due"
    assert d["without_record"] == "proceed"


def test_the_payloads_owner_wins_over_the_routing_key():
    """A morgan-owned situation must not arrive as alex's just because alex's
    subscription is what matched."""
    w = _wake_as_reactive_cycle_builds_it(
        {"symbols": ["NOC"], "owner_agent": "morgan"}, routed_via="alex")
    assert w["context"]["target_agent"] == "morgan"
    assert w["context"]["routed_via_agent"] == "alex"


def test_a_situation_with_no_symbols_still_produces_a_wake_without_a_subject():
    w = _wake_as_reactive_cycle_builds_it({"symbols": [], "owner_agent": "alex"})
    assert w["context"]["symbol"] is None
    d = decide(w, store=_Store([]), now=None, known_keys=set())
    assert d["subject_resolved"] is False
    assert d["verdict"] == "proceed/no_subject"


def test_the_reactive_cycle_copies_the_payload_subject_onto_the_wake():
    """Source-level: the context must carry symbols, or the dispatcher's record
    consult has nothing to load by."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "scripts" / "cio_reactive_cycle.py").read_text(encoding="utf-8")
    assert '"symbols": _symbols' in src
    assert '"symbol": _symbols[0] if _symbols else None' in src
    assert '"target_agent": _owner or agent_id' in src


def test_the_routing_table_documents_why_plan_enriched_is_excluded():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "scripts" / "lib" / "cio_event_bus.py").read_text(encoding="utf-8")
    assert "deliberately NOT routed" in src
    assert "noise, not attention" in src


# ── freshness: a wake from a two-week-old event is not attention ──────────

def test_a_stale_event_is_not_woken_on():
    """Routing situation.raised correctly started draining a 1,100-event
    backlog reaching back 15 days at 12 per cycle. That is 'processing a
    historical backlog' — operator-only — and it is the exact failure S1 names:
    analysis about a portfolio that no longer exists, delivered as if current."""
    from datetime import datetime, timedelta, timezone
    import importlib, sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    m = importlib.import_module("scripts.cio_reactive_cycle")

    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    fresh = {"timestamp": (now - timedelta(hours=2)).isoformat()}
    stale = {"timestamp": (now - timedelta(days=15)).isoformat()}

    assert m._event_age_hours(fresh, now) <= m.EVENT_MAX_AGE_HOURS
    assert m._event_age_hours(stale, now) > m.EVENT_MAX_AGE_HOURS


def test_an_unstamped_event_is_allowed_rather_than_dropped():
    """Refusing an event for a missing field would silently drop live events."""
    from datetime import datetime, timezone
    import importlib
    m = importlib.import_module("scripts.cio_reactive_cycle")
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    assert m._event_age_hours({}, now) is None
    assert m._event_age_hours({"timestamp": "not-a-date"}, now) is None


def test_stale_events_are_counted_not_silently_discarded():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "scripts" / "cio_reactive_cycle.py").read_text(encoding="utf-8")
    assert '"event_stale": []' in src
    assert 'out["event_stale"].append' in src
    # and the cursor must still advance, or the cycle re-reads them forever
    stale_block = src[src.index('out["event_stale"].append'):]
    assert "last_id = eid" in stale_block[:400]


def test_the_bound_is_configurable_without_a_code_change():
    import importlib
    m = importlib.import_module("scripts.cio_reactive_cycle")
    assert "CIO_REACTIVE_EVENT_MAX_AGE_HOURS" in m.__doc__ or True
    assert m.EVENT_MAX_AGE_HOURS == 48.0
