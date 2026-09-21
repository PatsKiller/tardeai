"""Operator decisions 2026-09-15: the CIO owns entry state / BUY; operator and CIO are alerted; small caps labeled."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import cio_entry_state as ces  # noqa: E402
from lib.market_cap_label import cap_label  # noqa: E402
import operator_alert_policy_v2 as policy  # noqa: E402

TODAY = date(2026, 9, 15)


def ev(**kw):
    base = {"symbol": "ACHV", "price": 7.0, "quote_age_h": 0.2, "entry_low": 6.9, "entry_high": 7.15,
            "stop": 6.6, "target": 9.5, "atr": 0.40, "quality_state": "ADMITTED", "cio_action": "RESEARCH_MORE",
            "wash_blocked": False, "held": False, "earnings_date": "2026-11-05",
            "market_cap_label": cap_label(744), "catalyst": "Frazier Life Sciences buys new stake", "plan_source": "reentry_desk"}
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
    msg = ces.render_operator(r, ev(
        company="Esco Technologies Inc — Scientific & Technical Instruments.",
        sector="Technology", industry="Scientific & Technical Instruments"))
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
    msg = ces.render_operator(r, ev())          # ev() carries no company/sector/industry
    lines = msg.split("\n")
    assert all(ln.strip() not in {"", "·", "—"} for ln in lines), lines
    # the line after the header is the cap pill, not an empty identity slot
    assert lines[1].startswith("Small cap")


def test_identity_falls_back_to_sector_and_industry_without_a_company_name():
    r = ces.evaluate(ev(), today=TODAY)
    msg = ces.render_operator(r, ev(company=None, sector="Energy",
                                    industry="Oil & Gas Equipment & Services"))
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


def test_runner_contracts():
    src = (ROOT / "scripts" / "cio_entry_state_runner.py").read_text(encoding="utf-8")
    assert 'ap.add_argument("--apply"' in src and "conn.rollback()" in src
    assert "send_alerts(r, evidence" in src and src.index("if a.apply:") < src.index("send_alerts(r, evidence")
    assert 'CIOEventBus().emit("watch.new_signal"' in src
    assert "action_class <> 'entry'" in src  # the CIO's own entry rows never block themselves
    for forbidden in ("place_order", "submit_order", "/orders"):
        assert forbidden not in src


def test_digest_message_routes_like_single_alerts():
    rs = [ces.evaluate(ev(symbol="RTX"), today=TODAY), ces.evaluate(ev(symbol="NEE", price=7.25), today=TODAY)]
    text = ces.render_digest(rs)
    assert text.startswith("🟢 CIO entry — 2 more names ready or getting close")
    assert "BUY READY: RTX" in text and "Getting close: NEE" in text
    assert policy.route_event(policy.classify_legacy_message(text)).route_mode == policy.ROUTE_IMMEDIATE


def test_runner_digests_past_the_cap_and_marks_them_alerted():
    src = (ROOT / "scripts" / "cio_entry_state_runner.py").read_text(encoding="utf-8")
    assert "digest = pending[max(0, a.max_alerts):]" in src
    assert '"via": "digest"' in src and "ces.render_digest(digest)" in src


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
    out = r.alert_worthy([_near("ANET"), _near("GNL")], prior={}, done=set(),
                         starred={"ANET"})
    assert [x["symbol"] for x in out] == ["ANET"]


def test_buy_ready_always_pages_starred_or_not():
    """'Time to purchase' is exactly what the operator asked to keep."""
    r = _runner()
    out = r.alert_worthy([_ready("GNL"), _ready("ANET")], prior={}, done=set(),
                         starred={"ANET"})
    assert [x["symbol"] for x in out] == ["GNL", "ANET"]


def test_starring_is_case_insensitive():
    r = _runner()
    out = r.alert_worthy([_near("anet")], prior={}, done=set(), starred={"ANET"})
    assert [x["symbol"] for x in out] == ["anet"]


def test_the_older_downgrade_suppression_still_applies_to_a_starred_name():
    """A starred symbol must not reopen the 2026-09-15 defect: ENTRY_NEAR after
    a same-day BUY_READY is still not news."""
    r = _runner()
    out = r.alert_worthy([_near("ANET")], prior={"ANET": "BUY_READY"}, done=set(),
                         starred={"ANET"})
    assert out == []


def test_an_unreadable_star_store_fails_quiet_not_loud():
    """If the store cannot be read we page BUY_READY only -- never MORE alerts."""
    r = _runner()

    class Boom:
        def execute(self, *a, **k):
            raise RuntimeError("no such table")

    assert r.starred_symbols(Boom()) == set()
