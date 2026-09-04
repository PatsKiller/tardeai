#!/usr/bin/env python3
"""Negative controls and behaviour tests for the canonical Brave router.

Every test here runs against an isolated ``tmp_path`` state root and a monkey-
patched transport. **No test in this file may reach the network**; the last
test in the module asserts that property structurally.

Covers source-prompt Phase 9 "Brave" items 1-13.
"""

from __future__ import annotations

import json
import time
import sys
from datetime import datetime, timedelta, timezone
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


@pytest.fixture(autouse=True)
def _isolate_budget_env():
    """Restore the SEARCH_BUDGET_* overrides after every test in this module.

    `_budget` writes them to `os.environ` directly, which leaked the last test's
    ceiling into every later module in the same pytest session — the operator
    truth-surface test then read a ceiling of 1 instead of 850 and failed only
    when run after this file. Setting them is fine; not putting them back is not.
    """
    import os

    keys = ("SEARCH_BUDGET_BRAVE_DAILY", "SEARCH_BUDGET_BRAVE_MONTHLY")
    saved = {k: os.environ.get(k) for k in keys}
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _budget(root: Path, *, daily: int, monthly: int):
    """Pin the shared ledger limits for this isolated root.

    Restored after each test by ``_isolate_budget_env``.
    """
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
        f"c = R.cache_get({fp!r}, 3600, root={str(root)!r}, now={NOW.timestamp()!r});"
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


# ═══════════════════════════════════════════════════════════════════════════
# Reservation / settlement, circuit breaker, stale-while-revalidate, redaction
# ═══════════════════════════════════════════════════════════════════════════


def test_reservation_spends_before_the_request(root):
    """Reserving after the request would let two processes take the last unit."""
    _budget(root, daily=25, monthly=850)
    rid = R.reserve("c", "EVIDENCE_GAP", root=root, now=NOW)
    assert rid
    assert SB.status("brave", now=NOW, root=root)["daily_used"] == 1
    assert rid in R.open_reservations(root=root)


def test_settlement_refunds_only_when_the_provider_was_not_reached(root):
    _budget(root, daily=25, monthly=850)
    rid = R.reserve("c", "EVIDENCE_GAP", root=root, now=NOW)
    assert R.settle(rid, provider_reached=False, caller="c", root=root, now=NOW) is True
    assert SB.status("brave", now=NOW, root=root)["daily_used"] == 0, "unit not returned"

    rid2 = R.reserve("c", "EVIDENCE_GAP", root=root, now=NOW)
    assert R.settle(rid2, provider_reached=True, caller="c", root=root, now=NOW) is False
    assert SB.status("brave", now=NOW, root=root)["daily_used"] == 1, "a billed call was refunded"


def test_settlement_is_idempotent_and_cannot_double_refund(root):
    """A retried settle must not hand back a second unit."""
    _budget(root, daily=25, monthly=850)
    rid = R.reserve("c", "EVIDENCE_GAP", root=root, now=NOW)
    assert R.settle(rid, provider_reached=False, caller="c", root=root, now=NOW) is True
    assert R.settle(rid, provider_reached=False, caller="c", root=root, now=NOW) is False
    assert R.settle(rid, provider_reached=False, caller="c", root=root, now=NOW) is False
    assert SB.status("brave", now=NOW, root=root)["daily_used"] == 0


def test_a_crashed_caller_does_not_leak_its_reservation(root):
    """Reserve, never settle (the process died), then reclaim."""
    _budget(root, daily=25, monthly=850)
    crashed = NOW - timedelta(seconds=R.RESERVATION_TTL_SECONDS + 60)
    R.reserve("crasher", "EVIDENCE_GAP", root=root, now=crashed)
    assert SB.status("brave", now=NOW, root=root)["daily_used"] == 1

    n = R.reclaim_stale_reservations(root=root, now=NOW)
    assert n == 1
    assert SB.status("brave", now=NOW, root=root)["daily_used"] == 0
    assert R.open_reservations(root=root) == {}


def test_reclaim_does_not_touch_a_live_in_flight_reservation(root):
    """A slow but living request must not have its unit pulled out from under it."""
    _budget(root, daily=25, monthly=850)
    R.reserve("live", "EVIDENCE_GAP", root=root, now=NOW)
    assert R.reclaim_stale_reservations(root=root, now=NOW) == 0
    assert SB.status("brave", now=NOW, root=root)["daily_used"] == 1


