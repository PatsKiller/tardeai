"""Operator decisions 2026-09-15: the CIO owns entry state / BUY; operator and CIO are alerted; small caps labeled."""

from __future__ import annotations

import ast
import copy
import re
import sys
import types
import json
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import cio_entry_state as ces  # noqa: E402
from lib.market_cap_label import cap_label  # noqa: E402
import operator_alert_policy_v2 as policy  # noqa: E402

TODAY = date(2026, 9, 15)
PORTFOLIO_UNAVAILABLE = {"status": "UNAVAILABLE", "flags": [], "unknowns": ["fixture portfolio facts"]}


@pytest.fixture(autouse=True)
def isolated_packet_inputs(tmp_path, monkeypatch):
    """Exercise the real packet renderer using contained public DTO stores only."""
    from scripts.lib import cio_options_fluency as fluency

    paths = {}
    for name, document in (
        ("OPTIONS_DESK_RUNTIME_CANDIDATES", {"by_symbol": {}}),
        ("GOALS_PROJECTION_CANDIDATES", {"goals": {}}),
        ("ENRICHMENT_CANDIDATES", {}),
    ):
        path = tmp_path / (name.lower() + ".json")
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[path] = document
        monkeypatch.setattr(fluency, name, (path,))
    load_json = fluency._load_json

    def fixture_json(path):
        assert path in paths, f"Unexpected packet store: {path}"
        return load_json(path)

    monkeypatch.setattr(fluency, "_load_json", fixture_json)


def ev(**kw):
    base = {
        "symbol": "ACHV",
        "price": 7.0,
        "quote_age_h": 0.2,
        "entry_low": 6.9,
        "entry_high": 7.15,
        "stop": 6.6,
        "target": 9.5,
        "atr": 0.40,
        "quality_state": "ADMITTED",
        "cio_action": "RESEARCH_MORE",
        "wash_blocked": False,
        "held": False,
        "earnings_date": "2026-11-05",
        "market_cap_label": cap_label(744),
        "catalyst": "Frazier Life Sciences buys new stake",
        "plan_source": "reentry_desk",
        "portfolio_facts": dict(PORTFOLIO_UNAVAILABLE),
    }
    base.update(kw)
    return base


def test_price_inside_zone_is_buy_ready():
    r = ces.evaluate(ev(), today=TODAY)
    # R:R is measured from the TOP of the zone (the worst fill inside it): (9.50 - 7.15) / (7.15 - 6.60)
    assert r["state"] == "BUY_READY" and r["rr"] == 4.27 and r["reasons"] == []


def test_just_above_zone_is_entry_near():
    r = ces.evaluate(ev(price=7.25), today=TODAY)
    assert r["state"] == "ENTRY_NEAR" and r["distance_pct"] == 1.4


def test_within_one_atr_counts_as_near_even_past_three_percent():
    r = ces.evaluate(ev(price=7.50, entry_high=7.15, atr=0.40), today=TODAY)
    assert r["state"] == "ENTRY_NEAR"


def test_far_above_zone_is_not_yet():
    assert ces.evaluate(ev(price=8.5), today=TODAY)["state"] == "NOT_YET"


def test_blocking_reasons():
    cases = {
        "quality gate quarantined": ev(quality_state="QUARANTINED"),
        "CIO decision is TRIM_REVIEW": ev(cio_action="TRIM_REVIEW"),
        "wash-sale window": ev(wash_blocked=True),
        "quote is 6.0h old": ev(quote_age_h=6.0),
        "plan R:R 0.82 is below 2.0": ev(target=7.6),
        "earnings in 1 day(s)": ev(earnings_date="2026-09-16"),
        "price is at or below the plan stop": ev(price=6.5, entry_low=6.4, stop=6.6),
        "no entry zone in the plan": ev(entry_low=None, entry_high=None),
    }
    for reason, e in cases.items():
        r = ces.evaluate(e, today=TODAY)
        assert r["state"] == "BLOCKED" and reason in r["reasons"], (reason, r["reasons"])


