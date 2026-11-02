"""Anthropic hosted web_search as an Ask-the-CIO source (2026-11-01).

Hermetic: every provider call is an injected transport stub. The four controls asserted here are the
ones that keep the paid source from becoming an ungoverned egress or a lane-wide outage:

1. only ``cio_ask_web_search`` may send a ``tools`` payload (transport allowlist);
2. the provider's ``web_search_tool_result`` blocks are normalised into cited results;
3. every transport/bridge failure is a typed value, never an exception into the Ask collector;
4. a failed paid source records ``no_data`` for that subject — never ``refused``, which would fail the
   whole source check and open the Ask lane's n8n breaker.

ANCHOR: CIO_ASK_ANTHROPIC_WEB_SEARCH_20261101
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import anthropic_web_search as ws  # noqa: E402
from scripts.lib import cio_ask_research as car  # noqa: E402

NOW = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------------------------- fixtures
def _results_document(model: str = "claude-sonnet-5-5") -> dict:
    """The provider message body the transport receives (``content`` = raw provider blocks)."""
    return {
        "id": "msg_fixture",
        "type": "message",
        "role": "assistant",
        "model": model,
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 10},
        "content": [
            {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "NVDA"}},
            {
                "type": "web_search_tool_result",
                "tool_use_id": "srvtoolu_1",
                "content": [
                    {
                        "type": "web_search_result",
                        "title": "Nvidia data-centre revenue",
                        "url": "https://example.invalid/nvda",
                        "encrypted_content": "opaque",
                        "page_age": "2026-10-30T00:00:00Z",
                    },
                    {
                        "type": "web_search_result",
                        "title": "Second result",
                        "url": "https://example.invalid/second",
                        "encrypted_content": "opaque",
                        "page_age": "2 days",
                    },
                ],
            },
            {"type": "text", "text": "Summary of what the search found."},
        ],
    }


def _bridge_document() -> dict:
    """What the governed bridge returns to a caller: the answer plus the raw provider blocks."""
    body = _results_document()
    return {
        "id": body["id"],
        "model": body["model"],
        "choices": [{"message": {"role": "assistant", "content": "Summary of what the search found."},
                     "finish_reason": "end_turn"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        "_tradeai": {"provider": "anthropic", "content_blocks": body["content"]},
    }


# ---------------------------------------------------------------------------------------- normalisation
def test_results_from_blocks_reads_only_web_search_results():
    results, error = ws.results_from_blocks(_results_document()["content"], 5)
    assert error is None
    assert [r["url"] for r in results] == ["https://example.invalid/nvda", "https://example.invalid/second"]
    assert results[0]["title"] == "Nvidia data-centre revenue"
    # The API exposes encrypted_content, never readable page text; the source must not pretend otherwise.
    assert results[0]["content"] == "opaque"


def test_results_from_blocks_honours_count():
    results, error = ws.results_from_blocks(_results_document()["content"], 1)
    assert error is None and len(results) == 1


def test_results_from_blocks_reports_a_provider_error_block():
    blocks = [{"type": "web_search_tool_result", "tool_use_id": "x", "content": {"error_code": "max_uses_exceeded"}}]
    results, error = ws.results_from_blocks(blocks, 5)
    assert results == [] and error == "max_uses_exceeded"


def test_results_from_blocks_ignores_non_tool_blocks():
    results, error = ws.results_from_blocks([{"type": "text", "text": "hi"}, None, "nope"], 5)
    assert (results, error) == ([], None)


# --------------------------------------------------------------------------------------------- search()
def test_search_normalises_a_bridge_success():
    sent = {}

    def transport(url, body, timeout_s):
        sent.update({"url": url, "body": body, "timeout_s": timeout_s})
        return _bridge_document()

    out = ws.search("NVDA data centre demand", count=5, transport=transport)
    assert out["ok"] is True and out["provider"] == "anthropic" and out["error"] is None
    assert len(out["results"]) == 2
    # The governed shape: one user message plus the server tool, under the registered caller.
    assert sent["body"]["tools"] == [ws.TOOL]
    assert sent["body"]["tools"][0]["type"] == "web_search_20260209"
    assert sent["body"]["messages"][0]["role"] == "user"


def test_search_reads_content_blocks_through_the_tradeai_envelope():
    def transport(url, body, timeout_s):
        return {"_tradeai": {"content_blocks": _results_document()["content"]}}

    out = ws.search("q", transport=transport)
    assert out["ok"] is True and len(out["results"]) == 2


def test_search_bridge_refusal_is_typed_not_raised():
    out = ws.search("q", transport=lambda *a: {"error": {"code": "PROCESS_NOT_REGISTERED"}})
    assert out["ok"] is False and out["error"] == "PROCESS_NOT_REGISTERED" and out["results"] == []


def test_search_transport_failure_is_typed_not_raised():
    def boom(url, body, timeout_s):
        raise URLError("bridge down")

    out = ws.search("q", transport=boom)
    assert out["ok"] is False and out["error"] == "URLError" and out["results"] == []


def test_search_with_no_results_is_not_ok():
    out = ws.search("q", transport=lambda *a: {"content": [{"type": "text", "text": "nothing"}]})
    assert out["ok"] is False and out["results"] == []


# ------------------------------------------------------------------------------------- source registry
def test_web_anthropic_source_is_off_by_default(monkeypatch):
    monkeypatch.delenv(car.ANTHROPIC_WEB_SEARCH_ENV, raising=False)
    assert "web.anthropic" not in {s.name for s in car.default_sources()}


def test_web_anthropic_source_registers_when_the_operator_turns_it_on(monkeypatch):
    monkeypatch.setenv(car.ANTHROPIC_WEB_SEARCH_ENV, "1")
    specs = {s.name: s for s in car.default_sources()}
    assert "web.anthropic" in specs
    spec = specs["web.anthropic"]
    # Works on a private entity too (no symbol needed) and has room for one hosted search round trip.
    assert spec.needs_symbol is False and spec.timeout_s >= 30.0


def _ws_module():
    """The exact module object the source imports (repo names resolve both ways)."""
    return car._imp("lib.anthropic_web_search", "scripts.lib.anthropic_web_search")


def _entity():
    return car.Entity(label="NVDA", kind="listed", symbol="NVDA", security_guid="sec-nvda-0001",
                      identity_status="RESOLVED")


def test_source_emits_cited_facts(monkeypatch):
    monkeypatch.setattr(_ws_module(), "search", lambda q, count=5: {"ok": True, "provider": "anthropic", "error": None,
                                                          "results": [{"title": "A", "url": "https://x.invalid/a",
                                                                       "content": "", "published": None}]})
    facts = car._src_anthropic_search(_entity(), car.ResearchContext(question="outlook", now=NOW))
    assert len(facts) == 1
    fact = facts[0]
    assert fact.citation["url"] == "https://x.invalid/a"
    assert fact.citation["provider"] == "anthropic"
    assert fact.as_of  # every fact carries a clock; unknown page_age falls back to retrieved_at
    assert facts.outcome == {"ok": True, "provider": "anthropic", "code_execution_blocks": 0}


def test_source_is_dry_run_silent(monkeypatch):
    def forbidden(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("a dry run must not spend a paid call")

    monkeypatch.setattr(_ws_module(), "search", forbidden)
    facts = car._src_anthropic_search(_entity(), car.ResearchContext(question="q", now=NOW, dry_run=True))
    assert list(facts) == [] and facts.outcome["reason"] == "DRY_RUN"


def test_source_failure_degrades_to_no_data_not_refused(monkeypatch):
    """A paid enhancement must never fail the Ask check: the run row says no_data and records why."""
    monkeypatch.setattr(_ws_module(), "search", lambda q, count=5: {"ok": False, "provider": "anthropic", "results": [],
                                                          "error": "CREDIT_EXHAUSTED"})
    ent = _entity()
    src = car.SourceSpec("web.anthropic", "web", car._src_anthropic_search, 60.0, needs_symbol=False)
    gathered = car.gather_facts([ent], [src], car.ResearchContext(question="q", now=NOW))
    row = next(r for r in gathered["runs"] if r["source"] == "web.anthropic")
    assert row["status"] == "no_data"
    assert row["reason"] == "CREDIT_EXHAUSTED"
    assert any(g["source"] == "web.anthropic" and g["reason"] == "CREDIT_EXHAUSTED" for g in gathered["gaps"])


# ------------------------------------------------------------------------------ transport tool gate
def _transport(tmp_path, provider_document):
    """A real transport over the real credit policy, with the provider call replaced by a fixture."""
    from scripts.lib.anthropic_credit import CreditBook
    from scripts.lib.anthropic_transport import AnthropicTransport, load_policy

    policy = load_policy()
    posts: list[dict] = []

    def request(method, path, payload, **kwargs):
        if path.endswith("count_tokens"):
            return 200, {"input_tokens": 100}, {}
        posts.append(payload)
        return 200, provider_document, {}

    client = AnthropicTransport(
        book=CreditBook(tmp_path, policy),
        env={"ANTHROPIC_API_KEY": "synthetic-fixture"},
        request=request,
        now=lambda: NOW,
        sleep=lambda _s: None,
        record_usage=lambda *a, **k: True,
        record_attempt=lambda *a, **k: True,
        reserve_process=lambda *a, **k: None,
        settle_process=lambda *a, **k: None,
    )
    return client, posts, policy


def _generate(client, process_id, tools):
    return client.generate(
        [{"role": "user", "content": "search the web"}],
        client.policy["models"]["mid"],
        max_tokens=256,
        client_request_id="fixture-" + process_id,
        process_id=process_id,
        credit_tier="mid",
        tools=tools,
    )


def test_tools_are_refused_for_every_other_process(tmp_path):
    from scripts.lib.anthropic_transport import AnthropicError

    client, posts, _ = _transport(tmp_path, _results_document())
    with pytest.raises(AnthropicError) as excinfo:
        _generate(client, "cio_ask_reanswer", [ws.TOOL])
    assert excinfo.value.code == "TOOLS_UNSUPPORTED"
    assert posts == []  # refused before any provider call, not after it was billed


def test_tools_reach_the_provider_for_the_registered_search_process(tmp_path):
    client, posts, policy = _transport(tmp_path, _results_document())
    assert policy["tools_processes"] == ["cio_ask_web_search"]
    answer = _generate(client, "cio_ask_web_search", [ws.TOOL])
    assert posts and posts[-1]["tools"][0]["type"] == "web_search_20260209"
    # The server-tool result blocks survive into the caller's envelope; without them the source sees nothing.
    blocks = answer["_tradeai"]["content_blocks"]
    assert any(b.get("type") == "web_search_tool_result" for b in blocks)


def test_a_refusal_without_the_degraded_marker_still_fails_the_check(monkeypatch):
    """The degrade path is opt-in per source; an ordinary refused source keeps its existing semantics."""

    def refused(ent, ctx):
        return car.SourceFacts(outcome={"ok": False, "reason": "SOURCE_REFUSED"})

    src = car.SourceSpec("web.other", "web", refused, 5.0, needs_symbol=False)
    gathered = car.gather_facts([_entity()], [src], car.ResearchContext(question="q", now=NOW))
    assert next(r for r in gathered["runs"] if r["source"] == "web.other")["status"] == "refused"


# ------------------------------------------------------------- dynamic filtering (provider-side code)
def test_code_execution_blocks_counts_only_sandbox_results():
    """web_search_20260209 answers through dynamic filtering: Claude writes code in Anthropic's sandbox to
    call web_search and filter results. Those blocks are counted, never consumed."""
    blocks = [
        {"type": "server_tool_use", "id": "c1", "name": "code_execution", "input": {"code": "r = await web_search(...)"}},
        {"type": "server_tool_use", "id": "w1", "name": "web_search", "input": {"query": "x"}},
        {"type": "web_search_tool_result", "tool_use_id": "w1", "content": [
            {"type": "web_search_result", "title": "T", "url": "https://x.invalid", "encrypted_content": "e"}]},
        {"type": "code_execution_tool_result", "tool_use_id": "c1", "content": {"type": "code_execution_result"}},
        {"type": "code_execution_tool_result", "tool_use_id": "c1", "content": {"type": "code_execution_result"}},
    ]
    assert ws.code_execution_blocks(blocks) == 2
    results, error = ws.results_from_blocks(blocks, 5)
    assert error is None and [r["url"] for r in results] == ["https://x.invalid"]


def test_search_reports_the_sandbox_count():
    def transport(url, body, timeout_s):
        return {"_tradeai": {"content_blocks": [
            {"type": "code_execution_tool_result", "tool_use_id": "c1", "content": {}},
            {"type": "web_search_tool_result", "tool_use_id": "w1", "content": [
                {"type": "web_search_result", "title": "T", "url": "https://x.invalid", "encrypted_content": "e"}]},
        ]}}

    out = ws.search("q", transport=transport)
    assert out["ok"] is True and out["code_execution_blocks"] == 1


def test_source_carries_the_sandbox_count_into_its_outcome(monkeypatch):
    monkeypatch.setattr(_ws_module(), "search", lambda q, count=5: {
        "ok": True, "provider": "anthropic", "error": None, "code_execution_blocks": 3,
        "results": [{"title": "A", "url": "https://x.invalid/a", "content": "", "published": None}]})
    facts = car._src_anthropic_search(_entity(), car.ResearchContext(question="q", now=NOW))
    assert facts.outcome["code_execution_blocks"] == 3
