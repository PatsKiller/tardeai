"""When the answer is stale or missing, the desk must GO FIND OUT -- through
declared vectors, in a declared order, inside a budget, leaving a receipt --
instead of serving the old value or opening a pending and hoping.

The operator asked (2026-09-13): "what happens when the information is stale or
it doesn't meet the operator's need -- how does it find out through multiple
different vectors: one for Hermes research, two for like DeepSeek curation,
etc." Before Phase 7 the answer was: it mostly doesn't.

Everything here is offline. Every vector's I/O is replaced by a fake that
records whether it was called; receipts go to tmp_path; the desk's evidence
gather, gap registration and Hermes enqueue are stubbed. No provider, model,
producer or Telegram is reached. The negative control switches the resolver
OFF and shows the pre-Phase-7 behaviour: a pending with no ETA.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# The desk imports the resolver as scripts.lib.gap_resolver; import the SAME
# module object here so monkeypatches land where the desk looks.
import scripts.lib.gap_resolver as gr  # noqa: E402
# data_broker is spelled lib.data_broker by its own __init__ -- one spelling.
import lib.data_broker.gap_hook as hook  # noqa: E402
import lib.cio_operator_desk_loop as desk  # noqa: E402

COVERS = ["scripts/lib/gap_resolver.py", "scripts/lib/data_broker/gap_hook.py"]

NOW = datetime(2026, 9, 13, 18, 0, tzinfo=timezone.utc)
WMT_INTENT = {"intent": "market", "symbols": ["WMT"], "needs": ["analyst_view", "research"],
              "text": "what are analysts saying about Walmart"}
INCOMPLETE = {
    "complete": False,
    "gaps": [{"domain": "analyst_view", "symbol": "WMT", "field": "analyst_view",
              "reason": "no analyst coverage on file for WMT", "gap_type": "missing_analyst_coverage"}],
    "blocking_gaps": [{"domain": "analyst_view", "symbol": "WMT", "field": "analyst_view",
                       "reason": "no analyst coverage on file for WMT", "gap_type": "missing_analyst_coverage"}],
    "sources": [],
}

#: Routing fixture, not a credential: passed into desk calls and asserted back
#: out unchanged, so its identity is irrelevant. tg_chat_ids.chat_ids() is not
#: used -- it reads TELEGRAM_CHAT_ID from the environment and returns a LIST,
#: which would break these equality assertions and make an offline test depend
#: on the host.
OPERATOR_CHAT = "6993102664"  # hardcode-ok: routing fixture, not a credential


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


class _Fake:
    """A vector stand-in that records calls and returns a fixed VectorResult."""

    def __init__(self, outcome="no_answer", **kw):
        self.calls = 0
        self.out = gr.VectorResult(outcome, **kw)

    def __call__(self, gap, entry, ctx):
        self.calls += 1
        return self.out


def _all_fakes(**overrides) -> dict[str, _Fake]:
    fakes = {v: _Fake() for v in gr.VECTORS}
    fakes.update(overrides)
    return fakes


@pytest.fixture(autouse=True)
def _default_chain_unless_a_test_declares_one(monkeypatch):
    """These tests prove the resolver's semantics against DEFAULT_ON_GAP. Since
    integration the live registry declares a chain per domain (e.g.
    analyst_opinion has no hermes_research slot), so a test that reads the live
    file would be testing the operator's chain, not the resolver. A test that
    passes its own ``authority=`` still gets exactly what it declared."""
    real = gr.registry_domain

    def patched(domain, *, authority=None):
        row = dict(real(domain, authority=authority) or {})
        if authority is None:
            row.pop("on_gap", None)
        return row

    monkeypatch.setattr(gr, "registry_domain", patched)


@pytest.fixture
def ctx(tmp_path):
    return gr.Context(now=lambda: NOW, receipts_path=tmp_path / "receipts.jsonl", live=False)


@pytest.fixture
def gap():
    return gr.DataGap(domain="analyst_view", subject="WMT", question="analyst view for WMT",
                      why="no_coverage", requester="operator:1")


# ── the chain is normalised: free → metered → paid, operator_ask last ────────


def test_chain_order_is_free_then_metered_then_paid_whatever_the_registry_says():
    scrambled = [
        {"vector": "operator_ask", "cost_class": "free"},
        {"vector": "governed_search", "cost_class": "paid"},
        {"vector": "hermes_research", "cost_class": "metered"},
        {"vector": "refresh_producer", "cost_class": "free"},
        {"vector": "backup_provider", "cost_class": "free"},
    ]
    chain = gr.normalise_chain(scrambled)
    classes = [gr.COST_RANK[c["cost_class"]] for c in chain if c["vector"] != "operator_ask"]
    assert classes == sorted(classes), "free before metered before paid"
    assert chain[-1]["vector"] == "operator_ask", "operator_ask is last, never first"
    assert [c["vector"] for c in chain] == [
        "refresh_producer", "backup_provider", "hermes_research", "governed_search", "operator_ask",
    ]


def test_vectors_run_in_normalised_order_and_every_attempt_is_receipted(ctx, gap):
    fakes = _all_fakes()
    chain = list(reversed(gr.DEFAULT_ON_GAP))  # registry listed them backwards
    res = gr.resolve(gap, chain=chain, vectors=fakes, ctx=ctx)
    receipts = _rows(ctx.receipts)
    ranks = [gr.COST_RANK[r["cost_class"]] for r in receipts if r["vector"] != "operator_ask"]
    assert ranks == sorted(ranks), "free ran before metered before paid"
    assert receipts[-1]["vector"] == "operator_ask"
    # Within a class the registry's own order is honoured (here: reversed).
    assert [r["vector"] for r in receipts if r["cost_class"] == "free"][:2] == ["backup_provider", "refresh_producer"]
    assert set(r["vector"] for r in receipts) == set(gr.VECTORS)
    assert len(receipts) == len(gr.VECTORS) == len(res.attempts)
    for r in receipts:
        assert r["schema"] == gr.RECEIPT_SCHEMA
        assert r["gap_id"] == gap.gap_id
        assert r["outcome"] in gr.OUTCOMES
        assert r["cost_class"] in gr.COST_CLASSES
        assert r["started"] and r["finished"]
    assert res.outcome == "no_coverage"
    assert res.answered is False


def test_unknown_vectors_in_a_registry_chain_are_dropped_not_run():
    chain = gr.normalise_chain([{"vector": "phone_a_friend", "cost_class": "free"},
                                {"vector": "refresh_producer", "cost_class": "free"}])
    assert [c["vector"] for c in chain] == ["refresh_producer"]


def test_load_on_gap_reads_the_registry_key_and_falls_back_to_the_default():
    authority = {"domains": [
        {"domain": "analyst_opinion", "on_gap": [
            {"vector": "hermes_research", "cost_class": "metered", "max_per_day": 2},
            {"vector": "refresh_producer", "cost_class": "free", "max_per_day": 3},
        ]},
        {"domain": "technicals"},
    ], "providers": {}}
    declared = gr.load_on_gap("analyst_view", authority=authority)
    assert [c["vector"] for c in declared] == ["refresh_producer", "hermes_research"]
    assert declared[1]["max_per_day"] == 2
    fallback = gr.load_on_gap("technicals", authority=authority)
    assert [c["vector"] for c in fallback] == [c["vector"] for c in gr.DEFAULT_ON_GAP]


def test_the_registry_declares_a_valid_on_gap_chain_for_every_domain():
    """The Phase 7 patch was applied at integration (2026-09-13); the registry is
    now the source. Every domain carries on_gap; every step names a declared
    vector and cost class; operator_ask is last; the chain is already in rail
    order. The patch file must still be a subset of what the registry says."""
    patch = json.loads((ROOT / "docs/implementation/sot/phase7_registry_patch.json").read_text())
    auth = json.loads((ROOT / "config/data_source_authority.json").read_text())
    domains = {d["domain"]: d for d in auth["domains"]}
    assert set(patch["domains_on_gap"]) <= set(domains)
    for dom, row in domains.items():
        assert "on_gap" in row, f"{dom}: no on_gap declared"
        chain = row["on_gap"]
        for c in chain:
            assert c["vector"] in gr.VECTORS, (dom, c)
            assert c["cost_class"] in gr.COST_CLASSES, (dom, c)
        if chain:
            assert chain[-1]["vector"] == "operator_ask", f"{dom}: operator_ask must be last"
            assert gr.normalise_chain(chain) == chain, f"{dom}: chain is not already in rail order"


# ── the free_first rail: paid needs an operator grant ─────────────────────────


def test_a_paid_vector_without_operator_grant_is_budget_denied_by_the_rail(ctx, gap):
    fakes = _all_fakes()
    chain = [{"vector": "refresh_producer", "cost_class": "free"},
             {"vector": "governed_search", "cost_class": "paid"}]
    ctx.env = {}
    gr.resolve(gap, chain=chain, vectors=fakes, ctx=ctx)
    receipts = _rows(ctx.receipts)
    paid = [r for r in receipts if r["vector"] == "governed_search"][0]
    assert paid["outcome"] == "budget_denied"
    assert "PAID_PROVIDER_FORBIDDEN" in paid["detail"]
    assert fakes["governed_search"].calls == 0, "the paid vector never ran"


def test_a_paid_vector_with_operator_grant_runs(ctx, gap):
    fakes = _all_fakes()
    chain = [{"vector": "governed_search", "cost_class": "paid"}]
    ctx.env = {gr.FLAG_PAID: "1"}
    gr.resolve(gap, chain=chain, vectors=fakes, ctx=ctx)
    assert fakes["governed_search"].calls == 1


# ── a retired provider is never a vector ──────────────────────────────────────


def test_a_retired_primary_provider_is_skipped_with_a_receipt_and_the_vector_never_runs(ctx, gap):
    """quote_price's primary is alpaca; pretend the registry pinned it to a retired one."""
    fakes = _all_fakes()
    authority = {"domains": [{"domain": "analyst_opinion", "primary_provider": "fmp", "backup": []}], "providers": {}}
    assert gr_is_retired("fmp"), "precondition: fmp is retired in the live registry"
    res = gr.resolve(gap, chain=[{"vector": "refresh_producer", "cost_class": "free"}],
                     vectors=fakes, ctx=ctx, authority=authority)
    receipts = _rows(ctx.receipts)
    assert receipts[0]["outcome"] == "retired_skipped"
    assert receipts[0]["provider"] == "fmp"
    assert fakes["refresh_producer"].calls == 0
    assert res.outcome == "no_coverage"


