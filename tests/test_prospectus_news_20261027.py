"""Prospectus NEWS methodology (operator 2026-10-27: "Implement these fixes … I need this to execute quickly").

Relevance gate (collisions, syndication dedupe, materiality), the Haiku classifier and the Sonnet CIO note (both
stubbed — no provider is reached), the rewrite decision (impact -> enqueue, coalescing, delta vs full), the window
receipt / outbox audit, the "Since this report" API field and the quality-gate collision check.

Synthetic tickers, names and headlines only (public repo); every store lives under a temp state root.
"""
from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.prospectus import batch as BATCH, load_config, news_gate as NG, news_note as NN, store  # noqa: E402
from scripts.lib.prospectus import quality_gate as QG  # noqa: E402
import prospectus_window as PW  # noqa: E402

GEN = "2026-10-26T12:00:00+00:00"
NOW = datetime(2026, 10, 27, 21, 50, tzinfo=timezone.utc)  # 17:50 ET, inside the post_close window
COLL = {"symbols": {"ZQX": {"issuer": "Zedquix Aerospace Fund", "exclude": [{"name": "Zeqqa", "why": "a London company"}]}},
        "foreign_exchange_prefixes": ["LON", "TSX"], "foreign_suffixes": ["L", "TO"]}


@pytest.fixture(autouse=True)
def no_real_batch(monkeypatch):
    monkeypatch.setattr(BATCH, "collect", lambda base, cfg, *, now, **_: {"written": [], "cost_usd": 0.0})
    monkeypatch.setattr(BATCH, "submit_due", lambda base, sources, cfg, *, now, **_: {"submitted": []})


@pytest.fixture(autouse=True)
def no_real_models(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test reached the governed model path")
    monkeypatch.setattr(NN, "_governed", refuse)


@pytest.fixture()
def cfg():
    return load_config()


# ── 1. relevance gate ─────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("title", [
    "Broker lifts target on Zeqqa (LON:ZQX) after printhead orders",
    "Zeqqa shares jump in London",
    "Zeqqa plc results (LSE: ZQX)",
    "ZQX.L climbs 4% in early trade",
])
def test_collision_headlines_rejected(title):
    item = {"id": "x", "title": title, "kind": "headline"}
    rel, why = NG.relevance(item, "ZQX", {"name": "Zedquix Aerospace Fund"}, collisions=COLL)
    assert rel == "collision" and why.startswith("collision")


def test_issuer_named_is_relevant_and_ticker_only_is_uncertain():
    named = {"title": "Zedquix Aerospace Fund sees record inflows", "kind": "headline"}
    assert NG.relevance(named, "ZQX", {"name": "Zedquix Aerospace Fund"}, collisions=COLL)[0] == "relevant"
    exch = {"title": "Something happened (NYSE Arca: ZQX)", "kind": "headline"}
    assert NG.relevance(exch, "ZQX", {"name": "Other"}, collisions=COLL)[0] == "relevant"
    bare = {"title": "ZQX moves higher", "kind": "headline"}
    assert NG.relevance(bare, "ZQX", {"name": "Zedquix Aerospace Fund"}, collisions=COLL)[0] == "uncertain"
    sec = {"title": "ZQX 8-K: Results of operations", "source": "sec_edgar", "catalyst_type": "earnings"}
    assert NG.relevance(sec, "ZQX", {}, collisions=COLL)[0] == "relevant"


def test_seeded_collision_config_has_the_two_known_cases():
    doc = NG.load_collisions()
    assert any(e["name"] == "Xaar" for e in doc["symbols"]["XAR"]["exclude"])
    assert doc["symbols"]["SPCX"]["exclude"]
    assert NG.collision_reason("Analyst note on Xaar (LON:XAR)", "XAR", {"name": "SPDR S&P Aerospace & Defense ETF"})
    assert NG.collision_reason("SPDR S&P Aerospace & Defense ETF adds holdings", "XAR", {}) is None


def test_syndicated_copies_dedupe_within_48h():
    items = NG.normalise([], [
        {"title": "Zedquix Aerospace Fund raises its dividend - Wire A", "published_at": "2026-10-27T10:00:00Z"},
        {"title": "Zedquix Aerospace Fund raises its dividend!", "published_at": "2026-10-27T12:00:00Z"},
        {"title": "Zedquix Aerospace Fund raises its dividend", "published_at": "2026-10-30T12:00:00Z"},  # > 48h
    ])
    kept, dups = NG.dedupe(items)
    assert len(dups) == 1 and len(kept) == 2
    assert kept[0]["at"] == "2026-10-27T10:00:00Z"  # the earliest copy wins


