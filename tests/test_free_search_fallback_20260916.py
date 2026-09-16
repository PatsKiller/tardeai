"""Free search as the answer to a CALLER_DAILY_CAP refusal (P1).

Measured 2026-09-16 on the live budget ledger: 129 denial receipts, every one
``reason=CALLER_DAILY_CAP``, every one ``spilled_to: null`` — refused, and then
asked of nobody, while a self-hosted provider with a 10,000/day allowance idled.

These tests pin the four things P1 changes:
  1. free_search meters every request it makes and refunds one it never made;
  2. a free provider is not rationed with a cap sized for money;
  3. the producer rescues ONLY a CALLER_DAILY_CAP refusal, only behind the flag,
     and amends the receipt so the question is no longer recorded as lost;
  4. the monitor reports refusals that went nowhere.

Fixtures only. No network, no paid call: the router refuses on budget before it
would ever reach a transport, and the free transport is injected.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import free_search as fs
from scripts.lib import search_budget as sb
from scripts.lib.governed_research_producer import FEATURE_FLAG, produce_research


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    (tmp_path / "data" / "runtime").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _hits(n: int = 2) -> list[dict]:
    return [
        {
            "title": f"Headline {i}",
            "snippet": f"Body text {i}",
            "url": f"https://example.com/{i}",
            "domain": "example.com",
            "engine": "searxng",
        }
        for i in range(n)
    ]


def _transport(by_category: dict[str, list[dict]] | None = None,
               *, raises: Exception | None = None,
               calls: list[str] | None = None):
    """Mimics ``searxng_client.searx_search``: returns rows, never raises for a
    transport error — it reports one error row instead."""

    def _t(query, *, categories, limit, timeout):
        if calls is not None:
            calls.append(categories)
        if raises is not None:
            raise raises
        table = by_category if by_category is not None else {"general": _hits()}
        return list(table.get(categories, []))[:limit]

    return _t


def _daily_used(root: Path, provider: str = fs.PROVIDER) -> int:
    return int(sb.status(provider, root=root)["daily_used"])


# ---------------------------------------------------------------- free_search


def test_a_free_hit_costs_one_ledger_unit_and_carries_a_readable_body(tmp_root: Path):
    resp = fs.search("visa catalyst", caller="t", root=tmp_root,
                     transport=_transport())
    assert resp.ok and resp.provider == "searxng" and resp.units == 1
    assert _daily_used(tmp_root) == 1
    # SearXNG spells the body "snippet"; every paid-search consumer reads
    # "description". Without the mapping a free answer is well-formed and empty.
    assert resp.results[0]["description"] == "Body text 0"
    assert resp.results[0]["url"] == "https://example.com/0"


def test_a_request_that_never_happened_is_refunded(tmp_root: Path):
    resp = fs.search("visa", caller="t", root=tmp_root,
                     transport=_transport(raises=RuntimeError("connection refused")))
    assert not resp.ok and resp.reason.startswith("PROVIDER_ERROR")
    assert resp.units == 0
    assert _daily_used(tmp_root) == 0, "a call that never reached the provider must not be counted"


def test_an_error_row_is_a_failure_not_an_answer(tmp_root: Path):
    err = _transport(by_category={"general": [{"error": "URLError:refused", "engine": "searxng"}]})
    resp = fs.search("visa", caller="t", root=tmp_root, transport=err)
    assert not resp.ok
    assert _daily_used(tmp_root) == 0


def test_news_falls_back_to_general_and_each_request_pays_its_own_unit(tmp_root: Path):
    calls: list[str] = []
    tx = _transport(by_category={"news": [], "general": _hits(1)}, calls=calls)
    resp = fs.search("visa", caller="t", kind="news", root=tmp_root, transport=tx)
    assert resp.ok and calls == ["news", "general"]
    # The paid path's known defect is web+news billing twice against ONE reserved
    # unit. Two requests here are two units; the ledger matches reality.
    assert resp.units == 2 and _daily_used(tmp_root) == 2


def test_a_refused_budget_never_reaches_the_transport(tmp_root: Path):
    calls: list[str] = []
    for _ in range(sb.caller_daily_cap("t", fs.PROVIDER)):
        sb.try_consume(fs.PROVIDER, caller="t", root=tmp_root)
    resp = fs.search("visa", caller="t", root=tmp_root, transport=_transport(calls=calls))
    assert not resp.ok and "BUDGET_REFUSED" in resp.reason
    assert calls == []


def test_only_a_caller_cap_refusal_is_answered_here():
    assert fs.applies_to("BUDGET_REFUSED:CALLER_DAILY_CAP")
    # These already spill through the registry chain; answering them here would
    # duplicate the spill and double-count the question.
    assert not fs.applies_to("BUDGET_REFUSED:DAILY_EXHAUSTED")
    assert not fs.applies_to("BUDGET_REFUSED:MONTHLY_EXHAUSTED")
    assert not fs.applies_to("PROVIDER_ERROR:HTTP 429")


# -------------------------------------------------------------- caller caps


def test_a_free_provider_is_not_rationed_with_a_cap_sized_for_money():
    assert sb.caller_daily_cap("default", "searxng") == sb.DEFAULT_LIMITS["searxng"]["daily"]
    # The paid caps are untouched, including when the provider is named.
    assert sb.caller_daily_cap("topic_ingestion") == 5
    assert sb.caller_daily_cap("topic_ingestion", "brave") == 5
    assert sb.caller_daily_cap("never_seen_before") == sb.CALLER_DAILY_CAPS["default"]


# ------------------------------------------------------------- mark_spilled


def test_mark_spilled_records_where_the_question_actually_went(tmp_root: Path):
    row = sb.write_denial_receipt("brave", "CALLER_DAILY_CAP", spilled_to=None,
                                  caller="producer", root=tmp_root)
    assert row and row["spilled_to"] is None
    assert sb.mark_spilled(row, "searxng", root=tmp_root) is True
    after = sb.denial_receipts(root=tmp_root)
    assert after[-1]["spilled_to"] == "searxng"
    assert after[-1]["detail"]["spilled_after_refusal"] is True


def test_mark_spilled_never_overwrites_an_answer_and_never_invents_a_row(tmp_root: Path):
    row = sb.write_denial_receipt("brave", "DAILY_EXHAUSTED", spilled_to="searxng",
                                  caller="producer", root=tmp_root)
    assert sb.mark_spilled(row, "tavily", root=tmp_root) is False
    assert sb.denial_receipts(root=tmp_root)[-1]["spilled_to"] == "searxng"
    assert sb.mark_spilled({"provider": "brave", "reason": "NOPE", "ts": "x",
                            "caller": "c", "kind": "web", "schema": "s"},
                           "searxng", root=tmp_root) is False


# ------------------------------------------------------------------ producer


def _env(tmp_path: Path, *, free: str = "1") -> dict:
    return {
        FEATURE_FLAG: "1",
        "TRADEAI_WAKE_RESEARCH_OBJECTS_PATH": str(tmp_path / "feed" / "research_objects.jsonl"),
        "GOVERNED_RESEARCH_PRODUCER_HEALTH_PATH": str(tmp_path / "health.json"),
        "TRADEAI_SOURCE_SHA": "abc123",
        fs.FALLBACK_FLAG: free,
    }


def _exhaust_the_producers_paid_slice(root: Path) -> None:
    caller = "governed_research_producer"
    for _ in range(sb.caller_daily_cap(caller, "brave")):
        sb.try_consume("brave", caller=caller, root=root)


def _targets():
    return [{"symbol": "V", "subject_guid": "sg-v", "query": "Visa stock catalyst news"}]


def test_a_caller_cap_refusal_is_answered_free_and_no_longer_counts_as_lost(tmp_root: Path):
    _exhaust_the_producers_paid_slice(tmp_root)
    env = _env(tmp_root)
    res = produce_research(targets=_targets(), env=env, root=tmp_root,
                           free_transport=_transport())

    # ONE rescued question, and the producer builds one research object per hit
    # exactly as it already does for a multi-result Brave answer — so two hits
    # are two feed rows, and one free ledger unit, not two.
    assert res.free_answered == 1 and res.produced == 2 and res.ok
    assert res.budget_denied == 0 and res.failed == 0

    rows = [json.loads(l) for l in
            Path(env["TRADEAI_WAKE_RESEARCH_OBJECTS_PATH"]).read_text().splitlines() if l.strip()]
    assert len(rows) == 2
    # Provenance must not claim the paid router for a free answer.
    assert "governed_free_search" in json.dumps(rows[0])

    # The receipt written at the moment of refusal now names the lane that
    # answered, so the never-asked-anywhere monitor cannot count it as lost.
    receipts = [r for r in sb.denial_receipts(root=tmp_root) if r["reason"] == "CALLER_DAILY_CAP"]
    assert receipts and receipts[-1]["spilled_to"] == "searxng"
    assert _daily_used(tmp_root) == 1


def test_with_the_flag_off_nothing_free_is_called_and_the_refusal_stands(tmp_root: Path):
    _exhaust_the_producers_paid_slice(tmp_root)
    calls: list[str] = []
    env = _env(tmp_root, free="0")
    res = produce_research(targets=_targets(), env=env, root=tmp_root,
                           free_transport=_transport(calls=calls))

    assert calls == [] and res.free_answered == 0
    assert res.produced == 0 and res.budget_denied == 1 and not res.ok
    assert _daily_used(tmp_root) == 0
    receipts = [r for r in sb.denial_receipts(root=tmp_root) if r["reason"] == "CALLER_DAILY_CAP"]
    assert receipts and receipts[-1]["spilled_to"] is None


# -------------------------------------------------------- gap attribution


def test_the_gap_receipt_names_the_provider_that_actually_answered(tmp_path: Path, monkeypatch):
    """RouterResponse carries no ``spilled_to`` — only the receipt does.

    The old reader was ``getattr(resp, "spilled_to", None)``, which is None on
    EVERY response, so a spilled answer was filed as brave and the gap receipts
    disagreed with the budget ledger about who answered.
    """
    from scripts.lib import brave_router as br
    from scripts.lib import gap_resolver as gr
    from scripts.lib import retired_providers as rp

    monkeypatch.setattr(rp, "is_retired", lambda p: False)
    monkeypatch.setattr(br, "router_enabled", lambda: True)

    def _answers(provider: str):
        def _search(*a, **kw):
            return br.RouterResponse(ok=True, provider=provider,
                                     results=[{"title": "t", "url": "https://example.com/1"}])
        return _search

    gap = gr.DataGap(domain="analyst_view", subject="WMT",
                     question="analyst view for WMT", why="no_coverage",
                     requester="operator:1")
    ctx = gr.Context(now=lambda: datetime(2026, 9, 16, tzinfo=timezone.utc),
                     receipts_path=tmp_path / "receipts.jsonl", live=True)

    monkeypatch.setattr(br, "search", _answers("searxng"))
    spilled = gr._v_governed_search(gap, {}, ctx)
    assert spilled.provider == "searxng"
    assert spilled.evidence["search_provider"] == "searxng"

    monkeypatch.setattr(br, "search", _answers("brave"))
    assert gr._v_governed_search(gap, {}, ctx).provider == "brave"


# ------------------------------------------------------------------- monitor


def test_the_monitor_reports_refusals_that_went_nowhere():
    from scripts.check_gap_resolution import REFUSED_THRESHOLD, refused_nowhere

    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    day = "2026-09-16T09:00:00+00:00"
    rows = [{"ts": day, "caller": "producer", "reason": "CALLER_DAILY_CAP", "spilled_to": None}
            for _ in range(REFUSED_THRESHOLD)]
    rows.append({"ts": day, "caller": "producer", "reason": "DAILY_EXHAUSTED", "spilled_to": "searxng"})
    rows.append({"ts": "2026-09-15T09:00:00+00:00", "caller": "producer",
                 "reason": "CALLER_DAILY_CAP", "spilled_to": None})

    found = refused_nowhere(rows, now=now)
    assert found == [{"caller": "producer", "reason": "CALLER_DAILY_CAP",
                      "refused_today": REFUSED_THRESHOLD}]
    # An answered refusal is governance working, not a finding.
    assert refused_nowhere(rows[REFUSED_THRESHOLD:], now=now) == []
