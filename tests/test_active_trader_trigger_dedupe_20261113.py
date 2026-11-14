"""LQ-20261113-3133 — Active Trader triggered signals: duplicate firing and the fire-age clock.

The read-only DIAG (inbox/claude-lead/DIAG-LQ-20261113-3133-cc-deepseek-4.md) confirmed two
defects in the live journal of 2026-11-13:

P1  one trigger was journaled 15-18x (57 TRIGGERED rows, 7 distinct fire bars) because
    Throttle.veto_repeat() compared the veto REASON SET as well as the cooldown key. The reason
    set churns every ~5 s tick as book/tape flicker (SPREAD_WIDE -> +TAPE_SELLERS -> L2_ASK_HEAVY
    -> QUOTE_STALE ...), so the cooldown never matched.
P2  alert_kind() returned the TRIGGERED kind_hint on faith, before its own max_fire_age_s check.
    fast_trigger_loop branch 2b re-emits one fire for extended_watch_min (15 min), so fires
    12-16 min old were journaled as "time to buy" candidates while the rules the page prints say
    "trigger fired <= 6 min ago".

Each test names the BEFORE count it produced against base 7b0cc18d0. Synthetic fixtures only:
temp journal/throttle paths, injected fetchers, no DB, no network, no send.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import momentum_alerts as ma  # noqa: E402

NOW = 1_790_000_000.0
CFG = ma.AlertConfig()


@pytest.fixture(autouse=True)
def _journal_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVE_TRADER_ALERTS_DIR", str(tmp_path / "at"))
    return tmp_path / "at"


def book(bid=(5.00, 5000), ask=(5.01, 2000), age=2.0, levels=10, at=NOW):
    return {"bids": [(bid[0] - i * 0.01, bid[1]) for i in range(levels)],
            "asks": [(ask[0] + i * 0.01, ask[1]) for i in range(levels)],
            "ts_epoch": at - age, "ts_source": "test"}


def tape(n=30, buy_share=0.8, age=3.0, at=NOW):
    return [{"ts_epoch": at - age - (n - i), "price": 5.0, "volume": 100,
             "direction": "BUY" if i < n * buy_share else "SELL"} for i in range(n)]


def cand(**kw):
    base = dict(symbol="SMX", lane="BELOW", ign=40.0, fsm_state="FIRED", entry_ref=4.2499,
                stop_ref=4.0678, rvol=8.0, float_mm=6.0, last=4.265, quote_ts_epoch=NOW - 2,
                fire_ts_epoch=NOW - 30, session_date="2026-11-13", source="fast")
    base.update(kw)
    return ma.Candidate(**base)


def _pass(cands, *, now=NOW, books=None, cfg=CFG):
    """One evaluate_pass against an injected book, persisted to the temp journal dir."""
    n = int(now - NOW) // 5
    b = books[n] if books is not None else book(at=now)
    return ma.evaluate_pass(cands, cfg=cfg, now=now, fetch_primary_book=lambda s: b,
                            fetch_primary_tape=lambda s: tape(at=now), persist=True)


# ── P1: one veto per cooldown window, not one per tick ────────────────────────

def test_veto_repeat_ignores_reason_churn_within_the_cooldown():
    """BEFORE (base 7b0cc18d0): True, False, False -- every churn journaled again."""
    th = ma.Throttle({}, CFG)
    assert th.veto_repeat("SMX", ma.TRIGGERED, "fire:1794586500", ["SPREAD_WIDE"], NOW) is False
    assert th.veto_repeat("SMX", ma.TRIGGERED, "fire:1794586500",
                         ["BOOK_STALE", "SPREAD_WIDE"], NOW + 5) is True
    assert th.veto_repeat("SMX", ma.TRIGGERED, "fire:1794586500",
                         ["L2_ASK_HEAVY", "SPREAD_WIDE"], NOW + 10) is True
    # the window starts at the first veto; the reason set actually journaled is kept
    assert th.vetoed["SMX:TRIGGERED:fire:1794586500"] == [NOW, ["SPREAD_WIDE"]]


def test_veto_repeat_journals_again_after_a_full_cooldown_window():
    th = ma.Throttle({}, CFG)
    assert th.veto_repeat("SMX", ma.TRIGGERED, "fire:1", ["SPREAD_WIDE"], NOW) is False
    assert th.veto_repeat("SMX", ma.TRIGGERED, "fire:1", ["SPREAD_WIDE"],
                          NOW + CFG.cooldown_s - 1) is True
    assert th.veto_repeat("SMX", ma.TRIGGERED, "fire:1", ["BOOK_STALE"],
                          NOW + CFG.cooldown_s) is False


def test_veto_repeat_is_per_level_not_per_symbol():
    """A new fire is a new signal, even inside the previous fire's cooldown."""
    th = ma.Throttle({}, CFG)
    assert th.veto_repeat("SMX", ma.TRIGGERED, "fire:1", ["SPREAD_WIDE"], NOW) is False
    assert th.veto_repeat("SMX", ma.TRIGGERED, "fire:2", ["SPREAD_WIDE"], NOW + 5) is False