def test_backup_chain_refuses_a_retired_slot_up_front(ctx, gap, monkeypatch):
    """The real backup_provider walk: the retired slot is a receipt, not a fall-through."""
    monkeypatch.setattr(gr, "registry_domain",
                        lambda domain, authority=None: {"domain": "analyst_opinion",
                                                        "backup": ["fmp", "yfinance_on_demand"]})
    called = []
    monkeypatch.setitem(gr.BACKUP_FETCHERS, ("analyst_opinion", "yfinance_on_demand"),
                        lambda g, c: called.append(1) or gr.VectorResult("answered", answer={"x": 1}))
    out = gr._v_backup_provider(gap, {}, ctx)
    assert out.outcome == "retired_skipped" and out.provider == "fmp"
    assert called == [], "nothing after the retired slot ran either -- the refusal is the receipt"


def gr_is_retired(p: str) -> bool:
    from scripts.lib.retired_providers import is_retired
    return is_retired(p)


# ── budgets ───────────────────────────────────────────────────────────────────


def test_budget_exhaustion_yields_budget_denied_and_the_chain_moves_on(ctx, gap):
    # One attempt already spent today on refresh_producer.
    gr._append_receipt(ctx.receipts, {"vector": "refresh_producer", "outcome": "no_answer",
                                      "started": NOW.isoformat(), "gap_id": "earlier"})
    fakes = _all_fakes(backup_provider=_Fake("answered", answer={"rating": "buy"}, as_of=NOW.isoformat(),
                                             provider="yfinance_on_demand"))
    chain = [{"vector": "refresh_producer", "cost_class": "free", "max_per_day": 1},
             {"vector": "backup_provider", "cost_class": "free", "max_per_day": 5}]
    res = gr.resolve(gap, chain=chain, vectors=fakes, ctx=ctx)
    receipts = _rows(ctx.receipts)[1:]
    assert receipts[0]["vector"] == "refresh_producer" and receipts[0]["outcome"] == "budget_denied"
    assert "1/1" in receipts[0]["detail"]
    assert fakes["refresh_producer"].calls == 0
    assert receipts[1]["vector"] == "backup_provider" and receipts[1]["outcome"] == "answered"
    assert res.answered and res.vector == "backup_provider"


