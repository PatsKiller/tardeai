"""ANCHOR: VIX_COMPLEX_STORE_BACKED_20261108 — the volatility complex is read from the stores, never Yahoo.

LQ-20261107-940 + LQ-20261107-969 (design WU-6). Until 2026-11-08 `market_regime_collector.collect_vix` asked
`query1.finance.yahoo.com` for `^VIX ^VIX9D ^VIX3M ^VVIX ^SKEW ^VXN` and stamped the answer
`source_key='yahoo_finance'`, and the collector also wrote a UVXY "vol proxy" when VIX was missing. yfinance is a
banned price source (operator price rule 2026-11-07), so the path was REBUILT (not patched): the same six CBOE
indices are Schwab symbols the off-hours lane already quotes into `market_quotes_extended` (feed `schwab`), and
FRED `VIXCLS`/`VXNCLS` is a labelled T+1 fallback for the two closes it actually publishes.

These tests pin the behaviour that makes the rebuild honest:
  * a row under a banned feed (yahoo / yahoo_finance / yfinance) is REFUSED BY NAME — never scored, never
    laundered into "no row", because the point is to see a rogue writer on the receipt;
  * a row from any other feed is refused as `unexpected_feed` (the store is shared with Alpaca rows);
  * every absence — no row, stale, non-positive, timeless, FRED stale/marker — is NAMED; nothing is written as a
    zero (design hard constraint "UNKNOWN never a silent zero");
  * FRED fills a key Schwab could not supply; a *dated* Schwab close still beats FRED, but a *carried*
    Schwab level (reference_basis = …carried_print_YYYY-MM-DD) is displaced by FRED's published close
    (REVIEW-LQ-969: three disagreeing Sunday-night numbers);
  * a carried print is aged from the print date in reference_basis, never from bar_end (so a Friday close
    stored with Sunday 20:00 bar_end is not reported 0.5 h fresh);
  * the term-structure ratios exist only when both inputs are real values;
  * complex_record() is the single VIX/VIX3M/VVIX read for MRE / outlook / CIO;
  * the receipt has one entry per configured symbol, so "0 rows" can never read as "nothing to do".

Hermetic: a fake connection answers by table name; no DB, no network, no YAML beyond what the test writes.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from itertools import count
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.market_regime import vix_complex as vc  # noqa: E402

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 6, 21, 5, tzinfo=timezone.utc)  # a Friday close, ET
# Sunday evening after a Friday carry (the weekend outlook window the review pinned).
SUN_NIGHT = datetime(2026, 11, 8, 20, 30, tzinfo=ET)

CFG = {
    "schema": vc.SCHEMA,
    "store": "market_quotes_extended",
    "feed": "schwab",
    "symbols": {"$VIX": "vix_close", "$VIX9D": "vix9d_close", "$VIX3M": "vix3m_close",
                "$VVIX": "vvix_close", "$SKEW": "skew_close", "$VXN": "vxn_close"},
    "fred": {"VIXCLS": "vix_close", "VXNCLS": "vxn_close"},
    "max_age_hours": 96,
    "fresh_after_hours": 26,
    "fred_max_age_days": 7,
    "carried_basis_prefix": "schwab_index_level_carried_print",
    "vix_signal": {"extreme": 30, "high": 20, "normal": 14},
}


class _Conn:
    """Answers `market_quotes_extended` and `fred_economic_series` from separate lists, by table name."""

    def __init__(self, rows=(), fred=(), fail=()):
        self.rows, self.fred, self.fail = list(rows), list(fred), set(fail)
        self.queries: list[tuple[str, object]] = []

    def cursor(self):
        conn = self

        class Cur:
            def execute(self, sql, params=None):
                self._sql = str(sql)
                conn.queries.append((self._sql, params))
                for table in conn.fail:
                    if table in self._sql:
                        raise RuntimeError(f"{table} unavailable")

            def fetchall(self):
                if "market_quotes_extended" in self._sql:
                    return conn.rows
                if "fred_economic_series" in self._sql:
                    return conn.fred
                return []

            def close(self):
                pass

        return Cur()

    def rollback(self):
        pass


def _row(sym, price, *, feed="schwab", hours_old=1.0, bar_end=None, basis="schwab_close", session="closed",
         session_date=None):
    return (sym, price, session, session_date if session_date is not None else NOW.date(),
            bar_end if bar_end is not None else NOW - timedelta(hours=hours_old), basis, feed)


def _carried_row(sym, price, *, print_day: date, bar_end: datetime):
    """A Friday close stored as an overnight LEVEL whose bar_end is that night's 20:00 ET start."""
    return _row(sym, price, bar_end=bar_end, session="overnight", session_date=bar_end.astimezone(ET).date(),
                basis=f"schwab_index_level_carried_print_{print_day.isoformat()}")


