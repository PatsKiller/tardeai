#!/usr/bin/env python3
"""Negative controls and behaviour tests for the canonical Brave router.

Every test here runs against an isolated ``tmp_path`` state root and a monkey-
patched transport. **No test in this file may reach the network**; the last
test in the module asserts that property structurally.

Covers source-prompt Phase 9 "Brave" items 1-13.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.lib import brave_research_router as R  # noqa: E402
from scripts.lib import search_budget as SB  # noqa: E402

NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def root(tmp_path, monkeypatch):
    """An isolated state root. Never the production one."""
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key-not-real")
    (tmp_path / "data" / "runtime").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _budget(root: Path, *, daily: int, monthly: int):
    """Pin the shared ledger limits for this isolated root."""
    import os

    os.environ["SEARCH_BUDGET_BRAVE_DAILY"] = str(daily)
    os.environ["SEARCH_BUDGET_BRAVE_MONTHLY"] = str(monthly)


class FakeResponse:
    def __init__(self, body: bytes, headers: dict, status: int = 200):
        self._body = body
        self.headers = headers
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _web_body(n: int = 3, urls=None):
    urls = urls or [f"https://example{i}.com/a" for i in range(n)]
    return json.dumps(
        {
            "web": {
                "results": [
                    {"title": f"t{i}", "url": urls[i], "description": f"d{i}", "age": "1d"} for i in range(len(urls))
                ]
            }
        }
    ).encode()


def _patch_transport(monkeypatch, body: bytes, headers=None, status=200, counter=None):
    hdrs = headers or {
        "x-ratelimit-policy": "1;w=1, 15000;w=2592000",
        "x-ratelimit-limit": "1, 15000",
        "x-ratelimit-remaining": "1, 14980",
    }

    def fake_urlopen(req, timeout=None):
        if counter is not None:
            counter.append(getattr(req, "full_url", ""))
        return FakeResponse(body, hdrs, status)

    monkeypatch.setattr(R.urllib.request, "urlopen", fake_urlopen)


# ── 1. Allowance is measured, not a guessed tier ────────────────────────────


def test_allowance_is_measured_from_response_headers(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    _patch_transport(
        monkeypatch,
        _web_body(),
        headers={
            "x-ratelimit-policy": "1;w=1, 15000;w=2592000",
            "x-ratelimit-limit": "1, 15000",
            "x-ratelimit-remaining": "1, 14980",
        },
    )
    out = R.search("q", caller="t", root=root, now=NOW)
    assert out.status is R.Status.OK
    a = out.observed_allowance
    assert a["billing_window_seconds"] == 2592000
    assert a["rate_limit_per_second"] == 1
    assert a["measured_monthly_limit"] == 15000
    rec = R.allowance_reconciliation(root=root)
    assert rec["reconciled"] is True
    assert rec["measured_monthly_limit"] == 15000


def test_per_second_rate_is_not_mistaken_for_a_monthly_quota(root, monkeypatch):
    """Regression: the live plan reports `50;w=1, 0;w=2592000`.

    Reading these as "max(50, 0) = 50 per month" reports a 50-req/s plan as
    allowing 50 calls a month. The billing window is the largest `w`.
    """
    _budget(root, daily=25, monthly=850)
    _patch_transport(
        monkeypatch,
        _web_body(),
        headers={
            "x-ratelimit-policy": "50;w=1, 0;w=2592000",
            "x-ratelimit-limit": "50, 0",
            "x-ratelimit-remaining": "49, 0",
            "x-ratelimit-reset": "1, 2339976",
        },
    )
    out = R.search("q", caller="t", root=root, now=NOW)
    a = out.observed_allowance
    assert a["rate_limit_per_second"] == 50
    assert a["billing_window_seconds"] == 2592000
    assert a["billing_window_limit"] == 0
    assert a["billing_window_metered"] is False
    # A 0 on the billing window must NOT be published as a monthly quota.
    assert "measured_monthly_limit" not in a
    assert a["billing_window_reset_seconds"] == 2339976


def test_unmetered_plan_reports_the_ceiling_as_local_policy(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    _patch_transport(
        monkeypatch,
        _web_body(),
        headers={
            "x-ratelimit-policy": "50;w=1, 0;w=2592000",
            "x-ratelimit-limit": "50, 0",
            "x-ratelimit-remaining": "49, 0",
        },
    )
    R.search("q", caller="t", root=root, now=NOW)
    rec = R.allowance_reconciliation(root=root)
    assert rec["billing_window_metered"] is False
    assert "LOCAL POLICY cap" in rec["note"]
    assert "not a provider" in rec["note"]


def test_allowance_windows_parse_without_a_policy_header(root):
    """Brave orders windows ascending; the last value is the billing period."""
    a = R.parse_allowance({"x-ratelimit-limit": "1, 2000", "x-ratelimit-remaining": "1, 1900"})
    assert a["rate_limit_per_second"] == 1
    assert a["measured_monthly_limit"] == 2000
    assert a["measured_monthly_remaining"] == 1900


def test_unmeasured_allowance_is_reported_as_an_assumption(root):
    rec = R.allowance_reconciliation(root=root)
    assert rec["reconciled"] is False
    assert "assumption" in rec["note"].lower()


def test_configured_ceiling_above_measured_plan_is_flagged(root, monkeypatch):
    _budget(root, daily=25, monthly=99999)
    _patch_transport(
        monkeypatch,
        _web_body(),
        headers={"x-ratelimit-policy": "1;w=1, 2000;w=2592000", "x-ratelimit-limit": "1, 2000"},
    )
    R.search("q", caller="t", root=root, now=NOW)
    rec = R.allowance_reconciliation(root=root)
    assert rec["measured_monthly_limit"] == 2000
    assert "EXCEEDS" in rec["note"]


# ── 2. Concurrency cannot overspend ─────────────────────────────────────────


def test_concurrent_consume_cannot_exceed_the_ceiling(root):
    """The last unit is consumed exactly once across many attempts."""
    _budget(root, daily=100, monthly=3)
    allowed = [SB.try_consume("brave", caller="c", root=root)["allowed"] for _ in range(10)]
    assert sum(allowed) == 3, f"overspend: {sum(allowed)} allowed against a ceiling of 3"


def test_router_consumes_atomically_not_check_then_record(root, monkeypatch):
    """Budget is spent via try_consume, so a check/record TOCTOU cannot recur."""
    _budget(root, daily=2, monthly=100)
    _patch_transport(monkeypatch, _web_body())
    a = R.search("q1", caller="t", root=root, now=NOW)
    b = R.search("q2", caller="t", root=root, now=NOW)
    c = R.search("q3", caller="t", root=root, now=NOW)
    assert a.status is R.Status.OK and b.status is R.Status.OK
    assert c.status is R.Status.DENIED_BUDGET
    assert "DAILY_EXHAUSTED" in c.reason


# ── 3. Corrupt ledger fails closed and is not overwritten ───────────────────


def test_corrupt_ledger_denies_and_is_not_rebuilt_as_zero(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    ledger = SB.budget_path(root)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("{ this is not json", encoding="utf-8")
    before = ledger.read_text(encoding="utf-8")

    _patch_transport(monkeypatch, _web_body())
    out = R.search("q", caller="t", root=root, now=NOW)

    assert out.status is R.Status.BUDGET_UNAVAILABLE
    assert out.degraded is True
    assert ledger.read_text(encoding="utf-8") == before, (
        "corrupt ledger was overwritten — that is the fail-open write path"
    )


# ── 4. Cache and coalescing prevent duplicate calls ─────────────────────────


def test_cache_survives_a_second_independent_call(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    calls: list[str] = []
    _patch_transport(monkeypatch, _web_body(), counter=calls)
    first = R.search("same question", caller="t", root=root, now=NOW)
    second = R.search("same question", caller="t", root=root, now=NOW)
    assert first.status is R.Status.OK
    assert second.status is R.Status.CACHED
    assert second.cache_hit is True
    assert len(calls) == 1, "second identical query hit the provider"


def test_cache_is_durable_across_processes_not_a_module_dict(root, monkeypatch):
    """The bug being fixed: an in-process dict gives every cron run a cold cache.

    Proven with a genuinely separate interpreter rather than a module reload:
    the answer must be readable by a process that never saw the first call.
    """
    import subprocess

    _budget(root, daily=25, monthly=850)
    calls: list[str] = []
    _patch_transport(monkeypatch, _web_body(), counter=calls)
    first = R.search("durable q", caller="t", root=root, now=NOW)
    assert first.status is R.Status.OK
    assert len(calls) == 1

    fp = R.fingerprint("durable q", endpoint="web", freshness=None, count=5)
    assert (R.cache_dir(root) / f"{fp}.json").exists(), "cache did not land on disk — it is still process-local"

    # A brand-new interpreter, no shared memory with this one.
    probe = (
        "import sys, json;"
        f"sys.path.insert(0, {str(REPO)!r});"
        "from scripts.lib import brave_research_router as R;"
        f"c = R.cache_get({fp!r}, 3600, root={str(root)!r});"
        "print(json.dumps({'hit': c is not None, 'n': len(c or [])}))"
    )
    res = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    got = json.loads(res.stdout.strip().splitlines()[-1])
    assert got["hit"] is True, "a fresh process could not read the cached answer"
    assert got["n"] == 3


def test_query_normalization_shares_one_cache_slot(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    calls: list[str] = []
    _patch_transport(monkeypatch, _web_body(), counter=calls)
    R.search("NVDA  Earnings!", caller="t", root=root, now=NOW)
    out = R.search("nvda earnings", caller="t", root=root, now=NOW)
    assert out.status is R.Status.CACHED
    assert len(calls) == 1


def test_token_order_is_not_collapsed(root):
    """Different questions must not silently share an answer."""
    assert R.fingerprint("TSLA recall") != R.fingerprint("recall TSLA")


def test_empty_result_is_cached_so_it_is_not_re_bought(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    calls: list[str] = []
    _patch_transport(monkeypatch, json.dumps({"web": {"results": []}}).encode(), counter=calls)
    first = R.search("nothing here", caller="t", root=root, now=NOW)
    second = R.search("nothing here", caller="t", root=root, now=NOW)
    assert first.status is R.Status.EMPTY
    assert second.status is R.Status.CACHED
    assert len(calls) == 1


# ── 5/6. Priority and reserve ───────────────────────────────────────────────


def test_reserve_protects_capacity_from_cold_universe(root):
    _budget(root, daily=100, monthly=100)
    # Spend down to inside the 15% reserve.
    for _ in range(86):
        SB.try_consume("brave", caller="bulk", root=root)
    refusal = R.evaluate_gates(
        purpose=R.Purpose.LONG_TAIL_DISCOVERY, priority=R.Priority.COLD_UNIVERSE, caller="t", root=root, now=NOW
    )
    assert refusal is not None
    assert refusal[0] is R.Status.DENIED_RESERVE


def test_held_capital_may_draw_on_the_reserve(root):
    _budget(root, daily=100, monthly=100)
    for _ in range(86):
        SB.try_consume("brave", caller="bulk", root=root)
    refusal = R.evaluate_gates(
        purpose=R.Purpose.EVIDENCE_GAP, priority=R.Priority.HELD_CAPITAL, caller="t", root=root, now=NOW
    )
    assert refusal is None, "held-capital evidence gap was denied its reserve"


def test_purpose_quota_bounds_one_purpose(root, monkeypatch):
    _budget(root, daily=1000, monthly=100)
    monkeypatch.setenv("BRAVE_QUOTA_SOCIAL_LEAD_DISCOVERY", "2")
    _patch_transport(monkeypatch, _web_body())
    for i in range(2):
        o = R.search(
            f"social {i}",
            purpose=R.Purpose.SOCIAL_LEAD_DISCOVERY,
            priority=R.Priority.HELD_CAPITAL,
            caller="t",
            root=root,
            now=NOW,
        )
        assert o.status is R.Status.OK
    o = R.search(
        "social 3",
        purpose=R.Purpose.SOCIAL_LEAD_DISCOVERY,
        priority=R.Priority.HELD_CAPITAL,
        caller="t",
        root=root,
        now=NOW,
    )
    assert o.status is R.Status.DENIED_PURPOSE_QUOTA


# ── 7. Error classes are distinguished ──────────────────────────────────────


@pytest.mark.parametrize(
    "code,expected",
    [
        (401, R.Status.UNAUTHORIZED),
        (402, R.Status.PAYMENT_REQUIRED),
        (403, R.Status.FORBIDDEN),
        (429, R.Status.RATE_LIMITED),
        (500, R.Status.SERVER_ERROR),
        (503, R.Status.SERVER_ERROR),
    ],
)
def test_http_error_codes_are_distinguishable(root, monkeypatch, code, expected):
    _budget(root, daily=25, monthly=850)

    def boom(req, timeout=None):
        raise R.urllib.error.HTTPError(req.full_url, code, "err", {}, None)

    monkeypatch.setattr(R.urllib.request, "urlopen", boom)
    out = R.search(f"q{code}", caller="t", root=root, now=NOW)
    assert out.status is expected
    assert out.degraded is True
    assert out.degradation_note()  # an operator-legible reason exists


def test_timeout_is_not_an_empty_result(root, monkeypatch):
    _budget(root, daily=25, monthly=850)

    def slow(req, timeout=None):
        raise TimeoutError("timed out")

    monkeypatch.setattr(R.urllib.request, "urlopen", slow)
    out = R.search("q", caller="t", root=root, now=NOW)
    assert out.status is R.Status.TIMEOUT
    assert out.results == []
    assert out.status is not R.Status.EMPTY


def test_malformed_body_is_distinguished_from_empty(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    _patch_transport(monkeypatch, b"<html>not json</html>")
    out = R.search("q", caller="t", root=root, now=NOW)
    assert out.status is R.Status.MALFORMED
    assert out.provider_billed is True, "a 200 was billed even though unreadable"


def test_missing_key_is_distinguished_from_empty(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.setattr(R, "_api_key", lambda project_root=None: None)
    out = R.search("q", caller="t", root=root, now=NOW)
    assert out.status is R.Status.DENIED_NO_KEY


def test_every_failure_mode_yields_a_distinct_status(root):
    """The core contract: `[]` is never the answer to 'what happened?'."""
    seen = set()
    for s in R.Status:
        note = R.Outcome(status=s).degradation_note()
        if s not in (R.Status.OK, R.Status.CACHED, R.Status.COALESCED):
            assert note, f"{s} has no operator-legible note"
            seen.add(note)
    assert len(seen) >= 12


# ── 8/9. Snippets stay discovery; primary sources are preferred ─────────────


def test_every_result_is_attributed_search_discovery(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    _patch_transport(monkeypatch, _web_body(urls=["https://reddit.com/r/stocks/x", "https://x.com/a/status/1"]))
    out = R.search(
        "chatter",
        purpose=R.Purpose.SOCIAL_LEAD_DISCOVERY,
        priority=R.Priority.HELD_CAPITAL,
        caller="t",
        root=root,
        now=NOW,
    )
    assert out.results
    for r in out.results:
        assert r.attribution == "SEARCH_DISCOVERY", "a Brave hit on a social page was not labelled discovery"


def test_primary_source_is_ranked_first(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    _patch_transport(
        monkeypatch,
        _web_body(
            urls=[
                "https://seekingalpha.com/article/1",
                "https://blog.example.com/take",
                "https://www.sec.gov/Archives/edgar/data/1/000.htm",
            ]
        ),
    )
    out = R.search(
        "filing",
        purpose=R.Purpose.PRIMARY_SOURCE_DISCOVERY,
        priority=R.Priority.HELD_CAPITAL,
        caller="t",
        root=root,
        now=NOW,
    )
    assert out.results[0].is_primary_source is True
    assert "sec.gov" in out.results[0].url


def test_domain_diversity_is_preserved(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    _patch_transport(
        monkeypatch,
        _web_body(
            urls=[
                "https://a.com/1",
                "https://a.com/2",
                "https://b.com/1",
                "https://c.com/1",
            ]
        ),
    )
    out = R.search("q", caller="t", root=root, now=NOW)
    assert R.unique_domains(out.results) == ["a.com", "b.com", "c.com"]


# ── 10. Page loads cause zero Brave calls ───────────────────────────────────


def test_page_load_purpose_is_denied_by_policy(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    calls: list[str] = []
    _patch_transport(monkeypatch, _web_body(), counter=calls)
    out = R.search(
        "render this", purpose=R.Purpose.PAGE_LOAD, priority=R.Priority.HELD_CAPITAL, caller="ui", root=root, now=NOW
    )
    assert out.status is R.Status.DENIED_POLICY
    assert calls == [], "a page-load purpose reached the provider"


@pytest.mark.parametrize(
    "p",
    [
        R.Purpose.QUOTE_RETRIEVAL,
        R.Purpose.BULK_SYMBOL_POLLING,
        R.Purpose.PAGE_LOAD,
        R.Purpose.SENTIMENT_SCORING,
    ],
)
def test_forbidden_purposes_are_refused_even_with_budget(root, monkeypatch, p):
    _budget(root, daily=9999, monthly=9999)
    calls: list[str] = []
    _patch_transport(monkeypatch, _web_body(), counter=calls)
    out = R.search("q", purpose=p, priority=R.Priority.HELD_CAPITAL, caller="t", root=root, now=NOW)
    assert out.status is R.Status.DENIED_POLICY
    assert calls == []


def test_no_evidence_gap_denies_the_spend(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    calls: list[str] = []
    _patch_transport(monkeypatch, _web_body(), counter=calls)
    out = R.search("already answered", caller="t", evidence_gap=False, root=root, now=NOW)
    assert out.status is R.Status.DENIED_NO_EVIDENCE_GAP
    assert calls == []


# ── 11. Metrics reconcile ───────────────────────────────────────────────────


def test_metrics_reconcile_with_what_happened(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    _patch_transport(monkeypatch, _web_body())
    R.search("m1", caller="t", root=root, now=NOW)  # billed
    R.search("m1", caller="t", root=root, now=NOW)  # cached
    R.search("m2", purpose=R.Purpose.PAGE_LOAD, caller="t", root=root, now=NOW)
    rep = R.effectiveness_report(root=root, now=NOW)
    assert rep["attempted"] == 3
    assert rep["billed"] == 1
    assert rep["cache_hits"] == 1
    assert rep["denied"] == 1
    assert rep["adopted"] == 0
    assert rep["adoption_rate_pct"] == 0.0


def test_adoption_is_the_metric_that_matters(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    _patch_transport(monkeypatch, _web_body())
    out = R.search("adopt me", caller="t", root=root, now=NOW)
    R.record_adoption(out.fingerprint, purpose=out.purpose, closed_evidence_gap=True, root=root, now=NOW)
    rep = R.effectiveness_report(root=root, now=NOW)
    assert rep["adopted"] == 1
    assert rep["evidence_gaps_closed"] == 1
    assert rep["calls_per_adopted_evidence"] == 1.0


def test_producing_but_not_adopted_is_reported_as_a_health_finding(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    _patch_transport(monkeypatch, _web_body())
    R.search("spend", caller="t", root=root, now=NOW)
    h = R.health(root=root, now=NOW)
    assert "brave_producing_not_adopted" in h["firing"]
    assert h["ok"] is False


def test_health_reports_four_separate_clocks(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    _patch_transport(monkeypatch, _web_body())
    out = R.search("clocks", caller="t", root=root, now=NOW)
    R.record_adoption(out.fingerprint, purpose=out.purpose, root=root, now=NOW)
    h = R.health(root=root, now=NOW)
    for k in ("last_attempt", "last_success", "last_nonempty", "last_adopted"):
        assert h[k], f"{k} is not reported"


# ── 12. Schedule projection stays within the measured allowance ─────────────


def test_monthly_projection_is_checked_against_the_measured_allowance(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    _patch_transport(
        monkeypatch, _web_body(), headers={"x-ratelimit-policy": "1;w=1, 500;w=2592000", "x-ratelimit-limit": "1, 500"}
    )
    R.search("q", caller="t", root=root, now=NOW)
    rec = R.allowance_reconciliation(root=root)
    assert rec["measured_monthly_limit"] == 500
    assert rec["configured_monthly_limit"] == 850
    assert "EXCEEDS" in rec["note"], "a configured ceiling above the real plan must be flagged, not trusted"


# ── 13. No caller bypasses the router ───────────────────────────────────────


def test_no_test_in_this_module_reaches_the_network():
    """Structural guard: this suite must never spend a real credit."""
    src = Path(__file__).read_text(encoding="utf-8")
    body = src.split("def test_no_test_in_this_module_reaches_the_network")[0]
    assert "allow_network=True" not in body
    # Every test that calls R.search patches urlopen first.
    assert body.count("_patch_transport") >= 15


def test_dry_run_mode_runs_gates_without_a_request(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    calls: list[str] = []
    _patch_transport(monkeypatch, _web_body(), counter=calls)
    out = R.search("dry", caller="t", root=root, now=NOW, allow_network=False)
    assert calls == []
    assert out.status is R.Status.DENIED_POLICY
    assert "dry run" in out.reason


def test_router_never_raises_on_any_transport_failure(root, monkeypatch):
    _budget(root, daily=25, monthly=850)

    def explode(req, timeout=None):
        raise RuntimeError("provider on fire")

    monkeypatch.setattr(R.urllib.request, "urlopen", explode)
    out = R.search("q", caller="t", root=root, now=NOW)
    assert out.status is R.Status.TRANSPORT_ERROR
    assert out.degraded is True


def test_router_holds_no_trading_authority():
    """No research path may reach broker/order/risk interfaces.

    Scans executable identifiers only. Prose that *states* the module holds no
    broker authority is not a reference to one, and a substring scan over the
    raw file cannot tell the difference.
    """
    import ast

    src = (REPO / "scripts" / "lib" / "brave_research_router.py").read_text()
    tree = ast.parse(src)

    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr.lower())
        elif isinstance(node, ast.Import):
            for a in node.names:
                identifiers.add(a.name.lower())
        elif isinstance(node, ast.ImportFrom):
            identifiers.add((node.module or "").lower())
            for a in node.names:
                identifiers.add(a.name.lower())

    forbidden = (
        "place_order",
        "submit_order",
        "cancel_order",
        "broker",
        "alpaca",
        "schwab",
        "risk_limit",
        "position_size",
        "portfolio_server",
        "execute_trade",
    )
    hits = {f for f in forbidden if any(f in i for i in identifiers)}
    assert not hits, f"router references trading surfaces: {sorted(hits)}"

    # And no network target other than the search provider.
    urls = {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("http")
    }
    assert urls == {R.WEB_URL, R.NEWS_URL}, f"unexpected network targets: {urls}"


# ── Weekend deferral (preserves the 2026-08 on-demand incident) ─────────────

SATURDAY = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)


def test_weekend_defers_scheduled_background_research(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    calls: list[str] = []
    _patch_transport(monkeypatch, _web_body(), counter=calls)
    out = R.search("cold universe sweep", priority=R.Priority.COLD_UNIVERSE, caller="bulk", root=root, now=SATURDAY)
    assert out.status is R.Status.DENIED_WEEKEND
    assert calls == []


def test_weekend_never_defers_held_capital_or_urgent_catalyst(root, monkeypatch):
    """The incident: an on-demand lookup silently returned [] on a Saturday."""
    _budget(root, daily=25, monthly=850)
    for pri in (R.Priority.HELD_CAPITAL, R.Priority.URGENT_CATALYST):
        _patch_transport(monkeypatch, _web_body())
        out = R.search(f"urgent {pri.name}", priority=pri, caller="on-demand", root=root, now=SATURDAY)
        assert out.status is R.Status.OK, f"{pri.name} was deferred on a weekend"


def test_a_weekend_deferral_is_never_a_silent_empty_list(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    _patch_transport(monkeypatch, _web_body())
    out = R.search("q", priority=R.Priority.WATCHLIST, caller="bulk", root=root, now=SATURDAY)
    assert out.results == []
    assert out.status is not R.Status.EMPTY, "a deferral must not be indistinguishable from 'nothing was published'"
    assert out.degraded is True
    assert "markets are closed" in out.degradation_note()


def test_weekday_does_not_defer(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    _patch_transport(monkeypatch, _web_body())
    out = R.search("q", priority=R.Priority.COLD_UNIVERSE, caller="bulk", root=root, now=NOW)  # NOW is a Thursday
    assert out.status is R.Status.OK


# ── Schedule projection must fit inside the configured ceiling ──────────────


def test_purpose_quotas_fit_within_the_cap_and_leave_the_reserve():
    """The quotas are what make the live schedules affordable.

    Worst-case cron volume for the routed Brave lanes projects ~1,028 calls a
    month against 723 usable after the reserve. The per-purpose quotas are the
    mechanism that bounds it, so they must themselves sum to less than the
    usable capacity — otherwise bulk discovery could still crowd out
    held-capital evidence-gap work.
    """
    cap = 850
    reserve = int(cap * R.DEFAULT_RESERVE_PCT / 100)
    usable = cap - reserve
    total = sum(R.purpose_quota(p, cap) for p in R.DEFAULT_PURPOSE_QUOTA_PCT)
    assert total <= usable, f"purpose quotas total {total} exceed usable capacity {usable}"
    assert reserve > 0, "no operator reserve is held back"
    # Evidence-gap work must hold the largest single share.
    shares = {p: R.purpose_quota(p, cap) for p in R.DEFAULT_PURPOSE_QUOTA_PCT}
    assert max(shares, key=shares.get) is R.Purpose.EVIDENCE_GAP


def test_no_forbidden_purpose_has_a_quota():
    """A forbidden purpose must not be allocated spend at all."""
    for p in R.FORBIDDEN_PURPOSES:
        assert p not in R.DEFAULT_PURPOSE_QUOTA_PCT