def test_transport_failure_returns_the_unit(root, monkeypatch):
    """End to end: a request that never reached the provider is not billed."""
    _budget(root, daily=25, monthly=850)

    def unreachable(req, timeout=None):
        raise OSError("Network is unreachable")

    monkeypatch.setattr(R.urllib.request, "urlopen", unreachable)
    out = R.search("q", caller="t", root=root, now=NOW)
    assert out.status is R.Status.TRANSPORT_ERROR
    assert SB.status("brave", now=NOW, root=root)["daily_used"] == 0, "an unreachable provider still consumed budget"


def test_a_billed_failure_keeps_the_unit(root, monkeypatch):
    """A 429 was served by the provider and is billed; it must not be refunded."""
    _budget(root, daily=25, monthly=850)

    def limited(req, timeout=None):
        raise R.urllib.error.HTTPError(req.full_url, 429, "slow down", {}, None)

    monkeypatch.setattr(R.urllib.request, "urlopen", limited)
    out = R.search("q", caller="t", root=root, now=NOW)
    assert out.status is R.Status.RATE_LIMITED
    assert SB.status("brave", now=NOW, root=root)["daily_used"] == 1


# ── Circuit breaker ─────────────────────────────────────────────────────────


def test_circuit_opens_after_repeated_provider_failures(root, monkeypatch):
    _budget(root, daily=100, monthly=850)

    def down(req, timeout=None):
        raise R.urllib.error.HTTPError(req.full_url, 503, "down", {}, None)

    monkeypatch.setattr(R.urllib.request, "urlopen", down)
    for i in range(R.BREAKER_THRESHOLD):
        R.search(f"q{i}", caller="t", root=root, now=NOW)
    assert R.breaker_state(root=root, now=NOW)["state"] == "open"

    spent_before = SB.status("brave", now=NOW, root=root)["daily_used"]
    out = R.search("q-after", caller="t", root=root, now=NOW)
    assert out.status is R.Status.CIRCUIT_OPEN
    assert SB.status("brave", now=NOW, root=root)["daily_used"] == spent_before, "an open circuit still spent budget"


def test_circuit_half_opens_after_the_cooldown(root, monkeypatch):
    _budget(root, daily=100, monthly=850)

    def down(req, timeout=None):
        raise R.urllib.error.HTTPError(req.full_url, 503, "down", {}, None)

    monkeypatch.setattr(R.urllib.request, "urlopen", down)
    for i in range(R.BREAKER_THRESHOLD):
        R.search(f"q{i}", caller="t", root=root, now=NOW)
    later = NOW + timedelta(seconds=R.BREAKER_COOLDOWN_SECONDS + 1)
    assert R.breaker_state(root=root, now=later)["state"] == "half_open"

    _patch_transport(monkeypatch, _web_body())
    out = R.search("recovered", caller="t", root=root, now=later)
    assert out.status is R.Status.OK
    assert R.breaker_state(root=root, now=later)["state"] == "closed", "a success did not reset the breaker"


def test_credential_and_rate_limit_failures_do_not_trip_the_breaker(root, monkeypatch):
    """A bad key is not a provider outage; retrying through a breaker won't fix it."""
    _budget(root, daily=100, monthly=850)
    for code in (401, 429):

        def err(req, timeout=None, _c=code):
            raise R.urllib.error.HTTPError(req.full_url, _c, "e", {}, None)

        monkeypatch.setattr(R.urllib.request, "urlopen", err)
        for i in range(R.BREAKER_THRESHOLD + 2):
            R.search(f"q{code}{i}", caller="t", root=root, now=NOW)
    assert R.breaker_state(root=root, now=NOW)["state"] == "closed"


# ── Backoff ─────────────────────────────────────────────────────────────────


def test_backoff_is_exponential_and_bounded():
    assert R.backoff_delay(0, rand=1.0) <= R.backoff_delay(3, rand=1.0)
    assert R.backoff_delay(50, rand=1.0) <= 8.0, "backoff is not capped"
    for a in range(6):
        lo, hi = R.backoff_delay(a, rand=0.0), R.backoff_delay(a, rand=1.0)
        assert lo > 0 and lo <= hi, "jitter is not bounded below"
        assert hi <= 8.0


# ── Stale-while-revalidate ──────────────────────────────────────────────────


