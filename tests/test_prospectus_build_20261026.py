"""Ticker Prospectus generator (operator 2026-10-26): inputs, grounding, routing outcome, storage, renderers, cadence.

Synthetic tickers and amounts only (public repo). The model and search are stubs; no DB, no token store, no network,
and every write goes to a temporary state root.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import SECTION_IDS, load_config, sections_for, store  # noqa: E402
from scripts.lib.prospectus import generate as gen  # noqa: E402
from scripts.lib.prospectus import pipeline as pl  # noqa: E402
from scripts.lib.prospectus.domains import full_assemble  # noqa: E402
from scripts.lib.prospectus.inputs import assemble  # noqa: E402

NOW = datetime(2026, 10, 26, 16, tzinfo=timezone.utc)


class FakeSources:
    """Synthetic house data: two holdings (ZZAA larger) and one watch name."""

    def __init__(self, state_root=None, *, search_reason=None):
        self.calls = []
        self.state_root = Path(state_root or "/nonexistent-prospectus-fixture")
        self.search_reason = search_reason

    def db(self):
        def query(sql, params=None, fetch="all"):
            if "fred_economic_series" in sql:
                start = datetime(2025, 10, 1)
                return [{"series_id": sid, "series_name": sid, "value": v + i * 0.01,
                         "observation_date": (start + timedelta(days=i)).date()}
                        for sid, v in (("DGS10", 4.0), ("FEDFUNDS", 4.5)) for i in range(400)]
            return []
        return query

    def dossier(self, sym):
        return {"profile": {"description_1s": f"{sym} makes synthetic widgets.", "sector": "Technology",
                            "industry": "Widgets", "next_earnings_date": "2026-11-05", "updated_at": "2026-10-25",
                            "last_eps_actual": 1.25, "last_eps_estimate": 1.1, "last_eps_surprise_pct": 13.6,
                            "last_earnings_date": "2026-08-05"},
                "catalysts": [{"catalyst_type": "earnings", "severity": "medium", "headline": f"{sym} schedules Q3 results call",
                               "at": "2026-10-20T12:00:00Z"}],
                "news": [{"title": f"{sym} wins a synthetic contract", "source": "fixturewire", "published_at": "2026-10-25T10:00:00Z"}],
                "agents": [{"agent": "fixture_agent", "recommendation": "HOLD", "confidence": 0.6, "created_at": "2026-10-24"}],
                "sector": {"sector": "technology", "trend": "Leading"}, "sector_as_of": "2026-10-26",
                "industry": None, "research": [], "thesis": None, "analyst": None, "iv": {"iv_pct": 41.0, "snapshot_date": "2026-10-24"}}

    def consensus(self, syms):
        return {s: "buy" for s in syms}

    def ohlc(self, sym):
        return [{"high": 101 + i * 0.1, "low": 99 + i * 0.1, "close": 100 + i * 0.1} for i in range(40)]

    def position_view(self, sym):
        return {}

    def trades(self, sym):
        return [{"trade_date": "2026-01-05", "action": "BUY", "quantity": 5, "price": 90.0, "account": "fixture_brokerage"}]

    def options_theses(self, sym):
        return []

    def lookthrough(self, sym):
        return {}

    def holdings(self):
        return {
            "ZZAA": {"shares": 10.0, "market_value": 1500.0, "cost_basis": 1000.0, "avg_cost": 100.0,
                     "unrealized_pl": 500.0, "unrealized_pl_pct": 50.0, "weight_pct": 12.5,
                     "accounts": ["fixture_roth_ira", "fixture_brokerage"], "as_of": "2026-10-26"},
            "ZZBB": {"shares": 5.0, "market_value": 250.0, "cost_basis": 300.0, "avg_cost": 60.0,
                     "unrealized_pl": -50.0, "unrealized_pl_pct": -16.67, "weight_pct": 2.1,
                     "accounts": ["fixture_brokerage"], "as_of": "2026-10-26"},
        }

    def watch_symbols(self):
        return ["ZZCC", "ZZAA"]

    def profile(self, sym):
        return {"description": f"{sym} makes synthetic widgets.", "sector": "Technology", "industry": "Widgets",
                "next_earnings_date": "2026-11-05", "updated_at": "2026-10-25"}

    def analyst(self, sym):
        return {"target_low": 120.0, "target_mean": 165.0, "target_high": 200.0, "analyst_count": 12,
                "recommendation_key": "buy", "created_at": "2026-10-24"}

    def bars(self, sym, days=1100):
        start = datetime(2025, 10, 27)
        drift = {"SPY": 0.05, "QQQ": 0.08, "XLK": 0.1}.get(sym, 0.137)
        return [{"price_date": (start + timedelta(days=i)).date().isoformat(),
                 "close": 100.0 + i * drift + (1.5 if i % 7 == 0 else 0)} for i in range(365)]

    def catalysts(self, sym):
        return [{"type": "earnings", "headline": f"{sym} schedules Q3 results call", "at": "2026-10-20T12:00:00Z"}]

    def news(self, sym):
        return [{"title": f"{sym} wins a synthetic contract", "source": "fixturewire", "url": "https://example.test/a",
                 "published_at": "2026-10-25T10:00:00Z"}]

    def enrichment_cache(self):
        base = {"industry": "Widgets", "sector": "Technology", "pe": 30.0, "forward_pe": 25.0, "ps": 6.0, "pb": 8.0,
                "peg": 1.5, "market_cap_b": 42.0, "gross_margin_pct": 55.0, "eps_growth_next_y_pct": 18.0,
                "sales_growth_past_5y_pct": 21.0, "cached_at": "2026-10-26T06:00:00"}
        peers = {f"ZP{i}": dict(base, pe=20.0 + i, ps=4.0 + i, pb=5.0, forward_pe=18.0 + i) for i in range(4)}
        return {"ZZAA": dict(base, company="Zeta Widgets Inc"), "ZZBB": dict(base, company="Beta Synthetic Co"),
                "ZZCC": dict(base, company="Gamma Fixture Ltd"), **peers}

    def cio(self, sym):
        return {"stance": "HOLD", "stage": "watch", "conviction": 62, "evidence_at": "2026-10-25"}

    def stops(self, sym, accounts):
        return [{"account": "fixture_brokerage", "stop_price": 140.0, "stop_source": "broker_resting",
                 "stop_captured_at": "2026-10-25"}] if sym == "ZZAA" else []

    def search(self, query, sym):
        self.calls.append(query)
        if self.search_reason:
            return {"ok": False, "reason": self.search_reason, "provider": "", "results": []}
        return {"ok": True, "provider": "brave", "reason": "",
                "results": [{"title": f"{sym} web item", "url": "https://example.test/w", "source": "fixture",
                             "published": "2026-10-25"}]}


def _fact(bundle, label):
    return next(f for f in bundle.facts if f["label"] == label)


def model_reply(bundle, *, extra: str = "") -> str:
    if not any(f["label"] == "Last close" for f in bundle.facts):
        secs = [{"id": sid, "title": sid, "body_md": "Price history is not available in the house.", "citations": []}
                for sid in sections_for(bundle.scope)]
        return json.dumps({"verdict_line": "Data-limited view.", "sections": secs, "scenarios": []})
    last = _fact(bundle, "Last close")
    tgt = _fact(bundle, "Analyst target mean")
    secs = []
    for sid in sections_for(bundle.scope):
        body = (f"The last close was ${last['value']:.2f} [{last['id']}] against a mean target of "
                f"${tgt['value']:.0f} [{tgt['id']}].\n- Demand for widgets is steady.")
        if sid == "risks":
            body += "\n- Margins could compress by 37.9% in a downturn."  # ungrounded -> dropped
        if sid == "position_and_plan":
            body += " You should buy 50 shares now."  # behavior -> dropped
        secs.append({"id": sid, "title": sid, "body_md": body + extra, "citations": [last["id"], tgt["id"]]})
    lo, hi = _fact(bundle, "Analyst target low"), _fact(bundle, "Analyst target high")
    scen = [{"case": "bear", "price_fact": lo["id"], "probability_pct": 25, "narrative": f"Demand slips toward ${lo['value']:.0f} [{lo['id']}]."},
            {"case": "base", "price_fact": tgt["id"], "probability_pct": 50, "narrative": "Steady execution."},
            {"case": "bull", "price_fact": hi["id"], "probability_pct": 25, "narrative": f"Wins expand toward ${hi['value']:.0f} [{hi['id']}]."}]
    notes = {"macro_effects": {"rates": "Headwind: higher yields weigh on long-duration growth.", "curve": "Neutral."},
             "earnings_call": {"guidance": "not in the sources"}, "filings": {"10-Q": "No change recorded."}}
    return json.dumps({"verdict_line": f"Steady compounder trading near ${last['value']:.2f} [{last['id']}].",
                       "sections": secs, "scenarios": scen, "notes": notes})


def stub_generate(sources, *, fail_premium: Exception | None = None, credit_down: bool = False):
    seen = []

    def fn(prompt, *, process_id, max_tokens, timeout, manual=False):
        seen.append(process_id)
        if credit_down:
            raise RuntimeError("ANTHROPIC_CREDIT_UNAVAILABLE: anthropic-only process; queue and retry")
        if fail_premium is not None and process_id.endswith("premium"):
            raise fail_premium
        sym = re.search(r"prospectus on (\S+)", prompt).group(1)
        if '{"searches"' in prompt:
            return json.dumps({"searches": [{"query": f"{sym} guidance", "why": "fresh guidance"},
                                            {"query": f"{sym} call", "why": "call"}]}), {"estimated_cost_usd": 0.05}
        scope = "holding" if "current holding" in prompt else "watch"
        bundle = full_assemble(sources, sym, scope, cfg=load_config(), holding=sources.holdings().get(sym), now=NOW)
        model = "claude-fable-5-1" if process_id.endswith("premium") else "claude-opus-5-5"
        return model_reply(bundle), {"returned_model": model, "estimated_cost_usd": 0.31, "provider": "anthropic",
                                     "usage": {"prompt_tokens": 9000, "completion_tokens": 7000}}
    fn.seen = seen
    return fn


@pytest.fixture()
def base(tmp_path):
    return store.base_dir(tmp_path, load_config())


def test_assemble_cites_every_fact_and_names_accounts_only():
    src = FakeSources()
    b = assemble(src, "ZZAA", "holding", holding=src.holdings()["ZZAA"], now=NOW)
    ids = [f["id"] for f in b.facts]
    assert ids == [f"F{i}" for i in range(1, len(ids) + 1)]
    assert all(f["source"] for f in b.facts)
    accounts = _fact(b, "Accounts holding")["text"]
    assert "Fixture Roth IRA" in accounts and not re.search(r"\d{3,}", accounts)
    assert _fact(b, "Upside to mean target %")["value"] == pytest.approx((165 / b.series["price_1y"][-1][1] - 1) * 100, rel=1e-3)
    assert b.series["valuation_vs_peers"] and b.series["position"]["stops"] == [140.0]
    assert any("Distance from last close to stop" in f["label"] for f in b.facts)
    w = assemble(src, "ZZCC", "watch", now=NOW)
    assert not any(f["kind"] == "position" for f in w.facts)


def test_guard_drops_ungrounded_numbers_and_behavior_and_logs_it():
    src = FakeSources()
    b = assemble(src, "ZZAA", "holding", holding=src.holdings()["ZZAA"], now=NOW)
    sections, verdict, log = gen.validate(json.loads(model_reply(b)), b)
    assert [s["id"] for s in sections] == list(SECTION_IDS)
    risks = next(s for s in sections if s["id"] == "risks")
    assert "37.9" not in risks["body_md"] and "steady" in risks["body_md"]
    plan = next(s for s in sections if s["id"] == "position_and_plan")
    assert "50 shares" not in plan["body_md"]
    reasons = {row["reason"] for row in log}
    assert "ungrounded_number" in reasons and any(r.startswith(("sizing", "execution", "contract")) for r in reasons)
    assert all(c["id"].startswith("F") and c["source"] for s in sections for c in s["citations"])
    assert "Steady compounder" in verdict


def test_unparseable_or_empty_output_fails_validation():
    src = FakeSources()
    b = assemble(src, "ZZCC", "watch", now=NOW)
    with pytest.raises(gen.GenerationFailed):
        gen.parse_output("no json here")
    with pytest.raises(gen.GenerationFailed):
        gen.validate({"sections": [{"id": "summary_verdict", "body_md": "It will hit 987.65 soon."}]}, b)


def test_universe_premium_top_n_and_first_build_order():
    cfg = dict(load_config(), premium_top_n=1)
    uni = pl.plan_universe(FakeSources(), cfg)
    assert [(r["symbol"], r["scope"], r["premium"]) for r in uni] == [
        ("ZZAA", "holding", True), ("ZZBB", "holding", False), ("ZZCC", "watch", False)]
    order = [r["symbol"] for r in pl.first_build_rows(uni)]
    assert order == ["ZZAA", "ZZBB", "ZZCC"]
    assert load_config()["premium_top_n"] == 5


def test_run_queue_writes_private_layout_index_and_all_formats(base):
    src = FakeSources()
    cfg = load_config()
    uni = pl.plan_universe(src, cfg)
    store.write_universe(base, uni)
    store.enqueue(base, pl.first_build_rows(uni), now=NOW)
    fn = stub_generate(src)
    out = pl.run_queue(base, src, cfg, limit=5, generate_fn=fn, now_fn=lambda: NOW, log=lambda _m: None,
                       batch_enabled=False)  # synchronous path under test (Watch batch: test_prospectus_watch_batch)
    assert out["done"] == ["ZZAA", "ZZBB", "ZZCC"] and out["cost_usd"] == pytest.approx(3 * (0.31 + 0.05))
    assert fn.seen[0] == "prospectus_writer_premium" and fn.seen[-1] == "prospectus_writer"
    vdir = base / "ZZAA" / store.stamp(NOW)
    names = {p.name for p in vdir.iterdir()}
    assert {"prospectus.json", "prospectus.html", "charts"} <= names
    doc = json.loads((vdir / "prospectus.json").read_text())
    assert doc["schema"] == "Prospectus@v1" and doc["model"] == "claude-fable-5-1"
    assert {c["id"] for c in doc["charts"]} == {"price_1y", "relative_performance", "revenue_eps_trend", "eps_surprise",
                                               "valuation_vs_peers", "analyst_targets", "position_pl"}
    price = next(c for c in doc["charts"] if c["id"] == "price_1y")
    assert {a["kind"] for a in price["annotations"]} == {"stop", "entry", "target"}
    rng = next(c for c in doc["charts"] if c["id"] == "analyst_targets")
    assert [a["kind"] for a in rng["annotations"]] == ["range", "mean", "current"]
    from scripts.lib.prospectus import BLOCK_IDS
    assert set(BLOCK_IDS) - {"fund_lookthrough"} <= set(doc["blocks"])
    rel = doc["blocks"]["relative_performance"]
    assert [r["name"] for r in rel["returns"]] == ["ZZAA", "XLK", "SPY", "QQQ"] and rel["series"]["1Y"]
    assert doc["blocks"]["peer_comparison"]["rows"][0]["is_subject"] is True
    assert doc["blocks"]["risk_technicals"]["correlation_to_book"] is not None
    assert doc["blocks"]["macro_sensitivity"]["series"]["DGS10"]["trend"] == "rising"
    assert doc["blocks"]["macro_sensitivity"]["effects"]["rates"].startswith("Headwind")
    sc = doc["blocks"]["scenarios"]
    assert [c["case"] for c in sc["cases"]] == ["bear", "base", "bull"] and sum(c["probability_pct"] for c in sc["cases"]) == 100
    cov = doc["source_coverage"]
    assert {r["domain"] for r in cov["domains"]} >= {"macro", "sec_filing_events", "quote_price", "web_search"}
    assert next(r for r in cov["domains"] if r["domain"] == "web_search")["status"] == "used"
    assert [w["query"] for w in cov["web_searches"]] == ["ZZAA guidance", "ZZAA call"]
    assert any(f["kind"] == "web" and f["url"].startswith("https://") and f["as_of"] for f in doc["facts"])
    assert doc["status"] == "ready" and doc["partial_gaps"] == []
    html = (vdir / "prospectus.html").read_text()
    assert "prefers-color-scheme: dark" in html and "<svg" in html and "http" not in html.split("<body>")[0]
    for title in ("Relative performance", "Peer comparison", "Estimates and earnings surprises", "Ownership and flows",
                  "Risk and technicals", "Scenarios · 12 months", "Macro sensitivity · FRED", "Filings · SEC EDGAR",
                  "Earnings call", "Options, sentiment and dividends", "Source coverage", "Sources"):
        assert title in html, title
    assert "Scenario analysis, not an order" in html
    if (vdir / "prospectus.pdf").exists():
        assert (vdir / "prospectus.pdf").read_bytes()[:4] == b"%PDF"
    if (vdir / "prospectus.docx").exists():
        assert "word/document.xml" in zipfile.ZipFile(vdir / "prospectus.docx").namelist()
    idx = store.read_index(base)["items"]
    assert idx["ZZAA"]["status"] == "ready" and idx["ZZAA"]["next_due"]
    assert store.read_queue(base)["items"] == []
    assert store.versions(base, "ZZAA")[0]["version"] == store.stamp(NOW)
    zzcc = json.loads((base / "ZZCC" / store.stamp(NOW) / "prospectus.json").read_text())
    assert "position_and_plan" not in {s["id"] for s in zzcc["sections"]}


def test_credit_unavailable_keeps_job_queued_and_stops(base):
    src = FakeSources()
    cfg = load_config()
    store.enqueue(base, pl.first_build_rows(pl.plan_universe(src, cfg)), now=NOW)
    fn = stub_generate(src, credit_down=True)
    out = pl.run_queue(base, src, cfg, limit=5, generate_fn=fn, now_fn=lambda: NOW, log=lambda _m: None)
    assert out["queued"] == ["ZZAA"] and out["done"] == [] and len(fn.seen) == 1
    q = store.read_queue(base)["items"]
    assert [r["state"] for r in q] == ["queued"] * 3 and q[0]["last_error"].startswith("credit:")


def test_premium_refusal_falls_back_to_opus_once(base):
    from scripts.lib.anthropic_transport import AnthropicError
    src = FakeSources()
    fn = stub_generate(src, fail_premium=AnthropicError("OUTPUT_INVALID", request_sent=True))
    b = assemble(src, "ZZAA", "holding", holding=src.holdings()["ZZAA"], now=NOW)
    doc = gen.write(b, processes=load_config()["processes"], premium=True, cfg=load_config(), generate_fn=fn,
                    now=NOW, version=store.stamp(NOW))
    assert fn.seen == ["prospectus_writer_premium", "prospectus_writer"]
    assert doc["model"] == "claude-opus-5-5" and doc["fallback"]["from"] == "prospectus_writer_premium"


def test_premium_credit_refusal_queues_instead_of_falling_back():
    src = FakeSources()
    fn = stub_generate(src, fail_premium=RuntimeError("PAUSED_TODAY"))
    b = assemble(src, "ZZAA", "holding", holding=src.holdings()["ZZAA"], now=NOW)
    with pytest.raises(gen.QueueLater):
        gen.write(b, processes=load_config()["processes"], premium=True, cfg=load_config(), generate_fn=fn,
                  now=NOW, version=store.stamp(NOW))
    assert fn.seen == ["prospectus_writer_premium"]


def test_delta_carries_unchanged_sections_forward():
    src = FakeSources()
    b = assemble(src, "ZZAA", "holding", holding=src.holdings()["ZZAA"], now=NOW)
    prev_sections, _, _ = gen.validate(json.loads(model_reply(b)), b)
    prev = {"verdict_line": "old", "sections": prev_sections}
    delta = {"verdict_line": "new", "sections": [s for s in json.loads(model_reply(b))["sections"]
                                                  if s["id"] in gen.DELTA_SECTION_IDS]}
    sections, _, _ = gen.validate(delta, b, mode="delta", previous=prev)
    assert [s["id"] for s in sections] == list(SECTION_IDS)
    assert next(s for s in sections if s["id"] == "risks") == next(s for s in prev_sections if s["id"] == "risks")
    prompt = gen.build_prompt(b, mode="delta", previous=prev)
    assert "weekly update" in prompt and "business_and_moat (" not in prompt


def test_prompt_respects_byte_budget_and_forbids_orders():
    src = FakeSources()
    b = assemble(src, "ZZAA", "holding", holding=src.holdings()["ZZAA"], now=NOW)
    small = gen.build_prompt(b, max_bytes=8000)
    assert len(small.encode()) <= 8000 + 60 and "further facts omitted" in small
    full = gen.build_prompt(b)
    assert "Do not tell the reader to buy, sell, size" in full and "F1 |" in full and '"scenarios"' in full


def test_search_allowance_is_capped_per_utc_day(base):
    assert store.search_allowance(base, 2, now=NOW) == 2
    assert store.search_allowance(base, 2, now=NOW, take=True) == 1
    assert store.search_allowance(base, 2, now=NOW, take=True) == 0
    assert store.search_allowance(base, 2, now=NOW, take=True) == -1
    assert store.search_allowance(base, 2, now=NOW + timedelta(days=1)) == 2


def test_due_rows_cadence_earnings_and_triggers():
    src = FakeSources()
    cfg = load_config()
    uni = pl.plan_universe(src, cfg)
    gen_at = (NOW - timedelta(days=8)).isoformat()
    index = {"items": {
        "ZZAA": {"generated_at": gen_at, "inputs_digest": {"cio_stance": "SELL"}},
        "ZZBB": {"generated_at": (NOW - timedelta(days=31)).isoformat(), "inputs_digest": {}},
        "ZZCC": {"generated_at": (NOW - timedelta(days=1)).isoformat(), "earnings_date": "2026-10-26",
                 "inputs_digest": {}},
    }}
    due = {r["symbol"]: (r["reason"], r["mode"]) for r in pl.due_rows(uni, index, src, cfg, now=NOW)}
    assert due["ZZBB"] == ("cadence_full", "full")
    assert due["ZZCC"] == ("after_earnings", "full")
    assert due["ZZAA"][0] == "cio_stance_change"  # a fresh catalyst row alone no longer fires (2026-10-27)
    assert pl.due_rows(uni, {"items": {}}, src, cfg, now=NOW)[0]["reason"] == "missing"


def test_estimate_uses_policy_pricing():
    from scripts.lib.anthropic_transport import load_policy
    est = pl.estimate("x" * 36000, load_config(), premium=False, pricing=load_policy()["pricing"])
    assert est["model"] == "claude-opus-5-5" and est["input_tokens_est"] == 10000
    assert est["cost_usd_est"] == pytest.approx(10000 * 4 / 1e6 + 9000 * 20 / 1e6)
    prem = pl.estimate("x" * 36000, load_config(), premium=True, pricing=load_policy()["pricing"])
    assert prem["model"] == "claude-fable-5-1" and prem["reservation_hold_usd"] < 4.0


def test_cli_dry_run_writes_nothing_and_calls_no_model(tmp_path, monkeypatch, capsys):
    import scripts.prospectus_build as cli
    monkeypatch.setattr(cli, "HouseSources", lambda _root, **_kw: FakeSources())
    monkeypatch.setattr(cli, "state_root", lambda: tmp_path)
    monkeypatch.setattr(gen, "governed_generate", lambda *a, **k: pytest.fail("model called in dry run"))
    assert cli.main(["--scope", "all", "--limit", "3"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["model_calls"] == 0 and out["planned"] == 3
    assert [r["symbol"] for r in out["shown"]] == ["ZZAA", "ZZBB", "ZZCC"]
    assert out["shown"][0]["premium"] is True and out["shown"][0]["model"] == "claude-fable-5-1"
    assert list(tmp_path.rglob("*")) == []


def test_layout_refuses_traversal_and_bad_versions(base):
    assert store.norm_symbol("../etc") is None and store.norm_symbol("zzaa") == "ZZAA"
    with pytest.raises(ValueError):
        store.write_version(base, "ZZAA", "../x", {}, {})
    with pytest.raises(ValueError):
        store.write_version(base, "ZZAA", store.stamp(NOW), {}, {"../evil.html": b"x"})
    assert store.file_path(base, "ZZAA", "exe") is None


def test_partial_when_a_key_source_is_missing_and_gap_is_named(base):
    class NoPrices(FakeSources):
        def bars(self, sym, days=1100):
            return [] if sym == "ZZCC" else super().bars(sym, days)
    src = NoPrices()
    b = full_assemble(src, "ZZCC", "watch", cfg=load_config(), now=NOW)
    # Quality gate (2026-10-26): no price at all is below minimum coverage → blocked before any model call.
    from scripts.lib.prospectus.quality_gate import DataBlocked
    calls = []
    with pytest.raises(DataBlocked) as err:
        gen.write(b, processes=load_config()["processes"], premium=False, cfg=load_config(),
                  generate_fn=lambda *a, **k: calls.append(1), now=NOW, version=store.stamp(NOW))
    assert "no_price" in str(err.value) and calls == []
    # A key source that is missing but not minimum coverage (the CIO record) still writes a partial report.
    class NoCio(FakeSources):
        def cio(self, sym):
            return {}
    src = NoCio()
    b = full_assemble(src, "ZZCC", "watch", cfg=load_config(), now=NOW)
    doc = gen.write(b, processes=load_config()["processes"], premium=False, cfg=load_config(),
                    generate_fn=stub_generate(src), now=NOW, version=store.stamp(NOW))
    assert doc["status"] == "partial" and any(g.startswith("cio_record: empty") for g in doc["partial_gaps"])
    assert "Partial:" in __import__("scripts.lib.prospectus.render", fromlist=["html"]).html(doc)


def test_brave_budget_exhausted_writes_from_house_data(base):
    src = FakeSources(search_reason="BRAVE_DAILY_BUDGET_EXHAUSTED")
    b = full_assemble(src, "ZZAA", "holding", cfg=load_config(), holding=src.holdings()["ZZAA"], now=NOW)
    doc = gen.write(b, processes=load_config()["processes"], premium=False, cfg=load_config(), generate_fn=stub_generate(src),
                    now=NOW, version=store.stamp(NOW), search_fn=src.search,
                    allowance_fn=lambda take: store.search_allowance(base, 40, now=NOW, take=take))
    cov = doc["source_coverage"]
    assert len(cov["web_searches"]) == 1 and "budget exhausted" in cov["web_stopped"]
    assert not any(f["kind"] == "web" for f in doc["facts"])
    assert next(r for r in cov["domains"] if r["domain"] == "web_search")["status"] == "empty"


def test_job_allowance_used_up_skips_web_and_says_so(base):
    src = FakeSources()
    for _ in range(2):
        store.search_allowance(base, 2, now=NOW, take=True)
    fn = stub_generate(src)
    b = full_assemble(src, "ZZAA", "holding", cfg=load_config(), holding=src.holdings()["ZZAA"], now=NOW)
    doc = gen.write(b, processes=load_config()["processes"], premium=False, cfg=load_config(), generate_fn=fn, now=NOW,
                    version=store.stamp(NOW), search_fn=src.search,
                    allowance_fn=lambda take: store.search_allowance(base, 2, now=NOW, take=take))
    assert src.calls == [] and "allowance" in doc["source_coverage"]["web_stopped"] and len(fn.seen) == 1


def test_paid_searches_count_against_the_job_allowance(base):
    src = FakeSources()
    b = full_assemble(src, "ZZAA", "holding", cfg=load_config(), holding=src.holdings()["ZZAA"], now=NOW)
    gen.write(b, processes=load_config()["processes"], premium=False, cfg=load_config(), generate_fn=stub_generate(src),
              now=NOW, version=store.stamp(NOW), search_fn=src.search,
              allowance_fn=lambda take: store.search_allowance(base, 40, now=NOW, take=take))
    assert store.search_allowance(base, 40, now=NOW) == 38


def test_coverage_records_every_house_source_outcome():
    class Broken(FakeSources):
        def cio(self, sym):
            raise RuntimeError("store down")
    b = full_assemble(Broken(), "ZZAA", "holding", cfg=load_config(), holding=FakeSources().holdings()["ZZAA"], now=NOW)
    status = {r["source"]: r["status"] for r in b.coverage}
    assert status["cio_record"] == "failed" and status["price_history"] == "used" and status["position"] == "used"
    reg = {r["domain"]: r for r in b.context["registry_coverage"]}
    assert reg["cio_prospect"]["status"] in {"used", "failed"} and reg["data_gaps"]["status"] == "not_applicable"
    assert reg["macro"]["status"] == "used" and reg["technicals"]["status"] == "failed"
    from scripts.lib.prospectus.inputs import key_gaps
    assert any(g.startswith("cio_record: failed") for g in key_gaps(b))
