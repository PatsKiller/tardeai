"""Dell 8-K EX-99.1 primary evidence (2026-09-27). Hermetic: no network, no psycopg2.

The house held Dell's 2026-09-01 8-K as a headline plus the cover-page url, so the thesis
and the CIO packet said the "$95B AI server backlog" / "$60.9B orders" had no Dell primary
source. These tests cover the exhibit fetcher's pure parts, the evidence catalog / prompt,
the CIO packet's liquidity + fundamentals + disclosures, and the web query builder."""
from __future__ import annotations

import json
import sys
import types
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import sec_filing_documents as sfd  # noqa: E402
from scripts.lib import hermes_web_research as hw  # noqa: E402
from scripts.lib import options_cio_review as ocr  # noqa: E402
from scripts.lib.symbol_thesis_synthesis import PRIMARY_SLOTS, _build_flash_synthesis_prompt, build_synthesis_packet  # noqa: E402

CIK, ACC = "0001571996", "0001571996-26-000039"
DIR = "https://www.sec.gov/Archives/edgar/data/1571996/000157199626000039"
EXHIBIT = "exhibit991earnings8kq2fy27.htm"
INDEX_JSON = {"directory": {"item": [
    {"name": "0001571996-26-000039-index.htm", "type": "text.gif"},
    {"name": "dell-20260901.htm", "type": "text.gif"},
    {"name": EXHIBIT, "type": "text.gif"},
    {"name": "dell-20260901_htm.xml", "type": "text.gif"},
    {"name": "R1.htm", "type": "text.gif"},
]}}
FIXTURE_HTML = f"""<html><head><title>ex991</title><style>p {{ margin: 0 }}</style>
<script>var x = "$999 billion";</script></head><body>
<p><b>ROUND ROCK, Texas, Sept. 1, 2026</b> &#8212; Dell Technologies (NYSE: DELL) announces financial
results for its fiscal 2027 second quarter.</p>
<p>&#8220;We booked a record $60.9 billion in orders, recognized a record $16.4 billion in revenue and exited
the quarter with a record $95 billion backlog,&#8221; said Jeff Clarke, vice chairman and chief operating officer.</p>
<p>&#8220;We are raising our full-year FY27 revenue outlook by $25 billion to $192 billion,&#8221; said
Yvonne McGill, chief financial officer.</p>
<div>Second-quarter revenue was $47.0 billion, up 58% year over year. Operating income was $2.2 billion.
Diluted earnings per share was $1.83. Cash flow from operations was $2.5 billion.</div>
<table><tr><td>Remaining performance obligations were $132.0 billion.</td></tr></table>
</body></html>"""
INDEX_HTM = """<table><tr><td>1</td><td>8-K</td><td><a href="/Archives/x/dell-20260901.htm">dell-20260901.htm</a></td><td>8-K</td></tr>
<tr><td>2</td><td>PRESS RELEASE</td><td><a href="/Archives/x/a99one.htm">a99one.htm</a></td><td>EX-99.1</td></tr>
<tr><td>3</td><td>OTHER</td><td><a href="/Archives/x/a99two.htm">a99two.htm</a></td><td>EX-99.2</td></tr></table>"""


def _facts_by_cat(facts):
    out = {}
    for f in facts:
        out.setdefault(f["category"], []).append(f)
    return out


# ── A. fetcher: pure parsing ────────────────────────────────────────────────────

def test_index_json_picks_ex991_then_any_ex99_by_file_name():
    assert sfd.choose_exhibit(INDEX_JSON) == EXHIBIT
    assert sfd.choose_exhibit({"directory": {"item": [{"name": "d1dex992.htm"}, {"name": "d1.htm"}]}}) == "d1dex992.htm"
    assert sfd.choose_exhibit({"directory": {"item": [{"name": "dell-20260901.htm"}]}}) is None
    assert sfd.choose_exhibit_from_index_html(INDEX_HTM) == "a99one.htm"
    assert sfd.exhibit_label(EXHIBIT) == "EX-99.1" and sfd.exhibit_label("d1dex992.htm") == "EX-99.2"
    assert sfd.index_url(CIK, ACC) == DIR + "/index.json"
    assert sfd.index_htm_url(CIK, ACC) == DIR + "/0001571996-26-000039-index.htm"


def test_html_to_text_drops_script_style_and_entities_and_is_bounded():
    text = sfd.html_to_text(FIXTURE_HTML)
    assert "$999 billion" not in text and "margin" not in text and "<" not in text
    assert "“We booked a record $60.9 billion in orders" in text
    assert len(sfd.html_to_text("<p>" + "x" * 100_000 + "</p>", cap=500)) == 500


