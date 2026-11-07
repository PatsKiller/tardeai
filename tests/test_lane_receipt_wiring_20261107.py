"""The two NO_SIGNAL lanes that had no receipt now write one (WORK-QUEUE 2026-11-07, items 4 and 6).

``rotation-rebalance-digest`` and ``alert-missing-conditions`` were declared ``output_signal.kind = none``
because neither wrote a durable artifact — a cron ``>> logs/...`` redirect proves only that cron opened a
file (AGENTS.md §9.3), and it advances on a traceback too. Each now writes one ``LaneRunReceipt@v1``
(``data/runtime/<lane>_last.json``) on a REAL run, and ``ok_at`` advances only on exit 0, so a failing
pass goes stale instead of green (``scripts/lib/lane_last_receipt.py``).

Every test here is hermetic: no DB, no network, no sender, no repo write. The receipt root is a tmp dir
through ``TRADEAI_STATE_ROOT``; the lane's own collaborators are replaced by recorders.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_OK_AT = "2026-01-01T00:00:00+00:00"


@pytest.fixture()
def state_root(tmp_path, monkeypatch):
    """Point the receipt writer at the tmp dir; never the live persistent state."""
    (tmp_path / "data/runtime").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    return tmp_path


def _receipt(state_root: Path, lane_id: str) -> dict:
    return json.loads((state_root / "data/runtime" / f"{lane_id}_last.json").read_text(encoding="utf-8"))


def _seed_previous(state_root: Path, lane_id: str) -> None:
    """A prior successful receipt: a failed run must carry its ok_at forward, never mint a new one."""
    (state_root / "data/runtime" / f"{lane_id}_last.json").write_text(
        json.dumps({"schema": "LaneRunReceipt@v1", "lane_id": lane_id, "status": "ok", "ok_at": PREVIOUS_OK_AT}),
        encoding="utf-8",
    )


class _TelegramStub:
    def __init__(self, return_value):
        self.return_value = return_value
        self.calls: list[tuple] = []

    def send_telegram(self, message, **kwargs):
        self.calls.append((message, kwargs))
        return self.return_value


# ── rotation-rebalance-digest ───────────────────────────────────────────────────────────────────────

def _rotation_module(tmp_path, monkeypatch, *, available: bool, telegram):
    monkeypatch.setitem(sys.modules, "telegram_alert", telegram)
    import rotation_rebalance_digest as rd  # scripts/ is on sys.path (tests/conftest.py)

    monkeypatch.setattr(rd, "ready", lambda _summary: available)
    monkeypatch.setattr(rd, "_get", lambda _path: {"data": {
        "publication": {"status": "READY" if available else "STALE", "reasons": [],
                        "source_as_of": "2026-11-06T20:00:00+00:00",
                        "cache_generated_at": "2026-11-06T21:00:00+00:00"},
        "sector_overweights": [{"theme": "energy", "pct": 22.5, "target": 18.0, "excess_dollars": 1234}],
        "sector_underweights": [{"theme": "health", "pct": 6.0, "floor": 9.0}],
        "research_rotation_ideas": [{"from_symbol": "AAA", "to_symbol": "BBB", "from_account_key": "acct-1"}],
        "degraded_holdings": [],
    }})
    monkeypatch.setattr(rd, "_post", lambda _path, _body=None: {"created": ["d1", "d2"]})
    return rd


def test_rotation_digest_writes_an_ok_receipt_with_produced_counts(state_root, tmp_path, monkeypatch):
    telegram = _TelegramStub(return_value=True)
    rd = _rotation_module(tmp_path, monkeypatch, available=True, telegram=telegram)

    assert rd.main() == 0

    receipt = _receipt(state_root, "rotation-rebalance-digest")
    assert receipt["schema"] == "LaneRunReceipt@v1"
    assert receipt["lane_id"] == "rotation-rebalance-digest"
    assert receipt["status"] == "ok" and receipt["exit"] == 0
    assert receipt["ok_at"] == receipt["finished_at"]
    # The receipt counts what the run produced, not what it printed.
    assert receipt["summary"]["directives_seeded"] == 2
    assert receipt["summary"]["ideas"] == 1
    assert receipt["summary"]["overweights"] == 1
    assert receipt["summary"]["underweights"] == 1
    # "accepted" is the platform's answer, never a delivery claim.
    assert receipt["summary"]["digest_accepted"] is True
    assert len(telegram.calls) == 1


def test_rotation_digest_withheld_publication_is_failed_and_carries_ok_at_forward(state_root, tmp_path, monkeypatch):
    _seed_previous(state_root, "rotation-rebalance-digest")
    rd = _rotation_module(tmp_path, monkeypatch, available=False, telegram=_TelegramStub(return_value=False))

    assert rd.main() == 1

    receipt = _receipt(state_root, "rotation-rebalance-digest")
    assert receipt["status"] == "failed" and receipt["exit"] == 1
    # The lane is still stale: a withheld digest must not look fresh.
    assert receipt["ok_at"] == PREVIOUS_OK_AT
    assert receipt["summary"]["directives_seeded"] == 0


def test_rotation_digest_sender_crash_is_typed_not_swallowed(state_root, tmp_path, monkeypatch):
    class _Boom:
        def send_telegram(self, *_a, **_k):
            raise RuntimeError("sender down: confidential detail")

    rd = _rotation_module(tmp_path, monkeypatch, available=True, telegram=_Boom())

    assert rd.main() == 0  # the digest still reached stdout; the run itself completed

    receipt = _receipt(state_root, "rotation-rebalance-digest")
    assert receipt["summary"]["send_error"] == "RuntimeError"
    assert "confidential" not in json.dumps(receipt)


# ── alert-missing-conditions ────────────────────────────────────────────────────────────────────────

class _FakeConn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _alert_module(monkeypatch, **checks):
    import alert_missing_conditions as amc

    conn = _FakeConn()
    monkeypatch.setattr(amc, "_get_conn", lambda: conn)
    monkeypatch.setattr(amc, "check_stale_proposals", checks.get("stale", lambda _c: 0))
    monkeypatch.setattr(amc, "check_api_credits", checks.get("credits", lambda _c: (0, "ok")))
    monkeypatch.setattr(amc, "check_email_digest", checks.get("email", lambda _c: 0))
    monkeypatch.setattr(amc, "check_rebalance_staleness", checks.get("rebalance", lambda _c: 0))
    return amc, conn


def test_alert_missing_conditions_receipt_counts_alerts_and_the_probe(state_root, monkeypatch):
    amc, conn = _alert_module(
        monkeypatch,
        stale=lambda _c: 2,
        credits=lambda _c: (0, "http_503"),
        email=lambda _c: 1,
    )

    assert amc.main([]) == 0

    receipt = _receipt(state_root, "alert-missing-conditions")
    assert receipt["status"] == "ok" and receipt["ok_at"] == receipt["finished_at"]
    assert receipt["summary"]["stale_proposal_alerts"] == 2
    assert receipt["summary"]["email_digest_alerts"] == 1
    # A probe that could not answer is recorded as such; it must not read as "credits fine".
    assert receipt["summary"]["api_probe"] == "http_503"
    assert receipt["summary"]["alerts"] == 3
    assert conn.closed is True


def test_alert_missing_conditions_failure_is_failed_and_carries_ok_at_forward(state_root, monkeypatch):
    _seed_previous(state_root, "alert-missing-conditions")

    def _boom(_conn):
        raise RuntimeError("db went away: secret-ish text")

    amc, _conn = _alert_module(monkeypatch, stale=_boom)

    assert amc.main([]) == 1

    receipt = _receipt(state_root, "alert-missing-conditions")
    assert receipt["status"] == "failed" and receipt["exit"] == 1
    assert receipt["ok_at"] == PREVIOUS_OK_AT
    assert receipt["error"] == "RuntimeError"
    assert "secret-ish" not in json.dumps(receipt)


def test_alert_missing_conditions_dry_run_writes_nothing(tmp_path):
    env = {**os.environ, "TRADEAI_STATE_ROOT": str(tmp_path), "PYTHONPATH": str(ROOT)}

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/alert_missing_conditions.py"), "--dry-run"],
        capture_output=True, text=True, timeout=120, env=env, cwd=str(ROOT),
    )

    assert proc.returncode == 0, proc.stderr
    assert "DRY-RUN alert-missing-conditions" in proc.stdout
    lane_lines = [line for line in proc.stderr.splitlines() if line.startswith("LANE_OUTPUT ")]
    assert len(lane_lines) == 1
    doc = json.loads(lane_lines[0][len("LANE_OUTPUT "):])
    assert doc["lane_id"] == "alert-missing-conditions"
    assert doc["mode"] == "dry_run"
    assert doc["produced_count"] == 0 and doc["empty_reason"] == "dry_run"
    # A dry run reaches the write nowhere: no receipt at the state root it was pointed at.
    assert not (tmp_path / "data/runtime/alert-missing-conditions_last.json").exists()
    assert not list(tmp_path.rglob("*_last.json"))
