"""C1 — the four `send_telegram_document` alarm sites, observed firing.

An alarm that has never been observed firing is indistinguishable from no alarm.
`send_telegram_document` started being COUNTED by the ratchet on 2026-09-22
(alarm_firing_coverage.TRANSPORT, sites_total 188 -> 192) precisely because its
four call sites had never been counted on any branch — alarms nobody could see
were untested. Counting them named the debt; this file pays it.

THE FOUR DOCUMENT SITES, all four driven here
    scripts/portfolio_alerts.py            _send_telegram_document
    scripts/portfolio_monthly_report.py    _send_telegram_doc
    scripts/portfolio_report_ms.py         send_telegram_report_notice
    scripts/portfolio_weekly_report.py     _send_telegram_doc

The weekly one did not exist as a function until today. It was inline at the end
of run_weekly_report(), unreachable without running the entire weekly report, so
it was extracted unchanged (see its docstring). A site that cannot be driven
cannot be observed, and a test that asserts nothing to work around that is worse
than no test.

WHOLE FILES FOR THREE, A `file:line` PIN FOR THE FOURTH
A whole-file COVERS entry claims EVERY transport site in that file has been
observed firing, so the sibling TEXT sites in portfolio_monthly_report and
portfolio_weekly_report are driven here too — both call send_telegram with
bypass_router=True, so both genuinely reach the transport. portfolio_report_ms
has exactly one site, the document one.

portfolio_alerts is the exception and is pinned to its document line, leaving its
TEXT site as named debt in config/alarm_firing_baseline.txt (2 -> 1).
`portfolio_alerts._send_telegram` calls `send_telegram_with_id(message)` WITHOUT
bypass_router, so the routing policy decides whether anything reaches the
transport — and MEASURED 2026-09-22 on this host, it decides no: an earnings
notice, a dividend notice, an analyst notice, a bare probe and even a message
beginning "🚨 CRITICAL" all classify P1_DIGEST and are suppressed to the digest
queue. There is no message that site can send which reaches the transport today.
It could be forced green by monkeypatching `should_send_telegram` to True, and
that was rejected: it would proves only that the stub was called, and would
record a delivery the operator does not actually get.
`test_the_alerts_text_site_is_deferred_not_forgotten` observes the suppression
instead, so the day the policy promotes that class the tripwire goes red and the
site can be covered honestly.

The pin costs brittleness — a `file:line` entry breaks on any edit ABOVE the
call, failing on a dimension that has nothing to do with whether the alarm fires
(tests/test_alarm_fires_disk_pressure_20260921.py records exactly that). It is
made self-verifying below: the pinned line is re-parsed and must still be a
`send_telegram_document` call, so drift is loud rather than a silently dropped
coverage claim.

MEASURED WHILE WRITING THIS, not asserted here:
  * `portfolio_monthly_report._send_telegram_doc` returns None. It prints whether
    the send worked and discards the verdict, so its caller cannot tell a
    delivered monthly brief from a dropped one. Asserted nowhere below, because
    an assertion on it would have to be deleted to fix it.
  * The two TEXT helpers driven here do NOT catch transport exceptions, unlike
    all four document helpers. A transport outage propagates out of them into the
    report job. `test_a_broken_transport_does_not_take_the_report_down` therefore
    runs over the document sites only; running it over the text sites would
    assert the opposite of what the code does.
"""

from __future__ import annotations

import ast
import importlib
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

#: (module, callable, kind) — the sites these tests actually drive.
SITES: list[tuple[str, str, str]] = [
    ("portfolio_alerts", "_send_telegram_document", "document"),
    ("portfolio_monthly_report", "_send_telegram_doc", "document"),
    ("portfolio_monthly_report", "_send_telegram", "text"),
    ("portfolio_report_ms", "send_telegram_report_notice", "document"),
    ("portfolio_weekly_report", "_send_telegram_doc", "document"),
    ("portfolio_weekly_report", "_send_telegram", "text"),
]

DOCUMENT_SITES = [(m, fn) for m, fn, kind in SITES if kind == "document"]
TEXT_SITES = [(m, fn) for m, fn, kind in SITES if kind == "text"]

#: Files where every transport site is driven above, so the whole file is claimed.
WHOLE_FILE = ("portfolio_monthly_report", "portfolio_report_ms", "portfolio_weekly_report")
#: portfolio_alerts is claimed at ONE line: its document send. Its text site stays
#: debt because the router gives it nowhere to go (module docstring).
PINNED = ("scripts/portfolio_alerts.py:522",)

