"""Cheaper Watch prospectuses: per-scope generation, Message Batches API, gate before submit (operator 2026-10-26:
"implement this cost savings right now; we don't need it immediately").

Synthetic tickers only (public repo). The batch client, the writer and the Haiku read are stubs; no DB, no token store,
no network; every write goes to a temporary state root.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import batch, load_config, store  # noqa: E402
from scripts.lib.prospectus import generate as gen  # noqa: E402
from scripts.lib.prospectus import pipeline as pl  # noqa: E402
from scripts.lib.prospectus.domains import full_assemble  # noqa: E402
from test_prospectus_build_20261026 import NOW, FakeSources, model_reply, stub_generate  # noqa: E402
from test_prospectus_quality_gate_20261026 import SpikySources  # noqa: E402


@pytest.fixture()
def base(tmp_path):
    return store.base_dir(tmp_path, load_config())


def test_generation_config_per_scope_holdings_unchanged():
    g = gen.generation_config()
    h, w = gen.scope_settings("holding", g), gen.scope_settings("watch", g)
    assert h["effort"] == "high" and h["max_output_tokens"] == 16000 and h["batch"] is False
    assert w["effort"] == "medium" and w["max_output_tokens"] == 5000 and w["batch"] is True
    src = FakeSources()
    wb = full_assemble(src, "ZZCC", "watch", cfg=load_config(), now=NOW)
    hb = full_assemble(src, "ZZAA", "holding", cfg=load_config(), holding=src.holdings()["ZZAA"], now=NOW)
    assert gen.max_tokens_for(wb, load_config(), "full") == 5000 and gen.max_tokens_for(hb, load_config(), "full") == 16000
    assert "Aim for 50-110 words per section (a concise report" in gen.writer_prompt(wb, load_config(), mode="full", previous=None)
    assert "Aim for 120-260 words per section;" in gen.writer_prompt(hb, load_config(), mode="full", previous=None)
    # every section is still asked for
    assert "thesis_breakers (Thesis breakers)" in gen.writer_prompt(wb, load_config(), mode="full", previous=None)


def test_estimate_watch_is_batch_priced_and_shorter():
    pricing = {"claude-opus-5-5": {"input": "4", "output": "20", "cache_write_5m": "5"}}
    w = pl.estimate("x" * 36000, load_config(), premium=False, pricing=pricing, scope="watch")
    h = pl.estimate("x" * 36000, load_config(), premium=False, pricing=pricing, scope="holding")
    assert w["batch"] is True and w["effort"] == "medium" and w["output_tokens_est"] == 4000
    assert h["batch"] is False and h["output_tokens_est"] == 9000
    assert w["cost_usd_est"] == pytest.approx((10000 * 4 + 4000 * 20) / 1e6 * 0.5)
    assert w["cost_usd_est"] < h["cost_usd_est"] / 2


def test_batch_eligibility():
    assert batch.is_batch_row({"scope": "watch", "priority": 1000, "reason": "first_build"})
    assert not batch.is_batch_row({"scope": "holding", "priority": 100, "reason": "first_build"})
    assert not batch.is_batch_row({"scope": "watch", "priority": 1, "reason": "operator_refresh"})
    assert not batch.is_batch_row({"scope": "watch", "priority": 1000, "reason": "operator_cli"})


def _queue(base, syms, *, at=NOW):
    store.enqueue(base, [{"symbol": s, "scope": "watch", "priority": 1000, "reason": "first_build"} for s in syms], now=at)


def test_due_needs_size_or_age(base):
    _queue(base, ["ZZC1", "ZZC2"])
    assert batch.due(base, now=NOW) == []
    assert len(batch.due(base, now=NOW + timedelta(hours=7))) == 2
    _queue(base, [f"ZZD{i}" for i in range(9)])
    assert len(batch.due(base, now=NOW)) == 11


class Submit:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self, prompt, **kw):
        self.calls.append(dict(kw, prompt=prompt))
        if self.fail:
            raise RuntimeError(self.fail)
        return {"batch_id": f"msgbatch_fx{len(self.calls)}", "client_request_id": kw["client_request_id"],
                "reservation_id": 7, "model": "claude-opus-5-5", "hold_usd": "0.4"}


def test_run_queue_leaves_watch_for_batch_and_writes_holdings_and_operator_rows(base):
    src = FakeSources()
    store.write_universe(base, [{"symbol": "ZZAA", "scope": "holding", "premium": False},
                                {"symbol": "ZZCC", "scope": "watch", "premium": False}])
    store.enqueue(base, [{"symbol": "ZZAA", "scope": "holding", "priority": 100, "reason": "first_build"},
                         {"symbol": "ZZCC", "scope": "watch", "priority": 1000, "reason": "first_build"}], now=NOW)
    out = pl.run_queue(base, src, load_config(), limit=5, generate_fn=stub_generate(src), now_fn=lambda: NOW,
                       log=lambda m: None)
    assert out["done"] == ["ZZAA"]
    assert [r["symbol"] for r in store.read_queue(base)["items"]] == ["ZZCC"]
    store.enqueue(base, [{"symbol": "ZZCC", "scope": "watch", "priority": 1, "reason": "operator_refresh"}], now=NOW)
    out = pl.run_queue(base, src, load_config(), limit=5, generate_fn=stub_generate(src), now_fn=lambda: NOW,
                       log=lambda m: None)
    assert out["done"] == ["ZZCC"]  # "Rewrite now" stays synchronous


def test_submit_gate_first_then_batch_with_medium_effort(base):
    src = SpikySources()  # ZZCC has a listing-day first bar → blocked before any spend
    _queue(base, ["ZZCC", "ZZBB"])
    sub, blocked, plans = Submit(), [], []
    inner = stub_generate(src)

    def gen_fn(prompt, **kw):
        plans.append(kw["process_id"])
        return inner(prompt, **kw)
    out = batch.submit_due(base, src, load_config(), now=NOW, submit_fn=sub, generate_fn=gen_fn, ai_fn=None, force=True,
                           log=lambda m: None, on_blocked=lambda s, e: blocked.append(s))
    assert out["blocked_data"] == ["ZZCC"] and blocked == ["ZZCC"] and out["submitted"] == ["ZZBB"]
    assert len(sub.calls) == 1
    call = sub.calls[0]
    assert call["effort"] == "medium" and call["max_tokens"] == 5000 and call["credit_tier"] == "long_form"
    assert call["process_id"] == "prospectus_writer" and "50-110 words" in call["prompt"]
    q = {r["symbol"]: r for r in store.read_queue(base)["items"]}
    assert q["ZZBB"]["state"] == "batch_pending" and q["ZZBB"]["attempts"] == 1
    st = batch.read_state(base)["items"]["ZZBB"]
    assert st["batch_id"] == "msgbatch_fx1" and st["state"] == "pending"
    assert (base / batch.PENDING_DIR / "ZZBB.json").exists()
    # in flight: a second submit pass does not resubmit
    batch.submit_due(base, src, load_config(), now=NOW, submit_fn=sub, generate_fn=gen_fn, ai_fn=None, force=True,
                     log=lambda m: None, on_blocked=lambda s, e: None)
    assert len(sub.calls) == 1


def test_submit_stops_on_credit_unavailable(base):
    src = FakeSources()
    _queue(base, ["ZZBB", "ZZCC"])
    sub = Submit(fail="ANTHROPIC_CREDIT_UNAVAILABLE: batch submit; queue and retry")
    out = batch.submit_due(base, src, load_config(), now=NOW, submit_fn=sub, generate_fn=stub_generate(src), ai_fn=None,
                           force=True, log=lambda m: None)
    assert out["stopped_reason"] and len(sub.calls) == 1 and out["submitted"] == []
    assert all(r["state"] == "queued" for r in store.read_queue(base)["items"])


def _submitted(base, src, sym="ZZBB"):
    _queue(base, [sym])
    batch.submit_due(base, src, load_config(), now=NOW, submit_fn=Submit(), generate_fn=stub_generate(src), ai_fn=None,
                     force=True, log=lambda m: None)


def test_collect_writes_report_once_and_is_idempotent(base):
    src = FakeSources()
    _submitted(base, src)
    seen = []
    bundle = full_assemble(src, "ZZBB", "watch", cfg=load_config(), now=NOW)

    def collect_fn(entry):
        seen.append(entry["batch_id"])
        if len(seen) == 1:
            return {"status": "PENDING"}
        return {"status": "SUCCEEDED", "text": model_reply(bundle),
                "prov": {"returned_model": "claude-opus-5-5", "provider": "anthropic", "estimated_cost_usd": 0.07,
                         "usage": {"prompt_tokens": 9000, "completion_tokens": 3500}, "batch": True}}
    first = batch.collect(base, load_config(), now=NOW + timedelta(hours=1), collect_fn=collect_fn, log=lambda m: None)
    assert first["pending"] == ["ZZBB"] and first["written"] == []
    second = batch.collect(base, load_config(), now=NOW + timedelta(hours=2), collect_fn=collect_fn, log=lambda m: None)
    assert second["written"] == ["ZZBB"]
    doc = store.read_prospectus(base, "ZZBB")
    assert doc["batch"]["batch_id"] == "msgbatch_fx1" and doc["gate"]["status"] in ("pass", "soft_fail")
    assert store.read_index(base)["items"]["ZZBB"]["status"] in ("ready", "partial")
    assert store.read_queue(base)["items"] == []
    third = batch.collect(base, load_config(), now=NOW + timedelta(hours=3), collect_fn=collect_fn, log=lambda m: None)
    assert third["written"] == [] and len(seen) == 2  # closed entries are never collected again


def test_errored_or_expired_results_requeue_then_fail(base):
    src = FakeSources()
    _submitted(base, src)
    out = batch.collect(base, load_config(), now=NOW + timedelta(hours=1),
                        collect_fn=lambda e: {"status": "FAILED", "error": "BATCH_RESULT_UNAVAILABLE"}, log=lambda m: None)
    assert out["requeued"] == ["ZZBB"]
    row = store.read_queue(base)["items"][0]
    assert row["state"] == "queued" and "BATCH_RESULT_UNAVAILABLE" in row["last_error"]
    for i in range(2):  # attempts 2 and 3: the third failure is final
        batch.submit_due(base, src, load_config(), now=NOW, submit_fn=Submit(), generate_fn=stub_generate(src),
                         ai_fn=None, force=True, log=lambda m: None)
        out = batch.collect(base, load_config(), now=NOW + timedelta(hours=40),
                            collect_fn=lambda e: {"status": "PENDING"}, log=lambda m: None)
    assert out["failed"] == ["ZZBB"]
    assert store.read_queue(base)["items"][0]["state"] == "failed"
    assert store.read_index(base)["items"]["ZZBB"]["status"] == "failed"


def test_transport_batch_accepts_long_form_tier_and_effort(tmp_path):
    from scripts.lib import anthropic_credit as credit, anthropic_transport as transport
    p = transport.load_policy()
    assert "long_form" in p["batch_tiers"] and p["models"]["long_form"] == "claude-opus-5-5"
    book = credit.CreditBook(tmp_path, p)
    sent = []

    def request(method, path, payload, **kw):
        sent.append((method, path, payload))
        if path.endswith("count_tokens"):
            return 200, {"input_tokens": 10}, {}
        return 200, {"id": "msgbatch_fixture", "processing_status": "in_progress"}, {}
    t = transport.AnthropicTransport(book=book, env={"ANTHROPIC_API_KEY": "synthetic"}, request=request,
                                     now=lambda: datetime(2026, 10, 26, 16, tzinfo=timezone.utc),
                                     reserve_process=lambda *a: None, record_usage=lambda *a: True,
                                     record_attempt=lambda *a: True, settle_process=lambda *a: None)
    args = dict(client_request_id="fx-watch", process_id="prospectus_writer", caller_allows_async=True, max_tokens=50,
                max_input_tokens=1000, process_cap=Decimal(5), credit_tier="long_form")
    with pytest.raises(transport.AnthropicError, match="BATCH_EFFORT_UNSUPPORTED"):
        t.submit_batch([{"role": "user", "content": "synthetic"}], "claude-opus-5-5", effort="max", **args)
    out = t.submit_batch([{"role": "user", "content": "synthetic"}], "claude-opus-5-5", effort="medium", **args)
    assert out["status"] == "PENDING"
    params = sent[-1][2]["requests"][0]["params"]
    assert params["output_config"]["effort"] == "medium" and params["model"] == "claude-opus-5-5"
    with pytest.raises(transport.AnthropicError, match="BATCH_TIER_UNSUPPORTED"):
        t.submit_batch([{"role": "user", "content": "x"}], "claude-fable-5-1", **dict(args, credit_tier="premium",
                                                                                    client_request_id="fx-2"))


def test_cli_dry_run_reports_watch_batch_estimate(tmp_path, monkeypatch, capsys):
    import prospectus_build as cli

    class Src(FakeSources):
        pass
    monkeypatch.setattr(cli, "HouseSources", lambda root, read_only=True: Src())
    monkeypatch.setattr(cli, "state_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "_pricing", lambda: {"claude-opus-5-5": {"input": "4", "output": "20", "cache_write_5m": "5"}})
    assert cli.main(["--symbols", "ZZCC", "--limit", "1"]) == 0
    out = json.loads(capsys.readouterr().out)
    row = out["shown"][0]
    assert row["scope"] == "watch" and row["batch"] is True and row["effort"] == "medium" and out["model_calls"] == 0
