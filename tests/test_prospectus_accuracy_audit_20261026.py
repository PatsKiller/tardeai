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

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import accuracy_audit as aa  # noqa: E402
from scripts.lib.prospectus import blocks as bk  # noqa: E402
from scripts.lib.prospectus import generate as gen  # noqa: E402
from scripts.lib.prospectus.inputs import Bundle  # noqa: E402
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


def test_review_prompt_carries_the_section_prose_from_body_md():
    """The writer stores prose as body_md; the prompt must not ask to audit sentences it does not hold."""
    doc = {"symbol": "ZZDEMO", "verdict_line": "HOLD",
           "sections": [{"id": "summary", "title": "Summary",
                         "body_md": "The book added a small position in ZZDEMO after the pullback."}],
           "facts": []}
    prompt = aa.review_prompt(doc)
    assert "The book added a small position in ZZDEMO after the pullback." in prompt
    # The older aliases still win when a caller supplies one.
    doc["sections"][0]["text"] = "explicit section text"
    prompt = aa.review_prompt(doc)
    assert "explicit section text" in prompt and "after the pullback" not in prompt


def test_review_prompt_redacts_account_names_before_egress():
    """The review prompt goes to an external model: prose that can name an account must not cross."""
    from scripts.lib.account_display import account_label
    name = account_label("schwab_rollover_ira")
    doc = {"symbol": "ZZDEMO", "verdict_line": f"The {name} still holds ZZDEMO.",
           "sections": [{"id": "summary", "title": "Summary",
                         "body_md": f"The {name} added 100 shares of ZZDEMO after the pullback."}],
           "facts": [{"id": "F1", "label": f"Position ({name})", "value": 100}]}
    prompt = aa.review_prompt(doc)
    assert name not in prompt and "Rollover IRA" not in prompt
    # Only the account identity is withheld; the sentence the auditor is asked to check survives.
    assert "added 100 shares of ZZDEMO after the pullback" in prompt
    assert "still holds ZZDEMO" in prompt
    # The same guard covers the older aliases, so no caller can route prose around it.
    doc["sections"][0]["text"] = f"The {name} trimmed the position."
    prompt = aa.review_prompt(doc)
    assert name not in prompt and "trimmed the position" in prompt


def test_review_prompt_redacts_an_account_missing_from_the_registry():
    """A name the writer saw in its own facts is redacted even when the display registry does not list it."""
    doc = {"symbol": "ZZDEMO",
           "sections": [{"id": "summary", "title": "Summary",
                         "body_md": "The Zzsecret Holdings IRA added 100 shares of ZZDEMO after the pullback. "
                                    "The Zzlongsource Stop Account holds the stop."}],
           "facts": [{"id": "F1", "label": "My open position (Zzsecret Holdings IRA): shares", "value": 100},
                     {"id": "F2", "label": "Recorded protective stop level (Zzlongsource Stop Account, "
                                            "stop_last_known / stops.json (cio_truth.stop_for), awaiting_stop_condition)",
                      "value": 50}],
           "blocks": {"my_history": {"open_lots": [{"account": "Zzsecret Holdings IRA", "shares": 100}]}}}
    prompt = aa.review_prompt(doc)
    assert "Zzsecret Holdings IRA" not in prompt
    assert "Zzlongsource Stop Account" not in prompt  # the long stop label is parsed too
    assert "added 100 shares of ZZDEMO after the pullback" in prompt


def test_review_prompt_refuses_egress_when_account_redaction_is_unavailable(monkeypatch):
    """No complete identity snapshot: refuse the outbound call outright (a numbers-only prompt is not certified)."""
    monkeypatch.setattr(aa, "_account_redaction_terms", lambda doc: ())
    doc = {"symbol": "ZZDEMO", "verdict_line": "The synthetic account still holds ZZDEMO.",
           "sections": [{"id": "summary", "title": "Summary",
                         "body_md": "The synthetic account added 100 shares of ZZDEMO."}],
           "facts": [{"id": "F1", "label": "Position (synthetic account)", "value": 100}]}
    with pytest.raises(aa.AccountIdentityUnavailable):
        aa.review_prompt(doc)


