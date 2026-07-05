#!/usr/bin/env python3
"""White-Space Discovery Stage 1 — worker pool: lanes, locks, caps, timeouts.

Covers: lane yaml load + hard-rule fail-closed validation, the runner
registration API, per-lane run caps / domain fences / citation gates,
flock-style lock exclusion, wall-clock timeout, the 4-thread pool bound,
dry-run writing nothing (no candidates, no audit, no state), do-no-harm
pause propagation, and the no-broker-imports guarantee.

    .venv/bin/python -m pytest tests/test_hermes_research_worker_pool.py -q
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import db_adapter  # noqa: E402
from lib.hermes_discovery import inbox, worker_pool  # noqa: E402


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    """Fresh lane cache + throwaway lock/state dirs for every test."""
    worker_pool._reset_lanes_cache()
    monkeypatch.setattr(worker_pool, "LOCK_DIR", tmp_path / "locks")
    monkeypatch.setattr(worker_pool, "STATE_PATH", tmp_path / "state.json")
    saved = dict(worker_pool._RUNNERS)
    yield
    worker_pool._RUNNERS.clear()
    worker_pool._RUNNERS.update(saved)
    worker_pool._reset_lanes_cache()


@pytest.fixture
def no_db(monkeypatch):
    monkeypatch.setattr(db_adapter, "_execute",
                        lambda sql, params=None, fetch=None: [] if fetch else None)


def _payload(label, domain="macro", with_url=False):
    ev = [{"source_domain": "x", "url": "https://example.com/a",
           "note": "n"}] if with_url else [{"note": "no citation"}]
    return dict(candidate_type="TOPIC_CANDIDATE", label=label, summary="s",
                evidence=ev, meta={"research_domain": domain})


# ── lane config: load + hard rules ───────────────────────────────────────────

def test_all_nine_lanes_load_with_hard_rules():
    lanes = worker_pool.load_lanes()
    assert set(lanes) == set(worker_pool.LANE_IDS)
    for lane_id, lane in lanes.items():
        assert lane["promotion_allowed"] is False
        assert lane["promotion_requires_operator"] is True
        assert lane["requires_operator_review"] is True
        assert lane["do_no_harm_policy"] == "respect"
        assert lane["cadence_minutes"] > 0
        assert lane["max_candidates_per_run"] > 0
        assert lane["max_llm_reviews_per_run"] > 0
    for sensitive in ("legal_domain", "tax_retirement"):
        assert lanes[sensitive]["sensitive_domain"] is True
        assert lanes[sensitive]["requires_citations"] is True
        assert lanes[sensitive]["cloud_allowed"] is False


_LANE_YAML = """
version: 1
defaults:
  enabled: true
  cadence_minutes: 60
  max_candidates_per_run: 5
  max_llm_reviews_per_run: 2
  timeout_seconds: {timeout}
  allowed_domains: []
  blocked_domains: []
  sensitive_domain: false
  requires_citations: false
  requires_operator_review: true
  cloud_allowed: false
  local_llm_allowed: true
  promotion_allowed: false
  promotion_requires_operator: true
  do_no_harm_policy: respect
lanes:
  {body}
