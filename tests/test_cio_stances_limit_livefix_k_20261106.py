"""LIVEFIX-K: a projection ``limit`` must apply AFTER filtering to the requested names.

Unfiltered, ``limit`` kept the top-N prospects by conviction, so low-conviction requested names vanished and
the Home card relabelled the missing record as a timestamp defect.
"""
from datetime import datetime, timezone

from scripts.lib import cio_truth
from scripts.lib.market_risk_home_context import collect  # noqa: F401  (import guard)

NOW = datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc)


def _row(sym, conviction):
    return {"symbol": sym, "security_guid": f"G-{sym}", "stance": "WATCH", "conviction": conviction,
            "stage": "watch", "as_of": "2026-01-05T17:00:00+00:00", "revision": 1,
            "inputs_as_of": "2026-01-05T16:00:00+00:00"}


def test_limit_applies_after_symbol_filter(monkeypatch):
    rows = [_row(f"HI{i}", 90 - i * 0.1) for i in range(100)] + [_row("LOWX", 10)]
    calls = {}

    def fake_get_prospects(*, symbols=None, limit=None, **_):
        calls["symbols"] = symbols
        want = {s.upper() for s in symbols} if symbols is not None else None
        picked = [r for r in rows if want is None or r["security_guid"].upper() in want]
        return {"prospects": picked[:limit] if limit else picked, "source": {"kind": "shadow"}}

    import scripts.lib.data_broker.cio_prospect as cp
    monkeypatch.setattr(cp, "get_prospects", fake_get_prospects)
    resolver = lambda s, root=None: {"identity_status": "CONFIRMED", "security_guid": f"G-{s}"}
    out = cio_truth.stances_for_symbols(["LOWX"], identity_resolver=resolver, now=NOW, limit=80)
    assert calls["symbols"] == ["G-LOWX"]
    assert out["LOWX"]["stance"] == "WATCH" and out["LOWX"]["gap"] is None


def test_missing_record_is_not_called_a_clock_defect():
    st = cio_truth.stance_for("G-NONE", projection={"prospects": []}, now=NOW)
    assert st["gap"] and st["input_time_gap"] is None
