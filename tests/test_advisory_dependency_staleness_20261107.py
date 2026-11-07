"""The advisory desk tells the truth about stale dependency clocks (LQ-20261107-242). Synthetic clocks only."""
from scripts import api_v3_advisory as adv


def clock(label, age_s, as_of, stale_after=64800):
    return {"label": label, "source_as_of": as_of, "age_seconds": age_s,
            "stale_after_seconds": stale_after, "freshness": "STALE" if age_s > stale_after else "FRESH",
            "refreshed_by_run_now": False}


def test_summary_does_not_claim_all_clear_when_the_synthesis_itself_is_stale():
    clocks = {
        "advisory_synthesis": clock("synthesis", 80 * 86400, "2026-01-01T00:00:00+00:00"),
        "prices": clock("prices", 300, "2026-03-22T00:00:00+00:00", 6 * 3600),
        "watch_intelligence": clock("watch intelligence", 66 * 86400, "2026-01-15T00:00:00+00:00", 96 * 3600),
    }
    out = adv._dependency_refresh(clocks)
    assert out["status"] == "DEPENDENCIES_AT_OR_AFTER_SYNTHESIS"
    assert out["stale"] == ["advisory_synthesis", "watch_intelligence"]
    assert "every dependency clock is at or after the synthesis" not in out["summary"]
    assert "synthesis 80d old" in out["summary"] and "watch intelligence 66d old" in out["summary"]


def test_summary_keeps_the_all_clear_when_nothing_is_stale():
    clocks = {"advisory_synthesis": clock("synthesis", 3600, "2026-03-22T00:00:00+00:00"),
              "prices": clock("prices", 300, "2026-03-22T01:00:00+00:00", 6 * 3600)}
    assert adv._dependency_refresh(clocks)["summary"] == "every dependency clock is at or after the synthesis"


def test_older_dependencies_still_win_the_summary():
    clocks = {"advisory_synthesis": clock("synthesis", 100, "2026-03-22T10:00:00+00:00"),
              "prices": clock("prices", 90000, "2026-03-21T10:00:00+00:00", 6 * 3600)}
    assert "older than synthesis" in adv._dependency_refresh(clocks)["summary"]


def test_a_retired_synthesis_producer_names_itself_instead_of_schedule_unavailable(monkeypatch):
    import lib.cio_source_clocks as c
    monkeypatch.setattr(c, "next_scheduled_run", lambda lanes, **k: {"next_run_at": None, "reason": f"{list(lanes)[0]}: lane state RETIRED"})
    why = adv._synthesis_schedule_reason({"timer_unit": "tradeai-advisory-shadow-session.timer"})
    assert "retired" in why and "Run now" in why and "tradeai-advisory-shadow-session" in why


def test_an_unknown_reason_keeps_the_old_text(monkeypatch):
    import lib.cio_source_clocks as c
    monkeypatch.setattr(c, "next_scheduled_run", lambda lanes, **k: {"next_run_at": None, "reason": "x: not in lane_registry"})
    assert adv._synthesis_schedule_reason({"timer_unit": "u.timer"}) == "advisory schedule unavailable"
    assert adv._synthesis_schedule_reason({}) == "advisory schedule unavailable"