def test_stale_is_never_served_unless_explicitly_allowed(root, monkeypatch):
    _budget(root, daily=100, monthly=850)
    _patch_transport(monkeypatch, _web_body())
    R.search("swr", caller="t", root=root, now=NOW)

    # +7 days keeps the same weekday: a Saturday would trip the weekend gate
    # before the transport error this test is about.
    expired = NOW + timedelta(days=7)

    def down(req, timeout=None):
        raise OSError("unreachable")

    monkeypatch.setattr(R.urllib.request, "urlopen", down)
    out = R.search("swr", caller="t", root=root, now=expired)  # allow_stale default False
    assert out.status is R.Status.TRANSPORT_ERROR
    assert out.results == [], "a stale answer was served without opt-in"


def test_stale_is_served_with_its_age_when_allowed(root, monkeypatch, tmp_path):
    _budget(root, daily=100, monthly=850)
    fp = R.fingerprint("swr2", endpoint="web", freshness=None, count=5)
    old = NOW.timestamp() - (R.DEFAULT_TTL[R.Purpose.EVIDENCE_GAP] + 3600)
    R.cache_put(
        fp,
        [R.Result(title="old", url="https://e.com/1", description="d", source_domain="e.com")],
        query="swr2",
        root=root,
        now=old,
    )

    def down(req, timeout=None):
        raise OSError("unreachable")

    monkeypatch.setattr(R.urllib.request, "urlopen", down)
    out = R.search("swr2", caller="t", root=root, now=NOW, allow_stale=True)
    assert out.status is R.Status.STALE_SERVED
    assert out.stale is True
    assert out.result_age_seconds and out.result_age_seconds > 0
    assert "older than its freshness window" in out.degradation_note()


def test_stale_beyond_grace_is_not_served(root, monkeypatch):
    _budget(root, daily=100, monthly=850)
    fp = R.fingerprint("swr3", endpoint="web", freshness=None, count=5)
    ancient = NOW.timestamp() - (R.DEFAULT_TTL[R.Purpose.EVIDENCE_GAP] + R.STALE_GRACE_SECONDS + 3600)
    R.cache_put(
        fp,
        [R.Result(title="ancient", url="https://e.com/1", description="d", source_domain="e.com")],
        query="swr3",
        root=root,
        now=ancient,
    )

    def down(req, timeout=None):
        raise OSError("unreachable")

    monkeypatch.setattr(R.urllib.request, "urlopen", down)
    out = R.search("swr3", caller="t", root=root, now=NOW, allow_stale=True)
    assert out.status is R.Status.TRANSPORT_ERROR


# ── Cache poisoning ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("status_code", [401, 402, 429, 500, 503])
def test_errors_do_not_poison_the_cache(root, monkeypatch, status_code):
    _budget(root, daily=100, monthly=850)

    def err(req, timeout=None):
        raise R.urllib.error.HTTPError(req.full_url, status_code, "e", {}, None)

    monkeypatch.setattr(R.urllib.request, "urlopen", err)
    R.search("poison", caller="t", root=root, now=NOW)
    fp = R.fingerprint("poison", endpoint="web", freshness=None, count=5)
    assert R.cache_get(fp, 3600, root=root) is None, f"HTTP {status_code} was written into the cache"


def test_a_malformed_body_does_not_poison_the_cache(root, monkeypatch):
    _budget(root, daily=100, monthly=850)
    _patch_transport(monkeypatch, b"<html>not json</html>")
    R.search("malformed", caller="t", root=root, now=NOW)
    fp = R.fingerprint("malformed", endpoint="web", freshness=None, count=5)
    assert R.cache_get(fp, 3600, root=root) is None


# ── Ledger integrity ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        '{"providers": {"brave"',  # truncated
        "",  # empty
        "null",  # valid JSON, wrong shape
        "[]",  # valid JSON, wrong type
    ],
)
def test_unreadable_ledgers_fail_closed(root, monkeypatch, payload):
    _budget(root, daily=25, monthly=850)
    ledger = SB.budget_path(root)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(payload, encoding="utf-8")
    before = ledger.read_text(encoding="utf-8")
    _patch_transport(monkeypatch, _web_body())
    out = R.search("q", caller="t", root=root, now=NOW)
    assert out.degraded is True, f"payload {payload!r} did not deny"
    assert ledger.read_text(encoding="utf-8") == before, "corrupt ledger overwritten"


def test_month_rollover_separates_periods(root):
    """A new month must start from zero without touching the prior month."""
    _budget(root, daily=1000, monthly=5)
    aug = datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc)
    for _ in range(5):
        SB.try_consume("brave", caller="c", now=aug, root=root)
    assert SB.check("brave", now=aug, root=root)["allowed"] is False

    sep = datetime(2026, 9, 1, 0, 1, tzinfo=timezone.utc)
    assert SB.check("brave", now=sep, root=root)["allowed"] is True
    assert SB.status("brave", now=sep, root=root)["monthly_used"] == 0
    assert SB.status("brave", now=aug, root=root)["monthly_used"] == 5