def test_refusals_do_not_consume_budget(ctx):
    rows = [{"vector": "v", "outcome": o, "started": NOW.isoformat()}
            for o in ("budget_denied", "retired_skipped", "no_answer", "error")]
    assert gr.attempts_today("v", now=NOW, rows=rows) == 2


def test_budget_is_per_utc_day(ctx):
    rows = [{"vector": "v", "outcome": "no_answer", "started": "2026-09-12T23:59:00+00:00"}]
    assert gr.attempts_today("v", now=NOW, rows=rows) == 0


# ── a fast answer stops the chain; a slow one carries an ETA ──────────────────


def test_a_fast_vector_answering_stops_the_chain(ctx, gap):
    fakes = _all_fakes(refresh_producer=_Fake("answered", answer={"target_mean": 110.0},
                                              as_of="2026-09-13T17:00:00+00:00", provider="yahoo"))
    res = gr.resolve(gap, vectors=fakes, ctx=ctx)
    assert res.answered and res.outcome == "answered"
    assert res.vector == "refresh_producer"
    assert res.source == "refresh_producer:yahoo"
    assert res.as_of == "2026-09-13T17:00:00+00:00"
    assert res.age_hours == 1.0, "age is carried; the answer is never presented as 'now'"
    assert res.eta_seconds is None
    assert len(_rows(ctx.receipts)) == 1
    assert all(f.calls == 0 for v, f in fakes.items() if v != "refresh_producer")


