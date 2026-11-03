"""FRESHNESS_CONSUMERS_20261103 — every consumer answers from ONE guarded read.

The authoritative-store guard existed but was wired into the ops summary only. A 0-byte or
corrupt holdings.json (or a manifest whose hash/clock no longer matches it) still rendered FRESH
on the portfolio monitor, the global-alerts banner and GET /api/freshness — a false all-clear on
the exact incident shape. These cross-surface tests drive the same store states through every
surface and assert that none of them can publish a healthy status over an unreadable book.

The read lives in ``lib.authoritative_store_guard.guarded_manifest``; every surface below must
answer through it. A surface that starts reading ``_freshness.json`` directly again is a
regression, so the last test pins the single read path itself.
"""

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import api_v2  # noqa: E402
import portfolio_ai_analyst  # noqa: E402
import portfolio_server  # noqa: E402
from lib.authoritative_store_guard import guarded_manifest, holdings_hash  # noqa: E402

NOW = datetime.now(timezone.utc)

HEALTHY_ROW = {
    "symbol": "AAA",
    "account": "schwab_taxable",
    "shares": 10,
    "market_value": 1200.0,
    "price": 120.0,
}


def _write_store(state_dir, holdings, *, completed_at=None, status="fresh", holdings_hash_value="__auto__"):
    """A store + manifest pair; ``holdings`` is written verbatim (bytes/str raw, dict as JSON)."""
    if isinstance(holdings, bytes):
        (state_dir / "holdings.json").write_bytes(holdings)
    elif isinstance(holdings, str):
        (state_dir / "holdings.json").write_text(holdings)
    else:
        (state_dir / "holdings.json").write_text(json.dumps(holdings))
    doc = holdings if isinstance(holdings, dict) else {}
    stamp = completed_at if completed_at is not None else NOW - timedelta(minutes=5)
    manifest = {
        "status": status,
        "completed_at": stamp.isoformat() if isinstance(stamp, datetime) else stamp,
        "holdings_hash": holdings_hash(doc) if holdings_hash_value == "__auto__" else holdings_hash_value,
        "run_id": "run-42",
        "steps_completed": 10,
    }
    (state_dir / "_freshness.json").write_text(json.dumps(manifest))
    return state_dir


def _healthy(state_dir):
    return _write_store(state_dir, {"holdings": [HEALTHY_ROW], "as_of": NOW.date().isoformat()})


SCENARIOS = {
    # name: (builder, expected status on every surface)
    "healthy": (_healthy, "fresh"),
    "zero_byte_store": (lambda d: _write_store(d, b"", holdings_hash_value="94f18d5b8ced"), "UNAVAILABLE"),
    "corrupt_store": (
        lambda d: _write_store(d, '{"holdings": [{"symbol": "AAA"', holdings_hash_value="94f18d5b8ced"),
        "UNAVAILABLE",
    ),
    "hash_mismatch": (
        lambda d: _write_store(d, {"holdings": [HEALTHY_ROW]}, holdings_hash_value="deadbeefcafe"),
        "STALE",
    ),
    "stale_completed_at": (
        lambda d: _write_store(d, {"holdings": [HEALTHY_ROW]}, completed_at=NOW - timedelta(hours=40)),
        "STALE",
    ),
    "future_completed_at": (
        lambda d: _write_store(d, {"holdings": [HEALTHY_ROW]}, completed_at=NOW + timedelta(hours=2)),
        "STALE",
    ),
}


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    """Point api_v2 AND the canonical observation layer at the temporary state directory."""
    monkeypatch.setattr(api_v2, "STATE_DIR", tmp_path)
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: None)
    from lib import canonical_observation as _co

    # The overview envelopes resolve through canonical_state_path, not api_v2.STATE_DIR; without
    # this they would read the live served copy and the test would assert about the wrong files.
    monkeypatch.setattr(_co, "canonical_state_path", lambda filename, checkout_root=None: tmp_path / filename)
    return tmp_path


