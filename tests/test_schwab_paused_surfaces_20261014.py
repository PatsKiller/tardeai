"""Schwab paused (incident 2026-10-14) — A status surfaces, C cache-not-live, D datetime freshness,
E paused/auth ingest notice, F market hours UNKNOWN, G health-agent remediation text.

Every test simulates the pause (TRADEAI_SCHWAB_ACCESS_MODE=forbidden) or a 401 with fakes. A Schwab transport
module that raises on import-use proves no Schwab call is made. No database, no broker, no Telegram.
"""
from __future__ import annotations

import io
import json
import sys
import types
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import schwab_access_mode as sam  # noqa: E402

# COVERS declares alarm-firing coverage only (scripts/lib/alarm_firing_coverage.py). These tests exercise
# api_v2, audit_position_basis, sync_basis_from_broker, schwab_position_sync, portfolio_aggregate_contract,
# schwab_transaction_ingest, pipeline_freshness_slo, paper_monitor_ops, health_agent and SchwabReauthBanner,
# but none of them fires a send_telegram site through the real transport, so none is claimed.
COVERS: list[str] = []
ET = ZoneInfo("America/New_York")


class _NoSchwab(types.ModuleType):
    """Any attribute use = a Schwab call that must not happen while paused."""

    def __getattr__(self, name):
        raise AssertionError(f"Schwab was called while paused: schwab_transport.{name}")


@pytest.fixture(autouse=True)
def _fresh_alert_day_state(monkeypatch, tmp_path):
    """The once-per-day notice state is durable by design; every test starts on a fresh day."""
    monkeypatch.setenv("TRADEAI_SCHWAB_PAUSED_ALERT_STATE", str(tmp_path / "alert_days.json"))


@pytest.fixture
def paused(monkeypatch):
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "forbidden")
    monkeypatch.setitem(sys.modules, "schwab_transport", _NoSchwab("schwab_transport"))
    sam._logged.clear()


class _Cur:
    def __init__(self, answers):
        self.answers, self.last = answers, ""

    def execute(self, sql, *a):
        self.last = sql

    def fetchall(self):
        return next((v for k, v in self.answers.items() if k in self.last), [])

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else (0,)


def _fake_db(monkeypatch, answers):
    cur = _Cur(answers)
    conn = types.SimpleNamespace(cursor=lambda *a, **k: cur, commit=lambda: None, rollback=lambda: None)
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
    return cur


# ── A: status surfaces + banner ─────────────────────────────────────────────

def test_access_fields_say_paused_and_do_not_reauth(monkeypatch):
    import api_v2
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "forbidden")
    f = api_v2._schwab_access_fields()
    assert f["schwab_access_mode"] == "forbidden" and f["schwab_paused"] is True
    assert "do not re-auth" in f["schwab_paused_message"]
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "normal")
    assert api_v2._schwab_access_fields()["schwab_paused"] is False


def test_schwab_status_route_exposes_the_mode(monkeypatch):
    import api_v2
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "forbidden")
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: [])
    out = api_v2._schwab_status()
    assert out["schwab_access_mode"] == "forbidden" and out["schwab_paused"] is True


def test_token_health_source_skips_the_live_probe_while_paused():
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    body = src[src.index("def _schwab_token_health"):]
    body = body[:body.index("\ndef ")]
    assert 'if _access["schwab_paused"]:\n        probe = None' in body and "**_access" in body


def test_banner_renders_paused_without_a_reauth_link():
    tsx = (ROOT / "apps/command-center-v3/src/components/SchwabReauthBanner.tsx").read_text()
    paused_block = tsx[tsx.index("health.schwab_paused ||"):tsx.index("const hard =")]
    assert "Schwab paused" in paused_block and "Renew now" not in paused_block and "/system/schwab-reauth" not in paused_block


# ── C: accounts-live labels the cache; basis tools refuse self-comparison ────