#: LITERAL strings, deliberately not derived from the constants above.
#: alarm_firing_coverage.declared_covers parses this with `ast` and accepts ONLY
#: ast.Constant elements, so `COVERS = [f"scripts/{m}.py" for m in WHOLE_FILE]`
#: parses as ZERO declared coverage — silently. The file would be green, the
#: ratchet would never move, and the four alarms would stay unobserved while
#: looking tested. Measured on the batch-6 file, which shipped as a comprehension
#: first and left coverage at 36/188.
#: `test_covers_matches_the_sites_these_tests_drive` keeps the literal and the
#: parametrised lists from drifting apart.
COVERS = [
    "scripts/portfolio_alerts.py:522",
    "scripts/portfolio_monthly_report.py",
    "scripts/portfolio_report_ms.py",
    "scripts/portfolio_weekly_report.py",
]


@pytest.fixture(autouse=True)
def _no_live_side_effects(monkeypatch):
    """Close every live side effect these helpers reach. AUTOUSE, deliberately.

    It was a plain fixture first, and `test_a_broken_transport_does_not_take_the
    _report_down` does not request it — it needs only monkeypatch. That test
    drives the same helpers, and `portfolio_alerts._send_telegram_document`
    publishes its CommunicationEvent from a SECOND try-block that runs even when
    the send raised. So the one test that skipped these guards was still reaching
    a live database and still leaving a dual-imported module behind. A guard that
    protects only the tests that remember to ask for it is the caller-denylist
    mistake this repo has already paid for twice (tests/conftest.py).

    `alarm_capture` (tests/conftest.py) patches BOTH transport functions —
    send_message and, since 2026-09-22, send_document — so nothing leaves the
    host. Two further live side effects sit on the document path and are closed
    here rather than hoped about:

      * `report_capture.capture()` runs inside send_telegram_document and INSERTs
        into the `telegram_outbox` table through `db_adapter._get_conn`, which is
        not one of the boundaries the conftest barrier walks. A caption that
        `classify_report` recognises — "Weekly portfolio DOCX" is exactly the kind
        it recognises — would mint a production row from a unit test.
      * `COMMS_GATEWAY_MODE` decides whether the gateway owns the class. Under
        CANARY, send_telegram_document filters the target chats down to
        COMMS_GATEWAY_CANARY_CHATS and returns False when none survive — so these
        tests would depend on the host's environment rather than on the code.
        Deleted from the environment so the path under test is the same one
        everywhere.

    The ROUTER is deliberately NOT neutralised. Every site driven here either
    bypasses it by design or is not claimed as covered at all.
    """
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)

    import report_capture

    monkeypatch.setattr(report_capture, "capture", lambda *a, **k: None)
    monkeypatch.setattr(report_capture, "archive_message", lambda *a, **k: None)

    # NO UNIT TEST HERE OPENS A DATABASE. Measured 2026-09-22 with psycopg2.connect
    # instrumented: driving these six sites once attempted SIX production
    # connections, and five of them survived every barrier already in place. Two
    # reasons, both real. `report_capture.capture` INSERTs into `telegram_outbox`
    # through `db_adapter._get_conn`, which the conftest barrier does not walk; and
    # the four helpers publish their CommunicationEvent through the `lib.comms`
    # spelling, whose `_db_conn` is a DIFFERENT object from the
    # `scripts.lib.comms` one the barrier patches. The credential is present by
    # then — importing telegram_alert runs env_bootstrap.ensure_loaded(), which
    # puts DB_PASSWORD into the process — so these were live connections, not
    # failed ones.
    #
    # Blocked at the driver rather than at any one caller: a denylist of callers
    # protects only the paths somebody already thought of, which is the lesson
    # already recorded in tests/conftest.py. Every one of these call sites treats a
    # connection failure as best-effort and swallows it, which is why refusing is
    # safe and why the alarm still fires.
    def _no_database(*a, **k):
        raise RuntimeError("unit test: no database connection")

    for driver in ("psycopg2", "psycopg"):
        try:
            monkeypatch.setattr(importlib.import_module(driver), "connect",
                                _no_database, raising=False)
        except Exception:
            continue

    # Driving the helpers imports `lib.comms`, and `scripts.lib.comms` is already
    # loaded, so the process ends the test with the same package live under both
    # spellings. scripts/lib/__init__.py:assert_single_import_identity() raises on
    # exactly that, so leaving it behind hands the next suite in the session a
    # failure this file caused. Only modules THIS test introduced are removed.
    before = {n for n in sys.modules if n.startswith("lib.")}
    yield
    for name in [n for n in sys.modules if n.startswith("lib.") and n not in before]:
        sys.modules.pop(name, None)