def test_one_trigger_journals_one_veto_not_one_per_tick(_journal_dir):
    """The live shape: same fire, reasons churn each ~5 s tick.
    BEFORE (base 7b0cc18d0): 3 rows, one per tick. AFTER: 1 row."""
    books = {0: book(at=NOW, age=60),                     # BOOK_STALE
             1: book(at=NOW + 5, ask=(5.10, 2000)),       # SPREAD_WIDE
             2: None}                                     # BOOK_MISSING
    rows = []
    for i, now in enumerate((NOW, NOW + 5, NOW + 10)):
        rows.append(_pass([cand(kind_hint=ma.TRIGGERED, quote_ts_epoch=now - 2)], now=now, books=books))
    assert [len(r) for r in rows] == [1, 0, 0]
    assert rows[0][0]["verdict"] == ma.VETO
    lines = (_journal_dir / "momentum_alerts.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["veto_reasons"] == ["BOOK_STALE"]
    # the throttle state kept the first (journaled) reason set for observability
    state = json.loads((_journal_dir / "momentum_alerts_throttle.json").read_text())
    assert state["vetoed"][f"SMX:TRIGGERED:fire:{int(NOW - 30)}"] == [NOW, ["BOOK_STALE"]]


# ── P2: the TRIGGERED hint is bounded by max_fire_age_s ───────────────────────

def test_stale_triggered_hint_is_not_a_new_trigger():
    """BEFORE (base 7b0cc18d0): all three returned TRIGGERED -- the hint was taken on faith.
    DIAG case: a 700 s old fire (the live 11:30:10 row of the 11:15 fire)."""
    on_bound = cand(kind_hint=ma.TRIGGERED, fire_ts_epoch=NOW - CFG.max_fire_age_s)
    stale = cand(kind_hint=ma.TRIGGERED, fire_ts_epoch=NOW - CFG.max_fire_age_s - 1)
    assert ma.alert_kind(cand(kind_hint=ma.TRIGGERED, fire_ts_epoch=NOW - 60), now=NOW, cfg=CFG) \
        == ma.TRIGGERED
    assert ma.alert_kind(on_bound, now=NOW, cfg=CFG) == ma.TRIGGERED
    assert ma.alert_kind(stale, now=NOW, cfg=CFG) is None
    assert ma.alert_kind(cand(kind_hint=ma.TRIGGERED, fire_ts_epoch=NOW - 700), now=NOW, cfg=CFG) is None


def test_triggered_hint_without_a_fire_timestamp_fails_closed():
    """Unknown freshness beats a guessed TRIGGERED. BEFORE: TRIGGERED."""
    assert ma.alert_kind(cand(kind_hint=ma.TRIGGERED, fire_ts_epoch=None), now=NOW, cfg=CFG) is None


def test_a_stale_trigger_is_not_relabelled_armed():
    """The setup already fired; calling it ARMED would be a different untruth. BEFORE: TRIGGERED."""
    c = cand(kind_hint=ma.TRIGGERED, fire_ts_epoch=NOW - 700, fsm_state="ARMED", lane="IGN_75")
    assert ma.alert_kind(c, now=NOW, cfg=CFG) is None


def test_stale_trigger_is_not_journaled(_journal_dir):
    """BEFORE: one ALERT row (with a "time to buy" message). AFTER: nothing, not even a file."""
    rows = _pass([cand(kind_hint=ma.TRIGGERED, fire_ts_epoch=NOW - 700)])
    assert rows == []
    assert not (_journal_dir / "momentum_alerts.jsonl").exists()


def test_fresh_triggered_hint_still_journals_and_alerts(_journal_dir):
    """The bound must not silence a live fire (the fast loop's own intrabar and branch-2b path)."""
    rows = _pass([cand(kind_hint=ma.TRIGGERED, fire_ts_epoch=NOW - 60)])
    assert len(rows) == 1 and rows[0]["kind"] == ma.TRIGGERED and rows[0]["verdict"] == ma.ALERT
    assert (_journal_dir / "momentum_alerts.jsonl").exists()


def test_other_kind_hints_are_not_age_bounded():
    """Only a TRIGGERED hint is a fire claim; every other kind passes through untouched."""
    others = [k for k in ma.KINDS if k != ma.TRIGGERED]
    assert ma.EXTENDED in others and ma.APPROACHING in others
    for kind in others:
        assert ma.alert_kind(cand(kind_hint=kind, fire_ts_epoch=NOW - 3600), now=NOW, cfg=CFG) == kind


# ── F1 (review 3133): the bound is on the BUY claim, not on the don't-chase heads-up ──────────
# A run-away fire (last past entry + chase_r·R) is EXTENDED — "don't chase, wait for the pullback" —
# and it is what writes the buy zone and arms the PULLBACK_ZONE watch. The P2 bound must not silence it.

def _runaway(**kw):
    """The same candidate, but the price already ran past entry + chase_r·R (r = 0.1821 → 4.432)."""
    return cand(last=4.50, **kw)


def test_stale_runaway_fire_keeps_the_dont_chase_heads_up():
    """FAIL-BEFORE on the P2-only tree (e908322f0): no row at all at 700 s — the heads-up and its
    zone were retired silently. Base 7b0cc18d0 emitted EXTENDED here; the fix restores that."""
    c = _runaway(kind_hint=ma.TRIGGERED, fire_ts_epoch=NOW - 700)
    assert ma.is_extended(c, CFG) is True
    assert ma.alert_kind(c, now=NOW, cfg=CFG) == ma.TRIGGERED
    assert ma.apply_chase_guard(c, ma.TRIGGERED, CFG) == ma.EXTENDED


def test_stale_runaway_fire_journals_extended_and_writes_the_zone(_journal_dir):
    """The whole downstream chain the bound used to cut: EXTENDED row + buy zone + PULLBACK_ZONE arming."""
    rows = _pass([_runaway(kind_hint=ma.TRIGGERED, fire_ts_epoch=NOW - 700)])
    assert len(rows) == 1, "a 700 s run-away fire must still produce its heads-up"
    row = rows[0]
    assert row["kind"] == ma.EXTENDED and row["verdict"] == ma.ALERT
    zones = json.loads((_journal_dir / "momentum_alerts_zones.json").read_text())
    assert "SMX" in zones
    assert zones["SMX"]["low"] < zones["SMX"]["high"]
    assert zones["SMX"]["fire_ts_epoch"] == NOW - 700
    assert zones["SMX"]["expires_epoch"] == NOW + CFG.zone_watch_min * 60


def test_stale_runaway_fire_still_heads_up_at_the_extended_watch_edge():
    """The fast loop re-emits for extended_watch_min (15 min); the reviewer's probe reached 899 s."""
    for age in (361, 420, 700, 899):
        c = _runaway(kind_hint=ma.TRIGGERED, fire_ts_epoch=NOW - age)
        assert ma.apply_chase_guard(c, ma.alert_kind(c, now=NOW, cfg=CFG), CFG) == ma.EXTENDED, age


def test_the_bound_still_refuses_a_stale_buy_claim(_journal_dir):
    """The operator's complaint — one fire must not keep saying "time to buy". A stale fire that is NOT
    run-away is dropped, and the difference from the case above is exactly is_extended()."""
    ordinary = cand(kind_hint=ma.TRIGGERED, fire_ts_epoch=NOW - 700)
    assert ma.is_extended(ordinary, CFG) is False
    assert ma.alert_kind(ordinary, now=NOW, cfg=CFG) is None
    assert _pass([ordinary]) == []


def test_the_heads_up_needs_a_fire_timestamp():
    """Without a fire timestamp there is no freshness fact, so nothing survives the bound (fail closed)."""
    assert ma.alert_kind(_runaway(kind_hint=ma.TRIGGERED, fire_ts_epoch=None), now=NOW, cfg=CFG) is None


def test_a_fresh_runaway_fire_is_extended_not_triggered(_journal_dir):
    """Unchanged: inside the bound a run-away fire is the same EXTENDED heads-up, never a buy claim."""
    rows = _pass([_runaway(kind_hint=ma.TRIGGERED, fire_ts_epoch=NOW - 60)])
    assert len(rows) == 1 and rows[0]["kind"] == ma.EXTENDED and rows[0]["verdict"] == ma.ALERT
