"""Prospectus accuracy auditor (standing QA after each run window; accuracy audit 2026-10-26).

The auditor recomputes a written report from synthetic primary stores (position store, stop observations, closes,
ex-date history, journal); the CLI writes only under a temp state root; the monthly Opus sample is stubbed and
capped. Synthetic tickers (ZZ*), accounts and amounts only (public repo); no DB, no token store, no network.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import accuracy_audit as aa  # noqa: E402
from scripts.lib.prospectus import blocks as bk  # noqa: E402
import prospectus_accuracy_audit as cli  # noqa: E402

NOW = datetime(2026, 10, 26, 22, tzinfo=timezone.utc)


def _calendar_rows(start: date, n_days: int, *, px=100.0, step=0.1) -> list[dict]:
    out, last = [], px
    for i in range(n_days):
        d = start + timedelta(days=i)
        if bk.is_session(d):
            last = round(last + step, 4)
        out.append({"price_date": d.isoformat(), "close": last})
    return out


# ── the auditor, against synthetic primary stores ─────────────────────────────────────────────────────────────────
def _primary(**kw):
    base = dict(positions=lambda s: [{"account": "fixture_ira", "shares": 10.0, "cost_basis": 500.0}],
                stop_rows=lambda s: [{"account": "fixture_ira", "symbol": s, "order_id": "1", "stop_price": 55.0,
                                      "status": "awaiting_stop_condition", "captured_at": "2026-10-26T20:00:00"}],
                closes=lambda s: [(r["price_date"], r["close"]) for r in _calendar_rows(date(2025, 10, 27), 365, px=50.0)],
                dividends=lambda s: [], dividend_data=lambda s: {}, finviz=lambda s: None, fred=lambda sid: [],
                trades=lambda s: [], stop_resolver=lambda a, s, rows: {"stop_price": 55.0, "stop_state": "active"})
    base.update(kw)
    return aa.Primary(**base)


def _doc(**over):
    s = bk._series(_calendar_rows(date(2025, 10, 27), 365, px=50.0))
    last = s[-1][1]
    doc = {"symbol": "ZZAU", "scope": "holding", "version": "v", "facts": [
        {"id": "F1", "label": "Shares held (all accounts)", "value": 10.0},
        {"id": "F2", "label": "Average cost $", "value": 50.0},
        {"id": "F3", "label": "Market value $", "value": round(10 * last, 2)},
        {"id": "F4", "label": "Unrealized P/L $", "value": round(10 * last - 500, 2)},
        {"id": "F5", "label": "Last close", "value": last, "as_of": s[-1][0]},
        {"id": "F6", "label": "Recorded protective stop level (fixture_ira, broker_resting, active)", "value": 55.0}],
        "blocks": {"relative_performance": {"returns": [{"name": "ZZAU", **{w: bk.window_return(s, w) for w in ("1W", "1M", "3M", "YTD", "1Y")}}]}}}
    doc.update(over)
    return doc


def test_auditor_passes_a_consistent_report():
    res = aa.audit(_doc(), _primary(stop_rows=lambda s: [{"account": "fixture_ira", "symbol": s, "order_id": "1",
                                                          "stop_price": 55.0, "status": "working"}]), now=NOW)
    assert [d["code"] for d in res["defects"] if d["severity"] in ("P1",)] == []


def test_auditor_finds_position_stop_and_status_defects():
    doc = _doc()
    doc["facts"][0]["value"] = 12.0                       # wrong shares
    doc["facts"][5]["value"] = 54.0                       # wrong stop
    res = aa.audit(doc, _primary(), now=NOW)
    codes = {d["code"] for d in res["defects"]}
    assert {"position_shares_mismatch", "stop_level_mismatch", "stop_status_unmapped"} <= codes or \
        {"position_shares_mismatch", "stop_level_mismatch"} <= codes


def test_auditor_finds_weekend_inflated_returns_and_bad_dividend():
    doc = _doc()
    raw = _calendar_rows(date(2025, 10, 27), 365, px=50.0)
    ser = [(r["price_date"], r["close"]) for r in raw]
    n = 21  # the old bar-count 1M over a series that still holds weekend rows
    doc["blocks"]["relative_performance"]["returns"][0]["1M"] = round((ser[-1][1] / ser[-1 - n][1] - 1) * 100, 2) + 2.0
    doc["facts"].append({"id": "F9", "label": "Annual dividend per share", "value": 4.0, "as_of": NOW.isoformat()})
    doc["series"] = {"price_1y": ser[-253:]}  # the report's own series still holds weekend rows
    prim = _primary(dividends=lambda s: [{"ex_date": date(2026, 9, 1), "amount": 0.25}, {"ex_date": date(2026, 6, 1), "amount": 0.25},
                                         {"ex_date": date(2026, 3, 1), "amount": 0.25}, {"ex_date": date(2025, 12, 1), "amount": 0.25}])
    codes = {d["code"] for d in aa.audit(doc, prim, now=NOW)["defects"]}
    assert {"return_window_mismatch", "weekend_bars_in_series", "dividend_annual_mismatch"} <= codes


def test_auditor_summary_ranks_by_severity_then_reach():
    results = [{"symbol": "ZZA", "defects": [aa.defect("x", "P2", "missing", "m"), aa.defect("y", "P1", "wrong", "m")]},
               {"symbol": "ZZB", "defects": [aa.defect("x", "P2", "missing", "m")]}]
    summ = aa.summarize(results)
    assert [c["code"] for c in summ["codes"]] == ["y", "x"] and summ["codes"][1]["tickers"] == ["ZZA", "ZZB"]


def test_gap_requests_route_only_data_defects_and_rewrites_are_listed():
    results = [{"symbol": "ZZA", "version": "v1", "defects": [
        aa.defect("dividend_annual_mismatch", "P1", "wrong", "m"), aa.defect("return_window_mismatch", "P1", "wrong", "m"),
        aa.defect("position_shares_mismatch", "P1", "wrong", "m"), aa.defect("options_thesis_empty", "P3", "wrong", "m")]}]
    assert aa.gap_requests(results) == [{"domain": "dividends", "symbol": "ZZA", "codes": ["dividend_annual_mismatch"]}]
    assert aa.rewrite_due(results) == [{"symbol": "ZZA", "version": "v1", "codes": ["position_shares_mismatch"]}]


def test_window_note_is_p2_and_absent_when_clean():
    summ = aa.summarize([{"symbol": "ZZA", "defects": [aa.defect("x", "P1", "wrong", "m")]}])
    assert aa.window_note(summ).startswith("P2 prospectus accuracy: 1 defect class")
    assert aa.window_note(aa.summarize([{"symbol": "ZZA", "defects": [aa.defect("y", "P3", "wrong", "m")]}])) is None


def _store(tmp_path, doc):
    d = tmp_path / "data/prospectus" / doc["symbol"] / "20261026T170000Z"
    d.mkdir(parents=True)
    (d / "prospectus.json").write_text(json.dumps(doc))


def test_cli_dry_run_writes_nothing_and_apply_writes_only_the_accuracy_dir(tmp_path, monkeypatch):
    doc = _doc(generated_at="2026-10-26T17:00:00+00:00", sections=[{"id": "summary", "text": "Synthetic."}])
    doc["facts"][0]["value"] = 12.0
    _store(tmp_path, doc)
    monkeypatch.setattr(cli.aa, "db_primary", lambda q, root: _primary())
    monkeypatch.setattr(cli, "_db_query", lambda: None)
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    assert cli.main(["--state-root", str(tmp_path)]) == 0
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before
    filed = []
    monkeypatch.setattr(cli, "file_gaps", lambda reqs, enqueue=None: filed.extend(reqs) or [])
    assert cli.main(["--state-root", str(tmp_path), "--apply"]) == 0
    new = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if str(p) not in before)
    assert all(p.startswith("data/prospectus/accuracy") for p in new) and "data/prospectus/accuracy/latest.json" in new
    latest = json.loads((tmp_path / "data/prospectus/accuracy/latest.json").read_text())
    assert "position_shares_mismatch" in latest["rewrite_due"][0]["codes"] and latest["note"].startswith("P2 ")


def test_cli_is_read_only_toward_the_db():
    import types
    fake = types.ModuleType("db_adapter")
    fake._execute = lambda sql, params=None, fetch="all": []
    sys.modules["db_adapter"] = fake
    try:
        query = cli._db_query()
        assert query("SELECT 1") == []
        try:
            query("DELETE FROM x")
        except PermissionError:
            pass
        else:
            raise AssertionError("a write statement must be refused")
    finally:
        sys.modules.pop("db_adapter", None)


def test_monthly_review_is_capped_and_dry_by_default(tmp_path):
    doc = _doc(sections=[{"id": "summary", "text": "Synthetic."}], version="v1")
    run = {"results": [{"symbol": "ZZAU", "scope": "holding", "counts": {"P1": 1}}]}
    out = tmp_path / "accuracy"
    plan = cli.run_review(out, run, {"ZZAU": doc}, apply=False, n=3, now=NOW)
    assert plan["sample"] == ["ZZAU"] and plan["reviews"] == [] and not out.exists()
    calls = []

    def fake(prompt):
        calls.append(prompt)
        return '{"issues": [{"section": "summary", "quote": "x", "problem": "unsupported", "severity": "P2"}], "overall": "ok"}', {"cost_usd": 0.5}
    plan = cli.run_review(out, run, {"ZZAU": doc}, apply=True, n=3, now=NOW, review_fn=fake)
    assert len(calls) == 1 and plan["reviews"][0]["issues"][0]["problem"] == "unsupported"
    ledger = json.loads((out / "review_ledger.json").read_text())
    ledger["2026-10"].append({"cost_usd": 1.4})
    (out / "review_ledger.json").write_text(json.dumps(ledger))
    plan = cli.run_review(out, run, {"ZZAU": doc}, apply=True, n=3, now=NOW, review_fn=fake)
    assert len(calls) == 1 and "monthly cap" in plan["stopped"]  # $1.90 spent + $0.45 estimate > $2