def _accounts_live(monkeypatch, *, sync_status="ok"):
    import api_v2
    from lib.data_broker import market_quote
    api_v2._SCHWAB_LIVE_CACHE.clear()
    holdings = {"holdings": [{"account": "schwab_taxable", "symbol": "NVDA", "shares": 10, "cost_basis": 1000,
                              "broker_position_as_of": "2026-10-14",
                              "broker_position_as_of_at": "2026-10-14T18:52:00+00:00"}]}
    monkeypatch.setattr(api_v2, "_load_json", lambda p: holdings)

    def _q(sql, *a, **k):
        if "broker_accounts" in sql:
            return [{"account_key": "schwab_taxable"}]
        if "schwab_sync_history" in sql:
            return [{"account_key": "schwab_taxable", "status": sync_status, "reason": "x", "created_at": None}]
        return []
    monkeypatch.setattr(api_v2, "_db_query", _q)
    monkeypatch.setattr(market_quote, "get_price_batch", lambda *a, **k: {})
    return api_v2._schwab_accounts_live()


def test_accounts_live_is_stale_cache_when_paused(monkeypatch):
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "forbidden")
    out = _accounts_live(monkeypatch)
    a = out["accounts"][0]
    assert a["positions_status"] == "stale" and a["source"] == "cache"
    assert a["as_of"] == "2026-10-14T18:52:00+00:00"           # a datetime, not a date
    assert out["schwab_paused"] is True


def test_accounts_live_is_stale_when_the_last_sync_failed_401(monkeypatch):
    out = _accounts_live(monkeypatch, sync_status="degraded_noop")
    assert out["accounts"][0]["positions_status"] == "stale"


def test_accounts_live_ok_after_a_good_sync(monkeypatch):
    out = _accounts_live(monkeypatch, sync_status="ok")
    assert out["accounts"][0]["positions_status"] == "ok" and out["accounts"][0]["source"] == "cache"


def test_audit_refuses_when_paused(paused, monkeypatch, capsys):
    import audit_position_basis as apb
    monkeypatch.setattr(sys, "argv", ["audit_position_basis.py", "--alert"])
    out = apb.main()
    assert out["status"].startswith("BROKER_SOURCE_UNAVAILABLE") and out["flagged"] == 0


def test_audit_never_takes_the_cache_as_the_broker(monkeypatch, capsys, tmp_path):
    import urllib.request

    import audit_position_basis as apb
    monkeypatch.setattr(sys, "argv", ["audit_position_basis.py"])
    hj = tmp_path / "data/portfolios/state/holdings.json"
    hj.parent.mkdir(parents=True)
    hj.write_text(json.dumps(
        {"holdings": [{"account": "schwab_taxable", "symbol": "NVDA", "shares": 10, "cost_basis": 1000}]}))
    monkeypatch.setattr(apb, "PROJECT_ROOT", tmp_path)
    monkeypatch.setitem(sys.modules, "schwab_transport", types.SimpleNamespace(
        get_positions=lambda ak: {"status": "error", "error": "HTTP 401"}))
    _fake_db(monkeypatch, {"broker_accounts": [("schwab_taxable",)]})
    cache = {"accounts": [{"account_key": "schwab_taxable", "positions_status": "ok", "source": "cache",
                           "positions": [{"symbol": "NVDA", "qty": 10, "avg_entry_price": 100.0,
                                          "market_value": 1500.0}]}]}
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(json.dumps(cache).encode()))
    out = apb.main()
    assert out["status"].startswith("BROKER_SOURCE_UNAVAILABLE")   # was: a false "0 flagged, all clean"


def test_sync_basis_skips_when_paused(paused, monkeypatch, capsys):
    import sync_basis_from_broker as sb
    _fake_db(monkeypatch, {})
    monkeypatch.setattr(sys, "argv", ["sync_basis_from_broker.py", "--apply"])
    out = sb.main()
    assert out == {"status": "BROKER_SOURCE_UNAVAILABLE", "reason": "schwab_paused"}
    assert "BROKER_SOURCE_UNAVAILABLE" in capsys.readouterr().out


