"""Operator-approved follow-ups 2026-10-16.

1. Hermes scalp catalyst research covers the Active Trader hot symbols too (data broker
   lib.data_broker.microstructure.live_symbols, capped) and writes to persistent state with a compat mirror.
3. premarket_watcher dedupes per symbol + filing/event id per day; re-alerts only on a material change.
4. hermes-momentum-catalyst-scalp registry row records the n8n-only cutover (cron line commented by Agent A).

Hermetic: temp dirs, monkeypatched search, no DB, no network, no send.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_momentum_catalyst_researcher as hr  # noqa: E402
from lib import hermes_catalyst_store as store  # noqa: E402

DAY = "2026-10-16"


# ── 1. AT symbols + persistent store ──────────────────────────────────────────

def test_union_keeps_scalp_order_and_caps_at_symbols():
    scalp = [{"symbol": "TCRT"}, "XLAB"]
    at = ["xlab", "IAM", "SHMD", "SDEV", "A", "B", "C", "D", "E", "F"]
    out = hr.union_with_at_symbols(scalp, at, cap=3)
    assert out[:2] == scalp
    assert out[2:] == ["IAM", "SHMD", "SDEV"]
    assert hr.AT_RESEARCH_SYMBOL_CAP == 8 and hr.RESEARCH_DEADLINE_S < 300


def test_at_symbols_come_from_the_data_broker_store(tmp_path, monkeypatch):
    micro = tmp_path / "at" / "micro"
    micro.mkdir(parents=True)
    (micro / "live_symbols.json").write_text(json.dumps({"ts_epoch": 1000.0, "symbols": ["iam", "SHMD"]}))
    monkeypatch.setenv("ACTIVE_TRADER_ALERTS_DIR", str(tmp_path / "at"))
    assert hr.active_trader_hot_symbols(now=1100.0) == ["IAM", "SHMD"]
    assert hr.active_trader_hot_symbols(now=1000.0 + 3600) == []  # stale store -> nothing


def test_store_prefers_persistent_state_and_falls_back(tmp_path, monkeypatch):
    state = tmp_path / "state"
    code = tmp_path / "code"
    monkeypatch.setenv(store.DIR_ENV, str(state))
    legacy = store.legacy_day_file(DAY, code)
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"symbol": "OLD"}\n')
    assert store.day_file_for_read(DAY, code) == legacy
    store.day_file(DAY).parent.mkdir(parents=True)
    store.day_file(DAY).write_text('{"symbol": "NEW"}\n')
    assert store.day_file_for_read(DAY, code) == store.day_file(DAY)
    assert store.read_dirs(code)[0] == state


def test_run_writes_primary_and_mirror_and_seeds_from_legacy(tmp_path, monkeypatch):
    monkeypatch.setattr(hr, "research_ticker", lambda sym, **kw: {
        "symbol": sym, "research_timestamp": "2026-10-16T10:25:00", "catalyst_type": "contract",
        "catalyst_summary": f"{sym} news", "confidence": 0.5, "source_count": 1})
    primary = tmp_path / "state" / "d.jsonl"
    mirror = tmp_path / "code" / "d.jsonl"
    mirror.parent.mkdir(parents=True)
    mirror.write_text(json.dumps({"symbol": "EARLY", "catalyst_type": "earnings"}) + "\n")
    primary.parent.mkdir(parents=True)
    hr.run(["IAM"], dry_run=False, output_path=str(primary), mirror_path=str(mirror), max_total_sources=40)
    rows = [json.loads(x) for x in primary.read_text().splitlines()]
    assert {r["symbol"] for r in rows} == {"EARLY", "IAM"}
    assert primary.read_text() == mirror.read_text()


def test_run_stops_at_deadline(monkeypatch):
    calls = []
    monkeypatch.setattr(hr, "research_ticker", lambda sym, **kw: calls.append(sym) or {
        "symbol": sym, "catalyst_type": "no_clear_catalyst", "confidence": 0.2, "source_count": 0})
    out = hr.run(["A", "B", "C"], dry_run=True, deadline_s=0.0)
    assert out == [] and calls == []


def test_scalp_list_reader_uses_persistent_store(tmp_path, monkeypatch):
    from lib.data_broker import scalp_list as sl
    monkeypatch.setenv(store.DIR_ENV, str(tmp_path))
    (tmp_path / f"{DAY}_catalysts.jsonl").write_text(
        json.dumps({"symbol": "IAM", "research_timestamp": "2026-10-16T10:25:00-04:00"}) + "\n")
    assert "IAM" in sl._research_records(DAY)


# ── 3. premarket_watcher dedupe ──────────────────────────────────────────────

def _pmw():
    from lib import premarket_dedupe as pmw
    return pmw


def _filing(eid="8-K:0001-26-000001"):
    return {"symbol": "SKYA", "title": "SKYA 8-K Filed Pre-Market: 2026-10-16", "type": "8-K", "event_id": eid}


def test_same_filing_alerts_once_per_day():
    pmw = _pmw()
    state = {"day": DAY, "symbols": {}}
    sent = 0
    for _ in range(12):  # the 2026-10-16 SKYA run: every 15 min 07:01-09:46
        material, state = pmw.select_material([{"symbol": "SKYA", "filings": [_filing()], "surge_count": None}], state)
        sent += bool(material)
    assert sent == 1


def test_new_filing_is_material():
    pmw = _pmw()
    _m, state = pmw.select_material([{"symbol": "SKYA", "filings": [_filing()], "surge_count": None}],
                                    {"day": DAY, "symbols": {}})
    m2, _ = pmw.select_material([{"symbol": "SKYA", "filings": [_filing(), _filing("8-K:0001-26-000002")],
                                  "surge_count": None}], state)
    assert [f["event_id"] for f in m2[0]["filings"]] == ["8-K:0001-26-000002"]


def test_surge_realerts_only_on_material_growth():
    pmw = _pmw()
    _m, state = pmw.select_material([{"symbol": "ABC", "filings": [], "surge_count": 20}], {"day": DAY, "symbols": {}})
    assert pmw.select_material([{"symbol": "ABC", "filings": [], "surge_count": 35}], state)[0] == []
    m, _ = pmw.select_material([{"symbol": "ABC", "filings": [], "surge_count": 40}], state)
    assert m and m[0]["surge_count"] == 40


def test_state_resets_on_a_new_day(tmp_path):
    pmw = _pmw()
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"day": "2026-10-15", "symbols": {"SKYA": {"events": ["x"]}}}))
    assert pmw.load_dedupe_state(p, DAY) == {"day": DAY, "symbols": {}}


def test_render_matches_legacy_block_shape():
    pmw = _pmw()
    blocks = pmw.render_items([{"symbol": "SKYA", "filings": [_filing()], "surge_count": 12}])
    assert blocks == ["PRE-MARKET: SKYA\n  SEC 8-K: SKYA 8-K Filed Pre-Market: 2026-10-16\n  StockTwits: 12 posts/2hr"]


# ── 4. registry row ──────────────────────────────────────────────────────────

def test_registry_row_records_n8n_only_cutover():
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
    row = next(r for r in reg["lanes"] if r.get("lane_id") == "hermes-momentum-catalyst-scalp")
    sch = row["scheduler"]
    assert (sch["kind"], sch["expression"], sch["stage"], sch["cadence"]) == ("n8n", "dispatcher", "cutover",
                                                                             "25 6-15 * * 1-5")
    assert row["scheduler_before_cutover"]["kind"] == "cron"
    assert "N8N-ONLY TEST 2026-10-16" in row["cutover_note"]
    assert row["dispatch"]["mode"] == "live"
