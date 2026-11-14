"""OPS-C1 — the Platform card and the /ops queue name ONE failed-unit list from ONE snapshot.

This is the *surface* test. ``tests/test_failed_units_20261114.py`` pins the adapter and the parsers; this file pins
what the operator actually sees: the Platform row's ``detail`` and the queue's ``sections.failed_units`` /
``needs_attention`` derived from the same snapshot, with the same observation time, and the api_v2 wiring that makes
that so.

The incident (2026-11-14, /ops): Platform listed the three failed ``tradeai*`` units; the queue listed
``hermes-deep-research-local`` instead of ``tradeai-deploy-on-main``, because it inferred "service failed" from a
per-timer ``systemctl --user show`` loop. Hermetic: a fake ``run`` and a fixed clock, no systemd, no host, no DB.

Review r2 (cc-deepseek-4, 2026-11-14T20:44Z) asked for behaviour, not source markers: the wiring test below calls
``api_v2._queue_control_tower()`` with its inputs monkeypatched and asserts the returned ``needs_attention`` carries
the failed unit. The source-text assertions are kept only as an extra guard; the behavioural test is the gate.
"""
from __future__ import annotations

import glob
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import failed_units as fu  # noqa: E402
from lib import platform_health as ph  # noqa: E402
import queue_runtime_status as qrs  # noqa: E402

NOW = datetime(2031, 3, 7, 15, 0, 0, tzinfo=timezone.utc)
AS_OF = NOW.isoformat()

# The live disagreement, as systemd prints it (descriptions invented, names real).
LIVE_OUTPUT = """\
tradeai-backup-enforcer.service     loaded failed failed Backup enforcer
tradeai-deploy-on-main.service     loaded failed failed Deploy on main
tradeai-prospectus-deliver.service loaded failed failed Prospectus deliver
hermes-deep-research-local.service loaded failed failed Hermes deep research (local)
"""


def runner(stdout: str = LIVE_OUTPUT, rc: int = 0, stderr: str = ""):
    def run(argv, **kw):
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)

    return run


def platform_row(run):
    deps = ph.Deps(runner=run, now=lambda: NOW)
    rows = ph.probe_failed_units(deps)
    assert len(rows) == 1, rows
    return rows[0]


# ── 1. One snapshot, one clock: the two surfaces agree ────────────────────────────────────────────────────────

def test_platform_and_queue_share_units_and_as_of():
    run = runner()
    row = platform_row(run)
    view = qrs.failed_units_snapshot(run=run, now=lambda: NOW)

    assert row["status"] == "WARN", row
    assert row["value"] == 3, row
    assert row["as_of"] == view["as_of"] == AS_OF
    assert row["detail"]["reviewed_at"] == AS_OF
    assert view["count"] == 4 and view["outside_count"] == 0
    assert row["detail"]["user_units_failed_total"] == view["count"] + view["outside_count"]
    assert row["detail"]["units"] == [
        "tradeai-backup-enforcer.service",
        "tradeai-deploy-on-main.service",
        "tradeai-prospectus-deliver.service",
    ]
    assert "tradeai-deploy-on-main.service" in [u["unit"] for u in view["units"]]


def test_narrower_surface_names_the_outside_units():
    row = platform_row(runner())
    assert row["detail"]["outside_scope"] == ["hermes-deep-research-local.service"]
    assert "outside this card's scope" in row["reason"]
    assert "hermes-deep-research-local.service" in row["reason"]


def test_unanswered_everywhere_is_unknown_not_zero():
    run = runner(stdout="", rc=4, stderr="Failed to connect to bus")
    row = platform_row(run)
    view = qrs.failed_units_snapshot(run=run, now=lambda: NOW)
    assert row["status"] == "UNKNOWN" and row["value"] is None
    assert view["answered"] is False and view["reason"]
    assert qrs.failed_units_attention(view) == []
    assert fu.summary(view).startswith("Failed units unknown:")


# ── 2. needs_attention is derived from the view, deduped, and never invents an all-clear ───────────────────

def test_attention_entries_carry_unit_source_and_as_of():
    view = qrs.failed_units_snapshot(run=runner(), now=lambda: NOW)
    entries = qrs.failed_units_attention(view)
    # sorted by unit name, as the adapter returns them (never by a per-timer glob order)
    assert [e["job_id"] for e in entries] == [
        "hermes-deep-research-local",
        "tradeai-backup-enforcer",
        "tradeai-deploy-on-main",
        "tradeai-prospectus-deliver",
    ]
    assert all(e["reason"] == "service failed" for e in entries)
    assert all(e["source"] and e["as_of"] == AS_OF for e in entries)
    assert entries[2]["unit"] == "tradeai-deploy-on-main.service"


