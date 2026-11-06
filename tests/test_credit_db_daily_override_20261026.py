"""The DB credit backstop honours the same daily-cap overrides as the credit journal."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from scripts.lib.llm_consumption import credit_daily_cap_usd

POLICY = {
    "daily_cap_usd": "10",
    "daily_cap_overrides": [{"usd": "25", "from": "2026-10-26", "until": "2026-10-29"}],
}


def at(day: str, hour: int = 12) -> datetime:
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00").replace(tzinfo=timezone.utc)


@pytest.mark.parametrize("day,cap", [
    ("2026-10-25", "10"), ("2026-10-26", "25"), ("2026-10-28", "25"), ("2026-10-29", "10"),
])
def test_override_window_is_utc_days_with_exclusive_until(day, cap):
    assert credit_daily_cap_usd(POLICY, at(day)) == Decimal(cap)


def test_no_overrides_uses_base_cap():
    assert credit_daily_cap_usd({"daily_cap_usd": "10"}, at("2026-10-26")) == Decimal("10")


def test_utc_day_not_local_day():
    # 2026-10-28 23:30 ET is 2026-10-29 03:30 UTC: the override has ended.
    assert credit_daily_cap_usd(POLICY, at("2026-10-29", 3)) == Decimal("10")


@pytest.mark.parametrize("bad", [
    {"daily_cap_usd": "10", "daily_cap_overrides": [{"usd": "25", "from": "nope", "until": "2026-10-29"}]},
    {"daily_cap_usd": "10", "daily_cap_overrides": [{"usd": "x", "from": "2026-10-26", "until": "2026-10-29"}]},
    {},
])
def test_bad_configuration_is_typed(bad):
    with pytest.raises(RuntimeError, match="CREDIT_CONFIGURATION_INVALID"):
        credit_daily_cap_usd(bad, at("2026-10-26"))
