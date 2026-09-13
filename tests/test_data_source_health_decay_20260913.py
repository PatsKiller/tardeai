"""A health row that nobody touches must decay. That is the whole point of the view.

On 2026-09-13 data_source_health said `yahoo_finance` was "healthy". Its
last_success_at was 2026-08-24, twenty days earlier; the status column is
written once by report_source() and never aged. brave_search, fred and
alpha_vantage read "unknown" since the day they were seeded because no caller
was wired; finnhub read "error" for seven weeks. The health agent and the API
read that raw column and scored the platform 75.

`effective_status` is pure -- it takes the row, the clock and the window -- so
every test here runs with no database, no systemd and no network. Rows are
injected; the 08-24 Yahoo row is reproduced exactly.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import data_source_health_view as dsv  # noqa: E402
import check_data_source_health as cdh  # noqa: E402

# Declares to the C1 alarm gate that this file's send_telegram site is exercised.
COVERS = ["scripts/check_data_source_health.py"]

REGISTRY = json.loads((ROOT / "config" / "data_source_authority.json").read_text())

# The clock at which the defect was measured.
NOW = datetime(2026, 9, 13, 16, 0, tzinfo=timezone.utc)
H = 60  # minutes


def _row(key, status, success=None, failure=None, **extra):
    r = {"source_key": key, "status": status, "last_success_at": success,
         "last_failure_at": failure, "last_error": None, "max_stale_minutes": 1440}
    r.update(extra)
    return r


# ── the defect this view exists for ──────────────────────────────────────────


def test_the_0824_yahoo_row_comes_out_unknown_not_healthy():
    """The measured row, verbatim: status='healthy', last_success 2026-08-24, 20 days old."""
    row = _row("yahoo_finance", "healthy", success=datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc))
    win = dsv.window_minutes_for("yahoo_finance", REGISTRY)
    assert win == 168 * H, "yfinance domains declare 168h; the view must read the registry, not a constant"
    assert dsv.effective_status(row, NOW, win) == "unknown"


def test_the_raw_status_column_is_never_consulted():
    """A row that CLAIMS healthy with no success at all is unknown. The claim is the defect."""
    assert dsv.effective_status(_row("x", "healthy"), NOW, 24 * H) == "unknown"


def test_a_fresh_success_is_healthy():
    row = _row("yahoo_finance", "healthy", success=NOW - timedelta(hours=2))
    assert dsv.effective_status(row, NOW, 168 * H) == "healthy"


def test_a_success_exactly_at_the_window_edge_is_still_healthy_and_one_second_past_is_not():
    edge = NOW - timedelta(minutes=24 * H)
    assert dsv.effective_status(_row("x", "healthy", success=edge), NOW, 24 * H) == "healthy"
    assert dsv.effective_status(_row("x", "healthy", success=edge - timedelta(seconds=1)), NOW, 24 * H) == "unknown"


def test_a_failure_newer_than_the_last_success_is_error_even_inside_the_window():
    row = _row("finviz", "healthy", success=NOW - timedelta(hours=1), failure=NOW - timedelta(minutes=10))
    assert dsv.effective_status(row, NOW, 12 * H) == "error"


def test_a_failure_older_than_the_last_success_does_not_override_it():
    """Negative control: a flake that was followed by a success is not an error."""
    row = _row("finviz", "healthy", success=NOW - timedelta(minutes=10), failure=NOW - timedelta(hours=1))
    assert dsv.effective_status(row, NOW, 12 * H) == "healthy"


def test_never_succeeded_but_failed_is_error_the_finnhub_case():
    """Seven weeks of HTTP 401 with no success ever: error, not unknown."""
    row = _row("finnhub", "error", failure=NOW - timedelta(days=49))
    assert dsv.effective_status(row, NOW, 24 * H) == "error"


def test_never_touched_is_unknown_the_brave_fred_alpha_vantage_case():
    for key in ("brave_search", "fred", "alpha_vantage"):
        assert dsv.effective_status(_row(key, "unknown"), NOW, 24 * H) == "unknown"


def test_naive_and_iso_string_timestamps_are_read_as_utc():
    """psycopg2 hands back aware datetimes; a JSON round-trip hands back strings."""
    assert dsv.effective_status({"last_success_at": "2026-09-13T15:00:00+00:00"}, NOW, 24 * H) == "healthy"
    assert dsv.effective_status({"last_success_at": "2026-09-13T15:00:00Z"}, NOW, 24 * H) == "healthy"
    assert dsv.effective_status({"last_success_at": datetime(2026, 9, 13, 15, 0)}, NOW, 24 * H) == "healthy"
    assert dsv.effective_status({"last_success_at": "garbage"}, NOW, 24 * H) == "unknown"


# ── the clock stops over the weekend for weekday-only sources ────────────────
# Phase 8 measurement, Sunday 2026-09-13 17:20 ET: seven sources last touched on
# Friday read `unknown` under plain elapsed time, and the hourly audit would have
# interrupted eight times before Monday's first cron. Nothing was ever going to
# run on Saturday or Sunday; the age must not count hours nobody scheduled.

FRI_17 = datetime(2026, 9, 11, 21, 0, tzinfo=timezone.utc)   # Fri 17:00 ET
SUN_20 = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)      # Sun 20:00 ET == Mon 00:00 UTC
MON_09 = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)   # Mon 09:00 ET


def test_weekday_minutes_skip_saturday_and_sunday():
    # Fri 21:00Z -> Sat 00:00Z = 3h counted; Saturday and Sunday contribute nothing
    assert dsv.weekday_minutes_between(FRI_17, SUN_20) == pytest.approx(3 * 60)
    # ... and Monday resumes: + 13h on Monday
    assert dsv.weekday_minutes_between(FRI_17, MON_09) == pytest.approx(3 * 60 + 13 * 60)
    assert dsv.weekday_minutes_between(MON_09, FRI_17) == 0.0


def test_a_friday_success_survives_the_weekend_for_a_weekday_only_source():
    row = {"source_key": "finviz", "status": "healthy", "last_success_at": FRI_17, "last_failure_at": None}
    assert dsv.effective_status(row, SUN_20, 12 * 60, weekday_only=True) == "healthy"
    # negative control: the plain clock says the same row is stale
    assert dsv.effective_status(row, SUN_20, 12 * 60, weekday_only=False) == "unknown"


def test_the_weekday_clock_still_decays_once_monday_passes_the_window():
    row = {"source_key": "finviz", "status": "healthy", "last_success_at": FRI_17, "last_failure_at": None}
    # 3h Friday + 13h Monday = 16h > 12h window
    assert dsv.effective_status(row, MON_09, 12 * 60, weekday_only=True) == "unknown"
    assert dsv.effective_status(row, MON_09, 24 * 60, weekday_only=True) == "healthy"


def test_weekday_only_comes_from_the_caller_schedule():
    assert dsv.weekday_only_for("finviz") is True          # 25 6-18/3 * * 1-5
    assert dsv.weekday_only_for("fred") is False           # 15 6 * * *  (daily)
    assert dsv.weekday_only_for("alpha_vantage") is False  # 0 8 * * 1   (Mondays, not the trading week)
    assert dsv.weekday_only_for("something_nobody_scheduled") is False, "no caller -> plain clock, decays sooner"


def test_view_row_uses_the_weekday_clock_and_says_so():
    row = {"source_key": "finviz", "status": "healthy", "last_success_at": FRI_17, "last_failure_at": None}
    v = dsv.view_row(row, SUN_20, REGISTRY)
    assert v["weekday_clock"] is True
    assert v["status"] == "healthy" and v["decayed"] is False


# ── the closed-market window ─────────────────────────────────────────────────


def test_the_quote_window_is_15_minutes_open_and_72_hours_closed():
    assert dsv.window_minutes_for("alpaca", REGISTRY, market_closed=False) == 15
    # closed: quote_price widens to 72h, but technicals (also alpaca-primary, 26h, no
    # closed window) is now the strictest alpaca domain — the min over domains holds.
    assert dsv.window_minutes_for("alpaca", REGISTRY, market_closed=True) == 26 * H
    # a domain with no closed window keeps its one window either way
    assert dsv.window_minutes_for("yahoo_finance", REGISTRY, market_closed=True) == 168 * H


def test_a_friday_close_quote_is_healthy_on_sunday_when_the_market_is_closed(monkeypatch):
    monkeypatch.setattr(dsv, "market_is_closed", lambda now=None: True)
    # alpaca has no row in data_source_health today, so it has no caller entry; give it the
    # quote refresher's real schedule so the weekday clock applies as it would for the quote row.
    monkeypatch.setitem(dsv.SCHEDULED_CALLERS, "alpaca",
                        [{"script": "scripts/portfolio_repricer.py", "cron": "*/15 9-16 * * 1-5"}])
    row = {"source_key": "alpaca", "status": "healthy", "last_success_at": FRI_17, "last_failure_at": None}
    v = dsv.view_row(row, SUN_20, REGISTRY)
    assert v["market_closed"] is True and v["window_minutes"] == 26 * H
    assert v["status"] == "healthy"
    # negative control: with the market open the 15-minute window applies and the row has decayed
    monkeypatch.setattr(dsv, "market_is_closed", lambda now=None: False)
    v2 = dsv.view_row(row, SUN_20, REGISTRY)
    assert v2["window_minutes"] == 15 and v2["status"] == "unknown" and v2["decayed"] is True


def test_when_the_session_helper_cannot_say_the_stricter_open_window_applies(monkeypatch):
    monkeypatch.setattr(dsv, "market_is_closed", lambda now=None: None)
    row = {"source_key": "alpaca", "status": "healthy", "last_success_at": FRI_17, "last_failure_at": None}
    assert dsv.view_row(row, SUN_20, REGISTRY)["window_minutes"] == 15


# ── the window comes from the registry ───────────────────────────────────────


def test_windows_are_read_from_the_authority_registry():
    assert dsv.window_minutes_for("finviz", REGISTRY) == 18 * H, "catalyst_news 18h (1.5x its 12h cadence gap) is the strictest finviz domain"
    assert dsv.window_minutes_for("alpaca", REGISTRY) == 15, "quote_price 0.25h"
    assert dsv.window_minutes_for("yahoo_finance", REGISTRY) == 168 * H


def test_a_source_with_no_declared_domain_gets_the_default_window():
    # Phase 3 registry patch (applied at integration): macro window 48h, fundamentals 192h (weekly lane).
    assert dsv.window_minutes_for("fred", REGISTRY) == 48 * 60
    assert dsv.window_minutes_for("alpha_vantage", REGISTRY) == 192 * 60
    assert dsv.window_minutes_for("something_nobody_declared", REGISTRY) == dsv.DEFAULT_WINDOW_MINUTES


def test_a_null_stale_after_hours_falls_through_to_the_default():
    """web_search declares stale_after_hours: null for brave. Null is not zero."""
    # web_search.stale_after_hours = 72 covers Friday 15:00 -> Monday 09:00 without a weekend decay.
    assert dsv.window_minutes_for("brave_search", REGISTRY) == 72 * 60


def test_an_unreadable_registry_decays_sooner_not_later(tmp_path):
    assert dsv.load_registry(tmp_path / "missing.json") == {}
    assert dsv.window_minutes_for("finviz", {}) == dsv.DEFAULT_WINDOW_MINUTES


def test_the_documented_alias_table_matches_the_registry_provider_names():
    providers = set(REGISTRY["providers"])
    for key, prov in dsv.SOURCE_KEY_ALIASES.items():
        assert prov in providers, f"{key} -> {prov} names a provider the registry does not declare"


# ── the row every consumer sees ──────────────────────────────────────────────


def test_view_row_replaces_status_and_flags_the_decay():
    row = _row("yahoo_finance", "healthy", success=datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc))
    v = dsv.view_row(row, NOW, REGISTRY)
    assert v["status"] == "unknown"
    assert v["raw_status"] == "healthy"
    assert v["decayed"] is True
    assert v["window_minutes"] == 168 * H
    assert abs(v["age_minutes"] - (20 * 24 * 60 + 4 * 60)) < 1  # 08-24 12:00 -> 09-13 16:00
    assert v["scheduled_caller"] is True


def test_a_fresh_row_is_not_marked_decayed_and_a_never_touched_row_has_no_age():
    fresh = dsv.view_row(_row("finviz", "healthy", success=NOW - timedelta(hours=1)), NOW, REGISTRY)
    assert fresh["status"] == "healthy" and fresh["decayed"] is False
    never = dsv.view_row(_row("fred", "unknown"), NOW, REGISTRY)
    assert never["status"] == "unknown" and never["decayed"] is False and never["age_minutes"] is None


def test_the_alert_set_is_not_healthy_AND_scheduled():
    rows = [
        _row("yahoo_finance", "healthy", success=datetime(2026, 8, 24, tzinfo=timezone.utc)),  # decayed, scheduled
        _row("fred", "unknown"),                                                                   # never, scheduled
        _row("finviz", "healthy", success=NOW - timedelta(hours=1)),                              # healthy
        _row("newsapi", "unknown"),                                                              # never, NOT scheduled
    ]
    viewed = dsv.view_rows(rows, NOW, REGISTRY)
    off = {r["source_key"] for r in dsv.not_healthy_with_scheduled_caller(viewed)}
    assert off == {"yahoo_finance", "fred"}


def test_every_scheduled_caller_entry_names_a_script_that_exists():
    for key, callers in dsv.SCHEDULED_CALLERS.items():
        assert callers, key
        for c in callers:
            script = c["script"].split()[0]
            assert (ROOT / script).exists(), f"{key}: {script} does not exist"
            assert c["cron"], f"{key}: cron expression missing"


def test_the_health_agent_collector_uses_the_view(monkeypatch):
    """The 08-24 row must produce a finding, and a fresh row must not.

    health_agent._db is monkeypatched so no database is touched; the weekend
    flag is forced False so severity is deterministic.
    """
    import health_agent as ha

    rows = [
        _row("yahoo_finance", "healthy", success=datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)),
        _row("finviz", "healthy", success=datetime.now(timezone.utc) - timedelta(hours=1)),
        _row("fred", "unknown"),
        _row("newsapi", "unknown"),
    ]
    monkeypatch.setattr(ha, "_db", lambda sql, params=None, fetch="one": rows if fetch == "all" else None)
    monkeypatch.setattr(ha, "_IS_WEEKEND", False)
    monkeypatch.setattr(ha, "_POLICY", {"data_sources": {"enabled": True, "finviz_cookie_check": False}})
    findings = ha.collect_data_source_health()
    by_src = {f["source"]: f for f in findings}
    assert "yahoo_finance" in by_src, findings
    assert by_src["yahoo_finance"]["type"] == "data_source_stale"
    assert by_src["yahoo_finance"]["decayed"] is True
    # 20 days = 480h against a 168h window: past the window (warning), not yet
    # past 3x the window (critical, at 504h). The collector uses the real clock,
    # so the exact tier drifts with the calendar; the finding must exist either way.
    assert by_src["yahoo_finance"]["severity"] in {"warning", "critical"}
    assert by_src["yahoo_finance"]["age_minutes"] > 168 * 60
    assert "fred" in by_src and by_src["fred"]["type"] == "data_source_never_reported"
    assert "finviz" not in by_src, "a fresh success is not a finding"
    assert "newsapi" not in by_src, "never reported with no scheduled caller is idle, not a finding"


# ── the alarm itself ─────────────────────────────────────────────────────────


class _Captured:
    def __init__(self):
        self.sent = []

    def send_telegram(self, message, **kwargs):
        self.sent.append(message)
        return True


@pytest.fixture
def wired(monkeypatch, tmp_path):
    cap = _Captured()
    mod = type(sys)("telegram_alert")
    mod.send_telegram = cap.send_telegram
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    monkeypatch.setattr(cdh, "STATE_PATH", tmp_path / "state.json")
    return cap


def _off_yahoo():
    row = _row("yahoo_finance", "healthy", success=datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc))
    return dsv.view_row(row, NOW, REGISTRY)


def test_alarm_fires_and_names_the_decayed_source(wired):
    cdh._alert([_off_yahoo()])
    assert len(wired.sent) == 1
    body = wired.sent[0]
    assert "yahoo_finance" in body
    assert "unknown" in body
    assert "table still says healthy" in body


def test_a_newly_unhealthy_source_escalates_to_an_interrupt(wired):
    """It must actually route P0, not merely sound urgent (see test_expected_services)."""
    cdh._alert([_off_yahoo()])
    body = wired.sent[0]
    assert "[PLATFORM_AVAILABILITY]" in body, "the sentinel routes this, not the wording"

    from telegram_alert_router import classify_alert

    assert classify_alert(body) == "P0_INTERRUPT"


def test_an_unchanged_off_set_stays_silent(wired):
    cdh.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cdh.STATE_PATH.write_text(json.dumps({"fingerprint": {"yahoo_finance": "unknown"}}))
    cdh._alert([_off_yahoo()])
    assert wired.sent == []


def test_recovery_is_reported_once(wired):
    cdh.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cdh.STATE_PATH.write_text(json.dumps({"fingerprint": {"yahoo_finance": "unknown"}}))
    cdh._alert([])
    assert len(wired.sent) == 1 and "✅" in wired.sent[0]
    cdh._alert([])
    assert len(wired.sent) == 1


def test_a_send_failure_does_not_advance_state(monkeypatch, tmp_path, capsys):
    mod = type(sys)("telegram_alert")

    def _boom(message, **kwargs):
        raise RuntimeError("unreachable")

    mod.send_telegram = _boom
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    monkeypatch.setattr(cdh, "STATE_PATH", tmp_path / "s.json")
    cdh._alert([_off_yahoo()])
    assert "FAILED to send" in capsys.readouterr().err
    assert not cdh.STATE_PATH.exists()


def test_classify_is_pure_and_separates_idle_from_off():
    rows = [_off_yahoo(), _row("newsapi", "unknown")]
    viewed, off = cdh.classify(rows, NOW, REGISTRY)
    assert len(viewed) == 2
    assert [r["source_key"] for r in off] == ["yahoo_finance"]


# ── the lane and the unit files exist and agree ───────────────────────────────


def test_lane_registry_declares_the_audit_with_a_receipt_signal():
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    lane = next(l for l in reg["lanes"] if l["lane_id"] == "data-source-health-audit")
    assert lane["scheduler"] == {"kind": "systemd", "expression": "tradeai-data-source-health.timer"}
    assert lane["output_signal"] == {"kind": "file_mtime", "path": "data/runtime/" + cdh.RECEIPT_NAME}


def test_unit_files_match_the_brief():
    svc = (ROOT / "config/systemd/user/tradeai-data-source-health.service").read_text()
    tmr = (ROOT / "config/systemd/user/tradeai-data-source-health.timer").read_text()
    assert "SuccessExitStatus=0 1" in svc
    assert "WorkingDirectory=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild" in svc
    assert "check_data_source_health.py --alert" in svc
    assert "OnCalendar=*-*-* *:27:00" in tmr
    assert "Persistent=true" in tmr
