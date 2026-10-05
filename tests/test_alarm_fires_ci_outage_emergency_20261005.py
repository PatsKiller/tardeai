"""Firing test (2026-10-05) for the emergency-release reconciliation page.

scripts/ci_outage_emergency_release.py pages the operator through the real
telegram_alert.send_telegram chokepoint when an emergency release fails reconciliation (GitHub CI
ran and failed on the deployed content) or misses its time box. Fakes only: no GitHub, no deploy.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import ci_outage_emergency_release as cli  # noqa: E402
from scripts.lib import ci_outage_emergency as em  # noqa: E402

COVERS = ["scripts/ci_outage_emergency_release.py"]

SHA = "c" * 40


class _Args:
    apply = True


def _setup(tmp_path, monkeypatch, *, failed: bool):
    monkeypatch.setattr(em, "STATE_DIR", tmp_path / "emergency")
    em.append_ledger({"event": "EMERGENCY_PROMOTED", "state": em.PENDING, "sha": SHA, "tree": "T",
                      "label": em.PENDING, "incident_ids": ["inc123"], "prev_release": "/rel/prev",
                      "promoted_at": time.time() - 3600})
    monkeypatch.setattr(cli, "_main_commits", lambda n=300: [(SHA, "T")])
    monkeypatch.setattr(cli, "collect_push_checks", lambda sha: {"ok": False, "errors": ["not_successful"]})
    monkeypatch.setattr(cli, "_ran_and_failed", lambda sha: failed)
    monkeypatch.setattr(cli, "_content_merged", lambda sha: True)
    return {"auto_rollback": False, "reconcile_within_h": 24, "page_cooldown_min": 120}


def test_reconcile_failure_pages_and_records_a_dry_run_rollback(alarm_capture, tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, failed=True)
    assert cli.cmd_reconcile(_Args(), cfg) == 0
    alarm_capture.assert_fired(contains="EMERGENCY RELEASE RECONCILE_FAILED")
    rows = em.load_ledger()
    assert any(r.get("event") == "ROLLBACK_DRY_RUN" and "rollback /rel/prev" in r.get("would_run", "") for r in rows)
    assert any(r.get("event") == em.RECONCILE_FAILED and r.get("paged") is True for r in rows)


def test_pending_release_does_not_page(alarm_capture, tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, failed=False)
    assert cli.cmd_reconcile(_Args(), cfg) == 0
    assert not any(r.get("paged") for r in em.load_ledger())
