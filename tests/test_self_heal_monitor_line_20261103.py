"""Self-heal hourly block: the counts and the one-line verdict (operator request, 2026-11-03).

The block answers "is self-healing live and working" in one paste for the hourly email:
detected / dispatched / fixed / still blocked from the supervisor receipt and the incident
index, plus DETECT / DECIDE / FIX and a single lane verdict. Pure builder — fixtures only,
except the one ``main()`` test that points the reader at a fixture state root.

The regression tests below are the four findings from the cc-deepseek-3 WHOLEHEAD BLOCK at
754a3327b: a stale supervisor receipt, a future-dated watcher receipt, an unreadable store,
and a ``main()`` that could not be pointed at a test root.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.self_heal_monitor_line import build_block, main  # noqa: E402

NOW = datetime(2026, 11, 3, 17, 7, tzinfo=timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _index():
    return {
        "summary": {"counts": {"open": 10, "fixed": 529, "blocked": 27}, "unresolved": 10},
        "incidents": [
            {"id": "NEW1", "status": "open", "opened_at": _iso(NOW - timedelta(minutes=5))},
            {
                "id": "NEW2",
                "status": "fixed",
                "opened_at": _iso(NOW - timedelta(minutes=20)),
                "closed_at": _iso(NOW - timedelta(minutes=2)),
            },
            {"id": "OLD", "status": "blocked", "opened_at": _iso(NOW - timedelta(days=2))},
            {
                "id": "FIXED-OLD",
                "status": "fixed",
                "opened_at": _iso(NOW - timedelta(days=1)),
                "closed_at": _iso(NOW - timedelta(hours=3)),
            },
        ],
    }


def _empty_index():
    """A genuinely empty but well-formed index: zero is a measurement, not a guess."""
    return {"summary": {"counts": {"open": 0, "fixed": 0, "blocked": 0}, "unresolved": 0}, "incidents": []}


def _watchers(as_of=None, gap=None):
    return {
        "as_of": _iso(as_of or NOW - timedelta(minutes=2)),
        "watchers": {"health_tick": {"findings": 3, "gap": None}, "lane_health": {"findings": 16, "gap": gap}},
    }


def _supervisor(skips=("daily model-call cap",) * 5, dispatched=0, actions=0, as_of=None):
    return {
        "as_of": _iso(as_of or NOW - timedelta(minutes=3)),
        "considered": [f"INC{i}" for i in range(5)],
        "actions": [{}] * actions,
        "dispatched": [{}] * dispatched,
        "skipped": [{"why": w} for w in skips],
    }


def _fixer(state="fix_requested", n=5):
    return {"jobs": {f"job{i}": {"state": state} for i in range(n)}}


def _ok(**overrides):
    """Every input readable, DECIDE working and FIX idle; override one source per test."""
    args = dict(
        index=_index(),
        supervisor=_supervisor(skips=(), dispatched=2, actions=1),
        watchers=_watchers(),
        calls={"date": "2026-11-03", "count": 3},
        policy={"policy": {"max_model_calls_per_day": 240}},
        fixer=_fixer(n=0),
        now=NOW,
    )
    args.update(overrides)
    return build_block(**args)


# ── the shapes that were already right ────────────────────────────────────────────────────────


def test_starved_lane_reports_counts_and_the_cap():
    block = build_block(
        index=_index(),
        supervisor=_supervisor(),
        watchers=_watchers(),
        calls={"date": "2026-11-03", "count": 40},
        policy={"policy": {"max_model_calls_per_day": 40}},
        fixer=_fixer(),
        now=NOW,
    )
    assert block[0] == "SELF-HEAL · 17:07 UTC"
    assert block[1] == (
        "detected 2 (last hour) · dispatched 0 · fixed 1 (last hour) · still blocked 27 · unresolved 10"
    )
    assert "considered 5, actions 0, dispatched 0, skipped 5 (5 on daily model-call cap)" in block[2]
    assert "model calls today 40/40" in block[2]
    assert block[3].startswith("watchers ") and "2/2 without a gap" in block[3]
    assert block[4].startswith("verdict: NOT LIVE — DETECT alive · DECIDE starved by the daily model-call cap")
    assert block[4].endswith("FIX not scheduled (5 requests queued)")


def test_a_working_lane_says_alive_end_to_end():
    block = _ok()
    assert "dispatched 2" in block[1]
    assert "skipped 0 (0 on daily model-call cap)" in block[2]
    assert block[4] == ("verdict: LIVE — DETECT alive · DECIDE working · FIX no queue")


def test_a_watcher_gap_is_reported_not_hidden():
    block = _ok(watchers=_watchers(gap={"reason": "unreadable"}))
    assert "1/2 without a gap" in block[3]
    assert block[4].startswith("verdict: NOT LIVE — DETECT gapped")


def test_a_stale_watcher_receipt_is_not_alive():
    block = _ok(watchers=_watchers(as_of=NOW - timedelta(hours=1)))
    assert block[4].startswith("verdict: NOT LIVE — DETECT stale")


# ── F1: a supervisor receipt that has not moved is not "working" ─────────────────────────────


def test_a_stale_supervisor_receipt_is_not_working():
    """cc-deepseek-3 F1: 14 days old with skipped=[] used to read "DECIDE working" and LIVE."""
    block = _ok(supervisor=_supervisor(skips=(), as_of=NOW - timedelta(days=14)))
    assert "DECIDE stale" in block[4]
    assert "DECIDE working" not in block[4]
    assert block[4].startswith("verdict: NOT LIVE")
    assert "supervisor 2026-10-20T17:07:00Z" in block[2]


def test_a_future_dated_supervisor_receipt_is_skew_not_working():
    """The same rule at the other end: a receipt from the future is skew, not freshness."""
    block = _ok(supervisor=_supervisor(skips=(), as_of=NOW + timedelta(days=2)))
    assert "DECIDE future-dated" in block[4]
    assert "DECIDE working" not in block[4]
    assert block[4].startswith("verdict: NOT LIVE")


# ── F2: a future-dated watcher receipt is skew, not maximally fresh ──────────────────────────


def test_a_future_dated_watcher_receipt_is_skew_not_fresh():
    """cc-deepseek-3 F2: two days ahead gave a negative age and passed the <= 15 min test."""
    block = _ok(watchers=_watchers(as_of=NOW + timedelta(days=2)))
    assert "DETECT future-dated" in block[4]
    assert "DETECT alive" not in block[4]
    assert block[4].startswith("verdict: NOT LIVE")


# ── F3: an unreadable store is unknown, never a zero and never LIVE ──────────────────────────


def test_an_unreadable_store_is_unknown_not_zero():
    """cc-deepseek-3 F3: ``{}`` is what the old reader returned on a missing/torn store.

    The block used to print "detected 0 ... still blocked 0 ... unresolved 0" and a LIVE verdict.
    """
    block = build_block(index={}, supervisor={}, watchers={}, calls={}, policy={}, fixer={}, now=NOW)
    assert "detected unknown" in block[1]
    assert "detected 0" not in block[1]
    assert "still blocked unknown" in block[1]
    assert "unresolved unknown" in block[1]
    assert "model calls today unknown/unknown" in block[2]
    assert "/40" not in block[2]
    assert "DETECT unknown" in block[4]
    assert "DECIDE unknown" in block[4]
    assert "FIX unknown" in block[4]
    assert "DATA unknown" in block[4]
    assert block[4].startswith("verdict: NOT LIVE")


def test_an_unreadable_policy_does_not_invent_the_default_cap():
    """The same finding's cap arm: an unreadable runbook config must not print the literal 40."""
    block = _ok(policy={})
    assert "model calls today 3/unknown" in block[2]
    assert "/40" not in block[2]
    assert "DATA unknown" in block[4]
    assert block[4].startswith("verdict: NOT LIVE")


