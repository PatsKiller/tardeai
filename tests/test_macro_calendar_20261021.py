"""Macro calendar for the release train's 08:00 ET window (operator ruling 2026-10-21): FRED primary, a yearly
overrides file (FOMC + operator add/remove), n8n-managed refresh, the host controller decides, fail closed.

Covers scripts/macro_calendar_refresh.py (FRED id verification, paging, mapping, coverage, override merge, atomic
write, dry run), scripts/lib/macro_calendar.py (skip_0800 / verdict / ReleaseTrainCalendar: missing, corrupt, stale,
uncovered, Thursday claims, CPI day, DST), the needs-action source ``macro_calendar`` and the n8n SHADOW lane
``macro-calendar-refresh`` (registry row, allowlist, DRAFT contract, closure).

Hermetic: FRED is a canned fake at the fetcher seam and ``urllib.request.urlopen`` raises for the whole module, so
nothing here can reach the network. Tmp state roots only. The fixture release dates are SYNTHETIC (shaped like the
real schedules, not copied from FRED).
"""
from __future__ import annotations

import json
import sys
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:  # CI runners have no driver; a minimal stand-in only when the real one is absent (never shadows it)
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on the runner
    _pg = types.ModuleType("psycopg2")
    _pg.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("psycopg2 stand-in: no DB in tests"))
    _pg.Error = Exception
    sys.modules["psycopg2"] = _pg

import macro_calendar_refresh as MCR  # noqa: E402
from scripts.lib import macro_calendar as MC  # noqa: E402
from scripts.lib import needs_action as NA  # noqa: E402

COVERS = ["scripts/macro_calendar_refresh.py", "scripts/lib/macro_calendar.py", "scripts/lib/needs_action.py",
          "config/macro_calendar_overrides.json", "config/lane_registry.json", "config/n8n_run_allowlist.json",
          "config/n8n_health_contracts.json"]

LANE = "macro-calendar-refresh"
RECEIPT = f"data/runtime/{LANE}_last.json"
KEY = "SENTINEL0FREDKEY0abcdef123456"
NOW = datetime(2026, 10, 21, 9, 5, tzinfo=timezone.utc)  # 05:05 ET, the lane's fire time
UTC = timezone.utc


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _refuse(*a, **k):
        raise AssertionError("tests must never reach the network")

    monkeypatch.setattr("urllib.request.urlopen", _refuse)


# ── FRED fake ──────────────────────────────────────────────────────────────────────────────────────────────────

RELEASES = [
    {"id": 9, "name": "Advance Monthly Sales for Retail and Food Services", "press_release": True},
    {"id": 10, "name": "Consumer Price Index", "press_release": True},
    {"id": 13, "name": "G.17 Industrial Production and Capacity Utilization", "press_release": True},
    {"id": 27, "name": "New Residential Construction", "press_release": True},
    {"id": 46, "name": "Producer Price Index", "press_release": True},
    {"id": 50, "name": "Employment Situation", "press_release": True},
    {"id": 53, "name": "Gross Domestic Product", "press_release": True},
    {"id": 54, "name": "Personal Income and Outlays", "press_release": True},
    {"id": 95, "name": "Manufacturers' Shipments, Inventories, and Orders", "press_release": True},
    {"id": 180, "name": "Unemployment Insurance Weekly Claims Report", "press_release": True},
]


def _thursdays(start: date, end: date, moved: dict) -> list[str]:
    d = start + timedelta(days=(3 - start.weekday()) % 7)
    out = []
    while d <= end:
        out.append(moved.get(d.isoformat(), d.isoformat()))
        d += timedelta(days=7)
    return out


#: SYNTHETIC schedule for 2026-10-21 .. 2027-02-18 (horizon 120 days). Thanksgiving week moves claims to Wednesday.
SCHEDULE = {
    180: _thursdays(date(2026, 10, 21), date(2027, 2, 18), {"2026-11-26": "2026-11-25"}),
    10: ["2026-11-10", "2026-12-10", "2027-01-13", "2027-02-10"],
    50: ["2026-11-06", "2026-12-04", "2027-01-08", "2027-02-05"],
    46: ["2026-11-13", "2026-12-11", "2027-01-14", "2027-02-12"],
    9: ["2026-11-17", "2026-12-15", "2027-01-15", "2027-02-17"],
    53: ["2026-10-29", "2026-11-25", "2026-12-22", "2027-01-28"],
    54: ["2026-10-30", "2026-11-25", "2026-12-23", "2027-01-29"],
    95: ["2026-10-27", "2026-11-24", "2026-12-23", "2027-01-27"],
    27: ["2026-11-18", "2026-12-17", "2027-01-20"],  # the earliest "last date": valid_through 2027-01-20
    13: ["2026-11-17", "2026-12-16"],  # unmapped (09:15 ET): ignored
}


