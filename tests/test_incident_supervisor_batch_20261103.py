"""ONBOARDING §12 rule 3 — one batched escalation per supervisor run (operator 2026-11-03).

Verbatim operator complaint: six P1 Telegrams from one supervisor run. The standard: "ONE batched
Telegram per supervisor run as a list — never six separate P1s. Page the operator ONLY for an
operator-only decision." These tests drive the real `cycle()` with six incidents that would each
have paged individually and assert exactly one message, its priority, its contents, and that every
incident still records its own delivered escalation row (so the once-per-episode suppression holds).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import incident_supervisor as S  # noqa: E402
from scripts.lib import incidents as L  # noqa: E402

T0 = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)
NOW = T0 + timedelta(hours=2)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_INCIDENTS_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "ps"))


def _cfg(**over):
    cfg = json.loads((ROOT / "config" / "incident_runbook_actions.json").read_text(encoding="utf-8"))
    cfg["policy"].update({"max_incidents_per_cycle": 6, "max_attempts_per_incident": 3})
    cfg["policy"].update(over)
    return cfg


def _seed(d: Path, *, n: int = 6, refused_first: bool = False) -> list[str]:
    ids = []
    for i in range(n):
        title = "credential exposure" if refused_first and i == 0 else f"lane outage {i}"
        rec, _created = L.open_incident(
            source={"kind": "watcher", "watcher": "lane_health"},
            title=title, where=f"tests/fixture_{i}", severity="P1" if title == "credential exposure" else "P2",
            d=d, now=T0,
        )
        # Three counted supervisor actions put each incident at the attempts cap, so the cycle
        # escalates without ever calling the model (the model stub below fails the test if called).
        for _ in range(3):
            L.attempt(rec["id"], actor="incident_supervisor", action="runbook", result="noop", ok=False,
                      d=d, now=T0)
        ids.append(rec["id"])
    return ids


def _run(tmp_path: Path, cfg, pages: list, now=NOW):
    def model(_prompt):
        raise AssertionError("the model must not be called for an attempts-cap escalation")

    def notify(text, producer, priority="P2"):
        pages.append({"text": text, "producer": producer, "priority": priority})
        return True

    deps = S.Deps(model=model, run=lambda *_a, **_k: (0, "ok"), notify=notify,
                  fixer=lambda *_a, **_k: {"rc": 0})
    return S.cycle(d=tmp_path / "ledger", state_root=tmp_path / "ps", release_root=tmp_path, cfg=cfg,
                   deps=deps, apply=True, now=now, environ={"HOME": "/h", "PATH": "/bin"}, root=ROOT)


def test_six_incidents_produce_exactly_one_batched_message(tmp_path):
    ids = _seed(tmp_path / "ledger")
    pages: list = []
    out = _run(tmp_path, _cfg(), pages)

    assert len(pages) == 1, f"expected one batched page, got {len(pages)}: {pages}"
    page = pages[0]
    assert page["priority"] == "P2"  # nothing operator-only in this batch
    assert page["producer"] == "incident_supervisor:batch"
    for iid in ids:
        assert iid in page["text"]
    assert page["text"].count("•") == 6
    assert "unresolved 120 min" in page["text"]          # time unresolved is in the list
    assert page["text"].count("Next:") == 6              # the exact next action per entry
    assert "operator-only" not in page["text"]

    # Every incident still records its own delivered escalation row: the batch is one message, not
    # one anonymous send, so the per-incident/episode suppression keeps working.
    assert len(out["escalated"]) == 6 and all(row["delivered"] is True for row in out["escalated"])
    assert all(row["priority"] == "P2" for row in out["escalated"])

    # A second cycle does not page again for the same delivered reason class.
    out2 = _run(tmp_path, _cfg(), pages, now=NOW + timedelta(minutes=10))
    assert len(pages) == 1
    assert out2["escalated"] == []


def test_a_batch_with_an_operator_only_decision_is_p1(tmp_path):
    ids = _seed(tmp_path / "ledger", refused_first=True)
    pages: list = []
    out = _run(tmp_path, _cfg(), pages)

    assert len(pages) == 1
    page = pages[0]
    assert page["priority"] == "P1"
    assert "operator-only decision" in page["text"]
    assert ids[0] in page["text"] and ids[-1] in page["text"]
    assert page["text"].count("•") == 6
    assert {row["operator_only"] for row in out["escalated"]} == {True, False}
    assert all(row["priority"] == "P1" for row in out["escalated"])


def test_a_failed_batch_records_undelivered_rows_for_the_retry_path(tmp_path):
    _seed(tmp_path / "ledger")
    pages: list = []

    def notify(_text, _producer, priority="P2"):
        raise RuntimeError("telegram down")

    def model(_prompt):
        raise AssertionError("no model")

    deps = S.Deps(model=model, run=lambda *_a, **_k: (0, "ok"), notify=notify, fixer=lambda *_a, **_k: {})
    out = S.cycle(d=tmp_path / "ledger", state_root=tmp_path / "ps", release_root=tmp_path, cfg=_cfg(),
                  deps=deps, apply=True, now=NOW, environ={"HOME": "/h", "PATH": "/bin"}, root=ROOT)
    assert len(out["escalated"]) == 6
    assert all(row["delivered"] is False for row in out["escalated"])  # queued for the retry path