def test_sync_basis_rejects_cache_accounts():
    import sync_basis_from_broker as sb
    assert not sb._server_account_is_live({"positions_status": "ok", "source": "cache"})
    assert not sb._server_account_is_live({"positions_status": "ok"})
    assert sb._server_account_is_live({"positions_status": "ok", "source": "schwab_api"})


# ── D: datetime freshness stamp ─────────────────────────────────────────────

def test_position_rows_carry_a_datetime_stamp(monkeypatch):
    import schwab_position_sync as sps
    monkeypatch.setitem(sys.modules, "share_reconciliation", types.SimpleNamespace(
        stamp_broker_qty=lambda prior, qty, **k: ({"shares": qty, "broker_actual_shares": qty}, None)))
    rows, _ = sps._build_account_rows("schwab_taxable", [{"symbol": "NVDA", "qty": 10, "market_value": 1500}], {})
    r = rows[0]
    assert len(r["broker_position_as_of"]) == 10                       # legacy date-only, unchanged
    assert "T" in r["broker_position_as_of_at"] and r["broker_position_as_of_at"].startswith(r["broker_position_as_of"])
    cash = sps._cash_rows_for_account("schwab_taxable", [], "schwab_taxable",
                                      types.SimpleNamespace(get_account=lambda ak: {"status": "active", "cash": 5}))
    assert "T" in cash[0]["broker_position_as_of_at"]


def test_aggregate_observation_prefers_the_datetime_stamp():
    from lib import portfolio_aggregate_contract as pac
    raw, field = pac._oldest_row_observation([
        {"broker_position_as_of": "2026-10-14", "broker_position_as_of_at": "2026-10-14T18:52:00+00:00"}])
    assert raw == "2026-10-14T18:52:00+00:00" and field == "holdings.broker_position_as_of_at"
    raw, field = pac._oldest_row_observation([{"broker_position_as_of": "2026-10-13"}])   # legacy rows still read
    assert raw == "2026-10-13" and field == "holdings.broker_position_as_of"


def test_position_sync_skips_schwab_when_paused(paused, monkeypatch):
    import schwab_position_sync as sps
    rec = []
    monkeypatch.setattr(sps, "_record", lambda *a, **k: rec.append(a))
    out = sps.sync_schwab_positions("schwab_taxable", dry_run=False)
    assert out == {"status": "degraded_noop", "reason": "schwab_paused", "wrote": False}
    assert rec and rec[0][1] == "degraded_noop" and rec[0][2].startswith("schwab_paused")


# ── E: one "Schwab paused/auth failure" notice per day, not "empty weekday ingest" ──

def _ingest_alerts(monkeypatch):
    sent = []
    monkeypatch.setitem(sys.modules, "alert_event_writer", types.SimpleNamespace(
        save_alert_event=lambda **k: sent.append(k)))
    return sent


def test_ingest_paused_reports_once_per_day(paused, monkeypatch, capsys):
    import schwab_transaction_ingest as sti
    sent = _ingest_alerts(monkeypatch)
    for _ in range(3):                                    # three 15-minute cron runs
        rep = sti.run(apply=True)
        assert rep["mode"] == "schwab_paused"
    assert len(sent) == 1 and "Schwab paused" in sent[0]["raw_text"]
    assert "empty weekday" not in sent[0]["raw_text"]


def test_ingest_401_is_an_auth_notice_once_per_day(monkeypatch):
    import schwab_transaction_ingest as sti
    sent = _ingest_alerts(monkeypatch)
    rep = {"accounts": {ak: {"error": "Schwab rejected the login token (HTTP 401)"} for ak in sti.ACCOUNTS},
           "rows_total": 0}
    sti._emit_health_alert(rep)
    sti._emit_health_alert(rep)
    assert len(sent) == 1 and "Schwab paused/auth failure" in sent[0]["raw_text"]


