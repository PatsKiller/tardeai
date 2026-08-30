"""Test process ids may write rows. They may not spend the operator's budget.

On 2026-08-29 sixteen `test_*` reservations carrying synthetic amounts ($0.60,
$0.04, $0.03) were written to the PRODUCTION cost ledger by test suites. They
were 99% of that day's apparent $2.72 spend — real production was $0.0141 — and
two never settled, so they permanently held budget and blocked a live residual
web hop with COST_CAP_EXCEEDED.

The false cap is the smaller harm. The larger one is that they corrupt the very
number an operator reads to decide what a realistic cap IS.
"""
import inspect
import re

from scripts.lib import llm_consumption as lc


def _spend_sql() -> str:
    return inspect.getsource(lc.ledger_paid_usd_today)


def test_the_spend_query_excludes_test_process_ids():
    sql = _spend_sql()
    assert "NOT LIKE 'test" in sql, "test rows would consume the daily cap"


def test_it_excludes_the_other_test_prefixes_too():
    sql = _spend_sql()
    for prefix in ("test-", "pytest", "fixture"):
        assert prefix in sql, f"{prefix}* rows can still eat the budget"


def test_the_exclusion_is_documented_with_its_cause():
    """A filter without its reason gets 'tidied away' by the next reader."""
    doc = lc.ledger_paid_usd_today.__doc__ or ""
    assert "EXCLUDED" in doc
    assert "2026-08-29" in doc


def test_real_process_ids_are_still_counted():
    """The fix must not become a hole: production spend still gates the cap."""
    sql = _spend_sql()
    # the exclusions are all anchored to test-shaped prefixes, never a bare wildcard
    for m in re.finditer(r"NOT LIKE '([^']+)'", sql):
        pat = m.group(1)
        assert pat.startswith(("test", "pytest", "fixture")), pat


def test_helper_classifies_process_ids():
    assert lc.is_test_process_id("test_gb_1788059011025") is True
    assert lc.is_test_process_id("pytest_thing") is True
    assert lc.is_test_process_id("fixture_x") is True
    assert lc.is_test_process_id("hermes_external_research") is False
    assert lc.is_test_process_id("advisory_desk_opinion") is False
    assert lc.is_test_process_id(None) is False


def test_a_process_merely_containing_test_is_not_excluded():
    """`latest_research` and `contest_desk` are not test harnesses."""
    assert lc.is_test_process_id("latest_research") is False
    assert lc.is_test_process_id("contest_desk") is False


# ── pricing truth, validated against the vendor docs 2026-08-30 ───────────
#
# The registry snapshot (effective 2026-08-03) understated every rate and had
# no peak/off-peak concept at all. DeepSeek DOUBLES during peak windows, so
# billing everything off-peak understated real cost on top of the snapshot
# itself being low. Restated over 7 days / 6,580 real calls: $0.8129 -> $1.8695.
# Source: https://api-docs.deepseek.com/quick_start/pricing/

from datetime import datetime, timezone   # noqa: E402

import pytest   # noqa: E402

from scripts.lib.llm_model_registry import (   # noqa: E402
    _in_peak_window, estimate_usd_cost, load_registry,
)

PEAK = datetime(2026, 9, 1, 2, 30, tzinfo=timezone.utc)      # Tue, in 01-04
OFF = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)       # Tue, midday
WEEKEND = datetime(2026, 8, 30, 2, 30, tzinfo=timezone.utc)  # Sun, in 01-04


@pytest.mark.parametrize("model,tier,expect", [
    ("deepseek-v4-flash", "off", {"cache_hit_input": 0.007, "cache_miss_input": 0.22, "output": 0.66}),
    ("deepseek-v4-pro", "off", {"cache_hit_input": 0.022, "cache_miss_input": 0.66, "output": 1.98}),
])
def test_the_registry_carries_the_documented_off_peak_prices(model, tier, expect):
    reg = load_registry()
    for prov in (reg.get("providers") or {}).values():
        for m in (prov.get("models") or {}).values():
            if m.get("model_id") == model:
                assert m["pricing_snapshot_usd_per_million_tokens"] == expect
                return
    pytest.fail(f"{model} not in registry")


def test_peak_is_exactly_double_off_peak():
    reg = load_registry()
    for prov in (reg.get("providers") or {}).values():
        for m in (prov.get("models") or {}).values():
            off = m.get("pricing_snapshot_usd_per_million_tokens") or {}
            peak = m.get("pricing_peak_usd_per_million_tokens") or {}
            if not peak:
                continue
            for k in off:
                assert abs(peak[k] - off[k] * 2) < 1e-9, (m.get("model_id"), k)


def test_peak_windows_match_the_vendor_doc():
    reg = load_registry()
    ds = (reg.get("providers") or {}).get("deepseek") or {}
    assert ds["pricing_peak_hours_utc"] == ["01:00-04:00", "06:00-10:00"]
    assert ds["pricing_peak_days"] == "Mon-Fri"


@pytest.mark.parametrize("at,expect", [
    (PEAK, True), (OFF, False), (WEEKEND, False),
    (datetime(2026, 9, 1, 7, 0, tzinfo=timezone.utc), True),    # in 06-10
    (datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc), False),  # boundary is exclusive
    (datetime(2026, 9, 1, 4, 0, tzinfo=timezone.utc), False),   # boundary is exclusive
])
def test_peak_window_detection(at, expect):
    reg = load_registry()
    ds = (reg.get("providers") or {}).get("deepseek") or {}
    assert _in_peak_window(ds, at=at) is expect


def test_a_peak_call_bills_double():
    kw = dict(model_id="deepseek-v4-flash", prompt_tokens=1000, completion_tokens=1000)
    p = estimate_usd_cost(**kw, at=PEAK)
    o = estimate_usd_cost(**kw, at=OFF)
    assert p["pricing_tier"] == "peak" and o["pricing_tier"] == "off_peak"
    assert abs(p["estimated_cost_usd"] - o["estimated_cost_usd"] * 2) < 1e-9


def test_the_superseded_prices_are_kept_not_deleted():
    """The old numbers explain every historical row; deleting them orphans the
    ledger."""
    reg = load_registry()
    for prov in (reg.get("providers") or {}).values():
        for m in (prov.get("models") or {}).values():
            if m.get("model_id") == "deepseek-v4-flash":
                sup = m.get("pricing_superseded") or {}
                assert sup["effective_at"] == "2026-08-03"
                assert sup["values"]["output"] == 0.28
                return
    pytest.fail("flash not found")
