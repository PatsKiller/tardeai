"""Delisted / inactive names (operator 2026-10-26: "remove SRNE and any delisted").

Synthetic tickers only (public repo) apart from the SRNE literal the operator named, which lives in
config/delisted_symbols.json. No DB (stub query functions), no network, every write under tmp_path.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import delisted_symbols as ds  # noqa: E402
from scripts.lib.prospectus import pipeline as pl  # noqa: E402
from scripts.lib.prospectus import store  # noqa: E402
import watch_archive_delisted as wad  # noqa: E402

REF = date(2026, 10, 23)  # a Friday


def _bars(closes, end=REF):
    days, d = [], end
    while len(days) < len(closes):
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return [{"price_date": x.isoformat(), "close": c} for x, c in zip(reversed(days), closes)]


CFG = ds.load_config()


# ── policy file ──────────────────────────────────────────────────────────────────────────────────────────────
def test_policy_names_srne_with_a_reason_and_every_threshold_is_config():
    srne = [r for r in CFG["explicit"] if r["symbol"] == "SRNE"]
    assert srne and "delisted" in srne[0]["reason"].lower() and srne[0]["since"]
    assert int(CFG["no_price_sessions"]) > 0 and float(CFG["near_zero_close_usd"]) > 0
    assert 0 < float(CFG["terminal_collapse"]["max_ratio_to_prior_median"]) < 1
    assert (ROOT / "config/delisted_symbols.json").read_bytes().count(b"\r") == 0


# ── detectors ────────────────────────────────────────────────────────────────────────────────────────────────
def test_explicit_list_wins_even_with_healthy_bars():
    v = ds.classify("srne", bars=_bars([5.0] * 30), flags=None, cfg=CFG, today=REF)
    assert v["code"] == "explicit"


def test_identity_flags_exclude():
    assert ds.classify("ZZD1", bars=_bars([5.0] * 30), flags={"delisted": True}, cfg=CFG, today=REF)["code"] == "identity"
    assert ds.classify("ZZD1", bars=_bars([5.0] * 30), flags={"listing_status": "delisted"}, cfg=CFG,
                       today=REF)["code"] == "identity"
    assert ds.classify("ZZD1", bars=_bars([5.0] * 30), flags={"listing_status": "ACTIVE"}, cfg=CFG, today=REF) is None


def test_no_prices_for_n_sessions_and_no_bars_is_a_gap_not_a_delisting():
    n = int(CFG["no_price_sessions"])
    old_end = REF - timedelta(days=(n + 3) * 7 // 5 + 2)
    v = ds.classify("ZZD2", bars=_bars([5.0] * 30, end=old_end), flags=None, cfg=CFG, today=REF)
    assert v and v["code"] == "no_prices"
    assert ds.classify("ZZD2", bars=_bars([5.0] * 30, end=REF - timedelta(days=3)), flags=None, cfg=CFG, today=REF) is None
    assert ds.classify("ZZD2", bars=[], flags=None, cfg=CFG, today=REF) is None


def test_near_zero_and_terminal_collapse():
    assert ds.classify("ZZD3", bars=_bars([0.30] * 25 + [0.0001]), flags=None, cfg=CFG, today=REF)["code"] == "near_zero"
    assert ds.classify("ZZD4", bars=_bars([40.0] * 25 + [0.5]), flags=None, cfg=CFG, today=REF)["code"] == "terminal"
    # a hard but tradable fall (-60%) is not terminal
    assert ds.classify("ZZD5", bars=_bars([40.0] * 25 + [16.0]), flags=None, cfg=CFG, today=REF) is None


def test_never_exclude_overrides_every_detector():
    cfg = dict(CFG, never_exclude=["ZZD3"])
    assert ds.classify("ZZD3", bars=_bars([0.30] * 25 + [0.0001]), flags={"delisted": True}, cfg=cfg, today=REF) is None


def test_reference_is_the_freshest_house_close_so_an_ingest_outage_excludes_nothing():
    stale = REF - timedelta(days=60)
    bars = {"ZZA1": _bars([5.0] * 30, end=stale), "ZZA2": _bars([7.0] * 30, end=stale)}
    out = ds.detect(["ZZA1", "ZZA2"], bars_fn=bars.get, cfg=CFG)
    assert out["excluded"] == {} and out["reference_date"] == stale.isoformat()
    bars["ZZA3"] = _bars([9.0] * 30, end=REF)
    out = ds.detect(["ZZA1", "ZZA2", "ZZA3"], bars_fn=bars.get, cfg=CFG)
    assert set(out["excluded"]) == {"ZZA1", "ZZA2"} and all(v["code"] == "no_prices" for v in out["excluded"].values())


def test_a_bars_read_error_never_excludes():
    def boom(sym):
        raise RuntimeError("db down")
    out = ds.detect(["ZZE1"], bars_fn=boom, cfg=CFG, today=REF)
    assert out["excluded"] == {} and "ZZE1" in out["errors"]


def test_house_flags_reads_the_position_store_and_identity_registry():
    flags = ds.house_flags(holdings_doc={"holdings": [{"symbol": "zzf1", "delisted": True}, {"symbol": "ZZF2"}]},
                           identity_doc={"by_symbol": {"ZZF3": "g3"}, "entities": {"g3": {"listing_status": "INACTIVE"}}})
    assert flags == {"ZZF1": {"delisted": True, "source": "position store"}, "ZZF3": {"listing_status": "INACTIVE"}}


def test_detector_never_writes_or_deletes_price_rows():
    src = (ROOT / "scripts/lib/delisted_symbols.py").read_text()
    for bad in ("DELETE", "UPDATE ", "INSERT", "place_order", "send_telegram"):
        assert bad not in src


# ── prospectus universe ──────────────────────────────────────────────────────────────────────────────────────
class Src:
    def __init__(self, root):
        self.state_root = Path(root)
        self._bars = {"ZZH1": _bars([50.0] * 30), "ZZH2": _bars([0.4] * 25 + [0.0001]),
                      "SRNE": _bars([0.3] * 30), "ZZW1": _bars([20.0] * 30), "ZZW2": []}

    def holdings(self):
        return {"ZZH1": {"market_value": 1000.0}, "ZZH2": {"market_value": 1.0}, "SRNE": {"market_value": 0.2}}

    def watch_symbols(self):
        return ["ZZW1", "ZZW2"]

    def bars(self, sym, days=1100):
        return self._bars.get(sym, [])


@pytest.fixture(autouse=True)
def _fresh_memo():
    pl._DELISTED_MEMO.update(sources=None, verdicts={}, reference=None)
    yield


def test_plan_universe_drops_delisted_names(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "holdings_ranked", lambda held: sorted(((s, float(r["market_value"])) for s, r in held.items()),
                                                                    key=lambda x: -x[1]), raising=False)
    rows = pl.plan_universe(Src(tmp_path), {"premium_top_n": 1})
    syms = [r["symbol"] for r in rows]
    assert "SRNE" not in syms and "ZZH2" not in syms
    assert {"ZZH1", "ZZW1", "ZZW2"} <= set(syms)  # ZZW2 has no bars: a gap, kept


def test_operator_named_symbols_are_still_excluded(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "holdings_ranked", lambda held: [], raising=False)
    rows = pl.plan_universe(Src(tmp_path), {}, symbols=["SRNE", "ZZW1"])
    assert [r["symbol"] for r in rows] == ["ZZW1"]


def test_existing_reports_are_marked_and_queue_rows_dropped_never_deleted(tmp_path):
    base = tmp_path / "data/prospectus"
    for sym in ("SRNE", "ZZH1"):
        store.update_index(base, sym, status="ready", version="20261020T000000Z", next_due="2026-11-20")
    store.enqueue(base, [{"symbol": "SRNE", "scope": "holding"}, {"symbol": "ZZH1", "scope": "holding"}])
    logs = []
    out = pl.apply_delisted_exclusions(base, Src(tmp_path), log=logs.append)
    idx = store.read_index(base)["items"]
    assert set(out) == {"SRNE"}
    assert idx["SRNE"]["status"] == ds.STATUS and idx["SRNE"]["status_label"] == "delisted — excluded"
    assert idx["SRNE"]["version"] == "20261020T000000Z" and idx["SRNE"]["next_due"] is None
    assert idx["ZZH1"]["status"] == "ready"
    assert [r["symbol"] for r in store.read_queue(base)["items"]] == ["ZZH1"]
    assert any("EXCLUDED SRNE" in m for m in logs)


def test_no_new_report_is_stored_for_an_excluded_name(tmp_path):
    base = tmp_path / "data/prospectus"
    mem = pl.persist_doc(base, "SRNE", "holding", {"name": "x"}, None, "20261026T000000Z", {}, {},
                         now=datetime(2026, 10, 26, tzinfo=timezone.utc), memory_root=tmp_path, log=lambda _m: None)
    assert mem["outcome"] == "skipped" and not (base / "SRNE" / "20261026T000000Z").exists()


def test_run_queue_marks_before_processing(tmp_path, monkeypatch):
    base = tmp_path / "data/prospectus"
    store.update_index(base, "SRNE", status="ready")
    store.enqueue(base, [{"symbol": "SRNE", "scope": "holding"}])
    called = []
    out = pl.run_queue(base, Src(tmp_path), {"processes": {"standard": "x", "premium": "y"}}, limit=5, holdings={},
                       generate_fn=lambda *a, **k: called.append(1), log=lambda _m: None, batch_enabled=False,
                       memory_root=tmp_path)
    assert out["delisted_excluded"] == ["SRNE"] and out["done"] == [] and not called
    assert store.read_queue(base)["items"] == []


# ── Watch archive script ─────────────────────────────────────────────────────────────────────────────────────
def _watch_db(names):
    def q(sql, params=None, fetch="all"):
        if "operator_starred_symbols" in sql:
            return [{"s": s, "at": None, "ref": None, "label": None} for s in names]
        if "ticker_prices" in sql or "close_price" in sql:
            sym = params[0]
            return [{"price_date": date.fromisoformat(b["price_date"]), "close_price": b["close"]}
                    for b in Src("/nonexistent")._bars.get(sym, [])]
        return []
    return q


def test_watch_script_dry_run_lists_delisted_names_and_writes_nothing():
    q = _watch_db(["ZZW1", "SRNE", "ZZH2"])
    out = wad.plan(db_query=q, state_root=Path("/nonexistent"), flags={})
    assert [r["symbol"] for r in out["delisted"]] == ["SRNE", "ZZH2"]
    assert {r["code"] for r in out["delisted"]} == {"explicit", "near_zero"}


def test_watch_archive_and_undo_use_the_my_watchlist_command_without_deleting():
    calls, statuses = [], []

    def command(body, **kw):
        calls.append((body, kw))
        return {"ok": True, "event_type": "watch_mine_removed" if body["action"] == "remove" else "watch_mine_added",
                "archived_directives": [77] if body["action"] == "remove" else []}

    res = wad.archive([{"symbol": "SRNE", "code": "explicit", "reason": "r"}], db_query=None, db_execute=None,
                      command=command)
    body, kw = calls[0]
    assert body["action"] == "remove" and kw["star_write"] is False and kw["by"] == wad.ACTOR
    assert "delisted — excluded" in body["note"] and res[0]["archived_directives"] == [77]
    receipt = {"schema": wad.RECEIPT_SCHEMA, "archived": res}
    back = wad.undo(receipt, db_query=None, db_execute=None, command=command,
                    set_status=lambda q, did, st, source: statuses.append((did, st)))
    assert back[0]["ok"] and statuses == [(77, "active")] and calls[-1][0]["action"] == "add"
    assert calls[-1][1]["star_write"] is False


def test_mine_command_star_write_false_keeps_the_star_row(monkeypatch):
    import api_v3_watch_commands as cmd
    monkeypatch.setattr(cmd, "_principal", lambda: "")
    ex = []
    out = cmd.post_mine_decision({"symbol": "ZZW9", "action": "remove", "note": "delisted"},
                                 db_execute=lambda sql, p=None: ex.append(sql), db_query=lambda *a, **k: [],
                                 by="watch_archive_delisted", star_write=False)
    assert out["ok"] and out["by"] == "watch_archive_delisted"
    assert not any("operator_starred_symbols" in s for s in ex)
    assert ex[-1].startswith("INSERT INTO watchlist_events")


def test_watch_script_is_dry_run_by_default():
    src = (ROOT / "scripts/watch_archive_delisted.py").read_text()
    assert 'if not args.apply:' in src and '"writes": "none"' in src
    for bad in ("DELETE", "place_order", "send_telegram"):
        assert bad not in src
