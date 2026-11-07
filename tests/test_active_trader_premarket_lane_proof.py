"""The premarket watch lane must prove its run, and must not be graded live while it sends nothing.

Measured 2026-11-07 against the live board. The lane showed ``status=late`` and
``quality=NOT_LIVE/shadow``. Two separate defects sat behind that row:

1. **late was false.** The cron line fires ``*/5 6-9`` but the script returns after
   09:29, so the registry declares ``scheduler.due_schedules`` (the fires whose output
   is due: 06:00–08:55 and 09:00–09:25). ``jobs_history`` expanded the raw cron
   expression instead, so at 09:30 the page compared a 09:25 output against a 09:55
   "latest scheduled time" and called a working lane late. (The fix belongs in
   ``scripts/lib/jobs_history.py``, held by another live claim — see the DONE report.)

2. **the heartbeat could not date its own run.** The cron line is not wrapped by
   ``safe_flock``, so nothing journals it, and ``run_quality.read_receipt`` reads the
   declared output document as the lane's receipt — a heartbeat that carried
   ``mode``/``as_of`` but no run timestamp. The page could only say "last at an
   unknown time", so a pass that evaluated 8 symbols and alerted on none was
   indistinguishable from a pass that never happened. This file pins the fields that
   make the heartbeat a datable receipt.

The third thing it pins is the mode. ``config/scalp_signal_engine.yaml`` has
``active_trader_premarket.mode: shadow`` since 2026-10-24 — journal only, **no
Telegram**. ``run_quality`` grades ``shadow`` as NOT_LIVE, which is the truth; the
heartbeat must keep reporting the run's real mode, never "live".

Hermetic: synthetic summaries and ``tmp_path``. No moomoo, no DB, no host state.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.active_trader import premarket_watch as pw  # noqa: E402
from scripts.cron_outage_watchdog import receipt_success  # noqa: E402
from scripts.lib import run_quality  # noqa: E402

REGISTRY = ROOT / "config" / "lane_registry.json"


def _lane_row() -> dict:
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    rows = [r for r in reg["lanes"] if r.get("lane_id") == pw.LANE_ID]
    assert len(rows) == 1, f"expected exactly one {pw.LANE_ID} row, found {len(rows)}"
    return rows[0]


def _heartbeat(mode="shadow", evaluated=8, alerts=0, state_changes=0):
    summary = {"as_of": "09:25", "mode": mode, "applied": True, "universe": 11, "pool": 11}
    if evaluated is not None:
        summary.update(evaluated=evaluated, alerts=alerts, sent=alerts, unvalidated=0)
    if state_changes is not None:
        summary["state_changes"] = state_changes
    return pw.heartbeat_doc(summary, started=datetime(2026, 11, 6, 14, 25, tzinfo=timezone.utc), at=1788787505.0)


def test_production_counts_alerts_not_symbols_examined():
    quiet = {"evaluated": 8, "alerts": 0, "sent": 0, "state_changes": 0}
    f = pw.receipt_fields(quiet)
    assert (f["produced_count"], f["attempted_count"]) == (0, 8)
    assert f["empty_reason"] == "no_alert_in_window"
    # a quiet slot is an idle slot, not an unexplained empty one
    assert run_quality._BENIGN_SKIP.search(f["empty_reason"])
    assert f["ok"] is True

    busy = {"evaluated": 11, "alerts": 2, "sent": 2, "state_changes": 1}
    f = pw.receipt_fields(busy)
    assert (f["produced_count"], f["attempted_count"], f["empty_reason"]) == (3, 11, None)


def test_a_pass_whose_every_tick_failed_is_not_ok():
    f = pw.receipt_fields({"ticks": 5, "tick_errors": 5, "evaluated": 0, "alerts": 0})
    assert f["ok"] is False and f["exit_code"] == 1
    assert f["error"] == "every tick failed"

    partial = pw.receipt_fields({"ticks": 5, "tick_errors": 1, "evaluated": 4, "alerts": 0})
    assert partial["ok"] is True, "one bad minute of five is degradation, not a failed run"


def test_the_heartbeat_dates_its_own_run():
    hb = _heartbeat()
    # the two keys run_quality needs to place the run on the clock (a bare "as_of": "09:25" is not a date)
    assert run_quality._at(hb["started_at"]) is not None
    assert run_quality._at(hb["finished_at"]) is not None
    assert run_quality.receipt_start(hb) == run_quality._at(hb["started_at"])


def test_only_a_sending_lane_claims_success_and_nothing_is_live_while_shadow():
    # receipt_success refuses a shadow receipt outright — a run that shipped nothing has not succeeded at
    # anything the operator can see. Pinned so nobody "fixes" the heartbeat into a false ok.
    assert receipt_success(_heartbeat("shadow"), None) is None
    success = receipt_success(_heartbeat("send"), None)
    assert success is not None and success[1].startswith("finished_at")


def test_the_heartbeat_carries_what_the_run_produced():
    hb = _heartbeat(evaluated=8, alerts=0, state_changes=0)
    assert run_quality.item_count(hb) == (0, "produced_count")
    assert hb["attempted_count"] == 8
    assert hb["empty_reason"] == "no_alert_in_window"

    busy = _heartbeat(evaluated=11, alerts=2, state_changes=1)
    assert run_quality.item_count(busy) == (3, "produced_count")


def test_a_shadow_lane_still_reads_shadow():
    # The whole point of the mode field: the config journals and sends nothing, so the page must not say live.
    assert run_quality.receipt_mode(_heartbeat("shadow")) == "shadow"
    assert run_quality.receipt_mode(_heartbeat("send")) == "live"


def test_existing_heartbeat_keys_are_untouched():
    # Consumers read ts_epoch, as_of, mode, cadence, applied, universe, pool, evaluated, alerts, sent, focus.
    hb = _heartbeat(evaluated=3, alerts=1, state_changes=0)
    for key, value in {"as_of": "09:25", "mode": "shadow", "applied": True, "universe": 11, "pool": 11,
                       "evaluated": 3, "alerts": 1, "sent": 1}.items():
        assert hb[key] == value, key


def test_the_lane_still_declares_the_heartbeat_it_writes():
    # The output signal stays the heartbeat: it advances every pass, which is what freshness reads, and
    # run_quality prefers the declared output document as the lane's receipt.
    assert Path(_lane_row()["output_signal"]["path"]).name == pw.HEARTBEAT_FILE
    src = (ROOT / "scripts" / "active_trader" / "premarket_watch.py").read_text(encoding="utf-8")
    assert "heartbeat_doc(summary" in src


def test_the_heartbeat_is_written_only_by_an_applying_run():
    src = (ROOT / "scripts" / "active_trader" / "premarket_watch.py").read_text(encoding="utf-8")
    write = src.index("**heartbeat_doc(summary")   # the call site, not the definition
    assert "if a.apply:" in src[write - 400:write]
