"""G10–G12 (2026-10-11), on the G8/G9 branch.

Honest exits, release-tree writes, the sender-flag check, and a second check of the g11 SIEM
skip (scripts/siem_critical_notify.select_incidents). Hermetic: no live .env, no database.
psycopg2 is stubbed only when it is not installed, the same way as
tests/test_notification_intents_wave2_20261011.py.
"""
from __future__ import annotations

import io
import json
import sys
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def no_psycopg2(monkeypatch):
    """Stub psycopg2 when it is not installed (CI has no DB driver).

    The modules under test import psycopg2 at module scope. A stub that raises on connect
    keeps the test from opening a database, and leaves a host with the real driver untouched.
    """
    try:
        import psycopg2  # noqa: F401
        import psycopg2.extras  # noqa: F401
        return
    except ImportError:
        pass

    def _no_db(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must not connect to a database")

    pg = types.ModuleType("psycopg2")
    pg.connect = _no_db
    pg.Error = pg.OperationalError = pg.DatabaseError = Exception
    extras = types.ModuleType("psycopg2.extras")
    extras.RealDictCursor = extras.DictCursor = object
    extras.execute_values = extras.execute_batch = _no_db
    pg.extras = extras
    monkeypatch.setitem(sys.modules, "psycopg2", pg)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)


class _Cur:
    def __init__(self, fail_insert_n=None, fail_rule=False):
        self.sql: list[str] = []
        self.inserts = 0
        self.fail_insert_n = fail_insert_n
        self.fail_rule = fail_rule

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self.sql.append(flat)
        if "INSERT INTO agent_recommendation_outcomes" in flat:
            self.inserts += 1
            if self.fail_insert_n is not None and self.inserts == self.fail_insert_n:
                raise RuntimeError("row failed")
        if self.fail_rule and "INSERT INTO agent_intelligence_rules" in flat:
            raise RuntimeError("rule failed")

    def fetchall(self):
        if any("FROM agent_calibration" in s for s in self.sql):
            return [("maria", 80.0, 4, 1, 5, "STABLE", 1.5)]
        return []

    def fetchone(self):
        return None


class _Conn:
    def __init__(self, cur):
        self.cur = cur
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, *a, **k):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_one_failed_outcome_row_exits_nonzero_and_keeps_the_rest(no_psycopg2):
    import agent_outcome_scorer as aos

    conn = _Conn(_Cur(fail_insert_n=2))
    stats: dict = {}
    rows = [{"verdict": "CORRECT", "verdict_score": 1.0}, {"verdict": "WRONG", "verdict_score": -1.0}]
    saved = aos.save_outcomes(conn, rows, stats)
    assert saved == 1 and stats["save_failed"] == 1 and conn.commits == 1
    assert any(s.startswith("ROLLBACK TO SAVEPOINT aos_outcome") for s in conn.cur.sql)
    summary = {"unscored_pairs": 2, "saved": saved, "save_failed": 1, "rule_write_failed": 0,
               "source_performance_ok": True}
    assert aos._exit_code(summary) == 1
    assert aos._exit_code({**summary, "save_failed": 0, "unscored_pairs": 0, "saved": 0}) == 0


def test_a_failed_calibration_rule_write_exits_nonzero(no_psycopg2):
    import agent_outcome_scorer as aos

    conn = _Conn(_Cur(fail_rule=True))
    stats: dict = {}
    aos.write_calibration_to_rules(conn, stats)
    assert stats["rule_write_failed"] == 1
    assert any(s.startswith("ROLLBACK TO SAVEPOINT aos_rule") for s in conn.cur.sql)
    assert aos._exit_code({"unscored_pairs": 0, "saved": 0, "save_failed": 0, "rule_write_failed": 1,
                           "source_performance_ok": True}) == 1


def _import_backtest():
    for name in ("pandas", "numpy", "yfinance"):
        try:
            __import__(name)
        except ModuleNotFoundError:
            sys.modules.setdefault(name, types.ModuleType(name))
    import trade_backtest_engine as tbe
    return tbe