def _surface_statuses(state_dir):
    """Every surface's published status for the store currently on disk."""
    monitor = api_v2._portfolio_monitor()
    alerts = api_v2._global_alerts()
    morning = api_v2._morning_command()
    ops = api_v2.ops_summary()
    _code, http_payload = portfolio_server.freshness_payload(state_dir)
    return {
        "guarded_read": api_v2._guarded_freshness()["status"],
        "portfolio_monitor": monitor["freshness"]["status"],
        "global_alerts": alerts["freshness"]["status"],
        "morning_command": morning["freshness"]["status"],
        "ops_summary": ops["pipeline"]["status"],
        "api_freshness": http_payload["status"],
    }


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_every_surface_publishes_the_guarded_status(state_dir, scenario):
    builder, expected = SCENARIOS[scenario]
    builder(state_dir)
    observed = _surface_statuses(state_dir)
    wrong = {name: value for name, value in observed.items() if value != expected}
    assert not wrong, f"{scenario}: surfaces must all publish {expected}, got {observed}"


def test_zero_byte_store_is_unavailable_with_a_plain_message(state_dir):
    _write_store(state_dir, b"", holdings_hash_value="94f18d5b8ced")
    _code, payload = portfolio_server.freshness_payload(state_dir)
    assert payload["status"] == "UNAVAILABLE"
    assert payload["guard"]["ok"] is False
    assert "holdings_store_empty" in payload["guard"]["reasons"]
    assert "could not be read" in payload["message"]


def test_corrupt_store_is_unavailable(state_dir):
    _write_store(state_dir, '{"holdings": [', holdings_hash_value="94f18d5b8ced")
    doc = guarded_manifest(state_dir)
    assert doc["status"] == "UNAVAILABLE"
    assert "holdings_store_unparseable" in doc["guard"]["reasons"]


def test_a_healthy_store_still_reads_fresh(state_dir):
    _healthy(state_dir)
    observed = _surface_statuses(state_dir)
    assert set(observed.values()) == {"fresh"}, observed


def test_hash_mismatch_is_never_fresh(state_dir):
    _write_store(state_dir, {"holdings": [HEALTHY_ROW]}, holdings_hash_value="deadbeefcafe")
    doc = api_v2._guarded_freshness()
    assert doc["status"] == "STALE"
    assert "holdings_hash_mismatch" in doc["guard"]["reasons"]
    _code, payload = portfolio_server.freshness_payload(state_dir)
    assert payload["status"] == "STALE"
    assert "cannot be confirmed current" in payload["message"]


def test_a_recent_clock_cannot_upgrade_a_guarded_status(state_dir, monkeypatch):
    """_compute_freshness must not let holdings mtime / pipeline_runs outvote the guard.

    last_refresh may still name the latest pipeline run (that is a true fact); the STATUS is what
    may not become fresh while the store is unreadable.
    """
    _write_store(state_dir, b"", holdings_hash_value="94f18d5b8ced")
    recent = (datetime.now() - timedelta(minutes=2)).isoformat()
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: {"latest": recent} if "pipeline_runs" in str(a) else None)
    doc = api_v2._guarded_freshness()
    assert doc["status"] == "UNAVAILABLE"
    computed = api_v2._compute_freshness(doc)
    assert computed["status"] == "UNAVAILABLE"


def test_analyst_staleness_warning_fails_closed(state_dir):
    _write_store(state_dir, b"", holdings_hash_value="94f18d5b8ced")
    warning = portfolio_ai_analyst._freshness_warning_for(state_dir)
    assert "STALENESS WARNING" in warning
    assert "holdings_store_empty" in warning
    _healthy(state_dir)
    assert portfolio_ai_analyst._freshness_warning_for(state_dir) == ""


def test_analyst_cache_hash_still_reads_the_manifest_field(state_dir):
    _healthy(state_dir)
    expected = holdings_hash({"holdings": [HEALTHY_ROW], "as_of": NOW.date().isoformat()})
    assert portfolio_ai_analyst._current_holdings_hash(state_dir) == expected