def test_only_a_slow_vector_queued_gives_an_eta_and_no_answer(ctx, gap):
    fakes = _all_fakes(hermes_research=_Fake("queued", provider="hermes", eta_seconds=1800))
    res = gr.resolve(gap, vectors=fakes, ctx=ctx)
    assert res.answered is False
    assert res.outcome == "queued"
    assert res.eta_seconds == 1800
    assert res.eta_text == "≈ 30 min"
    assert res.vector == "hermes_research"
    # operator_ask still ran (last) and the question is carried for the caller.
    assert fakes["operator_ask"].calls == 1


def test_operator_ask_is_reached_only_after_everything_else(ctx, gap):
    order = []

    def mk(name):
        def _f(g, e, c):
            order.append(name)
            return gr.VectorResult("no_answer")
        return _f

    gr.resolve(gap, vectors={v: mk(v) for v in gr.VECTORS}, ctx=ctx)
    assert order[-1] == "operator_ask" and order.index("operator_ask") == len(gr.VECTORS) - 1


def test_a_vector_that_raises_is_an_error_receipt_not_a_dead_chain(ctx, gap):
    def boom(g, e, c):
        raise RuntimeError("provider on fire")

    fakes = _all_fakes()
    fakes["refresh_producer"] = boom
    fakes["backup_provider"] = _Fake("answered", answer={"ok": 1}, as_of=NOW.isoformat(), provider="p")
    res = gr.resolve(gap, vectors=fakes, ctx=ctx)
    r = _rows(ctx.receipts)
    assert r[0]["outcome"] == "error" and "provider on fire" in r[0]["detail"]
    assert res.answered and res.vector == "backup_provider"


# ── llm_curation curates; it never invents ────────────────────────────────────


