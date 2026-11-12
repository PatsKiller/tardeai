"""LQ-20261107-1669: VIX refreshes every 15 min across the whole weekday, proven slot by slot.

Operator order 2026-11-09 14:50 ET: "VIX must refresh at least every 15 min during the trading day AND pre-market AND
after-hours (and the existing overnight) ... no gaps at 03:45/04:00/09:30/16:00/20:00 boundaries; prove it with a
timeline query showing a row per 15-min slot across all sessions (emulate the slots you cannot wait for)."

FAIL-BEFORE (pinned below against the unchanged off-hours lane): a fresh pre-market $VIX print is refused
``no_dated_reference_for_premarket``, and the regular session is never fetched (``regular_session``).

PASS-AFTER: ``scripts/vix_index_quotes_schwab.py`` is emulated for every 15-min slot from Sunday 18:00 to Friday
20:00 ET (488 slots) against a synthetic Cboe model, and every slot's stored row is read back through the one headline
read (``vix_headline`` -> ``vix_complex``). Cboe does not calculate VIX between 16:15 and 03:15 ET; those slots keep
the 16:15 print and say so (``stale_print``, with the print's own time, never missing). LQ-20261107-2600 measured that
16:15 IS the day's settlement, so the surface reads that stored print as current-for-session (FRESH/settled) rather
than condemning the evening as stale; a print that predated the settlement would read STALE with the settlement named.

Synthetic values only (public repo). No DB, no network, no Schwab.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import vix_index_quotes_schwab as lane  # noqa: E402
from lib import offhours_quotes as oq  # noqa: E402
from lib import vix_headline as vh  # noqa: E402
from lib.market_regime import vix_complex as vc  # noqa: E402

ET = ZoneInfo("America/New_York")
CFG = lane.load_config()
WEEK_START = datetime(2026, 11, 8, 18, 0, tzinfo=ET)  # Sunday 18:00 ET
WEEK_END = datetime(2026, 11, 13, 20, 0, tzinfo=ET)  # Friday 20:00 ET
FIRE_OFFSET = timedelta(seconds=40)  # n8n fires a little after the slot boundary
GTH = (time(3, 15), time(9, 25))  # Cboe global trading hours VIX calculation (synthetic model)
RTH = (time(9, 30), time(16, 15))  # regular VIX calculation; 16:15 is the settlement print


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _payload(prints: dict[str, tuple[float, datetime]], asset: str = "INDEX") -> dict:
    return {s: {"assetMainType": asset, "symbol": s, "quote": {"lastPrice": p, "tradeTime": _ms(t)}}
            for s, (p, t) in prints.items()}


# ── fail-before: the off-hours lane cannot carry a session VIX ────────────────────────────────────────────────


def test_fail_before_the_off_hours_lane_refuses_premarket_vix_and_skips_the_regular_session():
    ocfg = oq.load_config()
    assert oq.schwab_window(datetime(2026, 11, 10, 11, 0, tzinfo=ET), ocfg) == (False, "regular_session")
    now = datetime(2026, 11, 10, 7, 0, tzinfo=ET)
    rows, skipped = oq.schwab_rows(_payload({"$VIX": (18.4, now - timedelta(seconds=20))}), now, ocfg,
                                   reference_lookup=lambda _s, _d: None)
    assert rows == []
    assert skipped[0]["reason"] == "no_dated_reference_for_premarket"


# ── the lane's units ──────────────────────────────────────────────────────────────────────────────────────────


def test_the_shipped_config_is_on_only_with_its_recorded_grant_and_index_only():
    # 2026-11-09 16:08 ET the operator approved AGENTS 32.0.0 §23.20a; enabled only while the grant is recorded.
    import json as _json
    auth = _json.loads((Path(__file__).resolve().parents[1] / "config" / "data_source_authority.json").read_text())
    grants = auth["providers"]["schwab"]["supply_grants"]
    granted = any(g["supply"] == "market_data_quotes" and g["domain"] == "quote_price"
                  and "vix-index-quotes-schwab" in g["scope"] for g in grants)
    assert CFG["enabled"] is granted is True
    assert CFG["symbols"] == ["$VIX", "$VIX9D", "$VIX3M"]
    assert (CFG["store"], CFG["source"], CFG["cadence_minutes"], CFG["max_trade_age_minutes"]) == (
        "market_quotes", "schwab", 15, 30)
    assert "supply_grants" in CFG["requires_grant"]


@pytest.mark.parametrize("at, inside", [
    ("2026-11-08T17:59", False), ("2026-11-08T18:00", True), ("2026-11-10T03:45", True),
    ("2026-11-10T09:30", True), ("2026-11-10T16:00", True), ("2026-11-10T20:00", True),
    ("2026-11-13T19:59", True), ("2026-11-13T20:00", False), ("2026-11-14T12:00", False),
])
def test_the_window_is_one_continuous_span_sunday_evening_to_friday_night(at, inside):
    assert lane.in_window(datetime.fromisoformat(at).replace(tzinfo=ET), CFG)[0] is inside


def test_the_slot_is_the_15_minute_floor_in_et():
    assert lane.slot_of(datetime(2026, 11, 9, 19, 47, 31, tzinfo=timezone.utc)) == "2026-11-09T14:45"


NOW = datetime(2026, 11, 10, 11, 0, 40, tzinfo=ET)


@pytest.mark.parametrize("block, status", [
    ({"assetMainType": "INDEX", "quote": {"lastPrice": 18.0, "tradeTime": _ms(NOW - timedelta(seconds=15))}},
     "written"),
    # The store is empty in this table, so a print past the age line is NEWER than anything stored: from
    # LQ-20261107-1872 that is kept and labelled written_stale, never discarded. `stale_print` is the store already
    # holding it (or something newer) case -- see tests/test_vix_index_quotes_stale_written_20261110.py.
    ({"assetMainType": "INDEX", "quote": {"lastPrice": 18.0, "tradeTime": _ms(NOW - timedelta(minutes=31))}},
     "written_stale"),
    ({"assetMainType": "EQUITY", "quote": {"lastPrice": 18.0, "tradeTime": _ms(NOW)}},
     "refused:index_asset_type_equity"),
    ({"quote": {"lastPrice": 18.0, "tradeTime": _ms(NOW)}}, "refused:index_asset_type_missing"),
    ({"assetMainType": "INDEX", "quote": {"lastPrice": 0, "tradeTime": _ms(NOW)}}, "refused:no_trade_price_or_time"),
    ({"assetMainType": "INDEX", "quote": {"lastPrice": 18.0}}, "refused:no_trade_price_or_time"),
    ({"assetMainType": "INDEX", "quote": {"lastPrice": 18.0, "tradeTime": _ms(NOW + timedelta(minutes=10))}},
     "refused:future_timestamp"),
    ({"assetMainType": "INDEX"}, "refused:not_a_quote"),
])
def test_each_print_gets_one_named_status(block, status):
    rows, entries = lane.parse_payload({"$VIX": block}, NOW, CFG, {})
    assert entries[0]["status"] == status
    assert len(rows) == (1 if status in ("written", "written_stale") else 0)
    assert {e["symbol"] for e in entries} == {"$VIX", "$VIX9D", "$VIX3M"}  # one entry per symbol, always
    assert [e["status"] for e in entries[1:]] == ["refused:not_in_payload"] * 2


def test_a_print_already_stored_is_unchanged_and_the_row_carries_the_print_time_not_the_fetch_time():
    at = NOW - timedelta(minutes=3)
    rows, entries = lane.parse_payload(_payload({"$VIX": (18.0, at)}), NOW, CFG, {"$VIX": at})
    assert (rows, entries[0]["status"]) == ([], "unchanged")
    rows, _ = lane.parse_payload(_payload({"$VIX": (18.0, at)}), NOW, CFG, {"$VIX": at - timedelta(minutes=15)})
    assert rows == [{"symbol": "$VIX", "price": 18.0, "fetched_at": at}]


def test_a_provider_failure_is_the_receipt_status_and_nothing_is_written():
    wrote = []
    r = lane.run(cfg=CFG, now=NOW, fetch=lambda _s: {"_status": "token_not_fresh", "_detail": "x"},
                 read_last=lambda s: {}, write=wrote.append, dry_run=False)
    assert (r["status"], wrote) == ("token_not_fresh", [])


def test_outside_the_window_nothing_is_fetched():
    r = lane.run(cfg=CFG, now=datetime(2026, 11, 14, 12, 0, tzinfo=ET),
                 fetch=lambda _s: pytest.fail("fetched outside the window"), read_last=lambda s: {},
                 write=None, dry_run=True)
    assert r["status"] == "outside_window"


def _disabled_config(tmp_path):
    # the shipped config is enabled since 2026-11-09 16:08 ET; these cases pin the switched-off behaviour
    off = tmp_path / "vix_index_quotes.yaml"
    off.write_text(lane.CONFIG_PATH.read_text().replace("\nenabled: true\n", "\nenabled: false\n"))
    assert "\nenabled: false\n" in off.read_text()
    return str(off)


def test_apply_while_disabled_stops_before_any_schwab_module_is_imported_and_fails_its_receipt(monkeypatch, capsys, tmp_path):
    monkeypatch.setitem(sys.modules, "market_quotes_offhours_schwab", None)  # an import would raise
    got = []
    monkeypatch.setattr(lane, "_write_receipt", lambda r, s: got.append(r))
    assert lane.main(["--apply", "--config", _disabled_config(tmp_path)]) == 1  # a live fire of a disabled lane is never a quiet success (LQ-1684)
    assert '"status": "disabled"' in capsys.readouterr().out
    assert [r["status"] for r in got] == ["disabled"]


def test_a_shadow_dry_run_while_disabled_imports_nothing_and_writes_no_receipt(monkeypatch, capsys, tmp_path):
    monkeypatch.setitem(sys.modules, "market_quotes_offhours_schwab", None)
    monkeypatch.setattr(lane, "_write_receipt", lambda r, s: pytest.fail("a dry run wrote a receipt"))
    assert lane.main(["--dry-run", "--live-read", "--config", _disabled_config(tmp_path)]) == 0
    assert '"status": "disabled"' in capsys.readouterr().out


def test_a_dry_run_without_a_fixture_refuses_rather_than_call_schwab(capsys):
    assert lane.main(["--dry-run"]) == 2
    assert "--fixture" in capsys.readouterr().out


@pytest.mark.parametrize("receipt, outcome", [
    ({"status": "outside_window"}, (True, "outside_window")),
    ({"status": "vix_stale_print"}, (True, "cboe_not_calculating")),
    ({"status": "ok", "inserted": 0}, (True, "unchanged")),
    ({"status": "ok", "inserted": 3}, (True, None)),
    ({"status": "token_not_fresh"}, (False, None)),
    ({"status": "disabled"}, (False, None)),
    ({"status": "vix_not_index"}, (False, None)),
])
def test_each_fire_has_one_lane_outcome(receipt, outcome):
    assert lane.lane_outcome(receipt) == outcome


def test_the_lane_receipt_carries_the_vix_print_and_counts(monkeypatch):
    from lib import lane_last_receipt as llr
    seen = {}
    monkeypatch.setattr(llr, "write_lane_receipt", lambda lane_id, **kw: seen.update(lane_id=lane_id, **kw))
    at = datetime(2026, 11, 9, 14, 0, tzinfo=ET)
    r = lane.run(cfg=CFG, now=at + FIRE_OFFSET, fetch=lambda s: _payload({"$VIX": (18.0, at), "$VIX9D": (17.0, at),
                                                                          "$VIX3M": (19.0, at)}),
                 read_last=lambda s: {x: None for x in s}, write=lambda rows: {"rows_written": len(rows)}, dry_run=False)
    lane._write_receipt(r, "2026-11-09T19:00:40+00:00")
    assert seen["lane_id"] == "vix-index-quotes-schwab" and seen["ok"] is True and seen["exit_code"] == 0
    assert seen["produced_count"] == r["inserted"] and seen["attempted_count"] == 3
    assert seen["summary"]["vix_price"] == 18.0 and seen["summary"]["vix_print_at"]
    assert seen["empty_reason"] is None and r["inserted"] == 3


# ── the headline reads the continuous row ────────────────────────────────────────────────────────────────────


class _TwoStores:
    """Answers the off-hours store and the continuous store from separate lists (vix_complex's cursor protocol)."""

    def __init__(self, extended=(), continuous=(), fail=()):
        self.extended, self.continuous, self.fail = list(extended), list(continuous), set(fail)
        self.sql: list[str] = []

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self._sql = sql
        self.sql.append(sql)
        if any(t in sql for t in self.fail):
            raise RuntimeError("store unavailable")

    def fetchall(self):
        if "market_quotes_extended" in self._sql:
            return self.extended
        if "FROM market_quotes WHERE" in self._sql:
            return self.continuous
        return []

    def rollback(self):
        pass


VC = vc.load_config()
T = datetime(2026, 11, 10, 14, 0, tzinfo=ET)


def _cont(price, at):
    return ("$VIX", price, "continuous", None, at, "schwab_index_quote_continuous", "schwab")


def _ext(price, at):
    return ("$VIX", price, "overnight", at.date(), at, "schwab_index_level", "schwab")


def test_the_newer_of_the_two_stores_is_the_vix_and_names_its_store():
    vals, _, _ = vc.read_quotes(_TwoStores([_ext(17.0, T - timedelta(hours=10))], [_cont(18.5, T)]),
                                T + timedelta(minutes=1), VC)
    assert (vals["vix_close"]["value"], vals["vix_close"]["source"]) == (18.5, "market_quotes:schwab")
    vals, _, _ = vc.read_quotes(_TwoStores([_ext(17.0, T)], [_cont(18.5, T - timedelta(hours=10))]),
                                T + timedelta(minutes=1), VC)
    assert (vals["vix_close"]["value"], vals["vix_close"]["source"]) == (17.0, "market_quotes_extended:schwab")


def test_a_failing_continuous_read_is_named_and_the_off_hours_row_still_stands():
    vals, missing, _ = vc.read_quotes(_TwoStores([_ext(17.0, T)], fail=("FROM market_quotes WHERE",)),
                                      T + timedelta(minutes=1), VC)
    assert vals["vix_close"]["value"] == 17.0
    assert "vix_complex_continuous_read_failed:RuntimeError" in missing


def test_without_the_continuous_keys_only_the_off_hours_store_is_read():
    cfg = {k: v for k, v in VC.items() if k not in ("continuous_store", "continuous_source")}
    conn = _TwoStores([_ext(17.0, T)], [_cont(18.5, T)])
    vals, _, _ = vc.read_quotes(conn, T + timedelta(minutes=1), cfg)
    assert vals["vix_close"]["value"] == 17.0 and len(conn.sql) == 1


def test_a_banned_source_under_the_continuous_store_is_refused_by_name():
    row = ("$VIX", 18.5, "continuous", None, T, "schwab_index_quote_continuous", "yfinance")
    _, missing, _ = vc.read_quotes(_TwoStores([], [row]), T + timedelta(minutes=1), VC)
    assert "vix_close_banned_source:yfinance" in missing


# ── the emulated week: one receipt per 15-min slot, Sunday 18:00 -> Friday 20:00 ET ──────────────────────────


def _calculating(at: datetime) -> bool:
    et = at.astimezone(ET)
    if et.weekday() >= 5:
        return False
    t = et.time()
    return GTH[0] <= t < GTH[1] or RTH[0] <= t < RTH[1]


def _last_print(at: datetime) -> datetime:
    """Cboe's newest $VIX print at ``at`` in the synthetic model: 15 s old while calculating, else the last end."""
    if _calculating(at):
        return at - timedelta(seconds=15)
    probe = at.astimezone(ET).replace(second=0, microsecond=0)
    while not _calculating(probe - timedelta(minutes=1)):
        probe -= timedelta(minutes=1)
    return probe  # the instant the last span ended (09:25 or the 16:15 settlement)


def _price(at: datetime) -> float:
    return round(15.0 + (at.astimezone(ET).hour * 60 + at.astimezone(ET).minute) / 1000.0, 2)


def emulate_week(start: datetime = WEEK_START, end: datetime = WEEK_END) -> list[dict]:
    """Run the lane once per slot against the Cboe model and an in-memory store; read each slot back through the
    one headline read. Returns one timeline row per slot.

    The store starts with what the previous Friday's 16:15 slot wrote (the settlement print), as it would live; an
    empty store would read UNAVAILABLE until Monday 03:15, which is true but not this week's shape."""
    settle = _last_print(start)
    store: list[tuple] = [(s, settle, _price(settle)) for s in CFG["symbols"]]
    out = []
    slot = start
    while slot < end:
        fire = slot + FIRE_OFFSET

        def fetch(syms, fire=fire):
            p = _last_print(fire)
            return _payload({s: (_price(p), p) for s in syms})

        def read_last(syms):
            return {s: max((r[1] for r in store if r[0] == s), default=None) for s in syms}

        def write(rows):
            store.extend((r["symbol"], r["fetched_at"], r["price"]) for r in rows)
            return {"rows_written": len(rows)}

        rec = lane.run(cfg=CFG, now=fire, fetch=fetch, read_last=read_last, write=write, dry_run=False)

        def q(sql, params=None):
            if "FROM market_quotes WHERE" not in sql:
                return []
            latest = {}
            for sym, at, price in store:
                if sym not in latest or at > latest[sym][1]:
                    latest[sym] = (price, at)
            return [(s, p, "continuous", None, at, "schwab_index_quote_continuous", "schwab")
                    for s, (p, at) in sorted(latest.items())]

        head = vh.vix_headline(db_query=q, now=fire, cfg=VC)
        vix = next(e for e in rec["symbols"] if e["symbol"] == "$VIX")
        out.append({"slot": rec["slot"], "fire": fire, "cboe_calculating": _calculating(fire),
                    "lane_status": rec["status"], "vix_status": vix["status"], "print_at": vix.get("print_at"),
                    "inserted": rec["inserted"], "headline_state": head["vix_state"], "headline": head})
        slot += timedelta(minutes=15)
    return out


@pytest.fixture(scope="module")
def week():
    return emulate_week()


def test_every_slot_of_the_week_has_one_receipt_and_none_is_missing(week):
    assert len(week) == 488  # 122 h x 4
    slots = [datetime.fromisoformat(r["slot"]).replace(tzinfo=ET) for r in week]
    assert all(b - a == timedelta(minutes=15) for a, b in zip(slots, slots[1:]))
    assert {r["lane_status"] for r in week} <= {"ok", "vix_stale_print"}
    assert not any(r["vix_status"].startswith("refused") for r in week)


def test_every_calculating_slot_writes_and_reads_fresh_including_every_session_boundary(week):
    calc = [r for r in week if r["cboe_calculating"]]
    assert len(calc) == 5 * (25 + 27)  # GTH 03:15-09:15 slots (25) + RTH 09:30-16:00 slots (27) per weekday
    assert all(r["vix_status"] == "written" and r["inserted"] == 3 for r in calc)
    assert all(r["headline_state"] == "FRESH" for r in calc)
    for day in range(9, 14):
        for hhmm in ("03:45", "04:00", "09:30", "16:00"):
            row = next(r for r in week if r["slot"] == f"2026-11-{day:02d}T{hhmm}")
            assert (row["vix_status"], row["headline_state"]) == ("written", "FRESH"), row


def test_the_cboe_gap_reads_current_for_session_with_the_print_time_never_missing(week):
    """LQ-2600: the model's last RTH print is the 16:15 settlement, so the evening gap is FRESH/settled; the surface
    still shows the print's own time and never a missing value, and a print past the minute line is STALE."""
    for r in week:
        head = r["headline"]
        assert (head["vix"], head["vix_observation_time"]) != (None, None), r
        age = (r["fire"] - datetime.fromisoformat(r["print_at"])).total_seconds() / 60.0
        if head["vix_fresh_rule"] == "settled":
            assert head["vix_state"] == "FRESH", r  # the stored print IS the settlement the rule asks for
        else:
            assert head["vix_state"] == ("FRESH" if age <= 30 else "STALE"), r
        if head["vix_state"] == "STALE":
            hhmm = datetime.fromisoformat(r["print_at"]).astimezone(ET).strftime("%H:%M")
            assert f"last print {hhmm} ET" in head["vix_reason"], head
    after_close = next(r for r in week if r["slot"] == "2026-11-10T20:00")
    assert (after_close["vix_status"], after_close["headline_state"]) == ("stale_print", "FRESH")
    h = after_close["headline"]
    assert h["vix_fresh_rule"] == "settled"
    assert datetime.fromisoformat(h["vix_expected_print"]) == datetime.fromisoformat("2026-11-10T16:15:00-05:00")
    # the print's own time, 225 min after it settled, in whatever zone the store stamped it
    assert (datetime.fromisoformat(h["vix_observation_time"])
            == datetime.fromisoformat("2026-11-10T16:15:00-05:00"))
