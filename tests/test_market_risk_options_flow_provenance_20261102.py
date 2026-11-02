"""D1 provenance regression — options-flow category (audit 2026-11-02, Home risk indicator).

The defect: the category took each symbol's latest row with no per-symbol currency check and dated itself to the
NEWEST row across symbols. With Monday's QQQ collection failed, Friday's QQQ put/call reading still drove the score
but carried Monday's SPY timestamp, decay 1.0.

These synthetic fixtures reproduce that shape with public index put/call numbers only (no portfolio data). They assert
both halves of the repair: the contributor exposes the evidence time of the reading it shows, and freshness/decay
derive from the inputs that determine the state. No threshold or ``missed_slots_allowed`` is changed here.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from scripts.lib.market_risk import explain, scoring
from scripts.lib.market_risk.categories import options_flow
from scripts.lib.market_risk.contract import EvalContext
from scripts.lib.market_risk.policy import load_policy

# Monday 2026-11-02 12:15 ET, the audit's evaluation instant (EST, UTC-5).
NOW = datetime(2026, 11, 2, 17, 15, tzinfo=timezone.utc)
# Friday's 17:35:01 ET reading — the QQQ row that survived Monday's failed collection.
QQQ_FRIDAY = datetime(2026, 10, 30, 21, 35, 1, tzinfo=timezone.utc)
QQQ_FRIDAY_ISO = "2026-10-30T21:35:01+00:00"
# Monday's 10:00:02 ET collection: SPY succeeded, QQQ did not.
FRESH_MONDAY = datetime(2026, 11, 2, 15, 0, 2, tzinfo=timezone.utc)
FRESH_MONDAY_ISO = "2026-11-02T15:00:02+00:00"
# A QQQ row from Friday 10:00 ET: past its own second-slot deadline by Monday 12:15 ET.
QQQ_EXPIRED = datetime(2026, 10, 30, 14, 0, tzinfo=timezone.utc)


def _row(sym: str, at: datetime, oi: float, vol: float, px: float) -> dict:
    return {
        "symbol": sym,
        "as_of": at.isoformat(),
        "pc_oi_ratio": oi,
        "pc_vol_ratio": vol,
        "underlying_price": px,
    }


def _bdays(n: int, end: date = date(2026, 10, 29)) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def _history() -> list[dict]:
    """Trailing sessions so the detector has its median; public index put/call levels only."""
    rows: list[dict] = []
    for d in _bdays(12, date(2026, 10, 29)):
        at = datetime(d.year, d.month, d.day, 14, 0, tzinfo=timezone.utc)
        rows.append(_row("QQQ", at, 1.38, 0.96, 700.0))
        rows.append(_row("SPY", at, 1.0, 1.0, 650.0))
    return rows


class Reader:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def option_snapshots(self, symbols, *, sessions, end):
        return [r for r in self.rows if r["symbol"] in symbols]


@pytest.fixture(scope="module")
def policy():
    return load_policy()


def _eval(policy, rows, now=NOW):
    return options_flow.evaluate(EvalContext(now=now, reader=Reader(rows), policy=policy, session="regular"))


def _contributor(policy, obs):
    """The Home presentation path: compose -> explain.attribute -> Contributor.as_of."""
    assessment = scoring.compose([obs], policy, now=NOW)
    explain.explain(assessment, policy)
    return next(c for c in assessment.contributors if c.category == "options_flow")


def _unknown_evidence(obs, symbol):
    return next(e for e in obs.evidence if e.label.startswith(f"{symbol} put/call") and e.value == "UNKNOWN")


# ── fresh SPY / old QQQ: the exact D1 shape ─────────────────────────────────────────────────────────────────────
def test_fresh_spy_old_qqq_contributor_carries_qqq_evidence_time(policy):
    rows = _history()
    rows.append(_row("QQQ", QQQ_FRIDAY, 3.974, 0.896, 700.0))  # STRESS (3.85x median OI), Friday 17:35 ET
    rows.append(_row("SPY", FRESH_MONDAY, 1.215, 0.612, 650.0))  # CALM, Monday 10:00 ET
    obs = _eval(policy, rows)

    assert obs.state == "STRESS"
    # The reading shown is QQQ's Friday one, so that is the timestamp the contributor must expose.
    assert obs.observed_at == QQQ_FRIDAY_ISO
    assert obs.observed_at != FRESH_MONDAY_ISO
    contributor = _contributor(policy, obs)
    assert contributor.as_of == QQQ_FRIDAY_ISO
    assert "QQQ" in contributor.headline

    # Decay follows the determining (QQQ) input, not SPY's newest row: ~24.67 market hours -> 0.6, never 1.0.
    weight, age = scoring.decay_weight(obs, NOW, policy)
    assert 24.0 < age < 25.0
    assert weight == 0.6
    assert obs.stale_after_hours == pytest.approx(30.75, abs=0.02)  # Friday 17:35 ET -> Monday 18:20 ET


# ── a missing symbol ──────────────────────────────────────────────────────────────────────────────────────────────
def test_missing_symbol_is_reported_unknown_and_does_not_borrow_a_timestamp(policy):
    rows = [r for r in _history() if r["symbol"] == "SPY"]
    rows.append(_row("SPY", FRESH_MONDAY, 2.2, 2.6, 650.0))  # STRESS, Monday only; QQQ absent entirely
    obs = _eval(policy, rows)

    assert obs.state == "STRESS"
    assert obs.observed_at == FRESH_MONDAY_ISO
    assert _contributor(policy, obs).as_of == FRESH_MONDAY_ISO
    qqq = _unknown_evidence(obs, "QQQ")
    assert qqq.as_of is None and "no option-chain snapshot" in qqq.detail
    assert scoring.decay_weight(obs, NOW, policy)[0] == 1.0


# ── an expired input ──────────────────────────────────────────────────────────────────────────────────────────────
def test_expired_input_is_excluded_not_shown_as_today(policy):
    rows = _history()
    rows.append(_row("QQQ", QQQ_EXPIRED, 3.974, 0.896, 700.0))  # Friday 10:00 ET: past Monday 10:45 ET deadline
    rows.append(_row("SPY", FRESH_MONDAY, 1.215, 0.612, 650.0))  # CALM, fresh
    obs = _eval(policy, rows)

    # The expired QQQ STRESS reading must not set the state.
    assert obs.state == "CALM"
    assert obs.observed_at == FRESH_MONDAY_ISO
    assert scoring.decay_weight(obs, NOW, policy)[0] == 1.0
    qqq = _unknown_evidence(obs, "QQQ")
    assert qqq.as_of == "2026-10-30T14:00:00+00:00" and "expired" in qqq.detail


# ── a symbol rollover ────────────────────────────────────────────────────────────────────────────────────────────
def test_symbol_rollover_advances_the_evidence_time(policy):
    rows = _history()
    rows.append(_row("QQQ", QQQ_FRIDAY, 3.974, 0.896, 700.0))  # the carried Friday reading...
    rows.append(_row("QQQ", FRESH_MONDAY, 2.2, 2.6, 700.0))  # ...replaced by Monday's own STRESS collection
    rows.append(_row("SPY", FRESH_MONDAY, 1.215, 0.612, 650.0))
    obs = _eval(policy, rows)

    assert obs.state == "STRESS"
    # Once the symbol updates, the category stops carrying the old time: Monday's reading, Monday's as_of.
    assert obs.observed_at == FRESH_MONDAY_ISO
    assert _contributor(policy, obs).as_of == FRESH_MONDAY_ISO
    assert scoring.decay_weight(obs, NOW, policy) == (1.0, pytest.approx(2.25, abs=0.01))