def test_llm_curation_never_calls_a_model_when_nothing_was_gathered(ctx, gap, monkeypatch):
    ctx.live = True
    monkeypatch.setattr(gr, "_curate_deepseek", lambda p: pytest.fail("model called with no evidence"))
    monkeypatch.setattr(gr, "_curate_ollama", lambda p: pytest.fail("model called with no evidence"))
    out = gr._v_llm_curation(gap, {}, ctx)
    assert out.outcome == "no_answer"
    assert "no_evidence_to_curate" in out.detail


def test_llm_curation_output_is_labelled_with_source_and_model_id(ctx, monkeypatch):
    import scripts.lib.deepseek_offpeak as offpeak

    ctx.live = True
    monkeypatch.setattr(offpeak, "is_bulk_deepseek_window", lambda dt=None: True)
    monkeypatch.setattr(gr, "_curate_deepseek", lambda p: ("Evidence says targets cluster near 110.", "deepseek-v4-flash"))
    monkeypatch.setattr(gr, "_curate_ollama", lambda p: pytest.fail("off-peak window open: Ollama must not run"))
    g = gr.DataGap(domain="analyst_view", subject="WMT", question="q",
                   evidence={"search_results": [{"title": "t", "url": "u", "description": "d"}]})
    out = gr._v_llm_curation(g, {}, ctx)
    assert out.outcome == "partial", "curation is evidence, never an authoritative answer"
    assert out.answer["source"] == "llm_curation"
    assert out.answer["model"] == "deepseek-v4-flash" == out.model
    assert out.answer["curated_from"] == ["search_results"]


def test_llm_curation_uses_ollama_when_the_deepseek_window_is_closed(ctx, monkeypatch):
    import scripts.lib.deepseek_offpeak as offpeak

    ctx.live = True
    monkeypatch.setattr(offpeak, "is_bulk_deepseek_window", lambda dt=None: False)
    monkeypatch.setattr(gr, "_curate_deepseek", lambda p: pytest.fail("window closed: DeepSeek must not run"))
    monkeypatch.setattr(gr, "_curate_ollama", lambda p: ("local summary", "ollama:gemma3:12b"))
    g = gr.DataGap(domain="analyst_view", subject="WMT", question="q", evidence={"x": 1})
    out = gr._v_llm_curation(g, {}, ctx)
    assert out.provider == "ollama" and out.model == "ollama:gemma3:12b"
    assert out.answer["source"] == "llm_curation"


def test_evidence_gathered_by_search_flows_into_curation(ctx, gap):
    seen = {}

    def curate(g, e, c):
        seen["evidence"] = dict(g.evidence)
        return gr.VectorResult("no_answer")

    fakes = _all_fakes(governed_search=_Fake("partial", provider="brave", evidence={"search_results": [{"t": 1}]}))
    fakes["llm_curation"] = curate
    gr.resolve(gap, vectors=fakes, ctx=ctx)
    assert seen["evidence"] == {"search_results": [{"t": 1}]}


# ── side effects stay off unless armed ────────────────────────────────────────


def test_governed_search_makes_no_call_when_the_router_is_disabled(ctx, gap, monkeypatch):
    import scripts.lib.brave_router as br

    monkeypatch.delenv(br.FLAG_ENABLED, raising=False)
    monkeypatch.setattr(br, "search", lambda *a, **k: pytest.fail("router called while disabled"))
    out = gr._v_governed_search(gap, {}, ctx)
    # Dry Context: free_search residual is dry-run, Brave never called.
    assert out.outcome == "no_answer"
    assert "router_disabled" in out.detail
    assert "free_search" in out.detail or out.provider == "searxng"


