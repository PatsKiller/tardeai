"""Index options-flow detector (DSN-20261031-market-risk-engine-P0-T6).

Fixture = the system's own option_chain_snapshots rows for 2026-10-23..10-29 (RCA finding 4): at 10:00 ET on
10-29 QQQ put/call volume went 0.96 -> 3.31 and put/call OI 1.375 -> 2.856; SPY OI 0.90 -> 1.51. The detector must
read those as STRESS (QQQ) / WARN (SPY) and, during the regular session, choose P1. Pins also: short history is
UNKNOWN (never a false calm), no finding -> no send, dry run prints and sends nothing, send errors surface, every
threshold comes from config/market_risk_policy.yaml. Hermetic: fake cursor, telegram_alert / market_session stubbed.
"""

from __future__ import annotations

#: C1 firing coverage — the tests below inject the 10-29 surge and assert the card reaches the (stubbed) transport.
COVERS = ["scripts/lib/market_risk/flow_alert.py"]

import sys
import types
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.market_risk import options_flow as of  # noqa: E402
from lib.market_risk.policy import load_policy  # noqa: E402

CFG = load_policy()["options_flow"]

# option_chain_snapshots, newest first, excluding 10-29 (the "today" being evaluated)
QQQ_HIST = [
    {"as_of": "2026-10-28", "pc_oi_ratio": 1.375, "pc_vol_ratio": 0.96, "underlying_price": 722.18},
    {"as_of": "2026-10-27", "pc_oi_ratio": 1.337, "pc_vol_ratio": 0.865, "underlying_price": 721.19},
    {"as_of": "2026-10-26", "pc_oi_ratio": 2.1, "pc_vol_ratio": 0.96, "underlying_price": 712.53},
    {"as_of": "2026-10-23", "pc_oi_ratio": 2.914, "pc_vol_ratio": 1.022, "underlying_price": 705.54},
    {"as_of": "2026-10-22", "pc_oi_ratio": 1.6, "pc_vol_ratio": 1.1, "underlying_price": 704.0},
    {"as_of": "2026-10-21", "pc_oi_ratio": 1.5, "pc_vol_ratio": 0.98, "underlying_price": 725.0},
]
SPY_HIST = [
    {"as_of": "2026-10-28", "pc_oi_ratio": 0.9, "pc_vol_ratio": 1.024, "underlying_price": 770.45},
    {"as_of": "2026-10-27", "pc_oi_ratio": 0.85, "pc_vol_ratio": 0.924, "underlying_price": 770.04},
    {"as_of": "2026-10-26", "pc_oi_ratio": 1.193, "pc_vol_ratio": 0.906, "underlying_price": 765.32},
    {"as_of": "2026-10-23", "pc_oi_ratio": 1.717, "pc_vol_ratio": 1.118, "underlying_price": 761.11},
    {"as_of": "2026-10-22", "pc_oi_ratio": 1.0, "pc_vol_ratio": 1.0, "underlying_price": 764.0},
    {"as_of": "2026-10-21", "pc_oi_ratio": 0.95, "pc_vol_ratio": 0.99, "underlying_price": 773.0},
]
TODAY_1029 = {
    "QQQ": {"pc_oi_ratio": 2.856, "pc_vol_ratio": 3.309, "underlying_price": 705.5, "as_of": "2026-10-29"},
    "SPY": {"pc_oi_ratio": 1.513, "pc_vol_ratio": 1.292, "underlying_price": 764.57, "as_of": "2026-10-29"},
}
CALM_1028 = {
    "QQQ": {"pc_oi_ratio": 1.375, "pc_vol_ratio": 0.96, "underlying_price": 722.18, "as_of": "2026-10-28"},
    "SPY": {"pc_oi_ratio": 0.9, "pc_vol_ratio": 1.024, "underlying_price": 770.45, "as_of": "2026-10-28"},
}


def test_policy_carries_every_threshold():
    for k in (
        "index_symbols",
        "lookback_sessions",
        "min_history_sessions",
        "warn_factor",
        "stress_factor",
        "absolute_pc_vol_stress",
        "priority",
        "dedupe_minutes",
        "producer",
    ):
        assert k in CFG, k
    assert set(CFG["priority"]) == {"stress_market_hours", "stress_after_hours", "warn"}


def test_the_1029_morning_is_stress_on_qqq_and_warn_on_spy():
    out = of.evaluate(TODAY_1029, {"QQQ": QQQ_HIST, "SPY": SPY_HIST}, CFG)
    by = {f["symbol"]: f for f in out}
    assert by["QQQ"]["state"] == of.STRESS and by["QQQ"]["pc_vol_state"] == of.STRESS
    assert by["QQQ"]["pc_vol_factor"] >= 3.0 and by["QQQ"]["pc_oi_state"] == of.WARN
    assert by["QQQ"]["underlying_change_pct_vs_prior"] < -2.0
    assert by["SPY"]["state"] == of.WARN and by["SPY"]["pc_oi_state"] == of.WARN and by["SPY"]["pc_vol_state"] is None
    assert out[0]["symbol"] == "QQQ", "STRESS sorts first"
    assert of.priority_for(out, "regular", CFG) == "P1"
    assert of.priority_for(out, "afterhours", CFG) == "P2"


