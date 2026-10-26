"""Ticker Prospectus data-quality gate (operator 2026-10-26: "build this and execute it immediately").

Synthetic tickers and values only (public repo). The writer, the Haiku read and the data-gap queue are stubs; no DB,
no token store, no network; every write goes to a temporary state root.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import load_config, store  # noqa: E402
from scripts.lib.prospectus import generate as gen  # noqa: E402
from scripts.lib.prospectus import pipeline as pl  # noqa: E402
from scripts.lib.prospectus import quality_gate as qg  # noqa: E402
from scripts.lib.prospectus.domains import full_assemble  # noqa: E402
from scripts.lib import prospectus_api as api  # noqa: E402
from test_prospectus_build_20261026 import NOW, FakeSources, stub_generate  # noqa: E402

S = qg.load_settings()


def series(n=60, start=50.0, *, first=None, spike_at=None, break_at=None, end="2026-10-23"):
    end_d = datetime.fromisoformat(end)
    days, d = [], end_d
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d.date().isoformat())
        d -= timedelta(days=1)
    days.reverse()
    closes = [start + i * 0.1 for i in range(n)]
    if first is not None:
        closes[0] = first
    if spike_at is not None:
        closes[spike_at] = closes[spike_at] * 5
    if break_at is not None:
        closes = [c / 7 if i < break_at else c for i, c in enumerate(closes)]
    return list(zip(days, closes))


def packet(**kw):
    facts = [
        {"id": "F1", "kind": "price", "label": "Last close", "value": 55.9, "unit": "$", "source": "fx", "as_of": "2026-10-23"},
        {"id": "F2", "kind": "fundamental", "label": "Market cap ($B)", "value": 12.0, "unit": "", "source": "fx"},
        {"id": "F3", "kind": "analyst", "label": "Analyst target mean", "value": 70.0, "unit": "$", "source": "fx"},
        {"id": "F4", "kind": "fundamental", "label": "Performance YTD %", "value": 8.0, "unit": "%", "source": "fx"},
        {"id": "F5", "kind": "relative", "label": "ZQX return YTD %", "value": 9.0, "unit": "%", "source": "fx"},
        {"id": "F6", "kind": "risk", "label": "Beta (1Y vs SPY)", "value": 1.2, "unit": "", "source": "fx"},
        {"id": "F7", "kind": "risk", "label": "Annualized volatility %", "value": 35.0, "unit": "%", "source": "fx"},
    ]
    p = {"symbol": "ZQX", "name": "Zeq Widgets Inc", "scope": "watch", "facts": facts, "series": series(),
         "blocks": {"risk_technicals": {"beta_1y": 1.2, "vol_annualized_pct": 35.0},
                    "relative_performance": {"returns": [{"name": "ZQX", "YTD": 9.0, "1Y": 11.0}]},
                    "peer_comparison": {"industry": "Widgets", "fields": ["market_cap_b", "forward_pe"],
                                        "rows": [{"symbol": "ZQX", "is_subject": True, "market_cap_b": 12.0},
                                                 {"symbol": "ZP1", "market_cap_b": 10.0, "forward_pe": 20.0},
                                                 {"symbol": "ZP2", "market_cap_b": 15.0, "forward_pe": 22.0},
                                                 {"symbol": "ZP3", "market_cap_b": 9.0, "forward_pe": 18.0}],
                                        "median": {"market_cap_b": 10.0, "forward_pe": 20.0}}},
         "coverage": [], "context": {}, "as_of": "2026-10-26T16:00:00+00:00"}
    p.update(kw)
    return p


def codes(gate):
    return {f["code"] for f in gate["findings"]}


# ── layer 1 ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_clean_packet_passes():
    gate = qg.pre_write(packet(), settings=S)
    assert gate["status"] == qg.PASS, gate["reasons"]


def test_first_bar_outlier_like_a_listing_day_is_hard_fail():
    # listing-day style: first close ~7x below the following bars
    gate = qg.pre_write(packet(series=series(first=7.5)), settings=S)
    assert gate["status"] == qg.HARD and "first_bar_outlier" in codes(gate)


def test_isolated_jump_level_break_nonpositive_and_stale():
    assert "isolated_price_jump" in codes(qg.pre_write(packet(series=series(spike_at=30)), settings=S))
    assert "pre_listing_or_symbol_reuse" in codes(qg.pre_write(packet(series=series(break_at=25)), settings=S))
    bad = series()
    bad[10] = (bad[10][0], 0.0)
    assert "nonpositive_price" in codes(qg.pre_write(packet(series=bad), settings=S))
    g = qg.pre_write(packet(series=series(end="2026-10-01")), settings=S)
    assert g["status"] == qg.HARD and "stale_last_bar" in codes(g)
    g = qg.pre_write(packet(series=series(end="2026-10-19")), settings=S)
    assert g["status"] == qg.SOFT and "stale_last_bar" in codes(g)


def test_market_cap_unit_mismatch_is_soft_and_names_the_fact():
    p = packet()
    p["facts"][1]["value"] = 12000.0  # $M recorded as $B
    gate = qg.pre_write(p, settings=S)
    assert gate["status"] == qg.SOFT and "market_cap_units" in codes(gate) and gate["unreliable"]["F2"] == "market_cap_units"


def test_ranges_and_cross_source():
    p = packet()
    p["facts"][5]["value"] = 7.5
    p["facts"][6]["value"] = 450.0
    p["facts"][4]["value"] = 80.0  # house YTD 80% vs Finviz 8%
    got = codes(qg.pre_write(p, settings=S))
    assert {"beta_out_of_range", "volatility_absurd", "cross_source_disagreement"} <= got


def test_alphabetical_etf_cohort_peers_are_flagged_and_blocks_masked():
    p = packet()
    p["blocks"]["peer_comparison"] = {"industry": "Exchange Traded Fund", "fields": ["market_cap_b", "forward_pe"],
                                      "rows": [{"symbol": "ZQX", "is_subject": True, "market_cap_b": None},
                                               {"symbol": "AAA", "market_cap_b": None, "forward_pe": None},
                                               {"symbol": "AAAA", "market_cap_b": None, "forward_pe": 3.0},
                                               {"symbol": "AAAU", "market_cap_b": None, "forward_pe": None}],
                                      "median": {"market_cap_b": None, "forward_pe": 3.0}}
    gate = qg.pre_write(p, settings=S)
    assert "etf_cohort_peers" in codes(gate) and gate["status"] == qg.SOFT

    class B:  # minimal bundle
        facts, gaps, blocks = p["facts"], [], p["blocks"]
    qg.apply_unreliable(B, gate)
    rows = B.blocks["peer_comparison"]["rows"]
    assert rows[2]["forward_pe"] == "not reliable (etf_cohort_peers)"
    assert B.blocks["peer_comparison"]["unreliable"] and any("DATA QUALITY" in g for g in B.gaps)


def test_youtube_video_is_not_an_earnings_call_transcript():
    p = packet()
    p["facts"].append({"id": "F8", "kind": "earnings_call", "label": "Transcript: ZQX vs ZZZ: Which Stock Is The BETTER BUY? "
                       "(Some Channel)", "text": "hey guys", "source": "youtube_transcripts", "as_of": "2026-10-01"})
    p["facts"].append({"id": "F9", "kind": "earnings_call", "label": "Transcript: Zeq Widgets Q3 2026 Earnings Call "
                       "(Zeq IR)", "text": "Welcome to the Zeq Widgets third quarter earnings call", "source": "yt"})
    p["blocks"]["earnings_call"] = {"transcripts": [{"id": "F8"}, {"id": "F9"}]}
    gate = qg.pre_write(p, settings=S)
    f = next(x for x in gate["findings"] if x["code"] == "transcript_not_earnings_call")
    if not gate["layers"]["deterministic"]["external_guards"]["transcript_rejection"]:
        assert f["facts"] == ["F8"]
    assert "F8" in f["facts"]


def test_filing_under_another_cik_is_flagged():
    p = packet()
    for i, cik in enumerate(("1111111", "1111111", "2222222")):
        p["facts"].append({"id": f"F{20 + i}", "kind": "sec", "label": "SEC 8-K filed", "text": "x", "source": "sec",
                           "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/000/x.htm"})
    gate = qg.pre_write(p, settings=S)
    assert any(f["code"] == "filing_cik_mismatch" and f["facts"] == ["F22"] for f in gate["findings"])


def test_minimum_coverage_holding_without_position_is_hard():
    p = packet(scope="holding")
    gate = qg.pre_write(p, settings=S)
    assert gate["status"] == qg.HARD and "no_position" in codes(gate)
    p["facts"].append({"id": "F30", "kind": "position", "label": "Market value $", "value": 100.0, "unit": "$", "source": "fx"})
    assert codes(qg.pre_write(p, settings=S)) >= {"no_stop_state"}
    nothing = packet(series=[], facts=[])
    assert {"no_price", "no_analyst_or_fund_profile"} <= codes(qg.pre_write(nothing, settings=S))


# ── layer 2 ───────────────────────────────────────────────────────────────────────────────────────────────────
def ai_stub(anomalies, calls):
    def fn(prompt, *, max_tokens, timeout):
        calls.append(prompt)
        assert "FACTS (id" in prompt and "sections" not in prompt.lower().split("facts (id")[1][:0]
        return json.dumps({"anomalies": anomalies}), {"provider": "anthropic", "returned_model": "claude-haiku-5-5",
                                                      "estimated_cost_usd": 0.0009}
    return fn


def test_ai_high_severity_soft_and_confirming_hard():
    calls = []
    gate = qg.pre_write(packet(), settings=S, ai_fn=ai_stub([{"field": "F3", "value": "70", "why": "odd",
                                                              "severity": "high"}], calls))
    assert gate["status"] == qg.SOFT and "ai_anomaly" in codes(gate) and len(calls) == 1
    assert gate["layers"]["ai"]["model"] == "claude-haiku-5-5" and gate["layers"]["ai"]["cost_usd"] == 0.0009
    p = packet()
    p["facts"][1]["value"] = 12000.0
    gate = qg.pre_write(p, settings=S, ai_fn=ai_stub([{"field": "F2", "value": "12000", "why": "units",
                                                      "severity": "high"}], []))
    assert gate["status"] == qg.HARD and "ai_confirms_layer1" in codes(gate)
    low = qg.pre_write(packet(), settings=S, ai_fn=ai_stub([{"field": "F3", "why": "meh", "severity": "low"}], []))
    assert low["status"] == qg.PASS


def test_ai_skipped_on_hard_and_failure_never_blocks():
    calls = []
    qg.pre_write(packet(series=series(first=7.5)), settings=S, ai_fn=ai_stub([], calls))
    assert calls == []  # layer 1 hard fail: not even the cheap read is spent

    def boom(prompt, **kw):
        raise RuntimeError("ANTHROPIC_CREDIT_UNAVAILABLE")
    gate = qg.pre_write(packet(), settings=S, ai_fn=boom)
    assert gate["status"] == qg.PASS and gate["layers"]["ai"]["ran"] is False


def test_governed_ai_call_uses_haiku_process_then_grok_never_deepseek(monkeypatch):
    seen = []

    class LC:
        @staticmethod
        def gate_and_generate(prompt, *, process_id, lane, **kw):
            seen.append((process_id, lane))
            if process_id == qg.PROCESS_AI:
                raise RuntimeError("ANTHROPIC_CREDIT_UNAVAILABLE: anthropic-only process; queue and retry")
            return '{"anomalies": []}', {"provider": "grok"}
    monkeypatch.setitem(sys.modules, "lib.llm_consumption", LC)
    import lib  # noqa: F401
    monkeypatch.setattr(sys.modules["lib"], "llm_consumption", LC, raising=False)
    text, prov = qg.governed_ai_call("x", max_tokens=100, timeout=5)
    assert seen == [(qg.PROCESS_AI, "fast"), (qg.PROCESS_AI_OAUTH, "grok")] and prov["fallback"] == "grok_oauth"


def test_fact_check_processes_registered_haiku_anthropic_only_and_grok_only():
    reg = {p["id"]: p for p in json.loads((ROOT / "config/llm_process_registry.json").read_text())["processes"]}
    pol = json.loads((ROOT / "config/anthropic_credit_policy.json").read_text())
    assert qg.PROCESS_AI in pol["anthropic_only_processes"] and pol["process_tiers"][qg.PROCESS_AI] == "bulk"
    assert pol["models"]["bulk"] == "claude-haiku-5-5"
    assert reg[qg.PROCESS_AI]["daily_cost_cap_usd"] <= 1 and reg[qg.PROCESS_AI]["max_output_tokens"] <= 1200
    assert reg[qg.PROCESS_AI_OAUTH]["allowed_lanes"] == ["grok"] and not reg[qg.PROCESS_AI_OAUTH].get("anthropic_first")
    assert qg.ai_cost_estimate(S, {"claude-haiku-5-5": pol["pricing"]["claude-haiku-5-5"]}) <= 0.003


# ── layer 3 ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_post_write_numbers_must_match_cited_facts():
    facts = packet()["facts"]
    ok = [{"id": "summary_verdict", "body_md": "Last close $55.90 [F1] vs a $70 target [F3]; a 30-day view.",
           "citations": [{"id": "F1"}, {"id": "F3"}]}]
    assert qg.post_write(ok, facts, settings=S)["unmatched_count"] == 0
    bad = [{"id": "risks", "body_md": "Revenue fell 41.3% and margin 27.7% and debt 3.33x and growth 19.5% [F1].",
            "citations": [{"id": "F1"}]}]
    res = qg.post_write(bad, facts, settings=S)
    assert res["unmatched_count"] == 4 and res["rewrite"] is True
    uncited = [{"id": "risks", "body_md": "Target $70 [F1].", "citations": []}]
    assert qg.post_write(uncited, facts, settings=S)["uncited_count"] == 1


# ── wiring: write(), run_queue, API, --gate-only ──────────────────────────────────────────────────────────────
class SpikySources(FakeSources):
    def bars(self, sym, days=1100):
        rows = super().bars(sym, days)
        if sym == "ZZCC":  # listed ~5 months ago; the first stored bar belongs to another listing
            rows = rows[-110:]
            rows[0] = dict(rows[0], close=rows[0]["close"] / 7)
        return rows


def test_write_hard_fail_calls_no_model(tmp_path):
    src = SpikySources()
    b = full_assemble(src, "ZZCC", "watch", cfg=load_config(), now=NOW)
    calls = []
    with pytest.raises(qg.DataBlocked) as err:
        gen.write(b, processes=load_config()["processes"], premium=False, cfg=load_config(),
                  generate_fn=lambda *a, **k: calls.append(1), now=NOW, version=store.stamp(NOW), search_fn=src.search)
    assert calls == [] and src.calls == [] and "first_bar_outlier" in str(err.value)


def test_write_soft_fail_marks_partial_and_hides_numbers_from_writer():
    class BigCap(FakeSources):
        def enrichment_cache(self):
            c = super().enrichment_cache()
            c["ZZCC"] = dict(c["ZZCC"], market_cap_b=42000.0)
            return c
    src = BigCap()
    b = full_assemble(src, "ZZCC", "watch", cfg=load_config(), now=NOW)
    seen = []
    inner = stub_generate(src)

    def fn(prompt, **kw):
        seen.append(prompt)
        return inner(prompt, **kw)
    doc = gen.write(b, processes=load_config()["processes"], premium=False, cfg=load_config(), generate_fn=fn, now=NOW,
                    version=store.stamp(NOW))
    assert doc["status"] == "partial" and doc["gate"]["status"] == qg.SOFT
    assert any("market_cap_units" in g for g in doc["partial_gaps"])
    assert "NOT RELIABLE (market_cap_units)" in seen[-1] and "| 42000.0 |" not in seen[-1]
    assert "post_write" in doc["gate"]["layers"]


def test_run_queue_blocked_data_status_repairs_and_api(tmp_path, monkeypatch):
    base = store.base_dir(tmp_path, load_config())
    src = SpikySources()
    repairs = []
    monkeypatch.setattr(qg, "request_repairs", lambda sym, gate, gap_fn=None: repairs.append(sym) or ["quote_price"])
    store.write_universe(base, [{"symbol": "ZZCC", "scope": "watch", "premium": False}])
    store.enqueue(base, [{"symbol": "ZZCC", "scope": "watch", "priority": 1000}], now=NOW)
    out = pl.run_queue(base, src, load_config(), limit=3, holdings={}, generate_fn=stub_generate(src),
                       now_fn=lambda: NOW, log=lambda m: None, batch_enabled=False)
    assert out["blocked_data"] == ["ZZCC"] and repairs == ["ZZCC"] and out["done"] == []
    entry = store.read_index(base)["items"]["ZZCC"]
    assert entry["status"] == "blocked_data" and entry["gate_status"] == qg.HARD and entry["gate_reasons"]
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    item = next(i for i in api.index_payload(tmp_path)["items"] if i["symbol"] == "ZZCC")
    assert item["status"] == "blocked_data" and item["gate_status"] == qg.HARD and item["gate_reasons"]
    # re-requesting re-queues it (the gate runs again after the repair)
    store.enqueue(base, [{"symbol": "ZZCC", "scope": "watch", "priority": 1}], now=NOW)
    assert store.read_queue(base)["items"][0]["state"] == "queued"


def _seed_report(base, src, sym, scope="watch"):
    b = full_assemble(src, sym, scope, cfg=load_config(), holding=src.holdings().get(sym), now=NOW)
    doc = gen.write(b, processes=load_config()["processes"], premium=False, cfg=load_config(),
                    generate_fn=stub_generate(src), now=NOW, version=store.stamp(NOW), ai_fn=None)
    store.write_version(base, sym, doc["version"], doc, {})
    store.update_index(base, sym, status=doc["status"], version=doc["version"], scope=scope)
    return doc


def test_gate_only_dry_run_lists_rewrites_and_writes_nothing(tmp_path, monkeypatch):
    import prospectus_build as cli
    base = store.base_dir(tmp_path, load_config())
    doc = _seed_report(base, FakeSources(), "ZZAA", "holding")
    bad = json.loads(json.dumps(doc))  # same report, stored packet carrying a listing-day first bar
    pts = next(c for c in bad["charts"] if c["id"] == "price_1y")["series"][0]["points"]
    pts[0][1] = pts[0][1] / 7
    bad["symbol"], bad["version"] = "ZZBB", store.stamp(NOW + timedelta(minutes=1))
    store.write_version(base, "ZZBB", bad["version"], bad, {})
    store.update_index(base, "ZZBB", status="ready", version=bad["version"])
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    before = (base / "index.json").read_bytes(), (base / "queue.json").exists()
    out = cli.gate_only(cli.parse(["--gate-only", "--all"]), load_config(), base)
    assert out["mode"] == "gate_only_dry_run" and out["writes"] == "none" and out["layer2"]["ran"] is False
    assert out["blocked_data"] == ["ZZBB"] and "ZZBB" in out["needs_rewrite"]
    assert ((base / "index.json").read_bytes(), (base / "queue.json").exists()) == before

    gaps = []
    out = cli.gate_only(cli.parse(["--gate-only", "--symbols", "ZZBB", "--apply"]), load_config(), base,
                        ai_fn=ai_stub([], []), gap_fn=lambda *a, **k: gaps.append(a[0]))
    assert out["layer2"]["ran"] is True and gaps == ["quote_price"]
    q = store.read_queue(base)["items"]
    assert [r["symbol"] for r in q] == ["ZZBB"] and q[0]["reason"].startswith("gate_rewrite:")
    assert store.read_index(base)["items"]["ZZBB"]["gate_status"] == qg.HARD