def test_position_sync_paused_notice_once_per_day(monkeypatch):
    import schwab_position_sync as sps
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "forbidden")
    sent = []
    send = lambda text, **k: sent.append((text, k))   # noqa: E731
    res = {ak: {"status": "degraded_noop", "reason": "schwab_paused"} for ak in ("a", "b", "c")}
    assert sps.report_paused_or_auth(res, send=send)
    assert sps.report_paused_or_auth(res, send=send) is None
    assert len(sent) == 1 and sent[0][1]["priority"] == "P2" and "Schwab paused" in sent[0][0]
    mixed = {"a": {"status": "ok"}, "b": {"status": "degraded_noop", "reason": "401"}}
    assert sps.report_paused_or_auth(mixed, send=send) is None


# ── F: market hours UNKNOWN, not "closed" ───────────────────────────────────

@pytest.mark.parametrize("answer,expected", [
    (RuntimeError("401 Unauthorized"), "UNKNOWN"),
    ({"status": "error", "error": "HTTP 401"}, "UNKNOWN"),
    ({"markets": {"equity": {"is_open": False}}}, "CLOSED"),
    ({"markets": {"equity": {"is_open": True}}}, "OPEN"),
])
def test_market_state(monkeypatch, answer, expected):
    import pipeline_freshness_slo as pfs

    def get_market_hours():
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setitem(sys.modules, "schwab_transport", types.SimpleNamespace(get_market_hours=get_market_hours))
    assert pfs._market_state() == expected


def test_unknown_is_treated_conservatively(paused, monkeypatch):
    import pipeline_freshness_slo as pfs
    assert pfs._market_state() == "UNKNOWN"
    assert pfs._clock_session_open(datetime(2026, 10, 14, 11, 0, tzinfo=ET))
    assert not pfs._clock_session_open(datetime(2026, 10, 17, 11, 0, tzinfo=ET))   # Saturday
    monkeypatch.setattr(pfs, "_clock_session_open", lambda now=None: True)
    assert pfs._market_open() is True                     # was False ("closed") on any Schwab error


def test_slo_run_marks_schwab_fed_checks_paused_not_critical(paused, monkeypatch, capsys):
    import pipeline_freshness_slo as pfs
    _fake_db(monkeypatch, {})
    monkeypatch.setattr(pfs, "CHECKS", [])
    monkeypatch.setattr(pfs, "_clock_session_open", lambda now=None: True)
    out = pfs.run(telegram=False)
    assert out["market_state"] == "UNKNOWN" and out["market_checks_included"] is True
    st = {c["check"]: c["status"] for c in out["checks"]}
    assert st["schwab_stream_book_2h"] == "SCHWAB_PAUSED" and not out["findings"]


def test_paper_monitor_market_hours_never_calls_schwab_when_paused(paused):
    from lib.options_pipeline import paper_monitor_ops as pmo
    assert isinstance(pmo.is_market_hours(), bool)


# ── G: health agent says "deactivated by operator — do not re-auth", once a day ──

def test_health_agent_paused_remediation_once_per_day(monkeypatch):
    import health_agent as ha
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "forbidden")
    monkeypatch.setattr(ha, "_db", lambda *a, **k: [{"account_key": "schwab_taxable", "degraded": True,
                                                      "last_error": "Schwab rejected the login token (HTTP 401)"}])
    first = ha.collect_broker_token_health()[0]
    second = ha.collect_broker_token_health()[0]
    assert first["type"] == "schwab_token_revoked" and first["severity"] == "critical"
    assert sam.PAUSED_REMEDIATION in first["message"] and first["reauth_cmd"] == sam.PAUSED_REMEDIATION
    assert "reauth-url" not in first["message"]
    assert second["severity"] == "info"


def test_health_agent_normal_mode_keeps_the_reauth_remedy(monkeypatch):
    import health_agent as ha
    monkeypatch.setattr(ha, "_db", lambda *a, **k: [{"account_key": "schwab_taxable", "degraded": True,
                                                      "last_error": "HTTP 401"}])
    f = ha.collect_broker_token_health()[0]
    assert f["severity"] == "critical" and "reauth-url" in f["message"]