@pytest.fixture
def doc_alarm(alarm_capture):
    """The capture itself. The live side effects are closed by the autouse fixture.

    Kept as a named fixture rather than using `alarm_capture` directly so the
    tests below read as what they are — an observation of a document alarm — and
    so the guards above cannot be silently dropped by a test that asks only for
    the capture.
    """
    return alarm_capture


def _drive(module: str, notifier: str, *, doc: Path, caption: str, root: Path):
    """Call one site with the arguments it actually takes.

    `root` is a tmp_path, never the repository: `portfolio_alerts._send_telegram`
    calls `_load_env_from_file(project_root)`, which would read the real .env and
    push production credentials into os.environ for the rest of the session.
    """
    fn = getattr(importlib.import_module(module), notifier)
    calls = {
        ("portfolio_alerts", "_send_telegram_document"): lambda: fn(doc, caption, root),
        ("portfolio_alerts", "_send_telegram"): lambda: fn(caption, root),
        ("portfolio_monthly_report", "_send_telegram_doc"): lambda: fn(doc, caption),
        ("portfolio_monthly_report", "_send_telegram"): lambda: fn(caption),
        ("portfolio_report_ms", "send_telegram_report_notice"): lambda: fn(doc, caption),
        ("portfolio_weekly_report", "_send_telegram_doc"): lambda: fn(doc, caption),
        ("portfolio_weekly_report", "_send_telegram"): lambda: fn(caption),
    }
    return calls[(module, notifier)]()


@pytest.fixture
def report_file(tmp_path) -> Path:
    """A real file on disk — the document path refuses to send without one.

    `send_telegram_document` returns False at `path.is_file()`, and three of the
    four helpers check existence themselves before that. A test using a
    non-existent path would capture nothing and would have to assert nothing.
    """
    f = tmp_path / "portfolio_report_probe.docx"
    f.write_bytes(b"PK\x03\x04 c1 probe payload")
    return f


@pytest.mark.parametrize("module,notifier", DOCUMENT_SITES)
def test_the_document_alarm_reaches_the_transport(module, notifier, doc_alarm,
                                                  report_file, tmp_path):
    """The operator gets the file, not just a caption saying a file exists.

    Three assertions, each load-bearing: the send happened, it carried a
    DOCUMENT (not a text message about one), and it carried THIS file. Deleting
    the `send_telegram_document` call from any of the four helpers turns all
    three red.
    """
    caption = f"C1 probe {module}: portfolio report attached"

    _drive(module, notifier, doc=report_file, caption=caption, root=tmp_path)

    doc_alarm.assert_fired(contains="portfolio report attached")
    assert doc_alarm.documents, (
        f"{module}.{notifier} reached the transport but sent no document — the "
        "operator would get a caption with nothing attached"
    )
    assert doc_alarm.documents[0]["document"] == str(report_file), (
        f"{module}.{notifier} sent a different file than it was handed: "
        f"{doc_alarm.documents[0]['document']!r}"
    )


@pytest.mark.parametrize("module,notifier", TEXT_SITES)
def test_the_text_alarm_reaches_the_transport(module, notifier, doc_alarm,
                                              report_file, tmp_path):
    """The sibling text sites, driven so the whole-file COVERS claim is true.

    These are not incidental. A whole-file COVERS entry tells the ratchet every
    site in the file has been observed firing; leaving these undriven would claim
    tested alarms that were not.
    """
    probe = f"C1 probe {module}: operator alarm firing check"

    _drive(module, notifier, doc=report_file, caption=probe, root=tmp_path)

    doc_alarm.assert_fired(contains="operator alarm firing check")