def _date_rows(schedule=None) -> list[dict]:
    names = {r["id"]: r["name"] for r in RELEASES}
    rows = [{"release_id": rid, "release_name": names.get(rid, "x"), "date": d}
            for rid, ds in (schedule or SCHEDULE).items() for d in ds]
    return sorted(rows, key=lambda r: (r["date"], r["release_id"]))


class FakeFred:
    """Routes by path; pages with offset/limit like FRED; records (path, params) without the key."""

    def __init__(self, releases=None, rows=None, raw=None, count_skew=0):
        self.releases = RELEASES if releases is None else releases
        self.rows = _date_rows() if rows is None else rows
        self.raw = raw or {}
        self.count_skew = count_skew
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, path: str, params: dict, key: str) -> bytes:
        assert key == KEY
        self.calls.append((path, dict(params)))
        if path in self.raw:
            return self.raw[path]
        data = {"/releases": ("releases", self.releases), "/releases/dates": ("release_dates", self.rows)}[path]
        off, lim = int(params.get("offset", 0)), int(params.get("limit", 1000))
        body = {"realtime_start": params.get("realtime_start", "2026-10-21"),
                "realtime_end": params.get("realtime_end", "9999-12-31"), "count": len(data[1]) + self.count_skew,
                "offset": off, "limit": lim, data[0]: data[1][off:off + lim]}
        return json.dumps(body).encode()


def _refresh(tmp_path=None, fake=None, overrides=None, now=NOW, **kw):
    path = ROOT / MCR.OVERRIDES_REL
    if overrides is not None:
        path = tmp_path / "overrides.json"
        path.write_text(json.dumps(overrides))
    return MCR.refresh(KEY, fetch=fake or FakeFred(), overrides_path=path, now=now, **kw)


def _overrides(**changes):
    base = json.loads((ROOT / MCR.OVERRIDES_REL).read_text())
    base.update(changes)
    return base


# ── refresh: FRED ──────────────────────────────────────────────────────────────────────────────────────────────


def test_refresh_calls_the_two_read_only_endpoints_with_the_operator_params():
    fake = FakeFred()
    cal = _refresh(fake=fake)
    paths = [c[0] for c in fake.calls]
    assert paths == ["/releases", "/releases/dates"]
    p = fake.calls[1][1]
    assert p["realtime_start"] == "2026-10-21" and p["realtime_end"] == "2027-02-18"
    assert p["include_release_dates_with_no_data"] == "true"
    assert cal["schema"] == "MacroCalendar@v1" and cal["covers_from"] == "2026-10-21"
    assert cal["fetched_at"] == NOW.isoformat()