def test_governed_search_free_fallback_when_router_dark_and_live(gap, monkeypatch, tmp_path):
    """Live + router dark → free_search partial (feeds quality_escalate)."""
    import scripts.lib.brave_router as br
    import scripts.lib.free_search as fs

    monkeypatch.delenv(br.FLAG_ENABLED, raising=False)
    monkeypatch.setattr(br, "search", lambda *a, **k: pytest.fail("brave called"))

    class Resp:
        ok = True
        results = [{"title": "t", "snippet": "s", "url": "https://ex.com/1"}]
        reason = None

    monkeypatch.setattr(fs, "search", lambda *a, **k: Resp())
    ctx = gr.Context(live=True, receipts_path=tmp_path / "r.jsonl", env={})
    out = gr._v_governed_search(gap, {}, ctx)
    assert out.outcome == "partial"
    assert out.provider == "searxng"
    assert out.evidence.get("search_results")


def test_refresh_producer_dry_runs_without_the_arm_flag(ctx, monkeypatch):
    monkeypatch.setattr(gr.subprocess, "run", lambda *a, **k: pytest.fail("producer executed while disarmed"))
    g = gr.DataGap(domain="analyst_view", subject="WMT", question="q")
    out = gr._v_refresh_producer(g, {}, ctx)
    assert out.outcome == "no_answer" and out.detail.startswith("dry_run: would run scripts/pro_analyst_fetch.py")


def test_refresh_producer_says_no_producer_for_a_dead_feed(ctx):
    g = gr.DataGap(domain="watch_discovery", subject="WMT", question="q")
    out = gr._v_refresh_producer(g, {}, ctx)
    assert out.outcome == "no_answer" and out.detail.startswith("no_producer")


def test_backup_provider_dry_runs_without_the_arm_flag(ctx, gap, monkeypatch):
    monkeypatch.setitem(gr.BACKUP_FETCHERS, ("analyst_opinion", "yfinance_on_demand"),
                        lambda g, c: pytest.fail("provider fetched while disarmed"))
    out = gr._v_backup_provider(gap, {}, ctx)
    assert out.outcome == "no_answer" and out.detail.startswith("dry_run: would fetch from yfinance_on_demand")


def test_operator_ask_does_not_send_without_a_send_fn_and_returns_the_question(ctx, gap):
    out = gr._v_operator_ask(gap, {"expected_seconds": 7200}, ctx)
    assert out.outcome == "queued" and out.eta_seconds == 7200
    assert "≈ 120 min" in out.operator_question
    assert out.detail == "question embedded in caller's reply"


def test_gap_id_is_deterministic_for_the_same_question():
    a = gr.DataGap(domain="analyst_view", subject="wmt", question="q")
    b = gr.DataGap(domain="analyst_view", subject="WMT", question="q")
    assert a.gap_id == b.gap_id
    assert a.subject == "WMT" and a.symbols == ["WMT"]


# ── the desk wiring ───────────────────────────────────────────────────────────


