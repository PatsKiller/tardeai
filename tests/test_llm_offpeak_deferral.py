"""Off-peak deferral for paid LLM work + the operator's per-caller priority (2026-09-19).

Operator directive: when the free lanes are exhausted the work still has to reach
DeepSeek, but only the operator's own asks and callers they have marked critical may
spend at peak. Everything else is queued for the next off-peak window.

What this replaces: `deepseek_offpeak.should_scheduled_skip` returned True at peak and the
wrapper logged PEAK_SKIP and exited 0 — the work was DROPPED, nothing recorded that a
question went unasked, and nothing ever asked it.

These tests never touch the production database. A fixture in this repo has done that
before; the queue functions are exercised against a captured fake instead.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import llm_deferral as D  # noqa: E402
from lib.deepseek_offpeak import ET, is_scheduled_deepseek_window  # noqa: E402

# Verified against the window predicate itself, not asserted independently of it.
WED_PEAK = datetime(2026, 9, 16, 2, 0, tzinfo=ET)    # 06:00 UTC Wed -> DeepSeek peak
WED_LATE = datetime(2026, 9, 16, 23, 0, tzinfo=ET)   # outside the 09-21 ET operator window
WED_OPEN = datetime(2026, 9, 16, 14, 0, tzinfo=ET)   # inside both
SAT_OPEN = datetime(2026, 9, 19, 2, 0, tzinfo=ET)    # weekend: exempt by the operator rule


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """No test here may reach a real database."""
    monkeypatch.setattr(D, "_db_tiers", lambda: {})
    monkeypatch.setenv("LLM_DEFER_OFFPEAK", "1")


def test_the_fixture_times_are_what_the_window_predicate_says():
    """Anchor the table above to the gate, so a window change fails here loudly."""
    assert is_scheduled_deepseek_window(WED_PEAK) is False
    assert is_scheduled_deepseek_window(WED_LATE) is False
    assert is_scheduled_deepseek_window(WED_OPEN) is True
    assert is_scheduled_deepseek_window(SAT_OPEN) is True, "weekends are exempt"


# --------------------------------------------------------------------------- policy

def test_automated_work_outside_the_window_is_deferred_not_dropped():
    d = D.evaluate("hermes_external_research", now=WED_PEAK)
    assert d.defer is True
    assert d.reason == "OUTSIDE_OFFPEAK_WINDOW"
    assert d.run_after is not None and is_scheduled_deepseek_window(d.run_after)


def test_operator_request_never_waits():
    """The exemption the off-peak rule already carried: the operator is waiting."""
    d = D.evaluate("hermes_external_research", manual_trigger=True, now=WED_PEAK)
    assert d.defer is False and d.reason == "OPERATOR_REQUEST"


def test_a_caller_the_operator_marked_critical_spends_at_peak(monkeypatch):
    monkeypatch.setattr(D, "_db_tiers", lambda: {"stop_manager": D.TIER_CRITICAL})
    d = D.evaluate("stop_manager", now=WED_PEAK)
    assert d.defer is False and d.reason == "CRITICAL_CALLER" and d.tier == "critical"


def test_deferred_tier_waits_even_when_the_window_is_open(monkeypatch):
    monkeypatch.setattr(D, "_db_tiers", lambda: {"bulk_backfill": D.TIER_DEFERRED})
    d = D.evaluate("bulk_backfill", now=WED_OPEN)
    assert d.defer is True and d.reason == "TIER_ALWAYS_DEFERRED"


def test_inside_the_window_standard_work_just_runs():
    assert D.evaluate("hermes_external_research", now=WED_OPEN).defer is False
    assert D.evaluate("hermes_external_research", now=SAT_OPEN).defer is False


def test_an_unclassified_caller_does_not_inherit_the_right_to_spend_at_peak():
    """Default must be `standard`. A caller nobody reviewed must not read as critical."""
    assert D.resolve_tier("a_caller_nobody_has_ever_seen") == D.TIER_STANDARD
    assert D.evaluate("a_caller_nobody_has_ever_seen", now=WED_PEAK).defer is True


def test_disabled_by_default_so_it_ships_inert(monkeypatch):
    monkeypatch.delenv("LLM_DEFER_OFFPEAK", raising=False)
    assert D.enabled() is False
    assert D.evaluate("anything", now=WED_PEAK).reason == "DEFERRAL_DISABLED"


def test_a_disabled_feature_touches_no_database(monkeypatch):
    """Off must cost nothing and say nothing.

    This sits on the paid-call chokepoint. Resolving a tier costs a DB round-trip and a
    registry read, and the first version resolved it BEFORE checking the flag — so with
    the feature off (its shipped state) every DeepSeek call ran a SELECT against
    llm_caller_priority, and printed a SQL error for each one when the table was absent.
    """
    monkeypatch.delenv("LLM_DEFER_OFFPEAK", raising=False)

    def _boom():
        raise AssertionError("the disabled path must not resolve a tier")

    monkeypatch.setattr(D, "resolve_tier", lambda *a, **k: _boom())
    d = D.evaluate("any_caller", now=WED_PEAK)
    assert d.defer is False and d.reason == "DEFERRAL_DISABLED"
    assert d.tier == "unresolved", "do not report a tier that was never looked up"


def test_the_bypass_path_also_resolves_nothing(monkeypatch):
    """The drainer already knows it is draining; making it pay for a lookup is waste."""
    def _boom():
        raise AssertionError("the bypass path must not resolve a tier")

    monkeypatch.setattr(D, "resolve_tier", lambda *a, **k: _boom())
    assert D.evaluate("any_caller", bypass=True, now=WED_PEAK).reason == "DRAIN_BYPASS"


def test_the_drainer_bypass_cannot_requeue_its_own_work():
    assert D.evaluate("anything", bypass=True, now=WED_PEAK).reason == "DRAIN_BYPASS"


def test_operator_setting_overrides_the_registry_seed(monkeypatch):
    monkeypatch.setattr(D, "_registry_tiers", lambda: {"x": D.TIER_CRITICAL})
    assert D.resolve_tier("x") == D.TIER_CRITICAL
    monkeypatch.setattr(D, "_db_tiers", lambda: {"x": D.TIER_DEFERRED})
    assert D.resolve_tier("x") == D.TIER_DEFERRED, "the operator's choice wins"


def test_set_tier_refuses_a_tier_that_is_not_a_behaviour():
    with pytest.raises(ValueError):
        D.set_tier("x", "urgent-ish")


def test_next_window_start_lands_inside_the_window_from_every_fixture():
    for t in (WED_PEAK, WED_LATE, WED_OPEN, SAT_OPEN):
        assert is_scheduled_deepseek_window(D.next_window_start(t))


# --------------------------------------------------------------------------- queue

class _FakeDB:
    def __init__(self):
        self.sql: list[tuple] = []
        self.pending_keys: set[str] = set()

    def __call__(self, sql, params=None, fetch=None):
        self.sql.append((" ".join(sql.split()), params))
        if "INSERT INTO llm_deferred_requests" in sql:
            key = params[7]
            if key in self.pending_keys:
                return None            # the partial unique index held
            self.pending_keys.add(key)
            return {"id": "11111111-2222-3333-4444-555555555555"}
        if fetch == "all":
            return []
        if fetch == "one":
            return None
        return True


@pytest.fixture
def fake_db(monkeypatch):
    db = _FakeDB()
    import db_adapter
    monkeypatch.setattr(db_adapter, "_execute", db)
    return db


def test_an_identical_pending_question_is_queued_once(fake_db):
    """An hourly caller deferring for twelve hours must not queue twelve copies."""
    d = D.evaluate("hermes_external_research", now=WED_PEAK)
    first = D.enqueue(process_id="p", lane="fast", prompt="same question", decision=d)
    second = D.enqueue(process_id="p", lane="fast", prompt="same question", decision=d)
    assert first and second is None
    assert D.dedupe_key("p", "same") != D.dedupe_key("p", "different")


def test_the_ttl_clock_starts_at_the_window_not_at_enqueue(fake_db):
    """Deferred Friday night for a Monday window, a request must still be alive then."""
    d = D.evaluate("p", now=WED_LATE)
    D.enqueue(process_id="p", lane="fast", prompt="q", decision=d, ttl_hours=6)
    insert = next(s for s in fake_db.sql if "INSERT INTO llm_deferred_requests" in s[0])
    run_after, expires_at = insert[1][8], insert[1][9]
    assert expires_at == run_after + timedelta(hours=6)
    assert expires_at > d.run_after


def test_claim_uses_skip_locked_so_two_drainers_cannot_double_spend(fake_db):
    D.claim_due(limit=5)
    claim = next(s for s in fake_db.sql if "UPDATE llm_deferred_requests SET status = 'claimed'" in s[0])
    assert "FOR UPDATE SKIP LOCKED" in claim[0]


def test_dry_run_previews_without_claiming(fake_db):
    """A preview that consumes the work it previews is worse than no preview.

    Measured 2026-09-20 on the first live exercise: --dry-run called claim_due(), which
    moves rows pending -> claimed, printed them and exited. The row was stranded in
    'claimed' forever — never run, never expired, invisible to pending counts.
    """
    D.preview_due(limit=5)
    sql = " ".join(s for s, _ in fake_db.sql)
    assert "SELECT" in sql
    assert "SET status = 'claimed'" not in sql, "preview must not mutate"
    assert "FOR UPDATE" not in sql


def test_the_drain_script_dry_run_path_never_calls_claim():
    """Pinned against the source: the ordering is the whole bug."""
    src = (ROOT / "scripts" / "drain_llm_deferred.py").read_text(encoding="utf-8")
    dry = src.index("if args.dry_run:")
    claim = src.index("batch = llm_deferral.claim_due")
    assert dry < claim, "the dry-run branch must return before claim_due is reached"
    assert "llm_deferral.preview_due(limit=args.limit)" in src


def test_a_stranded_claim_comes_back_to_the_queue(fake_db):
    """A drain killed mid-batch must not remove work from existence."""
    D.reclaim_stale()
    sql = " ".join(s for s, _ in fake_db.sql)
    assert "SET status = 'pending', claimed_at = NULL" in sql
    assert "status = 'claimed' AND claimed_at <" in sql


def test_a_poison_request_is_retired_not_retried_forever(fake_db):
    """Retrying a request that always fails burns the money the queue exists to save."""
    D.reclaim_stale()
    calls = [s for s, _ in fake_db.sql if "SET status = 'failed'" in s]
    assert calls, "rows past MAX_ATTEMPTS must be retired"
    assert "attempts >= " in calls[0]
    assert D.MAX_ATTEMPTS >= 1


def test_reclaim_runs_before_the_queue_is_counted():
    """Counting first would report a queue smaller than the outstanding work."""
    src = (ROOT / "scripts" / "drain_llm_deferred.py").read_text(encoding="utf-8")
    assert src.index("reclaim_stale()") < src.index("queue_summary()")


def test_the_queue_table_mints_its_own_ids():
    """watchlist_agent_jobs.id has no default and every insert must supply one."""
    assert "id            UUID PRIMARY KEY DEFAULT gen_random_uuid()" in D.DDL


# ------------------------------------------------------------------ chokepoint wiring

def test_the_spend_chokepoint_defers_before_it_reserves():
    """A deferred call must not consume the cap reservation it never spent."""
    src = (ROOT / "scripts" / "lib" / "llm_consumption.py").read_text(encoding="utf-8")
    hook = src.index("from lib.llm_deferral import DeferredToOffPeak")
    reserve = src.index("reservation_id = None", hook - 4000)
    assert hook < reserve, "deferral must be evaluated before the reservation is taken"


def test_an_unreachable_queue_refuses_rather_than_quietly_paying_peak():
    src = (ROOT / "scripts" / "lib" / "llm_consumption.py").read_text(encoding="utf-8")
    assert "DEFERRAL_QUEUE_UNAVAILABLE" in src
    assert "not queued and not spent" in src


def test_deferred_error_is_a_runtime_error_so_unaware_callers_degrade():
    assert issubclass(D.DeferredToOffPeak, RuntimeError)
    e = D.DeferredToOffPeak("p", "fast", "abc", WED_OPEN, "OUTSIDE_OFFPEAK_WINDOW")
    assert "abc" in str(e) and "DEFERRED_TO_OFFPEAK" in str(e)


# ------------------------------------------------------------------ scheduling + UI

def test_the_drainer_is_declared_as_a_lane_with_a_durable_signal():
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
    lane = next((l for l in reg["lanes"] if l["lane_id"] == "llm-deferred-drain"), None)
    assert lane, "config/lane_registry.json must declare llm-deferred-drain"
    assert lane["state"] == "ACTIVE"
    assert "drain_llm_deferred.py" in lane["scheduler"]["match"]
    assert lane["output_signal"]["kind"] == "file_mtime"
    assert lane["output_signal"]["path"] == "data/runtime/llm_deferred_drain.json"


def test_the_drainer_will_not_run_outside_the_window_without_force():
    src = (ROOT / "scripts" / "drain_llm_deferred.py").read_text(encoding="utf-8")
    assert "if not in_window and not args.force:" in src
    assert "OUTSIDE_OFFPEAK_WINDOW" in src


def test_the_operator_can_reach_the_control_from_the_menu():
    """A route with no nav entry is reachable only by knowing the URL."""
    nav = (ROOT / "apps/command-center-v3/src/components/NavRail.tsx").read_text(encoding="utf-8")
    assert "'/consumption'" in nav, "LLM Spend must be on the nav rail"
    hub = (ROOT / "apps/command-center-v3/src/pages/ConsumptionHub.tsx").read_text(encoding="utf-8")
    assert "LlmRoutingModal" in hub


def test_the_api_exposes_read_and_save_for_the_priorities():
    api = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    assert '"/api/v2/consumption/caller-priorities": lambda: _llm_caller_priorities()' in api
    assert 'base_path == "/api/v2/consumption/caller-priorities"' in api
    assert '"/api/v2/consumption/deferred-queue": lambda: _llm_deferred_queue()' in api


def test_saving_rejects_an_unknown_tier_rather_than_storing_it():
    api = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    assert "unknown process_id or tier" in api
