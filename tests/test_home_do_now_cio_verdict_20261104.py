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


# ── cx-openai-3 BLOCK at 3d118f247: F1 per-account opinions, F2 aggregate clocks, F3 instant ordering ─────────────


def _real_plan(accounts=("schwab_taxable",), stamp=None):
    """The REAL producer: build_capital_plan -> build_position_decisions -> aggregate_position_decisions."""
    stamp = stamp or (NOW - timedelta(days=2)).isoformat()
    return build_capital_plan(
        portfolio_value=100_000.0,
        cash_total=10_000.0,
        positions=[{"symbol": "SYN", "account": a,
                    "market_value": 27_000.0 if i == 0 else 4_000.0,
                    "updated_at": stamp} for i, a in enumerate(accounts)],
        now=NOW,
    )


def test_f1_two_real_accounts_each_get_their_own_opinion_not_the_symbol_aggregate():
    """F1: consume the producer's `per_account` opinions instead of collapsing them into one aggregate.

    Before the repair a two-account row lived only in `aggregate`, so the stop item said there was no per-account
    verdict while the plan's own `per_account` list carried one for each account. The real producer's single
    aggregate row has no per-account stances of its own to clone: each opinion comes from `per_account` untouched.
    """
    plan = _real_plan(("schwab_taxable", "moomoo"))
    row = plan["position_decisions"][0]
    assert [o["account"] for o in row["per_account"]] == ["schwab_taxable", "moomoo"], row["per_account"]
    assert row["accounts"] == ["schwab_taxable", "moomoo"], row["accounts"]
    index = H.cio_verdict_index(plan)
    assert set(index["by_account"]) == {("SYN", "schwab_taxable"), ("SYN", "moomoo")}, index
    assert index["by_account"][("SYN", "schwab_taxable")]["stance"] == row["per_account"][0]["cio_stance"]
    assert index["by_account"][("SYN", "moomoo")]["stance"] == row["per_account"][1]["cio_stance"]
    risk = _risk(_pos("SYN", account="schwab_taxable"), _pos("SYN", value=4_000.0, account="moomoo"))
    why = _why(_build(risk, plan), "stop:SYN")
    assert "Schwab Individual: HOLD" in why, why
    assert "Moomoo: HOLD" in why, why
    assert "no per-account CIO verdict on record" not in why, why


def test_f2_old_real_aggregate_clock_is_aged_not_fresh():
    """F2: the aggregate sentence is displayed evidence, so its decision clock is aged like any other."""
    old = (NOW - timedelta(days=2)).isoformat()
    plan = _real_plan(("schwab_taxable", "moomoo"), old)
    assert plan["position_decisions"][0]["generated_at"] == old
    src = _build(_risk(_pos("SYN")), plan)["sources"]["cio"]
    assert src["aggregate_verdicts"] == 1, src
    assert src["evidence_as_of"] == old, src
    assert src["evidence_stale"] is True, src
    assert src["stale"] is True, src
    why = _why(_build(_risk(_pos("SYN")), plan), "stop:SYN")
    assert old in why and "not attributable to an account" in why, why


def test_f2_future_real_aggregate_clock_is_not_fresh():
    """F2: a future aggregate clock is explicit, not folded into 'fresh'."""
    future = (NOW + timedelta(days=2)).isoformat()
    plan = _real_plan(("schwab_taxable", "moomoo"), future)
    assert plan["position_decisions"][0]["generated_at"] == future
    src = _build(_risk(_pos("SYN")), plan)["sources"]["cio"]
    assert src["aggregate_verdicts"] == 1, src
    assert src["evidence_as_of_future"] is True, src
    assert src["stale"] is True, src
    assert src.get("evidence_stale") is not True, src


def test_f2_fresh_clocks_on_every_displayed_verdict_are_not_marked_stale():
    """F2 positive control: fresh clocks on every displayed verdict are neither stale nor missing.

    (cx2 at 8802d4da9: the earlier positive control used clockless member opinions under a fresh aggregate clock;
    that state is exactly the one the missing-clock rule must flag, so the control now gives every displayed
    verdict its own fresh clock.)
    """
    fresh = (NOW - timedelta(seconds=20)).isoformat()
    plan = _real_plan_with_member_clocks({"schwab_taxable": fresh, "moomoo": fresh})
    src = _build(_risk(_pos("SYN")), plan)["sources"]["cio"]
    assert src["evidence_as_of"] == fresh, src
    assert src.get("evidence_stale") is not True, src
    assert src.get("evidence_as_of_future") is not True, src
    assert src.get("evidence_as_of_missing") is not True, src


def test_f2_unparseable_evidence_clock_is_explicit_not_fresh():
    plan = _plan([{"symbol": "SPCX", "account": "schwab_taxable", "cio_stance": "TRIM",
                   "as_of": "not-a-clock"}])
    src = _build(_risk(_pos("SPCX")), plan)["sources"]["cio"]
    assert src["evidence_as_of_unparseable"] is True, src
    assert src["stale"] is True, src
    assert "evidence_as_of" not in src, src
    assert src.get("evidence_as_of_missing") is not True, src