def test_materiality_from_catalyst_grade_and_type():
    assert NG.materiality({"catalyst_type": "filing_quarterly", "severity": "medium"})[0] is True
    assert NG.materiality({"catalyst_type": "earnings", "severity": "high"})[0] is True
    assert NG.materiality({"catalyst_type": "regulatory_disclosure", "severity": "low"})[0] is False
    assert NG.materiality({"catalyst_type": "analyst_upgrade", "severity": "low"})[0] is False  # below medium
    assert NG.materiality({"title": "Zedquix downgraded at a broker"})[0] is None  # untyped -> classifier
    assert NG.materiality({"title": "Zedquix to attend a conference"})[0] is False


def test_8k_is_accepted_and_collision_and_dupes_rejected():
    cats = [{"headline": "ZQX 8-K: Entry into a material agreement (Item 1.01) filed 2026-10-27",
             "catalyst_type": "material_agreement", "severity": "high", "source": "sec_edgar",
             "at": "2026-10-27T13:00:00Z"}]
    news = [{"title": "Zeqqa (LON:ZQX) wins a printer order", "published_at": "2026-10-27T09:00:00Z"},
            {"title": "Old news before the report", "published_at": "2026-10-20T09:00:00Z"}]
    rows = NG.review("ZQX", NG.normalise(cats, news), since=NG.since(GEN), identity={"name": "Zedquix Aerospace Fund"},
                     collisions=COLL)
    by = {r["title"][:8]: r for r in rows}
    assert by["ZQX 8-K:"]["verdict"] == "accepted" and by["ZQX 8-K:"]["kind"] == "filing"
    assert by["Zeqqa (L"]["verdict"] == "rejected" and by["Zeqqa (L"]["reason"] == "collision"
    assert "Old news" not in by  # before the report


def test_classifier_labels_fold_in_and_missing_label_is_retried():
    rows = [{"id": "u1", "title": "ZQX shares slide on a downgrade", "verdict": "uncertain", "relevant": None,
             "material": None, "why": "w"},
            {"id": "u2", "title": "ZQX earnings in focus", "verdict": "uncertain", "relevant": None, "material": None,
             "why": "w"}]
    NG.apply_classification(rows, {"u1": {"relevant": True, "material": True, "why": "downgrade of the issuer"}})
    assert rows[0]["verdict"] == "accepted" and rows[0]["classified_by"] == "haiku"
    assert rows[1]["reason"] == "classifier_unavailable" and rows[1]["retry"] is True
    # a retried row is judged again (not frozen as rejected) on the next window
    again = NG.review("ZQX", [dict(rows[1], at="2026-10-27T10:00:00Z")], since=NG.since(GEN), known={"u2": rows[1]},
                      collisions=COLL)
    assert again[0]["verdict"] == "uncertain"


def test_classify_and_note_parse_stubbed_outputs(cfg):
    def gen(prompt, *, process_id, max_tokens, timeout):
        assert process_id == NN.PROCESS_CLASSIFY and "ZQX" in prompt
        return json.dumps({"items": [{"id": "u1", "relevant": True, "material": False, "why": "recap"}]}), {"cost_usd": 0.001}
    labels, prov = NN.classify("ZQX", "Zedquix", [{"id": "u1", "title": "t", "source": "s"}], cfg=cfg, generate_fn=gen)
    assert labels == {"u1": {"relevant": True, "material": False, "why": "recap"}} and prov["cost_usd"] == 0.001
    note = NN.parse_note('{"impact": "breaker", "which_breaker": "B2", "one_line": "Customer concentration up."}')
    assert note["impact"] == "breaker" and note["which_breaker"] == "B2" and not note["behavior_guarded"]
    guarded = NN.parse_note('{"impact": "stop", "which_breaker": null, "one_line": "Move the stop to 40 and sell 50 shares."}')
    assert guarded["behavior_guarded"] and "withheld" in guarded["one_line"]  # MBI_BEHAVIOR=0
    with pytest.raises(ValueError):
        NN.parse_note('{"impact": "buy"}')


# ── 2. CIO note -> decision, coalescing, receipts ─────────────────────────────────────────────────────────────
class Src:
    def __init__(self, cats=None, news=None, bars=None):
        self._c, self._n, self._b = cats or {}, news or {}, bars or {}

    def holdings(self):
        return {"ZQX": {"market_value": 1000.0, "accounts": []}}

    def watch_symbols(self):
        return ["WQY"]

    def catalysts(self, sym):
        return self._c.get(sym, [])

    def news(self, sym):
        return self._n.get(sym, [])

    def bars(self, sym, days=1100):
        return self._b.get(sym, [])

    def cio(self, sym):
        return {}

    def stops(self, sym, accounts):
        return []