def _review_run(doc, tmp_path):
    run = {"results": [{"symbol": doc["symbol"], "scope": doc.get("scope", "watch"), "counts": {}}]}
    return run


def test_identity_snapshot_is_fresh_and_alias_only_is_incomplete(tmp_path, monkeypatch):
    """A warmed cache is not identity evidence: the registry is re-read, and aliases alone are incomplete."""
    from scripts.lib import account_display as ad
    cfg = tmp_path / "names.json"
    cfg.write_text(json.dumps({"names": {"zz_acct": {"name": "Zz Warm Account"}}, "aliases": {}}))
    monkeypatch.setattr(ad, "_CONFIG", cfg)
    ad._load.cache_clear()
    assert "Zz Warm Account" in ad.redaction_terms()
    # Changed on disk after a read: the next snapshot is the new one, not the cached one.
    cfg.write_text(json.dumps({"names": {"zz_acct": {"name": "Zz Renamed Account"}}, "aliases": {}}))
    terms = ad.redaction_terms()
    assert "Zz Renamed Account" in terms and "Zz Warm Account" not in terms
    # Aliases with no account names cannot say which accounts exist: not a complete snapshot.
    cfg.write_text(json.dumps({"names": {}, "aliases": {"zz_alias": "zz_acct"}}))
    assert ad.redaction_terms() == ()
    # Deleted source is unreadable, never "complete".
    cfg.unlink()
    assert ad.redaction_terms() == ()


def test_review_refuses_egress_when_the_identity_source_disappears(tmp_path, monkeypatch):
    """The actual outbound boundary: a registry warmed then removed must not release synthetic private prose."""
    from scripts.lib import account_display as ad
    cfg = tmp_path / "names.json"
    cfg.write_text(json.dumps({"names": {"zz_acct": {"name": "Zz Warm Account"}}, "aliases": {}}))
    monkeypatch.setattr(ad, "_CONFIG", cfg)
    doc = {"symbol": "ZZDEMO", "verdict_line": "The Zz Warm Account still holds ZZDEMO.",
           "sections": [{"id": "summary", "title": "Summary",
                         "body_md": "The Zz Warm Account added 100 shares of ZZDEMO."}],
           "facts": [{"id": "F1", "label": "Position", "value": 100}]}
    assert "Zz Warm Account" not in aa.review_prompt(doc)  # warm and redacted while the source exists
    cfg.unlink()
    calls = []

    def fake(prompt):
        calls.append(prompt)
        return '{"issues": [], "overall": "ok"}', {"cost_usd": 0.4}

    plan = cli.run_review(tmp_path / "accuracy", _review_run(doc, tmp_path), {"ZZDEMO": doc},
                          apply=True, n=1, now=NOW, review_fn=fake)
    assert calls == []  # no outbound call at all
    assert plan["reviews"] and "AccountIdentityUnavailable" in plan["reviews"][0]["error"]


def test_review_refuses_egress_for_an_alias_only_registry(tmp_path, monkeypatch):
    """Aliases without account names are an incomplete snapshot, not permission to send prose."""
    from scripts.lib import account_display as ad
    cfg = tmp_path / "names.json"
    cfg.write_text(json.dumps({"names": {}, "aliases": {"zz_alias": "zz_acct"}}))
    monkeypatch.setattr(ad, "_CONFIG", cfg)
    doc = {"symbol": "ZZDEMO", "verdict_line": "The Zz Aliased Account still holds ZZDEMO.",
           "sections": [{"id": "summary", "title": "Summary",
                         "body_md": "The Zz Aliased Account added 100 shares of ZZDEMO."}],
           "facts": [{"id": "F1", "label": "Position", "value": 100}]}
    calls = []

    def fake(prompt):
        calls.append(prompt)
        return "", {}

    plan = cli.run_review(tmp_path / "accuracy", _review_run(doc, tmp_path), {"ZZDEMO": doc},
                          apply=True, n=1, now=NOW, review_fn=fake)
    assert calls == [] and "AccountIdentityUnavailable" in plan["reviews"][0]["error"]


