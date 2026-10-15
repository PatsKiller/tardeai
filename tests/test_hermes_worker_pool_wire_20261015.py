"""Hermes research worker pool — real lane runners + fail closed on zero output (2026-10-15).

From 2026-07-05 to 2026-10-15 three enabled lanes (tax_retirement, system_ops,
custom_domain) reported ``skipped: no_runner`` on every hourly run and the pool
exited 0; the n8n shadow dry run was green 89 times in a row because the
preview printed one line and returned. These tests pin:

* every enabled lane in the committed yaml has a registered runner (the regression);
* the expected-output rule: config validation, lane outcomes, failures, exit 3;
* exit 0 with every lane no_runner is impossible (CLI end to end);
* the durable output clock (last_output_at / tracking_since) and that a dry run writes nothing;
* the three new runners on fakes (cited rows only, stale/unreadable source raises,
  custom-domain denylist + blocked source types);
* the dry-run plan exits 3 on no_runner / overdue and stays offline;
* the n8n executor dry-run path: RUN_DONE when healthy, RUN_FAILED when a lane has no runner;
* the fabric rows: allowlist dry run only, registry stage shadow, effect key, health contract checks.

Hermetic: no DB (db_adapter._execute and coverage._rows are faked), no LLM, tmp_path
state/locks/receipts. .venv/bin/python -m pytest tests/test_hermes_worker_pool_wire_20261015.py -q
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import db_adapter  # noqa: E402
from lib.hermes_discovery import coverage, coverage_lanes, inbox, worker_pool  # noqa: E402

# register every lane runner BEFORE the autouse fixture snapshots the registry
RUNNER_IMPORT_ERRORS = worker_pool.load_runner_modules()

NEW_LANES = ("tax_retirement", "system_ops", "custom_domain")
LANE = "hermes-research-worker-pool"


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    worker_pool._reset_lanes_cache()
    monkeypatch.setattr(worker_pool, "LOCK_DIR", tmp_path / "locks")
    monkeypatch.setattr(worker_pool, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "root"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "root"))
    saved = dict(worker_pool._RUNNERS)
    yield
    worker_pool._RUNNERS.clear()
    worker_pool._RUNNERS.update(saved)
    worker_pool._reset_lanes_cache()


@pytest.fixture
def no_db(monkeypatch):
    monkeypatch.setattr(db_adapter, "_execute",
                        lambda sql, params=None, fetch=None: [] if fetch else None)


@pytest.fixture
def fake_inbox(monkeypatch):
    """Live-mode upserts land in a list; audit rows are recorded, nothing touches a DB."""
    import hermes_discovery_ingestors as ing
    written, audits = [], []

    def upsert(*, actor, **payload):
        written.append((actor, payload))
        return {"id": len(written), "status": "NEW", "seen_count": 1}

    monkeypatch.setattr(ing.inbox, "upsert_candidate", upsert)
    monkeypatch.setattr(inbox, "_audit", lambda *a, **k: audits.append(a))
    return written, audits


_YAML = """
version: 1
defaults:
  enabled: true
  cadence_minutes: 60
  max_candidates_per_run: 5
  max_llm_reviews_per_run: 2
  timeout_seconds: 5
  allowed_domains: []
  blocked_domains: []
  sensitive_domain: false
  requires_citations: false
  requires_operator_review: true
  cloud_allowed: false
  local_llm_allowed: false
  promotion_allowed: false
  promotion_requires_operator: true
  do_no_harm_policy: respect
