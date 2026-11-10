"""LQ-20261107-1808 item 4 — a failed lane read says "cannot be read", never `[]`.

`_db_rows` caught every exception and returned `[]`, so a blind monitor produced the same row as a
lane that genuinely wrote nothing, and `evaluate_lane` fired `zero_non_error_24h` at the lane for the
monitor's own failure (Constitution Rules 8 and 11: silent failure is SEV-1; unknown beats wrong).

These tests pin the two directions apart:
  * a read that raises  -> a NOT_MEASURED row whose firing string carries the reason, counters None;
  * a read that returns no rows -> unchanged: `[]` is still a real fact about the lane.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timezone

import pytest

from scripts.lib import research_lane_health as rla

NOW = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)
SINCE = datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc)


def _install_adapter(monkeypatch, execute):
    """A synthetic `db_adapter`. The module under test imports it by its bare name."""
    mod = types.ModuleType("db_adapter")
    mod._execute = execute  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "db_adapter", mod)


def _blind(*_a, **_kw):
    raise ConnectionRefusedError("connection refused by 127.0.0.1:5432")


def test_db_rows_failure_raises_named_reason(monkeypatch):
    _install_adapter(monkeypatch, _blind)

    with pytest.raises(rla.RowsUnreadable) as ei:
        rla._db_rows("select 1")

    msg = str(ei.value)
    assert msg.startswith("cannot be read: ")
    assert "ConnectionRefusedError" in msg
    assert "connection refused" in msg


def test_db_rows_bounds_the_reason(monkeypatch):
    def _verbose(*_a, **_kw):
        raise RuntimeError("x" * 5000)

    _install_adapter(monkeypatch, _verbose)

    with pytest.raises(rla.RowsUnreadable) as ei:
        rla._db_rows("select 1")

    assert len(str(ei.value)) < 300, "a 5000-char driver message must not be pasted into an alert"


def test_db_rows_empty_read_stays_empty(monkeypatch):
    """No rows is a fact about the lane, not a failure — it must not be turned into an error."""
    _install_adapter(monkeypatch, lambda *_a, **_kw: [])

    assert rla._db_rows("select 1") == []


def test_evaluated_lane_renders_unreadable_not_zero():
    def _loader(_lane, *, since):  # noqa: ARG001
        raise rla.RowsUnreadable("cannot be read: OperationalError: could not connect to server")

    row = rla._evaluated_lane(_loader, "deepseek", since=SINCE, silence=True, now=NOW)

    assert row["lane"] == "deepseek"
    assert row["ok"] is False
    assert row["measured"] is False
    assert row["firing"] == ["cannot be read: OperationalError: could not connect to server"]
    assert not any("zero_non_error" in f for f in row["firing"]), (
        "a blind read must not accuse the lane of silence (the 2026-11-10 defect)"
    )
    for key in ("error_streak", "non_error_24h", "attempts_24h", "error_24h",
                "skipped_budget_24h", "refused_24h", "error_rate_24h"):
        assert row[key] is None, f"{key} must be unmeasured (None), never 0"


def test_evaluated_lane_unchanged_when_rows_are_read():
    """The healthy path keeps exactly the old shape — no `measured` key, real counters."""
    rows = [{"recommendation": "Hold SCHD", "created_at": NOW}]

    def _loader(_lane, *, since):  # noqa: ARG001
        return rows, rows

    row = rla._evaluated_lane(_loader, "deepseek", since=SINCE, silence=True, now=NOW)

    assert "measured" not in row
    assert row["ok"] is True
    assert row["non_error_24h"] == 1
    assert row["attempts_24h"] == 1


def test_overnight_row_carries_the_read_failure(monkeypatch):
    def _blind_overnight(*, since):  # noqa: ARG001
        raise rla.RowsUnreadable("cannot be read: InterfaceError: connection already closed")

    monkeypatch.setattr(rla, "load_overnight_rows", _blind_overnight)

    row = rla._overnight_row(since=SINCE, now=NOW)

    assert row["lane"] == rla.OVERNIGHT_LANE
    assert row["measured"] is False
    assert row["firing"] == ["cannot be read: InterfaceError: connection already closed"]
    assert "provider_verdict" not in row, "no live probe is claimed for a lane whose rows were not read"


def test_fix_hint_names_the_read_failure_not_the_lane():
    """The operator hint for an unmeasured lane must point at the monitor, not at the lane's code."""
    import research_lane_health as hl

    row = rla.unreadable_lane(
        "deepseek", rla.RowsUnreadable("cannot be read: OperationalError: could not connect to server"))

    hint = hl.fix_hint(row)

    assert "could not be read" in hint
    assert "could not connect to server" in hint
    assert "CAUSE NOT DIAGNOSED" not in hint, "the cause is known: the read failed"
    assert "budget_throttled" not in hint and "DeepSeek:" not in hint, (
        "an unread row must not inherit the lane's own behaviour hint"
    )


