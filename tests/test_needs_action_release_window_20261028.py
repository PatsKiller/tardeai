"""Needs-action deploy STOP items after the release-train leftovers cleanup (operator directive 2026-10-27).

``needs_action.rule_release_window`` reads the deploy STOP latch (the one the host deploy_on_main poller and the
emergency promote refuse on) and the release-window runner's last receipt. Pinned here:

* a STOP set from the Command Center (``deploy_stop.request_stop``, the real writer: ``window_id`` None,
  outcome ``STOP_REQUESTED_OPERATOR``) renders its reason, never "window None ended ... for candidate";
* a window runner latch keeps its window / outcome / candidate detail;
* an unreadable latch is still a P1 STOP;
* no latch, no item; a recent failed window is still reported;
* the retired release train's orphaned-request spool no longer produces an item (it named removed subcommands);
* the Home "Do now" button for these sources reads "Open Jobs" (they link to the Jobs tab), not "Release train".

Hermetic: tmp state dir only. psycopg2 stubbed when absent. No network, git, systemd or broker.
"""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: these tests never touch a database")

    _pg.connect = _no_connect
    sys.modules.setdefault("psycopg2", _pg)

from scripts.lib import deploy_stop as DS  # noqa: E402
from scripts.lib import needs_action as NA  # noqa: E402

NOW = datetime(2026, 10, 28, 4, 0, tzinfo=timezone.utc)


def _items(root: Path) -> list[dict]:
    return NA.rule_release_window(NA.read_release_window_state(root), NOW)


def _write(path: Path, body) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")


def test_no_latch_no_receipt_is_no_item(tmp_path):
    assert _items(tmp_path) == []


def test_command_center_stop_renders_its_reason_not_window_none(tmp_path):
    status, body = DS.request_stop(
        actor="tailnet:operator@example",
        reason="operator pressed STOP DEPLOYS",
        idempotency_key="needs-action-test-0001",
        csrf_ok=True,
        root=tmp_path,
        now=NOW,
    )
    assert status < 300, body
    latch = json.loads((tmp_path / "STOP.json").read_text(encoding="utf-8"))
    assert latch["window_id"] is None and latch["outcome"] == "STOP_REQUESTED_OPERATOR"  # the real writer's shape

    items = _items(tmp_path)
    assert len(items) == 1, items
    it = items[0]
    assert it["severity"] == "P1" and it["title"] == "Deploys halted: STOP latched"
    assert it["source"] == "release_window" and it["where"] == NA.R_SYSTEM_JOBS
    assert "operator pressed STOP DEPLOYS" in it["why"]
    assert "window None" not in it["why"] and "for candidate" not in it["why"]
    assert "deploy_on_main poller" in it["why"] and "emergency promote" in it["why"]
    assert "scripts/release_window.py clear-stop" in it["why"]


def test_latch_without_window_or_reason_falls_back_to_outcome(tmp_path):
    _write(tmp_path / "STOP.json", {"latched_at": "2026-10-28T03:00:00Z", "window_id": None, "outcome": "X_OUTCOME"})
    (it,) = _items(tmp_path)
    assert "STOP latched (X_OUTCOME)" in it["why"]
    _write(tmp_path / "STOP.json", {"window_id": None})
    (it,) = _items(tmp_path)
    assert "STOP latched (no reason recorded)" in it["why"]


def test_window_runner_latch_keeps_window_detail(tmp_path):
    _write(
        tmp_path / "STOP.json",
        {
            "latched_at": "2026-10-27T21:31:00Z",
            "window_id": "20261027-1730",
            "outcome": "ROLLED_BACK",
            "candidate": "abcdef1234567890",
        },
    )
    (it,) = _items(tmp_path)
    assert it["severity"] == "P1" and it["title"] == "Deploys halted: STOP latched"
    assert it["why"].startswith("window 20261027-1730 ended ROLLED_BACK for candidate abcdef123;")
    assert it["since"] == "2026-10-27T21:31:00Z"


def test_unreadable_latch_is_a_p1_stop(tmp_path):
    _write(tmp_path / "STOP.json", "{corrupt")
    (it,) = _items(tmp_path)
    assert it["severity"] == "P1" and it["title"] == "Deploys halted: STOP latch unreadable"
    assert "cannot be read" in it["why"] and "deploy_on_main poller" in it["why"]


def test_recent_failed_window_receipt_is_still_reported(tmp_path):
    _write(
        tmp_path / "last.json",
        {
            "window_id": "20261027-1730",
            "outcome": "STOP_CI_NOT_GREEN",
            "finished_at": "2026-10-28T01:00:00+00:00",
            "candidate": {"sha": "1234567890abcdef", "selected_by": "head"},
        },
    )
    (it,) = _items(tmp_path)
    assert it["severity"] == "P2" and it["title"] == "Release window 20261027-1730 STOP_CI_NOT_GREEN"


def test_retired_train_orphan_spool_is_no_longer_an_item(tmp_path):
    _write(tmp_path / "train_requests" / "orphaned" / "req-1.json", {})
    state = NA.read_release_window_state(tmp_path)
    assert "orphaned" not in state
    assert _items(tmp_path) == []
    src = (ROOT / "scripts" / "lib" / "needs_action.py").read_text(encoding="utf-8")
    assert "Release train request" not in src and "then train-orphan-resolve" not in src


def test_home_do_now_label_for_these_sources_is_open_jobs():
    from scripts.lib.data_broker import home_do_now as H

    assert H.ACTION_LABEL["release_window"] == "Open Jobs"
    assert H.ACTION_LABEL["macro_calendar"] == "Open Jobs"
    assert "Release train" not in H.ACTION_LABEL.values()