def test_f2_missing_evidence_clock_is_explicit_not_fresh():
    plan = _plan([{"symbol": "SPCX", "account": "schwab_taxable", "cio_stance": "TRIM"}])
    src = _build(_risk(_pos("SPCX")), plan)["sources"]["cio"]
    assert src["evidence_as_of_missing"] is True, src
    assert src["stale"] is True, src


def test_f3_oldest_evidence_clock_is_ordered_by_instant_not_iso_text():
    """F3: 10:24-05:00 is 15:24Z (1 min old); 14:00Z is 85 min old. ISO text order picks the wrong one."""
    plan = build_capital_plan(
        portfolio_value=100_000.0,
        cash_total=10_000.0,
        positions=[
            {"symbol": "SYN", "account": "schwab_taxable", "market_value": 27_000.0,
             "updated_at": "2026-11-04T14:00:00+00:00"},
            {"symbol": "ZZZ", "account": "moomoo", "market_value": 4_000.0,
             "updated_at": "2026-11-04T10:24:00-05:00"},
        ],
        now=NOW,
    )
    assert {r["generated_at"] for r in plan["position_decisions"]} == {
        "2026-11-04T14:00:00+00:00", "2026-11-04T10:24:00-05:00"}
    src = _build(_risk(_pos("SYN")), plan)["sources"]["cio"]
    # The oldest INSTANT is 14:00Z (85 minutes old), normalised before it is reported.
    assert src["evidence_as_of"] == "2026-11-04T14:00:00+00:00", src
    assert src["evidence_stale"] is True, src


# ── cx-openai-3 clock-provenance note (20261105T174539Z): the producer's per_account entries carry no ────────────
# member clock, so the consumer must read a member's own clock when one exists and say "unknown" when it does not,
# never stamping the aggregate row's clock onto a member as if it had been independently measured.


def _real_plan_with_member_clocks(clocks):
    """The REAL producer, with an injected measure clock on the named per-account opinions.

    `aggregate_position_decisions` emits `per_account` opinions with no clock of their own (cx-openai-3 note
    2026-11-05). Building through the real producer and then giving selected opinions a clock exercises the
    consumer's member-clock path without inventing a row shape the producer cannot emit: the aggregate row keeps
    its own distinct `generated_at`, as it does in production.
    """
    plan = _real_plan(("schwab_taxable", "moomoo"), (NOW - timedelta(seconds=20)).isoformat())
    for o in plan["position_decisions"][0]["per_account"]:
        if o.get("account") in clocks:
            o["generated_at"] = clocks[o["account"]]
    return plan


def test_provenance_different_account_clocks_stay_separate_and_the_oldest_drives_staleness():
    """Each opinion keeps ITS OWN clock; the oldest member clock, not the aggregate's, is the evidence clock."""
    older, newer = "2026-11-02T15:25:00+00:00", "2026-11-04T14:00:00+00:00"
    plan = _real_plan_with_member_clocks({"schwab_taxable": older, "moomoo": newer})
    row = plan["position_decisions"][0]
    assert row["generated_at"] not in (older, newer), row  # the aggregate clock is a third, distinct clock
    index = H.cio_verdict_index(plan)
    assert index["by_account"][("SYN", "schwab_taxable")]["as_of"] == older, index
    assert index["by_account"][("SYN", "moomoo")]["as_of"] == newer, index
    risk = _risk(_pos("SYN", account="schwab_taxable"), _pos("SYN", value=4_000.0, account="moomoo"))
    out = _build(risk, plan)
    src = out["sources"]["cio"]
    assert src["evidence_as_of"] == older, src  # the OLDER member clock drives the stale determination
    assert src["evidence_stale"] is True, src
    why = _why(out, "stop:SYN")
    assert older in why, why
    assert "Schwab Individual: HOLD" in why and "Moomoo: HOLD" in why, why


def test_provenance_missing_member_clock_is_unknown_not_the_aggregate_clock():
    """A member opinion with no clock says "decision time not recorded"; the aggregate clock does not leak onto it."""
    plan = _real_plan_with_member_clocks({"moomoo": "2026-11-04T14:00:00+00:00"})
    row = plan["position_decisions"][0]
    agg_clock = row["generated_at"]
    assert agg_clock
    index = H.cio_verdict_index(plan)
    assert index["by_account"][("SYN", "schwab_taxable")]["as_of"] is None, index  # unknown, not borrowed
    assert index["by_account"][("SYN", "schwab_taxable")]["as_of"] != agg_clock
    assert index["by_account"][("SYN", "moomoo")]["as_of"] == "2026-11-04T14:00:00+00:00", index
    out = _build(_risk(_pos("SYN", account="schwab_taxable")), plan)
    why = _why(out, "stop:SYN")
    assert "Schwab Individual: HOLD" in why, why
    assert "CIO verdict (decision time not recorded)" in why, why
    assert f"CIO verdict ({agg_clock})" not in why, why  # the aggregate clock is NOT this member's clock
    assert f"aggregate HOLD ({agg_clock})" in why, why   # still named, as the aggregate only