def test_attention_skips_jobs_already_reported_as_last_run_failed():
    view = qrs.failed_units_snapshot(run=runner(), now=lambda: NOW)
    entries = qrs.failed_units_attention(view, skip={"tradeai-deploy-on-main"})
    assert "tradeai-deploy-on-main" not in [e["job_id"] for e in entries]
    assert len(entries) == 3


def test_section_shape_is_renderable():
    view = qrs.failed_units_snapshot(run=runner(), now=lambda: NOW)
    for key in ("units", "outside", "count", "outside_count", "scope", "source", "as_of", "answered", "reason"):
        assert key in view, key
    assert view["count"] == len(view["units"])
    assert view["answered"] is True and view["reason"] is None
    assert view["source"].startswith("systemctl --user list-units --all --state=failed")


# ── 3. The api_v2 wiring — proven by the endpoint's OUTPUT, not its source text (review F1) ──────────────────

def _queue_control_tower_source() -> str:
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    start = src.index("def _queue_control_tower(")
    end = src.index("\ndef ", start + 1)
    return src[start:end]


def answered_snapshot() -> dict:
    """The adapter's own snapshot shape, built through its parser, so the fixture cannot drift from the real one."""
    return {
        "schema": fu.SCHEMA, "scope": fu.SCOPE, "source": fu.SOURCE, "argv": list(fu.ARGV),
        "timeout_s": fu.DEFAULT_TIMEOUT_S, "answered": True, "reason": None,
        "units": fu.parse_failed_units(LIVE_OUTPUT), "as_of": AS_OF, "ms": 1,
    }


def test_api_queue_control_tower_publishes_and_uses_the_shared_units(monkeypatch):
    """The gate. A queue that drops the shared attention entries (review F1's ``+ []`` mutant) fails here."""
    import api_v2

    monkeypatch.setattr(glob, "glob", lambda pattern: [])                 # no timer files on this host
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: [])
    monkeypatch.setattr(fu, "snapshot", lambda **k: answered_snapshot())

    body = api_v2._queue_control_tower()

    section = body["sections"]["failed_units"]
    assert section["answered"] is True and section["count"] == 4, section
    assert body["failed_units"] == 4, body.get("failed_units")
    ids = [a["job_id"] for a in body["sections"]["needs_attention"]]
    assert "tradeai-deploy-on-main" in ids, ids  # the unit the old per-timer queue omitted
    assert "hermes-deep-research-local" in ids, ids
    entry = next(a for a in body["sections"]["needs_attention"] if a["job_id"] == "tradeai-deploy-on-main")
    assert entry["reason"] == "service failed", entry
    assert entry["source"] == fu.SOURCE and entry["as_of"] == AS_OF, entry


def test_api_queue_control_tower_never_derives_failed_units_from_timer_state():
    body = _queue_control_tower_source()
    assert '"service_state") == "failed"' not in body, (
        "the per-timer systemctl show loop (ActiveState) must not decide the failed set — that is the defect: it "
        "named hermes-deep-research-local and missed tradeai-deploy-on-main"
    )


# ── 4. The Platform joins the shared 5 s reading in production (review F2) ───────────────────────────────────

def test_platform_joins_the_shared_cache_instead_of_probing_again(monkeypatch):
    """The sharing claim, proven: a primed cache must satisfy the Platform with NO second probe."""
    fu._CACHE["at"] = None
    fu._CACHE["snapshot"] = None
    primed = fu.snapshot(run=runner(), now=lambda: NOW, use_cache=True)
    assert primed["as_of"] == AS_OF

    def boom(*a, **k):
        raise AssertionError("the Platform probed instead of reading the shared 5 s cache (review F2)")

    monkeypatch.setattr(subprocess, "run", boom)
    deps = ph.Deps(runner=subprocess.run, now=lambda: NOW)  # built after the patch: this identity is what opts in
    row = ph.probe_failed_units(deps)[0]
    fu._CACHE["at"] = None
    fu._CACHE["snapshot"] = None

    assert row["status"] == "WARN" and row["value"] == 3, row
    assert row["as_of"] == AS_OF and row["detail"]["reviewed_at"] == AS_OF, row


# ── 5. The Platform row states the source every reader actually runs (review F3) ─────────────────────────────

def test_platform_row_source_is_the_argv_every_reader_runs():
    row = platform_row(runner())
    assert row["source"] == fu.SOURCE, row["source"]
    assert row["detail"]["source"] == fu.SOURCE, row["detail"]
