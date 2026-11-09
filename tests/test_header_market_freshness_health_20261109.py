"""LQ-20261107-1610 — header REGIME / VIX contracts (header-market-freshness-health).

ANCHOR: HEADER_MARKET_FRESHNESS_HEALTH_20261109

Synthetic values only. The first case reproduces the defect the lane exists to catch: the header serving the scanner
run's VIX stamped with the run's clock while the card serves the Schwab print.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import header_market_freshness_health as hm  # noqa: E402

SCHWAB = "market_quotes_extended:schwab:$VIX"
OBS = "2026-01-12T03:45:00-05:00"


def _headline(vix=21.5, state="FRESH", as_of=OBS, source=SCHWAB, reason=None):
    return {"vix": vix, "vix_source": source if vix is not None else None,
            "vix_observation_time": as_of if vix is not None else None, "vix_state": state,
            "vix_age_hours": 5.0, "vix_stale_after_hours": 26.0, "vix_reason": reason}


def _header(vix=21.5, source=SCHWAB, as_of=OBS):
    return {"vix": vix, "vix_source": source, "vix_observation_time": as_of}


def _card(vix=21.5, source=SCHWAB, as_of=OBS):
    return {"vix": vix, "vix_source": source, "vix_as_of": as_of}


def test_the_scanner_vix_on_the_header_is_broken():
    """The live defect, synthetic: a carried close stamped with the scanner run's clock, beside the card's print."""
    out = hm.vix_contract(headline=_headline(), card=_card(),
                          header=_header(25.6, "trade_ai_run_summary", "2026-01-12T14:07:00+00:00"))
    assert out["verdict"] == "BROKEN" and out["reason"] == "header_source_inadmissible:trade_ai_run_summary"


def test_an_unfiltered_regime_row_or_a_banned_feed_is_broken():
    for src in ("market_regime_indicators.vix_close", "yahoo_finance"):
        out = hm.vix_contract(headline=_headline(), header=_header(source=src), card=_card())
        assert out["verdict"] == "BROKEN" and src in out["reason"]


def test_one_fresh_vix_on_both_surfaces_is_ok():
    out = hm.vix_contract(headline=_headline(), header=_header(), card=_card())
    assert (out["verdict"], out["reason"]) == ("OK", None)


def test_the_same_instant_in_another_zone_is_the_same_observation():
    out = hm.vix_contract(headline=_headline(), header=_header(as_of="2026-01-12T08:45:00+00:00"), card=_card())
    assert out["verdict"] == "OK"


def test_a_stale_headline_is_degraded_not_broken():
    out = hm.vix_contract(headline=_headline(state="STALE", reason="carried print from 2026-01-09"),
                          header=_header(), card=_card())
    assert out["verdict"] == "DEGRADED" and "carried print" in out["reason"]


def test_the_card_disagreeing_is_broken():
    out = hm.vix_contract(headline=_headline(), header=_header(), card=_card(vix=99.0))
    assert out["verdict"] == "BROKEN" and out["reason"] == "card_disagrees_with_headline"


def test_a_header_cache_older_than_the_print_is_lag_and_a_newer_one_is_a_second_source():
    older = _header(as_of="2026-01-11T21:00:00-05:00", vix=20.0)
    lag = hm.vix_contract(headline=_headline(), header=older, card=_card(),
                          header_written_at=datetime(2026, 1, 12, 2, 0, tzinfo=timezone.utc))
    assert lag["verdict"] == "DEGRADED" and lag["reason"] == "header_cache_older_than_newest_print"
    second = hm.vix_contract(headline=_headline(), header=older, card=_card(),
                             header_written_at=datetime(2026, 1, 12, 16, 0, tzinfo=timezone.utc))
    assert second["verdict"] == "BROKEN" and second["reason"] == "header_disagrees_with_headline"


def test_no_admissible_vix_is_broken_and_a_failed_read_or_missing_header_is_unverifiable():
    none = hm.vix_contract(headline=_headline(vix=None, state="UNAVAILABLE", reason="vix_close_unavailable:no_row"),
                           header=_header(vix=None, source=None, as_of=None), card=None)
    assert none["verdict"] == "BROKEN" and none["reason"].startswith("no_admissible_vix")
    failed = hm.vix_contract(headline=_headline(vix=None, state="UNAVAILABLE",
                                                reason="vix_complex read failed: OperationalError"),
                             header=_header(), card=_card())
    assert failed["verdict"] == "UNVERIFIABLE"
    assert hm.vix_contract(headline=_headline(), header=None, card=_card())["verdict"] == "UNVERIFIABLE"


def test_regime_contract_reads_its_own_clock():
    row = {"regime_label": "risk_on"}
    ok = {"regime": row, "as_of": "2026-01-12T10:00:00+00:00", "age_hours": 2.0, "stale": False, "stale_after_hours": 26}
    assert hm.regime_contract(ok)["verdict"] == "OK"
    assert hm.regime_contract({**ok, "stale": True, "age_hours": 55.2})["verdict"] == "DEGRADED"
    assert hm.regime_contract({**ok, "as_of": None, "age_hours": None})["reason"] == "regime_clock_not_reported"
    assert hm.regime_contract({**ok, "regime": None})["verdict"] == "BROKEN"
    assert hm.regime_contract(None)["verdict"] == "UNVERIFIABLE"


class _Conn:
    def __init__(self):
        self.commits = 0
        self.closed = False

    def rollback(self):
        pass

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def _wire(monkeypatch, tmp_path, *, header, recently=False):
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    (tmp_path / "data" / "runtime" / "trade_ai_cache.json").write_text(json.dumps(header), encoding="utf-8")
    from lib import cio_truth
    from lib import vix_headline as vh
    from lib.data_broker import market_regime as mr
    monkeypatch.setattr(hm, "_db_query_for", lambda conn: (lambda *a, **k: []))
    monkeypatch.setattr(vh, "vix_headline", lambda **k: _headline())
    env = {"regime": {"regime_label": "risk_on"}, "as_of": "2026-01-12T10:00:00+00:00", "age_hours": 2.0,
           "stale": False, "stale_after_hours": 26}
    monkeypatch.setattr(mr, "get_market_regime", lambda *a, **k: env)
    monkeypatch.setattr(cio_truth, "regime_for", lambda **k: _card())
    monkeypatch.setattr(hm, "_recently_escalated", lambda conn, name: recently)


def test_apply_escalates_a_broken_contract_once_and_sends_nothing(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, header=_header(25.6, "trade_ai_run_summary"))
    sent = []
    conn = _Conn()
    out = hm.run(root=tmp_path, apply=True, conn=conn, escalate=lambda n, r: sent.append(n) or True)
    assert out["verdict"] == "BROKEN" and out["escalated"] == ["vix"] and sent == ["vix"]
    assert out["sends"] == 0 and conn.commits == 1 and not conn.closed  # a caller's connection stays the caller's


def test_cooldown_suppresses_and_dry_run_never_escalates(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, header=_header(25.6, "trade_ai_run_summary"), recently=True)
    sent = []
    out = hm.run(root=tmp_path, apply=True, conn=_Conn(), escalate=lambda n, r: sent.append(n) or True)
    assert out["escalated"] == [] and out["escalation_suppressed_cooldown"] == ["vix"] and sent == []
    dry = hm.run(root=tmp_path, apply=False, conn=_Conn(), escalate=lambda n, r: sent.append(n) or True)
    assert dry["mode"] == "dry_run" and dry["escalated"] == [] and sent == []


def test_after_the_fix_both_contracts_are_ok(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, header=_header())
    out = hm.run(root=tmp_path, apply=False, conn=_Conn())
    assert out["verdict"] == "OK" and out["broken"] == 0