def test_research_more_does_not_block_the_cio_reviews_it():
    assert ces.evaluate(ev(cio_action="RESEARCH_MORE"), today=TODAY)["state"] == "BUY_READY"


def test_operator_message_labels_small_cap_and_is_advisory():
    r = ces.evaluate(ev(market_cap_label=cap_label(744)), today=TODAY)
    msg = ces.render_operator(r, ev(market_cap_label=cap_label(744)))
    assert msg.startswith("🟢 CIO entry — BUY READY: ACHV")
    assert "Small cap · $744M" in msg and "Advisory only" in msg
    for noisy in ("WAIT", "AVOID", "GO-Tier", "🎯", "PROPOSAL"):
        assert noisy not in msg


def test_operator_message_names_the_company_and_sector():
    """The alert must say WHAT it is, not just the ticker.

    Until 2026-09-21 this message carried a bare ticker and a market-cap pill: the
    operator was asked to decide on "ESE" without being told it is Esco Technologies,
    a Technology name. Every field was already in symbol_profiles; the runner simply
    never queried that table.
    """
    r = ces.evaluate(ev(), today=TODAY)
    msg = ces.render_operator(
        r,
        ev(
            company="Esco Technologies Inc — Scientific & Technical Instruments.",
            sector="Technology",
            industry="Scientific & Technical Instruments",
        ),
    )
    assert "Esco Technologies Inc" in msg
    assert "Technology" in msg
    # description_1s already ends with the industry, so it must not be repeated
    assert msg.count("Scientific & Technical Instruments") == 1
    # and the trailing full stop from description_1s is not carried into the line
    assert "Instruments. ·" not in msg


def test_identity_line_is_omitted_when_no_profile_exists():
    """A blank identity line under a BUY READY call is worse than no line.

    symbol_profiles covers ~3,136 symbols, fewer than the tracked set, so the absent
    case is normal and must render nothing rather than an empty or dangling separator.
    """
    r = ces.evaluate(ev(), today=TODAY)
    msg = ces.render_operator(r, ev())  # ev() carries no company/sector/industry
    lines = msg.split("\n")
    assert all(ln.strip() not in {"", "·", "—"} for ln in lines), lines
    # the line after the header is the cap pill, not an empty identity slot
    assert lines[1].startswith("Small cap")


def test_identity_falls_back_to_sector_and_industry_without_a_company_name():
    r = ces.evaluate(ev(), today=TODAY)
    msg = ces.render_operator(r, ev(company=None, sector="Energy", industry="Oil & Gas Equipment & Services"))
    assert "Energy · Oil & Gas Equipment & Services" in msg


def test_operator_message_routes_immediate_and_router_does_not_suppress():
    r = ces.evaluate(ev(price=7.25), today=TODAY)
    msg = ces.render_operator(r, ev(price=7.25))
    event = policy.classify_legacy_message(msg)
    assert event.alert_type == "cio_entry_state"
    assert policy.route_event(event).route_mode == policy.ROUTE_IMMEDIATE
    import telegram_alert_router as router

    assert router.classify_alert(msg) == "P0_INTERRUPT"


def test_cio_message_asks_the_cio_to_confirm():
    r = ces.evaluate(ev(), today=TODAY)
    text = ces.render_cio(r, ev())
    assert "Entry state BUY_READY for ACHV (Small cap · $744M)" in text and "Confirm or refute" in text


def test_transition_key_is_per_symbol_state_day():
    r = ces.evaluate(ev(), today=TODAY)
    assert ces.transition_key(r, TODAY) == "cio_entry:ACHV:BUY_READY:2026-09-15"


def test_runner_contracts(monkeypatch):
    src = (ROOT / "scripts" / "cio_entry_state_runner.py").read_text(encoding="utf-8")
    assert 'ap.add_argument("--apply"' in src and "conn.rollback()" in src
    assert "send_alerts(r, evidence" in src and src.index("if a.apply:") < src.index("send_alerts(r, evidence")
    _assert_runner_signal(_runner(), monkeypatch)
    assert "latest_cio_decisions(cur, syms)" in src
    shared = (ROOT / "scripts/lib/entry_alert_context.py").read_text(encoding="utf-8")
    assert "action_class <> 'entry'" in shared  # shared lookup excludes the runner's own entry rows
    for forbidden in ("place_order", "submit_order", "/orders"):
        assert forbidden not in src


