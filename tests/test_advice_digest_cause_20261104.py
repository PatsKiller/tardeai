"""The digest must render the CAUSE it counted, not only how many.

codex (2026-11-04) measured through the real renderer that a body saying "DeepSeek DEFERRED_TO_OFFPEAK" and one saying
"DeepSeek provider unavailable: critical failure" produced byte-identical digests — the operator could not tell "we were
late" from "we were broken". The counterfactual is the test: two causes must render differently.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import advice_digest as ad  # noqa: E402


def _render(rows):
    from datetime import datetime, timezone  # noqa: PLC0415
    return "\n".join(ad.render("slot", {}, [], {}, None, {"rows": rows}, datetime.now(timezone.utc)))


def _row(title):
    return (1, "2026-11-04T10:00:00Z", "notification_intent_p3:research_lane_health", title, "body")


def test_two_causes_render_differently():
    deferred = _render([_row("DeepSeek DEFERRED_TO_OFFPEAK: queued, not provider failure")])
    broken = _render([_row("DeepSeek provider unavailable: critical failure")])
    assert deferred != broken, "the digest is invariant to the cause"
    assert "DEFERRED_TO_OFFPEAK" in deferred and "provider unavailable" in broken


def test_the_cause_is_rendered_beside_the_count():
    out = _render([_row("DeepSeek provider unavailable: critical failure")])
    assert "×1" in out and "provider unavailable" in out


def test_two_causes_in_one_kind_are_both_named():
    out = _render([_row("DeepSeek DEFERRED_TO_OFFPEAK: queued"), _row("DeepSeek provider unavailable: critical")])
    assert "×2" in out and "(+1 other cause)" in out, out


def test_a_row_with_no_title_says_so_rather_than_going_silent():
    out = _render([_row("")])
    assert "no cause recorded" in out, out


def test_the_headline_names_the_MOST_COMMON_cause_not_the_first_seen():
    """cc2 (2026-11-04): the first-seen cause headlined the group, so one deferral appearing first could name the batch
    ahead of three provider failures. The line must rank by frequency."""
    rows = [_row("DeepSeek DEFERRED_TO_OFFPEAK: queued")]
    rows += [_row("DeepSeek provider unavailable: critical failure")] * 3
    out = _render(rows)
    # only the ranked head is rendered; the minority cause is folded into the (+N) tail
    assert "×4 — DeepSeek provider unavailable" in out, out
    assert "(+1 other cause)" in out, out