lanes:
{body}
"""


def _lanes(tmp_path, body: str) -> Path:
    p = tmp_path / "lanes.yaml"
    p.write_text(_YAML.format(body=body), encoding="utf-8")
    return p


def _payload(label="t", domain="macro", url="https://example.com/a"):
    return dict(candidate_type="TOPIC_CANDIDATE", label=label, summary="s",
                evidence=[{"source_domain": "x", "url": url, "note": "n"}],
                meta={"research_domain": domain})


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


# ── the regression: no enabled lane without a runner ─────────────────────────

def test_every_enabled_committed_lane_has_a_registered_runner():
    assert RUNNER_IMPORT_ERRORS == {} and worker_pool.load_runner_modules() == {}
    lanes = worker_pool.load_lanes()
    runners = set(worker_pool.registered_lanes())
    enabled = {k for k, v in lanes.items() if v["enabled"]}
    assert enabled - runners == set()
    assert set(NEW_LANES) <= runners
    for lane_id, lane in lanes.items():
        if lane["enabled"]:
            assert lane["expected_output_hours"] is not None
            if lane["expected_output_hours"] == 0:
                assert lane["zero_output_reason"]
        else:
            assert lane["disabled_reason"]


def test_committed_yaml_declares_expectation_per_lane_not_by_default():
    import yaml
    data = yaml.safe_load((ROOT / "config/hermes_research_worker_lanes.yaml").read_text())
    assert "expected_output_hours" not in (data.get("defaults") or {})
    for lane_id, spec in data["lanes"].items():
        assert "expected_output_hours" in spec, lane_id
    assert data["lanes"]["system_ops"]["expected_output_hours"] == 0


def test_runner_module_list_is_the_cli_source():
    cli = (ROOT / "scripts/hermes_research_worker_pool.py").read_text()
    assert "_RUNNER_MODULES" not in cli and "load_runner_modules" in cli
    assert "coverage_lanes" in worker_pool.RUNNER_MODULES


# ── config validation: the expected-output rule fails closed ─────────────────

@pytest.mark.parametrize("body,match", [
    ("  l1: {}", "expected_output_hours is required"),
    ("  l1:\n    expected_output_hours: 0", "zero_output_reason"),
    ("  l1:\n    expected_output_hours: -1", ">= 0"),
    ("  l1:\n    expected_output_hours: soon", "integer"),
    ("  l1:\n    cadence_minutes: 600\n    expected_output_hours: 2", "shorter than one cadence"),
    ("  l1:\n    enabled: false", "disabled_reason"),
])
def test_expected_output_rule_validation(tmp_path, body, match):
    with pytest.raises(worker_pool.LaneConfigError, match=match):
        worker_pool.load_lanes(_lanes(tmp_path, body))


def test_disabled_lane_with_reason_loads_without_expectation(tmp_path):
    lanes = worker_pool.load_lanes(_lanes(
        tmp_path, "  dormant:\n    enabled: false\n    disabled_reason: no source today"))
    assert lanes["dormant"]["disabled_reason"] == "no source today"
    assert lanes["dormant"]["expected_output_hours"] is None


# ── lane_outcome (pure) ──────────────────────────────────────────────────────

def _lane(**kw):
    base = {"lane_id": "l1", "enabled": True, "expected_output_hours": 24,
            "zero_output_reason": None, "disabled_reason": None}
    base.update(kw)
    return base


@pytest.mark.parametrize("result,entry,outcome,ok", [
    ({"skipped": "no_runner"}, {}, "no_runner", False),
    ({"error": "runner failed: boom"}, {}, "runner_error", False),
    ({"scanned": 2}, {}, "produced", True),
    ({"skipped": "paused"}, {}, "paused", True),
    ({"scanned": 0}, {"last_output_at": _iso(1)}, "empty_within_window", True),
    ({"scanned": 0}, {"last_output_at": _iso(30)}, "output_overdue", False),
    ({"skipped": "cadence"}, {"last_output_at": _iso(30)}, "output_overdue", False),
    ({"skipped": "cadence"}, {"last_output_at": _iso(2)}, "not_due", True),
    ({"scanned": 0}, {"tracking_since": _iso(30)}, "output_overdue", False),
    ({"scanned": 0}, {"tracking_since": _iso(3)}, "empty_within_window", True),
    ({"scanned": 0}, {}, "untracked", True),
])
def test_lane_outcome_table(result, entry, outcome, ok):
    out = worker_pool.lane_outcome(_lane(), {"lane": "l1", **result}, entry)
    assert (out["outcome"], out["ok"]) == (outcome, ok)


def test_lane_outcome_disabled_and_zero_ok():
    off = worker_pool.lane_outcome(_lane(enabled=False, disabled_reason="why"),
                                   {"lane": "l1", "skipped": "disabled"}, {})
    assert off["outcome"] == "disabled" and off["ok"] and off["reason"] == "why"
    zero = worker_pool.lane_outcome(_lane(expected_output_hours=0, zero_output_reason="r"),
                                    {"lane": "l1", "scanned": 0}, {})
    assert zero["outcome"] == "zero_output_ok" and zero["ok"]
    # zero-ok never excuses a missing runner or an error
    assert not worker_pool.lane_outcome(_lane(expected_output_hours=0, zero_output_reason="r"),
                                        {"lane": "l1", "skipped": "no_runner"}, {})["ok"]


# ── run_pool: failures + durable clock ───────────────────────────────────────

def test_pool_with_every_lane_no_runner_is_not_ok(no_db, tmp_path):
    path = _lanes(tmp_path, "  a:\n    expected_output_hours: 24\n  b:\n    expected_output_hours: 24")
    report = worker_pool.run_pool(dry_run=True, lanes_path=path, lock_dir=tmp_path / "l",
                                  state_path=tmp_path / "s.json")
    assert report["ok"] is False
    assert {(f["lane"], f["outcome"]) for f in report["failures"]} == {("a", "no_runner"), ("b", "no_runner")}
    assert not (tmp_path / "s.json").exists()  # dry evaluation writes nothing


def test_live_run_advances_last_output_only_when_payloads(no_db, fake_inbox, tmp_path):
    path = _lanes(tmp_path, "  a:\n    expected_output_hours: 24\n  b:\n    expected_output_hours: 24")
    worker_pool.register_lane_runner("a", lambda cfg, dry_run: [_payload("x")], replace=True)
    worker_pool.register_lane_runner("b", lambda cfg, dry_run: [], replace=True)
    state = tmp_path / "s.json"
    report = worker_pool.run_pool(lanes_path=path, lock_dir=tmp_path / "l", state_path=state)
    assert report["ok"] is True, report["failures"]
    assert report["lane_outcomes"]["a"]["outcome"] == "produced"
    assert report["lane_outcomes"]["b"]["outcome"] == "empty_within_window"
    lanes = json.loads(state.read_text())["lanes"]
    assert lanes["a"]["last_output_at"] and lanes["a"]["tracking_since"]
    assert "last_output_at" not in lanes["b"] and lanes["b"]["tracking_since"]
    written, audits = fake_inbox
    assert [w[0] for w in written] == ["worker:a"] and len(audits) == 2


def test_empty_lane_past_window_fails_even_when_cadence_skipped(no_db, fake_inbox, tmp_path):
    path = _lanes(tmp_path, "  a:\n    expected_output_hours: 24")
    worker_pool.register_lane_runner("a", lambda cfg, dry_run: [], replace=True)
    state = tmp_path / "s.json"
    state.write_text(json.dumps({"lanes": {"a": {"last_run_at": _iso(0.1),
                                                 "tracking_since": _iso(500),
                                                 "last_output_at": _iso(48)}}}))
    report = worker_pool.run_pool(lanes_path=path, lock_dir=tmp_path / "l", state_path=state)
    assert report["lanes"]["a"]["skipped"] == "cadence"
    assert report["failures"] == [{"lane": "a", "outcome": "output_overdue",
                                   "reason": report["lane_outcomes"]["a"]["reason"]}]
    assert "48.0 h > expected_output_hours 24" in report["lane_outcomes"]["a"]["reason"]


def test_first_live_evaluation_starts_the_clock_for_a_lane_that_never_ran(no_db, tmp_path):
    path = _lanes(tmp_path, "  a:\n    expected_output_hours: 24")
    worker_pool.register_lane_runner("a", lambda cfg, dry_run: [], replace=True)
    state = tmp_path / "s.json"
    state.write_text(json.dumps({"lanes": {"a": {"last_run_at": _iso(0.1)}}}))  # pre-2026-10-15 shape
    report = worker_pool.run_pool(lanes_path=path, lock_dir=tmp_path / "l", state_path=state)
    assert report["ok"] and report["lane_outcomes"]["a"]["outcome"] == "not_due"
    assert json.loads(state.read_text())["lanes"]["a"]["tracking_since"]


def test_runner_error_is_a_failure(no_db, tmp_path):
    path = _lanes(tmp_path, "  a:\n    expected_output_hours: 24")

    def boom(cfg, *, dry_run):
        raise RuntimeError("source unreadable")

    worker_pool.register_lane_runner("a", boom, replace=True)
    report = worker_pool.run_pool(dry_run=True, lanes_path=path, lock_dir=tmp_path / "l",
                                  state_path=tmp_path / "s.json")
    assert report["failures"][0]["outcome"] == "runner_error"
    assert "source unreadable" in report["failures"][0]["reason"]


def test_all_lanes_disabled_is_a_failure(no_db, tmp_path):
    path = _lanes(tmp_path, "  a:\n    enabled: false\n    disabled_reason: r")
    report = worker_pool.run_pool(dry_run=True, lanes_path=path, lock_dir=tmp_path / "l",
                                  state_path=tmp_path / "s.json")
    assert report["lane_outcomes"]["a"]["ok"] is True
    assert report["failures"][-1]["outcome"] == "no_enabled_lanes" and report["ok"] is False


def test_pause_is_reported_not_failed(no_db, tmp_path):
    cfg = json.loads((ROOT / "config/hermes_discovery_schedule.json").read_text())
    cfg["paused"] = True
    sched = tmp_path / "sched.json"
    sched.write_text(json.dumps(cfg))
    path = _lanes(tmp_path, "  a:\n    expected_output_hours: 24")
    report = worker_pool.run_pool(dry_run=True, lanes_path=path, config_path=sched,
                                  lock_dir=tmp_path / "l", state_path=tmp_path / "s.json")
    assert report["lane_outcomes"]["a"]["outcome"] == "paused" and report["ok"] is True


# ── CLI: exit 0 with every lane no_runner is impossible ─────────────────────

def _load_cli():
    import importlib.util
    spec = importlib.util.spec_from_file_location("wire_cli", ROOT / "scripts/hermes_research_worker_pool.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _receipt(tmp_path):
    return json.loads((tmp_path / "root/data/runtime" / f"{LANE}_last.json").read_text())


def test_cli_all_no_runner_exits_3_and_fails_receipt(no_db, monkeypatch, tmp_path):
    path = _lanes(tmp_path, "  a:\n    expected_output_hours: 24\n  b:\n    expected_output_hours: 24")
    monkeypatch.setattr(worker_pool, "LANES_PATH", path)
    monkeypatch.setattr(worker_pool, "load_runner_modules", lambda: {})
    worker_pool._RUNNERS.clear()
    mod = _load_cli()
    assert mod.main(["--run", "--json"]) == 3
    r = _receipt(tmp_path)
    assert r["status"] == "failed" and r["exit"] == 3 and r["ok_at"] is None
    assert r["error"] == "lane_failures"
    assert {f["outcome"] for f in r["summary"]["failures"]} == {"no_runner"}


def test_cli_healthy_pool_exits_0_and_advances_ok_at(no_db, fake_inbox, monkeypatch, tmp_path):
    path = _lanes(tmp_path, "  a:\n    expected_output_hours: 24")
    monkeypatch.setattr(worker_pool, "LANES_PATH", path)
    monkeypatch.setattr(worker_pool, "load_runner_modules", lambda: {})
    worker_pool._RUNNERS.clear()
    worker_pool.register_lane_runner("a", lambda cfg, dry_run: [_payload()], replace=True)
    mod = _load_cli()
    assert mod.main(["--run", "--json"]) == 0
    r = _receipt(tmp_path)
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["lane_outcomes"] == {"a": "produced"}
    # next hour: cadence-skipped, clock inside the window -> still ok
    assert mod.main(["--run", "--json"]) == 0
    assert _receipt(tmp_path)["summary"]["lane_outcomes"] == {"a": "not_due"}


def test_cli_runner_import_failure_is_loud(no_db, monkeypatch, tmp_path):
    path = _lanes(tmp_path, "  a:\n    expected_output_hours: 24")
    monkeypatch.setattr(worker_pool, "LANES_PATH", path)
    monkeypatch.setattr(worker_pool, "load_runner_modules", lambda: {"m": "ImportError: x"})
    worker_pool._RUNNERS.clear()
    mod = _load_cli()
    assert mod.main(["--run"]) == 3


# ── dry-run plan ─────────────────────────────────────────────────────────────

def test_dry_run_plan_exit_codes_and_writes_nothing(monkeypatch, tmp_path, capsys):
    path = _lanes(tmp_path, "  a:\n    expected_output_hours: 24\n  b:\n    expected_output_hours: 24")
    monkeypatch.setattr(worker_pool, "LANES_PATH", path)
    monkeypatch.setattr(worker_pool, "load_runner_modules", lambda: {})
    worker_pool._RUNNERS.clear()
    worker_pool.register_lane_runner("a", lambda cfg, dry_run: [], replace=True)
    mod = _load_cli()
    mod._load_dependencies = lambda: pytest.fail("preview loaded live dependencies")
    before = sorted(p.name for p in tmp_path.rglob("*"))
    assert mod.main(["--run", "--json", "--dry-run"]) == 3  # b has no runner
    out = capsys.readouterr().out
    assert out.startswith("DRY-RUN hermes-research-worker-pool: would")
    plan = json.loads(out.split("\n", 1)[1].rsplit("DRY-RUN-SUMMARY", 1)[0])
    assert plan["plan"]["b"]["status"] == "no_runner" and plan["plan"]["a"]["status"] == "untracked"
    worker_pool.register_lane_runner("b", lambda cfg, dry_run: [], replace=True)
    assert mod.main(["--dry-run"]) == 0
    worker_pool.STATE_PATH.write_text(json.dumps({"lanes": {"a": {"last_output_at": _iso(100)}}}))
    assert mod.main(["--dry-run"]) == 3  # overdue clock caught by the preview
    assert sorted(p.name for p in tmp_path.rglob("*")) == sorted(before + ["state.json"])


def test_committed_dry_run_plan_is_clean(monkeypatch, tmp_path, capsys):
    mod = _load_cli()
    assert mod.main(["--run", "--json", "--dry-run"]) == 0
    plan = json.loads(capsys.readouterr().out.split("\n", 1)[1].rsplit("DRY-RUN-SUMMARY", 1)[0])
    assert set(plan["plan"]) == set(worker_pool.LANE_IDS)
    assert all(row["runner_registered"] for row in plan["plan"].values())
    assert plan["runner_import_errors"] == {}


# ── the three new runners (fakes) ────────────────────────────────────────────

class FakeRows:
    """Stands in for coverage._rows: answers by table name, records strictness."""

    def __init__(self, news=(), hri=(), health=(), health_last=None, fail=False):
        self.news, self.hri, self.health = list(news), list(hri), list(health)
        self.health_last, self.fail, self.calls = health_last, fail, []

    def __call__(self, sql, params=None, *, strict=False):
        self.calls.append((sql.split("FROM")[1].split()[0] if "FROM" in sql else sql, strict))
        if self.fail and strict:
            raise RuntimeError("db down")
        if "max(updated_at)" in sql:
            return [{"last": self.health_last}]
        if "FROM news_articles" in sql:
            return list(self.news)
        if "FROM hermes_research_intelligence" in sql:
            return list(self.hri)
        if "system_health_checks" in sql:
            return list(self.health)
        return []


def _news(title, url="https://news.example/a", source="yahoo_rss"):
    return {"text_a": title, "text_b": "", "source": source, "source_url": url}


def test_tax_retirement_runner_keeps_cited_rows_only(monkeypatch):
    rows = FakeRows(news=[_news("Roth conversion rules"), _news("Roth conversion pacing"),
                          _news("Medicare premiums rise", url=None), _news("Medicare IRMAA", url=None),
                          _news("Social Security COLA"), _news("social security trust fund")])
    monkeypatch.setattr(coverage, "_rows", rows)
    lanes = worker_pool.load_lanes()
    out = coverage_lanes.tax_retirement_runner(dict(lanes["tax_retirement"]), dry_run=True)
    labels = {p["label"] for p in out}
    assert "Taxes research: roth conversion" in labels
    assert "Retirement research: social security" in labels
    assert "Retirement research: medicare" not in labels  # no URL evidence → dropped
    assert all(e["url"].startswith("https://") for p in out for e in p["evidence"])
    assert {p["meta"]["research_domain"] for p in out} <= {"taxes", "retirement"}
    assert rows.calls and all(strict for _, strict in rows.calls)


def test_system_ops_runner_raises_on_stale_or_empty_source(monkeypatch):
    lanes = worker_pool.load_lanes()
    cfg = dict(lanes["system_ops"])
    monkeypatch.setattr(coverage, "_rows", FakeRows(health_last=None))
    with pytest.raises(RuntimeError, match="empty"):
        coverage_lanes.system_ops_runner(cfg, dry_run=True)
    stale = datetime.now(timezone.utc) - timedelta(hours=72)
    monkeypatch.setattr(coverage, "_rows", FakeRows(health_last=stale))
    with pytest.raises(RuntimeError, match="stale"):
        coverage_lanes.system_ops_runner(cfg, dry_run=True)
    monkeypatch.setattr(coverage, "_rows", FakeRows(fail=True))
    with pytest.raises(RuntimeError, match="db down"):
        coverage_lanes.system_ops_runner(cfg, dry_run=True)


def test_system_ops_runner_fresh_source(monkeypatch):
    cfg = dict(worker_pool.load_lanes()["system_ops"])
    fresh = datetime.now(timezone.utc) - timedelta(hours=1)
    monkeypatch.setattr(coverage, "_rows", FakeRows(health_last=fresh))
    assert coverage_lanes.system_ops_runner(cfg, dry_run=True) == []  # healthy platform, zero_output_ok
    failing = [{"component": "alex_daily", "check_type": "cron", "status": "MISSING",
                "severity": "WARN", "failure_count": 3, "last_error": None, "updated_at": fresh}]
    monkeypatch.setattr(coverage, "_rows", FakeRows(health=failing, health_last=fresh))
    out = coverage_lanes.system_ops_runner(cfg, dry_run=True)
    assert [p["label"] for p in out] == ["System health: alex_daily MISSING"]
    assert out[0]["meta"]["research_domain"] == "system_ops"


def test_custom_domain_runner_denylist_and_blocked_sources(monkeypatch):
    rows = FakeRows(news=[
        _news("clinical trial results"), _news("new clinical trial"),
        _news("clinical trial miracle cure"),                      # denylist (health_general)
        _news("clinical trial chatter", source="google_news:Stocktwits"),  # blocked: social
        _news("liability ruling"), _news("liability case"),
    ])
    monkeypatch.setattr(coverage, "_rows", rows)
    cfg = dict(worker_pool.load_lanes()["custom_domain"])
    out = coverage_lanes.custom_domain_runner(cfg, dry_run=True)
    by_label = {p["label"]: p for p in out}
    trial = by_label["Health General research: clinical trial"]
    assert trial["meta"]["match_count"] == 2
    assert trial["meta"]["research_domain"] == "health_general"
    assert trial["meta"]["custom_domain"] == "health_general"
    assert "Legal General research: liability" in by_label
    assert {p["meta"]["research_domain"] for p in out} <= set(cfg["allowed_domains"])


def test_custom_domain_runner_without_admitted_domain_raises(monkeypatch):
    monkeypatch.setattr(coverage, "_rows", FakeRows())
    cfg = dict(worker_pool.load_lanes()["custom_domain"], allowed_domains=["nothing_custom"])
    with pytest.raises(RuntimeError, match="no custom research domain"):
        coverage_lanes.custom_domain_runner(cfg, dry_run=True)


def test_new_runners_go_through_pool_gates_dry(monkeypatch, no_db, tmp_path):
    """End to end through run_pool (dry): the citation gate and lane fences apply."""
    fresh = datetime.now(timezone.utc) - timedelta(hours=1)
    monkeypatch.setattr(coverage, "_rows", FakeRows(
        news=[_news("Roth conversion rules"), _news("Roth conversion pacing")], health_last=fresh))
    report = worker_pool.run_pool(list(NEW_LANES), dry_run=True, lock_dir=tmp_path / "l",
                                  state_path=tmp_path / "s.json")
    assert report["lanes"]["tax_retirement"]["scanned"] >= 1
    assert report["lane_outcomes"]["system_ops"]["outcome"] == "zero_output_ok"
    assert all(o["outcome"] != "no_runner" for o in report["lane_outcomes"].values())


def test_new_module_is_advisory_only():
    src = (ROOT / "scripts/lib/hermes_discovery/coverage_lanes.py").read_text()
    for forbidden in ("schwab", "alpaca", "brokers", "place_order", "requests", "urllib",
                      "local_llm", "cloud_review", "llm_review", "send_telegram"):
        assert f"import {forbidden}" not in src and f"from {forbidden}" not in src
    assert "upsert_candidate(" not in src  # the pool owns every write


# ── n8n executor dry-run path ────────────────────────────────────────────────

def _executor_entry(tmp_path):
    allow = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())
    entry = next(e for e in allow["lanes"] if e["lane_id"] == LANE)
    return dict(entry, lock=str(tmp_path / "pool.lock"))


def _execute(tmp_path, extra_env):
    from scripts import n8n_run_executor as X
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DB_", "PG"))}
    env.update({"TRADEAI_VENV_PYTHON": sys.executable, "TRADE_AI_CI": "1",
                "HERMES_WORKER_STATE_JSON": str(tmp_path / "state.json"),
                "HERMES_WORKER_LOCK_DIR": str(tmp_path / "locks"), **extra_env})
    row = {"run_id": "d:test", "lane_id": LANE, "mode": "dry_run"}
    state_root = tmp_path / "root"
    (state_root / "data/runtime").mkdir(parents=True, exist_ok=True)
    return X.execute(row, _executor_entry(tmp_path), env=env, state_root=state_root, code_root=ROOT)


def test_executor_dry_run_path_done_when_clean(tmp_path):
    receipt = _execute(tmp_path, {})
    assert receipt["state"] == "RUN_DONE", receipt
    assert receipt["exit_code"] == 0 and receipt["mode"] == "dry_run"
    assert receipt["argv"][-1] == "--dry-run"
    assert receipt["output_signal_mtime_before"] == receipt["output_signal_mtime_after"] is None
    assert "DRY-RUN-SUMMARY {\"ok\": true" in (receipt["stdout_tail"] or "")
    assert not (tmp_path / "state.json").exists()


def test_executor_dry_run_path_fails_on_no_runner_lane(tmp_path):
    lanes = _lanes(tmp_path, "  orphan:\n    expected_output_hours: 24")
    receipt = _execute(tmp_path, {"HERMES_WORKER_LANES_YAML": str(lanes)})
    assert receipt["state"] == "RUN_FAILED", receipt
    assert receipt["exit_code"] == 3
    assert '"outcome": "no_runner"' in (receipt["stdout_tail"] or "")


# ── fabric rows (AGENTS.md §23.21 / §23.23) ──────────────────────────────────

def test_fabric_rows_shadow_dry_run_only_with_zero_output_contract():
    allow = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())
    entry = next(e for e in allow["lanes"] if e["lane_id"] == LANE)
    assert entry["live_arg"] is None and entry["dry_run_arg"] == ["--dry-run"]
    reg = json.loads((ROOT / "config/lane_registry.json").read_text())
    row = next(r for r in reg["lanes"] if r["lane_id"] == LANE)
    assert row["scheduler"]["stage"] == "shadow" and row["dispatch"]["mode"] == "dry_run"
    fx = json.loads((ROOT / "config/n8n_effect_keys.json").read_text())["lanes"][LANE]
    assert fx["effects"] == ["append"] and fx["cron_claim"] is False and fx["n8n_claim"] is False
    contracts = json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]
    c = next(x for x in contracts if x["id"] == LANE)
    assert c["status"] == "REVIEWED" and c["stage"] == "shadow"
    checks = {x["check"] for x in c["healthy"] + c["failed"]}
    assert {"lane_outcomes_ok", "dry_run_plan_clean", "lane_zero_output"} <= checks
    zero = next(x for x in c["failed"] if x["check"] == "lane_zero_output")["text"]
    assert "no_runner" in zero and "expected_output_hours" in zero and "exits 3" in zero
    assert c["review"]["amendments"][0]["on"] == "2026-10-15"


def test_packet_present():
    packet = ROOT / "docs/ops/packets/hermes-worker-pool-wire-20261015"
    names = {p.name for p in packet.iterdir()}
    assert {"README.md", "01_dry_run.sh", "02_live_n8n_run.sh", "03_parity.py", "09_rollback.sh"} <= names
    for sh in packet.glob("*.sh"):
        res = subprocess.run(["bash", "-n", str(sh)], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
