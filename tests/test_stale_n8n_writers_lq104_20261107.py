"""ANCHOR: STALE_N8N_WRITERS_LQ104_20261107. LQ-20261107-104 — five scheduled writers whose stores stopped
moving while their logs kept saying everything was fine.

Each case below is a live observation from the 2026-11-07 DB re-test (read-only), pinned here so the silence stays
attributable:

* ``hermes-research-agenda-at-45-7`` — the cron applied at 07:45:01 and wrote ``status ok``; the dispatcher's
  duplicate fire at 07:45:04 hit the 12 h cadence gate and wrote ``status failed / agenda_blocked`` over it, so a
  lane that had just done its work graded FAILED.
* ``incubator-llm-screener`` — 10 candidates, 10 ``manual approval required`` refusals (``llm_process_config``
  mode=manual), ``screened 0``, and ``main()`` returned None: exit 0 for a run that screened nothing. Last
  successful screen 2026-08-27.
* ``reconcile-watch-outcomes`` — "no anchored events due — clean run" every week while
  ``watch_candidate_events`` had had no producer since 2026-07-16 (data_broker class ``dead_feed``).
* ``reconcile-exit-advisory-outcomes`` — "clean run on zero rows" forever: its input type ``exit_intelligence``
  is only written by ``gain_guardian_publish``, unreachable while Gain Guardian's ``published`` is false.
* ``research-intelligence-queue`` — id 148 sat ``running`` since 2026-08-10 with no process behind it, and
  nothing in the code ever looked at it again.

Hermetic: fake cursors/modules, no database, no network, no model call, synthetic rows.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str):
    """Import scripts/<name>.py under a private module name (no package import, no side effects beyond its own)."""
    spec = importlib.util.spec_from_file_location(f"lq104_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def receipts(monkeypatch):
    """Capture every LaneRunReceipt this test writes; the real writer would need a state root."""
    import lib.lane_last_receipt as llr

    calls: list[dict] = []
    monkeypatch.setattr(llr, "write_lane_receipt", lambda lane_id, **kw: calls.append({"lane_id": lane_id, **kw}))
    return calls


# ── hermes-research-agenda: a cadence skip is not a failed run ───────────────────────────────────────────────

def test_cadence_skip_is_classified_apart_from_a_kill_switch():
    mod = _load("hermes_research_agenda")
    assert mod.skip_kind("cadence_gate: 0.0h since last (min 12h)") == mod.SKIP_CADENCE
    assert mod.skip_kind("HERMES_DISABLED") == mod.SKIP_DISABLED
    assert mod.skip_kind("HERMES_AGENDA_DISABLED") == mod.SKIP_DISABLED
    assert mod.skip_kind("something_unknown") == "blocked"


def test_a_cadence_skip_leaves_the_applied_runs_receipt_alone(monkeypatch, receipts, capsys):
    mod = _load("hermes_research_agenda")
    reason = "cadence_gate: 0.0h since last (min 12h)"
    monkeypatch.setattr(mod, "run_agenda", lambda **kw: {
        "status": "skipped", "skip_kind": mod.SKIP_CADENCE, "reason": reason,
        "creates": 0, "retires": 0, "boosts": 0})
    assert mod.main(["--apply", "--json"]) == 0
    assert receipts == []                                   # the sibling that applied owns the receipt
    assert "receipt left untouched" in capsys.readouterr().err


def test_a_kill_switch_still_writes_a_failed_receipt(monkeypatch, receipts):
    mod = _load("hermes_research_agenda")
    monkeypatch.setattr(mod, "run_agenda", lambda **kw: {
        "status": "skipped", "skip_kind": mod.SKIP_DISABLED, "reason": "HERMES_DISABLED",
        "creates": 0, "retires": 0, "boosts": 0})
    assert mod.main(["--apply", "--json"]) == 0
    assert len(receipts) == 1 and receipts[0]["ok"] is False and receipts[0]["error"] == "HERMES_DISABLED"


def test_a_real_run_is_still_ok(monkeypatch, receipts):
    mod = _load("hermes_research_agenda")
    monkeypatch.setattr(mod, "run_agenda", lambda **kw: {
        "status": "ok", "mode": "apply", "candidates_found": 3, "creates": 1, "retires": 0,
        "boosts": 0, "top_candidates": []})
    assert mod.main(["--apply", "--json"]) == 0
    assert len(receipts) == 1 and receipts[0]["ok"] is True and receipts[0]["error"] is None


# ── incubator-llm-screener: ten refusals are one failed run, not ten quiet ones ───────────────────────────────

def _screener(monkeypatch, receipts, preflight=(None, None, "")):
    """Load the screener with a fake DB, ten synthetic candidates and a named preflight decision.

    The run-level contract is the integration line's (LQ-86: one preflight for the whole run, a receipt on every
    ``--run``, a non-zero exit for a refusal and for a run that screened nothing). These cases pin the property
    that matters — a run that screened nothing is never a green one; the 2026-08-27..11-07 defect was
    ``Screened: 0 / Errors: 10`` with exit 0 — not the wording of one implementation.
    """
    monkeypatch.setenv("DOTENV_LOADED", "1")   # the module must not read any env file for this test
    mod = _load("incubator_llm_screener")
    monkeypatch.setattr(mod, "get_db", lambda: types.SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(mod, "fetch_candidates", lambda conn, limit=10: [
        {"symbol": f"SYN{i}", "latest_score": 50 + i} for i in range(10)])
    route, refusal, label = preflight
    monkeypatch.setattr(mod, "preflight", lambda: (route or mod.ROUTE_IN_PROCESS, refusal, label))
    # the digest is sent only when something was screened; a stub keeps the test off the alert transport
    monkeypatch.setitem(sys.modules, "telegram_alert",
                        types.SimpleNamespace(send_telegram=lambda *a, **k: True))
    return mod


def test_a_run_the_governor_refuses_exits_its_own_code_and_writes_a_failed_receipt(monkeypatch, receipts, caplog):
    mod = _screener(monkeypatch, receipts, preflight=(None, "governor refuses process "
                                                      "incubator_llm_screener (reason=manual, mode=manual)", ""))
    monkeypatch.setattr(sys, "argv", ["incubator_llm_screener.py", "--run"])
    assert mod.main() == mod.EXIT_REFUSED
    assert receipts and receipts[0]["ok"] is False
    assert receipts[0]["empty_reason"] == "governor_refused"
    assert receipts[0]["skipped_reasons"] == {"governor_refused": 10}
    assert receipts[0]["produced_count"] == 0 and receipts[0]["attempted_count"] == 10
    assert "REFUSED:" in caplog.text


def test_every_candidate_failing_to_screen_is_a_failed_run_not_an_exit_zero(monkeypatch, receipts, caplog):
    mod = _screener(monkeypatch, receipts)
    monkeypatch.setattr(mod, "screen_one", lambda conn, c, dry_run=False, via_bridge=None: {
        "symbol": c["symbol"], "status": "error", "error": "manual approval required for x"})
    monkeypatch.setattr(sys, "argv", ["incubator_llm_screener.py", "--run"])
    assert mod.main() == mod.EXIT_NO_SCREENS
    assert receipts and receipts[0]["ok"] is False
    assert receipts[0]["empty_reason"] == "no_screens"
    assert receipts[0]["skipped_reasons"] == {"screen_error": 10}
    assert receipts[0]["produced_count"] == 0 and receipts[0]["attempted_count"] == 10
    assert "NO SCREENS: 0 of 10 symbols screened" in caplog.text


def test_a_screened_candidate_keeps_the_run_green(monkeypatch, receipts):
    mod = _screener(monkeypatch, receipts)
    monkeypatch.setattr(mod, "screen_one", lambda conn, c, dry_run=False, via_bridge=None: {
        "symbol": c["symbol"], "status": "screened", "grade": "B", "verdict": "HOLD", "confidence": 0.6})
    monkeypatch.setattr(sys, "argv", ["incubator_llm_screener.py", "--run"])
    assert mod.main() == 0
    assert receipts and receipts[0]["ok"] is True and receipts[0]["produced_count"] == 10
    assert receipts[0]["empty_reason"] is None


# ── the two reconcilers: a permanently empty input is not a clean run ────────────────────────────────────────

def _db_stub(monkeypatch, execute):
    stub = types.ModuleType("db_adapter")
    stub._execute = execute
    stub.USE_DB = True
    monkeypatch.setitem(sys.modules, "db_adapter", stub)


def test_watch_reconciler_calls_a_dead_feed_dependency_unavailable(monkeypatch, receipts, capsys, tmp_path):
    mod = _load("reconcile_watch_outcomes")
    # The shipped registry NOW declares this feed's death (LQ-20261107-909/1182: watch_discovery, class dead_feed,
    # approved by the operator 2026-09-13). This case pins the UNDECLARED path, where the death must still fail.
    monkeypatch.setattr(mod, "AUTHORITY_PATH", tmp_path / "no-authority.json")

    def execute(sql, params=None, fetch=None):
        s = " ".join(sql.split()).lower()
        if s.startswith("select id, symbol"):
            return []
        if s.startswith("update watch_candidate_events"):
            return None
        if s.startswith("select max(emitted_on)"):
            return {"last_on": "2026-07-16", "age_days": 114}
        raise AssertionError(f"unexpected SQL: {s[:60]}")

    _db_stub(monkeypatch, execute)
    assert mod.main() == 1
    assert "no producer" in capsys.readouterr().err
    assert receipts[0]["ok"] is False
    assert receipts[0]["empty_reason"] == "dependency_unavailable"
    assert receipts[0]["skipped_reasons"] == {"dependency_unavailable": 1}


def test_watch_reconciler_stays_clean_while_the_feed_is_live(monkeypatch, receipts):
    mod = _load("reconcile_watch_outcomes")

    def execute(sql, params=None, fetch=None):
        s = " ".join(sql.split()).lower()
        if s.startswith("select id, symbol"):
            return []
        if s.startswith("update watch_candidate_events"):
            return None
        if s.startswith("select max(emitted_on)"):
            return {"last_on": "2026-11-05", "age_days": 2}
        raise AssertionError(f"unexpected SQL: {s[:60]}")

    _db_stub(monkeypatch, execute)
    assert mod.main() == 0
    assert receipts[0]["ok"] is True and receipts[0]["empty_reason"] == "nothing_due"


def test_watch_declared_gap_as_of_the_sunday_slot_is_no_new_input(monkeypatch, receipts, capsys):
    """Sunday 2026-11-08 09:50 ET failed on hub code (dependency_unavailable, exit 1).

    As of that slot the feed's newest emitted_on is still 2026-07-16 (115 days) and the
    shipped registry declares the gap, so this pin exits 0 with no_new_input.
    """
    mod = _load("reconcile_watch_outcomes")

    def execute(sql, params=None, fetch=None):
        s = " ".join(sql.split()).lower()
        if s.startswith("select id, symbol"):
            return []
        if s.startswith("update watch_candidate_events"):
            return None
        if s.startswith("select max(emitted_on)"):
            return {"last_on": "2026-07-16", "age_days": 115}
        raise AssertionError(f"unexpected SQL: {s[:60]}")

    _db_stub(monkeypatch, execute)
    assert mod.main() == 0
    err = capsys.readouterr().err
    assert "no_new_input" in err and "declared_gap_no_producer" in err
    assert "dependency_unavailable" not in err
    assert receipts[0]["ok"] is True and receipts[0]["empty_reason"] == "no_new_input"
    assert receipts[0]["skipped_reasons"] == {"no_new_input": 1}


def _exit_execute(ever: int, pending: int = 0, newest_age_days: int = 1):
    import datetime as dt

    newest = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=newest_age_days)

    def execute(sql, params=None, fetch=None):
        s = " ".join(sql.split()).lower()
        if s.startswith("select count(*) as ever"):
            return {"ever": ever, "due": 0, "pending": pending, "newest": newest}
        if s.startswith("select h.id, h.symbol") or s.startswith("select id, symbol"):
            return []
        return None
    return execute


def test_exit_reconciler_names_the_disabled_producer(monkeypatch, receipts, capsys):
    mod = _load("reconcile_exit_advisory_outcomes")
    _db_stub(monkeypatch, _exit_execute(ever=0))
    monkeypatch.setattr(mod, "gain_guardian_published", lambda: False)
    assert mod.reconcile() == 1
    assert "published=false" in capsys.readouterr().err
    assert receipts[0]["ok"] is False and receipts[0]["empty_reason"] == "dependency_unavailable"


def test_exit_reconciler_is_clean_when_the_producer_is_live(monkeypatch, receipts):
    """LQ-882: 'clean' is now 'no advisory still owes an outcome', not 'no row is older than 5 days'."""
    mod = _load("reconcile_exit_advisory_outcomes")
    _db_stub(monkeypatch, _exit_execute(ever=40, pending=0))
    monkeypatch.setattr(mod, "gain_guardian_published", lambda: True)
    assert mod.reconcile() == 0
    assert receipts[0]["ok"] is True and receipts[0]["empty_reason"] == "up_to_date"


def test_a_missing_count_stays_unknown_and_is_never_read_as_zero():
    """A failed read must not be able to impersonate 'the producer was never switched on'."""
    mod = _load("reconcile_exit_advisory_outcomes")
    unknown = {"ever": None, "due": None, "pending": None, "newest_age_days": None}
    assert mod.producer_state(lambda *a, **k: {}) == unknown
    assert mod.producer_state(lambda *a, **k: {"ever": 3}) == unknown
    assert mod.producer_state(lambda *a, **k: {"ever": 3, "due": 1, "pending": 2, "newest": None}) == \
        {"ever": 3, "due": 1, "pending": 2, "newest_age_days": None}


def test_an_unattributable_zero_is_not_a_clean_run():
    mod = _load("reconcile_exit_advisory_outcomes")
    assert mod.empty_input_reason({"ever": None, "due": None}, False)[0] == "input_unreadable"
    # a partial state (the pending count did not come back) cannot be attributed either
    assert mod.empty_input_reason({"ever": 0, "due": 0}, False)[0] == "input_unreadable"
    assert mod.empty_input_reason({"ever": 0, "due": 0, "pending": 0}, None)[0] == "input_unreadable"
    assert mod.empty_input_reason({"ever": 0, "due": 0, "pending": 0}, False)[0] == "dependency_unavailable"
    # LQ-1416: published and still zero rows is a quiet book (nothing_due), not a dead producer.
    assert mod.empty_input_reason({"ever": 0, "due": 0, "pending": 0}, True)[0] == "nothing_due"


def test_exit_reconciler_does_not_call_an_unreadable_count_clean(monkeypatch, receipts, capsys):
    mod = _load("reconcile_exit_advisory_outcomes")

    def execute(sql, params=None, fetch=None):
        s = " ".join(sql.split()).lower()
        return {} if s.startswith("select count(*) as ever") else []

    _db_stub(monkeypatch, execute)
    monkeypatch.setattr(mod, "gain_guardian_published", lambda: True)
    assert mod.reconcile() == 1
    assert "cannot be attributed" in capsys.readouterr().err
    assert receipts[0]["ok"] is False and receipts[0]["empty_reason"] == "input_unreadable"


def test_exit_reconciler_names_an_unreadable_switch(monkeypatch, receipts, capsys):
    mod = _load("reconcile_exit_advisory_outcomes")
    _db_stub(monkeypatch, _exit_execute(ever=0))
    monkeypatch.setattr(mod, "gain_guardian_published", lambda: None)
    assert mod.reconcile() == 1
    assert "switch state is unknown" in capsys.readouterr().err
    assert receipts[0]["empty_reason"] == "input_unreadable"


def test_the_switch_reader_returns_none_when_the_config_is_unreadable(monkeypatch, tmp_path):
    """A missing config is 'unknown', not 'unpublished': only a real false licenses dependency_unavailable."""
    mod = _load("reconcile_exit_advisory_outcomes")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    assert mod.gain_guardian_published() is None


def test_the_shipped_guardian_switch_no_longer_describes_the_lane_input():
    """The published flag is one producer's switch. The lane input is EXIT_ADVISORY_TYPES.

    published=true with zero rows is nothing_due (LQ-1416). published=false with zero rows
    stays dependency_unavailable. Neither reading means the other producers have no rows.
    """
    import json
    cfg = json.loads((ROOT / "config" / "gain_guardian_thresholds.json").read_text())
    mod = _load("reconcile_exit_advisory_outcomes")
    assert isinstance(cfg.get("published"), bool)
    assert {"protection_advisory", "stop_health"} <= set(mod.EXIT_ADVISORY_TYPES)
    reason, _why = mod.empty_input_reason({"ever": 0, "due": 0, "pending": 0}, cfg["published"])
    assert reason == ("nothing_due" if cfg["published"] else "dependency_unavailable")


def test_exit_pending_advisory_as_of_the_sunday_slot_is_scored(monkeypatch, receipts, capsys):
    """Sunday 2026-11-08 09:00 ET failed on hub code that only read exit_intelligence while unpublished.

    On this pin a due protection_advisory is scored (exit 0). The run must not repeat that stderr.
    Synthetic symbol and prices only; bars and the database are stubs.
    """
    import datetime as dt

    mod = _load("reconcile_exit_advisory_outcomes")
    created = dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)
    advisory = {
        "id": 9101514,
        "symbol": "SYN",
        "topic": "synthetic",
        "created_at": created,
        "research_type": "protection_advisory",
        "evidence_json": {
            "inputs": {"price": 100.0, "atr": 2.0},
            "recommendation": {"stop_pct_below": 8},
        },
    }
    inserts: list = []

    def execute(sql, params=None, fetch=None):
        s = " ".join(sql.split()).lower()
        if s.startswith("create table"):
            return None
        if s.startswith("select count(*) as ever"):
            newest = dt.datetime(2026, 11, 6, tzinfo=dt.timezone.utc)
            return {"ever": 3, "due": 1, "pending": 1, "newest": newest}
        if s.startswith("select h.id, h.symbol"):
            return [advisory]
        if s.startswith("select 1 from exit_advisory_outcomes"):
            return None
        if s.startswith("select 1 from alert_events"):
            return None
        if s.startswith("insert into exit_advisory_outcomes"):
            inserts.append(params)
            return None
        raise AssertionError(f"unexpected SQL: {s[:70]}")

    _db_stub(monkeypatch, execute)
    monkeypatch.setattr(mod, "gain_guardian_published", lambda: True)
    monkeypatch.setattr(mod, "_closes_since", lambda *_a, **_k: [100.0 + i for i in range(30)])
    assert mod.reconcile() == 0
    err = capsys.readouterr().err
    assert "unpublished" not in err and "dependency_unavailable" not in err
    assert len(inserts) == 2
    assert receipts[0]["ok"] is True and receipts[0]["produced_count"] == 2


# ── research-intelligence-queue: a dead process must not hold a row 'running' forever ─────────────────────────

def test_stale_running_rows_are_settled_as_failed_not_left_running():
    mod = _load("research_intelligence_queue")
    seen = []

    def execute(sql, params=None, fetch=None):
        seen.append((" ".join(sql.split()), params))
        return [{"id": 148}]

    assert mod.settle_stale_running(execute) == [148]
    sql, params = seen[0]
    assert "set status = 'failed'" in sql.lower()
    assert "where status = 'running'" in sql.lower()
    assert params[1] == mod.STALE_RUNNING_HOURS == 6
    assert "stale" in params[0]


def test_drain_settles_before_it_selects_and_reports_what_it_settled(monkeypatch):
    mod = _load("research_intelligence_queue")
    order = []

    def execute(sql, params=None, fetch=None):
        s = " ".join(sql.split()).lower()
        if s.startswith("create table") or s.startswith("create index"):
            return None
        if s.startswith("select id, topic_id"):
            order.append("select_queued")
            return []
        if s.startswith("select count(*) as n"):
            order.append("count_queued")
            return {"n": 0}
        raise AssertionError(f"unexpected SQL: {s[:60]}")

    _db_stub(monkeypatch, execute)
    monkeypatch.setattr(mod, "settle_stale_running", lambda ex, hours=None: (order.append("settle") or [148]))
    stub = types.ModuleType("research_intelligence_materialize")
    stub.materialize = lambda: None
    monkeypatch.setitem(sys.modules, "research_intelligence_materialize", stub)
    out = mod.drain(cap=10)
    assert order[:2] == ["settle", "select_queued"]
    assert out["settled_stale"] == [148]
    assert out["processed"] == 0