def seed(base: Path, sym: str, scope: str = "holding", version: str = "20261026T120000Z", close: float = 100.0):
    store.update_index(base, sym, version=version, generated_at=GEN, name="Zedquix Aerospace Fund", scope=scope,
                       status="ready", inputs_digest={})
    vdir = base / sym / version
    vdir.mkdir(parents=True, exist_ok=True)
    doc = {"symbol": sym, "version": version, "generated_at": GEN, "scope": scope, "status": "ready",
           "facts": [{"id": "F1", "kind": "price", "label": "Last close", "value": close}],
           "sections": [{"id": "thesis_breakers", "body_md": "- Customer concentration above half of revenue\n- Margin below 10%"}]}
    (vdir / "prospectus.json").write_text(json.dumps(doc))
    store.write_json(base / sym / "versions.json", [{"version": version, "generated_at": GEN}])
    return doc


EIGHT_K = {"headline": "ZQX 8-K: Entry into a material agreement (Item 1.01) filed 2026-10-27",
           "catalyst_type": "material_agreement", "severity": "high", "source": "sec_edgar", "at": "2026-10-27T13:00:00Z"}


def fns(impact, calls, spine):
    def note_fn(sym, name, item, doc):
        calls.append((sym, item["id"], (doc or {}).get("version")))
        return {"impact": impact, "which_breaker": "B1" if impact == "breaker" else None,
                "one_line": f"synthetic {impact}", "model": "claude-sonnet-5-5", "cost_usd": 0.01}

    def spine_fn(sym, item, note):
        spine.append({"silo": "cio", "kind": NN.SPINE_KIND, "symbol": sym, "impact": note["impact"]})
        return {"outcome": "written"}
    return {"note_fn": note_fn, "spine_fn": spine_fn, "classify_fn": lambda *a, **k: ({}, {})}


@pytest.mark.parametrize("impact,reason,mode", [("thesis", "news_thesis", "delta"), ("stop", "news_stop", "delta"),
                                                ("breaker", "news_breaker", "full")])
def test_cio_note_impact_routes_to_enqueue(tmp_path, cfg, impact, reason, mode):
    base = store.base_dir(tmp_path, cfg)
    seed(base, "ZQX")
    calls, spine = [], []
    res = NN.review_symbol(base, {"symbol": "ZQX", "scope": "holding"}, store.read_index(base)["items"]["ZQX"],
                           Src(cats={"ZQX": [EIGHT_K]}, bars={"ZQX": [{"price_date": "2026-10-27", "close": 91.0}]}),
                           cfg, now=NOW, apply=True, **fns(impact, calls, spine))
    assert res["decision"] == {"reason": reason, "mode": mode, "item": res["decision"]["item"]}
    assert len(calls) == 1 and calls[0][2] == "20261026T120000Z"  # read against the latest prospectus
    assert spine == [{"silo": "cio", "kind": "prospectus_news_note", "symbol": "ZQX", "impact": impact}]
    log = NN.read_log(base, "ZQX")
    assert log["price"]["move_pct"] == -9.0 and log["spend"][NOW.date().isoformat()] == 0.01


def test_no_impact_is_a_note_only_and_watch_rewrites_go_full(tmp_path, cfg):
    base = store.base_dir(tmp_path, cfg)
    seed(base, "ZQX")
    res = NN.review_symbol(base, {"symbol": "ZQX", "scope": "holding"}, store.read_index(base)["items"]["ZQX"],
                           Src(cats={"ZQX": [EIGHT_K]}), cfg, now=NOW, apply=True, **fns("none", [], []))
    assert res["decision"] is None and res["audit"][0]["reason"] == "cio_no_impact"
    seed(base, "WQY", scope="watch")
    res = NN.review_symbol(base, {"symbol": "WQY", "scope": "watch"}, store.read_index(base)["items"]["WQY"],
                           Src(cats={"WQY": [dict(EIGHT_K, headline="WQY 8-K: material agreement")]}), cfg, now=NOW,
                           apply=True, **fns("thesis", [], []))
    assert res["decision"]["mode"] == "full"  # Watch rewrites go through the batch, which writes full reports


