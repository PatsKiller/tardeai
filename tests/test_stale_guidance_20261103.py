"""Stale-guidance hygiene (Board row 33 piece E, operator P0 2026-11-03).

The operator was stopped out of SPCX at 137.19 on 2026-10-30 and sat at 141.65 on 2026-11-03 while Home
still said "SPCX is below its stop" and the CIO home still carried an "Advisory TRIM — SPCX" label whose
narrative dated from 2026-10-07.

Review round 2 (cc-deepseek-5): the clock must be the OBSERVATION, not the directive's creation, and the
gate must cover the staging rows the operator actually reads. Both are asserted at the real call paths here.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from scripts.lib import stale_guidance as SG  # noqa: E402
from lib import cio_opportunity_queue as Q  # noqa: E402
from scripts.lib import cio_command_center as CC  # noqa: E402
import test_home_do_now_20261022 as HARNESS  # noqa: E402

COVERS = ["scripts/lib/stale_guidance.py", "scripts/lib/cio_opportunity_queue.py",
          "scripts/lib/data_broker/home_do_now.py", "scripts/lib/cio_command_center.py"]

NOW = datetime(2026, 11, 3, 16, 30, tzinfo=timezone.utc)


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


# ── the rule: the observation is the clock ──────────────────────────────────────────────────────────────────

def test_an_old_observation_is_stale():
    out = SG.advisory_freshness({"surfaced_at": _iso(27)}, NOW)   # SPCX: observed 2026-10-07
    assert out["stale"] is True and out["reason"] == "observation_older_than_14d"
    assert out["age_known"] is True and out["age_days"] == pytest.approx(27.0)


def test_a_fresh_observation_is_not_stale_even_if_the_directive_is_old():
    """E2: the directive's creation is not the observation. A hit surfaced today is fresh."""
    out = SG.advisory_freshness({"surfaced_at": _iso(0.1), "narrative_at": _iso(27)}, NOW)
    assert out["stale"] is False and out["age_known"] is True


def test_a_staged_row_proposed_sixty_days_ago_is_stale():
    """E1: undrained staging rows are the surface the operator reads; their proposed_at is the clock."""
    out = SG.advisory_freshness({"proposed_at": _iso(60)}, NOW)
    assert out["stale"] is True and out["reason"] == "observation_older_than_14d"


def test_an_undated_observation_is_unknown_not_stale():
    """N2: the docstring and the code now agree — unreadable is unknown, never suppressed."""
    out = SG.advisory_freshness({}, NOW)
    assert out["stale"] is False and out["age_known"] is False and out["age_days"] is None


def test_exactly_at_the_limit_is_not_stale():
    assert SG.advisory_freshness({"surfaced_at": _iso(14)}, NOW)["stale"] is False


# ── the real queue path: hits AND staging, observation clock ────────────────────────────────────────────────

def _row(symbol, observed_days, *, source="advisory", key="surfaced_at", label=None):
    return {"symbol": symbol, "source": source, "directive_label": label or f"Advisory TRIM — {symbol}",
            key: _iso(observed_days)}


def test_the_current_queue_cannot_render_a_stale_observation():
    q = Q.build_opportunity_queue([_row("SPCX", 27), _row("NVDA", 1)], now=NOW)
    assert "NVDA" in [i["symbol"] for i in q["items"]]
    assert "SPCX" not in [i["symbol"] for i in q["items"]], "a 27-day-old observation rendered as current"
    assert q["count"] == 1 and q["stale_count"] == 1
    stale = {i["symbol"]: i for i in q["stale_items"]}
    assert stale["SPCX"]["stale_reason"] == "observation_older_than_14d"
    assert q["digest"] == Q.build_opportunity_queue([_row("NVDA", 1)], now=NOW)["digest"]


def test_a_staging_row_is_covered_by_the_same_gate():
    """E1: the operator's queue is built from staging rows too — a 60-day undrained row must not render."""
    q = Q.build_opportunity_queue([_row("SCHG", 60, source="reentry", key="proposed_at"), _row("BAH", 1, source="reentry", key="proposed_at")], now=NOW)
    syms = [i["symbol"] for i in q["items"]]
    assert "BAH" in syms and "SCHG" not in syms and q["stale_count"] == 1


def test_a_fresh_hit_against_an_old_directive_still_renders():
    """E2 regression: the directive's age must not suppress a today observation."""
    row = {"symbol": "RTX", "source": "advisory", "directive_label": "Advisory TRIM — RTX",
           "surfaced_at": _iso(0.05), "narrative_at": _iso(27)}
    q = Q.build_opportunity_queue([row], now=NOW)
    assert [i["symbol"] for i in q["items"]] == ["RTX"] and q["stale_count"] == 0


# ── the suppression is visible on the surface, not silent ──────────────────────────────────────────────────

def test_the_cio_home_counts_the_guidance_it_held_back():
    q = Q.build_opportunity_queue([_row("SPCX", 27), _row("NVDA", 1)], now=NOW)
    home = CC.build_office_home(opportunity_queue=q, now=NOW)
    assert home["stale_guidance"]["count"] == 1
    assert home["stale_guidance"]["items"][0]["symbol"] == "SPCX"
    assert home["stale_guidance"]["items"][0]["reason"] == "observation_older_than_14d"


# ── the Home call path: the stop prompt ─────────────────────────────────────────────────────────────────────

def test_a_recovered_price_does_not_render_below_its_stop():
    """The operator's exact case: triggered at the 137.19 stop, price now 141.65 (+3.3% above it)."""
    out = HARNESS.build(**HARNESS.base(risk=HARNESS._risk(
        HARNESS._pos("SPCX", 200 * 141.65, account="schwab_taxable", stop=137.19, dist=3.3, triggered=True))))
    assert "stop:SPCX" not in HARNESS.ids(out), "a recovered price still rendered 'below its stop'"


def test_a_live_breach_still_renders():
    out = HARNESS.build(**HARNESS.base(risk=HARNESS._risk(
        HARNESS._pos("NEM", 30_000, stop=100, dist=-1.0, triggered=True))))
    item = next(i for i in out["items"] if i["id"] == "stop:NEM")
    assert item["severity"] == "P0" and "below its stop" in item["title"]


def test_an_unmeasured_breach_still_renders():
    out = HARNESS.build(**HARNESS.base(risk=HARNESS._risk(
        HARNESS._pos("RTX", 20_000, stop=150, dist=None, triggered=True))))
    assert "stop:RTX" in HARNESS.ids(out)


def test_the_rule_is_pure_and_does_not_depend_on_wall_clock():
    assert SG.stop_prompt_is_stale({"triggered": True, "distance_to_stop_pct": 3.3}) is True
    assert SG.stop_prompt_is_stale({"triggered": True, "distance_to_stop_pct": -0.5}) is False
    assert SG.stop_prompt_is_stale({"triggered": True, "distance_to_stop_pct": 0}) is False
    assert SG.stop_prompt_is_stale({"triggered": False, "distance_to_stop_pct": 3.3}) is False
