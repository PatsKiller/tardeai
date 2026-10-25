"""Binding EXCEPTIONS_MATRIX fixtures; historical 24 tests are not acceptance."""
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.conflicts.engine import Input, Subject, evaluate, headline
from scripts.lib.conflicts.profiles import SecurityStanceProfile
from scripts.lib.conflicts.profiles.security import trading_age
from scripts.lib.conflicts.profiles.vocabulary import ordinal, posture

NOW = datetime(2026, 10, 23, 19, tzinfo=timezone.utc)
SEC = SecurityStanceProfile()


def run(stance="WATCH", *inputs, held=False, history=(), context=None, canonical=None):
    subject = Subject("security", "guid", "FIXTURE", {"held": held, "identity_confirmed": True,
                      "concentration_policy": {"weight_pct": 1, "limit_pct": 12, "instrument_class": "single_stock"},
                      **(context or {})})
    c = canonical or (Input("curator", stance, NOW) if stance is not None else None)
    return evaluate(subject, c, inputs, SEC, now=NOW, history=history)


def flags(rows):
    return [r for r in rows if r.kind in {"CONFLICT", "NEEDS_OPERATOR", "GATE", "DATA_ERROR"}]


@pytest.mark.parametrize("a,b,held,relation", [
    ("ADD", "HOLD", True, "compatible"), ("HOLD", "TRIM", True, "compatible"),
    ("TRIM", "EXIT", True, "compatible"), ("ADD", "TRIM", True, "opposite"),
    ("ADD", "EXIT", True, "opposite"), ("HOLD", "EXIT", True, "opposite"),
    ("WATCH", "AVOID", False, "compatible"), ("WATCH", "SELL", False, "compatible"),
    ("BUY", "WATCH", False, "opposite"), ("RE_ENTER", "AVOID", False, "opposite"),
    ("WATCH", "HOLD", True, "compatible"), ("AVOID", "TRIM", True, "compatible"),
    ("HOLD", "HOLD", True, "same"), ("SELL", "EXIT", True, "compatible"),
    ("ACCUMULATE", "ADD", True, "compatible"), ("WAIT", "WATCH", False, "compatible"),
    ("KEEP", "HOLD", True, "compatible"), ("PASS", "SELL", False, "compatible"),
    ("ENTER", "BUY", False, "compatible"), ("NEAR_ENTRY", "RE_ENTER", False, "compatible"),
    ("TRIM", "HOLD", False, "compatible"), ("BUY_READY", "ADD", True, "unknown")])
def test_e1_e22_position_aware_ordinal(a, b, held, relation):
    assert SEC.compare(a, b, Subject("security", "guid", "X", {"held": held})) == relation


@pytest.mark.parametrize("label", ["ADD_ON_PULLBACK", "RESEARCH_MORE", "MORE_RESEARCH", "INSUFFICIENT_DATA",
    "HOLD / MONITOR", "BUY_READY", "NO_ACTION", "DEFER", "SELL_TAXABLE"])
def test_unmapped_labels_are_visible_errors(label):
    fs = run("WATCH", Input("desk", label, NOW))
    assert [(f.kind, f.rule) for f in fs] == [("DATA_ERROR", "R8")]
    assert posture(label) is None


def test_missing_stance_blocks_go_and_queues_working_compared_input_producer():
    fs = run(None)
    assert fs[0].kind == "GATE" and fs[0].rule == "R7" and "WATCH" in fs[0].summary
    assert fs[0].action == "queue_review"


@pytest.mark.parametrize("value", ["DETERMINISTIC_FAIL", "BLOCKED", "STALE", "DATA_UNAVAILABLE", "UNKNOWN"])
def test_t3_widened_trade_states_gate_even_held_add(value):
    fs = run("ADD", Input("trade_ai", value, NOW, role="gate", account="schwab_rollover_ira"), held=True)
    assert any(f.rule == "R3" and f.kind == "GATE" for f in fs)
    assert fs[0].sides[0]["account"] == "schwab_rollover_ira"


@pytest.mark.parametrize("value", ["READY", "WAIT", "MANAGING"])
def test_trade_states_that_do_not_gate(value):
    assert run("ADD", Input("trade_ai", value, NOW, role="gate"), held=True) == []


def test_trade_avoid_is_judgment_and_failed_partial_outputs_are_no_opinions():
    assert run("WATCH", Input("trade_ai", "AVOID", NOW)) [0].kind == "AGREEMENT"
    assert run("WATCH", Input("desk", "ADD", NOW, metadata={"quality": "partial"})) == []
    assert run("WATCH", Input("desk", "MAYBE", NOW, metadata={"quality": "failed"})) == []


def test_oldest_material_input_beats_fresh_run_time():
    c = Input("curator", "ADD", NOW, inputs_as_of=NOW - timedelta(days=20))
    fs = run(canonical=c)
    assert any(f.rule == "R7b" and f.kind == "GATE" for f in fs)


def test_weekend_and_holiday_are_not_trading_age():
    friday = datetime(2026, 10, 23, 19, tzinfo=timezone.utc)
    sunday = datetime(2026, 10, 25, 19, tzinfo=timezone.utc)
    monday_pre = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
    assert trading_age(friday, sunday) == trading_age(friday, monday_pre) == 0
    assert trading_age(datetime(2026, 12, 24, 19, tzinfo=timezone.utc), datetime(2026, 12, 27, 19, tzinfo=timezone.utc)) == 0