def test_urllib_fetch_builds_the_url_with_key_and_json_but_errors_carry_no_url(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        import urllib.error
        raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)

    monkeypatch.setattr(MCR.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(MCR.RefreshError) as ei:
        MCR.urllib_fetch("/releases", {"limit": 1}, KEY)
    q = parse_qs(seen["url"].split("?", 1)[1])
    assert seen["url"].startswith("https://api.stlouisfed.org/fred/releases?")
    assert q["api_key"] == [KEY] and q["file_type"] == ["json"]
    assert ei.value.reason == "dependency_unavailable" and "503" in str(ei.value) and KEY not in str(ei.value)


def test_every_mapped_id_is_verified_by_name():
    cal = _refresh()
    assert [v["release_id"] for v in cal["verification"]] == [r.release_id for r in MCR.RELEASE_MAP]
    assert all(v["ok"] for v in cal["verification"])
    assert {r.release_id for r in MCR.RELEASE_MAP} == {50, 10, 46, 9, 53, 180, 54, 95, 27}
    assert all(r.time_et == "08:30" and r.why for r in MCR.RELEASE_MAP)


@pytest.mark.parametrize("releases, needle", [
    ([r for r in RELEASES if r["id"] != 10], "10 (cpi): not in /fred/releases"),
    ([{**r, "name": "Consumer Credit"} if r["id"] == 10 else r for r in RELEASES], "10 (cpi): FRED name 'Consumer Credit'"),
])
def test_a_missing_or_renamed_id_fails_closed(releases, needle):
    with pytest.raises(MCR.RefreshError) as ei:
        _refresh(fake=FakeFred(releases=releases))
    assert ei.value.reason == "verification_failed" and needle in str(ei.value)


def test_maintenance_page_with_http_200_is_a_failure_not_an_empty_calendar():
    html = b"<!doctype html><html><head><title>Site Maintenance | St. Louis Fed</title>"
    with pytest.raises(MCR.RefreshError) as ei:
        _refresh(fake=FakeFred(raw={"/releases": html}))
    assert ei.value.reason == "dependency_unavailable" and "maintenance" in str(ei.value)


def test_fred_error_json_is_a_failure_and_the_key_is_scrubbed():
    raw = json.dumps({"error_code": 400, "error_message": f"Bad Request. api_key {KEY} is not registered."}).encode()
    with pytest.raises(MCR.RefreshError) as ei:
        _refresh(fake=FakeFred(raw={"/releases/dates": raw}))
    assert "400" in str(ei.value) and KEY not in str(ei.value) and "***" in str(ei.value)


def test_paging_reads_every_row_and_a_short_read_fails():
    noise = [{"release_id": 999, "release_name": "H.10", "date": (date(2026, 10, 21) + timedelta(days=i % 120)).isoformat()}
             for i in range(1600)]
    fake = FakeFred(rows=_date_rows() + noise)
    cal = _refresh(fake=fake)
    offsets = [int(p["offset"]) for path, p in fake.calls if path == "/releases/dates"]
    assert offsets == [0, 1000] and cal["source_receipts"][1]["rows"] == len(_date_rows()) + 1600
    with pytest.raises(MCR.RefreshError, match="rows of"):
        _refresh(fake=FakeFred(count_skew=5))


def test_a_mapped_release_with_no_scheduled_date_makes_coverage_unknown():
    sched = {k: v for k, v in SCHEDULE.items() if k != 27}
    with pytest.raises(MCR.RefreshError) as ei:
        _refresh(fake=FakeFred(rows=_date_rows(sched)))
    assert ei.value.reason == "dependency_unavailable" and "27 (housing_starts)" in str(ei.value)


# ── refresh: mapping, coverage, merge ──────────────────────────────────────────────────────────────────────────


def test_mapping_flags_0830_days_and_ignores_unmapped_releases():
    cal = _refresh()
    assert cal["valid_through"] == "2027-01-20" and cal["valid_through_bounded_by"] == ["housing_starts"]
    cpi = cal["dates"]["2026-11-10"]
    assert cpi["has_0830"] and cpi["skip_0800"] and [e["event"] for e in cpi["events"]] == ["cpi"]
    assert cpi["events"][0] == {"event": "cpi", "name": "Consumer Price Index", "time_et": "08:30", "skips_0800": True,
                                "source": "fred", "release_id": 10, "agency": "BLS"}
    assert "2026-12-16" not in cal["dates"]  # release 13 (G.17) is not mapped
    assert all(d <= "2027-01-20" for d in cal["dates"])  # nothing past coverage
    assert set(cal["skip_days_0800"]) == {k for k, v in cal["dates"].items() if v["skip_0800"]}


def test_thanksgiving_week_claims_follow_fred_to_wednesday():
    cal = _refresh()
    wed = cal["dates"]["2026-11-25"]
    assert {e["event"] for e in wed["events"]} == {"jobless_claims", "gdp", "pce"} and wed["skip_0800"]
    assert "2026-11-26" not in cal["dates"]


def test_fomc_is_recorded_at_1400_and_does_not_skip_unless_the_operator_says_so(tmp_path):
    cal = _refresh()
    fomc = cal["dates"]["2026-10-28"]
    assert fomc["events"] == [{"event": "fomc_decision", "name": "FOMC rate decision (statement)", "time_et": "14:00",
                               "skips_0800": False, "source": "overrides:fomc", "sep": False}]
    assert not fomc["skip_0800"] and not fomc["has_0830"]
    assert "2027-12-08" in cal["fomc_decisions"]
    ov = _overrides()
    ov["fomc"] = {**ov["fomc"], "skips_0800": True}
    cal2 = _refresh(tmp_path, overrides=ov)
    assert cal2["dates"]["2026-10-28"]["skip_0800"] and not cal2["dates"]["2026-10-28"]["has_0830"]


def test_operator_add_and_remove_overrides_apply_with_reasons(tmp_path):
    ov = _overrides(
        add=[{"date": "2026-11-02", "event": "ism_manufacturing_moved", "name": "ad hoc", "time_et": "08:30",
              "reason": "agency moved a release to 08:30", "added_by": "operator", "added_on": "2026-10-21"},
             {"date": "2026-11-03", "event": "treasury_refunding", "time_et": "08:30", "skips_0800": False,
              "reason": "record only"}],
        remove=[{"date": "2026-10-29", "event": "jobless_claims", "reason": "test: claims cancelled"},
                {"date": "2026-11-06", "event": "*", "reason": "test: shutdown, nothing publishes"}])
    cal = _refresh(tmp_path, overrides=ov)
    assert cal["dates"]["2026-11-02"]["skip_0800"]
    assert cal["dates"]["2026-11-03"]["has_0830"] and not cal["dates"]["2026-11-03"]["skip_0800"]
    assert [e["event"] for e in cal["dates"]["2026-10-29"]["events"]] == ["gdp"]
    assert "2026-11-06" not in cal["dates"]
    applied = cal["overrides_applied"]
    assert [r["reason"] for r in applied["added"]] == ["agency moved a release to 08:30", "record only"]
    assert applied["removed"][0]["matched"] == ["jobless_claims"]
    assert applied["removed"][1]["matched"] == ["employment_situation"]


@pytest.mark.parametrize("bad, needle", [
    ({"add": [{"date": "2026-11-02", "event": "x_event", "time_et": "08:30"}]}, "no reason"),
    ({"remove": [{"date": "2026-11-02", "event": "cpi", "reason": "  "}]}, "no reason"),
    ({"add": [{"date": "2026-11-02", "event": "Bad Key", "time_et": "08:30", "reason": "r"}]}, "not an event key"),
    ({"add": [{"date": "2026-13-02", "event": "x_event", "time_et": "08:30", "reason": "r"}]}, "bad date"),
    ({"add": [{"date": "2026-11-02", "event": "x_event", "time_et": "8:30am", "reason": "r"}]}, "HH:MM"),
    ({"schema": "Other@v1"}, "schema"),
])
def test_an_invalid_override_file_is_refused_whole(tmp_path, bad, needle):
    with pytest.raises(MCR.RefreshError) as ei:
        _refresh(tmp_path, overrides=_overrides(**bad))
    assert ei.value.reason == "config_invalid" and needle in str(ei.value)


def test_committed_overrides_file_holds_2026_and_2027_fomc_wednesdays():
    body, sha = MCR.load_overrides(ROOT / MCR.OVERRIDES_REL)
    ds = [date.fromisoformat(r["date"]) for r in body["fomc"]["decision_dates"]]
    assert len(ds) == 16 and {d.year for d in ds} == {2026, 2027} and len(sha) == 64
    assert all(d.weekday() == 2 for d in ds)  # the decision is the meeting's second day, a Wednesday
    assert body["fomc"]["time_et"] == "14:00" and body["fomc"]["skips_0800"] is False
    assert body["add"] == [] and body["remove"] == []


# ── reader: the controller's interface, fail closed ────────────────────────────────────────────────────────────


@pytest.fixture
def calfile(tmp_path):
    p = tmp_path / "data" / "runtime" / "macro_calendar.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(_refresh()))
    return p


def test_cpi_day_skips_and_a_plain_day_is_clear(calfile):
    now = NOW + timedelta(hours=1)
    skip, why = MC.skip_0800(date(2026, 11, 10), now, path=calfile)
    assert skip and why.startswith("MACRO_DAY:") and "cpi@08:30 (fred:10)" in why
    skip, why = MC.skip_0800(date(2026, 11, 9), now, path=calfile)
    assert not skip and why.startswith("CLEAR:")


def test_every_thursday_claims_day_skips(calfile):
    now = NOW + timedelta(hours=1)
    for d in SCHEDULE[180]:
        if d <= "2027-01-20":
            skip, why = MC.skip_0800(d, now, path=calfile)
            assert skip and "jobless_claims" in why, d
    assert MC.verdict("2026-10-22", now, path=calfile)[0] == "MACRO_DAY"  # Thursday
    assert MC.verdict("2026-10-23", now, path=calfile)[0] == "CLEAR"  # Friday, nothing at 08:30


def test_fomc_day_is_clear_for_0800_but_names_the_event(calfile):
    v, why = MC.verdict(date(2026, 10, 28), NOW, path=calfile)
    assert v == "CLEAR" and "fomc_decision" in why


def test_missing_file_fails_closed(tmp_path):
    skip, why = MC.skip_0800(date(2026, 10, 22), NOW, path=tmp_path / "absent.json")
    assert skip and why.startswith("UNAVAILABLE: calendar missing")


@pytest.mark.parametrize("mutate, needle", [
    (lambda t: "{not json", "corrupt"),
    (lambda t: json.dumps({**json.loads(t), "schema": "MacroReleaseCalendar@v1"}), "schema is not MacroCalendar@v1"),
    (lambda t: json.dumps({**json.loads(t), "fetched_at": "2026-10-21T09:05:00"}), "no UTC offset"),
    (lambda t: json.dumps({**json.loads(t), "dates": {"2026-11-10": {"events": []}}}), "malformed"),
    (lambda t: json.dumps({**json.loads(t), "valid_through": "2026-01-01"}), "before covers_from"),
    (lambda t: json.dumps([1, 2]), "corrupt"),
])
def test_corrupt_file_fails_closed(calfile, mutate, needle):
    calfile.write_text(mutate(calfile.read_text()))
    v, why = MC.verdict(date(2026, 10, 23), NOW, path=calfile)
    assert v == "UNAVAILABLE" and "corrupt" in why and needle in why
    assert MC.skip_0800(date(2026, 10, 23), NOW, path=calfile)[0] is True


def test_stale_after_three_days_and_future_stamp_fail_closed(calfile):
    d = date(2026, 10, 23)
    assert MC.verdict(d, NOW + timedelta(hours=72), path=calfile)[0] == "CLEAR"
    v, why = MC.verdict(d, NOW + timedelta(hours=72, minutes=1), path=calfile)
    assert v == "STALE" and "max 72 h" in why
    v, why = MC.verdict(d, NOW - timedelta(hours=2), path=calfile)
    assert v == "STALE" and "in the future" in why


def test_uncovered_date_fails_closed(calfile):
    for d in (date(2026, 10, 20), date(2027, 1, 21)):
        v, why = MC.verdict(d, NOW, path=calfile)
        assert v == "STALE" and "covers 2026-10-21..2027-01-20" in why
    assert MC.verdict(date(2027, 1, 20), NOW, path=calfile)[0] == "MACRO_DAY"  # housing starts, last covered day


def test_dst_end_age_is_absolute_and_the_window_date_is_the_et_date(tmp_path):
    # Fetched Saturday 2026-10-31 09:00 EDT (13:00Z); DST ends Sunday 2026-11-01. 08:00 EST Tuesday 2026-11-03 is
    # 13:00Z: exactly 72 h later on the clock of instants (wall clocks differ by 71 h), so not stale; one minute on is.
    fetched = datetime(2026, 10, 31, 13, 0, tzinfo=UTC)
    p = tmp_path / "c.json"
    p.write_text(json.dumps(_refresh(now=fetched)))
    window = datetime(2026, 11, 3, 8, 0, tzinfo=MC.ET)
    assert window.utcoffset() == timedelta(hours=-5)
    assert MC.verdict(window, window, path=p)[0] == "CLEAR"
    assert MC.verdict(window, window + timedelta(minutes=1), path=p)[0] == "STALE"
    # An aware instant is converted to the ET date: 2026-11-06 13:00Z is 08:00 EST on the jobs-report Friday.
    assert MC.et_date(datetime(2026, 11, 6, 13, 0, tzinfo=UTC)) == date(2026, 11, 6)
    assert MC.verdict(datetime(2026, 11, 6, 13, 0, tzinfo=UTC), window, path=p)[0] == "MACRO_DAY"


def test_dst_start_late_evening_utc_instant_maps_to_the_previous_et_day():
    # DST starts Sunday 2026-03-08. 2026-03-09 03:30Z is 23:30 EDT on 2026-03-08 (ET date the 8th, not the 9th).
    assert MC.et_date(datetime(2026, 3, 9, 3, 30, tzinfo=UTC)) == date(2026, 3, 8)
    assert MC.et_date(datetime(2026, 3, 9, 12, 0, tzinfo=UTC)) == date(2026, 3, 9)  # 08:00 EDT
    assert MC.et_date(datetime(2026, 3, 9, 8, 0)) == date(2026, 3, 9)  # naive = ET wall time
    assert MC.et_date("2026-03-09") == date(2026, 3, 9)


def test_bad_inputs_fail_closed_without_raising(calfile):
    assert MC.verdict("not-a-date", NOW, path=calfile)[0] == "UNAVAILABLE"
    assert MC.verdict(date(2026, 10, 23), datetime(2026, 10, 21, 9, 0), path=calfile)[0] == "UNAVAILABLE"


def test_release_train_adapter_matches_the_controller_signature_and_vocabulary(calfile):
    cal = MC.ReleaseTrainCalendar(calfile)
    assert cal.verdict(date(2026, 11, 6), NOW)[0] == "MACRO_DAY"
    assert cal.verdict(date(2026, 11, 9), NOW)[0] == "CLEAR"
    assert MC.ReleaseTrainCalendar(calfile.parent / "nope.json").verdict(date(2026, 11, 9), NOW)[0] == "UNAVAILABLE"
    # The controller halts with WINDOW_SKIPPED_MACRO_<verdict> for anything but CLEAR: the same four words.
    assert {MC.CLEAR, MC.MACRO_DAY, MC.STALE, MC.UNAVAILABLE} == {"CLEAR", "MACRO_DAY", "STALE", "UNAVAILABLE"}


def test_default_path_follows_the_state_root(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    assert MC.default_path() == tmp_path / "data" / "runtime" / "macro_calendar.json"


def test_reader_is_pure_stdlib_and_offline():
    import ast

    tree = ast.parse((ROOT / "scripts" / "lib" / "macro_calendar.py").read_text(encoding="utf-8"))
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level == 0}
    assert mods <= {"__future__", "json", "os", "datetime", "pathlib", "typing", "zoneinfo", "scripts", "lib"}, mods
    assert not {"urllib", "socket", "http", "requests", "psycopg2"} & mods


# ── main(): dry run writes nothing, live run writes atomically, failure keeps the old calendar ─────────────────


@pytest.fixture
def state(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    for k in ("TRADEAI_RUN_ID", "TRADEAI_RUN_ATTEMPT", "TRADEAI_RUN_MODE", "TRADEAI_CODE_SHA"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv(MCR.KEY_ENV, KEY)
    monkeypatch.setattr(MCR, "urllib_fetch", FakeFred())
    monkeypatch.setattr(MCR, "_utcnow", lambda: NOW)  # the fake schedule is fixed; the run date must be too
    return tmp_path


def test_dry_run_fetches_prints_and_writes_nothing(state, capsys):
    assert MCR.main(["--dry-run"]) == 0
    out = capsys.readouterr()
    assert not list(state.rglob("*")), "a dry run wrote something"
    assert "FRED_API_KEY configured: yes" in out.out and "DRY-RUN " in out.out
    assert "OK    10  cpi" in out.out and "SKIP 08:00" in out.out
    assert KEY not in out.out + out.err


def test_live_run_writes_calendar_then_receipt(state, capsys):
    assert MCR.main([]) == 0
    cal = json.loads((state / "data" / "runtime" / "macro_calendar.json").read_text())
    rec = json.loads((state / RECEIPT).read_text())
    assert cal["schema"] == "MacroCalendar@v1" and rec["status"] == "ok" and rec["ok_at"]
    assert rec["produced_count"] == len(cal["skip_days_0800"]) > 0
    assert not [p for p in (state / "data" / "runtime").iterdir() if p.name.endswith(".tmp")]
    assert KEY not in (state / RECEIPT).read_text() + json.dumps(cal) + "".join(capsys.readouterr())
    # The written file through the reader's default path (TRADEAI_STATE_ROOT): a covered CPI day, an uncovered day.
    assert MC.skip_0800(date(2026, 11, 10), NOW)[1].startswith("MACRO_DAY:")
    skip, why = MC.skip_0800(date(2027, 6, 1), NOW)
    assert skip and why.startswith("STALE:")


def test_failed_run_keeps_the_previous_calendar_and_writes_a_failed_receipt(state, monkeypatch, capsys):
    assert MCR.main([]) == 0
    target = state / "data" / "runtime" / "macro_calendar.json"
    before = target.read_bytes()
    monkeypatch.setattr(MCR, "urllib_fetch", FakeFred(raw={"/releases": b"<html>Site Maintenance</html>"}))
    assert MCR.main([]) == 1
    assert target.read_bytes() == before
    rec = json.loads((state / RECEIPT).read_text())
    assert rec["status"] == "failed" and rec["skipped_reasons"] == {"dependency_unavailable": 1}
    assert rec["summary"]["failure_kind"] == "dependency_unavailable" and "maintenance" in rec["summary"]["detail"]
    assert "maintenance" in capsys.readouterr().err


def test_failure_kinds_map_onto_the_closed_skip_reason_enum():
    import check_n8n_workflow_framework as F

    assert set(MCR.SKIP_REASON_OF_KIND.values()) <= F.FATAL_SKIP_REASONS
    assert MCR.RefreshError("verification_failed", "x").skip_reason == "unconfigured"
    assert MCR.RefreshError("config_invalid", "x").skip_reason == "unconfigured"
    assert MCR.RefreshError("no_credentials", "x").skip_reason == "no_credentials"
    c = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())
    k = next(x for x in c["contracts"] if x["id"] == LANE)
    assert set(MCR.SKIP_REASON_OF_KIND.values()) <= set(k["expected_output"]["fatal_skip_reasons"])
    assert F._check_expected_output(k)["status"] == F.PASS


def test_no_key_exits_1_and_says_only_that(state, monkeypatch, capsys):
    monkeypatch.delenv(MCR.KEY_ENV)
    assert MCR.main(["--dry-run"]) == 1
    out = capsys.readouterr()
    assert "FRED_API_KEY configured: no" in out.out and "not configured" in out.err
    assert MCR.main(["--horizon-days", "3"]) == 2


# ── needs-action source ────────────────────────────────────────────────────────────────────────────────────────


def test_needs_action_p2_when_stale_or_missing_and_nothing_on_a_macro_day():
    stale = NA.rule_macro_calendar({"day": "2026-10-22", "verdict": "STALE", "reason": "old"}, NOW)
    assert [(i["severity"], i["title"]) for i in stale] == [("P2", "08:00 release window skipped: calendar stale")]
    missing = NA.rule_macro_calendar({"day": "2026-10-22", "verdict": "UNAVAILABLE", "reason": "calendar missing"}, NOW)
    assert [(i["severity"], i["title"]) for i in missing] == [("P2", "08:00 release window skipped: calendar missing")]
    assert NA.rule_macro_calendar({"verdict": "MACRO_DAY"}, NOW) == []
    assert NA.rule_macro_calendar({"verdict": "CLEAR"}, NOW) == []
    with pytest.raises(NA.SourceUnavailable):
        NA.rule_macro_calendar({}, NOW)


def test_next_0800_day_rolls_past_0800_and_weekends():
    assert NA.next_0800_day(datetime(2026, 10, 21, 11, 59, tzinfo=UTC)) == date(2026, 10, 21)  # 07:59 EDT
    assert NA.next_0800_day(datetime(2026, 10, 21, 12, 0, tzinfo=UTC)) == date(2026, 10, 22)  # 08:00 EDT
    assert NA.next_0800_day(datetime(2026, 10, 23, 15, 0, tzinfo=UTC)) == date(2026, 10, 26)  # Friday -> Monday
    assert NA.next_0800_day(datetime(2026, 11, 2, 12, 30, tzinfo=UTC)) == date(2026, 11, 2)  # 07:30 EST


def test_needs_action_probe_and_aggregate(tmp_path, calfile):
    out = NA.aggregate({"macro_calendar": lambda: NA.probe_macro_calendar(tmp_path / "absent.json", now=NOW)}, now=NOW)
    assert out["sources"]["macro_calendar"]["status"] == "OK" and out["counts"]["P2"] == 1
    assert out["items"][0]["title"] == "08:00 release window skipped: calendar missing"
    ok = NA.probe_macro_calendar(calfile, now=NOW)
    assert ok == {"day": "2026-10-21", "verdict": "CLEAR", "reason": ok["reason"]}
    assert "macro_calendar" in NA.RULES


def test_api_v2_wires_the_source():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    assert '"macro_calendar": _na.probe_macro_calendar' in src


# ── the n8n lane: registry, allowlist, DRAFT contract, gate, closure ───────────────────────────────────────────


def _row():
    return next(r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]
                if r["lane_id"] == LANE)


def test_registry_row_is_n8n_native_ingest_shadow_daily_0505():
    row = _row()
    sch, d = row["scheduler"], row["dispatch"]
    assert (sch["kind"], sch["expression"], sch["stage"]) == ("n8n", "dispatcher", "shadow")
    assert sch["match"] == "scripts/macro_calendar_refresh.py"
    assert d["mode"] == "dry_run" and d["cron"] == ["5 5 * * *"] and d["tz"] == "America/New_York"
    assert d["class"] == "ingest" and d["retry_policy"] == "none" and row["owner"] == "platform"
    assert (row["output_signal"]["path"], row["output_signal"]["key"]) == (RECEIPT, "ok_at")
    from scripts.lib.lane_dispatch import dispatch_eligible
    ok = dispatch_eligible(row)
    assert ok[0] if isinstance(ok, tuple) else ok


def test_allowlist_entry_is_shadow_enforced_and_names_only_what_the_lane_reads():
    a = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())
    e = next(x for x in a["lanes"] if x["lane_id"] == LANE)
    assert e["command"] == ["$PY", "scripts/macro_calendar_refresh.py"]
    assert e["dry_run_arg"] == ["--dry-run"] and e["live_arg"] is None
    assert e["lock_kind"] == "flock" and e["output_signal"] == RECEIPT and e["output_receipt"] == "v2"
    assert e["env_allowlist_mode"] == "enforce"
    assert e["env_names"] == ["FRED_API_KEY", "TRADEAI_PERSISTENT_STATE_ROOT"]
    assert LANE not in json.dumps(a.get("never"))


