"""RECOVERY_MATERIAL_CHANGE_20261104 — a later material change is not swallowed by the repeat bound.

The per-case-per-day bound exists to stop REPEATS (operator ruling 2026-11-03: a T1 page is exempt
from the daily budget, at most one page per case per day). cc6's BLOCK (2026-11-04) found that it was
also suppressing a later, genuinely NEW fact in the same case and day, silently: the refusal lived
only in an in-memory list, and a page during the in-flight window left no record at all.

What this file pins:
* a page carries a material digest of the case's material facts (state/trigger/plan/… — not the
  volatile price or confidence);
* a repeat of the SAME material is suppressed (the lawful bound), and the suppression is DURABLE;
* a DIFFERENT material pages once more, and a repeat of that one is suppressed;
* past the per-case-day page allowance a further material change is recorded durably (never silent);
* during an in-flight attempt a material change is recorded durably with its own reason;
* a legacy page without a material token keeps the old one-page behaviour, with a durable record.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts", ROOT / "scripts" / "lib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import telegram_alert_router as router  # noqa: E402
from lib import recovery_notify as rn  # noqa: E402

DAY = router._budget_day()
BASE = {"symbol": "SPCX", "account": "schwab_roth_ira", "case_id": "SPCX-1", "state": "recovering",
        "price": 141.0, "exit_price": 137.19, "realized_loss_usd": 12770.0,
        "next_trigger": "reclaim 142", "eligibility": "taxable hold", "plan": "watch"}


@pytest.fixture
def pages(tmp_path, monkeypatch):
    path = tmp_path / "recovery_t1_pages.json"
    monkeypatch.setattr(router, "_RECOVERY_T1_PAGE_PATH", path)
    monkeypatch.setattr(router, "_budget_count_today", lambda: 10 ** 6)
    return path


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _message(**overrides) -> str:
    return rn.build_message({**BASE, **overrides})


def _deliver(message: str) -> None:
    assert router.route_intent(message, "P1", dedupe_minutes=0)["deliver"] is True
    router.recovery_t1_mark_delivered(message)


def test_the_material_digest_tracks_material_facts_not_the_volatile_price():
    a = rn.material_digest({**BASE, "price": 141.0})
    assert rn.material_digest({**BASE, "price": 999.0}) == a, "a price tick is not a material change"
    assert rn.material_digest({**BASE, "confidence": 0.41}) == a, "confidence is not a material change"
    assert rn.material_digest({**BASE, "state": "recovered"}) != a
    assert rn.material_digest({**BASE, "next_trigger": "reclaim 145"}) != a
    assert rn.material_digest({**BASE, "realized_loss_usd": 13000.0}) != a
    # And the page carries it, so the router (which only sees text) can tell.
    first_line = _message().splitlines()[0]
    assert f"material:{a}" in first_line
    assert f"case:{rn.case_token_for(rn.case_key_for(BASE))}" in first_line


def test_a_repeat_is_suppressed_and_the_refusal_is_durable(pages):
    first = _message()
    _deliver(first)
    again = router.route_intent(first, "P1", dedupe_minutes=0)
    assert again == {**again, "decision": "DEDUPED", "deliver": False}
    assert again["reason"] == "recovery_t1_daily_case_bound"
    suppressed = [r for r in _rows(pages) if r.get("state") == "suppressed"]
    assert suppressed and suppressed[-1]["reason"] == "recovery_t1_daily_case_bound"
    assert suppressed[-1].get("material") == rn.material_digest(BASE)
    assert suppressed[-1]["case"] == router._recovery_case_key(first)
    assert suppressed[-1]["day"] == DAY


def test_a_later_material_change_pages_once_and_its_repeat_is_suppressed(pages):
    _deliver(_message())
    changed = _message(state="recovered", next_trigger="reclaim 145", price=144.0)
    assert router.route_intent(changed, "P1", dedupe_minutes=0)["deliver"] is True
    router.recovery_t1_mark_delivered(changed)
    delivered = [r for r in _rows(pages) if r.get("state") == "delivered"]
    assert [r.get("material") for r in delivered] == [rn.material_digest(BASE),
                                                       rn.material_digest({**BASE, "state": "recovered",
                                                                           "next_trigger": "reclaim 145"})]
    repeat = router.route_intent(changed, "P1", dedupe_minutes=0)
    assert repeat["deliver"] is False and repeat["reason"] == "recovery_t1_daily_case_bound"
    assert any(r.get("state") == "suppressed" and r.get("reason") == "recovery_t1_daily_case_bound"
               for r in _rows(pages))


def test_the_page_allowance_still_bounds_the_case_and_the_extra_change_is_recorded(pages):
    _deliver(_message())
    second = _message(state="recovered", next_trigger="reclaim 145")
    _deliver(second)
    third = _message(state="triggered", next_trigger="reclaim 150")
    blocked = router.route_intent(third, "P1", dedupe_minutes=0)
    assert blocked["deliver"] is False
    assert blocked["reason"] == "recovery_t1_material_change_cap"
    row = [r for r in _rows(pages) if r.get("state") == "suppressed"][-1]
    assert row["reason"] == "recovery_t1_material_change_cap"
    assert row["material"] == rn.material_digest({**BASE, "state": "triggered", "next_trigger": "reclaim 150"})
    # Exactly two pages for the case-day, whatever the number of distinct materials seen.
    assert len([r for r in _rows(pages) if r.get("state") == "delivered"]) == 2


def test_a_material_change_during_the_in_flight_window_is_recorded_and_pages_afterwards(pages):
    first = _message(case_id="SPCX-2")
    assert router.recovery_t1_claim(first) is True          # an attempt is in flight, not delivered
    changed = _message(case_id="SPCX-2", state="triggered")
    # The preview no longer returns a bare False: it records WHY, durably (cc6 P2).
    assert router.should_send_telegram(changed, consume=False) is True  # nothing delivered blocks it
    in_flight = router.route_intent(changed, "P1", dedupe_minutes=0)
    assert in_flight["deliver"] is False
    assert in_flight["reason"] == "recovery_t1_material_change_in_flight"
    row = [r for r in _rows(pages) if r.get("state") == "suppressed"][-1]
    assert row["reason"] == "recovery_t1_material_change_in_flight"
    assert row["material"] == rn.material_digest({**BASE, "case_id": "SPCX-2", "state": "triggered"})
    # Once the in-flight attempt settles, the new material is allowed to page.
    router.recovery_t1_mark_delivered(first)
    assert router.route_intent(changed, "P1", dedupe_minutes=0)["deliver"] is True


def test_a_repeat_preview_during_the_in_flight_window_is_recorded_not_bare_false(pages):
    msg = _message(case_id="SPCX-3")
    assert router.recovery_t1_claim(msg) is True
    assert router.should_send_telegram(msg, consume=False) is False
    row = [r for r in _rows(pages) if r.get("state") == "suppressed"][-1]
    assert row["reason"] == "recovery_t1_daily_case_bound"
    assert row["material"] == rn.material_digest({**BASE, "case_id": "SPCX-3"})


def test_a_legacy_page_without_a_material_token_keeps_the_one_page_behaviour(pages):
    # A producer that has not been updated still gets the operator's one-page-per-case-day rule, and
    # its refusal is durable too (the record simply carries no material digest).
    legacy = "[[RECOVERY_T1]] Recovery: SPCX · case:legacy-case-1\nstate: recovering\nNo order is placed."
    assert router.should_send_telegram(legacy, consume=True) is True
    router.recovery_t1_mark_delivered(legacy)
    assert router.route_intent(legacy, "P1", dedupe_minutes=0)["deliver"] is False
    row = [r for r in _rows(pages) if r.get("state") == "suppressed"][-1]
    assert row["reason"] == "recovery_t1_daily_case_bound"
    assert "material" not in row


def test_the_batching_path_carries_the_material_digest_and_the_floor_is_per_material(monkeypatch):
    """When telegram_batch is present the page is a header + items; that header must carry the digest,
    and the repeat floor's key must be per material, or the router never sees a material change."""
    import types

    fake = types.ModuleType("lib.telegram_batch")
    seen = {}

    class NudgeState:
        def __init__(self, path):
            pass

        def due(self, keys, now, floor):
            return True

        def note(self, keys, now):
            return self

        def save(self, state):
            pass

    def batch_text(header, items):
        return header + "\n" + "\n".join(str(item.get("title") or "") for item in items)

    def nudge_decision(keys, state, now, priority, floor_minutes):
        seen["keys"] = list(keys)
        return {"send": True}

    fake.NudgeState, fake.batch_text, fake.nudge_decision = NudgeState, batch_text, nudge_decision
    monkeypatch.setitem(sys.modules, "lib.telegram_batch", fake)
    sent = {}

    def sender(body, **kwargs):
        sent["body"] = body
        return True

    case = {**BASE, "case_id": "SPCX-BATCH", "materiality_tier": "T1"}
    result = rn.notify_recovery_case(case, sender=sender)
    assert result["path"] == "batch" and result["sent"] is True
    digest = rn.material_digest(case)
    assert f"material:{digest}" in sent["body"]
    assert seen["keys"][0].endswith(digest), seen["keys"]
