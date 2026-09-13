"""Phase 5 — a Brave denial spills to the registry's backup chain, with a receipt.

Measured 2026-09-13: 38 DAILY_EXHAUSTED denials (22 on 09-11), every one lost,
while the self-hosted SearXNG (10,000/day in the same registry) sat idle. These
tests are offline: the Brave transport and the SearXNG hop are injected, the
ledger lives in tmp_path, and BRAVE_ROUTER_LIVE is never set — no real call.

Negative controls: the pre-fix behaviour (resolver disabled), an explicit
``no_spill=True``, and a reason the registry does NOT list in ``spill_on``.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import brave_router as br  # noqa: E402
from scripts.lib import search_budget as sb  # noqa: E402
from scripts.lib import data_source_authority as dsa  # noqa: E402


class FixedClock:
    def __init__(self, start: datetime):
        self._t = start

    def __call__(self) -> datetime:
        return self._t

    def advance(self, **kw) -> None:
        self._t = self._t + timedelta(**kw)


T0 = datetime(2026, 9, 13, 14, 0, tzinfo=timezone.utc)


def _brave_ok(url: str, hdrs: dict):
    return (
        {"web": {"results": [{"title": "brave hit", "url": "https://example.org/b", "description": "", "age": "1d"}]},
         "results": [{"title": "brave hit", "url": "https://example.org/b", "description": "", "age": "1d",
                      "meta_url": {"hostname": "example.org"}}]},
        {"x-ratelimit-limit": "50, 0", "x-ratelimit-remaining": "49, 0",
         "x-ratelimit-reset": "1, 1000", "x-ratelimit-policy": "50;w=1, 0;w=2592000"},
    )


class Http429(Exception):
    code = 429


def _brave_429(url: str, hdrs: dict):
    raise Http429("HTTP Error 429: Too Many Requests")


class SearxSpy:
    """Injected SearXNG hop: records every call, answers with two hits."""

    def __init__(self, fail: bool = False):
        self.calls: list[tuple[str, str, int]] = []
        self.fail = fail

    def __call__(self, query: str, kind: str, count: int):
        self.calls.append((query, kind, count))
        if self.fail:
            raise RuntimeError("URLError: connection refused")
        return [
            {"title": "searx hit 1", "url": "https://example.com/1", "snippet": "s1", "domain": "example.com"},
            {"title": "searx hit 2", "url": "https://example.com/2", "snippet": "s2", "domain": "example.com"},
        ]


@pytest.fixture
def tmp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    monkeypatch.delenv("BRAVE_ROUTER_LIVE", raising=False)
    for k in ("SEARCH_BUDGET_BRAVE_DAILY", "SEARCH_BUDGET_BRAVE_MONTHLY",
              "SEARCH_BUDGET_SEARXNG_DAILY", "SEARCH_BUDGET_SEARXNG_MONTHLY"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def _receipts(root: Path) -> list[dict]:
    return sb.denial_receipts(root=root)


# ── the chain and the reasons come from the registry ─────────────────────────


def test_spill_chain_and_reasons_are_read_from_the_registry():
    assert br._resolve_spill_chain() == ["searxng", "tavily"]
    assert br._spill_reasons() == frozenset({"DAILY_EXHAUSTED", "MONTHLY_EXHAUSTED", "HTTP_429"})
    assert dsa.primary_provider("web_search") == "brave"


def test_tavily_is_declared_but_has_no_adapter():
    """The registry lists tavily; this tree has no client. It must be visible, not silent."""
    assert "tavily" in br._resolve_spill_chain()
    assert "tavily" not in br.SPILL_ADAPTERS
    assert set(br.SPILL_ADAPTERS) == {"searxng"}


# ── negative control: the pre-fix behaviour ──────────────────────────────────


def test_denial_without_a_resolver_is_lost_and_the_receipt_says_nowhere(tmp_root, monkeypatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "0")
    monkeypatch.setattr(br, "_resolve_spill_chain", lambda: [])      # pre-fix: no chain
    spy = SearxSpy()
    resp = br.search("NVDA stock news", clock=FixedClock(T0), root=tmp_root, transport=_brave_ok,
                     enabled=True, api_key="fixture", spill_transport=spy)
    assert resp.ok is False
    assert resp.reason == "BUDGET_REFUSED:DAILY_EXHAUSTED"
    assert resp.results == []
    assert spy.calls == [], "no chain → no backup call"
    rows = _receipts(tmp_root)
    assert len(rows) == 1
    assert rows[0]["provider"] == "brave" and rows[0]["reason"] == "DAILY_EXHAUSTED"
    assert rows[0]["spilled_to"] is None
    assert rows[0]["detail"]["tried"] == {"_": "NO_BACKUP_CHAIN"}
    assert sb.status("searxng", now=T0, root=tmp_root)["daily_used"] == 0


def test_no_spill_opt_out_keeps_the_question_on_brave_only(tmp_root, monkeypatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "0")
    spy = SearxSpy()
    resp = br.search("NVDA stock news", clock=FixedClock(T0), root=tmp_root, transport=_brave_ok,
                     enabled=True, api_key="fixture", spill_transport=spy, no_spill=True)
    assert resp.ok is False and resp.results == []
    assert spy.calls == []
    rows = _receipts(tmp_root)
    assert len(rows) == 1 and rows[0]["spilled_to"] is None
    assert rows[0]["detail"]["no_spill"] is True


# ── the fix ──────────────────────────────────────────────────────────────────


def test_daily_denial_spills_to_searxng_and_writes_the_receipt(tmp_root, monkeypatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "0")
    spy = SearxSpy()
    clock = FixedClock(T0)
    resp = br.search("NVDA stock news", kind="news", count=5, clock=clock, root=tmp_root,
                     transport=_brave_ok, enabled=True, api_key="fixture",
                     caller="catalyst_intelligence", spill_transport=spy)
    assert resp.ok is True
    assert resp.reason == "SPILLED:searxng"
    assert resp.provider == "searxng"
    assert resp.budget_allocated is False, "no Brave unit was spent"
    assert len(resp.results) == 2 and all(r["provider"] == "searxng" for r in resp.results)
    assert resp.results[0]["source"] == "example.com"
    assert spy.calls == [("NVDA stock news", "news", 5)], "same question, once"

    rows = _receipts(tmp_root)
    assert len(rows) == 1
    row = rows[0]
    assert row["provider"] == "brave"
    assert row["reason"] == "DAILY_EXHAUSTED"
    assert row["spilled_to"] == "searxng"
    assert row["ts"] == "2026-09-13T14:00:00+00:00"
    assert row["caller"] == "catalyst_intelligence"
    assert row["detail"]["chain"] == ["searxng", "tavily"]
    assert row["detail"]["tried"]["searxng"] == "OK:2"
    assert resp.receipt == row

    # The receipt sits in the SAME ledger as the counters.
    doc = json.loads(sb.budget_path(tmp_root).read_text())
    assert doc["denial_receipts"][0]["spilled_to"] == "searxng"
    assert doc["providers"]["brave"]["denied"]["2026-09-13"] == 1
    assert sb.status("searxng", now=T0, root=tmp_root)["daily_used"] == 1
    assert sb.status("brave", now=T0, root=tmp_root)["daily_used"] == 0


def test_monthly_denial_spills_too(tmp_root, monkeypatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "0")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "100")
    spy = SearxSpy()
    resp = br.search("AAPL guidance", clock=FixedClock(T0), root=tmp_root, transport=_brave_ok,
                     enabled=True, api_key="fixture", spill_transport=spy)
    assert resp.ok and resp.provider == "searxng"
    rows = _receipts(tmp_root)
    assert rows[0]["reason"] == "MONTHLY_EXHAUSTED" and rows[0]["spilled_to"] == "searxng"
    assert len(spy.calls) == 1


def test_http_429_from_brave_refunds_and_spills(tmp_root):
    spy = SearxSpy()
    clock = FixedClock(T0)
    resp = br.search("TSLA recall", clock=clock, root=tmp_root, transport=_brave_429,
                     enabled=True, api_key="fixture", spill_transport=spy)
    assert resp.ok and resp.provider == "searxng" and resp.reason == "SPILLED:searxng"
    assert sb.status("brave", now=T0, root=tmp_root)["daily_used"] == 0, "429 unit refunded"
    rows = _receipts(tmp_root)
    assert rows[0]["reason"] == "HTTP_429" and rows[0]["spilled_to"] == "searxng"


def test_a_reason_the_registry_does_not_list_does_not_spill(tmp_root, monkeypatch):
    """MONTHLY_RESERVE_ONLY: the month is not exhausted, the bulk allowance is.
    web_search.spill_on does not name it, so the router must not spill — and
    the receipt must say which reasons would have."""
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "5")   # reserve = min(200, 5//5) = 1 → bulk ceiling 4
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "100")
    clock = FixedClock(T0)
    spy = SearxSpy()
    for i in range(4):
        r = br.search(f"q{i}", clock=clock, root=tmp_root, transport=_brave_ok, enabled=True,
                      api_key="fixture", idempotency_key=f"k{i}", spill_transport=spy)
        assert r.ok and r.provider == "brave"
    r5 = br.search("q-bulk-5", clock=clock, root=tmp_root, transport=_brave_ok, enabled=True,
                   api_key="fixture", idempotency_key="k5", spill_transport=spy)
    assert r5.ok is False and r5.reason == "BUDGET_REFUSED:MONTHLY_RESERVE_ONLY"
    assert spy.calls == []
    rows = _receipts(tmp_root)
    assert len(rows) == 1 and rows[0]["spilled_to"] is None
    assert rows[0]["detail"]["not_a_spill_reason"] == ["DAILY_EXHAUSTED", "HTTP_429", "MONTHLY_EXHAUSTED"]


def test_backup_is_budget_checked_under_its_own_cap_and_falls_through(tmp_root, monkeypatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "0")
    monkeypatch.setenv("SEARCH_BUDGET_SEARXNG_DAILY", "0")
    spy = SearxSpy()
    resp = br.search("NVDA", clock=FixedClock(T0), root=tmp_root, transport=_brave_ok,
                     enabled=True, api_key="fixture", spill_transport=spy)
    assert resp.ok is False and resp.results == []
    assert spy.calls == [], "searxng over its cap → never called"
    row = _receipts(tmp_root)[0]
    assert row["spilled_to"] is None
    assert row["detail"]["tried"]["searxng"] == "BUDGET_REFUSED:DAILY_EXHAUSTED"
    assert row["detail"]["tried"]["tavily"].startswith("NO_ADAPTER")


def test_backup_failure_refunds_its_unit(tmp_root, monkeypatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "0")
    spy = SearxSpy(fail=True)
    resp = br.search("NVDA", clock=FixedClock(T0), root=tmp_root, transport=_brave_ok,
                     enabled=True, api_key="fixture", spill_transport=spy)
    assert resp.ok is False
    assert len(spy.calls) == 1
    assert sb.status("searxng", now=T0, root=tmp_root)["daily_used"] == 0
    row = _receipts(tmp_root)[0]
    assert row["spilled_to"] is None
    assert row["detail"]["tried"]["searxng"].startswith("PROVIDER_ERROR:")


def test_spilled_answer_is_cached_so_the_next_ask_costs_nothing(tmp_root, monkeypatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "0")
    spy = SearxSpy()
    clock = FixedClock(T0)
    r1 = br.search("NVDA", clock=clock, root=tmp_root, transport=_brave_ok, enabled=True,
                   api_key="fixture", spill_transport=spy)
    r2 = br.search("NVDA", clock=clock, root=tmp_root, transport=_brave_ok, enabled=True,
                   api_key="fixture", spill_transport=spy)
    assert r1.ok and r2.ok and r2.cache_hit
    assert len(spy.calls) == 1
    assert len(_receipts(tmp_root)) == 1, "a cache hit is not a denial"


def test_live_searxng_hop_refuses_to_leave_the_host_unless_armed(monkeypatch):
    monkeypatch.delenv("BRAVE_ROUTER_LIVE", raising=False)
    with pytest.raises(RuntimeError, match="BRAVE_ROUTER_LIVE"):
        br._searxng_transport("q", "web", 3)


# ── budgets from ONE place ───────────────────────────────────────────────────


def _registry_with_brave_budget(budget):
    # Read the file, not dsa.registry(): tests monkeypatch dsa.registry to a lambda
    # that calls THIS helper, and the recursion would be swallowed by the fallback.
    reg = json.loads(json.dumps(dsa._load_registry_file()))
    if budget is None:
        reg["providers"]["brave"].pop("budget", None)
    else:
        reg["providers"]["brave"]["budget"] = budget
    return reg


def test_the_registry_caps_override_the_module_constants(monkeypatch):
    monkeypatch.delenv("SEARCH_BUDGET_BRAVE_DAILY", raising=False)
    monkeypatch.delenv("SEARCH_BUDGET_BRAVE_MONTHLY", raising=False)
    assert sb.DEFAULT_LIMITS["brave"] == {"daily": 120, "monthly": 1500}
    monkeypatch.setattr(dsa, "registry", lambda: _registry_with_brave_budget({"daily": 7, "monthly": 70}))
    assert sb.limits("brave") == {"daily": 7, "monthly": 70}
    assert br.local_cost_policy()["daily"] == 7 and br.local_cost_policy()["monthly"] == 70


def test_a_registry_silent_about_a_provider_falls_back_to_the_constants(monkeypatch):
    monkeypatch.delenv("SEARCH_BUDGET_BRAVE_DAILY", raising=False)
    monkeypatch.delenv("SEARCH_BUDGET_BRAVE_MONTHLY", raising=False)
    monkeypatch.setattr(dsa, "registry", lambda: _registry_with_brave_budget(None))
    assert sb.limits("brave") == sb.DEFAULT_LIMITS["brave"]


def test_an_unreadable_registry_falls_back_rather_than_denying_everything(monkeypatch):
    monkeypatch.delenv("SEARCH_BUDGET_BRAVE_DAILY", raising=False)

    def boom():
        raise OSError("registry unreadable")

    monkeypatch.setattr(dsa, "registry", boom)
    assert sb.limits("brave") == sb.DEFAULT_LIMITS["brave"]


def test_env_override_still_wins_over_the_registry(monkeypatch):
    monkeypatch.setattr(dsa, "registry", lambda: _registry_with_brave_budget({"daily": 7, "monthly": 70}))
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "3")
    monkeypatch.delenv("SEARCH_BUDGET_BRAVE_MONTHLY", raising=False)
    assert sb.limits("brave") == {"daily": 3, "monthly": 70}


def test_the_live_registry_declares_the_measured_caps(monkeypatch):
    for k in ("BRAVE", "SEARXNG", "TAVILY"):
        monkeypatch.delenv(f"SEARCH_BUDGET_{k}_DAILY", raising=False)
        monkeypatch.delenv(f"SEARCH_BUDGET_{k}_MONTHLY", raising=False)
    assert dsa.provider_budget("brave") == {"daily": 120, "monthly": 1500}
    assert dsa.provider_budget("searxng") == {"daily": 10000}
    assert dsa.provider_budget("tavily") == {"daily": 20}
    assert sb.limits("brave") == {"daily": 120, "monthly": 1500}
    assert sb.limits("searxng")["daily"] == 10000
    assert sb.limits("tavily")["daily"] == 20


# ── receipts are archived, never deleted ─────────────────────────────────────


def test_receipt_overflow_rolls_to_the_archive_sidecar(tmp_root, monkeypatch):
    monkeypatch.setattr(sb, "RECEIPTS_INLINE_MAX", 3)
    for i in range(5):
        sb.write_denial_receipt("brave", "DAILY_EXHAUSTED", spilled_to=None, caller=f"c{i}",
                                now=T0 + timedelta(minutes=i), root=tmp_root)
    inline = sb.denial_receipts(root=tmp_root)
    assert [r["caller"] for r in inline] == ["c2", "c3", "c4"]
    archive = sb.receipts_archive_path(tmp_root).read_text().strip().splitlines()
    assert [json.loads(l)["caller"] for l in archive] == ["c0", "c1"]


def test_a_corrupt_ledger_is_never_rebuilt_by_a_receipt(tmp_root):
    sb.budget_path(tmp_root).write_text("{not-json")
    assert sb.write_denial_receipt("brave", "DAILY_EXHAUSTED", spilled_to=None, root=tmp_root) is None
    assert sb.budget_path(tmp_root).read_text() == "{not-json"