def test_review_prompt_redacts_account_names_in_mapping_keys_without_collision():
    """Every outgoing text position is sanitized, keys included, and distinct identities never merge."""
    from scripts.lib.account_display import account_label
    name = account_label("schwab_rollover_ira")
    other = account_label("schwab_roth")
    assert name and other and name != other
    doc = {"symbol": "ZZDEMO",
           "sections": [{"id": "summary", "title": "Summary", "body_md": "Nothing to audit here."}],
           "facts": [{"id": "F1", "label": "Position",
                      "value": {name: 111, other: 222, "plain": 333}}]}
    prompt = aa.review_prompt(doc)
    assert name not in prompt and other not in prompt
    assert '"plain"' in prompt
    # Both redacted keys survive with their own values: no silent key collision.
    assert "111" in prompt and "222" in prompt and "333" in prompt
    assert "[account]#1" in prompt and "[account]#2" in prompt


def test_doc_account_terms_harvests_every_repeated_label_match():
    """One string can name more than one account; every occurrence is evidence, not just the first."""
    doc = {"facts": [{"id": "F1", "label": "My open position (Zz First Account): shares; "
                                           "My open position (Zz Second Account): shares"}],
           "sections": []}
    terms = aa._doc_account_terms(doc)
    assert {"Zz First Account", "Zz Second Account"} <= terms


def test_delta_retained_section_provenance_redacts_the_previous_account(tmp_path):
    """Real full→delta carry-forward: a retained section's prior account name must not reach the reviewer."""
    bundle = Bundle(symbol="ZZDLT", scope="watch", name="Zzdelta Holdings")
    bundle.add("price", "Last close", value=10.0, source="fixture", as_of=NOW)
    bundle.add("position", "My open position (Zz New Account): shares", value=5.0, source="fixture")

    carried_ids = ("business_and_moat", "financials_and_trend", "valuation_vs_peers",
                   "risks", "analyst_view", "thesis_breakers")
    previous = {
        "symbol": "ZZDLT", "mode": "full",
        "facts": [{"id": "F9", "label": "My open position (Zz Old Account): shares", "value": 5.0,
                   "source": "fixture"}],
        "sections": [{"id": sid, "title": sid,
                      "body_md": ("The Zz Old Account still holds the position through the cycle."
                                  if sid == "business_and_moat" else "Steady ordinary prose about the business.")}
                     for sid in carried_ids],
    }
    # The writer rewrites only the delta sections; the rest are carried from the previous version.
    writer = {"verdict_line": "Steady view.",
              "sections": [{"id": "summary_verdict", "body_md": "The business is steady."},
                           {"id": "catalysts_and_dates", "body_md": "No dated catalysts are recorded."}]}
    sections, verdict, _log = gen.validate(writer, bundle, mode="delta", previous=previous)
    doc = {"symbol": "ZZDLT", "scope": "watch", "mode": "delta", "verdict_line": verdict,
           "sections": sections, "facts": bundle.facts, "blocks": {}}

    calls = []

    def fake(prompt):
        calls.append(prompt)
        return '{"issues": [], "overall": "ok"}', {"cost_usd": 0.4}

    cli.run_review(tmp_path / "accuracy", _review_run(doc, tmp_path), {"ZZDLT": doc},
                   apply=True, n=1, now=NOW, review_fn=fake)
    assert len(calls) == 1
    prompt = calls[0]
    assert "Zz Old Account" not in prompt  # the prior identity the retained prose carries is redacted
    assert "Zz New Account" not in prompt  # the current identity from the current facts is redacted
    assert "still holds the position through the cycle" in prompt  # ordinary prose is still audited