def test_digest_message_routes_like_single_alerts():
    rs = [ces.evaluate(ev(symbol="RTX"), today=TODAY), ces.evaluate(ev(symbol="NEE", price=7.25), today=TODAY)]
    text = ces.render_digest(rs)
    assert text.startswith("🟢 CIO entry — 2 more names ready or getting close")
    assert "BUY READY: RTX" in text and "Getting close: NEE" in text
    assert policy.route_event(policy.classify_legacy_message(text)).route_mode == policy.ROUTE_IMMEDIATE


@pytest.mark.parametrize("cap", [-1, 0, 1, 3, 8])
def test_runner_digests_past_the_cap_and_marks_them_alerted(monkeypatch, tmp_path, cap):
    _assert_runner_digest(_runner(), monkeypatch, tmp_path, cap=cap)


def _assert_runner_signal(runner, monkeypatch):
    """Run the real alert function; all transport and store leaves are contained fakes."""
    from scripts.lib import advice_digest, cio_event_bus

    emitted = []

    class Bus:
        def emit(self, event, payload, **metadata):
            emitted.append((event, payload, metadata))

    monkeypatch.setattr(cio_event_bus, "CIOEventBus", Bus)
    monkeypatch.setattr(advice_digest, "hold", lambda _name: True)
    monkeypatch.setattr(runner, "cio_card_payload", lambda *_args: {"text": "fixture card"})
    monkeypatch.setattr(runner, "stamp_cio_stance", lambda text, *_args, **_kwargs: text)
    monkeypatch.setattr(runner, "operator_send", lambda *_args, **_kwargs: {"operator": True})
    result = ces.evaluate(ev(), today=TODAY)
    outcome = runner.send_alerts(result, ev())
    assert len(emitted) == 1, "entry must emit exactly one wake event"
    event, payload, metadata = emitted[0]
    assert event == "watch.new_signal"
    assert payload["symbol"] == result["symbol"] and payload["symbols"] == [result["symbol"]]
    assert payload["state"] == result["state"] and payload["signal"] == "cio_entry_state"
    assert metadata == {"source": "cio_entry_state_runner", "semantic_event_key": ces.transition_key(result)}
    assert outcome["cio_bus"] is True


