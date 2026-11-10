"""LQ-20261107-1625 — an old Form 4 is not an urgent insider buy, and one accession fires once.

The check used to select ``sec_form4`` on ``created_at`` and dedupe on (event type, symbol) for
4 hours. A backfill inserts an old filing with a fresh ``created_at``, the cooldown expires, and
the next slot pages urgent again. Urgent now requires a filing date inside the configured ceiling
and an accession parsed from ``sec_url``. The same accession does not fire twice in one run, and
it does not fire again when the queue already holds it.

Synthetic only: no database, no network, no send. The symbol, filer, accession and share numbers
below are fixtures.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "event_detector.py"
TODAY = date(2026, 11, 10)
ACCESSION = "0000000001-26-000001"
BARE = "000000000126000001"
URL = f"https://www.sec.gov/Archives/edgar/data/1/{BARE}/synthetic.xml"


def _load():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("event_detector_1625", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ev():
    return _load()


def _row(
    *,
    symbol: str = "SYNOLD",
    filing_date=TODAY,
    url: str = URL,
    accession_digits: str = BARE,
):
    if url is None:
        sec_url = ""
    elif url == URL and accession_digits != BARE:
        sec_url = f"https://www.sec.gov/Archives/edgar/data/1/{accession_digits}/synthetic.xml"
    else:
        sec_url = url
    return {
        "symbol": symbol,
        "filer_name": "Synthetic Filer",
        "filer_relation": "synthetic",
        "transaction_type": "P",
        "shares": 10,
        "price": 2.5,
        "total_value": 25.0,
        "filing_date": filing_date,
        "sec_url": sec_url,
    }


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.sql = ""
        self.params = None

    def execute(self, sql, params=None):
        self.sql = " ".join(sql.split())
        self.params = params
        self.conn.executed.append((self.sql, params))

    def fetchall(self):
        if "FROM sec_form4" in self.sql:
            return list(self.conn.rows)
        return []

    def fetchone(self):
        if "trigger_data" in self.sql and self.params is not None:
            event_type, symbol, accession = self.params
            if (event_type, symbol, accession) in self.conn.queued:
                return {"id": 1}
            return None
        return None


class _Conn:
    def __init__(self, rows, queued=()):
        self.rows = list(rows)
        self.queued = set(queued)
        self.executed = []
        self.commits = 0

    def cursor(self, cursor_factory=None):
        return _Cursor(self)

    def commit(self):
        self.commits += 1

    @property
    def inserts(self):
        return [params for sql, params in self.executed if sql.startswith("INSERT")]


def _pin_today(ev, monkeypatch, today=TODAY):
    monkeypatch.setattr(ev, "_today_et", lambda: today)


def _fire(ev, monkeypatch, rows, queued=(), dry_run=False):
    _pin_today(ev, monkeypatch)
    conn = _Conn(rows, queued)
    fired = ev.check_sec_insider_buy(conn, dry_run=dry_run)
    return fired, conn


def test_accession_comes_from_the_url_bare_or_dashed(ev):
    assert ev.filing_accession(URL) == ACCESSION
    dashed = "https://www.sec.gov/Archives/edgar/data/1/0000000001-26-000001/synthetic.xml"
    assert ev.filing_accession(dashed) == ACCESSION
    assert ev.filing_accession("https://example.invalid/no-accession") == ""
    assert ev.filing_accession("") == ""
    assert ev.filing_accession(None) == ""
    assert ev.filing_accession("https://example.invalid/0000000001260000019/x") == ""


def test_a_months_old_filing_does_not_fire(ev, monkeypatch):
    """Ingest can be recent. The filing date is what the ceiling reads."""
    fired, conn = _fire(ev, monkeypatch, [_row(filing_date=date(2026, 2, 17))])
    assert fired == 0
    assert conn.inserts == []
    assert conn.commits == 0
    select = [params for sql, params in conn.executed if "FROM sec_form4" in sql]
    assert select[0][0] == date(2026, 11, 3)


def test_the_boundary_is_the_configured_seven_days(ev, monkeypatch):
    fired, conn = _fire(ev, monkeypatch, [_row(filing_date=date(2026, 11, 3))])
    assert fired == 1
    assert len(conn.inserts) == 1
    payload = json.loads(conn.inserts[0][2])
    assert payload["accession"] == ACCESSION
    assert payload["filing_date"] == "2026-11-03"
    assert conn.inserts[0][4] == "urgent"

    fired, conn = _fire(ev, monkeypatch, [_row(filing_date=date(2026, 11, 2))])
    assert fired == 0 and conn.inserts == []


def test_a_future_filing_date_does_not_fire(ev, monkeypatch):
    fired, conn = _fire(ev, monkeypatch, [_row(filing_date=date(2026, 11, 11))])
    assert fired == 0 and conn.inserts == []


def test_a_datetime_filing_date_uses_its_calendar_day(ev, monkeypatch):
    fired, conn = _fire(
        ev, monkeypatch, [_row(filing_date=datetime(2026, 11, 10, 22, 0, 0))]
    )
    assert fired == 1 and len(conn.inserts) == 1


def test_two_rows_of_one_accession_fire_once_even_when_the_cooldown_is_empty(ev, monkeypatch):
    rows = [
        _row(),
        _row(filing_date=date(2026, 11, 9)),
    ]
    fired, conn = _fire(ev, monkeypatch, rows)
    assert fired == 1
    assert len(conn.inserts) == 1
    identity = [params for sql, params in conn.executed if "trigger_data->>" in sql]
    assert identity == [("SEC_INSIDER_BUY", "SYNOLD", ACCESSION)]


def test_an_accession_already_queued_does_not_fire_again(ev, monkeypatch):
    fired, conn = _fire(
        ev,
        monkeypatch,
        [_row()],
        queued={("SEC_INSIDER_BUY", "SYNOLD", ACCESSION)},
    )
    assert fired == 0
    assert conn.inserts == []
    assert conn.commits == 0


def test_a_row_with_no_accession_does_not_fire(ev, monkeypatch):
    fired, conn = _fire(ev, monkeypatch, [_row(url="")])
    assert fired == 0 and conn.inserts == []
    assert not any("trigger_data->>" in sql for sql, _ in conn.executed)


def test_a_null_filing_date_does_not_fire(ev, monkeypatch):
    fired, conn = _fire(ev, monkeypatch, [_row(filing_date=None)])
    assert fired == 0 and conn.inserts == []


def test_a_string_filing_date_does_not_fire(ev, monkeypatch):
    fired, conn = _fire(ev, monkeypatch, [_row(filing_date="2026-11-10")])
    assert fired == 0 and conn.inserts == []


def test_a_dry_run_of_a_fresh_filing_fires_and_inserts_nothing(ev, monkeypatch):
    fired, conn = _fire(ev, monkeypatch, [_row()], dry_run=True)
    assert fired == 1
    assert conn.inserts == []
    assert conn.commits == 0


def test_the_ceiling_is_read_from_the_policy_file(ev, tmp_path, monkeypatch):
    policy = tmp_path / "event_detector_policy.json"
    policy.write_text(json.dumps({"sec_insider_buy": {"max_filing_age_days": 1}}))
    monkeypatch.setattr(ev, "POLICY_PATH", policy)
    fresh, fresh_conn = _fire(ev, monkeypatch, [_row(filing_date=date(2026, 11, 9))])
    stale, stale_conn = _fire(ev, monkeypatch, [_row(filing_date=date(2026, 11, 8))])
    assert fresh == 1 and len(fresh_conn.inserts) == 1
    assert stale == 0 and stale_conn.inserts == []


def test_the_shipped_policy_is_seven_days_and_the_regime_lag_stays_zero(ev):
    assert ev.insider_buy_policy()["max_filing_age_days"] == 7
    assert ev.FILING_MAX_AGE_DAYS_DEFAULT == 7
    assert ev.regime_policy()["max_observation_lag_sessions"] == 0
    doc = json.loads((ROOT / "config" / "event_detector_policy.json").read_text())
    assert doc["schema"] == "EventDetectorPolicy@v1"
    assert doc["sec_insider_buy"]["max_filing_age_days"] == 7
    assert doc["regime"]["max_observation_lag_sessions"] == 0


def test_an_unusable_policy_falls_back_to_seven_and_does_not_fall_open(ev, tmp_path, monkeypatch):
    bad = tmp_path / "event_detector_policy.json"
    monkeypatch.setattr(ev, "POLICY_PATH", bad)
    assert ev.insider_buy_policy()["max_filing_age_days"] == 7

    bad.write_text(json.dumps({"sec_insider_buy": {"max_filing_age_days": "7"}}))
    assert ev.insider_buy_policy()["max_filing_age_days"] == 7

    bad.write_text(json.dumps({"sec_insider_buy": {"max_filing_age_days": True}}))
    assert ev.insider_buy_policy()["max_filing_age_days"] == 7

    bad.write_text(json.dumps({"sec_insider_buy": {"max_filing_age_days": -1}}))
    assert ev.insider_buy_policy()["max_filing_age_days"] == 7

    bad.write_text("{not json")
    assert ev.insider_buy_policy()["max_filing_age_days"] == 7
