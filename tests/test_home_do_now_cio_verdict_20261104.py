"""FQ-097 — a Do-now stop item renders the CIO verdict for that (symbol, account), and none of its own.

Operator report, 2026-11-04: the Home Do-now card said "SPCX is below its stop … Verify the broker executed it."
while the CIO's capital plan said TRIM for SPCX on the Schwab taxable account. The queue was authoring an
instruction ("verify the broker executed it") that the CIO had not given.

The rule these tests pin:
* a stop item always states the fact (price through the stop, no stop on record) — that is the risk snapshot's job;
* the only course of action it may show is the CIO's verdict, read from the same capital plan the CIO desk renders;
* when the CIO has no verdict, the item says so — it does not substitute one of its own;
* when the plan cannot be read, the item says that — "could not be read" is never "no verdict on record";
* no stop item, in any of those states, contains a directive the projection invented ("Verify the broker …").

Hermetic: in-memory payloads, no database, no network, no broker.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_capital_plan import build_capital_plan  # noqa: E402
from scripts.lib.data_broker import home_do_now as H  # noqa: E402

NOW = datetime(2026, 11, 4, 15, 25, tzinfo=timezone.utc)
ISO = NOW.isoformat()
PLAN_AS_OF = (NOW - timedelta(minutes=2)).isoformat()

DIRECTIVES = ("Verify the broker executed it", "Verify at the broker")


def _pos(sym, value=27_578.0, account="schwab_taxable", stop=10.0, dist=None, triggered=True, max_loss=500.0):
    return {"symbol": sym, "account": account, "market_value": value, "stop_price": stop,
            "distance_to_stop_pct": dist, "triggered": triggered, "max_loss_dollar": max_loss,
            "risk_excluded": False, "day_change_pct": -6.1}


def _risk(*positions):
    return {"computed_at": (NOW - timedelta(seconds=20)).isoformat(), "portfolio": {"heat_pct": 0.1},
            "positions": list(positions), "ok": True}


def _plan(rows, as_of=PLAN_AS_OF):
    return {"ok": True, "as_of": as_of, "computed_at": as_of, "position_decisions": list(rows)}


def _verdict(sym, account, stance, why="Advisory TRIM — SPCX"):
    return {"symbol": sym, "account": account, "accounts": [account], "cio_stance": stance, "why_now": why,
            "as_of": PLAN_AS_OF}


def _build(risk, plan=None, inbox=None):
    probes = {"risk": lambda: risk, "needs_action": lambda: {"items": [], "total": 0, "as_of": ISO,
                                                             "all_sources_answered": True},
              "inbox": lambda: inbox or {"items": [], "total_count": 0},
              "proposals": lambda: {"pending": 0}, "deploy": lambda: {"events": []}}
    if plan is not None:
        probes["cio"] = (lambda: plan) if not isinstance(plan, BaseException) else _raise(plan)
    return H.build(probes, now=NOW)


def _raise(exc):
    def _fn():
        raise exc
    return _fn


def _item(out, key):
    return next(i for i in out["items"] if i["id"] == key)


def _why(out, key):
    return _item(out, key)["why"]


# ── 1. the verdict is the CIO's, for that account ────────────────────────────────────────────────────────────────


def test_triggered_stop_renders_the_cio_verdict_for_that_symbol_and_account():
    out = _build(_risk(_pos("SPCX")), _plan([_verdict("SPCX", "schwab_taxable", "TRIM")]))
    why = _why(out, "stop:SPCX")
    assert "CIO verdict" in why
    assert "TRIM" in why
    assert "Schwab Individual" in why, why          # account by NAME, never a number
    assert "Price is through the stop on record" in why  # the fact survives


def test_the_projection_adds_no_directive_of_its_own():
    for plan in (_plan([_verdict("SPCX", "schwab_taxable", "TRIM")]), _plan([]), None):
        why = _why(_build(_risk(_pos("SPCX")), plan), "stop:SPCX")
        for d in DIRECTIVES:
            assert d not in why, (d, why)


def test_two_accounts_each_get_their_own_verdict():
    risk = _risk(_pos("SPCX", account="schwab_taxable"), _pos("SPCX", value=5_000.0, account="moomoo"))
    plan = _plan([_verdict("SPCX", "schwab_taxable", "TRIM"), _verdict("SPCX", "moomoo", "HOLD")])
    why = _why(_build(risk, plan), "stop:SPCX")
    assert "TRIM" in why and "HOLD" in why, why


# ── 2. no verdict, no invention ──────────────────────────────────────────────────────────────────────────────────


def test_no_cio_verdict_is_stated_as_absent_not_replaced():
    why = _why(_build(_risk(_pos("SPCX")), _plan([])), "stop:SPCX")
    assert "no per-account CIO verdict on record" in why
    for stance in ("TRIM", "HOLD", "BUY", "SELL", "EXIT"):
        assert stance not in why, (stance, why)


def test_unreadable_plan_is_said_differently_from_a_missing_verdict():
    why = _why(_build(_risk(_pos("SPCX")), H.SourceUnavailable("plan unreadable")), "stop:SPCX")
    assert "could not be read" in why
    assert "no per-account CIO verdict" not in why


def test_a_malformed_plan_is_unavailable_not_an_empty_verdict_list():
    out = _build(_risk(_pos("SPCX")), {"ok": True, "as_of": PLAN_AS_OF, "position_decisions": "nope"})
    assert out["sources"]["cio"]["status"] == "UNAVAILABLE"
    assert "could not be read" in _why(out, "stop:SPCX")


def test_a_plan_that_raises_is_an_item_and_the_stop_still_renders():
    out = _build(_risk(_pos("SPCX")), RuntimeError("boom"))
    assert out["all_sources_answered"] is False
    assert "Price is through the stop on record" in _why(out, "stop:SPCX")


# ── 3. every stop shape, not only the triggered one ─────────────────────────────────────────────────────────────


def test_near_stop_and_no_stop_items_carry_the_verdict_too():
    near = _build(_risk(_pos("AAA", stop=10.0, dist=1.2, triggered=False)), _plan([_verdict("AAA", "schwab_taxable", "HOLD")]))
    assert "CIO verdict" in _why(near, "stop:AAA") and "HOLD" in _why(near, "stop:AAA")
    bare = _build(_risk(_pos("BBB", value=50_000.0, stop=None, triggered=False)), _plan([_verdict("BBB", "schwab_taxable", "TRIM")]))
    assert "CIO verdict" in _why(bare, "stop:BBB") and "TRIM" in _why(bare, "stop:BBB")


def test_the_inbox_stop_alert_carries_the_verdict_and_no_directive():
    inbox = {"total_count": 1, "items": [{"type": "stop", "symbol": "SPCX", "at": ISO,
                                          "detail": "stop breached", "account": "schwab_taxable"}]}
    why = _why(_build(_risk(), _plan([_verdict("SPCX", "schwab_taxable", "TRIM")]), inbox), "stop:SPCX")
    assert "CIO verdict" in why and "TRIM" in why
    assert "Verify at the broker" not in why


# ── 4. the source says where its clock came from ────────────────────────────────────────────────────────────────


def test_the_cio_source_uses_the_plans_own_as_of():
    out = _build(_risk(_pos("SPCX")), _plan([], as_of=PLAN_AS_OF))
    src = out["sources"]["cio"]
    assert src["status"] == "OK"
    assert src["as_of"] == PLAN_AS_OF
    assert src["as_of_basis"] == "capital_plan.as_of"


# ── cx-openai-2 re-review at 89d938197: three semantic defects ─────────────────────────────────────────────────


def test_the_projection_never_authors_an_instruction():
    """The surface renders; it does not tell the operator what to do. "Set stops" was ours, not the CIO's."""
    out = _build(_risk(_pos("SPCX", stop=None, triggered=False, value=50_000.0)), _plan([]))
    labels = [i["action"]["label"] for i in out["items"]]
    assert labels, "no items built"
    for label in labels:
        assert "set stops" not in label.lower(), label


