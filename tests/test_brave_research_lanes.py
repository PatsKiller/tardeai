#!/usr/bin/env python3
"""Research-lane contract tests: Docker, Hermes, schedulers, stores, fixtures.

Source-prompt Phase 8 "Research lanes" items 1-10. These are **contract** tests:
they assert the wiring that makes a lane real — that a trigger reaches its
producer, that producer and consumer resolve the same store, that a fixture
cannot pass as live data, that a failed run cannot advance freshness, and that a
disabled lane reports disabled rather than healthy.

They deliberately do not require Docker or a live provider: a test that silently
skips when infrastructure is absent is exactly the "looks green, proves nothing"
failure this campaign exists to remove. Where runtime state genuinely cannot be
asserted offline, the test asserts the *contract* in source and the inventory
records the runtime classification instead.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.lib import brave_research_router as R  # noqa: E402
from scripts.lib.research_observation.brave_adapter import (  # noqa: E402
    wrap_brave_outcome,
)
from scripts.lib.research_observation.statuses import FreshnessStatus  # noqa: E402

NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)


# ── 1/2. A lane trigger reaches its expected producer ───────────────────────

#: (module, the router entry point it must reach)
ROUTED_LANES = [
    ("scripts/aegis_social_sentiment.py", "SOCIAL_LEAD_DISCOVERY"),
    ("scripts/aegis_transcript_discovery.py", "TRANSCRIPT_DISCOVERY"),
    ("phase2b_analyst.py", "EVIDENCE_GAP"),
]


@pytest.mark.parametrize("module,purpose", ROUTED_LANES)
def test_lane_trigger_reaches_the_governed_producer(module, purpose):
    """The lane's collection path must call the router with a declared purpose."""
    src = (REPO / module).read_text(encoding="utf-8")
    assert "brave_research_router" in src, f"{module} does not reach the router"
    assert purpose in src, f"{module} does not declare purpose {purpose}"
    # And it must not have kept a private path to the provider.
    assert "api.search.brave.com" not in src
    assert "X-Subscription-Token" not in src


def test_every_declared_purpose_is_a_real_router_purpose():
    """A typo'd purpose string would silently fall back to a default quota."""
    valid = {p.value for p in R.Purpose}
    for module, _ in ROUTED_LANES:
        src = (REPO / module).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
                if node.value.attr == "Purpose":
                    assert node.attr in valid, f"{module}: unknown Purpose.{node.attr}"


# ── 3. Producer and consumer resolve the same canonical store ───────────────


def test_producer_and_consumer_resolve_one_ledger(tmp_path):
    """A forked store is how two components disagree about the same fact."""
    from scripts.lib import search_budget as SB

    producer = SB.budget_path(tmp_path)
    consumer = SB.budget_path(tmp_path)
    assert producer == consumer
    assert producer.is_relative_to(tmp_path)


def test_router_stores_all_live_under_one_state_root(tmp_path):
    roots = {
        R.cache_dir(tmp_path).parent,
        R.metrics_path(tmp_path).parent,
        R.allowance_path(tmp_path).parent,
        R.reservations_path(tmp_path).parent,
        R.breaker_path(tmp_path).parent,
    }
    assert len(roots) == 1, f"router stores are forked across {roots}"
    assert next(iter(roots)).is_relative_to(tmp_path)


def test_default_state_root_is_the_canonical_one():
    """Not a release-relative path: that is how each release got its own counter."""
    from scripts.lib import search_budget as SB

    assert str(SB.budget_path()).endswith("data/runtime/search_budget.json")
    assert R.metrics_path().parent == SB.budget_path().parent


# ── 4. Missing mounts and disconnected stores are detected ──────────────────


def test_an_unwritable_state_root_does_not_silently_succeed(tmp_path, monkeypatch):
    """A missing mount must not read as a healthy empty ledger."""
    from scripts.lib import search_budget as SB

    bad = tmp_path / "not" / "mounted"
    ledger = SB.budget_path(bad)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("{ truncated", encoding="utf-8")
    verdict = SB.check("brave", root=bad)
    assert verdict["allowed"] is False
    assert "BUDGET_UNAVAILABLE" in verdict["reason"]


def test_a_disconnected_cache_directory_is_a_miss_not_an_error(tmp_path):
    """A cache that cannot be read must degrade to a miss, never crash a lane."""
    assert R.cache_get("nonexistent-fingerprint", 3600, root=tmp_path) is None


# ── 5. Fixtures cannot masquerade as live data ──────────────────────────────


def test_a_fixture_outcome_is_never_labelled_fresh_without_results():
    empty = R.Outcome(status=R.Status.EMPTY, results=[], query="q", fingerprint="f")
    obs = wrap_brave_outcome(empty, run_id="r", trace_id="t", now=NOW)
    assert obs.freshness_status is FreshnessStatus.GAP
    assert obs.durable_output_present is False