def test_an_unreadable_fixer_state_is_unknown_not_no_queue():
    block = _ok(fixer={})
    assert "FIX unknown" in block[4]
    assert "FIX no queue" not in block[4]
    assert block[4].startswith("verdict: NOT LIVE")


def test_a_genuinely_empty_index_reports_zero_not_unknown():
    """Guard against over-correcting: a well-formed empty index measured zero, honestly."""
    block = _ok(index=_empty_index())
    assert "detected 0 (last hour)" in block[1]
    assert "still blocked 0 · unresolved 0" in block[1]
    assert "unknown" not in block[1]


# ── F4: the reader can be pointed at a test root, and main() is exercised ────────────────────


def test_main_reads_the_state_root_and_reports_a_torn_index_as_unknown(tmp_path, monkeypatch, capsys):
    """cc-deepseek-3 F4: the state root was hardcoded and no test called main()."""
    now = datetime.now(timezone.utc)
    incidents = tmp_path / "data" / "coordination" / "incidents"
    runtime = tmp_path / "data" / "runtime"
    incidents.mkdir(parents=True)
    runtime.mkdir(parents=True)
    # A torn index is exactly the OSError/ValueError the old `_load` flattened to {}.
    (incidents / "index.json").write_text('{"incidents": [', encoding="utf-8")
    (incidents / "supervisor_last.json").write_text(
        json.dumps(
            {
                "as_of": _iso(now - timedelta(minutes=3)),
                "considered": [],
                "actions": [],
                "dispatched": [],
                "skipped": [],
            }
        ),
        encoding="utf-8",
    )
    (incidents / "watchers_last.json").write_text(
        json.dumps(
            {"as_of": _iso(now - timedelta(minutes=2)), "watchers": {"health_tick": {"findings": 0, "gap": None}}}
        ),
        encoding="utf-8",
    )
    (incidents / "supervisor_calls.json").write_text(
        json.dumps({"date": now.date().isoformat(), "count": 1}), encoding="utf-8"
    )
    (runtime / "self_heal_fixer_state.json").write_text(json.dumps({"jobs": {}}), encoding="utf-8")

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    rc = main([])
    out = capsys.readouterr().out

    assert rc == 0
    assert "detected unknown" in out
    assert "detected 0" not in out
    assert "index.json unreadable" in out
    assert "verdict: NOT LIVE" in out
    # The other inputs in the fixture root were readable and fresh; only the index is unknown.
    assert "DETECT alive" in out and "DECIDE working" in out and "FIX no queue" in out