def test_a_calm_day_has_no_finding_and_no_priority():
    out = of.evaluate(CALM_1028, {"QQQ": QQQ_HIST[1:], "SPY": SPY_HIST[1:]}, CFG)
    assert out == [] and of.priority_for(out, "regular", CFG) is None


def test_short_history_is_unknown_not_calm():
    out = of.evaluate(TODAY_1029, {"QQQ": QQQ_HIST[:2], "SPY": []}, CFG)
    assert {f["symbol"]: f["state"] for f in out} == {"QQQ": "UNKNOWN", "SPY": "UNKNOWN"}
    assert of.priority_for(out, "regular", CFG) is None


def test_absolute_volume_floor_is_stress_even_against_a_high_median():
    hist = [dict(h, pc_vol_ratio=2.0) for h in QQQ_HIST]  # a median of 2.0 would make 3.31 only 1.65x
    out = of.evaluate({"QQQ": TODAY_1029["QQQ"]}, {"QQQ": hist}, CFG)
    assert out and out[0]["state"] == of.STRESS and out[0]["pc_vol_state"] == of.STRESS


def test_render_names_the_numbers_and_only_a_review():
    out = of.evaluate(TODAY_1029, {"QQQ": QQQ_HIST, "SPY": SPY_HIST}, CFG)
    text = of.render(out, "regular", "Thu 10-29 10:00 EDT")
    assert "INDEX OPTIONS FLOW STRESS" in text and "QQQ" in text and "3.31" in text and "median" in text
    import re

    assert re.search(r"\b(buy|sell|short|long)\b", text, re.I) is None, "a card recommends a review, never a trade"
    assert re.search(r"\$\s?\d|\b\d+\s*(shares|contracts)\b", text) is None, "no size or dollar amount"
    assert "advisory" in text and "MBI_BEHAVIOR = 0" in text


class FakeCur:
    def __init__(self, hist):
        self.hist = hist
        self._sym = None

    def execute(self, sql, params=None):
        self._sym = params[0] if params else None

    def fetchall(self):
        return [
            (h["as_of"], h["pc_oi_ratio"], h["pc_vol_ratio"], h["underlying_price"])
            for h in self.hist.get(self._sym, [])
        ]


@pytest.fixture
def wired(monkeypatch):
    import options_chain_snapshot as ocs

    sent = []
    tg = types.ModuleType("telegram_alert")
    tg.send_telegram = lambda msg, **k: sent.append({"msg": msg, **k}) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", tg)
    ms = types.ModuleType("market_session")
    ms.current_market_session = lambda now=None: "regular"
    monkeypatch.setitem(sys.modules, "market_session", ms)
    return ocs, sent


def test_wiring_sends_one_p1_intent_with_policy_dedupe(wired):
    ocs, sent = wired
    out = ocs._flow_alerts(FakeCur({"QQQ": QQQ_HIST, "SPY": SPY_HIST}), TODAY_1029, dry_run=False)
    assert out["priority"] == "P1" and out["accepted"] is True and out["error"] is None
    assert len(sent) == 1
    c = sent[0]
    assert (
        c["priority"] == "P1" and c["dedupe_minutes"] == int(CFG["dedupe_minutes"]) and c["producer"] == CFG["producer"]
    )
    assert c["message_class"] == "market_risk" and "QQQ" in c["msg"]


def test_wiring_dry_run_prints_and_sends_nothing(wired, capsys):
    ocs, sent = wired
    out = ocs._flow_alerts(FakeCur({"QQQ": QQQ_HIST, "SPY": SPY_HIST}), TODAY_1029, dry_run=True)
    assert out["priority"] == "P1" and out["accepted"] is None and sent == []
    assert "DRY RUN would send P1" in capsys.readouterr().out


def test_wiring_calm_day_sends_nothing(wired):
    ocs, sent = wired
    out = ocs._flow_alerts(FakeCur({"QQQ": QQQ_HIST[1:], "SPY": SPY_HIST[1:]}), CALM_1028, dry_run=False)
    assert out["priority"] is None and sent == []


def test_wiring_surfaces_a_send_failure(wired):
    ocs, sent = wired

    def boom(msg, **k):
        raise RuntimeError("transport down")

    sys.modules["telegram_alert"].send_telegram = boom
    out = ocs._flow_alerts(FakeCur({"QQQ": QQQ_HIST, "SPY": SPY_HIST}), TODAY_1029, dry_run=False)
    assert out["accepted"] is False and "transport down" in out["error"]


def test_as_of_today_is_a_date_string():
    assert isinstance(date.today().isoformat(), str)
