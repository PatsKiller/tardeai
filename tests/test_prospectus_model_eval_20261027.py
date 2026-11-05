"""Watch prospectus model eval harness (operator 2026-10-27: "Yes, ... let me test.").

Synthetic tickers and amounts only (public repo). The model, search, renderer and stores are stubs; every write goes to
a temporary directory, no network, no token store, no real credit journal.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import prospectus_model_eval as ev  # noqa: E402
from scripts.lib.anthropic_credit import CreditBook  # noqa: E402
from scripts.lib.prospectus import accuracy_audit as aa  # noqa: E402
from scripts.lib.prospectus import generate as gen  # noqa: E402
from scripts.lib.prospectus import load_config, quality_gate as qg, store  # noqa: E402
from scripts.lib.prospectus.domains import full_assemble  # noqa: E402
from tests.test_prospectus_build_20261026 import FakeSources, model_reply  # noqa: E402

NOW = datetime(2026, 10, 26, 16, tzinfo=timezone.utc)
SYM = "ZZCC"  # FakeSources' watch name


def _modules():
    from scripts.lib import anthropic_routing as routing
    from scripts.lib import anthropic_transport as transport
    return routing, transport


def stub_writer(sources, *, model: str, cost: float = 0.07, fail_on: set[str] | None = None, calls: list | None = None):
    calls = calls if calls is not None else []

    def fn(prompt, *, process_id, max_tokens, timeout, manual=False):
        calls.append((process_id, max_tokens))
        sym = re.search(r"prospectus on (\S+)", prompt).group(1)
        if fail_on and sym in fail_on:
            raise RuntimeError("ANTHROPIC_CREDIT_UNAVAILABLE: PAUSED_TODAY")
        if '{"searches"' in prompt:
            return json.dumps({"searches": [{"query": f"{sym} guidance", "why": "guidance"}]}), {
                "estimated_cost_usd": 0.01, "returned_model": model}
        b = full_assemble(sources, sym, "watch", cfg=load_config(), holding=None, now=NOW)
        return model_reply(b), {"returned_model": model, "estimated_cost_usd": cost, "provider": "anthropic",
                                "usage": {"prompt_tokens": 6500, "completion_tokens": 3900}}
    fn.calls = calls
    return fn


def seed_opus(state_root: Path, sym: str = SYM) -> dict:
    """A stored Opus Watch report in a temporary prospectus store (the baseline the harness reads)."""
    src = FakeSources(state_root)
    cfg = load_config()
    b = full_assemble(src, sym, "watch", cfg=cfg, holding=None, now=NOW - timedelta(hours=10))
    version = store.stamp(NOW - timedelta(hours=10))
    doc = gen.write(b, processes=cfg["processes"], premium=False, cfg=cfg,
                    generate_fn=stub_writer(src, model="claude-opus-5-5", cost=0.12), now=NOW - timedelta(hours=10),
                    version=version, search_fn=None)
    doc["batch"] = {"batch_id": "fixture-batch", "price_multiplier": 0.5}
    base = store.base_dir(state_root, cfg)
    store.write_version(base, sym, version, doc, {"prospectus.pdf": b"%PDF-1.4 synthetic opus"})
    store.update_index(base, sym, scope="watch", status="ready", model=doc["model"], version=version,
                       generated_at=doc["generated_at"], gate_status="pass")
    return doc


def tree(path: Path) -> dict:
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def deps_for(state_root: Path, writer, *, ai_fn=None) -> ev.Deps:
    return ev.Deps(sources=FakeSources(state_root), primary=aa.Primary(), generate_fn=writer, ai_fn=ai_fn,
                   render_fn=lambda doc: {"prospectus.html": b"<html>synthetic</html>",
                                          "prospectus.pdf": b"%PDF-1.4 synthetic sonnet"},
                   assemble_fn=full_assemble, state_root=state_root)


# ── the eval route ────────────────────────────────────────────────────────────────────────────────────────────────
def test_overlay_pins_writer_to_mid_and_only_raises_its_per_call_ceiling():
    _, transport = _modules()
    p = transport.load_policy()
    out = ev.overlay_policy(p)
    assert out["process_tiers"]["prospectus_writer"] == "mid" and out["models"]["mid"] == "claude-sonnet-5-5"
    assert out["per_call_caps_usd"]["mid"] == ev.EVAL_PER_CALL_CAP_USD and "mid" in out["thinking_tiers"]
    for key in ("total_cap_usd", "daily_cap_usd", "daily_cap_overrides", "pricing"):
        assert out[key] == p[key]
    assert {k: v for k, v in out["per_call_caps_usd"].items() if k != "mid"} == {
        k: v for k, v in p["per_call_caps_usd"].items() if k != "mid"}
    assert p["process_tiers"]["prospectus_writer"] == "long_form"  # the input is not mutated
    higher = dict(p, per_call_caps_usd=dict(p["per_call_caps_usd"], mid="0.90"))
    assert ev.overlay_policy(higher)["per_call_caps_usd"]["mid"] == "0.90"  # never lowered
    with pytest.raises(RuntimeError, match="CREDIT_CONFIGURATION_INVALID"):
        ev.overlay_policy(dict(p, models=dict(p["models"], mid="claude-opus-5-5")))


def test_eval_route_resolves_sonnet_medium_inside_and_restores_production_outside():
    routing, transport = _modules()
    assert routing.tier_for("PRO_THINK", "high", process_id="prospectus_writer") == "long_form"
    with ev.eval_route() as route:
        assert routing.tier_for("PRO_THINK", "high", process_id="prospectus_writer") == "mid"
        assert routing.load_policy()["models"]["mid"] == "claude-sonnet-5-5"
        s = transport._reasoning_settings("claude-sonnet-5-5", "enabled", transport.load_policy())
        assert s["output_config"]["effort"] == "medium" and s["thinking"] == {"type": "adaptive"}
        o = transport._reasoning_settings("claude-opus-5-5", "enabled", transport.load_policy())
        assert o["output_config"]["effort"] == "high"  # only the eval model changes
        assert route["patched"]
        cfg = {"reasoning_tier": "high", "deepseek_allowed_policies": ["PRO_THINK"]}
        res = {n: {"thinking": "enabled" if "THINK" in n else "disabled"} for n in ("FAST", "PRO", "PRO_THINK")}
        sel = routing.selected_policy("prospectus_writer", cfg, res)
        assert (sel["model_id"], sel["credit_tier"], sel["thinking"]) == ("claude-sonnet-5-5", "mid", "enabled")
        assert "mid" in routing.load_policy()["thinking_tiers"]  # llm_consumption sends thinking=enabled for it
    assert routing.tier_for("PRO_THINK", "high", process_id="prospectus_writer") == "long_form"
    s = transport._reasoning_settings("claude-sonnet-5-5", "enabled", transport.load_policy())
    assert s["output_config"]["effort"] == "high"


def _fake_http(model: str, sent: list):
    def request(method, path, payload, **kwargs):
        sent.append((path, payload))
        if path.endswith("count_tokens"):
            return 200, {"input_tokens": 6000}, {}
        return 200, {"id": "fixture", "model": model, "content": [{"type": "text", "text": "{}"}],
                     "stop_reason": "end_turn", "usage": {"input_tokens": 6000, "output_tokens": 3500}}, {}
    return request


def _client(transport, book, sent):
    return transport.AnthropicTransport(book=book, env={"ANTHROPIC_API_KEY": "synthetic-only"},
                                        request=_fake_http("claude-sonnet-5-5", sent), now=lambda: NOW,
                                        sleep=lambda _s: None, record_usage=lambda *a: True,
                                        record_attempt=lambda *a: True, reserve_process=lambda *a: None,
                                        settle_process=lambda *a: None)


def test_writer_call_is_refused_on_tier_mid_without_the_route_and_journaled_with_it(tmp_path):
    _, transport = _modules()
    prompt = "x" * 23000  # a Watch writer prompt is ~23 KB
    msgs = [{"role": "user", "content": prompt}]
    plain = CreditBook(tmp_path / "plain", dict(transport.load_policy(), enabled=True))
    with pytest.raises(transport.AnthropicError, match="CREDIT_PER_CALL_CAP"):
        _client(transport, plain, []).generate(msgs, "claude-sonnet-5-5", max_tokens=5000, client_request_id="a",
                                                process_id="prospectus_writer", credit_tier="mid", thinking="enabled")
    sent: list = []
    with ev.eval_route():
        book = CreditBook(tmp_path / "eval", dict(transport.load_policy(), enabled=True))
        out = _client(transport, book, sent).generate(msgs, "claude-sonnet-5-5", max_tokens=5000, client_request_id="b",
                                                      process_id="prospectus_writer", credit_tier="mid",
                                                      thinking="enabled")
        snap = book.snapshot(now=NOW)
    payload = sent[-1][1]
    assert payload["model"] == "claude-sonnet-5-5" and payload["max_tokens"] == 5000
    assert payload["output_config"]["effort"] == "medium" and payload["thinking"] == {"type": "adaptive"}
    assert out["_tradeai"]["estimated_cost_usd"] == pytest.approx(6000 * 2 / 1e6 + 3500 * 10 / 1e6)
    assert Decimal(snap["credit_used_usd"]) == Decimal("0.047") and snap["open_reservations"] == 0
    rows = [json.loads(x) for x in book.path.read_text().splitlines() if x.strip()]
    assert {r.get("tier") for r in rows if r.get("event") == "reserve"} == {"mid"}  # a tier the journal knows


# ── budget and preflight ──────────────────────────────────────────────────────────────────────────────────────────
def test_budget_stop_is_a_credit_refusal_so_the_writer_queues_instead_of_failing():
    b = ev.Budget(cap_usd=0.30)
    b.check(0.25, "writer")
    b.add("writer", {"estimated_cost_usd": 0.2}, SYM)
    with pytest.raises(ev.BudgetStop) as exc:
        b.check(0.25, "writer")
    assert gen._credit_refusal(exc.value) and b.calls[0]["cost_usd"] == 0.2


class FakeLC:
    def __init__(self, spent=0.0, calls=0):
        self.spent, self.n = spent, calls

    def get_process_config(self, pid):
        return {"daily_cost_cap_usd": 40.0 if pid == "prospectus_writer" else 0.5,
                "daily_soft_cap": 200 if pid == "prospectus_writer" else 250}

    def ledger_paid_usd_today(self, pid):
        return self.spent if pid == "prospectus_writer" else 0.0

    def calls_today(self, pid):
        return self.n

    def _conn(self):
        raise OSError("no database in tests")


def test_preflight_quotes_every_limit_and_sizes_under_the_lowest(tmp_path):
    _, transport = _modules()
    policy = ev.overlay_policy(dict(transport.load_policy(), enabled=True))
    pf = ev.preflight(state_root=tmp_path, n_symbols=5, cap_usd=3.0, est_per_symbol_usd=0.12, now=NOW, policy=policy,
                      lc=FakeLC(), search_status=lambda: {"remaining_today": 10})
    assert set(pf["limits"]) >= {"credit_journal", "per_call_cap", "process:prospectus_writer",
                                 "process:prospectus_fact_check", "db_backstop", "global_daily_provider_cap",
                                 "search_budget"}
    assert pf["limits"]["db_backstop"].get("error") and pf["lowest"] == "db_daily" and not pf["ok"]  # unreadable → refuse
    pf2 = ev.preflight(state_root=tmp_path, n_symbols=5, cap_usd=0.75, est_per_symbol_usd=0.12, now=NOW, policy=policy)
    assert pf2["lowest"] == "eval_cap" and pf2["symbols_that_fit"] == 2  # (0.75 - 0.50 ceiling) // 0.12
    pf3 = ev.preflight(state_root=tmp_path, n_symbols=5, cap_usd=3.0, est_per_symbol_usd=0.12, now=NOW, policy=policy)
    assert pf3["ok"] and pf3["symbols_that_fit"] == 5
    paused = ev.preflight(state_root=tmp_path, n_symbols=5, cap_usd=3.0, est_per_symbol_usd=0.12,
                          now=NOW, policy=dict(policy, enabled=False))
    assert paused["symbols_that_fit"] == 0 and paused["limits"]["credit_journal"]["status"] == "DISABLED"


# ── run, score, outputs ───────────────────────────────────────────────────────────────────────────────────────────
def test_dry_run_assembles_gates_and_sizes_with_no_model_call_and_no_store_write(tmp_path):
    seed_opus(tmp_path)
    before = tree(tmp_path)
    writer = stub_writer(FakeSources(tmp_path), model="claude-sonnet-5-5")
    out = tmp_path / "eval-out"
    res = ev.run([{"symbol": SYM, "category": "tech"}], deps=deps_for(tmp_path, writer), cfg=load_config(), out=out,
                 apply=False, budget=ev.Budget(3.0), settings=qg.load_settings(), now_fn=lambda: NOW,
                 preflight_fn=lambda n, est: {"ok": True, "symbols_that_fit": n, "est": est})
    assert res["mode"] == "dry_run" and writer.calls == [] and tree(tmp_path) == before
    row = res["plan"][0]
    assert row["symbol"] == SYM and row["prompt_bytes"] > 1000 and row["gate_layer1"] in ("pass", "soft_fail")
    assert row["opus_version"] and res["preflight"]["est"] > 0


def test_apply_writes_only_to_out_and_scores_both_sides(tmp_path):
    opus = seed_opus(tmp_path)
    base = store.base_dir(tmp_path, load_config())
    before = tree(base)
    writer = stub_writer(FakeSources(tmp_path), model="claude-sonnet-5-5")
    ai_calls = []
    ai = lambda prompt, *, max_tokens, timeout: (ai_calls.append(1) or '{"anomalies": []}', {"estimated_cost_usd": 0.002})  # noqa: E731
    budget = ev.Budget(3.0)
    deps = deps_for(tmp_path, ev.budget_writer(writer, budget, worst_usd=0.5, symbol_ref={}),
                    ai_fn=ev.budget_ai(ai, budget, worst_usd=0.1, symbol_ref={}, what="gate_layer2"))
    out = tmp_path / "eval-out"
    sel = [{"symbol": SYM, "category": "tech", "version": opus["version"]}]
    res = ev.run(sel, deps=deps, cfg=load_config(), out=out, apply=True, budget=budget, settings=qg.load_settings(),
                 now_fn=lambda: NOW, preflight_fn=lambda n, est: {"ok": True, "symbols_that_fit": n})
    assert res["write"]["stopped_reason"] is None and not res["write"]["rows"][0].get("error")
    assert tree(base) == before  # the prospectus store, index and queue are untouched
    assert {p for p, _ in writer.calls} == {"prospectus_writer"}
    assert [m for _, m in writer.calls] == [4000, 5000]  # web plan turn, then the Watch writer at 5,000 tokens
    sdir = next((out / "sonnet" / SYM).iterdir())
    assert (sdir / "prospectus.pdf").read_bytes().startswith(b"%PDF") and (sdir / "house_facts.json").is_file()
    assert json.loads((sdir / "prospectus.json").read_text())["model"] == "claude-sonnet-5-5"
    result = ev.score(sel, deps=deps, cfg=load_config(), out=out, settings=qg.load_settings(), budget=budget,
                      write_rows=res["write"]["rows"], now=NOW)
    row = result["rows"][0]
    assert row["opus"]["cost"]["mode"] == "batch" and row["sonnet"]["cost"]["mode"] == "sync"
    assert row["opus"]["cost"]["batch_equivalent_usd"] == pytest.approx(0.12)
    assert row["sonnet"]["spot"]["house"]["differs"] == []  # the new report carries the house facts it was given
    assert row["sonnet"]["measure"]["sections_written"] == row["sonnet"]["measure"]["sections_expected"]
    assert row["sonnet"]["measure"]["guard_drops"].get("ungrounded_number")  # the fixture's 37.9% is dropped
    assert set(row["files"]) == {"Opus PDF", "Sonnet PDF", "Sonnet HTML"}
    assert (out / "pdf" / f"{SYM}_opus.pdf").is_file() and (out / "pdf" / f"{SYM}_sonnet.pdf").is_file()
    for name in ("comparison.json", "SCORECARD.md", "comparison.html"):
        assert (out / name).is_file()
    html = (out / "comparison.html").read_text()
    assert "prefers-color-scheme:dark" in html and "max-width:760px" in html and SYM in html
    assert result["recommendation"]["verdict"] in ("SONNET_MATCHES_ON_ACCURACY", "KEEP_OPUS")
    assert result["budget"]["spent_usd"] == pytest.approx(0.01 + 0.07 + 0.002 * len(ai_calls))
    assert len(ai_calls) == 3  # layer 2 inside the write, then the gate review of each side


def test_credit_refusal_stops_cleanly_and_later_symbols_are_not_written(tmp_path):
    seed_opus(tmp_path, "ZZCC")
    seed_opus(tmp_path, "ZZAA")
    writer = stub_writer(FakeSources(tmp_path), model="claude-sonnet-5-5", fail_on={"ZZCC"})
    res = ev.run([{"symbol": "ZZCC"}, {"symbol": "ZZAA"}], deps=deps_for(tmp_path, writer), cfg=load_config(),
                 out=tmp_path / "o", apply=True, budget=ev.Budget(3.0), settings=qg.load_settings(),
                 now_fn=lambda: NOW, preflight_fn=lambda n, est: {"ok": True, "symbols_that_fit": n})
    rows = res["write"]["rows"]
    assert "PAUSED_TODAY" in res["write"]["stopped_reason"] and all(r.get("error") for r in rows)
    assert not (tmp_path / "o" / "sonnet").exists()


def test_hard_cap_stops_before_the_call_that_could_cross_it(tmp_path):
    seed_opus(tmp_path)
    inner = stub_writer(FakeSources(tmp_path), model="claude-sonnet-5-5")
    budget = ev.Budget(0.40)
    res = ev.run([{"symbol": SYM}], deps=deps_for(tmp_path, ev.budget_writer(inner, budget, worst_usd=0.5, symbol_ref={})),
                 cfg=load_config(), out=tmp_path / "o", apply=True, budget=budget, settings=qg.load_settings(),
                 now_fn=lambda: NOW, preflight_fn=lambda n, est: {"ok": True, "symbols_that_fit": n})
    assert inner.calls == [] and "eval hard cap" in res["write"]["stopped_reason"]


def test_a_non_sonnet_answer_is_never_scored_as_sonnet(tmp_path):
    seed_opus(tmp_path)
    writer = stub_writer(FakeSources(tmp_path), model="claude-opus-5-5")
    res = ev.run([{"symbol": SYM}], deps=deps_for(tmp_path, writer), cfg=load_config(), out=tmp_path / "o", apply=True,
                 budget=ev.Budget(3.0), settings=qg.load_settings(), now_fn=lambda: NOW,
                 preflight_fn=lambda n, est: {"ok": True, "symbols_that_fit": n})
    assert "is not claude-sonnet-5-5" in res["write"]["rows"][0]["error"]


def test_preflight_refusal_writes_nothing(tmp_path):
    seed_opus(tmp_path)
    writer = stub_writer(FakeSources(tmp_path), model="claude-sonnet-5-5")
    res = ev.run([{"symbol": SYM}], deps=deps_for(tmp_path, writer), cfg=load_config(), out=tmp_path / "o", apply=True,
                 budget=ev.Budget(3.0), settings=qg.load_settings(), now_fn=lambda: NOW,
                 preflight_fn=lambda n, est: {"ok": False, "symbols_that_fit": 0, "lowest": "credit_daily"})
    assert res["stopped_reason"].startswith("preflight") and writer.calls == []


# ── scoring pieces ────────────────────────────────────────────────────────────────────────────────────────────────
def _doc(body: str, facts: list[dict]) -> dict:
    return {"symbol": "ZZQQ", "scope": "watch", "sections": [{"id": "summary_verdict", "title": "Summary", "body_md": body}],
            "facts": facts}


def test_spot_check_classifies_numbers_and_dates_against_cited_facts():
    facts = [{"id": "F1", "label": "Last close", "value": 41.5, "unit": "$", "as_of": "2026-10-26"},
             {"id": "F2", "label": "Analyst target mean", "value": 55.0, "unit": "$"},
             {"id": "F3", "label": "Next earnings date", "text": "2026-11-05"}]
    body = ("The stock closed at $41.50 [F1]. The mean target is $55 [F2]. Peers trade at $55 [F1]. "
            "Margins are 23.7% [F1]. Results are due 2026-11-05 [F3] and the call is on December 3.")
    sc = ev.spot_check(_doc(body, facts), house_facts=[dict(facts[0], value=44.0)])
    assert sc["counts"] == {"ok": 2, "uncited": 1, "unsupported": 1}
    assert sc["by_kind"]["price"]["unsupported"] == 1 and sc["by_kind"]["target"]["ok"] == 1
    assert [d["date"] for d in sc["dates"]["unsupported"]] == ["*-12-03"]
    margins = ev.spot_check(_doc("Gross margin 95.0% [F1]. Operating margin 44.2% [F1]. Due Nov 5 [F3].", facts))
    assert margins["dates"] == {"total": 1, "unsupported": []}  # "margin 95" is not March 95
    assert sc["house"]["differs"][0]["label"] == "Last close"


def test_measure_counts_sections_specificity_vague_words_and_guard_drops():
    doc = _doc("Revenue grew 12.5% [F1]. Momentum is strong and robust.", [])
    doc["guard_log"] = [{"reason": "ungrounded_number"}, {"reason": "behavior"}]
    m = ev.measure(doc)
    assert m["sections_written"] == 1 and m["sections_expected"] == 8 and m["vague_words"] == 2
    assert m["citations"] == 1 and m["specific_sentence_pct"] == 50.0
    assert m["guard_drops"] == {"ungrounded_number": 1, "behavior": 1}


def test_recommend_keeps_opus_on_any_accuracy_regression_and_needs_every_symbol():
    base = {"reports": 5, "audit_p1": 9, "audit_p2": 2, "gate_pass": 0, "gate_hard_fail": 0, "unsupported_rate": 0.02,
            "prose_uncited": 3, "dates_unsupported": 1, "guard_drops": 6, "guard_drops_per_1000w": 2.0,
            "sections_written": 40, "sections_expected": 40, "house_differs": 0, "audit_prose": 0,
            "batch_equivalent_usd_avg": 0.12}
    same = dict(base, batch_equivalent_usd_avg=0.03, audit_p1=0)
    r = ev.recommend(base, same)
    assert r["verdict"] == "SONNET_MATCHES_ON_ACCURACY" and r["batch_cost_saving_pct"] == 75.0
    assert r["input_vintage"]["audit_p1"] == {"opus": 9, "sonnet": 0}  # reported, never the deciding test
    assert ev.recommend(base, dict(same, audit_p1=20))["verdict"] == "SONNET_MATCHES_ON_ACCURACY"
    for worse in (dict(same, unsupported_rate=0.2), dict(same, guard_drops_per_1000w=4.0), dict(same, audit_prose=1),
                  dict(same, house_differs=1), dict(same, sections_written=39)):
        assert ev.recommend(base, worse)["verdict"] == "KEEP_OPUS"
    assert ev.recommend(base, dict(same, reports=4))["verdict"] == "INCOMPLETE"


def test_candidates_are_ready_opus_watch_reports_inside_the_window_and_never_holdings(tmp_path):
    seed_opus(tmp_path, "ZZCC")
    seed_opus(tmp_path, "ZZAA")
    base = store.base_dir(tmp_path, load_config())
    rows = ev.candidates(base, hours=48, now=NOW, holdings={"ZZAA"})
    assert [r["symbol"] for r in rows] == ["ZZCC"] and rows[0]["mode"] == "batch"
    assert ev.candidates(base, hours=1, now=NOW, holdings=set()) == []


def test_out_dir_inside_the_prospectus_store_is_refused(tmp_path):
    cfg = load_config()
    with pytest.raises(SystemExit, match="inside the prospectus store"):
        ev._guard_out(store.base_dir(tmp_path, cfg) / "eval", tmp_path, cfg)
    ev._guard_out(tmp_path / "elsewhere", tmp_path, cfg)