@pytest.mark.parametrize("module,notifier", DOCUMENT_SITES)
def test_no_file_means_no_send(module, notifier, doc_alarm, tmp_path):
    """DISCRIMINATION CONTROL: the alarm above is conditional, not unconditional.

    Without this, `test_the_document_alarm_reaches_the_transport` would pass just
    as happily against a helper that sent on every call, including when the
    report it is announcing was never produced. An alarm that always fires is
    also indistinguishable from no alarm, because nobody reads it.
    """
    missing = tmp_path / "never_rendered.docx"
    assert not missing.exists()

    _drive(module, notifier, doc=missing, caption="C1 probe: file was never rendered",
           root=tmp_path)

    assert not doc_alarm.documents, (
        f"{module}.{notifier} sent a document that does not exist on disk"
    )


@pytest.mark.parametrize("module,notifier", DOCUMENT_SITES)
def test_a_broken_transport_does_not_take_the_report_down(module, notifier,
                                                          monkeypatch, report_file,
                                                          tmp_path):
    """Telegram being down must not fail the report job.

    Every one of these runs at the end of a report that has already done its real
    work — holdings loaded, narratives generated, DOCX rendered, HTML written. If
    the notifier propagated, a transport outage would turn a missing message into
    a lost report.
    """
    import telegram_alert as TA

    def _boom(*a, **k):
        raise RuntimeError("transport down")

    monkeypatch.setattr(TA, "send_telegram_document", _boom, raising=True)

    _drive(module, notifier, doc=report_file, caption="C1 probe: outage", root=tmp_path)


def test_the_alerts_text_site_is_deferred_not_forgotten(doc_alarm, tmp_path):
    """Why portfolio_alerts is pinned to one line instead of claimed whole.

    `portfolio_alerts._send_telegram` is the one site here that consults the
    router (no bypass_router), and the router sends it to the digest queue. This
    is the OBSERVATION that justifies leaving it as debt in
    config/alarm_firing_baseline.txt rather than a quiet omission: it is not that
    nobody wrote the test, it is that the site reaches no transport to be
    observed at.

    A TRIPWIRE, not a lock: if the routing policy ever promotes this class, this
    goes red, and the correct response is to cover the site for real and lower
    the baseline entry — never to delete this test.
    """
    sent = _drive("portfolio_alerts", "_send_telegram",
                  doc=tmp_path / "unused", caption="📅 Earnings This Week\n\n"
                  "AAPL reports Thursday before open", root=tmp_path)

    assert doc_alarm.transport == [], (
        "portfolio_alerts._send_telegram now reaches the transport. Cover it with "
        "a firing test, declare scripts/portfolio_alerts.py whole in COVERS, and "
        "remove its line from config/alarm_firing_baseline.txt."
    )
    assert doc_alarm.suppressed, "the router neither delivered nor suppressed it"
    # MEASURED, and the reason this site is worth naming rather than forgetting:
    # it returns True. Nothing reached the transport, and the caller is told the
    # alert was accepted -- which is send_telegram's documented contract
    # ("delivered now, queued for a digest, or recorded"), not a bug here. But
    # portfolio_alerts reads that bool as delivery: on True it sets
    # sent["earnings"] = N and prints "✅ Earnings: N ...". The job log therefore
    # reports a sent alert for a message the operator has not been shown.
    assert sent is True


def test_control_the_capture_is_empty_until_a_site_fires(doc_alarm, report_file,
                                                         tmp_path):
    """NEGATIVE CONTROL: `assert_fired` is load-bearing, not decorative.

    If the capture were filled by anything other than the site under test — an
    import, a fixture, another module's chatter — every assertion above would be
    green over an alarm that never fired, which is the exact defect this gate
    exists to prevent.
    """
    assert doc_alarm.transport == [], "the transport was called before any site ran"

    import portfolio_report_ms

    portfolio_report_ms.send_telegram_report_notice(report_file, "C1 probe: control")
    assert len(doc_alarm.transport) == 1, "one site fired, so exactly one send is expected"
    assert len(doc_alarm.documents) == 1