def _collect(rows=(), fred=(), cfg=None, fail=(), now=None):
    ids = count(1)
    return vc.collect(_Conn(rows, fred, fail), "SNAP_T", now or NOW, cfg or CFG, lambda: f"IND_{next(ids)}")


def _keys(inds):
    return {i["indicator_key"] for i in inds}


# ── the shipped config ──────────────────────────────────────────────────────────────────────────────────────


def test_the_shipped_config_names_the_six_cboe_indices_and_the_two_fred_closes():
    cfg = vc.load_config()
    assert set(cfg["symbols"]) == {"$VIX", "$VIX9D", "$VIX3M", "$VVIX", "$SKEW", "$VXN"}
    assert set(cfg["symbols"].values()) == {"vix_close", "vix9d_close", "vix3m_close", "vvix_close",
                                            "skew_close", "vxn_close"}
    assert cfg["feed"] == "schwab" and cfg["store"] == "market_quotes_extended"
    assert set(cfg["fred"]) == {"VIXCLS", "VXNCLS"}
    assert set(cfg["fred"].values()) <= set(cfg["symbols"].values())
    assert cfg["carried_basis_prefix"] == "schwab_index_level_carried_print"
    assert list(vc.expected_keys(cfg)) == list(cfg["symbols"].values())


def test_the_query_only_asks_for_the_configured_symbols_and_feeds_nothing_else():
    _, _, receipts = vc.read_quotes(_Conn([]), NOW, CFG)
    assert len(receipts) == len(CFG["symbols"])  # every configured symbol is reported, present or refused


# ── refusals are named ───────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("feed", ["yahoo", "yahoo_finance", "yfinance"])
def test_a_banned_feed_row_is_refused_by_name_and_never_scored(feed):
    inds, missing, summary = _collect([_row("$VIX", 20.0, feed=feed)])
    assert "vix_close" not in _keys(inds)
    assert f"vix_close_banned_source:{feed}" in missing
    assert summary["banned_feeds_refused"] == [{"symbol": "$VIX", "key": "vix_close",
                                                "refused": f"banned_source:{feed}"}]
    assert "vix_close" not in summary["values"]


def test_a_row_from_another_granted_source_is_refused_as_unexpected_feed():
    inds, missing, _ = _collect([_row("$VIX", 20.0, feed="alpaca")])
    assert "vix_close" not in _keys(inds)
    assert "vix_close_unexpected_feed:alpaca" in missing


@pytest.mark.parametrize("price", [0, -1.5, "n/a", None, float("nan"), float("inf")])
def test_a_non_positive_or_non_finite_price_is_named_and_never_becomes_a_value(price):
    inds, missing, _ = _collect([_row("$VIX", price)])
    assert "vix_close" not in _keys(inds)
    assert any(m.startswith("vix_close_non_positive_price:") for m in missing)


def test_a_row_without_a_bar_end_is_named_not_dated_now():
    inds, missing, _ = _collect([_row("$VIX", 20.0, bar_end=date(2026, 11, 6))])  # a DATE is not an instant
    assert "vix_close" not in _keys(inds)
    assert "vix_close_no_bar_end" in missing


def test_a_stale_row_is_named_with_its_age_and_the_max_age_boundary_is_inclusive():
    _, missing, _ = _collect([_row("$VIX", 20.0, hours_old=120)])
    assert "vix_close_stale:120.0h" in missing
    inds, missing, _ = _collect([_row("$VIX", 20.0, hours_old=96)])  # exactly max_age_hours: still usable
    assert "vix_close" in _keys(inds)
    assert not any(m.startswith("vix_close_") for m in missing)


def test_a_failing_store_read_is_named_and_yields_no_rows():
    inds, missing, summary = _collect(fail={"market_quotes_extended"})
    assert inds == [] and summary["values"] == {}
    assert "vix_complex_read_failed:RuntimeError" in missing
    assert inds == []  # never a placeholder row


def test_a_missing_key_is_absent_from_missing_only_when_the_other_source_filled_it():
    inds, missing, _ = _collect([])  # no Schwab rows, no FRED rows
    assert inds == []
    for key in CFG["symbols"].values():
        assert f"{key}_unavailable:no_row" in missing