"""


def _lanes_file(tmp_path, body: str, timeout: int = 5) -> Path:
    p = tmp_path / "lanes.yaml"
    p.write_text(_LANE_YAML.format(body=body, timeout=timeout), encoding="utf-8")
    return p


def test_promotion_allowed_true_fails_closed(tmp_path):
    p = _lanes_file(tmp_path, "sneaky:\n    promotion_allowed: true")
    with pytest.raises(worker_pool.LaneConfigError, match="promotion_allowed"):
        worker_pool.load_lanes(p)


def test_do_no_harm_bypass_fails_closed(tmp_path):
    p = _lanes_file(tmp_path, "sneaky:\n    do_no_harm_policy: ignore")
    with pytest.raises(worker_pool.LaneConfigError, match="do_no_harm"):
        worker_pool.load_lanes(p)


def test_operator_review_off_fails_closed(tmp_path):
    p = _lanes_file(tmp_path, "sneaky:\n    requires_operator_review: false")
    with pytest.raises(worker_pool.LaneConfigError):
        worker_pool.load_lanes(p)


def test_missing_or_broken_yaml_fails_closed(tmp_path):
    with pytest.raises(worker_pool.LaneConfigError):
        worker_pool.load_lanes(tmp_path / "absent.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("lanes: []\n")
    with pytest.raises(worker_pool.LaneConfigError):
        worker_pool.load_lanes(bad)


def test_nonpositive_cap_fails_closed(tmp_path):
    p = _lanes_file(tmp_path, "sneaky:\n    max_candidates_per_run: 0")
    with pytest.raises(worker_pool.LaneConfigError, match="> 0"):
        worker_pool.load_lanes(p)


# ── runner registration API ──────────────────────────────────────────────────

def test_default_runners_registered():
    assert {"holdings", "watchlist"} <= set(worker_pool.registered_lanes())


def test_register_duplicate_requires_replace():
    with pytest.raises(worker_pool.LaneRunnerError):
        worker_pool.register_lane_runner("holdings", lambda cfg, dry_run: [])
    worker_pool.register_lane_runner("holdings", lambda cfg, dry_run: [],
                                     replace=True)  # no raise


def test_unregistered_lane_is_skipped_not_error(no_db):
    report = worker_pool.run_lane("strategy", dry_run=True)
    assert report["skipped"] == "no_runner"
    assert "error" not in report


# ── caps / fences / citations (dry-run: no DB writes anywhere) ───────────────

def test_lane_run_cap_honored(no_db):
    worker_pool.register_lane_runner(
        "white_space",
        lambda cfg, dry_run: [_payload(f"topic {i}") for i in range(12)],
        replace=True)
    report = worker_pool.run_lane("white_space", dry_run=True)
    cap = worker_pool.load_lanes()["white_space"]["max_candidates_per_run"]
    assert report["scanned"] == 12
    assert report["skipped_reasons"]["lane_run_cap"] == 12 - cap
    assert len(report["candidates"]) <= cap


def test_lane_domain_fences(no_db):
    worker_pool.register_lane_runner(
        "strategy",
        lambda cfg, dry_run: [_payload("ok topic", domain="macro"),
                              _payload("fenced topic", domain="taxes")],
        replace=True)
    report = worker_pool.run_lane("strategy", dry_run=True)
    assert report["skipped_reasons"] == {"lane_domain_not_allowed:taxes": 1}
    assert [c["label"] for c in report["candidates"]] == ["ok topic"]


def test_citation_gate_on_sensitive_lane(no_db):
    worker_pool.register_lane_runner(
        "legal_domain",
        lambda cfg, dry_run: [_payload("cited", domain="legal", with_url=True),
                              _payload("uncited", domain="legal")],
        replace=True)
    report = worker_pool.run_lane("legal_domain", dry_run=True)
    assert report["skipped_reasons"].get("missing_citation") == 1
    assert [c["label"] for c in report["candidates"]] == ["cited"]


# ── locks / cadence / timeout ────────────────────────────────────────────────

def test_lane_lock_excludes_concurrent_run(no_db, tmp_path):
    worker_pool.register_lane_runner("white_space",
                                     lambda cfg, dry_run: [], replace=True)
    lock = worker_pool._LaneLock("white_space", tmp_path / "locks")
    assert lock.acquire()
    try:
        report = worker_pool.run_lane("white_space", dry_run=True,
                                      lock_dir=tmp_path / "locks")
        assert report["skipped"] == "locked"
    finally:
        lock.release()
    report = worker_pool.run_lane("white_space", dry_run=True,
                                  lock_dir=tmp_path / "locks")
    assert report.get("skipped") != "locked"


def test_cadence_honored_and_force_overrides(no_db, tmp_path):
    lanes = worker_pool.load_lanes(_lanes_file(tmp_path, "l1: {}"))
    worker_pool.register_lane_runner("l1", lambda cfg, dry_run: [], replace=True)
    state = tmp_path / "state.json"
    r1 = worker_pool.run_lane("l1", lanes=lanes, state_path=state,
                              lock_dir=tmp_path / "locks")
    assert "skipped" not in r1 and state.exists()
    r2 = worker_pool.run_lane("l1", lanes=lanes, state_path=state,
                              lock_dir=tmp_path / "locks")
    assert r2["skipped"] == "cadence"
    r3 = worker_pool.run_lane("l1", lanes=lanes, state_path=state, force=True,
                              lock_dir=tmp_path / "locks")
    assert "skipped" not in r3


def test_timeout_honored(no_db, tmp_path):
    lanes = worker_pool.load_lanes(_lanes_file(tmp_path, "slow: {}", timeout=1))

    def sleepy(cfg, *, dry_run):
        time.sleep(3)
        return []

    worker_pool.register_lane_runner("slow", sleepy, replace=True)
    started = time.monotonic()
    report = worker_pool.run_lane("slow", dry_run=True, lanes=lanes,
                                  lock_dir=tmp_path / "locks")
    assert "timeout" in report["error"]
    assert time.monotonic() - started < 3  # abandoned, not awaited


# ── pool bound ───────────────────────────────────────────────────────────────

def test_pool_hard_bound_is_four(no_db, tmp_path):
    assert worker_pool.MAX_WORKERS == 4
    body = "\n  ".join(f"l{i}: {{}}" for i in range(8))
    lanes_path = _lanes_file(tmp_path, body)

    running, peak = {"n": 0, "max": 0}, threading.Lock()

    def tracked(cfg, *, dry_run):
        with peak:
            running["n"] += 1
            running["max"] = max(running["max"], running["n"])
        time.sleep(0.15)
        with peak:
            running["n"] -= 1
        return []

    for i in range(8):
        worker_pool.register_lane_runner(f"l{i}", tracked, replace=True)
    report = worker_pool.run_pool(dry_run=True, max_workers=99,
                                  lanes_path=lanes_path,
                                  lock_dir=tmp_path / "locks",
                                  state_path=tmp_path / "state.json")
    assert report["max_workers"] == 4
    assert running["max"] <= 4
    assert len(report["lanes"]) == 8
    assert all("error" not in r for r in report["lanes"].values())


# ── dry-run writes NOTHING ───────────────────────────────────────────────────

def test_dry_run_writes_nothing(no_db, monkeypatch, tmp_path):
    monkeypatch.setattr(inbox, "upsert_candidate",
                        lambda *a, **k: pytest.fail("dry-run must not upsert"))
    monkeypatch.setattr(inbox, "_audit",
                        lambda *a, **k: pytest.fail("dry-run must not audit"))
    import hermes_discovery_ingestors as ing
    monkeypatch.setattr(ing.inbox, "upsert_candidate",
                        lambda *a, **k: pytest.fail("dry-run must not upsert"))
    worker_pool.register_lane_runner(
        "white_space", lambda cfg, dry_run: [_payload("t1")], replace=True)
    state = tmp_path / "state.json"
    report = worker_pool.run_pool(["white_space"], dry_run=True,
                                  lock_dir=tmp_path / "locks", state_path=state)
    lane = report["lanes"]["white_space"]
    assert lane["scanned"] == 1 and lane["upserted"] == 0
    assert lane["candidates"][0]["label"] == "t1"
    assert not state.exists()  # cadence state untouched by dry runs


# ── do-no-harm pause propagation ─────────────────────────────────────────────

def test_pause_skips_every_lane(no_db, tmp_path):
    cfg = json.loads((ROOT / "config" / "hermes_discovery_schedule.json")
                     .read_text(encoding="utf-8"))
    cfg["paused"] = True
    paused_cfg = tmp_path / "sched.json"
    paused_cfg.write_text(json.dumps(cfg), encoding="utf-8")
    report = worker_pool.run_pool(dry_run=True, config_path=paused_cfg,
                                  lock_dir=tmp_path / "locks",
                                  state_path=tmp_path / "state.json")
    assert all(r.get("skipped") == "paused" for r in report["lanes"].values())
    assert report["skipped_reasons"] == {"paused": len(report["lanes"])}


def test_broken_schedule_config_fails_closed(no_db, tmp_path):
    report = worker_pool.run_pool(dry_run=True,
                                  config_path=tmp_path / "missing.json",
                                  lock_dir=tmp_path / "locks",
                                  state_path=tmp_path / "state.json")
    assert "error" in report and report["lanes"] == {}


def test_unknown_lane_is_an_error(no_db):
    report = worker_pool.run_pool(["not_a_lane"], dry_run=True)
    assert "unknown lane" in report["error"]


# ── advisory-only guarantee ──────────────────────────────────────────────────

def test_no_broker_imports_in_worker_pool_files():
    forbidden = re.compile(
        r"^\s*(?:import|from)\s+(?:scripts\.)?(?:lib\.)?(brokers\b|schwab\w*|"
        r"alpaca\w*)", re.MULTILINE)
    targets = [
        ROOT / "scripts" / "lib" / "hermes_discovery" / "worker_pool.py",
        ROOT / "scripts" / "lib" / "hermes_discovery" / "workspaces.py",
        ROOT / "scripts" / "hermes_research_worker_pool.py",
    ]
    offenders = [p.name for p in targets if forbidden.search(p.read_text())]
    assert not offenders, f"broker imports in advisory-only files: {offenders}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