@pytest.fixture
def desk_offline(monkeypatch, tmp_path):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.delenv("CIO_GAP_RESOLVER", raising=False)
    monkeypatch.setattr(desk, "PENDING_PATH", tmp_path / "pending.jsonl")
    monkeypatch.setattr(desk, "analyze_operator_intent", lambda text: dict(WMT_INTENT))
    monkeypatch.setattr(desk, "gather_tradeai_evidence", lambda intent: json.loads(json.dumps(INCOMPLETE)))
    monkeypatch.setattr(desk, "_register_gaps", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(desk, "_enqueue_hermes_research", lambda *a, **k: pytest.fail("old hermes path ran"))
    monkeypatch.setattr(desk, "_emit_telegram_desk_payload", lambda *a, **k: None)
    monkeypatch.setattr(gr, "RECEIPTS_PATH", tmp_path / "receipts.jsonl")
    return tmp_path


def _wire(monkeypatch, fakes):
    monkeypatch.setattr(gr, "DEFAULT_VECTORS", dict(fakes))


def test_desk_answers_now_when_a_fast_vector_answers(desk_offline, monkeypatch):
    _wire(monkeypatch, _all_fakes(backup_provider=_Fake(
        "answered", answer={"rating": "buy", "target_mean": 110.0}, as_of="2026-09-13T17:00:00+00:00",
        provider="yfinance_on_demand")))
    res = desk.handle_operator_desk_question(WMT_INTENT["text"], chat_id=OPERATOR_CHAT, message_id="7")
    assert res["kind"] == "answered"
    assert res["pending_id"] is None
    assert res["reply_source"] == "gap_resolver:backup_provider"
    assert "backup_provider:yfinance_on_demand" in res["text"]
    assert "as of 2026-09-13T17:00" in res["text"]
    assert "target_mean=110.0" in res["text"]
    assert _rows(desk.PENDING_PATH) == [], "answered now: no pending"
    assert res["gap_resolution"]["answered"] == ["analyst_opinion:WMT:backup_provider"]


def test_desk_opens_a_pending_with_the_eta_when_only_a_slow_vector_queued(desk_offline, monkeypatch):
    _wire(monkeypatch, _all_fakes(hermes_research=_Fake("queued", provider="hermes", eta_seconds=1800)))
    res = desk.handle_operator_desk_question(WMT_INTENT["text"], chat_id=OPERATOR_CHAT, message_id="7")
    assert res["kind"] == "deferred"
    assert res["pending_id"]
    assert res["eta_seconds"] == 1800
    assert "≈ 30 min" in res["text"]
    rows = _rows(desk.PENDING_PATH)
    assert rows and rows[-1]["status"] == "open" and rows[-1]["eta_seconds"] == 1800
    assert rows[-1]["resolver"]["queued"] == ["analyst_opinion:WMT:hermes_research"]


def test_desk_says_no_coverage_and_opens_nothing_when_every_vector_is_denied(desk_offline, monkeypatch):
    fakes = _all_fakes()
    fakes["governed_search"] = _Fake("budget_denied", provider="brave")
    _wire(monkeypatch, fakes)
    res = desk.handle_operator_desk_question(WMT_INTENT["text"], chat_id=OPERATOR_CHAT, message_id="7")
    assert res["kind"] == "no_coverage"
    assert res["pending_id"] is None
    assert "no coverage through any declared source" in res["text"]
    assert "governed_search=budget_denied" in res["text"]
    assert "say_so" in res["text"], "the domain's declared no_coverage behaviour is named"
    assert _rows(desk.PENDING_PATH) == [], "no silent pending"
    receipts = _rows(gr.RECEIPTS_PATH)
    assert len(receipts) == len(gr.VECTORS), "every attempt was receipted even though none answered"


def test_desk_uses_the_store_when_a_refresh_makes_it_complete(desk_offline, monkeypatch):
    complete = {"complete": True, "gaps": [], "blocking_gaps": [], "sources": ["analyst"],
                "available": {"analyst_view": {"items": [{"symbol": "WMT"}]}}}
    state = {"n": 0}

    def gather(intent):
        state["n"] += 1
        return json.loads(json.dumps(INCOMPLETE if state["n"] == 1 else complete))

    monkeypatch.setattr(desk, "gather_tradeai_evidence", gather)
    monkeypatch.setattr(desk, "_curate_from_evidence",
                        lambda text, ev: {"ok": True, "text": "WMT: from the store\nREAD_ONLY_ADVISORY",
                                          "source": "tradeai_deterministic", "model": None})
    _wire(monkeypatch, _all_fakes(refresh_producer=_Fake("answered", answer={"ran": True},
                                                         as_of=NOW.isoformat(), provider="yahoo")))
    res = desk.handle_operator_desk_question(WMT_INTENT["text"], chat_id=OPERATOR_CHAT, message_id="7")
    assert res["kind"] == "answered" and res["reply_source"] == "tradeai_deterministic"
    assert res["evidence_complete"] is True and res["blocking_gaps"] == []
    assert _rows(desk.PENDING_PATH) == []


def test_desk_still_refuses_an_unanswerable_ask_before_any_vector_runs(desk_offline, monkeypatch):
    spacex = {**WMT_INTENT, "symbols": []}
    monkeypatch.setattr(desk, "analyze_operator_intent", lambda text: dict(spacex))
    fakes = {v: (lambda g, e, c: pytest.fail("vector ran for an unanswerable ask")) for v in gr.VECTORS}
    _wire(monkeypatch, fakes)
    res = desk.handle_operator_desk_question("outlook for SpaceX", chat_id=OPERATOR_CHAT, message_id="7")
    assert res["kind"] == "unanswerable" and res["pending_id"] is None
    assert not gr.RECEIPTS_PATH.exists()


def test_negative_control_resolver_off_opens_a_pending_with_no_eta(desk_offline, monkeypatch):
    """The pre-Phase-7 path: defer, ticket, hope. No vectors, no ETA."""
    monkeypatch.setenv("CIO_GAP_RESOLVER", "0")
    monkeypatch.setattr(desk, "_enqueue_hermes_research", lambda *a, **k: {"ok": True})
    _wire(monkeypatch, {v: (lambda g, e, c: pytest.fail("resolver ran while disabled")) for v in gr.VECTORS})
    res = desk.handle_operator_desk_question(WMT_INTENT["text"], chat_id=OPERATOR_CHAT, message_id="7")
    assert res["kind"] == "deferred" and res["pending_id"]
    assert "≈" not in res["text"]
    assert res.get("eta_seconds") is None
    rows = _rows(desk.PENDING_PATH)
    assert rows and rows[-1]["status"] == "open" and "eta_seconds" not in rows[-1]
    assert not gr.RECEIPTS_PATH.exists(), "no receipts: nothing was tried"


def test_desk_falls_back_to_the_old_path_when_the_resolver_itself_breaks(desk_offline, monkeypatch):
    """A resolver traceback is a defect, not a fact about coverage."""
    monkeypatch.setattr(desk, "_enqueue_hermes_research", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(gr, "resolve", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("resolver bug")))
    res = desk.handle_operator_desk_question(WMT_INTENT["text"], chat_id=OPERATOR_CHAT, message_id="7")
    assert res["kind"] == "deferred" and res["pending_id"]
    assert "≈" not in res["text"]
    assert res["gap_resolution"]["errors"] == ["analyst_view:RuntimeError"]
    assert _rows(desk.PENDING_PATH)[-1]["status"] == "open"


def test_desk_hands_its_own_hermes_enqueue_to_the_resolver(desk_offline, monkeypatch):
    """Two import names, one function: the resolver must call the desk's copy."""
    calls = []
    monkeypatch.setattr(desk, "_enqueue_hermes_research",
                        lambda **kw: calls.append(kw) or {"ok": True, "plan_id": "plan_x", "emitted": 1})
    fakes = _all_fakes()
    fakes["hermes_research"] = gr._v_hermes_research   # the real vector, fake enqueue
    _wire(monkeypatch, fakes)
    res = desk.handle_operator_desk_question(WMT_INTENT["text"], chat_id=OPERATOR_CHAT, message_id="7")
    assert calls and calls[0]["symbols"] == ["WMT"] and calls[0]["chat_id"] == OPERATOR_CHAT
    assert res["kind"] == "deferred" and "≈ 30 min" in res["text"]


# ── the projection hook only enqueues ─────────────────────────────────────────


def test_gap_hook_enqueues_once_and_dedupes_within_the_hour(tmp_path):
    q = tmp_path / "queue.jsonl"
    a = hook.enqueue_gap("market_quote", "WMT", "price stale", stale_age_hours=3.0, path=q, now=NOW)
    b = hook.enqueue_gap("market_quote", "WMT", "price stale", stale_age_hours=3.1, path=q, now=NOW)
    assert a["enqueued"] is True and b["enqueued"] is False and b["reason"] == "deduped"
    rows = hook.read_queue(q)
    assert len(rows) == 1 and rows[0]["schema"] == hook.SCHEMA and rows[0]["status"] == "open"
    assert rows[0]["gap_id"] == a["gap_id"]


def test_gap_hook_never_raises_on_a_bad_path(tmp_path):
    out = hook.enqueue_gap("quote", "WMT", "q", path=tmp_path / "nope" / "x" / "queue.jsonl" / "dir")
    assert out["ok"] in (True, False) and "gap_id" in out