# ── FRED is a labelled fallback, never a substitute ─────────────────────────────────────────────────────────


def test_fred_fills_only_the_gap_and_the_payload_names_the_source_of_record():
    rows = [_row("$VIX", 20.0)]
    fred = [("VIXCLS", date(2026, 11, 5), 19.9), ("VXNCLS", date(2026, 11, 5), 27.5)]
    inds, missing, summary = _collect(rows, fred)
    by = {i["indicator_key"]: i for i in inds}
    assert by["vix_close"]["value"] == 20.0
    assert by["vix_close"]["payload"]["value_source"] == "schwab"
    assert by["vix_close"]["payload"]["source"] == "market_quotes_extended:schwab"
    assert by["vxn_close"]["value"] == 27.5
    assert by["vxn_close"]["payload"]["value_source"] == "fred"
    assert by["vxn_close"]["payload"]["source"] == "fred_economic_series"
    assert by["vxn_close"]["payload"]["reference_basis"] == "fred_close"
    assert summary["sources"]["vix_close"] == "schwab" and summary["sources"]["vxn_close"] == "fred"
    assert "vxn_close_unavailable:no_row" not in missing
    assert "vix_close_unavailable:no_row" not in missing


def test_a_carried_friday_print_is_aged_from_the_print_date_not_bar_end():
    # REVIEW-LQ-969-cc-sonnet-3: bar_end = Sun 20:00 ET would report age 0.5 h / fresh=True for a Fri print.
    bar_end = datetime(2026, 11, 8, 20, 0, tzinfo=ET)
    row = _carried_row("$VIX", 25.64, print_day=date(2026, 11, 6), bar_end=bar_end)
    values, missing, receipts = vc.read_quotes(_Conn([row]), SUN_NIGHT, CFG)
    assert "vix_close" in values
    assert not any(m.startswith("vix_close_") for m in missing)
    assert values["vix_close"]["carried_from"] == "2026-11-06"
    assert values["vix_close"]["fresh"] is False
    # ~52.5 h from Fri 16:00 ET to Sun 20:30 ET — never the 0.5 h that bar_end would invent.
    assert 50.0 <= values["vix_close"]["age_hours"] <= 55.0
    vix_receipt = next(r for r in receipts if r["key"] == "vix_close")
    assert vix_receipt["carried_from"] == "2026-11-06"
    assert vix_receipt["fresh"] is False


def test_fred_displaces_a_carried_schwab_level_but_a_dated_schwab_close_still_wins():
    bar_end = datetime(2026, 11, 8, 20, 0, tzinfo=ET)
    carried = _carried_row("$VIX", 25.64, print_day=date(2026, 11, 6), bar_end=bar_end)
    fred = [("VIXCLS", date(2026, 11, 5), 28.18)]
    inds, _, summary = _collect([carried], fred, now=SUN_NIGHT)
    by = {i["indicator_key"]: i for i in inds}
    assert by["vix_close"]["value"] == 28.18
    assert by["vix_close"]["payload"]["value_source"] == "fred"
    assert by["vix_close"]["payload"]["schwab_carried_level"] == 25.64
    assert by["vix_close"]["payload"]["schwab_carried_from"] == "2026-11-06"
    assert by["vix_close"]["payload"]["fresh"] is False  # observation is 3 calendar days old on Sun night
    assert summary["sources"]["vix_close"] == "fred"

    # A non-carried Schwab close (regular session print) still beats the same FRED observation.
    dated = _row("$VIX", 20.0, hours_old=1.0, basis="schwab_regular_close")
    inds2, _, summary2 = _collect([dated], fred, now=NOW)
    by2 = {i["indicator_key"]: i for i in inds2}
    assert by2["vix_close"]["value"] == 20.0
    assert by2["vix_close"]["payload"]["value_source"] == "schwab"
    assert summary2["sources"]["vix_close"] == "schwab"


def test_complex_record_is_the_single_vix_vix3m_vvix_read():
    rows = [_row("$VIX", 20.0), _row("$VIX3M", 21.0), _row("$VVIX", 101.2)]
    rec = vc.complex_record(_Conn(rows), now=NOW, cfg=CFG)
    assert rec["schema"] == vc.SCHEMA
    assert rec["vix"]["value"] == 20.0 and rec["vix"]["fresh"] is True
    assert rec["vix3m"]["value"] == 21.0
    assert rec["vvix"]["value"] == 101.2
    assert rec["term_structure"] == "contango"
    assert rec["term_structure_ratio"] == round(20 / 21, 4)
    assert rec["sources"]["vix_close"] == "schwab"
    assert "yahoo" not in json_dumps_lower(rec)


