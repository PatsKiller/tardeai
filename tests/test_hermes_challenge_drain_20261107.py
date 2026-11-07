"""LQ-20261107-233 — the closed-loop Hermes challenge queue must actually drain.

Live 2026-11-07: the Closed-loop page showed 191 pending challenges, oldest 2 064 h, and the
queue-health view classified them {missing_symbol: 35, stale: 154, legitimate_current: 2}. The
age-based drain (``intelligence_lineage.drain_hermes_challenges``) existed and was tested, but its
only caller was ``scripts/closed_loop_reconcile.py``, which no scheduler runs — the last
``stale_gt_7d`` expiry was 2026-08-20, during the P0 build. The queue grew for 79 days because the
consumer of the same store (``hermes_cio_worker``, systemd timer, every 15 minutes) expired only
challenges whose plan had completed research, never the ones that went stale.

These tests pin the wiring: the scheduled worker expires stale/duplicate/test challenges on every
``--drain`` run, keeps genuinely current ones, and can never take the research run down with it.

ANCHOR: HERMES_CHALLENGE_DRAIN_20261107
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lib.cio_hermes_challenge_queue import HermesChallengeQueue
from lib.intelligence_lineage import challenge_latest, challenge_pending
from scripts import hermes_cio_worker as worker


@pytest.fixture
def cio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "cio"
    d.mkdir()
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(d))
    return d


def _enqueue(path: Path, *, symbols: list[str], when: datetime, stream: str) -> None:
    """One ENQUEUED challenge with a controlled age.

    The queue only appends, so the age is set by rewriting the single row the enqueue just wrote —
    the fixture holds one row at a time, and every assertion below reads the queue back through the
    production readers, never the fixture's own bookkeeping.
    """
    q = HermesChallengeQueue(event_store_path=path)
    q.enqueue(
        challenge_type="research_gap",
        description="Material CIO situation S5_CASH_DEPLOYMENT (book); independently verify.",
        source="test",
        priority="normal",
        metadata={"symbols": symbols, "plan_id": "plan_fixture"},
    )
    rows = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(rows[-1])
    rec["occurred_at"] = when.isoformat()
    rec["stream_id"] = stream
    rec["payload"]["symbols"] = symbols
    rec["metadata"] = {"symbols": symbols, "plan_id": "plan_fixture"}
    rows[-1] = json.dumps(rec, sort_keys=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _pending_ids(path: Path) -> list[str]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return sorted(str(r.get("stream_id")) for r in challenge_pending(challenge_latest(rows)))


def test_a_stale_challenge_is_expired_and_a_current_one_is_kept(cio: Path):
    path = cio / "hermes_challenge_queue.jsonl"
    now = datetime.now(timezone.utc)
    _enqueue(path, symbols=["MU"], when=now - timedelta(days=86), stream="hermes-challenge-stale")
    _enqueue(path, symbols=["SCHD"], when=now - timedelta(hours=3), stream="hermes-challenge-fresh")

    out = worker.drain_stale_challenges()

    assert out["ok"] is True and out["applied"] is True
    assert out["expired_stale"] == 1
    assert out["left_pending"] == 1
    # The fresh challenge survives; history is appended, never rewritten or deleted.
    assert _pending_ids(path) == ["hermes-challenge-fresh"]
    assert out["deleted"] == 0
    assert "hermes-challenge-stale" in path.read_text(encoding="utf-8")


def test_the_drain_cannot_take_the_research_run_down(cio: Path, monkeypatch: pytest.MonkeyPatch,
                                                      capsys: pytest.CaptureFixture[str]):
    def boom(*_a, **_k):
        raise OSError("store unreadable")

    import lib.intelligence_lineage as lineage

    monkeypatch.setattr(lineage, "drain_hermes_challenges", boom)

    out = worker.drain_stale_challenges()
    assert out["ok"] is False and out["applied"] is False
    assert "store unreadable" in out["error"]  # names the failure instead of raising

    # The scheduled run still completes and still reports the failure in its JSON receipt.
    rc = worker.main(["--drain", "--max", "0", "--backend", "stub", "--json"])
    assert rc == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["challenge_drain"]["ok"] is False


def test_the_scheduled_drain_flag_runs_the_queue_drain(cio: Path, capsys: pytest.CaptureFixture[str]):
    path = cio / "hermes_challenge_queue.jsonl"
    now = datetime.now(timezone.utc)
    _enqueue(path, symbols=["MU"], when=now - timedelta(days=86), stream="hermes-challenge-stale")

    rc = worker.main(["--drain", "--max", "1", "--backend", "stub", "--json"])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    # The systemd unit runs exactly this branch (`--drain … --json`), so the drain must ride it.
    assert out["challenge_drain"]["expired_stale"] == 1
    assert _pending_ids(path) == []


def test_a_quiet_run_reports_an_unchanged_queue(cio: Path):
    path = cio / "hermes_challenge_queue.jsonl"
    now = datetime.now(timezone.utc)
    _enqueue(path, symbols=["SCHD"], when=now - timedelta(hours=2), stream="hermes-challenge-fresh")

    out = worker.drain_stale_challenges()

    assert out["ok"] is True and out["expired_stale"] == 0 and out["left_pending"] == 1
    assert _pending_ids(path) == ["hermes-challenge-fresh"]
