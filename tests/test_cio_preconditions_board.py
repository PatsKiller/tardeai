"""The board must be able to say RED, say GREEN, and admit when it cannot tell.

A preconditions board is only worth running if it can fail. Each of the four
checks is therefore driven to GREEN and to RED from constructed state, and the
wrong-root case is pinned separately because it is the one that has actually
bitten: a board run from a worktree with no data/ sees an empty store and, if it
is careless, reports four REDs about a spine that is perfectly healthy.

The dust/CASH check is tested against the real `is_mintable`, not a stub. A
refusal test that mocks the refuser proves nothing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts.lib.cio_instrument_record import cc_narrative, new_record
from scripts.lib.cio_preconditions_board import (
    CANNOT_VERIFY, GREEN, RED, ROOT_EMPTY_STORE, ROOT_NO_CIO_DIR,
    ROOT_NO_RECORD_STORE, ROOT_OK, build_board, check_cc_narrative_without_ping,
    check_critique_persisted, check_dust_cash_refused, check_s0_attach_rehydrate,
    load_records, notify_rails, probe_root, read_policy_notify, render,
    scan_wake_consumers,
)
from scripts.lib.cio_rehydrate import attach_operator_turn

NOW = datetime.now(timezone.utc)
OK_PROBE = {"verdict": ROOT_OK, "reason": "test"}


# ── fixtures built from the real libraries, not hand-written dicts ─────────

def _schd_with_defer():
    rec = new_record("HELD", "SCHD", symbols=["SCHD"])
    rec, _ = attach_operator_turn(
        rec, intent="defer", text="wait for price buffer",
        plan_id="plan_79fe9e72f2d4", now=NOW)
    return rec


def _held_with_narrative(symbol: str, what: str):
    rec = new_record("HELD", symbol, symbols=[symbol])
    rec["cc_narrative"] = cc_narrative(what=what, thesis_fit="advisory")
    return rec


def _cash_sleeve(what: str = "Cash sleeve 630784.82."):
    rec = new_record("SLEEVE", "CASH")
    rec["cc_narrative"] = cc_narrative(what=what)
    return rec


def _home(*, texts=(), telegram_sent=False, would_send_any=False, dust=()):
    return {
        "holdings_thesis_coverage": {"items": [{"why": t} for t in texts],
                                     "dust_tickers": list(dust)},
        "notifications": {"would_send_any": would_send_any,
                          "telegram_sent": telegram_sent},
        "telegram_sent": telegram_sent,
        "delivery": "dashboard",
    }


def _write_store(tmp_path, records):
    store = tmp_path / "data" / "cio" / "cio_instrument_records.jsonl"
    store.parent.mkdir(parents=True, exist_ok=True)
    with open(store, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, default=str) + "\n")
    return store


# ── check 1: S0 attach + rehydrate ────────────────────────────────────────

def test_s0_is_green_when_a_turn_carries_a_plan_id_and_reads_back():
    out = check_s0_attach_rehydrate([_schd_with_defer()], probe=OK_PROBE)
    assert out["status"] == GREEN
    assert out["facts"]["read_back_ok_n"] == 1
    example = out["facts"]["read_back_examples"][0]
    assert example["plan_id"] == "plan_79fe9e72f2d4"
    assert example["subject_key"] == "HELD:SCHD"


def test_s0_is_red_when_no_record_carries_an_operator_turn():
    out = check_s0_attach_rehydrate(
        [_held_with_narrative("NOC", "held")], probe=OK_PROBE)
    assert out["status"] == RED
    assert "never attached" in out["reason"]


def test_s0_is_red_when_the_turn_lost_its_plan_id():
    """The plan_id is the whole point: a turn that cannot be traced back to the
    plan that raised it is the failure mode the record exists to prevent."""
    rec = _schd_with_defer()
    rec["last_operator_turn"] = dict(rec["last_operator_turn"], plan_id=None)
    out = check_s0_attach_rehydrate([rec], probe=OK_PROBE)
    assert out["status"] == RED
    assert "plan_id" in out["reason"]
    assert out["facts"]["records_with_operator_turn"] == 1


def test_s0_is_red_when_the_turn_moved_no_cognition():
    rec = _schd_with_defer()
    rec["next_research_question"] = None
    rec["next_eligible_at"] = None
    rec["cc_narrative"] = None
    out = check_s0_attach_rehydrate([rec], probe=OK_PROBE)
    assert out["status"] == RED
    assert "stored, not remembered" in out["reason"]


def test_s0_green_still_carries_the_caveat_when_no_wake_consumes_the_spine():
    """GREEN on the mechanism must not read as GREEN on the loop."""
    out = check_s0_attach_rehydrate(
        [_schd_with_defer()], probe=OK_PROBE, wake_consumers=[])
    assert out["status"] == GREEN
    assert out["caveat"] and "not yet a working loop" in out["caveat"]

    wired = check_s0_attach_rehydrate(
        [_schd_with_defer()], probe=OK_PROBE,
        wake_consumers=["scripts/lib/cio_wake.py"])
    assert wired["caveat"] is None


# ── check 2: CC narrative without a ping ──────────────────────────────────

def test_cc_is_green_when_a_non_schd_narrative_and_the_cash_letter_are_shown():
    held = _held_with_narrative("NOC", "NOC is held under desk@v5 defensive_observe "
                                       "with no open S1; observational only.")
    cash = _cash_sleeve()
    home = _home(texts=[held["cc_narrative"]["what"], cash["cc_narrative"]["what"]])
    out = check_cc_narrative_without_ping([held, cash], home, probe=OK_PROBE)
    assert out["status"] == GREEN
    assert out["facts"]["held_narrative_surfaced_n"] == 1
    assert out["facts"]["cash_letter_surfaced"] is True
    assert out["facts"]["no_ping"] is True


def test_cc_is_red_when_the_narrative_exists_on_the_record_but_not_in_the_payload():
    """The live failure: 12 narratives written, zero surfaced."""
    held = _held_with_narrative("NOC", "NOC is held under desk@v5, observational only.")
    cash = _cash_sleeve()
    out = check_cc_narrative_without_ping([held, cash], _home(), probe=OK_PROBE)
    assert out["status"] == RED
    assert "none appears in the CC payload" in out["reason"]
    assert out["facts"]["held_narrative_candidates_n"] == 1
    assert out["facts"]["held_narrative_surfaced_n"] == 0


def test_cc_is_red_when_the_narrative_is_shown_but_a_ping_would_fire():
    """Showing it silently is half the precondition, and the half easily lost."""
    held = _held_with_narrative("NOC", "NOC is held under desk@v5, observational only.")
    cash = _cash_sleeve()
    home = _home(texts=[held["cc_narrative"]["what"], cash["cc_narrative"]["what"]],
                 would_send_any=True)
    out = check_cc_narrative_without_ping([held, cash], home, probe=OK_PROBE)
    assert out["status"] == RED
    assert "ping is implicated" in out["reason"]


def test_cc_ignores_schd_because_schd_is_the_exception_not_the_proof():
    schd = _held_with_narrative("SCHD", "Operator deferred: wait for price buffer.")
    cash = _cash_sleeve()
    home = _home(texts=[schd["cc_narrative"]["what"], cash["cc_narrative"]["what"]])
    out = check_cc_narrative_without_ping([schd, cash], home, probe=OK_PROBE)
    assert out["status"] == RED
    assert out["facts"]["held_narrative_candidates_n"] == 0


def test_cc_cannot_verify_when_the_payload_could_not_be_fetched():
    out = check_cc_narrative_without_ping(
        [_held_with_narrative("NOC", "x" * 60), _cash_sleeve()], None,
        probe=OK_PROBE, home_error="URLError: connection refused")
    assert out["status"] == CANNOT_VERIFY
    assert "connection refused" in out["reason"]


# ── check 3: critique persisted ───────────────────────────────────────────

def test_critique_is_green_on_an_attached_artifact():
    rec = _held_with_narrative("V", "V held.")
    rec["last_artifact_id"] = "grok_critique_3d2314e10dc2"
    rec["last_outcome"] = "attached"
    out = check_critique_persisted([rec], probe=OK_PROBE)
    assert out["status"] == GREEN
    assert out["facts"]["attach_n"] == 1


def test_critique_is_green_on_a_reject_and_names_it_a_reject():
    """A reject counts for more: it is the branch that proves the desk can
    learn from a refusal instead of re-asking the prompt that failed closed."""
    rec = _held_with_narrative("V", "V held.")
    rec["last_outcome"] = "rejected"
    rec["last_artifact_id"] = "grok_critique_rejected"
    rec["research_blocked"] = True
    out = check_critique_persisted([rec], probe=OK_PROBE)
    assert out["status"] == GREEN
    assert out["facts"]["reject_n"] == 1
    assert out["facts"]["attach_n"] == 0


def test_critique_is_green_on_a_grok_lesson_even_without_an_artifact_id():
    rec = _held_with_narrative("V", "V held.")
    rec["lessons"] = [{"lesson_id": "grok_critique:abc", "claim": "counter-thesis"}]
    out = check_critique_persisted([rec], probe=OK_PROBE)
    assert out["status"] == GREEN


def test_critique_is_red_when_nothing_was_ever_written_back():
    """The live state: 40 records, not one carries an artifact or an outcome."""
    out = check_critique_persisted(
        [_held_with_narrative("NOC", "NOC held."), _cash_sleeve()], probe=OK_PROBE)
    assert out["status"] == RED
    assert "no critique has ever been written back" in out["reason"]
    assert out["facts"]["records_with_critique_n"] == 0


# ── check 4: dust and cash-as-a-ticker actually refuse ────────────────────

def test_dust_and_cash_are_green_and_the_gate_really_refuses():
    out = check_dust_cash_refused(
        [_held_with_narrative("NOC", "NOC held."), _cash_sleeve()], probe=OK_PROBE,
        dust_tickers=["JEPI", "LDOS", "SCHG", "SRNE"])
    assert out["status"] == GREEN
    assert out["facts"]["gate_failures"] == []
    assert out["facts"]["control_symbol_mintable"] is True
    assert out["facts"]["stored_leaks"] == []


def test_the_refusal_is_real_not_asserted():
    """Drive the real is_mintable, so the test fails if the rule is ever relaxed."""
    from scripts.lib.cio_instrument_record import is_mintable
    assert is_mintable("HELD", "CASH")[0] is False
    assert is_mintable("HELD", "CASH")[1] == "cash_or_test_ticker"
    assert is_mintable("HELD", "USD")[0] is False
    assert is_mintable("HELD", "TEST")[0] is False
    assert is_mintable("HELD", "DUSTY", market_value=49.99)[0] is False
    assert is_mintable("HELD", "DUSTY", market_value=49.99)[1] == "dust_residual"
    assert is_mintable("HELD", "DUSTY", market_value=-1.0)[0] is False
    # and the gate is not simply refusing everything
    assert is_mintable("HELD", "NOC", market_value=127.67)[0] is True
    assert is_mintable("SLEEVE", "CASH")[0] is True     # cash IS a sleeve


def test_dust_is_red_when_a_cash_ticker_leaked_into_the_store_as_a_holding():
    """$630k of cash reappearing as a fake position is the whole point of the rule."""
    leak = new_record("HELD", "CASH")
    leak["subject_key"] = "HELD:CASH"
    out = check_dust_cash_refused([leak], probe=OK_PROBE)
    assert out["status"] == RED
    assert "cash-as-a-ticker" in out["reason"]
    assert out["facts"]["stored_leaks"][0]["why"] == "cash_or_test_ticker_as_instrument"


def test_dust_is_red_when_a_live_dust_ticker_still_holds_a_record():
    stale = _held_with_narrative("SCHG", "SCHG held.")
    out = check_dust_cash_refused([stale], probe=OK_PROBE, dust_tickers=["SCHG"])
    assert out["status"] == RED
    assert out["facts"]["stored_leaks"][0]["why"] == "live_dust_ticker_has_a_record"


# ── the wrong root reports CANNOT VERIFY, never RED ───────────────────────

def test_a_tree_with_no_data_dir_cannot_verify_rather_than_failing(tmp_path):
    """The bug this pins: run from a worktree with no data/, see zero records,
    and report four REDs about a spine that was never broken."""
    probe = probe_root(tmp_path)
    assert probe["verdict"] == ROOT_NO_CIO_DIR
    assert str(tmp_path) in probe["reason"]
    assert "CURRENT" in probe["reason"]          # says how to fix it

    board = build_board(tmp_path, home=_home())
    assert board["counts"][CANNOT_VERIFY] == 4
    assert board["counts"][RED] == 0
    assert board["counts"][GREEN] == 0
    for chk in board["checks"]:
        assert chk["status"] == CANNOT_VERIFY
        assert chk["store_path_resolved"].endswith(
            "data/cio/cio_instrument_records.jsonl")


def test_a_cio_dir_with_no_record_store_cannot_verify(tmp_path):
    (tmp_path / "data" / "cio").mkdir(parents=True)
    probe = probe_root(tmp_path)
    assert probe["verdict"] == ROOT_NO_RECORD_STORE
    board = build_board(tmp_path, home=_home())
    assert board["counts"][CANNOT_VERIFY] == 4 and board["counts"][RED] == 0


def test_an_empty_store_reads_as_cannot_verify_not_as_a_broken_spine(tmp_path):
    _write_store(tmp_path, [])
    probe = probe_root(tmp_path)
    assert probe["verdict"] == ROOT_EMPTY_STORE
    assert "not a RED" in probe["reason"]
    board = build_board(tmp_path, home=_home())
    assert board["counts"][CANNOT_VERIFY] == 4 and board["counts"][RED] == 0


def test_the_probe_reports_ok_and_the_resolved_path_for_a_real_store(tmp_path):
    _write_store(tmp_path, [_schd_with_defer()])
    probe = probe_root(tmp_path)
    assert probe["verdict"] == ROOT_OK
    assert probe["subjects"] == 1 and probe["rows"] == 1
    assert probe["store_path_resolved"].endswith("cio_instrument_records.jsonl")


def test_load_records_follows_the_explicit_root_not_the_cwd(tmp_path, monkeypatch):
    """CIO stores use relative paths, so the CWD can silently redirect a read.
    Passing the root explicitly is what makes this board trustworthy."""
    _write_store(tmp_path, [_schd_with_defer()])
    monkeypatch.chdir(tmp_path.parent)
    assert [r["subject_key"] for r in load_records(tmp_path)] == ["HELD:SCHD"]


# ── the board as a whole ──────────────────────────────────────────────────

def test_a_fully_healthy_tree_boards_four_greens(tmp_path):
    held = _held_with_narrative("NOC", "NOC is held under desk@v5 defensive_observe, "
                                       "observational lifecycle note only.")
    critiqued = _held_with_narrative("V", "V is held with no open S1.")
    critiqued["last_artifact_id"] = "grok_critique_3d2314e10dc2"
    critiqued["last_outcome"] = "attached"
    cash = _cash_sleeve()
    _write_store(tmp_path, [_schd_with_defer(), held, critiqued, cash])

    home = _home(texts=[held["cc_narrative"]["what"], cash["cc_narrative"]["what"]])
    board = build_board(tmp_path, home=home)
    assert board["counts"][GREEN] == 4, [c["reason"] for c in board["checks"]]
    assert board["all_green"] is True
    assert board["record_counts_by_kind"] == {"HELD": 3, "SLEEVE": 1}


def test_the_board_reports_two_red_when_narratives_and_critiques_are_missing(tmp_path):
    """The live shape as of 2026-08-29: the spine persists, nothing consumes it."""
    held = _held_with_narrative("NOC", "NOC is held under desk@v5, observational.")
    _write_store(tmp_path, [_schd_with_defer(), held, _cash_sleeve()])
    board = build_board(tmp_path, home=_home())
    statuses = {c["id"]: c["status"] for c in board["checks"]}
    assert statuses["S0_ATTACH_REHYDRATE"] == GREEN
    assert statuses["CC_NARRATIVE_NO_PING"] == RED
    assert statuses["CRITIQUE_PERSISTED"] == RED
    assert statuses["DUST_CASH_REFUSED"] == GREEN
    assert board["all_green"] is False


def test_the_board_writes_nothing_to_the_store(tmp_path):
    """READ_ONLY_ADVISORY is a claim the board has to be able to survive."""
    store = _write_store(tmp_path, [_schd_with_defer(), _cash_sleeve()])
    before = store.read_bytes()
    build_board(tmp_path, home=_home())
    build_board(tmp_path, home=None, home_error="skipped")
    assert store.read_bytes() == before


def test_render_names_the_status_and_the_store_path(tmp_path):
    _write_store(tmp_path, [_schd_with_defer(), _cash_sleeve()])
    text = render(build_board(tmp_path, home=_home()))
    assert "CIOPreconditionsBoard@v1" in text
    assert "CANNOT_VERIFY" not in text.split("PRECONDITIONS")[0].split("root probe")[0]
    assert str(tmp_path) in text
    assert "LIVE NOTIFY RAILS" in text


# ── the rails are read, not asserted ──────────────────────────────────────

def test_policy_notify_is_parsed_from_the_file_including_a_true_master(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "cio_llm_policy.yaml").write_text(
        "situation_notify_telegram: true    # master\n"
        "notify_situation_types:\n"
        "  - S6_CONCENTRATION_OR_DISPOSITION\n"
        "notify_cooldown_hours: 12\n", encoding="utf-8")
    out = read_policy_notify(tmp_path)
    assert out["policy_readable"] is True
    assert out["situation_notify_telegram"] is True
    assert out["notify_situation_types"] == ["S6_CONCENTRATION_OR_DISPOSITION"]


def test_a_commented_out_master_is_not_mistaken_for_the_live_value(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "cio_llm_policy.yaml").write_text(
        "# situation_notify_telegram: true\n"
        "situation_notify_telegram: false\n", encoding="utf-8")
    assert read_policy_notify(tmp_path)["situation_notify_telegram"] is False


def test_notify_rails_never_invent_a_value_when_nothing_can_be_read(tmp_path):
    rails = notify_rails(tmp_path, pid=-1)
    assert rails["policy_readable"] is False
    assert rails["situation_notify_telegram"] is None
    assert rails["notify_enabled"] is False
    assert rails["env"] == {}


def test_the_rails_report_secrets_are_not_collected(tmp_path, monkeypatch):
    """The server env holds bot tokens next to the flags; only flags come back."""
    rails = notify_rails(tmp_path, pid=-1)
    blob = json.dumps(rails)
    assert "TOKEN" not in blob and "CHAT_ID" not in blob


# ── spine wiring is a printed fact, not an inference ──────────────────────

def test_scan_wake_consumers_excludes_the_libraries_and_the_migrator(tmp_path):
    scripts = tmp_path / "scripts" / "lib"
    scripts.mkdir(parents=True)
    (tmp_path / "scripts" / "cio_migrate_instrument_records.py").write_text(
        "from scripts.lib.cio_instrument_record import new_record\n", encoding="utf-8")
    (scripts / "cio_rehydrate.py").write_text(
        "from scripts.lib.cio_instrument_record import apply_cognition\n",
        encoding="utf-8")
    assert scan_wake_consumers(tmp_path) == []

    (scripts / "cio_wake.py").write_text(
        "from scripts.lib.cio_rehydrate import gate_input_from_record\n",
        encoding="utf-8")
    assert scan_wake_consumers(tmp_path) == ["scripts/lib/cio_wake.py"]
