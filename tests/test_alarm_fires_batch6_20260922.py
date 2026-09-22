"""C1 batch 6 — ten operator notifiers observed reaching the transport.

An alarm that has never been observed firing is indistinguishable from no alarm.
Before this file, each of these ten `send_telegram` call sites was a line in
config/alarm_firing_baseline.txt: named debt, counted, and unproven. They are
removed from that file by this one, so the ratchet number moves because the
alarms were tested, not because the baseline absorbed them.

Every site here is a single-call notifier with the same shape — a small helper
that imports the transport lazily and swallows its exceptions — so each file is
declared WHOLE in COVERS. That is only honest because each file has exactly ONE
`send_telegram` call: verified 2026-09-22 against
`alarm_firing_coverage.call_sites`, which is the same function the gate reads.
`test_covers_matches_what_this_file_actually_drives` keeps it that way; if a
second site is ever added to one of these files, coverage stops being claimed for
the whole file and the ratchet should notice.

Sites are declared WHOLE, deliberately not pinned to a line: a `file:line` pin
breaks on any edit ABOVE the call, which fails on a dimension that has nothing to
do with whether the alarm fires (recorded in
tests/test_alarm_fires_disk_pressure_20260921.py, where exactly that happened).

MEASURED WHILE WRITING THIS, not asserted here: all ten helpers discard the
transport's verdict. Nine return None and swallow every exception; the tenth,
`stop_health_check._send_telegram`, returns True whenever `send_telegram` did not
raise — including when it returned False, i.e. when the message was refused. A
refused send therefore reads as a delivered one. No test below asserts that
behaviour, because an assertion on it would have to be deleted to fix it, and a
test that must be deleted to allow a fix is a lock on the defect rather than a
record of it. It is stated here so the next reader has the number.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

#: (module, notifier) — the one transport-calling helper in each module.
SITES: list[tuple[str, str]] = [
    ("agent_watchlist_engine", "_send_tg"),
    ("auto_research", "_send_tg"),
    ("credential_monitor", "_send_tg"),
    ("cron_self_heal", "_notify"),
    ("hermes_score_alerts", "_telegram"),
    ("overnight_batch", "_send_tg"),
    ("run_alex_daily", "_send_tg"),
    ("stop_health_check", "_send_telegram"),
    ("telegram_smart_alerts", "_send_tg"),
    ("youtube_backfill_manager", "_send_tg"),
]

#: Spelled out as LITERAL strings, not derived from SITES. alarm_firing_coverage
#: .declared_covers reads this with ast and accepts only ast.Constant elements, so a
#: comprehension parses to NO declared coverage at all -- the gate reads it as zero,
#: silently, and the ten files stay uncovered while this file is green. Measured
#: 2026-09-22: written as a comprehension first, coverage stayed at 36/188.
#: test_covers_matches_what_this_file_actually_drives keeps the literal and the
#: parametrised list from drifting apart.
COVERS = [
    "scripts/agent_watchlist_engine.py",
    "scripts/auto_research.py",
    "scripts/credential_monitor.py",
    "scripts/cron_self_heal.py",
    "scripts/hermes_score_alerts.py",
    "scripts/overnight_batch.py",
    "scripts/run_alex_daily.py",
    "scripts/stop_health_check.py",
    "scripts/telegram_smart_alerts.py",
    "scripts/youtube_backfill_manager.py",
]


@pytest.fixture
def capture_transport(monkeypatch):
    """Replace the transport itself, not a wrapper.

    Each helper does `from telegram_alert import send_telegram` INSIDE the
    function body, so the name is resolved on the module at call time and this
    patch is what the site actually reaches.
    """
    captured: list[tuple[str, dict]] = []

    def _send(msg, *args, **kwargs):
        captured.append((msg, dict(kwargs)))
        return True

    import telegram_alert

    monkeypatch.setattr(telegram_alert, "send_telegram", _send)
    return captured


@pytest.mark.parametrize("module,notifier", SITES)
def test_the_alarm_reaches_the_transport(module, notifier, capture_transport):
    """The site fires, and the operator's text survives the trip.

    Substring, not equality: cron_self_heal prefixes its own label. What must
    hold is that the caller's words reach the transport, not that nothing was
    added to them.
    """
    mod = importlib.import_module(module)
    probe = f"C1 probe {module}: operator alarm firing check"

    getattr(mod, notifier)(probe)

    assert capture_transport, f"{module}.{notifier} never called the transport"
    assert probe in capture_transport[0][0], (
        f"{module}.{notifier} reached the transport but dropped its message"
    )


@pytest.mark.parametrize("module,notifier", SITES)
def test_a_broken_transport_does_not_take_the_job_down(module, notifier, monkeypatch):
    """Notification failure must not become job failure.

    Every one of these runs inside a cron job whose real work (queueing batches,
    healing crontab lines, checking stops) has nothing to do with Telegram. If
    the notifier propagated, a transport outage would abort the work the
    operator actually depends on — turning a missing message into a missing run.
    """
    import telegram_alert

    def _boom(*args, **kwargs):
        raise RuntimeError("transport down")

    monkeypatch.setattr(telegram_alert, "send_telegram", _boom)
    mod = importlib.import_module(module)
    getattr(mod, notifier)("probe")  # must not raise


def test_control_the_capture_only_fills_when_a_site_fires(capture_transport):
    """Negative control: the assertion above is load-bearing.

    If `capture_transport` were populated by anything other than the site under
    test — an import, a fixture, another module's chatter — then
    `assert capture_transport` would pass for a notifier that never fired, and
    every test above would be green over an unobserved alarm. That is the exact
    defect this gate exists to prevent, so it is checked rather than assumed.
    """
    assert capture_transport == [], "the transport was called before any site ran"

    import cron_self_heal

    cron_self_heal._notify("control probe")
    assert len(capture_transport) == 1, "one site fired, so exactly one send is expected"


def test_covers_matches_what_this_file_actually_drives():
    """A COVERS entry is a claim that a test fires that file's alarm.

    Declaring a file the tests do not drive would overstate coverage to the
    ratchet, which is worse than the debt line it replaced: the baseline was at
    least honest about being untested.
    """
    assert COVERS == [f"scripts/{module}.py" for module, _ in SITES]
    for module, notifier in SITES:
        mod = importlib.import_module(module)
        assert callable(getattr(mod, notifier, None)), (
            f"{module}.{notifier} does not exist; COVERS claims a site that is gone"
        )


def test_each_covered_file_still_holds_exactly_one_transport_site():
    """Whole-file coverage is only true while the file has one site.

    Read with the gate's own analyser, so this cannot drift from what the
    ratchet counts. If a second `send_telegram` is added to one of these files,
    the whole-file COVERS entry would silently claim the new site as tested too.
    """
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    from alarm_firing_coverage import call_sites

    sites = call_sites(ROOT / "scripts")
    counts: dict[str, int] = {}
    for path, _lineno in sites:
        counts[path] = counts.get(path, 0) + 1

    for covered in COVERS:
        assert counts.get(covered) == 1, (
            f"{covered} now holds {counts.get(covered)} send_telegram sites; a "
            "whole-file COVERS entry would claim the untested one as covered. "
            "Cover the new site, or narrow this entry to file:line."
        )