def test_coalescing_one_news_rewrite_per_symbol_per_day_and_no_renote(tmp_path, cfg):
    base = store.base_dir(tmp_path, cfg)
    seed(base, "ZQX")
    calls = []
    entry = store.read_index(base)["items"]["ZQX"]
    first = NN.review_symbol(base, {"symbol": "ZQX", "scope": "holding"}, entry, Src(cats={"ZQX": [EIGHT_K]}), cfg,
                             now=NOW, apply=True, **fns("thesis", calls, []))
    assert first["decision"]["reason"] == "news_thesis"
    second_item = dict(EIGHT_K, headline="ZQX 8-K: Officer or director change (Item 5.02) filed 2026-10-27",
                       catalyst_type="executive_change", severity="medium", at="2026-10-27T15:00:00Z")
    later = NN.review_symbol(base, {"symbol": "ZQX", "scope": "holding"}, entry,
                             Src(cats={"ZQX": [EIGHT_K, second_item]}), cfg, now=NOW, apply=True,
                             **fns("thesis", calls, []))
    assert later["decision"] is None
    assert [a["reason"] for a in later["audit"] if a["title"].startswith("ZQX 8-K: Officer")] == ["coalesced"]
    assert len(calls) == 2  # the first item is never re-noted


def test_per_symbol_note_cap_defers(tmp_path, cfg):
    base = store.base_dir(tmp_path, cfg)
    seed(base, "ZQX")
    log = NN.read_log(base, "ZQX")
    log.update(report_version="20261026T120000Z", spend={NOW.date().isoformat(): 0.10})
    NN.write_log(base, "ZQX", log)
    calls = []
    res = NN.review_symbol(base, {"symbol": "ZQX", "scope": "holding"}, store.read_index(base)["items"]["ZQX"],
                           Src(cats={"ZQX": [EIGHT_K]}), cfg, now=NOW, apply=True, **fns("thesis", calls, []))
    assert calls == [] and res["decision"] is None and res["audit"][0]["reason"] == "note_cap"


def test_window_apply_enqueues_delta_and_records_audit(tmp_path, cfg):
    base = store.base_dir(tmp_path, cfg)
    seed(base, "ZQX")
    calls = []
    src = Src(cats={"ZQX": [EIGHT_K]},
              news={"ZQX": [{"title": "Zeqqa (LON:ZQX) wins a printer order", "published_at": "2026-10-27T09:00:00Z"}]})
    seen_rows = []

    def run_queue(base_, sources, cfg_, *, limit, holdings, manual, batch_enabled):
        seen_rows.extend(r for r in store.read_queue(base_)["items"] if r.get("state") in ("queued", None))
        return {"done": [], "failed": [], "queued": [], "cost_usd": 0.0}
    out = PW.run(Namespace(apply=True, now=NOW.isoformat(), window=""), cfg, tmp_path,
                 sources_factory=lambda r, ro: src, run_queue_fn=run_queue, news_fns=fns("thesis", calls, []))
    assert out["window"] == "post_close"
    row = next(r for r in seen_rows if r["symbol"] == "ZQX")
    assert row["reason"] == "news_thesis" and row["mode"] == "delta" and row.get("item")
    news = out["news"]
    assert news["counts"].get("collision") == 1 and news["rewrites"] == {"ZQX": "news_thesis"}
    assert news["enqueued"] == ["ZQX"]
    outbox = list((base / "delivery" / "outbox").glob("*.json"))
    assert outbox and json.loads(outbox[0].read_text())["news"]["counts"]["collision"] == 1


def test_window_dry_run_calls_no_model_and_writes_nothing(tmp_path, cfg):
    base = store.base_dir(tmp_path, cfg)
    seed(base, "ZQX")
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
    out = PW.run(Namespace(apply=False, now=NOW.isoformat(), window=""), cfg, tmp_path,
                 sources_factory=lambda r, ro: Src(cats={"ZQX": [EIGHT_K]}))
    assert out["mode"] == "dry_run" and out["news"]["counts"].get("accepted") == 1
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file()) == before


# ── 3. the strip + delivery text ──────────────────────────────────────────────────────────────────────────────
def test_since_report_api_shape(tmp_path, cfg):
    from scripts.lib import prospectus_api as API
    base = store.base_dir(tmp_path, cfg)
    seed(base, "ZQX")
    src = Src(cats={"ZQX": [EIGHT_K]}, bars={"ZQX": [{"price_date": "2026-10-27", "close": 110.0}]},
              news={"ZQX": [{"title": "Zeqqa (LON:ZQX) wins a printer order", "published_at": "2026-10-27T09:00:00Z"}]})
    NN.review_symbol(base, {"symbol": "ZQX", "scope": "holding"}, store.read_index(base)["items"]["ZQX"], src, cfg,
                     now=NOW, apply=True, **fns("watch", [], []))
    ctx = API.Ctx(principal=lambda: "", listener=lambda: None, csrf=lambda m, p: (True, ""),
                  allowed_logins=frozenset(), state_root=tmp_path)
    status, doc = API.handle("/api/v2/prospectus/ZQX", "GET", ctx=ctx)
    assert status == 200
    s = doc["since_report"]
    assert s["schema"] == "ProspectusSinceReport@v1" and s["written_at"] == GEN
    assert s["price"]["move_pct"] == 10.0 and s["hidden"] == {"collision": 1}
    assert len(s["items"]) == 1
    it = s["items"][0]
    assert it["material"] is True and it["badge"] == "material" and it["status"] == "CIO note: watch"
    assert it["note"]["impact"] == "watch" and set(it) >= {"id", "at", "title", "source", "url", "status"}
    assert s["next_window"]["id"] in ("pre_market", "post_close")
    # an older version is never annotated with what happened after the latest one
    status, old = API.handle("/api/v2/prospectus/ZQX", "GET", query={"version": "20261001T120000Z"}, ctx=ctx)
    assert "since_report" not in (old or {})


