"""The full picture for a named stock, and the pill line on every reply.

2026-09-14 08:40 (operator): "What about analyst reviews? What about ... the
industry? ... not thorough and complete, and all the data is there. ... I don't see
the pill icons of whether this is internal to trade AI, has any external
information been looked up, or if it was a LLM like DeepSeek."

Offline: db_query is a fake keyed on the SQL; runtime files are temp; no model,
no snapshot, no network.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

import scripts.lib.cio_operator_desk_loop as desk
import scripts.lib.reply_provenance as rp
import scripts.lib.subject_dossier as sd

TODAY = datetime.now(timezone.utc)


def _fake_db(tables: dict[str, list[dict]]):
    calls = []

    def q(sql, params=None, fetch="all"):
        calls.append(sql)
        for key, rows in tables.items():
            if f"FROM {key}" in sql:
                return rows
        return []
    q.calls = calls
    return q


AXTI_TABLES = {
    "symbol_profiles": [{
        "description_1s": "AXT, Inc. designs, develops, manufactures, and distributes compound semiconductor substrates.",
        "sector": "Technology", "industry": "Semiconductor Equipment & Materials", "source": "yfinance",
        "updated_at": TODAY - timedelta(days=25), "next_earnings_date": date(2026, 10, 29),
        "last_earnings_date": date(2026, 7, 30), "last_eps_estimate": 0.07, "last_eps_actual": 0.19,
        "last_eps_surprise_pct": 163.89, "earnings_updated_at": TODAY}],
    "catalyst_events": [{"catalyst_type": "earnings_beat", "severity": "critical", "source": "google_news",
                         "headline": "AXTI Stock Skyrockets As Investors Cheer Blowout Guidance, Record Quarterly Revenue",
                         "at": TODAY - timedelta(days=45)}],
    "news_articles": [{"title": "AXT (AXTI) Q2 2026 Earnings Call Transcript", "source": "yahoo_premarket",
                       "published_at": TODAY - timedelta(days=28)}],
    "watchlist_agent_results": [],
    "watchlist_final_synthesis": [],
    "options_iv_history": [],
    "ticker_dividend_data": [],
}


@pytest.fixture
def runtime(tmp_path):
    (tmp_path / "sector_momentum_latest.json").write_text(json.dumps({
        "generated_at": "2026-09-14T05:36:41+00:00",
        "rows": [{"etf": "XLK", "sector": "Technology", "state": "LEADING", "rs5": 1.09, "rs20": 0.4,
                  "rs60": -4.95, "breadth_pct": 28},
                 {"etf": "XLF", "sector": "Financials", "state": "LAGGING"}]}), encoding="utf-8")
    (tmp_path / "industry_momentum_latest.json").write_text(json.dumps({
        "captured_at": "2026-09-14T12:37:00+00:00",
        "industries": [{"industry": "Semiconductor Equipment & Materials", "sector": "Technology",
                        "state": "LAGGING", "perf_week": -7.82, "perf_month": -17.58, "perf_quarter": -23.06,
                        "perf_ytd": 53.06, "rel1m": -16.06}]}), encoding="utf-8")
    return tmp_path


def _gather(runtime, **kw):
    analyst = [{"symbol": "AXTI", "rating": "buy", "analysts": 4, "target_mean": 96.5, "target_low": 73.0,
                "target_high": 125.0, "as_of": "2026-06-24", "age_days": 82, "stale": True}]
    research = [{"symbol": "AXTI", "research_type": "deep_research_local", "summary": "constrained: no recent trades",
                 "as_of": "2026-09-13"}]
    return sd.gather(["AXTI"], db_query=_fake_db(AXTI_TABLES), runtime_dir=runtime,
                     analyst_fn=lambda s: analyst, research_fn=lambda s: research,
                     thesis_fn=lambda s: {"thesis_state": "STALE", "portfolio_role": "QUALITY_CORE",
                                          "thesis_summary": "HOLD/REDUCE, not a buy"},
                     held={}, **kw)


def test_dossier_carries_every_section_the_house_holds(runtime):
    text = sd.format_dossier(["AXTI"], _gather(runtime), prices={"AXTI": 64.76})
    for needle in ("Technology / Semiconductor Equipment & Materials", "EPS $0.19 vs est $0.07", "next report Oct 29",
                   "Buy · 4 analysts · mean target $96.50 (low $73.00, high $125.00)", "82 days old — stale",
                   "earnings beat (critical)", "Q2 2026 Earnings Call Transcript",
                   "Technology (XLK) LEADING", "Semiconductor Equipment & Materials LAGGING", "month -17.6%",
                   "deep research local", "STALE · role QUALITY_CORE", "Position (holdings.json): not held"):
        assert needle in text, needle


def test_every_fact_line_carries_the_house_pill_and_outside_is_stated(runtime):
    text = sd.format_dossier(["AXTI"], _gather(runtime), prices={"AXTI": 64.76})
    for ln in text.split("\n"):
        if ln.startswith(("*AXTI", "Not on file")):
            continue
        assert ln.startswith((sd.PILL_HOUSE, sd.PILL_OUTSIDE)), ln
    assert "🔵 Looked up outside Trade-AI: nothing for these lines" in text


def test_missing_sections_are_named_not_hidden(runtime):
    text = sd.format_dossier(["AXTI"], _gather(runtime), prices={"AXTI": 64.76})
    miss = [ln for ln in text.split("\n") if ln.startswith("Not on file for AXTI")]
    assert miss and "specialist agent reviews" in miss[0] and "options IV" in miss[0]


def test_what_it_means_uses_no_new_number(runtime):
    text = sd.format_dossier(["AXTI"], _gather(runtime), prices={"AXTI": 64.76})
    meaning = [ln for ln in text.split("\n") if "What the stored facts say together" in ln][0]
    assert "beat estimates" in meaning and "lagging" in meaning and "dated" in meaning
    assert not any(ch.isdigit() for ch in meaning.split(":", 1)[1])


def test_sector_alias_maps_yfinance_names():
    doc = {"rows": [{"sector": "Financials", "etf": "XLF"}, {"sector": "Consumer Discretionary", "etf": "XLY"}]}
    assert sd._sector_row(doc, "Financial Services")["etf"] == "XLF"
    assert sd._sector_row(doc, "Consumer Cyclical")["etf"] == "XLY"


def test_unreadable_store_is_a_gap_not_a_crash(runtime):
    def boom(sql, params=None, fetch="all"):
        raise RuntimeError("db down")
    d = sd.gather(["AXTI"], db_query=boom, runtime_dir=runtime)
    text = sd.format_dossier(["AXTI"], d)
    assert "Not on file for AXTI" in text and "company profile" in text


def test_dossier_fits_under_a_telegram_message(runtime):
    d = _gather(runtime)
    d["AXTI"]["research"] = [{"symbol": "AXTI", "research_type": "x", "summary": "y" * 900, "as_of": "2026-09-13"}] * 3
    assert len(sd.format_dossier(["AXTI"], d)) <= sd.MAX_CHARS


# ── desk wiring ──────────────────────────────────────────────────────────────


def test_curate_puts_legend_pill_header_and_dossier_under_the_answer(monkeypatch):
    monkeypatch.setattr(desk, "_curate_from_evidence_core",
                        lambda t, ev: {"ok": True, "text": "🎯 AXTI — re-entry check\nREAD_ONLY_ADVISORY",
                                       "source": "tradeai_deterministic", "model": None})
    out = desk._curate_from_evidence("axti?", {"available": {"subject_dossier_text": "*AXTI — full picture*\n🟢 Trade-AI x"}})
    lines = out["text"].split("\n")
    assert lines[0] == sd.LEGEND
    assert lines[1].startswith("🟢 Trade-AI data — desk answer")
    assert "*AXTI — full picture*" in out["text"] and out["dossier"] is True


def test_model_written_summary_gets_the_deepseek_pill(monkeypatch):
    monkeypatch.setattr(desk, "_curate_from_evidence_core",
                        lambda t, ev: {"ok": True, "text": "summary", "source": "freeform_flash", "model": "deepseek-flash"})
    out = desk._curate_from_evidence("x", {"available": {"subject_dossier_text": "*AXTI — full picture*"}})
    assert out["text"].split("\n")[1].startswith("🟣 AI model (DeepSeek) wrote the summary below")


def test_empty_evidence_becomes_the_dossier(monkeypatch):
    monkeypatch.setattr(desk, "_curate_from_evidence_core",
                        lambda t, ev: {"ok": False, "text": "Trade-AI has no vetted facts", "source": "empty_evidence"})
    out = desk._curate_from_evidence("x", {"available": {"subject_dossier_text": "*AXTI — full picture*"}})
    assert out["ok"] is True and out["source"] == "tradeai_deterministic" and "no vetted facts" not in out["text"]


def test_meta_answers_get_no_dossier(monkeypatch):
    monkeypatch.setattr(desk, "_curate_from_evidence_core",
                        lambda t, ev: {"ok": True, "text": "runtime", "source": "runtime_meta", "model": None})
    out = desk._curate_from_evidence("x", {"available": {"subject_dossier_text": "*AXTI*"}})
    assert out["text"] == "runtime"


def test_gather_attaches_dossier_for_a_stock_question_only(monkeypatch, runtime):
    monkeypatch.setattr(desk, "_gather_tradeai_evidence_core",
                        lambda intent: {"available": {"subject_price": {"AXTI": {"close": 64.76}}}, "sources": []})
    monkeypatch.setattr(desk, "_research_db_query", _fake_db(AXTI_TABLES))
    monkeypatch.setattr(desk, "PROJECT_ROOT", runtime.parent)
    (runtime.parent / "data").mkdir(exist_ok=True)
    rt = runtime.parent / "data" / "runtime"
    if not rt.exists():
        rt.symlink_to(runtime)
    monkeypatch.setattr(desk, "subject_analyst_view", lambda s: [])
    monkeypatch.setattr(desk, "subject_research", lambda s: [])
    monkeypatch.setattr(desk, "_held_positions_map", lambda: {})
    ev = desk.gather_tradeai_evidence({"intent": "reentry", "symbols": ["AXTI"], "needs": ["reentry_levels"]})
    assert "AXTI — full picture" in ev["available"]["subject_dossier_text"]
    assert {"symbol_profiles", "catalyst_events", "industry_momentum_latest.json"} <= set(ev["sources"])
    meta = desk.gather_tradeai_evidence({"intent": "meta_system", "symbols": ["AXTI"], "needs": []})
    assert "subject_dossier_text" not in meta["available"]


# ── the Origin pill line on every reply ─────────────────────────────────────


def test_finalize_adds_the_origin_pill_line_above_sources():
    prov = rp.ReplyProvenance(kind="operator_desk", stores_read=["re-entry desk", "symbol_profiles"],
                              went_outside=["deepseek-flash — intent classification only; no facts"])
    final, prov = rp.finalize_operator_reply("body\nREAD_ONLY_ADVISORY", prov)
    lines = final.split("\n")
    origin = [ln for ln in lines if ln.startswith("Origin: ")]
    assert len(origin) == 1
    assert origin[0] == ("Origin: 🟢 Trade-AI data (2 stores) · 🔵 Looked up outside Trade-AI: nothing · "
                         "🟣 AI model (DeepSeek): intent classification only")
    assert lines.index(origin[0]) == lines.index(next(ln for ln in lines if ln.startswith("Sources:"))) - 1
    assert prov.sources_line_present and prov.authority_tail_present


def test_origin_names_an_outside_lookup_separately_from_the_model():
    line = rp.origin_line(["CIO snapshot"], ["governed_search — analyst view for SPCX had no house coverage (answered)",
                                             "deepseek-flash — general knowledge where labelled; numbers from the stores above"],
                          None)
    assert "🔵 Looked up outside Trade-AI: governed_search — analyst view for SPCX" in line
    assert "🟣 AI model (DeepSeek): general knowledge where labelled" in line


def test_refinalizing_does_not_duplicate_the_origin_line():
    prov = rp.ReplyProvenance(kind="operator_desk", stores_read=["holdings.json"])
    once, prov = rp.finalize_operator_reply("hello", prov)
    twice, _ = rp.finalize_operator_reply(once, prov)
    assert twice.count("Origin: ") == 1


def test_no_store_and_no_model_is_said_out_loud():
    assert rp.origin_line([], [], None) == ("Origin: 🟢 Trade-AI data: no store read · 🔵 Looked up outside Trade-AI: nothing · "
                                            "🟣 AI model (DeepSeek): not used")
