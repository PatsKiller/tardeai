"""LP-DEF-01 (live-proof 2026-09-28): the earnings gate must fail closed on an unknown strategy id, map every
producer vocabulary onto one canonical set, and block every directional / short-premium alternative when the
event falls inside the option's life — driven through the REAL gate, not a stub."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "tests"))

import options_desk_enterprise as ode  # noqa: E402
import buy_ready_options_alternatives as boa  # noqa: E402
from test_buy_ready_options_20260924 import V_PLAN, v_chain, _liq_ok  # noqa: E402


def _cal_31d(monkeypatch):
    # AXTI shape: earnings 31 days out, option lives 109 days → the event falls inside the option's life.
    import datetime as dt
    d = (dt.date.today() + dt.timedelta(days=31)).isoformat()
    monkeypatch.setattr(ode, "earnings_calendar", lambda syms: {s.upper(): d for s in syms})


def test_unknown_strategy_fails_closed(monkeypatch):
    _cal_31d(monkeypatch)
    r = ode.earnings_blackout_check("AXTI", dte=109, strategy="totally_new_structure")
    assert r["in_blackout"] is True and r["trigger"] == "unknown_strategy" and "not in the earnings gate" in r["reason"]


def test_aliases_resolve_to_the_canonical_set(monkeypatch):
    _cal_31d(monkeypatch)
    for raw, canon in (("debit_call_vertical", "debit_spread"), ("call_debit_spread", "debit_spread"), ("short_put", "cash_secured_put"), ("leaps", "leaps_call")):
        assert ode.canonical_strategy(raw) == canon
        r = ode.earnings_blackout_check("AXTI", dte=109, strategy=raw)
        assert r["in_blackout"] is True and r["strategy"] == canon and r["strategy_raw"] == raw and r["trigger"] == "expires_after_earnings"


def test_hedges_and_paper_canaries_never_block(monkeypatch):
    _cal_31d(monkeypatch)
    for s in ("protective_put", "deep_itm_call", "atm_call", "earnings_put_debit_spread"):
        assert ode.earnings_blackout_check("AXTI", dte=109, strategy=s)["in_blackout"] is False


def test_every_alternative_blocks_through_the_real_gate(monkeypatch):
    _cal_31d(monkeypatch)
    plan = {**V_PLAN, "symbol": "AXTI"}
    out = boa.build_alternatives(plan, v_chain(), held=True, liquidity_fn=_liq_ok, blackout_fn=ode.earnings_blackout_check)
    assert out["alternatives"], "fixture chain must yield alternatives"
    for a in out["alternatives"]:
        assert not a["qualified"] and any(d.startswith("EARNINGS_BLACKOUT") for d in a["disqualified_by"]), (a["strategy"], a["disqualified_by"])
        assert a["strategy"] in ("long_call", "debit_call_vertical", "leaps_call", "cash_secured_put")


def test_no_event_inside_life_keeps_alternatives_qualified(monkeypatch):
    import datetime as dt
    far = (dt.date.today() + dt.timedelta(days=900)).isoformat()   # beyond the longest fixture LEAPS (484 DTE)
    monkeypatch.setattr(ode, "earnings_calendar", lambda syms: {s.upper(): far for s in syms})
    out = boa.build_alternatives({**V_PLAN, "symbol": "AXTI"}, v_chain(), held=True, liquidity_fn=_liq_ok, blackout_fn=ode.earnings_blackout_check)
    assert any(a["qualified"] for a in out["alternatives"]) and not any("EARNINGS_BLACKOUT" in " ".join(a["disqualified_by"]) for a in out["alternatives"])