def test_collect_report_never_reports_a_blind_lane_as_quiet(monkeypatch):
    """The wiring: a raising loader reaches the report as NOT_MEASURED for every row it serves."""
    monkeypatch.setattr(rla, "load_external_rows", _blind)
    monkeypatch.setattr(rla, "load_overnight_rows",
                        lambda *, since: (_ for _ in ()).throw(  # noqa: ARG005
                            rla.RowsUnreadable("cannot be read: RuntimeError: pool exhausted")))
    for flag in ("RESEARCH_LANE_HEALTH_PIN", "RESEARCH_LANE_HEALTH_DRIVE",
                 "RESEARCH_LANE_HEALTH_COVERAGE_STALL", "RESEARCH_LANE_HEALTH_REGISTRY",
                 "RESEARCH_LANE_HEALTH_SEARCH", "RESEARCH_LANE_HEALTH_CIO_HERMES"):
        monkeypatch.setenv(flag, "0")
    monkeypatch.setenv("RESEARCH_LANE_HEALTH_OVERNIGHT", "1")

    # The identity collector is unconditional; its module import is patched at the source.
    import scripts.lib.identity_health as ih
    monkeypatch.setattr(ih, "collect_identity_health", lambda now=None: {
        "lane": "identity-spine", "ok": True, "firing": [], "as_of": NOW.isoformat()})

    report = rla.collect_report(
        now=NOW,
        cio_ask_health_reader=lambda now=None: {
            "lane": "cio-ask", "ok": True, "firing": [], "as_of": NOW.isoformat()},
    )

    blind = [r for r in report["lanes"] if r.get("measured") is False]
    assert {r["lane"] for r in blind} == set(rla.EXTERNAL_AUTO_LANES) | set(rla.EXTERNAL_MANUAL_LANES) | {
        rla.OVERNIGHT_LANE}
    for row in blind:
        assert row["firing"] and str(row["firing"][0]).startswith("cannot be read: "), row
        assert row["non_error_24h"] is None and row["attempts_24h"] is None
    # Every blind lane is also named in the report's firing list — the alarm still reaches the operator.
    assert set(report["firing"]) == {r["lane"] for r in blind}
    assert report["ok"] is False


# ── should-fix 7 (r2): the coverage stall may not read an uncounted flow as zero ──────────────────────────


def _measured(ok):
    return {"lane": "deepseek", "ok": True, "firing": [], "non_error_24h": ok, "attempts_24h": ok}


def test_an_unreadable_deepseek_row_is_unmeasured_not_zero():
    """``unreadable_lane`` carries ``non_error_24h=None``; reading it as 0 invented a count (should-fix 7)."""
    row = rla.unreadable_lane("deepseek", rla.RowsUnreadable("cannot be read: OperationalError: down"))
    assert rla._deepseek_ok([row]) is None


def test_an_absent_or_countless_deepseek_row_is_unmeasured():
    assert rla._deepseek_ok([]) is None
    assert rla._deepseek_ok([{"lane": "grok", "non_error_24h": 9}]) is None
    assert rla._deepseek_ok([{"lane": "deepseek"}]) is None
    assert rla._deepseek_ok([{"lane": "deepseek", "non_error_24h": "n/a"}]) is None


def test_a_measured_zero_is_still_a_zero():
    """A lane that really did produce nothing is measured — the hold is for unknown, not for bad news."""
    assert rla._deepseek_ok([_measured(0)]) == 0
    assert rla._deepseek_ok([_measured(33)]) == 33


def test_the_stall_holds_and_names_the_missing_measurement():
    row = rla.collect_coverage_stall(
        now=NOW, deepseek_ok_24h=None, thesis_substantive=6, thesis_coverage=22, thesis_held=23,
        persist=False,
    )

    assert row["ok"] is True, "a flat thesis count may not be charged to a research flow nobody counted"
    assert row["firing"] == []
    assert str(row["held_by"]).startswith("research_ok_unmeasured:")
    assert row["non_error_24h"] is None and row["attempts_24h"] is None
    assert row["thesis_substantive"] == 6 and row["thesis_held"] == 23


def test_a_measured_count_still_fires_and_a_zero_does_not():
    fired = rla.collect_coverage_stall(
        now=NOW, deepseek_ok_24h=33, thesis_substantive=6, thesis_coverage=22, thesis_held=23,
        persist=False,
    )
    assert fired["firing"] and fired["firing"][0].startswith("research_up_thesis_flat:")

    quiet = rla.collect_coverage_stall(
        now=NOW, deepseek_ok_24h=0, thesis_substantive=6, thesis_coverage=22, thesis_held=23,
        persist=False,
    )
    assert quiet["ok"] is True and quiet["held_by"] is None
    assert quiet["non_error_24h"] == 0, "a measured zero stays on the row as 0"


def test_a_broken_leg_keeps_its_own_held_by():
    """The unhealthy-leg hold is the more specific cause and must not be overwritten by 'unmeasured'."""
    row = rla.collect_coverage_stall(
        now=NOW, deepseek_ok_24h=None, thesis_substantive=6, thesis_held=23, persist=False,
        research_leg={"attempts_24h": 183, "error_rate_24h": 84.2, "non_error_24h": 29},
    )
    assert str(row["held_by"]).startswith("research_lane_unhealthy:")


def test_an_unmeasured_run_does_not_reset_the_baseline(tmp_path):
    """The snapshot is the next run's ``>= prev`` baseline; persisting None would reset it to zero."""
    from pathlib import Path

    snap = Path(tmp_path) / "coverage_stall_snapshot.json"
    rla.collect_coverage_stall(now=NOW, deepseek_ok_24h=30, thesis_substantive=6, thesis_held=23,
                               snap_path=snap)
    assert '"deepseek_ok_24h": 30' in snap.read_text()

    import json
    before = json.loads(snap.read_text())
    rla.collect_coverage_stall(now=NOW, deepseek_ok_24h=None, thesis_substantive=6, thesis_held=23,
                               snap_path=snap)
    assert json.loads(snap.read_text()) == before, "an unmeasured run must leave the last measured baseline"