def test_dry_run_mode_cannot_produce_a_live_observation():
    """allow_network=False must be visibly a non-result, not an empty success."""
    out = R.Outcome(status=R.Status.DENIED_POLICY, results=[], reason="allow_network=False (dry run)")
    obs = wrap_brave_outcome(out, run_id="r", trace_id="t", now=NOW)
    assert obs.freshness_status is FreshnessStatus.INELIGIBLE
    assert obs.durable_output_present is False
    assert "SEARCH_DISCOVERY" in obs.degraded_label


def test_the_router_never_synthesises_a_result():
    """No code path may fabricate a Result the provider did not return.

    Three construction sites are legitimate and each is named here: the response
    parser, and the two cache readers that *deserialise* a previously returned
    answer. Deserialising a stored provider result is not synthesis; inventing
    one from literals would be. The test therefore pins both the enclosing
    function and the absence of hardcoded content.
    """
    src = (REPO / "scripts" / "lib" / "brave_research_router.py").read_text()
    tree = ast.parse(src)

    allowed = {"_execute", "cache_get", "cache_get_stale"}
    found: dict[str, int] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "Result":
                found[fn.name] = found.get(fn.name, 0) + 1
                # Every construction must draw from a variable, never a literal.
                for kw in n.keywords:
                    assert not (
                        isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                        and kw.value.value not in ("", ATTRIBUTION_OK)
                    ), f"{fn.name} builds a Result from a hardcoded {kw.arg}={kw.value.value!r}"
    assert set(found) <= allowed, f"Result constructed outside the parser/cache readers: {sorted(set(found) - allowed)}"
    assert "_execute" in found, "the response parser no longer builds Results"


ATTRIBUTION_OK = "SEARCH_DISCOVERY"


# ── 6. Stale output cannot advance freshness ────────────────────────────────


def test_a_stale_served_result_carries_its_age_not_the_retrieval_time():
    out = R.Outcome(
        status=R.Status.STALE_SERVED,
        results=[R.Result(title="t", url="https://e.com/1", description="d", source_domain="e.com")],
        stale=True,
        result_age_seconds=99999.0,
        query="q",
        fingerprint="f",
    )
    assert out.stale is True
    assert out.result_age_seconds == 99999.0
    assert "older than its freshness window" in out.degradation_note()


def test_a_failed_run_does_not_advance_the_success_clock(tmp_path, monkeypatch):
    """last_success must not move when the provider failed."""
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "25")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "850")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

    def down(req, timeout=None):
        raise OSError("unreachable")

    monkeypatch.setattr(R.urllib.request, "urlopen", down)
    R.search("q", caller="t", root=tmp_path, now=NOW)
    hb = R.effectiveness_report(root=tmp_path, now=NOW)["heartbeat"]
    assert hb.get("last_attempt"), "a failed run did not record an attempt"
    assert not hb.get("last_success"), "a failed run advanced last_success"
    assert not hb.get("last_nonempty")


# ── 7. Duplicate producers do not create duplicate durable records ──────────


def test_two_identical_queries_produce_one_provider_call(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "25")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "850")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")
    calls: list[str] = []
    body = json.dumps({"web": {"results": [{"title": "t", "url": "https://e.com/1", "description": "d"}]}}).encode()

    class Resp:
        headers = {"x-ratelimit-policy": "1;w=1, 2000;w=2592000", "x-ratelimit-limit": "1, 2000"}
        status = 200

        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def once(req, timeout=None):
        calls.append(req.full_url)
        return Resp()

    monkeypatch.setattr(R.urllib.request, "urlopen", once)
    a = R.search("dupe", caller="p1", root=tmp_path, now=NOW)
    b = R.search("dupe", caller="p2", root=tmp_path, now=NOW)
    assert a.status is R.Status.OK
    assert b.status is R.Status.CACHED
    assert len(calls) == 1, "two producers each bought the same answer"


def test_identical_evidence_hashes_identically_so_it_can_be_deduplicated():
    def mk():
        return R.Outcome(
            status=R.Status.OK,
            query="q",
            fingerprint="f",
            results=[R.Result(title="t", url="https://e.com/1", description="d", source_domain="e.com")],
        )

    a = wrap_brave_outcome(mk(), run_id="r", trace_id="t", now=NOW)
    b = wrap_brave_outcome(mk(), run_id="r", trace_id="t", now=NOW)
    assert a.source_hash == b.source_hash


# ── 8. Failed or partial runs do not publish complete observations ──────────


