"""The committed browser fixture for e2e/tradeinview-redesign.fixture.mjs is A's pure-builder output.

COVERS = ["scripts/lib/data_broker/trade_journey.py", "scripts/lib/data_broker/trade_calendar.py",
          "scripts/lib/data_broker/trade_replay.py",
          "apps/command-center-v3/e2e/fixtures/tradeinviewRedesign.fixture.json"]

Every value comes from the TradeInView builders run on SYNTHETIC pinned inputs (no production
copy, no live state). The tradeinview-redesign-fixture workflow consumes the JSON; this test
fails when a builder change makes the committed fixture stale. Regenerate with
TRADEINVIEW_WRITE_FIXTURE=1 (writes only the committed fixture path).
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.data_broker import trade_calendar as cal  # noqa: E402
from lib.data_broker import trade_journey as tj  # noqa: E402
from lib.data_broker import trade_replay as rp  # noqa: E402
from lib.data_broker import tradeinview_sources as src  # noqa: E402
import test_tradeinview_projections_20261024 as base  # noqa: E402

FIXTURE = ROOT / "apps/command-center-v3/e2e/fixtures/tradeinviewRedesign.fixture.json"
SCHEMA = ROOT / "config/schemas/tradeinview_projection_v1.schema.json"
NOW = base.NOW
ACCOUNT = "schwab_roth"

TRADES = [
    # Open, latest mark under the working stop -> "Awaiting fill" (stop likely filled, unconfirmed).
    {"trade_id": "open:schwab_roth_ira:TSTA", "symbol": "TSTA", "account": ACCOUNT, "status": "open", "fill_qty": 11,
     "entry_ref": 41, "mark_ref": 39, "mark_at": "2026-11-04T16:59:00Z", "entry_at": "2026-10-28T14:15:00Z"},
    # Open, mark above its stop -> ordinary open row.
    {"trade_id": "open:schwab_roth_ira:TSTB", "symbol": "TSTB", "account": ACCOUNT, "status": "open", "fill_qty": 5,
     "entry_ref": 20, "mark_ref": 19, "mark_at": "2026-11-04T16:59:00Z", "entry_at": "2026-10-29T14:15:00Z"},
    # Closed winning trip used as the Replay "compare with a win" partner.
    {"trade_id": "rt:fixture-ledger-trip-2", "symbol": "TSTB", "account": ACCOUNT, "status": "closed", "fill_qty": 5,
     "entry_ref": 18.0, "exit_ref": 21.0, "entry_at": "2026-10-20T14:15:00Z", "exit_at": "2026-10-27T15:25:00Z",
     "pl_amount": 15.0},
    # Closed trip whose stored replay carries candles / closes / no bars.
    {"trade_id": "rt:fixture-ledger-trip", "symbol": "TSTA", "account": ACCOUNT, "status": "closed", "fill_qty": 11,
     "entry_ref": 41.25, "exit_ref": 43.75, "entry_at": "2026-10-28T14:15:00Z", "exit_at": "2026-11-02T15:25:00Z",
     "pl_amount": 27.5},
]
STOPS = {"TSTA": [{"stop_price": 40, "status": "WORKING", "captured_at": "2026-11-04T16:30:00Z", "account": ACCOUNT}],
         "TSTB": [{"stop_price": 18, "status": "WORKING", "captured_at": "2026-11-04T16:30:00Z", "account": ACCOUNT}]}


def _journeys(ingest_at: str | None, stop_at: str, ledger_at: str | None = None) -> dict:
    """ingest_at=None: no ingest run receipt (today's reality); the chip then reads the ledger store clock."""
    payload = tj.build_trade_journeys(deepcopy(TRADES), inputs={"stops": deepcopy(STOPS), "days": 30}, now=NOW)
    trust = {"trades_at": "2026-11-02T15:25:00Z", "redesign_inputs": {
        "holdings_written_at": "2026-11-04T16:55:00Z",
        "ledger_store": ({"written_at": ledger_at, "rows": 4, "source": tj.LEDGER_STORE_SOURCE} if ledger_at
                         else {"written_at": None, "reason": "transaction ledger store has no schwab_api rows"}),
        "ingest_receipt": ({"status": "ok", "document": {"status": "ok", "finished_at": ingest_at}} if ingest_at
                           else {"status": "missing"}),
        "stop_health_receipt": {"status": "ok", "document": {"status": "ok", "finished_at": stop_at}},
        "registry": {"status": "ok", "document": {"lanes": []}}}}
    return tj._add_redesign_fields(payload, trust, NOW)


def compose() -> dict:
    import lib.cio_market_aware_freshness as freshness
    saved_open, saved_cache = freshness.market_is_open, src._SNAPSHOT_CACHE
    freshness.market_is_open, src._SNAPSHOT_CACHE = (lambda now: True), {}
    try:
        populated = base.snapshot()
        populated["sources"]["schwab_round_trips"]["rows"] = [base.roundtrip(), base.roundtrip(
            id=902, dedupe_key="fixture-ledger-trip-3", symbol="TSTB", exit_time="2026-11-03T15:00:00+00:00",
            net_pnl=-12.0, exit_price=40.16)]
        populated["sources"]["catalyst_events"]["rows"] = [{
            "id": 1, "symbol": "TSTA", "catalyst_type": "catalyst", "published_at": "2026-11-02T15:00:00Z",
            "headline": "Fixture publication", "source": "fixture publisher"}]
        missing = base.snapshot()
        missing["sources"]["schwab_round_trips"] = {"status": "unavailable", "rows": [], "truncated": False,
                                                    "reason": "fixture source unavailable"}
        closes = base.replay_snapshot()
        closes["replay_bars"] = {"status": "ok", "table": "ticker_prices", "rows": [
            {"time": "2026-10-28T00:00:00Z", "close": 43}, {"time": "2026-11-02T00:00:00Z", "close": 43.75}]}
        no_bars = base.replay_snapshot()
        no_bars["replay_bars"] = {"status": "ok", "table": "market_ohlcv_bars", "rows": []}
        winner = base.replay_snapshot()
        winner["sources"]["schwab_round_trips"]["rows"] = [base.roundtrip(
            id=902, dedupe_key="fixture-ledger-trip-2", symbol="TSTB", entry_time="2026-10-20T14:15:00+00:00",
            exit_time="2026-10-27T15:25:00+00:00", qty=5, entry_price=18.0, exit_price=21.0, net_pnl=15.0,
            pnl_pct=(21 / 18 - 1) * 100)]
        winner["replay_bars"] = {"status": "ok", "table": "market_ohlcv_bars", "rows": [
            {"time": "2026-10-20T00:00:00Z", "open": 18, "high": 19, "low": 17.5, "close": 18.5},
            {"time": "2026-10-23T00:00:00Z", "open": 18.5, "high": 20.5, "low": 18.2, "close": 20},
            {"time": "2026-10-27T00:00:00Z", "open": 20, "high": 21.5, "low": 19.8, "close": 21}]}
        month = {"month": "2026-11"}
        return {
            "_comment": "SYNTHETIC pinned inputs run through the TradeInView builders; regenerate via "
                        "tests/test_tradeinview_redesign_fixture_20261025.py. Not production data.",
            "clock": NOW.isoformat(),
            "journeys": {"fresh": _journeys("2026-11-04T16:45:00Z", "2026-11-04T16:50:00Z"),
                         "stale": _journeys("2026-11-01T16:45:00Z", "2026-11-01T16:00:00Z"),
                         "ledger_store": _journeys(None, "2026-11-04T16:50:00Z", "2026-11-04T16:48:02+00:00"),
                         "no_ledger": _journeys(None, "2026-11-04T16:50:00Z")},
            "calendar": {"populated": cal.build_calendar(populated, month, now=NOW),
                         "empty": cal.build_calendar(base.snapshot(), month, now=NOW),
                         "missing": cal.build_calendar(missing, month, now=NOW)},
            "replay": {"bars": rp.build_replay(base.replay_snapshot(), {"trade_id": "rt:fixture-ledger-trip"}, now=NOW),
                       "closes": rp.build_replay(closes, {"trade_id": "rt:fixture-ledger-trip"}, now=NOW),
                       "missing": rp.build_replay(no_bars, {"trade_id": "rt:fixture-ledger-trip"}, now=NOW),
                       "winner": rp.build_replay(winner, {"trade_id": "rt:fixture-ledger-trip-2"}, now=NOW)},
        }
    finally:
        freshness.market_is_open, src._SNAPSHOT_CACHE = saved_open, saved_cache


def _encode(doc: dict) -> str:
    return json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def test_committed_browser_fixture_is_current_builder_output():
    doc = compose()
    if os.environ.get("TRADEINVIEW_WRITE_FIXTURE") == "1":
        FIXTURE.write_text(_encode(doc), encoding="utf-8")
    assert FIXTURE.read_text(encoding="utf-8") == _encode(doc), "regenerate with TRADEINVIEW_WRITE_FIXTURE=1"


def test_fixture_covers_every_browser_state_and_validates_against_the_projection_schema():
    sys.path.insert(0, str(ROOT))
    from tests.helpers.tradeinview_schema import validate as schema_validate
    doc = compose()
    payloads = [*doc["journeys"].values(), *doc["calendar"].values(), *doc["replay"].values()]
    for payload in payloads:
        schema_validate(payload)  # stdlib Draft 2020-12 subset; also jsonschema (must agree) where installed
        assert payload["provider_calls"] == payload["writes"] == 0
    kinds = {(j["status"], j["exit_cause"]["kind"]) for j in doc["journeys"]["fresh"]["journeys"]}
    assert {("open", "stop_likely_filled"), ("open", "open"), ("closed", "unknown")} <= kinds
    assert doc["calendar"]["populated"]["summary"]["known_trade_count"] > 0
    assert doc["calendar"]["empty"]["summary"]["known_trade_count"] == 0
    assert doc["calendar"]["missing"]["summary"]["coverage"]["status"] != "COMPLETE"
    assert [doc["replay"][k]["kind"] for k in ("bars", "closes", "missing", "winner")] == ["candles", "closes", "none", "candles"]
    wins = [j for j in doc["journeys"]["fresh"]["journeys"]
            if j["trade_id"] != "rt:fixture-ledger-trip" and (j["pl"]["amount"] or 0) > 0]
    assert [j["trade_id"] for j in wins] == ["rt:fixture-ledger-trip-2"]  # the only Compare partner has stored bars


def test_ledger_chip_variants_store_clock_and_truly_absent():
    doc = compose()["journeys"]
    chip = {c["key"]: c for c in doc["ledger_store"]["freshness_chips"]}["ledger_sync"]
    assert chip["at"] == "2026-11-04T16:48:02+00:00" and chip["source_label"] == "ledger row write"
    absent = {c["key"]: c for c in doc["no_ledger"]["freshness_chips"]}["ledger_sync"]
    assert absent["value"] == "Not measured" and "no schwab_api rows" in absent["missing_reason"]
