"""Producer-boundary and exact-source fixture checks, all clocks pinned."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from scripts.lib.conflicts.adapters import (evaluate_inputs, findings_section, numeric_inputs,
    schedule_inputs, security_inputs, security_inputs_from_truth)
from scripts.lib.conflicts.engine import Input
from scripts.lib.conflicts.profiles.rulebook import load_rulebook

NOW = datetime(2026, 10, 24, 23, tzinfo=timezone.utc)
AT = NOW.isoformat()
FIXTURES = Path(__file__).parent / "fixtures/conflicts"


def sec(**kwargs):
    bundle = security_inputs(**{"security_guid": "confirmed-fixture-guid", "symbol": "SPCX", "held": True,
                               "canonical": {"stance": "ADD", "as_of": AT}, **kwargs})
    bundle.subject.context["concentration_policy"] = {"weight_pct": 1, "limit_pct": 12, "instrument_class": "single_stock"}
    return bundle


def test_exact_real_opportunity_rows_keep_evidence_clock_and_do_not_mint_guid():
    rows = json.loads((FIXTURES / "opportunity_rows.json").read_text())
    assert rows["provenance"]["sha256"] and len(rows["items"]) == 16
    for symbol, row in rows["items"].items():
        bundle = security_inputs(security_guid=None, symbol=symbol, canonical=row, held=None)
        assert bundle.canonical.as_of.isoformat() == row["as_of"]
        findings = evaluate_inputs(bundle, now=NOW)
        assert any(f.kind == "DATA_ERROR" for f in findings)
        assert not any(f.kind == "CONFLICT" for f in findings)
        assert bundle.subject.kind == "identity" and bundle.subject.id == symbol


def test_watch_review_and_synthesis_keep_their_distinct_evidence_times():
    old = (NOW - timedelta(days=60)).isoformat()
    b = sec(card={"symbol": "SPCX", "cio_review": {"verdict": "HOLD", "completed_at": old},
                  "decision": {"inputs": {"synthesis": "SELL", "synthesis_at": AT}}})
    fs = evaluate_inputs(b, now=NOW)
    assert [(f.kind, f.rule) for f in fs] == [("AGREEMENT", "R6"), ("NEEDS_OPERATOR", "U7")]
    assert fs[0].sides[1]["as_of"] == old
    assert fs[1].sides[1]["as_of"] == AT


@pytest.mark.parametrize("bad", [None, "invalid", "2026-10-24T23:00:00", "2026-10-25T23:00:00Z"])
def test_invalid_canonical_time_is_data_error_without_judgment(bad):
    fs = evaluate_inputs(sec(canonical={"stance": "ADD", "as_of": bad}), now=NOW)
    assert "CONFLICT" not in [f.kind for f in fs]
    assert any(f.kind == ("GATE" if bad is None else "DATA_ERROR") for f in fs)


@pytest.mark.parametrize("extra", [Input("x", "ADD", NOW, role="unknown"),
    Input("stop", "MAYBE", NOW, role="protection"), Input("gate", "MAYBE", NOW, role="gate"),
    Input("x", "SELL", NOW, subject_id="another-guid")])
def test_bad_identity_role_and_role_vocabulary_never_silently_agree(extra):
    assert [f.kind for f in evaluate_inputs(sec(extras=[extra]), now=NOW)] == ["DATA_ERROR"]


def test_w1_unknown_holdings_never_defaults_to_unheld():
    truth = {"security_guid": "guid", "canonical": {"source": "CIO record", "value": "ADD", "as_of": AT},
             "context": {"held": None}}
    assert all(f.kind == "DATA_ERROR" for f in evaluate_inputs(security_inputs_from_truth(truth), now=NOW))


def test_w1_filled_stop_while_still_held_needs_operator_and_named_account():
    truth = {"security_guid": "guid", "canonical": {"source": "CIO record", "value": "ADD", "as_of": AT},
             "context": {"held": True}, "protection_inputs": [{"source": "stop_last_known", "value": "filled",
             "as_of": AT, "account": "schwab_rollover_ira", "subject_id": "guid"}]}
    fs = evaluate_inputs(security_inputs_from_truth(truth), now=NOW)
    assert [f.kind for f in fs] == ["DATA_ERROR"] and fs[0].never_auto
    assert fs[0].sides[0]["account"] == "schwab_rollover_ira"


def test_count_difference_of_one_is_not_rounding_noise():
    fs = evaluate_inputs(numeric_inputs("position_count", {"source": "W1", "value": 12, "as_of": AT},
        [{"source": "header", "value": 13, "as_of": AT}], unit="count"), now=NOW)
    assert [f.kind for f in fs] == ["CONFLICT"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, None])
def test_invalid_numeric_observation_is_data_error(bad):
    fs = evaluate_inputs(numeric_inputs("total", {"source": "W1", "value": 100, "as_of": AT},
        [{"source": "header", "value": bad, "as_of": AT}]), now=NOW)
    assert [f.kind for f in fs] == ["DATA_ERROR"]


def test_schedule_adapter_preserves_registry_and_observation():
    b = schedule_inputs("lane", {"source": "lane_registry", "state": "RETIRED", "as_of": AT},
                        [{"source": "crontab", "state": "ACTIVE", "as_of": AT}])
    fs = evaluate_inputs(b, now=NOW)
    assert fs[0].action == "notify_operator" and fs[0].rule == "U7"
    section = findings_section(fs)
    assert section["findings"][0]["key"] == "job:lane:U7:crontab"
    assert section["headline"] and section["gap"] is None


def test_rulebook_does_not_assert_operator_ratification_or_live_authority():
    doc = load_rulebook()
    assert doc["status"] == "PROPOSED" and doc["approval"] is None and not doc["live_enabled"]


def test_failed_paper_and_intra_synthesis_inputs_do_not_become_data_error_sides():
    for metadata in [{"paper": True}, {"quality": "failed"}, {"intra_synthesis": True}]:
        assert evaluate_inputs(sec(extras=[Input("ignored", "UNMAPPED", None, metadata=metadata)]), now=NOW) == []


def test_option_contradiction_reaches_scope_rule_without_equity_vocabulary_error():
    fs = evaluate_inputs(sec(canonical={"stance": "EXIT", "as_of": AT},
        extras=[Input("options", "LONG_CALL", NOW, metadata={"instrument": "option"})]), now=NOW)
    assert [(f.kind, f.rule) for f in fs] == [("NEEDS_OPERATOR", "R10")]
