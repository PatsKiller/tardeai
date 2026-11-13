"""LQ-20261107-2641 — REVIEW-2632 gaps G1/G2/G3 on the DDQ route verdict (base 9b70aea76).

G1 is the residual silent PASS of the same class the 2620 fix closed. ``route()`` selects rows for
update, then finds no lane at all; it returned ``routed=0, failed=0`` and ``_route_verdict`` read
that as an empty backlog, so the run wrote ``ok`` and advanced ``ok_at`` over questions that were
never sent. Demonstrated on the folded head with a fake cursor returning two selected questions:

    bridge, policy unreadable, no measured lane -> {'routed': 0, 'failed': 0}
                                                   ['no research lane met the minimum success rate']
                                                   verdict (True, 0, None)
    cron path, no measured lane                 -> same

The fix counts the SELECTED questions as failed at the point the lane list turns out empty. When
nothing was selected the same branch is an idle lane and must stay ``nothing_due``.

G2: ``routed=0, failed=1`` (one selected question) was unpinned; a ``failed > 1`` mutant survived.
G3: the ``RESEARCH_LANE_CANDIDATES`` filter in ``bridge_lane_order`` was unpinned; dropping it let
a policy provider the researcher refuses (``claude``, exit 75) become the ``--lane`` label.

No database, no network, no model call, no live lane run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture(scope="module")
def ddq():
    return pytest.importorskip("due_diligence_questions")


class _Cur:
    """The SELECT ... FOR UPDATE cursor. No ``connection`` attribute: the lease helpers no-op."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.rows


def _route(ddq, monkeypatch, *, rows, lanes, bridge, order=None):
    cur = _Cur(rows)
    monkeypatch.setattr(ddq, "rank_research_lanes", lambda _c: lanes)
    monkeypatch.setattr(ddq, "via_bridge", lambda: bridge)
    monkeypatch.setattr(ddq, "bridge_lane_order", lambda *a, **k: order if order is not None else [])
    monkeypatch.setattr(
        ddq.subprocess, "run", lambda *a, **k: pytest.fail("a lane was called although the list was empty")
    )
    return ddq.route(cur, 2)


SELECTED = [("q1", "NVDA", "Q?"), ("q2", "AMD", "Q?")]


# ── G1: selected and un-routable is a failed route, on both paths ───────────────────────────────────

def test_a_selected_question_with_no_lane_is_a_failed_route(ddq, monkeypatch):
    """Before: {'routed': 0, 'failed': 0, 'lanes_ranked': []} -> verdict (True, 0, None) -> ok."""
    out = _route(ddq, monkeypatch, rows=SELECTED, lanes=[], bridge=True, order=[])
    assert out["routed"] == 0, out
    assert out["failed"] == len(SELECTED), out
    assert out["detail"] == ["no research lane met the minimum success rate"], out
    assert ddq._route_verdict(out) == (False, 1, "all_route_attempts_failed"), out


def test_the_same_rule_holds_on_the_cron_path(ddq, monkeypatch):
    """The measured ranking can empty there too; an unmeasured cron run is not an empty backlog."""
    out = _route(ddq, monkeypatch, rows=SELECTED, lanes=[], bridge=False)
    assert out["failed"] == len(SELECTED), out
    assert ddq._route_verdict(out) == (False, 1, "all_route_attempts_failed"), out


def test_one_selected_question_with_no_lane_is_failed_too(ddq, monkeypatch):
    """G2's boundary: a single-question run must fail, so `failed = len(rows)` cannot be `or 1`."""
    out = _route(ddq, monkeypatch, rows=SELECTED[:1], lanes=[], bridge=True, order=[])
    assert out["failed"] == 1, out
    assert ddq._route_verdict(out) == (False, 1, "all_route_attempts_failed"), out


def test_an_idle_lane_with_nothing_selected_stays_nothing_due(ddq, monkeypatch):
    """The fix counts SELECTED questions, not the empty lane list: no rows stays ok/nothing_due."""
    out = _route(ddq, monkeypatch, rows=[], lanes=[], bridge=True, order=[])
    assert out["failed"] == 0 and out["routed"] == 0, out
    assert ddq._route_verdict(out) == (True, 0, None), out


# ── G2: routed=0 with exactly one failure fails the run ─────────────────────────────────────────────

def test_a_single_failed_question_fails_the_run(ddq):
    """A `failed > 1` mutant leaves this green while a one-question regression grades PASS."""
    routed = {"routed": 0, "failed": 1, "lanes_ranked": ["grok"],
              "detail": ["NVDA:grok gated before attempting — next lane"]}
    assert ddq._route_verdict(routed) == (False, 1, "all_route_attempts_failed"), routed


# ── G3: the policy order never names a provider the researcher refuses ──────────────────────────────

def _policy(tmp_path: Path, *, primary: str, secondary: str, fallback: str) -> Path:
    doc = {
        "default_policy_id": "default",
        "policies": {"default": {"processes": {"due_diligence_questions": {
            "primary": {"provider": primary},
            "secondary": {"provider": secondary},
            "fallback": {"provider": fallback},
        }}}},
    }
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "llm_routing_policy.json").write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def test_bridge_lane_order_drops_a_provider_the_researcher_refuses(ddq, monkeypatch, tmp_path):
    """`claude` is not in RESEARCH_LANE_CANDIDATES: the researcher gates it with exit 75 (CLAUDE_NOT_ON_GOVERNED_BRIDGE)."""
    monkeypatch.setattr(ddq, "ROOT", _policy(tmp_path, primary="claude", secondary="grok", fallback="deepseek"))
    assert ddq.bridge_lane_order() == ["grok", "deepseek"]


def test_bridge_lane_order_keeps_only_the_candidates_and_dedupes(ddq, monkeypatch, tmp_path):
    """A repeated provider is one label, not two attempts; a non-candidate anywhere is dropped."""
    monkeypatch.setattr(ddq, "ROOT", _policy(tmp_path, primary="grok", secondary="grok", fallback="claude"))
    assert ddq.bridge_lane_order() == ["grok"]
