"""Stale-guidance hygiene (Board row 33 piece E, operator P0 2026-11-03).

The operator was stopped out of SPCX at 137.19 on 2026-10-30 and sat at 141.65 on 2026-11-03 while Home
still said "SPCX is below its stop" and the CIO home still carried an "Advisory TRIM — SPCX" label whose
narrative dated from 2026-10-07. Guidance that was true when written and false when read is worse than no
guidance: it asks the operator to act on a market that has moved.

These tests fail if stale guidance can render as CURRENT. Each one names the assertion that would still
pass if the gate were removed, so a green run proves the gate is load-bearing rather than decorative.
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
import test_home_do_now_20261022 as HARNESS  # noqa: E402

COVERS = ["scripts/lib/stale_guidance.py", "scripts/lib/cio_opportunity_queue.py"]

NOW = datetime(2026, 11, 3, 16, 30, tzinfo=timezone.utc)


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


# ── the rule ────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_narrative_older_than_the_limit_is_stale():
    out = SG.advisory_freshness({"narrative_at": _iso(27)}, NOW)   # SPCX: 2026-10-07 narrative
    assert out["stale"] is True and out["reason"] == "narrative_older_than_14d" and out["age_known"] is True
    assert out["age_days"] == pytest.approx(27.0)


def test_a_fresh_narrative_is_not_stale():
    assert SG.advisory_freshness({"narrative_at": _iso(3)}, NOW)["stale"] is False
    # Exactly at the limit is not "older than" it.
    assert SG.advisory_freshness({"narrative_at": _iso(14)}, NOW)["stale"] is False


def test_old_evidence_is_stale_even_with_a_fresh_narrative():
    out = SG.advisory_freshness({"narrative_at": _iso(2), "evidence_at": _iso(40)}, NOW)
    assert out["stale"] is True and out["reason"] == "evidence_older_than_30d"


def test_an_undated_advisory_is_unknown_not_silently_dropped():
    out = SG.advisory_freshness({}, NOW)
    assert out["stale"] is False and out["age_known"] is False and out["age_days"] is None


# ── the real queue path: a stale advisory cannot render as current ───────────────────────────────────────────

def _row(symbol, narrative_days, *, source="advisory", label=None):
    return {"symbol": symbol, "source": source, "directive_label": label or f"Advisory TRIM — {symbol}",
            "surfaced_at": _iso(0.1), "narrative_at": _iso(narrative_days)}


def test_the_current_queue_cannot_render_a_stale_advisory():
    """If the gate is removed, SPCX reappears in items and this test fails."""
    q = Q.build_opportunity_queue([_row("SPCX", 27), _row("NVDA", 2)], now=NOW)
    assert "NVDA" in [i["symbol"] for i in q["items"]]
    assert "SPCX" not in [i["symbol"] for i in q["items"]], "a 27-day-old advisory rendered as current"
    assert "SPCX" not in [i["symbol"] for i in q["top"]]
    assert q["count"] == 1
    stale = {i["symbol"]: i for i in q["stale_items"]}
    assert stale["SPCX"]["stale_reason"] == "narrative_older_than_14d"
    # The digest is the wake signal: a stale advisory must not be able to make the queue look new.
    fresh_only = Q.build_opportunity_queue([_row("NVDA", 2)], now=NOW)
    assert q["digest"] == fresh_only["digest"]


def test_a_queue_with_only_stale_rows_is_empty_not_silently_full():
    q = Q.build_opportunity_queue([_row("SPCX", 27)], now=NOW)
    assert q["count"] == 0 and q["items"] == [] and q["material"] is False
    assert len(q["stale_items"]) == 1


# ── the Home call path: the stop prompt ─────────────────────────────────────────────────────────────────────

def test_a_recovered_price_does_not_render_below_its_stop():
    """The operator's exact case: triggered at the 137.19 stop, price now 141.65 (+3.3% above it)."""
    out = HARNESS.build(**HARNESS.base(risk=HARNESS._risk(
        HARNESS._pos("SPCX", 200 * 141.65, account="schwab_taxable", stop=137.19, dist=3.3, triggered=True))))
    assert "stop:SPCX" not in HARNESS.ids(out), "a recovered price still rendered 'below its stop'"


def test_a_live_breach_still_renders():
    """Guard against over-suppression: a genuinely breached stop (distance < 0) must still page."""
    out = HARNESS.build(**HARNESS.base(risk=HARNESS._risk(
        HARNESS._pos("NEM", 30_000, stop=100, dist=-1.0, triggered=True))))
    item = next(i for i in out["items"] if i["id"] == "stop:NEM")
    assert item["severity"] == "P0" and "below its stop" in item["title"]


def test_an_unmeasured_breach_still_renders():
    """Unknown distance is not evidence of recovery: a stop believed breached must still page."""
    out = HARNESS.build(**HARNESS.base(risk=HARNESS._risk(
        HARNESS._pos("RTX", 20_000, stop=150, dist=None, triggered=True))))
    assert "stop:RTX" in HARNESS.ids(out)


def test_the_rule_is_pure_and_does_not_depend_on_wall_clock():
    assert SG.stop_prompt_is_stale({"triggered": True, "distance_to_stop_pct": 3.3}) is True
    assert SG.stop_prompt_is_stale({"triggered": True, "distance_to_stop_pct": -0.5}) is False
    assert SG.stop_prompt_is_stale({"triggered": True, "distance_to_stop_pct": 0}) is False
    assert SG.stop_prompt_is_stale({"triggered": False, "distance_to_stop_pct": 3.3}) is False