def test_since_report_is_cheap_and_empty_without_a_log(tmp_path, cfg):
    base = store.base_dir(tmp_path, cfg)
    doc = seed(base, "ZQX")
    s = NN.since_report(base, "ZQX", doc, cfg=cfg)
    assert s["items"] == [] and s["price"] is None and s["checked_at"] is None


def test_delivery_texts_carry_the_news_audit(tmp_path, cfg):
    from scripts.lib.prospectus import delivery
    record = {"run_key": "k", "window_id": "post_close", "window_label": "After the close", "local_date": "2026-10-27",
              "items": [], "failed": [], "news": {"counts": {"accepted": 1, "collision": 2},
                                                   "rewrites": {"ZQX": "news_thesis"},
                                                   "accepted": [{"symbol": "ZQX", "title": "ZQX 8-K", "verdict": "accepted",
                                                                 "reason": None, "status": "queued", "impact": "thesis"}],
                                                   "rejected": [{"symbol": "ZQX", "title": "Zeqqa (LON:ZQX)",
                                                                 "verdict": "rejected", "reason": "collision"}],
                                                   "rejected_total": 2}}
    mail = delivery.plan_email(record, cfg, tmp_path)
    assert "News triggers" in mail["body"] and "collision" in mail["body"] and "news_thesis" in mail["body"]
    tel = delivery.plan_telegram(record, cfg, delivery.read_ledger(tmp_path), tmp_path)
    assert tel["text"] and "ZQX" in tel["text"] and "thesis" in tel["text"]


# ── 4. report facts never carry a collision ───────────────────────────────────────────────────────────────────
def test_quality_gate_rejects_collision_facts(monkeypatch):
    monkeypatch.setattr(NG, "load_collisions", lambda root=None: COLL)
    packet = {"symbol": "ZQX", "name": "Zedquix Aerospace Fund", "facts": [
        {"id": "F1", "kind": "news", "label": "News — wire", "text": "Zeqqa (LON:ZQX) wins a printer order"},
        {"id": "F2", "kind": "news", "label": "News — wire", "text": "Zedquix Aerospace Fund adds a holding"}]}
    out = QG.check_news_collisions(packet, {})
    assert len(out) == 1 and out[0]["code"] == "news_symbol_collision" and out[0]["facts"] == ["F1"]
    assert out[0]["severity"] == QG.SOFT
    kept, dropped = NG.filter_facts([{"title": "Zeqqa (LON:ZQX) wins"}, {"title": "fine"}], "ZQX", "Zedquix",
                                    text_key="title", collisions=COLL)
    assert [r["title"] for r in kept] == ["fine"] and len(dropped) == 1


def test_processes_registered_anthropic_only_with_caps():
    reg = {p["id"]: p for p in json.loads((ROOT / "config/llm_process_registry.json").read_text())["processes"]}
    pol = json.loads((ROOT / "config/anthropic_credit_policy.json").read_text())
    assert reg["prospectus_news_classify"]["daily_cost_cap_usd"] == 0.25
    assert reg["prospectus_cio_news_note"]["daily_cost_cap_usd"] == 1.5
    for pid in ("prospectus_news_classify", "prospectus_cio_news_note"):
        assert reg[pid]["advisory_only"] is True and reg[pid]["fallback_allowed"] is False
        assert pid in pol["anthropic_only_processes"]  # never DeepSeek / another provider
    assert pol["models"][pol["process_tiers"]["prospectus_news_classify"]] == "claude-haiku-5-5"
    assert pol["models"][pol["process_tiers"]["prospectus_cio_news_note"]] == "claude-sonnet-5-5"
    news = load_config()["news"]
    assert news["per_symbol_note_usd_per_day"] == 0.10 and news["max_news_rewrites_per_day"] == 1
