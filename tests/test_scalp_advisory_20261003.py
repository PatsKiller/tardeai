"""Momentum scalps are advisory alerts, not paper orders (operator 2026-10-03).

Pins: a fully-gated signal becomes an alert and never a paper_trade_proposals row; the
pre-promotion gate still runs; one alert per symbol+setup per session; the paper fast path cannot
submit while fast_path_auto_approve is false; WIDE_SPREAD reads the single 8% limit; the window
end comes from the strategy config. No Telegram is sent: the sender is stubbed.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import yaml

import importlib.util  # noqa: E402

# CI installs no psycopg2 (memory: "CI has NO psycopg2"); these tests never touch
# a database, so stand in a minimal module only when the driver is absent.
if importlib.util.find_spec("psycopg2") is None:  # pragma: no cover - CI path
    _pg = types.ModuleType("psycopg2")
    for _name in ("Error", "OperationalError", "InterfaceError", "DatabaseError", "ProgrammingError", "IntegrityError"):
        setattr(_pg, _name, type(_name, (Exception,), {}))

    def _no_db(*_a, **_k):
        raise _pg.OperationalError("psycopg2 unavailable in tests")

    _pg.connect = _no_db
    for _sub in ("extras", "extensions", "pool", "sql", "errors"):
        _m = types.ModuleType(f"psycopg2.{_sub}")
        setattr(_pg, _sub, _m)
        sys.modules[f"psycopg2.{_sub}"] = _m
    _pg.extras.RealDictCursor = object
    _pg.extras.DictCursor = object
    _pg.extras.Json = lambda value: value
    _pg.extras.execute_values = _no_db
    _pg.extensions.connection = object
    _pg.extensions.cursor = object
    _pg.pool.SimpleConnectionPool = _no_db
    _pg.pool.ThreadedConnectionPool = _no_db
    sys.modules["psycopg2"] = _pg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import auto_proposal_generator as apg  # noqa: E402
import momentum_scalp_paper_fast_path as fp  # noqa: E402
import multi_setup_router as router  # noqa: E402
from lib import scalp_advisory_alert as saa  # noqa: E402

CFG = yaml.safe_load((ROOT / "config" / "strategies" / "momentum_scalp.yaml").read_text())
SIG = {"symbol": "abcd", "strategy_id": "momentum_scalp", "setup_description": "gap_and_go",
       "signal_grade": "A", "signal_score": 44, "price": 3.1, "rvol": 9.2, "float_m": 6.5,
       "gap_pct": 18.0, "catalyst": "FDA clearance", "catalyst_verified": True,
       "entry_high": 3.2, "stop_loss": 2.9, "target_1": 3.8, "target_2": 4.4}


def test_config_is_advisory_and_paper_submit_is_off():
    assert apg._contract_delivery(CFG) == apg.ADVISORY_ALERT
    assert fp.auto_submit_enabled(CFG) is False
    assert apg._window_end_et(CFG) == "12:00"


def _patch_generator(monkeypatch, blockers):
    decisions = []
    monkeypatch.setattr(apg, "_inside_window", lambda cfg, now=None: True)
    monkeypatch.setattr(apg, "_pre_promotion_blockers", lambda sig: list(blockers))
    monkeypatch.setattr(apg, "record_decision", lambda conn, rl, sig, d, reasons, pid, sz, rg: decisions.append((d, pid)))
    monkeypatch.setattr(apg, "create_auto_proposal",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("proposal created")))
    return decisions


def test_gated_signal_alerts_and_creates_no_proposal(tmp_path, monkeypatch):
    decisions = _patch_generator(monkeypatch, [])
    monkeypatch.setattr(saa, "LEDGER", tmp_path / "ledger.json")
    monkeypatch.setattr(saa, "RECEIPTS", tmp_path / "alerts.jsonl")
    sent = []
    out = apg.deliver_advisory_alert(None, "r", dict(SIG), {}, {}, CFG,
                                     send=lambda text: sent.append(text) or True, session="2026-10-05")
    assert out["decision"] == "ADVISORY_ALERT"
    assert decisions == [("ADVISORY_ALERT", None)]
    assert len(sent) == 1 and "ABCD" in sent[0] and "nothing is placed" in sent[0]
    assert "stop $2.90" in sent[0] and "Valid until 12:00 ET" in sent[0]


def test_pre_promotion_gate_still_blocks(tmp_path, monkeypatch):
    decisions = _patch_generator(monkeypatch, ["rr_below_minimum"])
    sent = []
    out = apg.deliver_advisory_alert(None, "r", dict(SIG), {}, {}, CFG,
                                     send=lambda t: sent.append(t) or True, session="2026-10-05")
    assert out["decision"] == "SKIPPED_PREPROMOTION" and not sent
    assert decisions[0][0] == "SKIPPED_PREPROMOTION"


def test_one_alert_per_symbol_setup_per_session(tmp_path):
    kw = dict(gates={}, window_end_et="12:00", ledger_path=tmp_path / "l.json", receipts_path=tmp_path / "r.jsonl")
    sent = []
    send = lambda t: sent.append(t) or True  # noqa: E731
    first = saa.send_advisory_alert(dict(SIG), session="2026-10-05", send=send, **kw)
    again = saa.send_advisory_alert(dict(SIG), session="2026-10-05", send=send, **kw)
    next_day = saa.send_advisory_alert(dict(SIG), session="2026-10-06", send=send, **kw)
    assert (first["status"], again["status"], next_day["status"]) == ("SENT", "DUPLICATE_SUPPRESSED", "SENT")
    assert len(sent) == 2
    assert len((tmp_path / "r.jsonl").read_text().splitlines()) == 2


def test_failed_send_is_retried_next_run(tmp_path):
    kw = dict(gates={}, window_end_et="12:00", session="2026-10-05",
              ledger_path=tmp_path / "l.json", receipts_path=tmp_path / "r.jsonl")
    assert saa.send_advisory_alert(dict(SIG), send=lambda t: False, **kw)["status"] == "SEND_FAILED"
    assert saa.send_advisory_alert(dict(SIG), send=lambda t: True, **kw)["status"] == "SENT"


def test_fast_path_cannot_submit_while_advisory(monkeypatch):
    monkeypatch.setattr(fp, "_cfg", lambda: CFG)
    stub = types.ModuleType("db_adapter")

    def _conn():
        raise RuntimeError("no db in test")

    stub.get_connection = _conn
    monkeypatch.setitem(sys.modules, "db_adapter", stub)
    assert fp.run(dry_run=False)["mode"] == "dry_run"


def test_wide_spread_reads_the_single_8pct_limit():
    disq = next(d for d in CFG["auto_disqualifiers"] if d["id"] == "WIDE_SPREAD")
    assert router._config_path(CFG, disq["threshold_from"]) == 8.0
    assert router._check_ref_disqualifier(disq["condition"], disq["threshold_from"], CFG, {"spread_pct": 6.5}) is False
    assert router._check_ref_disqualifier(disq["condition"], disq["threshold_from"], CFG, {"spread_pct": 8.5}) is True
    assert router._check_ref_disqualifier(disq["condition"], disq["threshold_from"], CFG, {}) is False
    assert "spread_pct > 5" not in (ROOT / "config" / "strategies" / "momentum_scalp.yaml").read_text()


def test_outside_the_window_nothing_alerts(monkeypatch):
    decisions = _patch_generator(monkeypatch, [])
    monkeypatch.setattr(apg, "_inside_window", lambda cfg, now=None: False)
    sent = []
    out = apg.deliver_advisory_alert(None, "r", dict(SIG), {}, {}, CFG, send=lambda t: sent.append(t) or True)
    assert out["decision"] == "SKIPPED_OUTSIDE_WINDOW" and not sent
    assert decisions[0][0] == "SKIPPED_OUTSIDE_WINDOW"


def test_window_bounds_are_six_to_noon_et():
    from datetime import datetime, timezone
    at = lambda h, m: datetime(2026, 10, 5, h, m, tzinfo=timezone.utc)  # noqa: E731  EDT = UTC-4
    assert apg._inside_window(CFG, at(10, 0)) is True      # 06:00 ET
    assert apg._inside_window(CFG, at(15, 59)) is True     # 11:59 ET
    assert apg._inside_window(CFG, at(16, 0)) is False     # 12:00 ET
    assert apg._inside_window(CFG, at(9, 59)) is False     # 05:59 ET


def test_lane_split_env_filters(monkeypatch):
    monkeypatch.setenv("AUTO_PROPOSAL_STRATEGIES", "momentum_scalp")
    monkeypatch.delenv("AUTO_PROPOSAL_EXCLUDE_STRATEGIES", raising=False)
    assert apg._strategy_filter() == ({"momentum_scalp"}, set())
    monkeypatch.delenv("AUTO_PROPOSAL_STRATEGIES")
    monkeypatch.setenv("AUTO_PROPOSAL_EXCLUDE_STRATEGIES", "momentum_scalp")
    assert apg._strategy_filter() == (set(), {"momentum_scalp"})


def test_health_counts_advisory_alerts_as_conversion():
    import health_agent as ha
    assert ha._assess_go_conversion(6, 1, {"SKIPPED_LOW_SCORE": 3}, 5)["finding"] is False
    out = ha._assess_go_conversion(6, 0, {"SKIPPED_OUTSIDE_WINDOW": 4}, 5)
    assert out["severity"] == "warning"