def test_dell_sentences_yield_backlog_orders_guidance_with_figures():
    facts = sfd.extract_facts(sfd.html_to_text(FIXTURE_HTML))
    by = _facts_by_cat(facts)
    assert by["backlog"][0]["amount_usd"] == 95e9 and by["backlog"][0]["amount_raw"] == "$95 billion"
    assert by["orders"][0]["amount_usd"] == 60.9e9 and "$60.9 billion" in by["orders"][0]["figures"]
    assert by["guidance"][0]["amount_usd"] == 192e9 and by["guidance"][0]["figures"] == ["$25 billion", "$192 billion"]
    assert "record $95 billion backlog" in by["backlog"][0]["sentence"]
    assert by["revenue"][0]["amount_usd"] == 16.4e9          # nearest figure to the keyword, same sentence
    assert by["operating_income"][0]["amount_usd"] == 2.2e9
    assert by["eps"][0]["amount_usd"] == 1.83                 # trailing period does not eat the figure
    assert by["cash_flow"][0]["amount_usd"] == 2.5e9
    assert by["remaining_performance_obligation"][0]["amount_usd"] == 132e9
    assert not any("$999" in f["sentence"] for f in facts)   # script text never becomes a fact


def test_fetch_exhibit_uses_index_json_then_the_index_htm_fallback():
    urls = []

    def fj(url):
        urls.append(url)
        return INDEX_JSON

    def ft(url):
        urls.append(url)
        return FIXTURE_HTML
    got = sfd.fetch_exhibit(CIK, ACC, fetch_json=fj, fetch_text=ft)
    assert got["doc_url"] == f"{DIR}/{EXHIBIT}" and got["exhibit"] == "EX-99.1"
    assert _facts_by_cat(got["facts"])["backlog"][0]["amount_usd"] == 95e9
    assert urls == [DIR + "/index.json", f"{DIR}/{EXHIBIT}"]

    def fj_fail(url):
        raise OSError("403")

    def ft2(url):
        return INDEX_HTM if url.endswith("-index.htm") else FIXTURE_HTML
    got = sfd.fetch_exhibit(CIK, ACC, fetch_json=fj_fail, fetch_text=ft2)
    assert got["doc_url"] == DIR + "/a99one.htm"


FILINGS = [
    {"form": "8-K", "filing_date": "2026-09-01", "accession_number": ACC, "items": "2.02,9.01"},
    {"form": "8-K", "filing_date": "2026-09-15", "accession_number": "0001571996-26-000041", "items": "5.02"},
    {"form": "10-Q", "filing_date": "2026-09-08", "accession_number": "0001571996-26-000040", "items": ""},
    {"form": "8-K", "filing_date": "2026-05-28", "accession_number": "0001571996-26-000021", "items": "2.02"},  # outside window
]


def test_only_in_window_8k_202_or_701_filings_get_documents_and_stored_ones_are_skipped():
    today = date(2026, 9, 27)
    need = sfd.filings_needing_documents(FILINGS, today=today)
    assert [f["accession_number"] for f in need] == [ACC]
    fetched = []

    def ft(url):
        fetched.append(url)
        return FIXTURE_HTML
    docs = sfd.fetch_documents_for_filings("dell", CIK, FILINGS, today=today, fetch_json=lambda u: INDEX_JSON, fetch_text=ft)
    assert len(docs) == 1 and docs[0]["symbol"] == "DELL" and docs[0]["accession"] == ACC
    assert docs[0]["exhibit"] == "EX-99.1" and docs[0]["filing_date"] == "2026-09-01" and docs[0]["items"] == "2.02,9.01"
    assert docs[0]["doc_url"] == f"{DIR}/{EXHIBIT}" and docs[0]["cik"] == CIK
    assert _facts_by_cat(docs[0]["facts"])["orders"][0]["amount_usd"] == 60.9e9
    # idempotent: a stored (accession, exhibit) is never refetched
    again = sfd.fetch_documents_for_filings("DELL", CIK, FILINGS, today=today, skip=lambda acc, ex: acc == ACC,
                                            fetch_json=lambda u: INDEX_JSON, fetch_text=ft)
    assert again == [] and len(fetched) == 1