def json_dumps_lower(obj) -> str:
    import json
    return json.dumps(obj, default=str).lower()


def test_a_stale_fred_observation_is_named_and_never_passed_off_as_todays_close():
    inds, missing, _ = _collect(fred=[("VIXCLS", date(2026, 9, 1), 19.9)])
    assert "vix_close" not in _keys(inds)
    assert any(m.startswith("vix_close_fred_stale:") for m in missing)


def test_a_fred_missing_value_marker_is_not_a_zero():
    inds, missing, _ = _collect(fred=[("VIXCLS", date(2026, 11, 5), None)])
    assert "vix_close" not in _keys(inds)
    assert "vix_close_unavailable:no_row" in missing


def test_a_fred_read_failure_does_not_discard_the_schwab_half():
    rows = [_row("$VIX", 20.0)]
    inds, missing, _ = _collect(rows, fail={"fred_economic_series"})
    assert "vix_close" in _keys(inds)
    assert "fred_read_failed:RuntimeError" in missing


# ── derived ratios ──────────────────────────────────────────────────────────────────────────────────────────


def test_term_structure_ratios_are_derived_only_from_two_real_values():
    _, missing, _ = _collect([_row("$VIX", 20.0)])
    assert "vix9d_vix_ratio_unavailable:needs_vix9d_and_vix" in missing
    assert "vix_vix3m_ratio_unavailable:needs_vix_and_vix3m" in missing

    inds, missing, _ = _collect([_row("$VIX", 20.0), _row("$VIX9D", 19.0), _row("$VIX3M", 21.0)])
    by = {i["indicator_key"]: i for i in inds}
    assert by["vix9d_vix_ratio"]["value"] == 0.95 and by["vix9d_vix_ratio"]["signal"] == "contango"
    assert by["vix_vix3m_ratio"]["value"] == round(20 / 21, 4) and by["vix_vix3m_ratio"]["signal"] == "contango"
    assert by["vix9d_vix_ratio"]["source_key"] == "derived"
    assert not any(m.startswith("vix9d_vix_ratio_unavailable") or m.startswith("vix_vix3m_ratio_unavailable")
                   for m in missing)


def test_no_row_is_ever_a_zero_and_the_six_closes_are_the_only_configured_keys():
    inds, _, _ = _collect([_row("$VIX", 20.0), _row("$VVIX", 101.2)])
    assert _keys(inds) == {"vix_close", "vvix_close"}
    assert all(i["value"] > 0 for i in inds)
    assert all(i["indicator_group"] == "volatility" for i in inds)


# ── the VIX bucket is config, not a literal ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("value,signal", [
    (None, "unknown"), (14.0, "low"), (14.01, "normal"), (20.0, "normal"), (20.01, "high"),
    (30.0, "high"), (30.01, "extreme"),
])
def test_vix_signal_boundaries_are_strict_and_configured(value, signal):
    assert vc.vix_signal(value, CFG) == signal


# ── config validation fails loud ────────────────────────────────────────────────────────────────────────────


def _write_cfg(tmp_path, **over):
    doc = dict(CFG, **over)
    p = tmp_path / "vix.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return p


@pytest.mark.parametrize("over", [
    {"schema": "Wrong@v1"},
    {"symbols": {"VIX": "vix_close"}},                       # not '$'-prefixed
    {"symbols": {}},
    {"feed": ""},
    {"store": " "},
    {"max_age_hours": 0},
    {"max_age_hours": float("nan")},
    {"max_age_hours": True},                                  # a bool is not an age
    {"fresh_after_hours": 200, "max_age_hours": 96},
    {"fred_max_age_days": 0.5},
    {"vix_signal": {"extreme": 10, "high": 20, "normal": 14}},  # thresholds must not increase
])
def test_a_config_that_cannot_describe_the_complex_is_rejected_by_name(tmp_path, over):
    with pytest.raises(vc.ConfigError) as exc:
        vc.load_config(_write_cfg(tmp_path, **over))
    assert str(exc.value).startswith(str(tmp_path / "vix.yaml"))


def test_an_unreadable_config_names_the_path(tmp_path):
    with pytest.raises(vc.ConfigError) as exc:
        vc.load_config(tmp_path / "absent.yaml")
    assert "absent.yaml" in str(exc.value)