def test_nothing_leaves_the_host(doc_alarm, report_file, tmp_path):
    """The captured send was the fake, not a message that actually went out.

    Checked through telegram_alert's bound name rather than by importing
    telegram_transport and booby-trapping it. That was the first version, and
    scripts/check_telegram_chokepoint.py correctly called it a NEW bypass:
    `transport_import` flags any file importing something from the transport that
    can SEND, and it scans tests/ deliberately — a blanket tests/ exclusion would
    let a real producer hide in a test path. There is an APPROVED list for tests
    that must name the transport to prove it is interdicted, and adding this file
    to it would have been legitimate; it is not done here because the property is
    provable without touching a governance surface at all.

    `send_telegram_document` calls the `send_document` bound into telegram_alert,
    so that name IS the only route to the network from these sites. Asserting it
    is the fixture's stub says exactly what the booby trap said: whatever the
    document alarms reached, it was not the wire.
    """
    import telegram_alert as TA

    assert TA.send_document.__name__ == "_fake_send_document", (
        "the transport boundary is not stubbed; a document send from this test "
        "could reach the real Telegram API"
    )

    _drive("portfolio_weekly_report", "_send_telegram_doc", doc=report_file,
           caption="C1 probe: must not leak", root=tmp_path)
    doc_alarm.assert_fired(contains="must not leak")


def test_covers_matches_the_sites_these_tests_drive():
    """A COVERS entry is a claim that a test fires that file's alarms.

    Declaring a file these tests do not drive would overstate coverage to the
    ratchet, which is worse than the baseline line it replaces: the baseline was
    at least honest about being untested.
    """
    assert COVERS == sorted([f"scripts/{m}.py" for m in WHOLE_FILE] + list(PINNED))
    for module, notifier, _kind in SITES:
        mod = importlib.import_module(module)
        assert callable(getattr(mod, notifier, None)), (
            f"{module}.{notifier} does not exist; COVERS claims a site that is gone"
        )


def test_every_site_in_a_whole_file_claim_is_driven_here():
    """Whole-file coverage is only true while every site in the file is driven.

    Read with the GATE'S OWN analyser, so this cannot drift from what the ratchet
    counts. If another `send_telegram*` call is added to one of these three files,
    the whole-file COVERS entry would silently claim the new, untested site as
    observed — so this turns red instead.
    """
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    from alarm_firing_coverage import call_sites

    actual = Counter(path for path, _lineno in call_sites(ROOT / "scripts"))
    driven = Counter(f"scripts/{module}.py" for module, _, _ in SITES)

    for module in WHOLE_FILE:
        rel = f"scripts/{module}.py"
        assert actual.get(rel) == driven.get(rel), (
            f"{rel} holds {actual.get(rel)} transport sites but this file drives "
            f"{driven.get(rel)}. A whole-file COVERS entry would claim the undriven "
            "one as observed. Drive the new site, or narrow this entry to file:line."
        )


def test_the_pinned_line_is_still_the_document_send():
    """A `file:line` pin that has drifted claims coverage of whatever moved there.

    This is the cost of pinning instead of claiming the file, paid explicitly: any
    edit ABOVE portfolio_alerts.py:512 silently repoints the claim. Re-parsing the
    file and demanding that the pinned line still holds a `send_telegram_document`
    call turns that drift into a failure with an instruction, rather than a
    coverage number that quietly stops meaning anything.
    """
    for entry in PINNED:
        rel, _, lineno = entry.partition(":")
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        # Every call on the line, not one of them: the pinned line reads
        # `send_telegram_document(str(file_path), ...)`, so it holds a nested
        # `str` call too. Keeping a single name per line picked whichever `ast.walk`
        # reached last — 'str' — and failed a correct pin.
        names: dict[int, set[str]] = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                nm = (n.func.attr if isinstance(n.func, ast.Attribute)
                      else getattr(n.func, "id", None))
                names.setdefault(n.lineno, set()).add(nm)
        found = names.get(int(lineno), set())
        assert "send_telegram_document" in found, (
            f"{entry} no longer points at a send_telegram_document call (found "
            f"{sorted(x for x in found if x)!r}). Re-pin COVERS to the line the call "
            "is on now, or declare the file whole once every site in it is driven."
        )


def test_the_document_transport_is_still_counted_by_the_ratchet():
    """REGRESSION GUARD: these four sites only exist as debt while they are counted.

    send_telegram_document was added to alarm_firing_coverage.TRANSPORT by
    operator decision on 2026-09-22. If it were dropped again, these four sites
    would leave the denominator entirely and the baseline entries this file
    removes could never come back — the alarms would be invisible rather than
    covered, which is the failure mode the ratchet exists to prevent.
    """
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    import alarm_firing_coverage as AFC

    assert "send_telegram_document" in AFC.TRANSPORT