class _Cur:
    def __init__(self, existing=()):
        self.existing, self.calls, self._last = set(existing), [], None

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self._last = (sql, params)

    def fetchone(self):
        sql, params = self._last
        return (1,) if "SELECT 1" in sql and (params[0], params[1]) in self.existing else None

    def fetchall(self):
        return []

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def __init__(self, cur):
        self._cur, self.commits, self.rollbacks = cur, 0, 0

    def cursor(self, *a, **k):
        return self._cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_ingest_hook_upserts_on_accession_exhibit_and_never_raises():
    import sec_fundamentals_ingest as ing
    cur = _Cur()
    conn = _Conn(cur)
    out = ing.ingest_documents(conn, "DELL", CIK, FILINGS, fetch_json=lambda u: INDEX_JSON, fetch_text=lambda u: FIXTURE_HTML)
    assert out["filing_documents_new"] == 1 and out["filing_facts_new"] >= 8 and conn.commits == 1
    ins = [c for c in cur.calls if c[0].lstrip().startswith("INSERT INTO sec_filing_documents")]
    assert len(ins) == 1 and "ON CONFLICT (accession, exhibit)" in ins[0][0]
    assert ins[0][1][2] == ACC and ins[0][1][5] == "EX-99.1" and json.loads(ins[0][1][9])[0]["category"]
    # second run: the row exists, nothing is fetched or inserted
    cur2 = _Cur(existing={(ACC, "EX-99.1")})
    out2 = ing.ingest_documents(_Conn(cur2), "DELL", CIK, FILINGS, fetch_json=lambda u: 1 / 0, fetch_text=lambda u: 1 / 0)
    assert out2 == {"filing_documents_new": 0, "filing_facts_new": 0}
    # table missing / db error: reported on the step, transaction rolled back, no raise
    class _Boom(_Cur):
        def execute(self, sql, params=None):
            raise RuntimeError('relation "sec_filing_documents" does not exist')
    conn3 = _Conn(_Boom())
    out3 = ing.ingest_documents(conn3, "DELL", CIK, FILINGS, fetch_json=lambda u: INDEX_JSON, fetch_text=lambda u: FIXTURE_HTML)
    assert "does not exist" in out3["filing_documents_error"] and conn3.rollbacks == 1


# ── D/E. evidence catalog + synthesis prompt ────────────────────────────────────

def _stored_record():
    return sfd.document_record(symbol="DELL", cik=CIK, accession=ACC, form="8-K", items="2.02,9.01", exhibit="EX-99.1",
                               filing_date="2026-09-01", doc_url=f"{DIR}/{EXHIBIT}", text=sfd.html_to_text(FIXTURE_HTML))


class _RoutingCur:
    """Answers only the sec_filing_documents query; every other evidence query returns nothing."""
    def __init__(self, rows):
        self.rows, self.q = rows, ""

    def execute(self, sql, params=None):
        self.q = sql

    def fetchall(self):
        return self.rows if "FROM sec_filing_documents" in self.q else []

    def close(self):
        pass


class _RoConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self, *a, **k):
        return self._cur

    def rollback(self):
        pass


def _stub_psycopg2(monkeypatch):
    pg = types.ModuleType("psycopg2")
    ext = types.ModuleType("psycopg2.extras")
    ext.RealDictCursor = object
    pg.extras = ext
    monkeypatch.setitem(sys.modules, "psycopg2", pg)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", ext)


def test_stored_exhibit_facts_become_dated_linked_primary_evidence(monkeypatch):
    _stub_psycopg2(monkeypatch)
    from scripts.lib import symbol_thesis_evidence as ste
    rec = _stored_record()
    row = {k: rec[k] for k in ("symbol", "cik", "accession", "form", "items", "exhibit", "filing_date", "doc_url")}
    row["facts"] = json.dumps(rec["facts"])  # a driver without jsonb decoding hands back text
    items = ste.retrieve_structured_sources("DELL", limit=8, conn=_RoConn(_RoutingCur([row])))
    ex = [i for i in items if i["source_type"] == "sec_8k_ex99"]
    assert ex and all(i["quality"] == "PRIMARY_REGULATORY" for i in ex)
    backlog = next(i for i in ex if i["provenance"]["category"] == "backlog")
    assert backlog["url"] == f"{DIR}/{EXHIBIT}" and backlog["observed_at"] == "2026-09-01"
    assert "$95 billion" in backlog["fact"] and "filed 2026-09-01" in backlog["fact"]
    assert backlog["provenance"]["accession"] == ACC and backlog["provenance"]["exhibit"] == "EX-99.1"
    assert backlog["provenance"]["form"] == "8-K"
    suff = ste.catalog_sufficiency({"supporting": [], "contradictory": [], "structured": items})
    assert "no_approved_primary_or_news" not in suff["remaining_evidence_gaps"]