def test_health_contract_is_a_draft_for_the_operator_to_review():
    c = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())
    k = next(x for x in c["contracts"] if x["id"] == LANE)
    # An agent may not mark its own contract REVIEWED (AGENTS.md §23.19): the operator does.
    assert k["status"] in ("DRAFT", "REVIEWED") and k["owner"] == "platform" and k["stage"] == "shadow"
    if k["status"] == "REVIEWED":
        assert k["review"]["reviewed_by"].startswith("operator ")
    assert k["evidence"]["receipt"] == RECEIPT and k["expected_output"]["rule"] == "min_produced"
    from scripts.lib import n8n_output_verdict as V
    assert V.validate_expected_output(k["expected_output"]) == []


def test_ci_gate_is_registered_with_an_anchor():
    g = json.loads((ROOT / "config" / "ci_gates" / "macro_calendar_20261021.json").read_text())
    assert g["schema"] == "CiGate@v1" and g["name"] == "macro_calendar_20261021"
    assert g["files"] == ["tests/test_macro_calendar_20261021.py"] and g["anchor"] == "MACRO_CALENDAR_20261021"


def test_lane_closure_reaches_no_sender_broker_order_or_db():
    import audit_lane_transitive_capabilities as cap
    res = cap.Resolver()
    order, _ = res.closure(ROOT / "scripts" / "macro_calendar_refresh.py")
    rels = {res.info(m).path for m in order}
    assert not rels & {"scripts/db_adapter.py", "scripts/telegram_alert.py", "scripts/lib/host_comms_intents.py",
                       "scripts/n8n_coordination_gateway.py", "scripts/lib/env_bootstrap.py"}, rels
    caps = set().union(*(res.info(m).caps for m in order))
    assert not caps & {"direct_sender", "broker_module", "order_placement", "chokepoint_send"}, caps