def test_only_the_guard_module_reads_the_manifest():
    """One code path: no runtime module outside the guard may READ _freshness.json itself.

    Matches a path join (``STATE_DIR / "_freshness.json"``), not every mention of the filename:
    the observation envelope, the backup list and the staleness threshold map name the file without
    reading it, and they are not freshness consumers.
    """
    read_re = re.compile(r'/\s*["\']_freshness\.json["\']')
    offenders = []
    for path in sorted((ROOT / "scripts").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if "test" in path.name or rel.startswith("scripts/cc_runtime_harness/"):
            continue
        if rel in {
            "scripts/lib/authoritative_store_guard.py",  # the one read path
            "scripts/portfolio_orchestrator.py",  # the producer/writer of the manifest
            # Live-claim handoff, not a permanent exemption: cc-deepseek-6 holds this file for the
            # recovery-engine slice (claim 20261103T185459Z-claude-16fa46ef). Its two reads are
            # dead loads (assigned, never used); handoff filed 2026-11-03 to route them through
            # guarded_manifest. Remove this line and the file must pass.
            "scripts/recovery_watch_daily.py",
        }:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            if read_re.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, "direct _freshness.json reads outside the guard: " + "; ".join(offenders)


# ── R1: the PRIMARY overview status must consult the store, not only file ages (cx-openai-4) ────
def _fresh_context(state_dir):
    """The other overview datasets, so the envelope baseline is FRESH and only the guard can degrade it."""
    for name in ("performance_history.json", "portfolio_news.json"):
        (state_dir / name).write_text("{}", encoding="utf-8")
    return state_dir


def test_overview_primary_status_cannot_beat_the_store(state_dir):
    _write_store(_fresh_context(state_dir), {"holdings": [], "as_of": NOW.date().isoformat()})
    out = api_v2.overview()
    assert out["pipeline_status"] != "fresh"
    assert out["observation"]["surface_status"] != "FRESH"
    assert "authoritative_store" in out["observation"]["not_fresh_datasets"]
    assert out["observation"]["authoritative_store"]["ok"] is False


def test_overview_hash_mismatch_primary_status_is_stale(state_dir):
    _write_store(_fresh_context(state_dir), {"holdings": [HEALTHY_ROW], "as_of": NOW.date().isoformat()},
                 holdings_hash_value="deadbeefcafe")
    out = api_v2.overview()
    assert out["pipeline_status"] == "stale"
    assert out["observation"]["surface_status"] == "STALE"
    assert "authoritative_store" in out["observation"]["not_fresh_datasets"]


def test_overview_healthy_store_still_reports_fresh(state_dir):
    _healthy(_fresh_context(state_dir))
    out = api_v2.overview()
    assert out["pipeline_status"] == "fresh"
    assert out["observation"]["surface_status"] == "FRESH"
    assert "authoritative_store" not in out["observation"]["not_fresh_datasets"]


# ── R2: one manifest read, one validated document (cx-openai-4) ────────────────────────────────
def test_guarded_manifest_validates_the_exact_document_it_returns(state_dir, monkeypatch):
    _write_store(state_dir, {"holdings": [HEALTHY_ROW]}, holdings_hash_value="deadbeefcafe")
    replacement = {
        "status": "fresh",
        "completed_at": NOW.isoformat(),
        "holdings_hash": holdings_hash({"holdings": [HEALTHY_ROW]}),
    }
    reads = {"n": 0}
    real_read_text = Path.read_text

    def replacing_read(self, *args, **kwargs):
        if self.name == "_freshness.json":
            reads["n"] += 1
            if reads["n"] > 1:  # an atomic replacement between two reads
                return json.dumps(replacement)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", replacing_read)
    doc = api_v2._guarded_freshness()

    assert reads["n"] == 1, "the manifest must be read exactly once"
    assert doc["guard"]["holdings_hash_expected"] == doc.get("holdings_hash")
    assert doc["status"] != "fresh", "the returned document is the stale/mismatched one, and so is its verdict"
    assert "holdings_hash_mismatch" in doc["guard"]["reasons"]