def _assert_runner_digest(runner, monkeypatch, tmp_path, *, cap=1):
    """Exercise actual main slicing, digest rendering, and recorded alerted flags."""
    executed, direct, rendered, delivered = [], [], [], []

    class Cursor:
        def execute(self, sql, parameters=None):
            executed.append((sql, parameters))

    class Connection:
        def cursor(self):
            return Cursor()

        def commit(self):
            pass

        def rollback(self):
            pytest.fail("apply fixture must not enter dry rollback")

    evidence = {symbol: ev(symbol=symbol) for symbol in ("AA", "BB", "CC", "DD")}
    results = {symbol: ces.evaluate(item, today=TODAY) for symbol, item in evidence.items()}
    monkeypatch.setattr(runner, "_conn", Connection)
    monkeypatch.setattr(runner, "gather", lambda _cursor: evidence)
    monkeypatch.setattr(runner, "last_states", lambda _cursor: {s: "BUY_READY" for s in evidence})
    monkeypatch.setattr(runner, "alerted_today", lambda *_args: set())
    monkeypatch.setattr(runner, "starred_symbols", lambda _cursor: set())
    monkeypatch.setattr(runner.ces, "evaluate", lambda item: results[item["symbol"]])
    monkeypatch.setattr(runner.ces, "render_cio", lambda *_args: "fixture rationale")

    def render_digest(items):
        rendered.append([item["symbol"] for item in items])
        return "fixture digest"

    def send_single(result, _evidence):
        direct.append(result["symbol"])
        return {"operator": True}

    def send_digest(text, *, primary_symbols):
        delivered.append((text, primary_symbols))
        return {"operator": True}

    monkeypatch.setattr(runner.ces, "render_digest", render_digest)
    monkeypatch.setattr(runner, "prepare_packet_inputs", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(runner, "record_review", lambda *_args: None)
    monkeypatch.setattr(runner, "save_packet", lambda *_args: None)
    monkeypatch.setattr(runner, "follow_up_pending_reviews", lambda *_args: [])
    monkeypatch.setattr(runner, "send_alerts", send_single)
    monkeypatch.setattr(runner, "operator_send", send_digest)
    monkeypatch.setattr(runner, "stamp_cio_stance", lambda text, *_args, **_kwargs: text)
    monkeypatch.setattr(runner, "RECEIPT", tmp_path / "fixture-receipt.json")
    monkeypatch.setattr(sys, "argv", ["fixture-entry", "--apply", "--max-alerts", str(cap)])
    assert runner.main() == 0
    symbols = list(evidence)
    expected_direct, expected_digest = symbols[: max(0, cap)], symbols[max(0, cap) :]
    assert direct == expected_direct, "direct alerts must honor the nonnegative cap"
    assert rendered == ([expected_digest] if expected_digest else []), "digest must contain exactly the remainder"
    assert delivered == ([("fixture digest", expected_digest)] if expected_digest else [])
    digest_rows = [
        (sql, parameters)
        for sql, parameters in executed
        if parameters
        and isinstance(parameters[-1], str)
        and parameters[-1].startswith("{")
        and json.loads(parameters[-1]).get("via") == "digest"
    ]
    assert [parameters[0] for _, parameters in digest_rows] == expected_digest
    for sql, parameters in digest_rows:
        assert re.search(r"VALUES\s*\(\s*%s\s*,\s*%s\s*,\s*%s\s*,\s*true\s*,", sql, re.IGNORECASE), (
            "digest rows must be marked alerted"
        )
        assert parameters[1:3] == ("BUY_READY", "BUY_READY")


def _mutated_runner(mutation):
    """Compile one actual function with a deliberate defect, never edit production source."""
    original = _runner()
    name = "send_alerts" if mutation == "deleted_emit" else "main"
    tree = ast.parse((ROOT / "scripts/cio_entry_state_runner.py").read_text())
    function = copy.deepcopy(
        next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    )

    class BreakContract(ast.NodeTransformer):
        changed = 0

        def visit_Expr(self, node):
            if mutation == "deleted_emit" and isinstance(node.value, ast.Call):
                call = node.value
                if (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "emit"
                    and call.args
                    and isinstance(call.args[0], ast.Constant)
                    and call.args[0].value == "watch.new_signal"
                ):
                    self.changed += 1
                    return ast.copy_location(ast.Pass(), node)
            return self.generic_visit(node)

        def visit_Assign(self, node):
            if mutation == "wrong_slice" and any(isinstance(t, ast.Name) and t.id == "digest" for t in node.targets):
                assert isinstance(node.value, ast.Subscript) and isinstance(node.value.slice, ast.Slice)
                node.value.slice.upper, node.value.slice.lower = node.value.slice.lower, None
                self.changed += 1
            return self.generic_visit(node)

        def visit_Constant(self, node):
            if (
                mutation == "unmarked_digest"
                and isinstance(node.value, str)
                and "INSERT INTO cio_entry_states" in node.value
                and "%s,%s,%s,true,%s::jsonb" in node.value
            ):
                self.changed += 1
                return ast.copy_location(
                    ast.Constant(node.value.replace("%s,%s,%s,true,%s::jsonb", "%s,%s,%s,false,%s::jsonb")), node
                )
            return node

    breaker = BreakContract()
    function = breaker.visit(function)
    assert breaker.changed >= 1
    mutant = types.ModuleType("fixture_mutated_entry")
    mutant.__dict__.update(original.__dict__)
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), "contained-entry-mutant", "exec"
        ),
        mutant.__dict__,
    )
    return mutant


