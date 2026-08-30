"""The search budget cannot fail open, and pool degradation is not silent.

Measured 2026-08-30:

    ledger  monthly_calls 2026-08: 150      last_call 2026-08-10
    provider dashboard    2026-08: ~1,000

The budget layer was correct for the callers that used it and saw ~15% of the
traffic. Eleven Brave call sites existed; four held their own client and never
imported the budgeted one, and three more were not even in the first census I
wrote. The alert path was wired, scheduled and reaching a channel, and reported
`monthly_pct: 17.6, monthly_alert: "ok"` while the provider was at its ceiling.
A working alarm on an unrepresentative sensor.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scripts.lib import search_budget as sb
from scripts.lib import search_health as sh

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


# ── never fail open ────────────────────────────────────────────────────────

def test_an_unreadable_ledger_denies_rather_than_resetting_the_counter(tmp_path):
    """The exact old bug: `_load_budget()` swallowed every exception and
    returned {}, which the caller rebuilt as a fresh zero counter — so a corrupt
    ledger produced an UNBUDGETED call."""
    p = sb.budget_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ this is not json", encoding="utf-8")

    with pytest.raises(sb.BudgetUnavailable):
        sb.status("brave", root=tmp_path)

    verdict = sb.check("brave", root=tmp_path)
    assert verdict["allowed"] is False
    assert "BUDGET_UNAVAILABLE" in verdict["reason"]


def test_a_ledger_that_is_not_a_dict_denies(tmp_path):
    p = sb.budget_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("[1,2,3]", encoding="utf-8")
    assert sb.check("brave", root=tmp_path)["allowed"] is False


def test_check_never_raises_whatever_the_ledger_contains(tmp_path):
    """A caller must always get an answer; the answer under doubt is DENY."""
    p = sb.budget_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    for junk in ("", "null", "0", '"a string"', "{}"):
        p.write_text(junk, encoding="utf-8")
        v = sb.check("brave", root=tmp_path)
        assert isinstance(v, dict) and "allowed" in v


def test_a_missing_ledger_is_a_fresh_budget_not_an_error(tmp_path):
    """Absent is different from corrupt: a first run must be allowed."""
    v = sb.check("brave", root=tmp_path)
    assert v["allowed"] is True
    assert v["status"]["monthly_used"] == 0


# ── per provider ───────────────────────────────────────────────────────────

def test_providers_have_separate_counters(tmp_path):
    for _ in range(5):
        sb.record("brave", caller="t", now=NOW, root=tmp_path)
    assert sb.status("brave", now=NOW, root=tmp_path)["monthly_used"] == 5
    assert sb.status("tavily", now=NOW, root=tmp_path)["monthly_used"] == 0


def test_exhausting_the_daily_cap_denies_then_the_next_day_allows(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "3")
    for _ in range(3):
        sb.record("brave", caller="t", now=NOW, root=tmp_path)
    assert sb.check("brave", now=NOW, root=tmp_path)["reason"] == "DAILY_EXHAUSTED"

    tomorrow = NOW.replace(day=31)
    assert sb.check("brave", now=tomorrow, root=tmp_path)["allowed"] is True


def test_the_monthly_cap_binds_even_when_the_daily_one_does_not(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "2")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "100")
    for _ in range(2):
        sb.record("brave", caller="t", now=NOW, root=tmp_path)
    assert sb.check("brave", now=NOW, root=tmp_path)["reason"] == "MONTHLY_EXHAUSTED"


def test_a_malformed_env_override_keeps_the_safe_default(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "not-a-number")
    st = sb.status("brave", now=NOW, root=tmp_path)
    assert st["monthly_limit"] == sb.DEFAULT_LIMITS["brave"]["monthly"]


# ── the ledger survives a process, and is not release-relative ────────────

def test_the_ledger_lives_under_the_canonical_state_root_not_a_release(tmp_path):
    """The original counter was `_PROJECT_ROOT/data/portfolios/state/...` where
    _PROJECT_ROOT is wherever the module was imported from."""
    p = sb.budget_path()
    assert "data/runtime/search_budget.json" in str(p)
    assert "portfolio-server/" not in str(p), "must not be pinned to one release"


def test_counts_persist_across_a_fresh_read(tmp_path):
    sb.record("brave", caller="t", now=NOW, root=tmp_path)
    doc = json.loads(sb.budget_path(tmp_path).read_text(encoding="utf-8"))
    assert doc["providers"]["brave"]["monthly"]["2026-08"] == 1


# ── guard() and note() ────────────────────────────────────────────────────

def test_guard_counts_the_call_it_permits(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "budget_path", lambda root=None: tmp_path / "b.json")
    assert sb.guard("brave", "t") is True
    assert sb.status("brave")["monthly_used"] == 1


def test_guard_records_denials_separately_from_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "budget_path", lambda root=None: tmp_path / "b.json")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "1")
    assert sb.guard("brave", "t") is True
    assert sb.guard("brave", "t") is False
    st = sb.status("brave")
    assert st["monthly_used"] == 1, "a denied call must not count as spend"
    assert st["denied_today"] == 1


def test_note_counts_but_never_denies(tmp_path, monkeypatch):
    """Key validators burn a real credit, so they must be counted — but denying
    one would report a healthy key as dead, which is the worse failure."""
    monkeypatch.setattr(sb, "budget_path", lambda root=None: tmp_path / "b.json")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "0")
    assert sb.check("brave")["allowed"] is False
    sb.note("brave", "secret_validators")               # must not raise
    assert sb.status("brave")["monthly_used"] == 1


# ── pool degradation is never silent ──────────────────────────────────────

def _probe(serving, unresponsive, results=10, reachable=True):
    return lambda *a, **k: {
        "reachable": reachable, "results": results,
        "serving_engines": sorted(serving), "engine_counts": {e: 1 for e in serving},
        "unresponsive": [{"engine": e, "reason": r} for e, r in unresponsive],
    }


def test_ten_results_from_one_engine_is_impaired(monkeypatch):
    """The measured failure: 10 results, all from bing, three engines down —
    a response indistinguishable from a healthy one."""
    monkeypatch.setattr(sh, "probe_searxng", _probe(
        ["bing"], [("duckduckgo", "CAPTCHA"), ("startpage", "CAPTCHA"),
                   ("brave", "too many requests")], results=10))
    h = sh.pool_health(now=NOW)
    assert h["impaired"] is True
    assert h["results"] == 10, "result COUNT looked healthy — that is the point"
    assert h["engines_serving_count"] == 1
    assert "impaired" in h["degradation_note"]
    assert "duckduckgo" in h["degradation_note"]


def test_a_healthy_pool_is_not_flagged(monkeypatch):
    monkeypatch.setattr(sh, "probe_searxng", _probe(
        ["bing", "brave"], [("startpage", "CAPTCHA")], results=23))
    h = sh.pool_health(now=NOW)
    assert h["impaired"] is False
    assert "healthy" in h["degradation_note"]


def test_an_unreachable_pool_is_impaired_not_empty(monkeypatch):
    monkeypatch.setattr(sh, "probe_searxng", _probe([], [], 0, reachable=False))
    h = sh.pool_health(now=NOW)
    assert h["impaired"] is True
    assert h["reachable"] is False


def test_the_lane_fires_on_an_impaired_pool(monkeypatch):
    monkeypatch.setattr(sh, "probe_searxng", _probe(["bing"], [("ddg", "CAPTCHA")]))
    lane = sh.collect_search_health(now=NOW)
    assert lane["lane"] == "search-providers"
    assert lane["ok"] is False
    assert "engine_pool_impaired" in lane["firing"]


def test_the_lane_can_run_without_probing_for_ci():
    lane = sh.collect_search_health(now=NOW, probe=False)
    assert lane["lane"] == "search-providers"
    assert isinstance(lane["budgets"], dict)


def test_impairment_is_decided_by_engines_not_by_result_count(monkeypatch):
    """A single engine returning 100 results is still one engine's blind spots."""
    monkeypatch.setattr(sh, "probe_searxng", _probe(["bing"], [], results=100))
    assert sh.pool_health(now=NOW)["impaired"] is True