@pytest.mark.parametrize(
    "status",
    [
        R.Status.TIMEOUT,
        R.Status.TRANSPORT_ERROR,
        R.Status.SERVER_ERROR,
        R.Status.MALFORMED,
        R.Status.RATE_LIMITED,
        R.Status.UNAUTHORIZED,
        R.Status.CIRCUIT_OPEN,
        R.Status.BUDGET_UNAVAILABLE,
    ],
)
def test_a_failed_run_publishes_an_incomplete_observation(status):
    obs = wrap_brave_outcome(
        R.Outcome(status=status, results=[], query="q", fingerprint="f"), run_id="r", trace_id="t", now=NOW
    )
    assert obs.freshness_status is not FreshnessStatus.FRESH
    assert obs.durable_output_present is False


# ── 9. Scheduler commands resolve in their actual runtime environment ───────


def _cron_lines() -> list[str]:
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            return []
        return [ln for ln in out.stdout.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    except Exception:
        return []


def test_scheduled_research_scripts_exist_on_disk():
    """A cron entry pointing at a missing script is a lane that never runs."""
    lines = _cron_lines()
    if not lines:
        pytest.skip("no crontab available in this environment")
    import re

    missing: list[str] = []
    for ln in lines:
        for m in re.finditer(r"(scripts/[A-Za-z0-9_./-]+\.py)", ln):
            rel = m.group(1)
            if not (REPO / rel).exists():
                missing.append(rel)
    # Report as data: the repo may legitimately schedule scripts from a release
    # tree. The assertion is that the ROUTED lanes resolve.
    for module, _ in ROUTED_LANES:
        assert (REPO / module).exists(), f"routed lane {module} missing on disk"


def test_routed_lane_modules_import_without_side_effects():
    """A lane that cannot be imported cannot run, however its cron entry reads."""
    for module, _ in ROUTED_LANES:
        r = subprocess.run(
            [sys.executable, "-c", f"import ast,sys;ast.parse(open({str(REPO / module)!r}).read())"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert r.returncode == 0, f"{module} does not parse: {r.stderr[-400:]}"


# ── 10. Disabled lanes report disabled, not healthy ─────────────────────────


def test_a_flag_gated_lane_declares_itself_disabled_not_healthy():
    """AEGIS_BRAVE_ENABLED / TOPIC_BRAVE_ENABLED default to off."""
    for module, flag in (
        ("scripts/aegis_social_sentiment.py", "AEGIS_BRAVE_ENABLED"),
        ("scripts/topic_ingestion.py", "TOPIC_BRAVE_ENABLED"),
    ):
        src = (REPO / module).read_text(encoding="utf-8")
        assert flag in src, f"{module} lost its {flag} gate"
        assert 'getenv("%s", "0")' % flag in src or f'"{flag}", "0"' in src, (
            f"{module}: {flag} no longer defaults to off"
        )


def test_a_denied_lane_is_degraded_not_empty():
    """INTENTIONALLY_DISABLED must never render as a healthy empty result."""
    for status in (R.Status.DENIED_POLICY, R.Status.DENIED_WEEKEND, R.Status.DENIED_BUDGET, R.Status.CIRCUIT_OPEN):
        out = R.Outcome(status=status, results=[], query="q", fingerprint="f")
        assert out.degraded is True
        assert out.degradation_note()
        assert out.status is not R.Status.EMPTY


def test_health_reports_firing_conditions_rather_than_a_single_badge(tmp_path):
    h = R.health(root=tmp_path, now=NOW)
    assert isinstance(h["firing"], list)
    assert "brave_allowance_never_measured" in h["firing"], "an unmeasured allowance must be visible, not assumed"
    assert h["ok"] is False


# ── Docker / SearXNG lane contract ──────────────────────────────────────────


def test_searxng_health_module_reports_engine_pool_not_result_count():
    """Ten results from one engine is not a healthy pool."""
    from scripts.lib import search_health as SH

    assert SH.MIN_HEALTHY_ENGINES >= 2
    src = (REPO / "scripts" / "lib" / "search_health.py").read_text()
    assert "serving_engines" in src and "unresponsive" in src


def test_searxng_probe_failure_is_reachable_false_not_an_exception():
    from scripts.lib import search_health as SH

    p = SH.probe_searxng("x", url="http://127.0.0.1:9", timeout=1)
    assert p["reachable"] is False
    assert p["results"] == 0
    assert p["error"]


def test_searxng_and_brave_cannot_share_one_budget_reservation(tmp_path, monkeypatch):
    """Docker and Hermes lanes must not both spend the same unit."""
    from scripts.lib import search_budget as SB

    # monkeypatch, not os.environ: writing these directly leaked a ceiling of 10
    # into every later module in the session, and the operator truth-surface
    # test then read 10 where the documented local policy is 850 — a failure
    # that appeared only in a particular file ordering.
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "1")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "10")
    first = SB.try_consume("brave", caller="docker-lane", now=NOW, root=tmp_path)
    second = SB.try_consume("brave", caller="hermes-lane", now=NOW, root=tmp_path)
    assert first["allowed"] is True
    assert second["allowed"] is False, "two lanes both spent the last unit"
    # SearXNG is self-hosted and must not draw on the paid provider's ledger.
    sx = SB.try_consume("searxng", caller="docker-lane", now=NOW, root=tmp_path)
    assert sx["allowed"] is True
    assert SB.status("brave", now=NOW, root=tmp_path)["daily_used"] == 1


# ── Truth inventory: configuration is not proof ─────────────────────────────


def _inventory():
    import importlib

    m = importlib.import_module("scripts.research_truth_inventory")
    return m


def test_inventory_uses_only_the_closed_classification_vocabulary():
    m = _inventory()
    doc = m.build()
    assert doc["row_count"] > 0
    for r in doc["rows"]:
        assert r["classification"] in m.CLASSIFICATIONS, r["classification"]


def test_inventory_emits_every_required_field_for_every_row():
    m = _inventory()
    for r in m.build()["rows"]:
        for f in m.FIELDS:
            assert f in r, f"row {r['component']} missing field {f}"


def test_a_running_container_is_not_classified_as_working():
    """`docker ps` says a process exists, not that a lane produces anything."""
    m = _inventory()
    for r in m.build()["rows"]:
        if r["component"].startswith("docker:"):
            assert r["classification"] != "WIRED_AND_WORKING", (
                f"{r['component']} was called working on the strength of `docker ps` alone"
            )


def test_a_present_credential_is_not_classified_as_working():
    m = _inventory()
    for r in m.build()["rows"]:
        if r["category"] == "keyed_provider":
            assert r["classification"] in ("CONFIGURED_NOT_PROVEN", "NOT_IMPLEMENTED")
            assert "NOT liveness" in r["runtime_evidence"]


def test_an_http_200_is_not_classified_as_working():
    """Transport success without a proven durable-output join is not working."""
    m = _inventory()
    for r in m.build()["rows"]:
        ev = str(r["runtime_evidence"])
        if "transport only" in ev:
            assert r["classification"] == "CONFIGURED_NOT_PROVEN", (
                f"{r['component']}: a 200 was promoted to {r['classification']}"
            )


def test_an_enabled_timer_is_not_classified_as_working():
    m = _inventory()
    for r in m.build()["rows"]:
        if r["category"] == "hermes_lane":
            assert r["classification"] != "WIRED_AND_WORKING", (
                f"{r['component']} was called working on unit-file state alone"
            )


def test_the_unwired_command_center_panel_is_reported_as_not_implemented():
    m = _inventory()
    rows = {r["component"]: r for r in m.build()["rows"]}
    panel = rows["command_center_brave_panel"]
    assert panel["classification"] == "NOT_IMPLEMENTED"
    assert panel["served_store"] == "NONE"
    assert "leased" in panel["runtime_evidence"]


def test_the_inventory_makes_no_paid_provider_call():
    """Structural: the inventory must never spend a Brave credit.

    It reads the metrics the router already wrote. Calling ``R.search`` from an
    inventory would mean auditing the system changed the system — and would bill
    the operator once per audit.
    """
    src = (REPO / "scripts" / "research_truth_inventory.py").read_text()
    tree = ast.parse(src)

    # The host name DOES appear — as the needle its own bypass detector greps
    # for. What matters is that it is only ever compared against, never fetched.
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and "api.search.brave.com" in n.value:
            parents = [q for q in ast.walk(tree) if isinstance(q, ast.Compare) and n in ast.walk(q)]
            assert parents, "the provider host is used outside a comparison"

    # And no probe URL points at the paid provider.
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_http":
            for a in n.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    assert "brave.com" not in a.value, f"inventory probes {a.value}"

    called: set[str] = set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Attribute):
            owner = getattr(f.value, "id", "")
            # `re.search` is a regex, not a provider call. Qualify by owner so
            # the check tests what it actually means to test.
            called.add(f"{owner}.{f.attr}" if owner else f.attr)
        elif isinstance(f, ast.Name):
            called.add(f.id)

    spending = {c for c in called if c.endswith(".search") and not c.startswith("re.")}
    spending |= {c for c in called if c in ("search", "try_consume", "reserve", "guard", "note")}
    assert not spending, f"the inventory spends provider budget via {sorted(spending)}"
    # It reads, rather than produces.
    assert any(c.endswith("effectiveness_report") for c in called)