# ── codex-cloud BLOCK at 8802d4da9: the do-now GET is read-only, and a fresh aggregate clock never hides a ────────
# clockless member opinion.


def test_cx2_fresh_aggregate_clock_does_not_hide_a_member_with_no_clock():
    """cx2 (codex-cloud at 8802d4da9): a valid aggregate clock must not report an unknown member as fresh.

    The REAL producer's aggregate row carries ``generated_at``, but its per-account opinions carry no clock. The
    stop item displays those opinions as "decision time not recorded", so the CIO source must say the same thing:
    its oldest displayed evidence is unknown even though a sibling clock parses. Before the repair the source
    reported ``stale: false`` and no ``evidence_as_of_missing``.
    """
    fresh = (NOW - timedelta(seconds=20)).isoformat()
    plan = _real_plan(("schwab_taxable", "moomoo"), fresh)
    row = plan["position_decisions"][0]
    assert row["generated_at"] == fresh
    assert all(not o.get("generated_at") for o in row["per_account"]), row["per_account"]
    out = _build(_risk(_pos("SYN", account="schwab_taxable")), plan)
    src = out["sources"]["cio"]
    assert src["verdicts"] == 2, src                   # both member opinions are displayed ...
    assert src["aggregate_verdicts"] == 1, src
    assert src["evidence_as_of"] == fresh, src         # ... the only known clock is still named ...
    assert src["evidence_as_of_missing"] is True, src  # ... and the unknown member clocks are never called fresh
    assert src["stale"] is True, src
    why = _why(out, "stop:SYN")
    assert "decision time not recorded" in why, why


def test_cx1_a_cache_miss_do_now_request_never_writes_the_decision_journal(tmp_path, monkeypatch):
    """cx1 (codex-cloud at 8802d4da9): GET /api/v2/home/do-now must not write durable state.

    The recording capital-plan build appends every unseen decision id to the authoritative decision journal and
    fsyncs it (AGENTS.md §28.9; §28.11 forbids new side-effecting GET exceptions). The Do-now queue only displays
    the plan, so its cache-miss probe builds it WITHOUT recording: the journal is absent (or unchanged) after the
    request. Reverting the probe to the recording handler makes this test fail.
    """
    import api_v2
    import lib.data_broker.home_do_now as HD_API
    import lib.data_broker.risk_snapshot as RS_API
    import lib.data_broker.watch_domains as WD_API
    import lib.needs_action as NA_API
    import scripts.lib.cio_capital_plan as CP
    import scripts.lib.cio_investment_product as IP
    import scripts.lib.cio_opportunity_queue as OQ

    journal = tmp_path / "cio_capital_plan_decisions.jsonl"
    monkeypatch.setenv("CIO_CAPITAL_PLAN_DECISIONS_JSONL", str(journal))
    plan = {"position_decisions": [{
        "symbol": "SYN", "account": "schwab_taxable", "cio_stance": "HOLD",
        "decision_id": "unseen-do-now-decision", "generated_at": PLAN_AS_OF}]}
    monkeypatch.setattr(CP, "build_capital_plan_from_sources", lambda **kw: dict(plan))
    monkeypatch.setattr(OQ, "build_queue_from_executor", lambda query: {})
    monkeypatch.setattr(IP, "merge_queue_with_stored_verdicts", lambda queue, **kw: queue)
    monkeypatch.setattr(api_v2, "_load_json", lambda path: {})
    monkeypatch.setattr(api_v2, "_redeploy_opportunity_set", lambda: {})
    monkeypatch.setattr(api_v2, "_cio_sector_opportunities", lambda: {"opportunities": []})
    monkeypatch.setattr(api_v2, "_desk_thesis_head", lambda: {})
    monkeypatch.setattr(api_v2, "_risk_posture", lambda desk=None: {})
    monkeypatch.setattr(api_v2, "_ratified_investment_policy", lambda: None)
    monkeypatch.setattr(api_v2, "_needs_action", lambda: {"items": [], "total": 0, "as_of": ISO,
                                                          "all_sources_answered": True})
    monkeypatch.setattr(api_v2, "_inbox", lambda: {"items": [], "total_count": 0})
    monkeypatch.setattr(api_v2, "_deploy_events", lambda *a, **k: {"events": []})
    monkeypatch.setattr(RS_API, "get_risk_snapshot", lambda **kw: {"computed_at": ISO, "positions": [], "ok": True})
    monkeypatch.setattr(WD_API, "held_positions", lambda surface=None: {"positions": [], "as_of": ISO,
                                                                        "source": "test", "symbols": []})
    monkeypatch.setattr(NA_API, "probe_desk_truth", lambda: {})
    monkeypatch.setattr(HD_API, "probe_pending_proposals", lambda query: {"pending": 0})
    monkeypatch.setitem(api_v2._HOME_DO_NOW_CACHE, "v", None)  # force a cache miss

    out = api_v2._home_do_now()

    assert out["sources"]["cio"]["status"] == "OK", out["sources"]["cio"]
    assert not journal.exists(), journal.read_text(encoding="utf-8")