def test_packet_keeps_exhibit_and_xbrl_facts_and_the_prompt_shows_dated_links():
    rec = _stored_record()
    from scripts.lib.symbol_thesis_evidence import evidence_item
    ex = [evidence_item(fact=sfd.fact_line("DELL", rec, f), source_type="sec_8k_ex99", source_id=str(i), polarity="CONTEXT",
                        quality="PRIMARY_REGULATORY", observed_at="2026-09-01", url=rec["doc_url"])
          for i, f in enumerate(rec["facts"])]
    xbrl = [{"evidence_id": f"ev_x{i}", "source_type": "sec_xbrl", "quality": "PRIMARY_REGULATORY",
             "fact": f"DELL metric {i} from 10-Q", "polarity": "CONTEXT", "url": "https://www.sec.gov/x", "observed_at": "2026-09-08"}
            for i in range(13)]
    news = [{"evidence_id": f"ev_n{i}", "source_type": "news", "quality": "APPROVED_NEWS", "fact": f"headline {i}",
             "polarity": "CONTEXT"} for i in range(10)]
    assert PRIMARY_SLOTS >= 24 and len(ex) + len(xbrl) <= PRIMARY_SLOTS
    catalog = {"supporting": [], "contradictory": [], "structured": news + xbrl + ex,
               "sufficiency": {"sufficient_for_synthesis": True}}
    packet = build_synthesis_packet("DELL", question="q", evidence_catalog=catalog)
    got = packet["evidence"]["structured"]
    assert [r["source_type"] for r in got[:len(ex)]] == ["sec_8k_ex99"] * len(ex)      # exhibit sentences first
    assert sum(r["source_type"] == "sec_xbrl" for r in got) == 13                        # xbrl all kept
    assert sum(r["source_type"] == "news" for r in got) == 8
    slim = got[0]
    assert slim["url"] == rec["doc_url"] and slim["observed_at"] == "2026-09-01"       # _slim keeps url + date
    prompt = _build_flash_synthesis_prompt("DELL", packet)
    assert "[dated 2026-09-01]" in prompt and f"<{rec['doc_url']}>" in prompt          # _fmt prints them
    assert "$95 billion backlog" in prompt and "DELL metric 12 from 10-Q" in prompt
    assert len(prompt) < 20_000


# ── F. CIO packet ───────────────────────────────────────────────────────────────

SPREAD = {
    "symbol": "DELL", "strategy": "credit_spread", "underlying_price": 563.0, "strike": 522.5, "short_strike": 522.5,
    "long_strike": 497.5, "premium": 8.1, "dte": 54, "breakeven": 514.4, "contracts": 1,
    "enterprise": {"tier": "A", "live_eligible": True, "blocks": [],
                   "liquidity": {"pass": True, "oi": 366, "volume": 12, "bid_ask_spread_pct": 4.94, "mid": 8.1, "issues": []}},
    "legs_liquidity": [
        {"role": "short put", "strike": 522.5, "bid": 7.9, "ask": 8.3, "mid": 8.1, "open_interest": 366, "volume": 12, "spread_pct": 4.9},
        {"role": "long put", "strike": 497.5, "bid": 3.1, "ask": 3.4, "mid": 3.25, "open_interest": 666, "volume": 4, "spread_pct": 9.2},
    ],
    "fundamentals": {"state": "OK", "symbol": "DELL", "source": "sec_xbrl", "filing_url": "https://www.sec.gov/q",
                     "lines": ["DELL revenue $46.97B for quarter ended 2026-07-31 (+57.7% YoY), 10-Q filed 2026-09-08",
                               "DELL remaining performance obligation $132.0B as of 2026-07-31, 10-Q filed 2026-09-08"]},
    "committee_memo": {"investment_thesis": "t", "contrarian_view": "c"},
}