# ── Codex Cloud round 2: a failed cycle is not healthy, a won't-fix is not a fix,
#    and yesterday's counter is not today's ──────────────────────────────────────────────────


def test_a_failed_triage_cycle_is_not_live():
    """CX1: every model call failed (model_error/unparseable); a fresh receipt is not healthy."""
    for reason in ("model_error", "unparseable"):
        block = _ok(supervisor=_supervisor(skips=(reason,) * 5))
        assert "DECIDE working" not in block[4]
        assert "DECIDE failing" in block[4]
        assert block[4].startswith("verdict: NOT LIVE")


def test_a_wont_fix_closure_is_not_a_fix():
    """CX2: status=closed/resolution=wont_fix has a recent closed_at but was not repaired."""
    index = _index()
    index["incidents"].append(
        {
            "id": "WONTFIX",
            "status": "closed",
            "resolution": "wont_fix",
            "opened_at": _iso(NOW - timedelta(days=1)),
            "closed_at": _iso(NOW - timedelta(minutes=1)),
        }
    )
    block = _ok(index=index)
    assert "fixed 1 (last hour)" in block[1]
    assert "fixed 2" not in block[1]


def test_a_stale_counter_date_is_not_today():
    """CX3: supervisor_calls.json keeps yesterday's count until the next call; the date gates it."""
    block = _ok(calls={"date": "2026-11-02", "count": 40})
    assert "model calls today 0/240" in block[2]
    assert "40/240" not in block[2]