def test_missing_material_time_is_stale_not_a_silent_agreement():
    fs = run(canonical=Input("curator", "ADD", None))
    assert [(f.kind, f.rule) for f in fs] == [("GATE", "R1")]


def test_source_age_not_canonical_delta_drives_superseded():
    old = Input("watchlist CIO review", "ADD", NOW - timedelta(days=8))
    fs = run("WATCH", old)
    assert [(f.kind, f.rule) for f in fs] == [("SUPERSEDED", "R1")]
    assert headline(fs) is None


def test_wash_loss_window_applies_across_ira_and_taxable_accounts():
    fs = run("ADD", Input("wash_sale", "BLOCKED", NOW, role="gate", account="schwab_taxable"), held=True)
    assert fs[0].rule == "R9" and fs[0].never_auto
    assert fs[0].key.endswith("all_accounts")


def test_pending_fill_freezes_judgments_and_never_becomes_resolvable():
    fs = run("ADD", Input("stop", "AWAITING_FILL", NOW, role="protection"), Input("desk", "EXIT", NOW), held=True)
    assert len(fs) == 1 and fs[0].kind == "DATA_ERROR" and fs[0].rule == "R12" and fs[0].never_auto


def test_safety_and_identity_beat_recorded_operator_judgment():
    decision = Input("operator", "ADD", NOW, metadata={"recorded_by": "operator", "reason": "fixture",
                                                    "expires_at": NOW + timedelta(days=1)})
    fs = run("WATCH", decision, Input("kill", "ENGAGED", NOW, role="safety"), context={"identity_confirmed": False})
    assert {f.rule for f in fs} == {"T0", "R16"}
    assert all(f.never_auto and f.kind == "GATE" for f in fs)


def test_held_exit_vs_add_requires_operator_and_all_n_way_sides_are_kept():
    fs = run("ADD", Input("desk", "EXIT", NOW), Input("advisory", "TRIM", NOW), held=True)
    assert len(fs) == 1 and fs[0].kind == "NEEDS_OPERATOR" and len(fs[0].sides) == 3


def test_paper_signals_escalation_counts_and_archived_names_never_vote():
    assert run("WATCH", Input("paper", "ADD", NOW, metadata={"paper": True})) == []
    assert run("WATCH", Input("agents", "ADD", NOW, metadata={"intra_synthesis": True})) == []
    assert run("ADD", Input("desk", "EXIT", NOW), context={"unwatched": True}) == []


def test_option_equity_scope_is_separate_except_contradiction():
    assert run("HOLD", Input("options", "WIN", NOW, metadata={"instrument": "option"}), held=True) == []
    fs = run("EXIT", Input("options", "LONG_CALL", NOW, metadata={"instrument": "option"}), held=True)
    assert fs[0].rule == "R10" and fs[0].kind == "NEEDS_OPERATOR"


def test_hysteresis_requires_two_runs_and_small_conviction_noise_keeps_decision():
    desk = Input("desk", "ADD", NOW)
    first = run("WATCH", desk)
    assert headline(first) is None and first[0].rule == "R15"
    history = [{"key": "security:guid:U7:desk", "signature": [["curator", 1], ["desk", 0]]}]
    assert run("WATCH", desk, history=history)[0].kind == "CONFLICT"
    for conviction in [69, 70, 71]:
        fs = run("WATCH", desk, history=history, context={"conviction": conviction,
                 "decision_anchor": {"signature": history[0]["signature"], "conviction": 70}})
        assert headline(fs) is None


def test_every_flag_has_owner_clear_condition_and_next_run():
    fs = run("ADD", Input("policy", "BREACH", NOW, role="policy"), Input("trade_ai", "STALE", NOW, role="gate"), held=True)
    assert all(f.owner and f.clears_when and f.next_run for f in flags(fs))


@pytest.mark.parametrize("asset,weight,limit,breach", [("broad_fund", 16.8, 25, False),
    ("broad_fund", 25.1, 25, True), ("thematic_fund", 12.1, 12, True),
    ("single_stock", 22.6, 12, True), ("leveraged_inverse", 5.1, 5, True)])
def test_r13_consumes_w1_class_specific_policy_without_local_default(asset, weight, limit, breach):
    rows = run("ADD", held=True, context={"concentration_policy": {"instrument_class": asset,
        "weight_pct": weight, "limit_pct": limit, "approval_ref": "EXCEPTIONS_MATRIX R13 2026-10-24"}})
    assert bool(flags(rows)) == breach
    if breach:
        assert rows[0].kind == "NEEDS_OPERATOR" and rows[0].never_auto


def test_r13_missing_fund_coverage_never_means_zero_exposure():
    rows = run("ADD", held=True, context={"concentration_policy": {"gap": {"reason": "fund holdings incomplete"}}})
    assert rows[0].kind == "GATE" and rows[0].rule == "R13"


def test_naive_and_unreadable_material_times_are_data_errors():
    for bad in [NOW.replace(tzinfo=None), "unreadable"]:
        rows = run(canonical=Input("curator", "ADD", bad))
        assert rows[0].kind == "DATA_ERROR"


def test_hysteresis_does_not_reuse_an_older_nonconsecutive_observation():
    history = [{"key": "security:guid:U7:desk", "signature": [["curator", 1], ["desk", 0]]},
               {"key": "other", "signature": []}]
    rows = run("WATCH", Input("desk", "ADD", NOW), history=history)
    assert headline(rows) is None and rows[0].rule == "R15"
