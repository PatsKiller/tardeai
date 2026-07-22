"""Chart-pattern engine tests (Section 17.19 items 1-10) — synthetic OHLCV
fixtures, positive AND negative, zero network. Deterministic geometry only."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import chart_patterns as cp  # noqa: E402


def bars_from_closes(closes, spread=0.6, vol=1_000_000, vol_at=None):
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        hi = max(prev, c) + spread
        lo = min(prev, c) - spread
        v = vol * (vol_at.get(i, 1.0) if vol_at else 1.0)
        out.append({"open": prev, "high": hi, "low": lo, "close": c,
                    "volume": v, "ts": f"b{i}"})
        prev = c
    return out


def ramp(a, b, n):
    return [a + (b - a) * i / max(1, n - 1) for i in range(n)]


# ── fixtures ─────────────────────────────────────────────────────────────────
def hs_fixture(scale=1.0, confirm=True):
    """Valid H&S: LS 84.2 · head 91.4 · RS 85.1 · neckline ~78.6."""
    seq = (ramp(70, 84.2, 10) + ramp(84.2, 78.5, 6) + ramp(78.5, 91.4, 10)
           + ramp(91.4, 78.7, 8) + ramp(78.7, 85.1, 8) + ramp(85.1, 79.5, 6))
    if confirm:
        seq += ramp(79.5, 74.0, 6)   # closed break of the neckline
    else:
        seq += ramp(79.5, 79.2, 6)   # hovers above — must NOT be CONFIRMED
    # spread scales with price so relative geometry is identical at every scale
    return bars_from_closes([round(x * scale, 4) for x in seq], spread=0.6 * scale)


def invalid_hs_fixture():
    """Looks similar but the 'head' barely exceeds shoulders (< tolerance)."""
    seq = (ramp(70, 84.2, 10) + ramp(84.2, 78.5, 6) + ramp(78.5, 84.9, 10)
           + ramp(84.9, 78.7, 8) + ramp(78.7, 84.4, 8) + ramp(84.4, 74.0, 10))
    return bars_from_closes(seq)


def double_bottom_fixture(confirm=True):
    seq = (ramp(90, 70.2, 10) + ramp(70.2, 79.0, 8) + ramp(79.0, 70.5, 8))
    seq += ramp(70.5, 83.0, 10) if confirm else ramp(70.5, 76.0, 6)
    return bars_from_closes(seq)


def loose_double_top_fixture():
    """Two peaks far apart in price (outside EQ tolerance) — must be rejected."""
    seq = (ramp(70, 90.0, 10) + ramp(90, 80, 8) + ramp(80, 84.5, 8) + ramp(84.5, 70, 10))
    return bars_from_closes(seq)


def bull_flag_fixture(confirmed=False):
    pole = ramp(50, 65, 13)
    flag = [64.4, 64.0, 63.6, 63.8, 63.4, 63.6]
    seq = ramp(49, 50, 12) + pole + flag
    if confirmed:
        seq += [66.5]
    return bars_from_closes(seq, vol_at={len(seq) - 1: 3.0} if confirmed else None)


def ascending_triangle_fixture():
    seq = []
    lows = [70, 72.5, 75, 77.5]
    for lo in lows:
        seq += ramp(lo, 80.0, 6) + ramp(80.0, lo + 2.5, 6)
    seq += ramp(lows[-1] + 2.5, 79.5, 4)
    return bars_from_closes(seq)


def cup_handle_fixture():
    seq = (ramp(95, 100, 8) + ramp(100, 80, 15) + ramp(80, 99.5, 15)
           + [98.5, 97.8, 97.2, 97.6, 98.2, 99.0])
    return bars_from_closes(seq)


# ── tests 1-10 ───────────────────────────────────────────────────────────────
def _find(res, name):
    return [p for p in res["patterns"] if p["pattern"] == name]


def test_1_head_and_shoulders_detected_on_valid_fixture():
    res = cp.detect_all(hs_fixture())
    hs = _find(res, "HEAD_AND_SHOULDERS")
    assert hs, f"H&S not detected; found {[p['pattern'] for p in res['patterns']]}"
    assert hs[0]["state"] == "CONFIRMED"
    assert hs[0]["direction"] == "BEARISH"
    assert hs[0]["measured_target"] < hs[0]["trigger"]


def test_2_similar_invalid_fixture_rejected():
    res = cp.detect_all(invalid_hs_fixture())
    assert not _find(res, "HEAD_AND_SHOULDERS"), \
        "head within shoulder tolerance must not classify as H&S"


def test_3_inverse_hs_separately_classified():
    inv = [{"open": 200 - b["open"], "high": 200 - b["low"], "low": 200 - b["high"],
            "close": 200 - b["close"], "volume": b["volume"], "ts": b["ts"]}
           for b in hs_fixture()]
    res = cp.detect_all(inv)
    ihs = _find(res, "INVERSE_HEAD_AND_SHOULDERS")
    assert ihs and ihs[0]["direction"] == "BULLISH"
    assert not _find(res, "HEAD_AND_SHOULDERS")


def test_4_double_extremes_require_documented_tolerance():
    ok = cp.detect_all(double_bottom_fixture())
    assert _find(ok, "DOUBLE_BOTTOM"), "valid double bottom missed"
    bad = cp.detect_all(loose_double_top_fixture())
    assert not _find(bad, "DOUBLE_TOP"), \
        "peaks outside EQ_TOL_ATR must not form a double top"


def test_5_flags_triangles_cup_have_positive_fixtures():
    assert _find(cp.detect_all(bull_flag_fixture(confirmed=True)), "BULL_FLAG") or \
        _find(cp.detect_all(bull_flag_fixture(confirmed=True)), "BULLISH_PENNANT")
    tri = cp.detect_all(ascending_triangle_fixture())
    assert _find(tri, "ASCENDING_TRIANGLE") or _find(tri, "SYMMETRICAL_TRIANGLE"), \
        f"triangle missed: {[p['pattern'] for p in tri['patterns']]}"
    cup = cp.detect_all(cup_handle_fixture())
    assert _find(cup, "CUP_AND_HANDLE")


def test_5b_negative_flag_fixture():
    """A weak drift with no pole must not be a flag."""
    res = cp.detect_all(bars_from_closes(ramp(50, 51.5, 40)))
    assert not any(p["pattern"].endswith("FLAG") or p["pattern"].endswith("PENNANT")
                   for p in res["patterns"])


def test_6_forming_never_displays_confirmed():
    res = cp.detect_all(hs_fixture(confirm=False))
    for p in _find(res, "HEAD_AND_SHOULDERS"):
        assert p["state"] != "CONFIRMED", "no closed bar broke the neckline"


def test_7_confirmation_requires_closed_break():
    unconfirmed = cp.detect_all(double_bottom_fixture(confirm=False))
    for p in _find(unconfirmed, "DOUBLE_BOTTOM"):
        assert p["state"] in ("AWAITING_CONFIRMATION", "FORMING")


def test_8_no_lookahead_pivots():
    """Truncating the future must not change earlier pivot geometry."""
    full = hs_fixture()
    early = full[:30]
    piv_full = [(p.idx, p.price) for p in cp.find_pivots(full) if p.idx < 25]
    piv_early = [(p.idx, p.price) for p in cp.find_pivots(early) if p.idx < 25]
    assert piv_early == piv_full[:len(piv_early)]


def test_9_price_scale_normalization():
    """$6 stock and $600 stock: identical relative geometry → identical verdicts."""
    small = cp.detect_all(hs_fixture(scale=0.075))
    big = cp.detect_all(hs_fixture(scale=7.5))
    assert bool(_find(small, "HEAD_AND_SHOULDERS")) == bool(_find(big, "HEAD_AND_SHOULDERS"))
    if _find(small, "HEAD_AND_SHOULDERS"):
        assert _find(small, "HEAD_AND_SHOULDERS")[0]["state"] == \
            _find(big, "HEAD_AND_SHOULDERS")[0]["state"]


def test_10_trigger_invalidation_target_deterministic():
    a = cp.detect_all(hs_fixture())
    b = cp.detect_all(hs_fixture())
    pa, pb = _find(a, "HEAD_AND_SHOULDERS")[0], _find(b, "HEAD_AND_SHOULDERS")[0]
    for k in ("trigger", "invalidation", "measured_target", "quality_score", "state"):
        assert pa[k] == pb[k]
    assert pa["trigger"] is not None and pa["invalidation"] is not None \
        and pa["measured_target"] is not None


def test_quality_components_documented():
    res = cp.detect_all(hs_fixture())
    p = _find(res, "HEAD_AND_SHOULDERS")[0]
    assert set(p["quality_components"]) == {"geometry", "symmetry", "volume_confirmation",
                                            "duration", "boundary_quality"}
    assert 0 <= p["quality_score"] <= 100


def test_candle_structures_detected():
    closes = ramp(50, 48, 20)
    bars = bars_from_closes(closes)
    # force a bullish engulfing on the last bar
    bars[-2].update(open=48.4, close=48.0, high=48.6, low=47.8)
    bars[-1].update(open=47.9, close=48.9, high=49.0, low=47.7)
    res = cp.detect_all(bars)
    names = [c["pattern"] for c in res["candles"]]
    assert "BULLISH_ENGULFING" in names
    for c in res["candles"]:
        assert c["primary_eligible"] is False, "a lone candle never leads the rail"