def test_an_accountless_verdict_is_never_presented_as_an_accounts_verdict():
    """An unscoped TRIM must not become "Demo IRA: TRIM" — that is the cross-account bleed the operator ruled out."""
    plan = _plan([{"symbol": "SPCX", "cio_stance": "TRIM", "why_now": "Advisory TRIM", "as_of": PLAN_AS_OF}])
    why = _why(_build(_risk(_pos("SPCX", account="schwab_taxable")), plan), "stop:SPCX")
    assert "Schwab Individual: TRIM" not in why, why
    assert "no per-account CIO verdict on record" in why, why
    assert "aggregate TRIM" in why, why          # named as the plan's aggregate, not as this account's
    assert "not attributable to an account" in why, why


def test_a_multi_account_verdict_is_an_aggregate_not_a_clone():
    risk = _risk(_pos("SPCX", account="schwab_taxable"), _pos("SPCX", value=5_000.0, account="moomoo"))
    plan = _plan([{"symbol": "SPCX", "accounts": ["schwab_taxable", "moomoo"], "cio_stance": "TRIM"}])
    why = _why(_build(risk, plan), "stop:SPCX")
    assert "Schwab Individual: TRIM" not in why and "Moomoo: TRIM" not in why, why
    assert "aggregate TRIM" in why, why


def test_old_decision_evidence_is_not_stamped_with_the_plans_clock():
    """The clock the REAL producer carries survives aggregation, and old evidence is marked old.

    Driven through ``build_capital_plan`` -> ``build_position_decisions`` -> ``aggregate_position_decisions``.
    The aggregated row carries ``generated_at`` only (it does not preserve ``decision_generated_at``), so this pins
    the producer's actual shape rather than a hand-built row the plan cannot emit.
    """
    old = (NOW - timedelta(days=2)).isoformat()
    plan = build_capital_plan(
        portfolio_value=100_000.0,
        cash_total=10_000.0,
        positions=[{"symbol": "SPCX", "account": "schwab_taxable",
                    "market_value": 27_578.0, "updated_at": old}],
        now=NOW,
    )
    row = plan["position_decisions"][0]
    # The producer's real row: the evidence clock is `generated_at`; the pre-aggregation key is gone.
    assert row.get("generated_at") == old, row
    assert row.get("decision_generated_at") is None, row
    index = H.cio_verdict_index(plan)
    assert index["by_account"][("SPCX", "schwab_taxable")]["as_of"] == old  # non-null on the real row
    out = _build(_risk(_pos("SPCX")), plan)
    why = _why(out, "stop:SPCX")
    assert old in why, why
    assert plan["as_of"] not in why, why                 # never the plan's own build clock
    assert out["sources"]["cio"]["evidence_as_of"] == old
    assert out["sources"]["cio"]["evidence_stale"] is True
    assert out["sources"]["cio"]["stale"] is True


def test_a_verdict_with_no_clock_says_so_rather_than_borrowing_one():
    plan = _plan([{"symbol": "SPCX", "account": "schwab_taxable", "cio_stance": "TRIM"}])
    why = _why(_build(_risk(_pos("SPCX")), plan), "stop:SPCX")
    assert "TRIM" in why and PLAN_AS_OF not in why, why
    assert "decision time not recorded" in why, why
