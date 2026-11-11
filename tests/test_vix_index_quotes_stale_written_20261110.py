"""LQ-20261107-1872: a real VIX print newer than the store is kept and labelled stale -- never discarded, never fresh.

Production 2026-11-10 20:00 ET (``d:vix-index-quotes-schwab:live:20261110T2000``, live on 763b3a776): Schwab returned
$VIX / $VIX9D / $VIX3M printed 16:15 ET, age 225 min. ``market_quotes`` held NO row for any of the three symbols, and
the lane graded all three ``stale_print`` -> ``inserted 0``. A real print newer than anything stored was thrown away
only because it was older than ``max_trade_age_minutes``, so the headline kept reading the 03:45 ET overnight print.

The rule (constitution: last-known-good with age; unknown beats wrong): a print NEWER than the stored one is written
once, with its TRUE print time, and marked ``written_stale`` -- it can never read as FRESH. A print that is not newer
than the stored one is never written. ``produced_count`` counts these rows, and the surface still reads STALE with the
real print time (``16:15 ET``), not the older overnight print.

Synthetic values only (public repo). No DB, no network, no Schwab.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import vix_index_quotes_schwab as lane  # noqa: E402
from lib import lane_last_receipt as lr  # noqa: E402
from lib import n8n_output_verdict as ov  # noqa: E402
from lib import vix_headline as vh  # noqa: E402
from lib.market_regime import vix_complex as vc  # noqa: E402

ET = ZoneInfo("America/New_York")
CFG = lane.load_config()
NOW = datetime(2026, 11, 10, 20, 0, 40, tzinfo=ET)      # the 20:00 fire
PRINT = datetime(2026, 11, 10, 16, 15, 1, tzinfo=ET)   # Cboe's last print of the day; age 225 min at NOW
SYMS = ("$VIX", "$VIX9D", "$VIX3M")


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _payload(prints: dict[str, tuple[float, datetime]]) -> dict:
    return {s: {"assetMainType": "INDEX", "symbol": s, "quote": {"lastPrice": p, "tradeTime": _ms(t)}}
            for s, (p, t) in prints.items()}


def _stale_payload(at: datetime = PRINT) -> dict:
    return _payload({"$VIX": (18.0, at), "$VIX9D": (17.5, at), "$VIX3M": (19.5, at)})


def _contract_rule() -> dict:
    doc = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))
    for c in doc["contracts"]:
        if c.get("id") == lane.LANE_ID:
            return c["expected_output"]
    raise AssertionError(f"no health contract for {lane.LANE_ID}")


# ── the defect: a real print newer than the store is discarded ───────────────────────────────────────────────


def test_a_real_print_newer_than_the_empty_store_is_written_with_its_true_print_time():
    rows, entries = lane.parse_payload(_stale_payload(), NOW, CFG, {s: None for s in SYMS})
    assert [e["status"] for e in entries] == ["written_stale"] * 3
    assert [(r["symbol"], r["price"], r["fetched_at"]) for r in rows] == [
        ("$VIX", 18.0, PRINT), ("$VIX9D", 17.5, PRINT), ("$VIX3M", 19.5, PRINT)]
    # The row's clock is the print's, never the fire's: a consumer computing an age must see 225 min, not 0.
    assert all(r["fetched_at"] == PRINT and r["fetched_at"] < NOW for r in rows)
    assert [e["age_minutes"] for e in entries] == [225.7, 225.7, 225.7]


def test_the_stale_status_is_a_write_not_a_skip_and_is_never_called_written():
    """The whole point of a distinct token: `written` means fresh, `written_stale` means kept-but-stale."""
    _, entries = lane.parse_payload(_stale_payload(), NOW, CFG, {})
    assert {e["status"] for e in entries} == {"written_stale"}
    assert "written" not in {e["status"] for e in entries}


def test_a_stale_print_the_store_already_holds_is_not_written_again():
    rows, entries = lane.parse_payload(_stale_payload(), NOW, CFG, {s: PRINT for s in SYMS})
    assert (rows, [e["status"] for e in entries]) == ([], ["stale_print"] * 3)


def test_a_print_older_than_the_stored_one_is_never_written():
    rows, entries = lane.parse_payload(_stale_payload(), NOW, CFG, {s: PRINT + timedelta(minutes=15) for s in SYMS})
    assert (rows, [e["status"] for e in entries]) == ([], ["stale_print"] * 3)


def test_a_print_inside_the_age_line_still_takes_the_ordinary_written_path():
    at = NOW - timedelta(minutes=3)
    rows, entries = lane.parse_payload(_stale_payload(at), NOW, CFG, {s: None for s in SYMS})
    assert [e["status"] for e in entries] == ["written"] * 3
    assert all(r["fetched_at"] == at for r in rows)


# ── the fire: ok, three rows, produced_count counts them ─────────────────────────────────────────────────────


def test_the_production_fire_shape_writes_three_rows_and_reports_ok():
    wrote: list = []
    r = lane.run(cfg=CFG, now=NOW, fetch=lambda _s: _stale_payload(), read_last=lambda s: {x: None for x in s},
                 write=lambda rows: (wrote.append(list(rows)) or {"rows_written": len(rows)}), dry_run=False)
    assert r["status"] == "ok"
    assert r["inserted"] == 3
    assert [e["status"] for e in r["symbols"]] == ["written_stale"] * 3
    assert len(wrote) == 1 and [row["symbol"] for row in wrote[0]] == list(SYMS)
    assert lane.lane_outcome(r) == (True, None)


def test_the_next_fire_re_reads_the_same_print_and_writes_nothing():
    """After the first stale write, the 15-min ticks must not append the same print again."""
    wrote: list = []
    r = lane.run(cfg=CFG, now=NOW + timedelta(minutes=15), fetch=lambda _s: _stale_payload(),
                 read_last=lambda s: {x: PRINT for x in s}, write=lambda rows: (wrote.append(rows) or {}),
                 dry_run=False)
    assert (wrote, r["inserted"], r["status"]) == ([], 0, "vix_stale_print")
    assert lane.lane_outcome(r) == (True, "cboe_not_calculating")


def test_the_lane_receipt_counts_the_written_stale_rows_as_produced(monkeypatch):
    """produced_count is rows inserted, and these rows were inserted: the contract must grade the fire `produced`."""
    captured: dict = {}

    def fake_write_receipt(lane_id, **kw):
        captured.update({"lane_id": lane_id, **kw})

    monkeypatch.setattr(lr, "write_lane_receipt", fake_write_receipt)
    r = lane.run(cfg=CFG, now=NOW, fetch=lambda _s: _stale_payload(), read_last=lambda s: {x: None for x in s},
                 write=lambda rows: {"rows_written": len(rows)}, dry_run=False)
    lane._write_receipt(r, NOW.isoformat())
    assert (captured["ok"], captured["produced_count"], captured["empty_reason"]) == (True, 3, None)
    assert captured["skipped_reasons"] is None  # a written_stale row is written, not skipped
    run_id = f"d:{lane.LANE_ID}:live:TEST1872"
    monkeypatch.setenv(lr.RUN_ID_ENV, run_id)
    monkeypatch.setenv(lr.RUN_MODE_ENV, "live")
    monkeypatch.delenv(lr.RUN_ATTEMPT_ENV, raising=False)
    doc = lr.build_receipt(lane.LANE_ID, ok=True, exit_code=0, started_at=NOW.isoformat(),
                           script="vix_index_quotes_schwab.py", summary=captured["summary"],
                           produced_count=3, attempted_count=3, skipped_reasons=None, empty_reason=None)
    v = ov.evaluate(_contract_rule(), doc, run_id=run_id, lane_id=lane.LANE_ID, mode="live")
    assert (v["verdict"], v["produced_count"]) == ("produced", 3)


def test_a_dry_run_lists_the_rows_it_would_write_and_calls_no_writer():
    wrote: list = []
    r = lane.run(cfg=CFG, now=NOW, fetch=lambda _s: _stale_payload(), read_last=lambda s: {x: None for x in s},
                 write=lambda rows: (wrote.append(rows) or {}), dry_run=True)
    assert (wrote, r["inserted"], r["would_insert"], r["dry_run"]) == ([], 0, 3, True)
    assert [e["status"] for e in r["symbols"]] == ["written_stale"] * 3


# ── the surface: STALE, with the real print time, on the row the lane wrote ──────────────────────────────────


class _Conn:
    """The two store reads ``vix_complex.read_quotes`` issues, answered from in-memory rows."""

    def __init__(self, extended: list, continuous: list):
        self.extended, self.continuous, self._rows = extended, continuous, []

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self._rows = list(self.continuous if "market_quotes WHERE" in sql else self.extended)

    def fetchall(self):
        return list(self._rows)

    def rollback(self):
        pass


def _headline_for(store_rows: list) -> dict:
    vcfg = vc.load_config()
    conn = _Conn(extended=[("$VIX", 19.8, "overnight", None, datetime(2026, 11, 10, 8, 45, tzinfo=timezone.utc),
                          "schwab_index_level", "schwab")], continuous=store_rows)
    values, missing, _ = vc.read_quotes(conn, NOW, vcfg)
    # The other configured symbols are not in this fixture; only the VIX leg has to resolve here.
    assert not [m for m in missing if m.startswith("vix_close")], missing
    leg = {"value": values["vix_close"]["value"], "source": f"{values['vix_close']['source']}:$VIX",
           "as_of": values["vix_close"]["as_of"], "age_hours": values["vix_close"]["age_hours"]}
    return vh.from_record({"vix": leg}, now=NOW, stale_after_hours=float(vcfg["fresh_after_hours"]),
                          session_fresh_after_minutes=vcfg.get("session_fresh_after_minutes"))


def test_the_surface_keeps_reading_stale_with_the_real_print_time_not_the_overnight_print():
    head = _headline_for([("$VIX", 18.0, "continuous", None, PRINT, "schwab_index_quote_continuous", "schwab")])
    assert (head["vix"], head["vix_state"]) == (18.0, "STALE")
    assert "16:15 ET" in head["vix_reason"] and "min ago" in head["vix_reason"]
    assert head["vix_source"] == "market_quotes:schwab:$VIX"
    assert head["vix_stale"] is True


def test_the_continuous_source_is_admissible_to_the_header_monitor():
    """Without this the monitor would read a newer continuous print as BROKEN header_source_inadmissible."""
    import header_market_freshness_health as hmf  # noqa: PLC0415

    assert "market_quotes:schwab:$VIX" in hmf.ADMISSIBLE_VIX_SOURCES


def test_before_the_fix_the_surface_read_the_older_overnight_print():
    """The control: no continuous row -> the headline still shows the 03:45 ET print. That is the discarded value."""
    head = _headline_for([])
    assert (head["vix"], head["vix_state"]) == (19.8, "STALE")
    assert "08:45 ET" in head["vix_reason"] or "03:45 ET" in head["vix_reason"]


@pytest.mark.parametrize("stored,age_min,expected", [
    (None, 225.6, "written_stale"),
    (PRINT, 225.6, "stale_print"),
    (PRINT + timedelta(minutes=15), 225.6, "stale_print"),
    (None, 3.0, "written"),
    (PRINT - timedelta(minutes=15), 3.0, "written"),
])
def test_the_status_table_is_the_one_the_docstring_states(stored, age_min, expected):
    at = PRINT if age_min > 100 else NOW - timedelta(minutes=age_min)
    rows, entries = lane.parse_payload(_payload({"$VIX": (18.0, at)}), NOW, CFG,
                                       {"$VIX": stored, "$VIX9D": None, "$VIX3M": None})
    assert entries[0]["status"] == expected
    assert len(rows) == (1 if expected.startswith("written") else 0)
