"""LQ-20261107-196 / DSN-20261107-ANTHROPIC-FIRST-ROUTING §3A: Anthropic-first policy, step 1.

Tier mapping (FAST and the light tiers no longer resolve to Opus), per-tier daily sub-caps enforced at CreditBook
admission (ANTHROPIC_CREDIT_TIER_CAP), the ``monthly_credit_usd`` / ``period_start`` renewal shape (daily cap =
monthly / 30), and a torn journal tail that still fails closed. No network, no real journal: every CreditBook lives
under tmp_path and every amount is synthetic.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import anthropic_credit as ac  # noqa: E402
from scripts.lib import jsonl_tail  # noqa: E402
from scripts.lib.anthropic_credit import CreditBook, CreditDenied  # noqa: E402
from scripts.lib.anthropic_routing import tier_for  # noqa: E402

LIVE = json.loads((ROOT / "config/anthropic_credit_policy.json").read_text(encoding="utf-8"))
NOV12 = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)
SHARES = {"bulk": "0.40", "mid": "0.45", "standard": "0.15"}


def policy(**over):
    """A synthetic, enabled one-time policy with a $10 base day and room in every per-call cap."""
    base = dict(deepcopy(LIVE), enabled=True, promotion_id="synthetic-lq196", credit_usd="200",
                total_cap_usd="190", daily_cap_usd="10", daily_cap_overrides=[],
                starts_at="2026-11-01T00:00:00Z", expires_at="2027-06-01T00:00:00Z",
                per_call_caps_usd={t: "5.00" for t in ("bulk", "mid", "standard", "high", "highest",
                                                       "long_form", "premium")},
                emergency_process_caps=None, renewal={"mode": "one_time", "monthly_allowance_usd": "190", "renews_on_day": None})
    base.update(over)
    return base


# ── tier mapping ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("logical,tier,model", [
    ("FAST", "bulk", "claude-haiku-5-5"),
    ("FAST_THINK", "mid", "claude-sonnet-5-5"),
    ("PRO", "mid", "claude-sonnet-5-5"),
    ("PRO_THINK", "standard", "claude-opus-5-5"),
])
def test_logical_policies_resolve_to_the_cheapest_adequate_model(logical, tier, model):
    assert LIVE["policy_tiers"][logical] == tier
    assert tier_for(logical, policy=LIVE, process_id="lq196_unpinned_synthetic") == tier
    assert LIVE["models"][tier] == model


def test_a_declared_process_pin_still_wins_over_the_logical_tier():
    pinned = dict(LIVE, process_tiers={"lq196_pinned": "long_form"})
    assert tier_for("FAST", policy=pinned, process_id="lq196_pinned") == "long_form"


def test_live_policy_carries_the_sub_caps_and_the_operators_monthly_200():
    # Operator decision 2026-11-07 13:55 ET: $200/month of API credits; the billing day is still pending.
    assert LIVE["tier_daily_cap_shares"] == SHARES
    renewal = LIVE["renewal"]
    assert renewal["mode"] == "monthly" and renewal["monthly_credit_usd"] == "200"
    assert renewal["period_start"] is None and "OPERATOR VALUE" in renewal["note"]
    assert "monthly_allowance_usd" not in renewal  # naming both amounts would refuse the policy
    assert LIVE["expires_at"].startswith("2026-11-16")


def test_live_monthly_200_paces_six_sixty_six_a_day_split_by_tier(tmp_path):
    snap = CreditBook(tmp_path, LIVE).snapshot(now=datetime(2026, 11, 8, 12, tzinfo=timezone.utc))
    assert snap["renewal_mode"] == "monthly" and snap["total_cap_usd"] == "200.00"
    assert snap["daily_cap_base_usd"] == "6.66"
    assert snap["tier_daily_caps_usd"] == {"bulk": "2.66", "mid": "2.99", "standard": "0.99"}


# ── per-tier daily sub-caps ───────────────────────────────────────────────────────────────────


def test_tier_cap_refuses_opus_beyond_fifteen_percent_of_the_day(tmp_path):
    book = CreditBook(tmp_path, policy(tier_daily_cap_shares=SHARES))
    book.reserve("o1", "lq196_proc", Decimal("1.00"), tier="standard", now=NOV12)
    book.settle("o1", Decimal("1.00"), now=NOV12)
    with pytest.raises(CreditDenied) as exc:
        book.reserve("o2", "lq196_proc", Decimal("0.60"), tier="standard", now=NOV12)
    assert exc.value.reason == "ANTHROPIC_CREDIT_TIER_CAP"
    # high / highest / long_form / premium are Opus or Fable: they share the 15% bucket
    with pytest.raises(CreditDenied) as exc:
        book.reserve("o3", "lq196_proc", Decimal("0.60"), tier="premium", now=NOV12)
    assert exc.value.reason == "ANTHROPIC_CREDIT_TIER_CAP"
    # an unsettled hold counts too
    book.reserve("o4", "lq196_proc", Decimal("0.50"), tier="high", now=NOV12)
    with pytest.raises(CreditDenied):
        book.reserve("o5", "lq196_proc", Decimal("0.01"), tier="standard", now=NOV12)
    # the cheap buckets are independent of the Opus bucket
    book.reserve("h1", "lq196_proc", Decimal("4.00"), tier="bulk", now=NOV12)
    book.reserve("s1", "lq196_proc", Decimal("4.00"), tier="mid", now=NOV12)  # day total $9.50 < $10
    with pytest.raises(CreditDenied) as exc:
        book.reserve("h2", "lq196_proc", Decimal("0.01"), tier="bulk", now=NOV12)
    assert exc.value.reason == "ANTHROPIC_CREDIT_TIER_CAP"
    snap = book.snapshot(now=NOV12)
    assert snap["tier_daily_caps_usd"] == {"bulk": "4.00", "mid": "4.50", "standard": "1.50"}
    assert snap["tier_today_used_usd"] == {"bulk": "4.00", "mid": "4.00", "standard": "1.50"}
    # a new UTC day reopens every bucket
    book.reserve("o6", "lq196_proc", Decimal("1.00"), tier="standard",
                 now=datetime(2026, 11, 13, 0, 5, tzinfo=timezone.utc))


def test_tier_cap_scales_with_an_active_daily_override(tmp_path):
    p = policy(tier_daily_cap_shares=SHARES,
               daily_cap_overrides=[{"usd": "40", "from": "2026-11-12", "until": "2026-11-13"}])
    book = CreditBook(tmp_path, p)
    book.reserve("o1", "lq196_proc", Decimal("5.00"), tier="standard", now=NOV12)  # 15% of $40 = $6
    with pytest.raises(CreditDenied) as exc:
        book.reserve("o2", "lq196_proc", Decimal("1.01"), tier="standard", now=NOV12)
    assert exc.value.reason == "ANTHROPIC_CREDIT_TIER_CAP"


def test_tier_cap_refusal_is_a_recorded_fallback_code(tmp_path):
    book = CreditBook(tmp_path, policy(tier_daily_cap_shares=SHARES))
    book.record_fallback("ANTHROPIC_CREDIT_TIER_CAP", now=NOV12, process_id="lq196_proc")
    assert book._read()[-1]["reason"] == "ANTHROPIC_CREDIT_TIER_CAP"


def test_without_shares_there_is_no_tier_cap(tmp_path):
    book = CreditBook(tmp_path, policy(tier_daily_cap_shares=None))
    book.reserve("o1", "lq196_proc", Decimal("5.00"), tier="standard", now=NOV12)
    assert book.snapshot(now=NOV12)["tier_daily_caps_usd"] is None


@pytest.mark.parametrize("bad", [
    {"bulk": "0.50", "mid": "0.45", "standard": "0.15"},   # sums above 1
    {"bulk": "0.40", "mid": "0.45", "opus": "0.15"},       # unknown bucket
    {"bulk": "0", "mid": "0.45", "standard": "0.15"},
    {"bulk": "-0.1", "mid": "0.45", "standard": "0.15"},
    {"bulk": "x", "mid": "0.45", "standard": "0.15"},
    ["bulk", "mid"],
])
def test_invalid_shares_refuse_the_configuration(tmp_path, bad):
    with pytest.raises(CreditDenied) as exc:
        CreditBook(tmp_path, policy(tier_daily_cap_shares=bad))
    assert exc.value.reason == "CREDIT_CONFIGURATION_INVALID"


def test_a_tier_outside_every_bucket_is_refused_not_uncapped(tmp_path):
    p = policy(tier_daily_cap_shares={"bulk": "0.40", "mid": "0.45"})  # no Opus bucket at all
    book = CreditBook(tmp_path, p)
    with pytest.raises(CreditDenied) as exc:
        book.reserve("o1", "lq196_proc", Decimal("0.10"), tier="standard", now=NOV12)
    assert exc.value.reason == "ANTHROPIC_CREDIT_TIER_CAP"


# ── monthly renewal: monthly_credit_usd + period_start ───────────────────────────────────────


def _monthly(**renewal):
    return policy(renewal=dict({"mode": "monthly"}, **renewal), tier_daily_cap_shares=None)


def test_monthly_credit_sets_total_and_a_daily_cap_of_one_thirtieth(tmp_path):
    book = CreditBook(tmp_path, _monthly(monthly_credit_usd="190", period_start="2026-11-10"))
    snap = book.snapshot(now=NOV12)
    assert snap["total_cap_usd"] == "190.00"
    assert snap["daily_cap_base_usd"] == "6.33"  # 190 / 30, rounded down to the cent
    assert snap["period_start"].startswith("2026-11-10")


def test_monthly_rollover_starts_a_fresh_period_on_the_anniversary(tmp_path):
    book = CreditBook(tmp_path, _monthly(monthly_credit_usd="3", period_start="2026-11-10"))
    assert book.snapshot(now=datetime(2026, 11, 9, 23, tzinfo=timezone.utc))["status"] == "NOT_STARTED"
    for i, day in enumerate((10, 11, 12)):
        at = datetime(2026, 11, day, 12, tzinfo=timezone.utc)
        book.reserve(f"m{i}", "lq196_proc", Decimal("0.10"), tier="bulk", now=at)
        book.settle(f"m{i}", Decimal("0.10"), now=at)
    dec9 = datetime(2026, 12, 9, 23, 59, tzinfo=timezone.utc)
    assert book.snapshot(now=dec9)["credit_used_usd"] == "0.30"
    dec10 = datetime(2026, 12, 10, 0, 1, tzinfo=timezone.utc)
    snap = book.snapshot(now=dec10)
    assert snap["credit_used_usd"] == "0.00" and snap["period_start"].startswith("2026-12-10")
    assert len(book._read()) == 6  # the earlier period stays in the journal
    book.reserve("m9", "lq196_proc", Decimal("0.10"), tier="bulk", now=dec10)


def test_monthly_daily_cap_pauses_the_day_not_the_month(tmp_path):
    book = CreditBook(tmp_path, _monthly(monthly_credit_usd="3", period_start="2026-11-10"))  # $0.10/day
    book.reserve("d1", "lq196_proc", Decimal("0.10"), tier="bulk", now=NOV12)
    with pytest.raises(CreditDenied) as exc:
        book.reserve("d2", "lq196_proc", Decimal("0.01"), tier="bulk", now=NOV12)
    assert exc.value.reason == "PAUSED_TODAY"


def test_legacy_monthly_allowance_shape_still_reads(tmp_path):
    p = policy(renewal={"mode": "monthly", "monthly_allowance_usd": "50", "renews_on_day": 15},
               tier_daily_cap_shares=None)
    snap = CreditBook(tmp_path, p).snapshot(now=NOV12)
    assert snap["total_cap_usd"] == "50.00" and snap["daily_cap_base_usd"] == "10.00"
    assert snap["period_start"].startswith("2026-10-15")


@pytest.mark.parametrize("renewal", [
    {"mode": "monthly", "monthly_credit_usd": "0", "period_start": "2026-11-10"},
    {"mode": "monthly", "monthly_credit_usd": "190", "period_start": "2026-11-31"},
    {"mode": "monthly", "monthly_credit_usd": "190", "period_start": "2026-11-29"},   # no 29th in February
    {"mode": "monthly", "monthly_credit_usd": "190", "period_start": "not-a-date"},
    {"mode": "monthly", "monthly_credit_usd": "190", "monthly_allowance_usd": "190"},  # two amounts
    {"mode": "monthly", "monthly_credit_usd": "190", "period_start": "2026-11-10", "renews_on_day": 3},
])
def test_invalid_monthly_shapes_refuse_the_configuration(tmp_path, renewal):
    with pytest.raises(CreditDenied) as exc:
        CreditBook(tmp_path, policy(renewal=renewal))
    assert exc.value.reason == "CREDIT_CONFIGURATION_INVALID"


def test_one_time_mode_is_unchanged(tmp_path):
    snap = CreditBook(tmp_path, policy()).snapshot(now=NOV12)
    assert snap["renewal_mode"] == "one_time" and snap["period_start"] is None
    assert snap["total_cap_usd"] == "190.00" and snap["daily_cap_base_usd"] == "10.00"


# ── a torn journal tail still fails closed ───────────────────────────────────────────────────


def test_corrupt_tail_is_credit_unavailable_until_the_fragment_is_archived(tmp_path, monkeypatch):
    reports = []
    monkeypatch.setattr(jsonl_tail, "report", lambda path, n, **kw: reports.append((Path(path).name, n)))
    book = CreditBook(tmp_path, policy(tier_daily_cap_shares=SHARES))
    book.reserve("t1", "lq196_proc", Decimal("0.10"), tier="bulk", now=NOV12)
    journal = tmp_path / ac.JOURNAL_REL
    with journal.open("ab") as fh:
        fh.write(b'{"schema":"AnthropicCreditAuthorization@v1","sequ')  # disk full mid-write
    for call in (lambda: book.snapshot(now=NOV12),
                 lambda: book.reserve("t2", "lq196_proc", Decimal("0.10"), tier="bulk", now=NOV12)):
        with pytest.raises(CreditDenied) as exc:
            call()
        assert exc.value.reason == "CREDIT_UNAVAILABLE"
    assert reports and reports[0][0] == "anthropic_credit.jsonl"
    # the lead's step 2: archive the fragment beside the store; the book reopens with the earlier spend intact
    raw = journal.read_bytes()
    offset, fragment = jsonl_tail.truncated_tail(raw)
    archive = jsonl_tail.quarantine_tail(journal, offset, fragment)
    assert archive.read_bytes() == fragment
    snap = book.snapshot(now=NOV12)
    assert snap["status"] == "OK" and snap["reserved_usd"] == "0.10"


def test_monitoring_credit_config_shows_the_sub_caps_and_monthly_keys(tmp_path, monkeypatch):
    from scripts.lib import anthropic_monitoring as mon
    monkeypatch.delenv("ANTHROPIC_ADMIN_API_KEY", raising=False)
    p = policy(tier_daily_cap_shares=SHARES)
    cfg = mon.snapshot(tmp_path, policy=p, now=NOV12, configured=True)["credit_config"]
    assert cfg["tier_daily_cap_shares"] == SHARES
    assert cfg["tier_daily_caps_usd"] == {"bulk": "4.00", "mid": "4.50", "standard": "1.50"}
    assert cfg["tier_today_used_usd"] == {"bulk": "0.00", "mid": "0.00", "standard": "0.00"}
    monthly = _monthly(monthly_credit_usd="90", period_start="2026-11-10")
    cfg = mon.snapshot(tmp_path / "m", policy=monthly, now=NOV12, configured=True)["credit_config"]
    assert cfg["renewal"]["monthly_credit_usd"] == "90" and cfg["renewal"]["period_start"] == "2026-11-10"
    assert cfg["daily_cap_usd"] == "3.00"
