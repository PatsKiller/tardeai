"""Shared pytest hooks — block live side effects during unit tests."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# CI does not install python-dotenv, so any alarm module importing it raised
# ModuleNotFoundError during collection and the C1 firing gate did not run at all.
# A gate that silently does not execute is the exact defect this suite exists to
# close, so the dependency is stubbed rather than the tests skipped. Loading a real
# .env inside a unit test would be wrong anyway: the stub is the correct behaviour,
# not a workaround.
if "dotenv" not in sys.modules:
    try:
        import dotenv  # noqa: F401
    except ModuleNotFoundError:
        import types as _types

        _stub = _types.ModuleType("dotenv")
        _stub.load_dotenv = lambda *a, **k: False
        _stub.find_dotenv = lambda *a, **k: ""
        _stub.dotenv_values = lambda *a, **k: {}
        sys.modules["dotenv"] = _stub

# These four predate the pytest suite: they are standalone SCRIPTS whose entire
# body — including live database writes to trade_approvals and
# schwab_round_trips — runs at module import and then calls sys.exit(). pytest
# executes module bodies during COLLECTION, so importing any one of them raised
# SystemExit inside the collector and aborted the run with INTERNALERROR before
# a single test executed. `pytest tests/` was therefore collecting zero tests.
#
# CI never caught this because every workflow names its files explicitly
# (options-lifecycle-ci.yml:59) and none of them names these four — so CI stayed
# green while the full-suite command was completely broken.
#
# Ignored rather than converted: they exercise real broker approval and canary
# paths against a live database, which is a deliberate choice for a manually-run
# script and the wrong thing to have pytest trigger on collection. Run them
# directly: `.venv/bin/python tests/test_canary_gate.py`.
# (found 2026-07-20 while wiring the decision-packet suite)
def pytest_configure(config) -> None:
    config.addinivalue_line("markers", "tier0: R11 fast unit + contracts (<5 min)")
    config.addinivalue_line("markers", "tier1: R11 integration fixtures (<15 min)")


collect_ignore = [
    "test_broker_scaffold.py",
    "test_canary_exclusion.py",
    "test_canary_gate.py",
    "test_two_channel_approval.py",
]


@pytest.fixture(autouse=True)
def _block_options_monitor_live_telegram(monkeypatch):
    """Reconcile/orphan tests call real alert dispatch; never ping the operator bot."""
    from lib.options_pipeline import paper_position_alerts as ppa

    monkeypatch.setattr(ppa, "send_telegram", lambda _message: False)


@pytest.fixture(autouse=True)
def _block_all_telegram_http(monkeypatch):
    """Phase 1: hard-interdict telegram_transport.send_message for entire suite.

    No unit test may open api.telegram.org. Returns a structured blocked result.
    """
    def _blocked(**kwargs):
        return {
            "ok": False,
            "status_code": 0,
            "response": {"ok": False, "description": "PYTEST_INTERDICTED"},
            "interdicted": True,
        }

    try:
        import telegram_transport as tt
        monkeypatch.setattr(tt, "send_message", _blocked)
    except Exception:
        pass
    try:
        import scripts.telegram_transport as tt2  # type: ignore
        monkeypatch.setattr(tt2, "send_message", _blocked)
    except Exception:
        pass

@pytest.fixture(autouse=True)
def _block_alert_outbox_production_writes(monkeypatch):
    """Keep the alert outbox off the PRODUCTION database during unit tests.

    Found 2026-07-29. `tests/test_telegram_notification_normalization.py` calls
    publish_event() directly with no DB isolation, and alert_outbox._db() opens a
    connection to the live trade_ai database. Those writes used to fail — the
    outbox targeted a first-draft schema that no longer existed, so the calls
    raised and nothing landed. Repairing publish_event() turned a
    failing-and-harmless test into a passing-and-POLLUTING one: a single suite run
    wrote 3 incidents, 6 occurrences, 2 deliveries and a digest row into
    production alert tables.

    Returning None routes publish_event() to its designed in-memory path, which is
    what these tests actually assert against. Tests that genuinely need a database
    (test_alert_delivery_recording_db.py, test_alert_occurrence_persistence_db.py)
    monkeypatch _db themselves to an ISOLATED DSN and refuse any DSN naming
    trade_ai, so they override this and stay safe.
    """
    try:
        import alert_outbox
    except Exception:
        return
    monkeypatch.setattr(alert_outbox, "_db", lambda: None)


@pytest.fixture(autouse=True)
def _block_cio_wake_trace_production_writes(monkeypatch, tmp_path_factory):
    """Keep CIO wake traces out of the repository's own data/ tree.

    Found 2026-09-13 by putting tests/test_p26_shadow_autonomy.py back into CI
    after it had sat in UNLISTED_BASELINE. It passed locally and failed on CI at
    a completely different gate:

        test_whole_site_truth.py::test_an_empty_state_root_is_never_reported_live
        /v3/control-plane/workflows claimed LIVE with an empty root

    scripts/lib/cio_wake_traces writes to a module-level DEFAULT_TRACE_PATH of
    PROJECT_ROOT/data/cio/cio_wake_traces.jsonl with no override, so any test
    reaching that path appends to the repo. Locally data/cio/ is already full of
    real state and nothing looked wrong. On a fresh CI clone the p26 suite CREATED
    that root, and the next gate found a state root that existed and was empty --
    which is exactly the condition test_whole_site_truth exists to catch.

    So the site-truth test was right, and the pollution was real. It had simply
    been invisible for as long as the suite that caused it did not run.

    Redirecting the module default keeps every test off the repo tree. Tests that
    pass an explicit path are unaffected -- every writer in that module takes
    `path` and only falls back to this default.
    """
    try:
        from scripts.lib import cio_wake_traces
    except Exception:
        return
    isolated = tmp_path_factory.mktemp("cio_traces") / "cio_wake_traces.jsonl"
    monkeypatch.setattr(cio_wake_traces, "DEFAULT_TRACE_PATH", isolated)


@pytest.fixture(autouse=True)
def _block_data_broker_snapshot_production_writes(monkeypatch, tmp_path_factory):
    """Keep data_broker snapshot caches out of the repository tree.

    Same discovery as _block_cio_wake_trace_production_writes: with the p26 suite
    running, a pass left ``state/data_broker/portfolio_snapshot.json`` behind in
    the repo. `state/` is gitignored, so it never showed in `git status` and left
    no local trace -- but on a fresh CI clone the suite CREATES that tree, and a
    later gate reads a store that exists only because a test put it there.

    This sets an ENVIRONMENT VARIABLE rather than monkeypatching a module
    constant, and that choice is the whole point. The package is importable as
    both `lib.data_broker.x` and `scripts.lib.data_broker.x`, which are distinct
    module objects with distinct copies of every constant; the repo enforces one
    spelling in test_scripts_lib_bootstrap. An earlier version of this fixture
    patched both spellings to reach the real writer and tripped that guard --
    correct diagnosis, forbidden remedy. The environment is process-global, so it
    redirects the writer whichever spelling loaded it, and breaks no invariant.

    Requires the module to resolve its path per call, which is why
    portfolio_snapshot grew _snapshot_path().
    """
    monkeypatch.setenv(
        "TRADEAI_DATA_BROKER_STATE_DIR",
        str(tmp_path_factory.mktemp("data_broker_state")),
    )


# ── C1 alarm-firing capture ──────────────────────────────────────────────────
# An alarm that has never been observed firing is indistinguishable from no alarm.
# Capture happens at the REAL transport boundary, telegram_transport.send_message,
# which telegram_alert binds at module level. Capturing at send_telegram itself
# would prove only that a function was called; capturing here proves the message
# reached the transport it claims to use, having survived the router. Nothing is
# sent -- the stub never touches the network.
from dataclasses import dataclass, field  # noqa: E402


@dataclass
class Captured:
    transport: list[dict] = field(default_factory=list)
    suppressed: list[str] = field(default_factory=list)

    @property
    def fired(self) -> bool:
        return bool(self.transport)

    def text(self) -> str:
        return "\n".join(m.get("text", "") for m in self.transport)

    def assert_fired(self, contains: str | None = None) -> None:
        assert self.transport, (
            "alarm did not reach the transport. "
            + (f"router suppressed {len(self.suppressed)}: {self.suppressed[:2]}"
               if self.suppressed else "nothing was produced at all")
        )
        if contains is not None:
            assert contains.lower() in self.text().lower(), (
                f"alarm fired but the message does not mention {contains!r}: "
                f"{self.text()[:200]!r}"
            )


@pytest.fixture
def alarm_capture(monkeypatch):
    """Capture outbound Telegram at the transport boundary. Sends nothing."""
    import telegram_alert as TA

    cap = Captured()

    def _fake_send_message(token=None, chat_id=None, text="", **kw):
        cap.transport.append({"chat_id": chat_id, "text": text})
        return {"ok": True, "status_code": 200}

    # Bound into telegram_alert's namespace by `from telegram_transport import ...`,
    # so patching the source module alone would not intercept it.
    monkeypatch.setattr(TA, "send_message", _fake_send_message, raising=True)
    # _enabled() gates send_telegram before anything else. Patching only _token and
    # _chat_ids passed locally (a real token in the environment) and failed in CI,
    # where send_telegram returned at the first line and produced nothing at all.
    monkeypatch.setattr(TA, "_enabled", lambda: True, raising=False)
    monkeypatch.setattr(TA, "_token", lambda: "test-token", raising=False)
    monkeypatch.setattr(TA, "_chat_ids", lambda: ["test-chat"], raising=False)

    # Record router suppression instead of letting it silently swallow.
    try:
        import telegram_alert_router as TR

        real_should = TR.should_send_telegram

        def _record(msg, *a, **k):
            allowed = True
            try:
                allowed = bool(real_should(msg, *a, **k))
            except Exception:
                allowed = True
            if not allowed:
                cap.suppressed.append(msg[:120])
            return allowed

        monkeypatch.setattr(TR, "should_send_telegram", _record, raising=True)
        monkeypatch.setattr(TR, "mark_sent", lambda *a, **k: None, raising=False)
    except Exception:
        pass

    return cap


@pytest.fixture(autouse=True)
def _production_receipt_write_barrier(monkeypatch):
    """Centralized barrier at the lowest durable receipt-write boundary.

    Found 2026-09-08 by the integration owner, the hard way: while iterating on
    tests/test_inbound_poller_integration.py, feed_telegram_update() reached
    emit_consumption_receipt() and minted real AgentConsumptionReceipt rows in
    the live trade_ai database ('persisted': 'db'). Nothing stopped it, because
    every guard in this file was a per-PATH denylist and SFR-I-RUNTIME-001 had
    just created a write path no entry named. A denylist protects only the paths
    somebody already thought of; each new writer is uncovered by default.

    The barrier is placed at `_db_conn()` -- the single point every durable
    receipt write must pass through -- rather than on any individual function.
    A new module, wrapper or code path cannot route around it, because it does
    not know the names of its callers.

    It does NOT hard-fail: emit_consumption_receipt already degrades to its
    in-memory path when the connection is None, so legitimate persistence tests
    (replay collision, schema version, source linkage) keep working and simply
    stop touching production. A first draft blocked the writer outright and took
    down tests/test_comms_campaign_gaps_b.py, which is the failure mode
    requirement 15 exists to prevent.

    A test that genuinely needs a database must set TRADEAI_TEST_ISOLATED_DSN to
    an isolated cluster. The production DSN is never accepted under pytest.
    """
    isolated = os.environ.get("TRADEAI_TEST_ISOLATED_DSN", "").strip()

    def _barrier(*a, **k):
        if not isolated:
            return None
        import psycopg
        return psycopg.connect(isolated)

    # DISCOVER every connection boundary; never enumerate by name.
    #
    # 2026-09-09: the first version of this barrier patched ONLY
    # scripts.lib.comms.agent_contracts and its docstring claimed _db_conn was
    # "the single point every durable write must pass through". That was wrong.
    # There are SEVEN _db_conn definitions -- agent_contracts, delivery, inbound,
    # librarian, subject_memory, client, and hermes_embedding_enqueue -- and six
    # were unguarded. tests/test_comms_channel_adapters.py reached production
    # through delivery._db_conn and wrote a real row into
    # communication_deliveries with the synthetic provider id "wamid.test_1"
    # (delivery dlv_01a06fc8-1567-7034, 2026-09-05), which then contaminated
    # SENT-with-provider_message_id counts.
    #
    # A name list is the same mistake as a caller denylist, one layer down.
    # Walk the package so a module added tomorrow is covered without an edit.
    import pkgutil
    targets = ["scripts.hermes_embedding_enqueue"]
    try:
        import scripts.lib.comms as _comms
        targets += [f"scripts.lib.comms.{m.name}"
                    for m in pkgutil.iter_modules(_comms.__path__)]
    except Exception:
        pass
    for mod in targets:
        try:
            m = importlib.import_module(mod)
        except Exception:
            continue
        if hasattr(m, "_db_conn"):
            monkeypatch.setattr(m, "_db_conn", _barrier, raising=False)