def test_signal_contract_rejects_deleted_emit(monkeypatch):
    with pytest.raises(AssertionError, match="exactly one wake event"):
        _assert_runner_signal(_mutated_runner("deleted_emit"), monkeypatch)


@pytest.mark.parametrize(
    "mutation,reason", [("wrong_slice", "exactly the remainder"), ("unmarked_digest", "marked alerted")]
)
def test_digest_contract_rejects_broken_effects(monkeypatch, tmp_path, mutation, reason):
    with pytest.raises(AssertionError, match=reason):
        _assert_runner_digest(_mutated_runner(mutation), monkeypatch, tmp_path)


# ── operator decision 2026-09-21: only page when it is time to purchase ──────
#
# "Only alert when time to purchase unless stared on watchlist"
#
# At 15:10 on 2026-09-21 the operator was paged two amber "getting close" cards
# -- GNL at +1.1% and LOMA at +2.9% above the zone -- for names that were not
# starred and on which no action was available. ENTRY_NEAR is a heads-up, not a
# purchase moment, so it now pages only for a starred symbol.


def _runner():
    import cio_entry_state_runner as runner

    return runner


def _near(sym):
    return {"symbol": sym, "state": "ENTRY_NEAR"}


def _ready(sym):
    return {"symbol": sym, "state": "BUY_READY"}


def test_getting_close_does_not_page_for_an_unstarred_symbol():
    """The GNL / LOMA regression, verbatim from the 15:10 alerts."""
    r = _runner()
    out = r.alert_worthy([_near("GNL"), _near("LOMA")], prior={}, done=set(), starred=set())
    assert out == [], [x["symbol"] for x in out]


def test_getting_close_still_pages_for_a_starred_symbol():
    """Starring is the operator's opt-in, so it must survive the new gate."""
    r = _runner()
    out = r.alert_worthy([_near("ANET"), _near("GNL")], prior={}, done=set(), starred={"ANET"})
    assert [x["symbol"] for x in out] == ["ANET"]


def test_buy_ready_always_pages_starred_or_not():
    """'Time to purchase' is exactly what the operator asked to keep."""
    r = _runner()
    out = r.alert_worthy([_ready("GNL"), _ready("ANET")], prior={}, done=set(), starred={"ANET"})
    assert [x["symbol"] for x in out] == ["GNL", "ANET"]


def test_starring_is_case_insensitive():
    r = _runner()
    out = r.alert_worthy([_near("anet")], prior={}, done=set(), starred={"ANET"})
    assert [x["symbol"] for x in out] == ["anet"]


def test_the_older_downgrade_suppression_still_applies_to_a_starred_name():
    """A starred symbol must not reopen the 2026-09-15 defect: ENTRY_NEAR after
    a same-day BUY_READY is still not news."""
    r = _runner()
    out = r.alert_worthy([_near("ANET")], prior={"ANET": "BUY_READY"}, done=set(), starred={"ANET"})
    assert out == []


def test_an_unreadable_star_store_fails_quiet_not_loud():
    """If the store cannot be read we page BUY_READY only -- never MORE alerts."""
    r = _runner()

    class Boom:
        def execute(self, *a, **k):
            raise RuntimeError("no such table")

    assert r.starred_symbols(Boom()) == set()


def test_held_alert_leads_with_add_decision_and_quote_rr():
    from scripts.lib import cio_entry_state as ces

    ev = {
        "symbol": "AXTI",
        "price": 78.17,
        "entry_low": 71.5,
        "entry_high": 74.5,
        "stop": 67.5,
        "target": 96.5,
        "held": True,
        "catalyst": None,
        "portfolio_facts": dict(PORTFOLIO_UNAVAILABLE),
    }
    result = ces.evaluate(ev)
    text = ces.render_operator(result, ev)
    assert result["rr"] == 3.14
    assert result["rr_at_current_price"] == 1.72
    assert text.startswith("🟡 CIO entry — already owned: add decision required: AXTI")
    assert "not a new position" in text
    assert "Catalyst: unavailable" in text