def test_build_facts_reads_leg_liquidity_fundamentals_and_primary_disclosures():
    rec = _stored_record()
    loader_calls = []

    def loader(sym):
        loader_calls.append(sym)
        return sfd.primary_disclosures(sym, [rec])
    f = ocr.build_facts(SPREAD, disclosures_loader=loader)
    assert f["oi"] == 366 and f["bid_ask_spread_pct"] == 4.94               # not null on a credit spread
    legs = f["liquidity"]["legs"]
    assert [l["open_interest"] for l in legs] == [366, 666]
    assert legs[0] == {"role": "short put", "strike": 522.5, "bid": 7.9, "ask": 8.3, "mid": 8.1,
                       "open_interest": 366, "volume": 12, "spread_pct": 4.9}
    assert legs[1]["bid"] == 3.1 and legs[1]["ask"] == 3.4 and legs[1]["volume"] == 4 and legs[1]["spread_pct"] == 9.2
    assert f["liquidity"]["gate_pass"] is True and f["liquidity"]["issues"] == []
    assert f["fundamentals"]["lines"] == SPREAD["fundamentals"]["lines"] and f["fundamentals"]["state"] == "OK"
    assert loader_calls == ["DELL"]
    d = f["primary_disclosures"]
    backlog = next(x for x in d if x["category"] == "backlog")
    assert backlog["date"] == "2026-09-01" and backlog["url"] == rec["doc_url"] and backlog["amount"] == "$95 billion"
    assert backlog["form"] == "8-K EX-99.1" and "record $95 billion backlog" in backlog["fact"]
    assert "not the AI server backlog".lower() in f["rpo_vs_backlog_note"].lower()
    # a reviewer quoting the filing's figures now passes the traceability rail
    ok, errs = ocr.validate({"outcome": "MORE_RESEARCH", "confidence": "MEDIUM",
                             "reasoning": "Backlog of $95 billion and orders of $60.9 billion are disclosed; OI 366 on the short leg"},
                            f)
    assert ok, errs


def test_build_facts_without_documents_or_rpo_has_no_note_and_no_disclosures():
    p = dict(SPREAD, fundamentals={"state": "UNAVAILABLE", "lines": []})
    f = ocr.build_facts(p, disclosures_loader=lambda sym: [])
    assert f["primary_disclosures"] == [] and "rpo_vs_backlog_note" not in f
    f2 = ocr.build_facts({"symbol": "HOOD", "strategy": "cash_secured_put", "oi": 1200, "bid_ask_spread_pct": 2.0},
                         disclosures_loader=lambda sym: 1 / 0)      # loader failure is "none on file"
    assert f2["oi"] == 1200 and f2["primary_disclosures"] == [] and f2["liquidity"]["legs"] == []


def test_rpo_note_needs_both_an_rpo_line_and_a_backlog_disclosure():
    disc = [{"category": "backlog"}]
    assert sfd.rpo_note(["DELL remaining performance obligation $132.0B"], disc) == sfd.RPO_NOTE
    assert sfd.rpo_note(["DELL revenue $46.97B"], disc) is None
    assert sfd.rpo_note(["DELL remaining performance obligation $132.0B"], [{"category": "orders"}]) is None


# ── G. web research queries ─────────────────────────────────────────────────────

CFG = {"enabled_reasons": ["options_thesis_gap"], "max_queries": 6, "results_per_query": 2, "max_results": 5,
       "brave_fallback": False}
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def test_question_query_keeps_the_ai_acronym():
    q = hw._question_query("DELL", "DELL: What is Dell's exact AI server backlog dollar figure?")
    assert "AI" in q.split() and "backlog" in q and q.startswith("DELL ")
    assert "of" not in hw._question_query("DELL", "size of the AI server backlog in dollars").split()


def test_primary_source_templates_fire_on_reported_figure_questions_and_are_persisted():
    req = {"authority": "READ_ONLY_ADVISORY", "research_id": "res_dell", "symbol": "DELL", "reason": "options_thesis_gap",
           "questions": [{"id": "q1", "intent": "thesis_check", "text": "What is the thesis?"},
                         {"id": "q2", "intent": "cio_followup_1",
                          "text": "DELL: find dated, sourced facts: AI server backlog and quarterly AI orders"}]}
    planned = hw.planned_queries(req, hw.settings(CFG), now=NOW)
    qs = [q for q, _ in planned]
    assert "DELL earnings press release 8-K site:sec.gov" in qs
    assert "DELL investor relations earnings release" in qs
    assert any("AI" in q.split() and "backlog" in q for q in qs)
    assert hw.INTENT_QUERIES["primary_source"].format(sym="X", year=2026) == "X earnings press release 8-K site:sec.gov"
    # no reported-figure words -> no sec.gov query added on its own
    plain = {**req, "questions": [{"id": "q1", "intent": "thesis_check", "text": "What is the thesis?"}]}
    assert not any("sec.gov" in q for q, _ in hw.planned_queries(plain, hw.settings(CFG), now=NOW))
    searched = []

    def free(q, **k):
        searched.append(q)
        return types.SimpleNamespace(ok=False, results=[], reason="no_results")
    out = hw.gather(req, cfg=CFG, free_fn=free, env={}, now=NOW)
    assert out["used"] and out["planned_queries"] == [{"query": q, "kind": k} for q, k in planned]
    assert [x["query"] for x in out["queries"]] == searched == qs
    body = hw.ground_citations({"answers": []}, out)
    assert body["web_research"]["planned_queries"] == out["planned_queries"]
