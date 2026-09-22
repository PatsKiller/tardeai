"""Burn-rate alerting must page fast, ticket slow, and shut up on no traffic.

WHY THESE TESTS LOOK THE WAY THEY DO
------------------------------------
An earlier draft of this calculator was wrong in three ways that all LOOKED
right: ``window_seconds`` was stored and never read, ``consumed_budget_pct``
was ``burn_rate * 100``, and config validation lived in the evaluator instead
of the config. Every one of those passes a test suite that only asserts "a
PAGE came out when I fed it a disaster". So each has a dedicated negative
control here:

* ``test_window_seconds_selects_the_sample``    — fails if the field stops routing
* ``test_window_length_changes_the_verdict``    — fails if the field stops deciding
* ``test_consumed_budget_is_not_rate_times_100``— pins the 14.4 -> 2% identity
* ``test_a_bad_target_raises_from_the_config``  — pins WHERE the ValueError comes from

The math assertions are unconditional. The feed assertions are gated on a
fixture that skips when no database is reachable, because CI is hermetic — a
test that can only pass with a database attached does not belong in a
hermetic gate, and one that silently passes because it skipped everything is
worse.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.slo_burn_rate import (  # noqa: E402
    SEVERITY_PAGE,
    SEVERITY_TICKET,
    STATUS_INSUFFICIENT_DATA,
    STATUS_NO_DATA,
    STATUS_OK,
    BurnRateTier,
    SLOConfig,
    WindowSample,
    burn_rate,
    consumed_budget_pct,
    evaluate,
    freshness_window_sample,
    load_slo_configs,
)

CONFIG_PATH = ROOT / "config" / "slo_targets.json"
REPORTER = ROOT / "scripts" / "report_slo_burn_rate.py"

PAGE_TIER = BurnRateTier(
    label="fast_page", long_window_seconds=3600, short_window_seconds=300, threshold=14.4, severity="PAGE"
)
SLOW_PAGE_TIER = BurnRateTier(
    label="slow_page", long_window_seconds=21600, short_window_seconds=1800, threshold=6.0, severity="PAGE"
)
TICKET_TIER = BurnRateTier(
    label="fast_ticket", long_window_seconds=86400, short_window_seconds=7200, threshold=3.0, severity="TICKET"
)


def _config(*tiers: BurnRateTier, target: float = 0.99, min_events: int = 10) -> SLOConfig:
    return SLOConfig(
        name="probe",
        description="synthetic",
        slo_target=target,
        period_days=30,
        tiers=tiers or (PAGE_TIER, TICKET_TIER),
        min_events=min_events,
    )


def _samples(pairs: dict[int, tuple[int, int]]) -> dict[int, WindowSample]:
    """{window_seconds: (good, total)} -> samples."""
    return {w: WindowSample(window_seconds=w, good=g, total=t) for w, (g, t) in pairs.items()}


# ---------------------------------------------------------------- math: burn


def test_burn_rate_is_failure_rate_over_budget():
    """1% budget, 10% failing -> burning 10x."""
    assert burn_rate(good=900, total=1000, slo_target=0.99) == pytest.approx(10.0)
    assert burn_rate(good=1000, total=1000, slo_target=0.99) == pytest.approx(0.0)
    # Everything failing burns at exactly 1/budget.
    assert burn_rate(good=0, total=50, slo_target=0.99) == pytest.approx(100.0)


def test_burn_rate_refuses_an_empty_window():
    """Zero events is not zero burn — it is no measurement."""
    with pytest.raises(ValueError):
        burn_rate(good=0, total=0, slo_target=0.99)


def test_consumed_budget_is_not_rate_times_100():
    """THE identity that makes the Workbook's thresholds mean anything.

    Burn rate 14.4 sustained for 1h against a 30-day budget consumes 2% of it.
    The wrong implementation returns 1440.
    """
    got = consumed_budget_pct(14.4, window_seconds=3600, period_seconds=30 * 86400)
    assert got == pytest.approx(2.0, abs=1e-9)
    assert got != pytest.approx(1440.0)
    # And the rest of the table, which is the same arithmetic.
    assert consumed_budget_pct(6.0, 6 * 3600, 30 * 86400) == pytest.approx(5.0, abs=1e-9)
    assert consumed_budget_pct(3.0, 24 * 3600, 30 * 86400) == pytest.approx(10.0, abs=1e-9)
    assert consumed_budget_pct(1.0, 72 * 3600, 30 * 86400) == pytest.approx(10.0, abs=1e-9)


def test_consumed_budget_depends_on_window_length():
    """Same rate, longer window, strictly more budget spent."""
    period = 30 * 86400
    one_hour = consumed_budget_pct(6.0, 3600, period)
    six_hours = consumed_budget_pct(6.0, 6 * 3600, period)
    assert six_hours == pytest.approx(one_hour * 6)
    assert six_hours > one_hour


# ------------------------------------------------------- verdicts: the table


def test_fast_burn_pages():
    """100% failing across 1h and 5m -> burn 100x, way over 14.4."""
    cfg = _config(PAGE_TIER, TICKET_TIER)
    verdict = evaluate(cfg, _samples({3600: (0, 500), 300: (0, 40), 86400: (0, 5000), 7200: (0, 900)}))
    assert verdict["status"] == SEVERITY_PAGE
    assert "fast_page" in verdict["fired_tiers"]
    fast = next(t for t in verdict["tiers"] if t["label"] == "fast_page")
    assert fast["status"] == SEVERITY_PAGE
    assert fast["long"]["burn_rate"] == pytest.approx(100.0)


def test_slow_burn_tickets_and_does_not_page():
    """A 5x burn clears the 3x ticket tier but not the 14.4x or 6x page tiers."""
    cfg = _config(PAGE_TIER, SLOW_PAGE_TIER, TICKET_TIER)
    # 5% failing against a 1% budget = 5x, everywhere.
    pairs = {w: (95 * n, 100 * n) for w, n in ((3600, 10), (300, 10), (21600, 10), (1800, 10),
                                               (86400, 10), (7200, 10))}
    verdict = evaluate(cfg, _samples(pairs))
    assert verdict["status"] == SEVERITY_TICKET
    assert verdict["fired_tiers"] == ["fast_ticket"]
    by_label = {t["label"]: t for t in verdict["tiers"]}
    assert by_label["fast_page"]["status"] == STATUS_OK
    assert by_label["slow_page"]["status"] == STATUS_OK  # 5x < 6x
    assert by_label["fast_ticket"]["status"] == SEVERITY_TICKET


def test_a_healthy_slo_is_ok():
    cfg = _config(PAGE_TIER, TICKET_TIER)
    pairs = {w: (1000, 1000) for w in (3600, 300, 86400, 7200)}
    assert evaluate(cfg, _samples(pairs))["status"] == STATUS_OK


def test_insufficient_traffic_suppresses_instead_of_paging():
    """THE negative control for alert storms.

    Three events, all failed, is a 100x burn rate — and it is also noise. The
    tier must be suppressed, and the overall verdict must NOT be a page.
    """
    cfg = _config(PAGE_TIER, min_events=10)
    verdict = evaluate(cfg, _samples({3600: (0, 3), 300: (0, 1)}))
    assert verdict["status"] == STATUS_INSUFFICIENT_DATA
    assert verdict["fired_tiers"] == []
    tier = verdict["tiers"][0]
    assert tier["status"] == STATUS_INSUFFICIENT_DATA
    assert "min_events=10" in tier["why"]


def test_one_thin_window_suppresses_the_whole_tier():
    """A fat long window cannot carry a starved short window into a page."""
    cfg = _config(PAGE_TIER, min_events=10)
    verdict = evaluate(cfg, _samples({3600: (0, 5000), 300: (0, 2)}))
    assert verdict["status"] == STATUS_INSUFFICIENT_DATA
    assert verdict["fired_tiers"] == []


def test_a_burn_that_stopped_does_not_keep_paging():
    """The short window is the 'is it STILL burning?' half.

    Long window still shows the incident, short window is clean -> no page.
    This is what stops a one-minute outage latching an alert for an hour.
    """
    cfg = _config(PAGE_TIER)
    verdict = evaluate(cfg, _samples({3600: (0, 500), 300: (40, 40)}))
    assert verdict["status"] == STATUS_OK
    tier = verdict["tiers"][0]
    assert tier["status"] == STATUS_OK
    assert "short window" in tier["why"]


# ------------------------------------------- negative controls: window_seconds


def test_window_seconds_selects_the_sample():
    """Samples are joined BY window_seconds.

    If the field stopped routing — if evaluate grabbed whatever sample was
    handy — this would come back PAGE instead of NO_DATA.
    """
    cfg = _config(PAGE_TIER)  # wants 3600 and 300
    verdict = evaluate(cfg, _samples({21600: (0, 5000), 1800: (0, 500)}))
    assert verdict["status"] == STATUS_INSUFFICIENT_DATA
    assert verdict["tiers"][0]["status"] == STATUS_NO_DATA


def test_window_length_changes_the_verdict():
    """THE test that fails if window_seconds becomes decorative.

    Same target, same threshold, same samples, same everything except which
    windows the tier names. The 1h window is on fire; the 6h window is clean.
    A calculator that ignored window_seconds could not tell these apart.
    """
    samples = _samples(
        {
            3600: (0, 500),      # last hour: everything failed
            300: (0, 40),
            21600: (6000, 6000),  # last six hours: clean
            1800: (500, 500),
        }
    )
    hot = SLOConfig(name="probe", description="", slo_target=0.99, period_days=30,
                    tiers=(PAGE_TIER,), min_events=10)
    cool = SLOConfig(name="probe", description="", slo_target=0.99, period_days=30,
                     tiers=(BurnRateTier(label="fast_page", long_window_seconds=21600,
                                         short_window_seconds=1800, threshold=14.4,
                                         severity="PAGE"),), min_events=10)
    assert evaluate(hot, samples)["status"] == SEVERITY_PAGE
    assert evaluate(cool, samples)["status"] == STATUS_OK


def test_the_same_burn_rate_reports_different_budget_by_window():
    """Two tiers, identical burn, different windows -> different budget spend."""
    cfg = _config(PAGE_TIER, SLOW_PAGE_TIER, min_events=5)
    pairs = {w: (90, 100) for w in (3600, 300, 21600, 1800)}  # 10x everywhere
    verdict = evaluate(cfg, _samples(pairs))
    by_label = {t["label"]: t for t in verdict["tiers"]}
    one_hour = by_label["fast_page"]["long"]["consumed_budget_pct"]
    six_hour = by_label["slow_page"]["long"]["consumed_budget_pct"]
    assert by_label["fast_page"]["long"]["burn_rate"] == by_label["slow_page"]["long"]["burn_rate"]
    # rel is loose because the receipt rounds to 4 dp; the claim under test is
    # the 6x relationship, not the rounding.
    assert six_hour == pytest.approx(one_hour * 6, rel=1e-3)


# ------------------------------------------------ validation lives in config


def test_a_bad_target_raises_from_the_config():
    """The caller constructs a config; the config is what must refuse.

    A target of exactly 1.0 leaves a zero error budget — every burn-rate
    division would be by zero.
    """
    for bad in (1.0, 0.0, -0.5, 1.5):
        with pytest.raises(ValueError):
            SLOConfig(name="p", description="", slo_target=bad, period_days=30,
                      tiers=(PAGE_TIER,), min_events=1)


def test_other_malformed_config_also_raises_at_construction():
    with pytest.raises(ValueError):  # no period
        SLOConfig(name="p", description="", slo_target=0.99, period_days=0, tiers=(PAGE_TIER,), min_events=1)
    with pytest.raises(ValueError):  # no tiers
        SLOConfig(name="p", description="", slo_target=0.99, period_days=30, tiers=(), min_events=1)
    with pytest.raises(ValueError):  # unnamed
        SLOConfig(name="", description="", slo_target=0.99, period_days=30, tiers=(PAGE_TIER,), min_events=1)
    with pytest.raises(ValueError):  # min_events below 1 would divide noise
        SLOConfig(name="p", description="", slo_target=0.99, period_days=30, tiers=(PAGE_TIER,), min_events=0)
    with pytest.raises(ValueError):  # window longer than the budget period
        SLOConfig(name="p", description="", slo_target=0.99, period_days=1,
                  tiers=(BurnRateTier(label="slow_ticket", long_window_seconds=259200,
                                      short_window_seconds=21600, threshold=1.0,
                                      severity="TICKET"),), min_events=1)


def test_a_non_workbook_window_pair_is_rejected():
    """A short window that is not ~1/12 of the long one makes the shared
    threshold meaningless — and makes window_seconds decorative by the back door."""
    with pytest.raises(ValueError):
        BurnRateTier(label="bad", long_window_seconds=86400, short_window_seconds=82800,
                     threshold=3.0, severity="TICKET")
    with pytest.raises(ValueError):  # short >= long
        BurnRateTier(label="bad", long_window_seconds=300, short_window_seconds=3600,
                     threshold=3.0, severity="PAGE")
    with pytest.raises(ValueError):  # severity is not free text
        BurnRateTier(label="bad", long_window_seconds=3600, short_window_seconds=300,
                     threshold=3.0, severity="WARN")


def test_sample_refuses_impossible_counts():
    with pytest.raises(ValueError):
        WindowSample(window_seconds=3600, good=10, total=5)


# --------------------------------------------------------- freshness bucketing


def test_a_dead_feed_scores_zero_not_a_hundred():
    """Counting rows would score a silent producer as perfect. Buckets do not."""
    now = 1_000_000.0
    sample = freshness_window_sample(
        event_times=[now - 500_000], now=now, window_seconds=3600,
        bucket_seconds=60, staleness_budget_seconds=7200,
    )
    assert sample.total == 60
    assert sample.good == 0


def test_a_live_feed_scores_full():
    now = 1_000_000.0
    events = [now - i * 60 for i in range(200)]
    sample = freshness_window_sample(
        event_times=events, now=now, window_seconds=3600,
        bucket_seconds=60, staleness_budget_seconds=7200,
    )
    assert (sample.good, sample.total) == (60, 60)


def test_freshness_window_seconds_drives_the_bucket_count():
    """Window length is the denominator; the field cannot go unread here either."""
    now = 1_000_000.0
    events = [now - i * 60 for i in range(2000)]
    short = freshness_window_sample(event_times=events, now=now, window_seconds=3600,
                                    bucket_seconds=60, staleness_budget_seconds=7200)
    long = freshness_window_sample(event_times=events, now=now, window_seconds=21600,
                                   bucket_seconds=60, staleness_budget_seconds=7200)
    assert short.total == 60
    assert long.total == 360
    assert long.total == short.total * 6


def test_a_gap_in_the_middle_is_scored_stale():
    """The producer stopped for an hour, then came back."""
    now = 1_000_000.0
    # rows every minute for the last 30 min, and before a 60-min hole
    events = [now - i * 60 for i in range(30)] + [now - 90 * 60 - i * 60 for i in range(30)]
    sample = freshness_window_sample(event_times=events, now=now, window_seconds=7200,
                                     bucket_seconds=60, staleness_budget_seconds=600)
    assert 0 < sample.good < sample.total


def test_freshness_rejects_a_bucket_bigger_than_the_window():
    with pytest.raises(ValueError):
        freshness_window_sample(event_times=[], now=0.0, window_seconds=300,
                                bucket_seconds=3600, staleness_budget_seconds=60)


# ------------------------------------------------------------- the real config


def _document() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def test_the_committed_config_defines_exactly_three_slos():
    configs = load_slo_configs(_document())
    assert sorted(configs) == ["alert_delivery", "card_freshness", "quote_freshness"]


def test_every_slo_names_a_verified_feed():
    """An SLO with no feed is an unscheduled validator wearing a budget."""
    doc = _document()
    for entry in doc["slos"]:
        feed = entry["feed"]
        assert feed["kind"] in ("ratio_of_rows", "freshness_buckets")
        assert feed["table"] and feed["timestamp_column"]
        assert feed.get("verified_on"), f"{entry['name']}: feed must record when its schema was verified"


def test_targets_are_in_config_not_in_code():
    """No operator-tunable number may be a literal in the library."""
    src = (ROOT / "scripts" / "lib" / "slo_burn_rate.py").read_text(encoding="utf-8")
    for entry in _document()["slos"]:
        assert str(entry["slo_target"]) not in src, f"{entry['name']}: slo_target is hardcoded in the library"
        budget = entry["feed"].get("staleness_budget_seconds")
        if budget is not None:
            assert str(budget) not in src, f"{entry['name']}: staleness budget is hardcoded in the library"


def test_the_library_does_no_io():
    """It is pure: no config read, no clock, no database. `now` is always passed in."""
    src = (ROOT / "scripts" / "lib" / "slo_burn_rate.py").read_text(encoding="utf-8")
    for forbidden in ("import json", "from pathlib", "open(", "psycopg2", "datetime.now", "time.time"):
        assert forbidden not in src, f"the pure library must not use {forbidden}"


def test_the_reporter_is_not_wired_to_a_scheduler():
    """Scheduling is operator-only (AGENTS.md §17). Pinned so a later edit trips."""
    src = REPORTER.read_text(encoding="utf-8")
    assert "SCHEDULED_ENTRYPOINT" in src
    assert "NONE" in src.split("SCHEDULED_ENTRYPOINT")[1][:200]
    for forbidden in ("send_telegram", "telegram_alert", "crontab"):
        assert forbidden not in src, f"a report-only script must not reference {forbidden}"


def test_the_reporter_rejects_an_injected_identifier():
    spec = importlib.util.spec_from_file_location("_slo_reporter", REPORTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with pytest.raises(ValueError):
        mod._identifier("alert_events; DROP TABLE x", "feed.table")
    with pytest.raises(ValueError):
        mod._predicate("1=1; DROP TABLE x")
    with pytest.raises(ValueError):
        mod._predicate("x IS NOT NULL -- comment")
    assert mod._predicate("telegram_message_id IS NOT NULL")


# ------------------------------------------------------------- live feed (DB)


@pytest.fixture
def reporter():
    spec = importlib.util.spec_from_file_location("_slo_reporter_live", REPORTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def live_conn(reporter):
    """Skip feed assertions when no database is reachable.

    CI is hermetic. The math above still runs unconditionally, so a skip here
    narrows the claim rather than emptying the suite.
    """
    conn = reporter.connect()
    if conn is None:
        pytest.skip("no database in this environment; math assertions still ran")
    yield conn
    conn.close()


def test_every_feed_table_and_column_actually_exists(live_conn):
    """The reason several column guesses were wrong tonight: nobody asked."""
    with live_conn.cursor() as cur:
        for entry in _document()["slos"]:
            feed = entry["feed"]
            cur.execute(
                "SELECT count(*) FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
                (feed["table"], feed["timestamp_column"]),
            )
            assert cur.fetchone()[0] == 1, f"{feed['table']}.{feed['timestamp_column']} does not exist"


def test_the_live_feeds_return_real_samples(reporter, live_conn):
    doc = _document()
    configs = load_slo_configs(doc)
    for name, cfg in configs.items():
        feed = reporter.feed_for(doc, name)
        samples = reporter.collect_samples(live_conn, feed, cfg.window_seconds())
        assert set(samples) == set(cfg.window_seconds())
        assert any(s.total > 0 for s in samples.values()), f"{name}: every window empty — the feed is not real"


def test_the_report_runs_end_to_end_and_names_a_status(reporter, live_conn):
    report = reporter.run(_document(), live_conn)
    assert report["database"] == "connected"
    assert len(report["slos"]) == 3
    for slo in report["slos"]:
        assert slo["status"] in (SEVERITY_PAGE, SEVERITY_TICKET, STATUS_OK, STATUS_INSUFFICIENT_DATA)


def test_a_missing_database_reports_unknown_not_zero(reporter):
    """The failure mode that matters: an unfed calculator must say so."""
    report = reporter.run(_document(), None)
    assert report["database"] == "unreachable"
    assert {s["status"] for s in report["slos"]} == {"UNAVAILABLE"}