def test_backtest_full_outage_exits_nonzero_partial_and_empty_stay_zero(no_psycopg2, monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    tbe = _import_backtest()
    assert tbe._counts_exit({"full": 0, "partial": 0, "insufficient": 0, "error": 0}) == 0
    assert tbe._counts_exit({"full": 1, "partial": 0, "insufficient": 0, "error": 2}) == 0
    monkeypatch.setattr(tbe, "run_all", lambda limit=None: {"full": 0, "partial": 0, "insufficient": 0, "error": 3})
    monkeypatch.setattr(tbe, "print_summary", lambda: None)
    assert tbe.main([]) == 1
    receipt = json.loads((tmp_path / "state" / "data" / "runtime" / "trade_backtest_engine_last.json").read_text())
    assert receipt["status"] == "failed" and receipt["exit"] == 1


def _lockup_seed(path: Path) -> None:
    est = (date.today() + timedelta(days=30)).isoformat()
    path.write_text(json.dumps({"lockups": {"SPCX": {"tranches": [
        {"date": est, "approx": True, "desc": "2nd trading day after earnings", "pct": 10},
    ]}}}), encoding="utf-8")


def test_earnings_lookup_error_exits_nonzero_and_does_not_write(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    import update_lockup_earnings_dates as ule

    seed = tmp_path / "ipo_lockups.json"
    _lockup_seed(seed)
    before = seed.read_bytes()
    monkeypatch.setattr(ule, "SEED_CFG", tmp_path / "not-this.json")
    monkeypatch.setattr(ule, "CFG", seed)

    def boom(symbol):
        raise RuntimeError("lookup down")

    yf = types.ModuleType("yfinance")
    yf.Ticker = boom
    monkeypatch.setitem(sys.modules, "yfinance", yf)
    assert ule.main([]) == 1
    assert seed.read_bytes() == before


def test_lockup_snap_writes_the_state_copy_and_leaves_the_seed(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "receipts"))
    import update_lockup_earnings_dates as ule

    seed = tmp_path / "seed" / "ipo_lockups.json"
    seed.parent.mkdir()
    _lockup_seed(seed)
    before = seed.read_bytes()
    state = tmp_path / "persistent" / "config" / "ipo_lockups.json"
    monkeypatch.setattr(ule, "SEED_CFG", seed)
    monkeypatch.setattr(ule, "CFG", seed)
    monkeypatch.setattr(ule, "_state_cfg", lambda: state)
    monkeypatch.setattr(ule, "_next_earnings", lambda sym: date.today() + timedelta(days=33))
    fake = types.ModuleType("alert_event_writer")
    fake.save_alert_event = lambda **k: None
    monkeypatch.setitem(sys.modules, "alert_event_writer", fake)
    assert ule.main([]) == 0
    assert seed.read_bytes() == before
    written = json.loads(state.read_text())["lockups"]["SPCX"]["tranches"][0]
    assert written["approx"] is False and "snapped" in written["note"]
    assert not str(state).startswith(str(ROOT))


def test_lockup_reader_prefers_the_state_copy_outside_tests():
    import ipo_lockups

    state = Path("/tmp/g10-state/config/ipo_lockups.json")
    seed = Path("/tmp/g10-seed/config/ipo_lockups.json")
    assert ipo_lockups.resolve_lockup_cfg(state, seed, under_test=True) == seed
    assert ipo_lockups.resolve_lockup_cfg(state, seed, under_test=False) == seed
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("{}", encoding="utf-8")
    try:
        assert ipo_lockups.resolve_lockup_cfg(state, seed, under_test=False) == state
        assert ipo_lockups._under_test() is True
        assert ipo_lockups._cfg_path() == ipo_lockups._CFG
    finally:
        state.unlink(missing_ok=True)


def test_hermes_weights_write_goes_to_the_state_root(no_psycopg2, tmp_path, monkeypatch):
    from scripts.lib.hermes_discovery import feedback as fb

    checkout = tmp_path / "release" / "data" / "runtime" / "hermes_discovery_weights.json"
    checkout.parent.mkdir(parents=True)
    checkout.write_text(json.dumps({
        "version": "discovery-weights-v1", "source_deltas": {"feed": 0.1}, "trend_deltas": {},
    }), encoding="utf-8")
    state = tmp_path / "persistent" / "data" / "runtime" / "hermes_discovery_weights.json"
    monkeypatch.setattr(fb, "_CHECKOUT_WEIGHTS", checkout)
    monkeypatch.setattr(fb, "weights_path", lambda: state)
    fb.apply_weight_delta(source_domain="feed", delta=0.05)
    assert json.loads(checkout.read_text())["source_deltas"]["feed"] == 0.1
    assert json.loads(state.read_text())["source_deltas"]["feed"] == 0.15
    assert fb.resolve_weights_path(under_test=False, state_root=tmp_path / "persistent", checkout=checkout) == state
    assert fb.resolve_weights_path(under_test=True, state_root=tmp_path / "persistent", checkout=checkout) == checkout


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_siem_notifier_skips_n8n_bridge_rows_and_pages_the_rest(monkeypatch, tmp_path):
    import siem_critical_notify as scn
    from scripts.lib.n8n_siem_bridge import COMPONENT_PREFIX

    assert scn.N8N_BRIDGE_PREFIX == COMPONENT_PREFIX == "n8n:"
    monkeypatch.setattr(scn, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(scn, "STATE", tmp_path / "siem_notified.json")
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {"severity": "P1", "component": "n8n:expected_services/tradeai-phone-status.service",
         "event_type": "INACTIVE", "last": now, "events": 4, "groups": 1},
        {"severity": "P0", "component": "disk", "event_type": "FULL", "last": now, "events": 2, "groups": 1},
        {"severity": "P1", "component": "n8n", "event_type": "OTHER", "last": now, "events": 1, "groups": 1},
    ]
    assert [c["component"] for c in scn.select_incidents(rows)] == ["disk", "n8n"]
    sent: list[str] = []
    monkeypatch.setattr(scn, "_send", lambda msg: sent.append(msg) or True)

    def urlopen(url, timeout=0):
        return _Resp(json.dumps({"data": {"correlated": rows}}).encode())

    monkeypatch.setattr(scn.urllib.request, "urlopen", urlopen)
    assert scn.main() == 0
    assert len(sent) == 2
    assert all(not msg.startswith("🚨 SIEM P1: n8n:") for msg in sent)
    assert any("disk" in msg for msg in sent)
    assert any("SIEM P1: n8n —" in msg for msg in sent)


def test_alert_send_and_telegram_flags_are_sender_tokens():
    from scripts.lib.lane_dispatch import _command_fields, forbidden_text_hits

    assert "alert" in forbidden_text_hits("$PY scripts/audit_enrichment_coverage.py --alert")
    assert "send" in forbidden_text_hits("$PY scripts/x.py --send")
    assert "telegram" in forbidden_text_hits("$PY scripts/x.py --telegram")
    assert "telegram" in forbidden_text_hits("$PY scripts/x.py --telegram-summary")
    assert forbidden_text_hits("$PY scripts/system_health_alerts.py") == []
    assert forbidden_text_hits("$PY scripts/momentum_alerts.py") == []
    assert "alert" not in forbidden_text_hits("$PY scripts/x.py --alerts")
    reg = json.loads((ROOT / "config/lane_registry.json").read_text(encoding="utf-8"))
    row = next(r for r in reg["lanes"] if r["lane_id"] == "audit-enrichment-coverage")
    texts = [text for _, text in _command_fields(row, allowlist_argv={})]
    assert not any("--alert" in text for text in texts)
