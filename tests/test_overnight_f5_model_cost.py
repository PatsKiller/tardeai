"""WAVE F5 — model-call cost accounting (AGENTS.md §9.2 / §12).

Invariants:
  * every measured call records cost + rate_tier (peak|off_peak|flat) + cache_hit
  * accounting path has no hardcoded USD rate literals
  * budget check before call never fails open
  * weekend UTC clock-windows are off-peak (weekday peak only)
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.llm_model_registry import estimate_usd_cost
from lib.provider_cost.budget import BudgetDenied, ensure_budget_allows_call
from lib.provider_cost.emit import emit_cost_event
from lib.provider_cost.pricing import calculate_usd, is_peak, resolve_schedule
from lib.provider_cost.schema import ProviderCostEvent


PEAK_WEEKDAY = datetime(2026, 8, 31, 2, 0, tzinfo=timezone.utc)   # Mon 02:00 UTC
OFF_WEEKDAY = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)  # Mon 12:00 UTC
WEEKEND_IN_CLOCK = datetime(2026, 8, 29, 2, 0, tzinfo=timezone.utc)  # Sat 02:00 UTC


# ── rate tier + cache hit recorded ───────────────────────────────────────────

def test_f5_calculate_usd_records_band_and_cache_hit():
    priced = calculate_usd(
        provider="deepseek",
        model="deepseek-v4-flash",
        at=OFF_WEEKDAY,
        cache_hit_input=1000,
        cache_miss_input=0,
        output=0,
    )
    assert priced["calculated_cost_usd"] is not None
    assert priced["band"] == "off_peak"
    assert priced["cache_hit"] is True
    assert priced["price_schedule_id"]


def test_f5_peak_weekday_vs_offpeak_is_double():
    kw = dict(
        provider="deepseek",
        model="deepseek-v4-flash",
        cache_hit_input=0,
        cache_miss_input=1_000_000,
        output=0,
    )
    peak = calculate_usd(at=PEAK_WEEKDAY, **kw)
    off = calculate_usd(at=OFF_WEEKDAY, **kw)
    assert peak["band"] == "peak"
    assert off["band"] == "off_peak"
    assert abs(peak["calculated_cost_usd"] - off["calculated_cost_usd"] * 2) < 1e-9


def test_f5_weekend_inside_clock_window_is_off_peak():
    """Sat/Sun never carry the peak surcharge (AGENTS.md §12)."""
    sched = resolve_schedule(
        provider="deepseek", model="deepseek-v4-flash", at=WEEKEND_IN_CLOCK
    )
    assert is_peak(WEEKEND_IN_CLOCK, sched) is False
    priced = calculate_usd(
        provider="deepseek",
        model="deepseek-v4-flash",
        at=WEEKEND_IN_CLOCK,
        cache_miss_input=1_000_000,
        output=0,
    )
    assert priced["band"] == "off_peak"


def test_f5_estimate_usd_cost_matches_schedule_and_exposes_tier_cache():
    est = estimate_usd_cost(
        model_id="deepseek-v4-flash",
        prompt_tokens=None,
        completion_tokens=10,
        cache_hit_tokens=500,
        cache_miss_tokens=500,
        at=OFF_WEEKDAY,
    )
    expected = calculate_usd(
        provider="deepseek",
        model="deepseek-v4-flash",
        at=OFF_WEEKDAY,
        cache_hit_input=500,
        cache_miss_input=500,
        output=10,
    )
    assert est["estimated_cost_usd"] == pytest.approx(expected["calculated_cost_usd"], rel=1e-9)
    assert est["pricing_tier"] == "off_peak"
    assert est["cache_hit"] is True
    assert "price_schedule" in (est.get("cost_basis") or "")


def test_f5_emit_persists_rate_tier_and_cache_hit(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_PROVIDER_COST_DIR", str(tmp_path))
    # Prefer explicit path argument
    dest = tmp_path / "events.jsonl"
    eid = emit_cost_event(
        provider="deepseek",
        model="deepseek-v4-flash",
        outcome="success",
        prompt_tokens=1000,
        completion_tokens=100,
        cache_hit_tokens=400,
        cache_miss_tokens=600,
        usage_start=OFF_WEEKDAY.isoformat(),
        path=dest,
        process_id="test_f5_emit",
    )
    assert eid
    rows = [json.loads(line) for line in dest.read_text().splitlines() if line.strip()]
    assert rows
    row = rows[-1]
    assert row["rate_tier"] == "off_peak"
    assert row["cache_hit"] is True
    assert row["calculated_cost_usd"] is not None
    assert row["cached_input_tokens"] == 400
    # Schema field present on dataclass
    assert "rate_tier" in ProviderCostEvent.__dataclass_fields__
    assert "cache_hit" in ProviderCostEvent.__dataclass_fields__


# ── no hardcoded cost literals in accounting path ────────────────────────────

_ACCOUNTING_FILES = [
    ROOT / "scripts/lib/provider_cost/pricing.py",
    ROOT / "scripts/lib/provider_cost/emit.py",
    ROOT / "scripts/lib/provider_cost/budget.py",
    ROOT / "scripts/lib/deepseek_client.py",
]

# USD-per-million figures that must live in config schedules, not code.
_FORBIDDEN_RATE_LITERALS = {0.007, 0.014, 0.022, 0.044, 0.22, 0.44, 0.66, 1.32, 1.98, 3.96}


def _numeric_constants(path: Path) -> set[float]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[float] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            out.add(float(node.value))
    return out


def test_f5_accounting_modules_have_no_hardcoded_rate_literals():
    for path in _ACCOUNTING_FILES:
        assert path.is_file(), path
        found = _numeric_constants(path) & _FORBIDDEN_RATE_LITERALS
        assert not found, f"{path.name} embeds rate literals {found}; use schedule JSON"


def test_f5_rates_live_only_in_schedule_json():
    data = json.loads((ROOT / "config/provider_pricing_schedules.json").read_text())
    bands = []
    for s in data["schedules"]:
        if s.get("peak_enabled"):
            assert s.get("peak_days") == "Mon-Fri"
            bands.append(s["off_peak"])
            bands.append(s["peak"])
    assert bands, "expected peak/off_peak schedules"
    # Sanity: schedule carries the published flash off-peak miss rate
    flash_off = next(
        s["off_peak"]
        for s in data["schedules"]
        if s["schedule_id"] == "deepseek-v4-flash-peakoff-2026-08-16"
    )
    assert "input_cache_miss" in flash_off


# ── budget check never fails open ────────────────────────────────────────────

def test_f5_budget_denies_when_persistence_unavailable(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TRADE_AI_CI", raising=False)
    monkeypatch.setenv("LLM_GLOBAL_DAILY_USD_CAP", "10")
    monkeypatch.setenv("TRADEAI_ENFORCE_MODEL_BUDGET_IN_CI", "1")

    import lib.provider_cost.budget as budget_mod

    # Force non-test context
    monkeypatch.setattr(budget_mod, "_is_test_context", lambda _pid: False)

    import lib.llm_consumption as lc

    monkeypatch.setattr(lc, "cost_persistence_available", lambda: False)
    with pytest.raises(BudgetDenied) as ei:
        ensure_budget_allows_call(
            process_id="production_job",
            projected_usd=0.01,
            reservation_id=None,
            require_global_cap=True,
        )
    assert ei.value.reason == "BUDGET_UNAVAILABLE"
    assert ei.value.details.get("fail_open") is False


def test_f5_budget_denies_when_global_cap_missing(monkeypatch):
    import lib.provider_cost.budget as budget_mod
    import lib.llm_consumption as lc

    monkeypatch.setattr(budget_mod, "_is_test_context", lambda _pid: False)
    monkeypatch.delenv("LLM_GLOBAL_DAILY_USD_CAP", raising=False)
    monkeypatch.setattr(lc, "cost_persistence_available", lambda: True)
    with pytest.raises(BudgetDenied) as ei:
        ensure_budget_allows_call(process_id="production_job", require_global_cap=True)
    assert ei.value.reason == "COST_CONFIGURATION_INVALID"
    assert ei.value.details.get("fail_open") is False


def test_f5_budget_denies_when_check_cost_cap_errors(monkeypatch):
    import lib.provider_cost.budget as budget_mod
    import lib.llm_consumption as lc

    monkeypatch.setattr(budget_mod, "_is_test_context", lambda _pid: False)
    monkeypatch.setenv("LLM_GLOBAL_DAILY_USD_CAP", "5")
    monkeypatch.setattr(lc, "cost_persistence_available", lambda: True)
    monkeypatch.setattr(
        lc,
        "check_cost_cap",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    with pytest.raises(BudgetDenied) as ei:
        ensure_budget_allows_call(process_id="production_job", require_global_cap=True)
    assert ei.value.reason == "BUDGET_UNAVAILABLE"
    assert ei.value.details.get("fail_open") is False


def test_f5_check_cost_cap_never_fail_open_on_ledger_error(monkeypatch):
    import lib.llm_consumption as lc

    monkeypatch.setattr(
        lc,
        "get_process_config",
        lambda pid: {"daily_cost_cap_usd": 1.0, "process_id": pid},
    )
    monkeypatch.setattr(
        lc,
        "ledger_paid_usd_today",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ledger down")),
    )
    result = lc.check_cost_cap("any_process", projected_usd=0.1, global_cap=10.0)
    assert result["allow"] is False
    assert result["reason"] == "BUDGET_UNAVAILABLE"
    assert result["fail_open"] is False


def test_f5_reservation_short_circuits_budget_precheck():
    out = ensure_budget_allows_call(
        process_id="production_job",
        reservation_id="res_123",
        require_global_cap=True,
    )
    assert out["allow"] is True
    assert out["reason"] == "RESERVATION_HELD"
    assert out["fail_open"] is False


def test_f5_deepseek_chat_denies_before_post_when_budget_blocks(monkeypatch):
    """chat() must not touch the network when budget denies."""
    import lib.deepseek_client as ds
    import lib.provider_cost as pc
    import lib.provider_cost.budget as budget_mod

    def deny(**_kw):
        raise BudgetDenied("COST_CAP_EXCEEDED", details={"fail_open": False})

    # Patch both the module attribute and any scripts.lib twin.
    monkeypatch.setattr(budget_mod, "ensure_budget_allows_call", deny)
    monkeypatch.setattr(pc, "ensure_budget_allows_call", deny)
    try:
        import scripts.lib.provider_cost.budget as sbudget  # type: ignore
        monkeypatch.setattr(sbudget, "ensure_budget_allows_call", deny)
    except ImportError:
        pass

    monkeypatch.setattr(
        ds,
        "get_deepseek_api_key",
        lambda: ("sk-test-not-a-real-key", "deepseek_tradeai", False),
    )
    posted = {"n": 0}

    def boom_post(*_a, **_k):
        posted["n"] += 1
        raise AssertionError("HTTP POST must not run after budget deny")

    monkeypatch.setattr(ds.requests, "post", boom_post)
    monkeypatch.setattr(ds, "_emit_chat_event", lambda **_k: None)

    resp = ds.chat(
        model_id="deepseek-v4-flash",
        prompt="hello",
        source_process="production_job",
    )
    assert resp.ok is False
    assert resp.error_class == ds.COST_CAP_EXCEEDED
    assert resp.request_sent is False
    assert posted["n"] == 0