def test_legacy_quota_constants_cannot_control_runtime(root, monkeypatch):
    """brave_search's retained DAILY/MONTHLY numbers are documentation only."""
    import importlib

    bs = importlib.import_module("scripts.brave_search")
    monkeypatch.setattr(bs, "MONTHLY_BUDGET", 999999, raising=False)
    monkeypatch.setattr(bs, "DAILY_BUDGET", 999999, raising=False)
    _budget(root, daily=1, monthly=1)
    _patch_transport(monkeypatch, _web_body())
    R.search("a", caller="t", root=root, now=NOW)
    out = R.search("b", caller="t", root=root, now=NOW)
    assert out.status is R.Status.DENIED_BUDGET, "a legacy module constant influenced the governed ceiling"


# ── Secret redaction ────────────────────────────────────────────────────────


def test_the_api_key_never_appears_in_an_outcome(root, monkeypatch):
    _budget(root, daily=25, monthly=850)
    secret = "brave-secret-key-abcdef123456"
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", secret)

    def leaky(req, timeout=None):
        raise RuntimeError(f"failed calling {req.full_url}&key={secret}")

    monkeypatch.setattr(R.urllib.request, "urlopen", leaky)
    out = R.search("q", caller="t", root=root, now=NOW)
    blob = json.dumps(out.to_dict())
    assert secret not in blob, "the API key leaked into the outcome"
    assert "[REDACTED]" in out.reason


def test_redaction_covers_common_credential_shapes():
    secret = "supersecretvalue123"
    for probe in (
        f"X-Subscription-Token: {secret}",
        f"?api_key={secret}&q=x",
        f"authorization: Bearer {secret}",
        f"token={secret}",
    ):
        assert secret not in R.redact(probe), f"leaked from {probe!r}"
    assert R.redact_mapping({"X-Subscription-Token": secret, "Accept": "application/json"}) == {
        "X-Subscription-Token": "[REDACTED]",
        "Accept": "application/json",
    }


def test_no_secret_reaches_the_metrics_or_allowance_files(root, monkeypatch):
    secret = "another-secret-key-999"
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", secret)
    _budget(root, daily=25, monthly=850)
    _patch_transport(monkeypatch, _web_body())
    R.search("q", caller="t", root=root, now=NOW)
    for f in (R.metrics_path(root), R.allowance_path(root), R.reservations_path(root)):
        if f.exists():
            assert secret not in f.read_text(encoding="utf-8"), f"{f.name} leaked"


def test_the_ledger_and_the_gates_agree_on_which_day_it_is(root, monkeypatch):
    """Regression: reserve() once spent under wall-clock time while the gates
    evaluated under the injected clock.

    The two disagreed only across a day/month boundary, so it was invisible
    until UTC midnight passed mid-session: the gate checked an empty bucket and
    allowed, while the spend landed in yesterday's. A caller with an explicit
    clock — every scheduled job that pins its run time — could exceed the daily
    ceiling without any denial being recorded.
    """
    _budget(root, daily=2, monthly=100)
    # A logical clock deliberately on a DIFFERENT calendar day from wall time.
    other_day = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    _patch_transport(monkeypatch, _web_body())

    a = R.search("q1", caller="t", root=root, now=other_day)
    b = R.search("q2", caller="t", root=root, now=other_day)
    assert a.status is R.Status.OK and b.status is R.Status.OK

    # The spend must be visible in the SAME bucket the gate reads.
    st = SB.status("brave", now=other_day, root=root)
    assert st["daily_used"] == 2, "spend landed in a different day bucket than the gate"

    c = R.search("q3", caller="t", root=root, now=other_day)
    assert c.status is R.Status.DENIED_BUDGET
    assert "DAILY_EXHAUSTED" in c.reason


def test_refund_returns_the_unit_to_the_same_bucket_it_came_from(root):
    _budget(root, daily=5, monthly=50)
    other_day = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    rid = R.reserve("c", "EVIDENCE_GAP", root=root, now=other_day)
    assert SB.status("brave", now=other_day, root=root)["daily_used"] == 1
    R.settle(rid, provider_reached=False, caller="c", root=root, now=other_day)
    assert SB.status("brave", now=other_day, root=root)["daily_used"] == 0, (
        "the refund landed in a different bucket than the spend"
    )
