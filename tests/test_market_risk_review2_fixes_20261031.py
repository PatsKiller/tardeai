"""Round-2 review of the Market Risk Engine (#2383) — every failing probe input is a regression test here.

B3 curation allow-list template; B5d crash-safe outbox; N1 account-weighted budget uplift; N2 GREEN guard and
de-escalation path; N3 reopen on re-entry; N4 ATR on bars without OHLC; M2 torn ledger quarantine; M3 names only;
M4 pre-gate stance in versions; session_of holidays; N5 FRED last_seen_at; N6 ACK principal and NONE projection.
Hermetic: no DB, no network, no sends (transport stubbed). Probes: ~/agent_scratch/review-2383/probes/.
"""

from __future__ import annotations

import json
import sys
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.lib.market_risk import alerts, curation, escalation as esc, registry, scoring  # noqa: E402
from scripts.lib.market_risk import contract as c  # noqa: E402
from scripts.lib.market_risk.policy import load_policy  # noqa: E402
from scripts.lib import market_risk_projection as proj  # noqa: E402

ET = ZoneInfo("America/New_York")
POLICY = load_policy()

# ── B3: curation allow-list template ─────────────────────────────────────────────────────────────────────────────
CARD = (
    "🟡 MARKET RISK YELLOW 50/100 · 2 of 9 categories confirm\nWhy: Options flow and technicals are stressed.\n"
    "options_flow +32 · Options flow: QQQ P/C OI 3.97 (3.85x median) · 10-30 17:35 ET\nEvaluated 10-31 10:36 ET. Advisory."
)
DOC = {
    "tier": "YELLOW",
    "score": 50,
    "confirming": 2,
    "as_of": "2026-10-31T14:36:00Z",
    "contributors": [
        {"category": "options_flow", "points": 32, "headline": "Options flow: QQQ P/C OI 3.97 (3.85x median)"}
    ],
}
# p_cur2.py: 71 paraphrases; the 2 legitimate descriptive sentences are in ALLOWED below.
P_CUR2 = [
    "Reduce exposure to tech.",
    "Pare back the AI names.",
    "Sell into strength.",
    "Buy the dip.",
    "Add on weakness.",
    "Size down.",
    "Hedge with SQQQ.",
    "Sell ５００ shares.",
    "Five hundred shares of NVDA go.",
    "Trim 5️⃣0️⃣0️⃣ shares",
    "Lock in gains on the AI basket.",
    "Go defensive now.",
    "Load up on SQQQ.",
    "Tighten your stops.",
    "Trail your stops.",
    "Tighten stops on NVDA.",
    "Accumulate QQQ.",
    "Back up the truck on QQQ.",
    "Take chips off the table.",
    "Book gains in semis.",
    "Lower your NVDA position.",
    "Raise your cash buffer.",
    "Move into Treasuries.",
    "Switch to bonds.",
    "Park money in T-bills.",
    "Ring the register on NVDA.",
    "Stay underweight semis.",
    "Go underweight tech.",
    "Close NVDA.",
    "Close out the NVDA position.",
    "Bail on semis.",
    "Run for the exits.",
    "QQQ could fall twenty percent from here.",
    "A crash of fifty percent is possible.",
    "VIX could hit 𝟒𝟓.",
    "QQQ could fall 2⁰ percent.",
    "Risk could reach 3.9 next week.",
    "Risk is 50; QQQ P/C 3.97 implies 397 basis points.",
    "Put/call 3.97 means about 4 times normal.",
    "QQQ may drop to 3,97.",
    "Lessen exposure.",
    "Diminish holdings.",
    "Protect gains with a collar on QQQ.",
    "Buy protection.",
    "Get long volatility.",
    "Short QQQ.",
    "Stand aside.",
    "Wait before deploying fresh capital.",
    "Do not deploy new money.",
    "Keep powder dry.",
    "Sit on your hands.",
    "Don’t chase.",
    "It’s time to lighten up.",
    "Be a seller.",
    "Sellers should act.",
    "Selling makes sense.",
    "Buying here is risky.",
    "Purchase SQQQ.",
    "Unwind NVDA.",
    "Halve NVDA.",
    "Quarter the NVDA stake.",
    "Dial down risk.",
    "Turn down risk.",
    "Tone down exposure.",
    "Scale back.",
    "Pull back on new buys.",
    "Ｓｅｌｌ NVDA.",
    "S​ell NVDA.",
    "Ѕell NVDA.",
]
# p_cur3.py: invented numbers the old trivial-number exemption let through
P_CUR3 = [
    "QQQ could fall 25 percent this week.",
    "The S&P could drop to 2050.",
    "Expect a 30 point drop in QQQ.",
    "Risk 50 could become 51.6 tomorrow.",
    "QQQ could fall 12 percent, VIX to 31.",
    "Risk is 50, 3.97 P/C means 52 by Monday.",
    "NVDA could lose 5.0 percent.",
    "NVDA could lose 5.0%.",
]
# Template mode: what passes is a phrase CHOICE rendered from the card's own names and figures, never model prose.
ALLOWED = ['{"phrases": [{"id": "lead"}]}', '{"phrases": [{"id": "score"}, {"id": "detail"}]}']


def _cfg():
    return dict(curation.load_config(), skip_tiers=["ORANGE", "RED"])  # exercise the template on YELLOW


@pytest.mark.parametrize("answer", P_CUR2 + P_CUR3)
def test_b3_template_rejects_every_probe_paraphrase(answer):
    r = curation.curate(CARD, DOC, call_model=lambda p, t, a=answer: a, cfg=_cfg())
    assert r["curated"] is False and r["text"] == CARD, (answer, r["reason"])


@pytest.mark.parametrize("answer", ALLOWED)
def test_b3_template_keeps_descriptive_sentences_built_from_displayed_figures(answer):
    r = curation.curate(CARD, DOC, call_model=lambda p, t, a=answer: a, cfg=_cfg())
    assert r["curated"] is True, r["reason"]


def test_b3_format_characters_are_stripped_and_confusables_refused():
    assert curation.normalize("S​ell") == "Sell"
    assert curation.non_ascii_chars("Ѕell NVDA") == ["Ѕ"]


def test_b3_no_trivial_number_exemption():
    assert curation.ungrounded_numbers("QQQ could fall 25 percent", "", DOC) == ["25"]
    assert curation.ungrounded_numbers("drop to 2050", "", DOC) == ["2050"]
    assert curation.ungrounded_numbers("risk 50, 32 points, 3.97", "", DOC) == []


def test_b3_shipped_default_skips_every_tier_until_reviewed():
    cfg = curation.load_config()
    for tier in ("RED", "ORANGE", "YELLOW", "BLUE", "GREEN"):
        r = curation.curate(CARD, dict(DOC, tier=tier), call_model=lambda p, t: "Options flow is elevated.", cfg=cfg)
        assert r["curated"] is False and "never curated" in r["reason"]


# ── B5d: crash-safe outbox (p_crash.py, CRASH_I=1 and 3) ─────────────────────────────────────────────────────────
def _evaluator():
    import importlib.util

    spec = importlib.util.spec_from_file_location("mre_eval_r2", ROOT / "scripts" / "market_risk_evaluate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mk(now, tier):
    st = {
        "RED": {
            k: ("STRESS", 100)
            for k in ("options_flow", "breadth", "technical", "volatility", "extended_hours", "cross_asset")
        },
        "YELLOW": {"options_flow": ("STRESS", 85), "technical": ("STRESS", 70)},
    }[tier]
    return [
        c.CategoryObservation(
            category=k,
            state=st.get(k, ("CALM", 5))[0],
            score=st.get(k, ("CALM", 5))[1],
            observed_at=now.isoformat(),
            headline=k,
        )
        for k in c.CATEGORIES
    ]


class _Crash(BaseException):
    pass


def _crash_run(tmp_path, monkeypatch, crash_at, crash_i):
    sent = []
    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = lambda msg, **kw: sent.append((kw.get("priority"), msg.splitlines()[0])) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    ev = _evaluator()
    d = tmp_path / f"run-{crash_at}-{crash_i}"
    d.mkdir()
    t0 = datetime(2026, 11, 3, 10, 0, tzinfo=ET)
    prior = None
    for i in range(0, 16):
        t = t0 + timedelta(minutes=15 * i)
        tier = "YELLOW" if i == 0 else "RED"
        obs = _mk(t, tier)

        def fake_eval(now_, reader, policy, prior_, portfolio=None, obs=obs):
            from scripts.lib.market_risk import explain

            a = scoring.compose(obs, policy, prior=prior_, now=now_)
            return explain.explain(scoring.apply_uplift(a, None, policy), policy)

        monkeypatch.setattr(ev, "evaluate", fake_eval)
        persisted = {}
        originals = {"observe": esc.observe, "claim": alerts.claim, "settle": alerts.settle, "record": esc.record_send}
        if i == crash_i:
            name, when = crash_at.split(":")
            mod, attr = {
                "observe": (esc, "observe"),
                "claim": (alerts, "claim"),
                "settle": (alerts, "settle"),
                "record": (esc, "record_send"),
            }[name]
            fn = originals[name]

            def wrapped(*a, _fn=fn, _when=when, **k):
                if _when == "before":
                    raise _Crash(name)
                r = _fn(*a, **k)
                raise _Crash(name)

            monkeypatch.setattr(mod, attr, wrapped)
        try:
            ev.run_cycle(
                t,
                None,
                POLICY,
                prior,
                apply=True,
                episodes_path=d / "ep.json",
                ledger_path=d / "keys.json",
                on_assessed=lambda doc: persisted.update(doc=json.loads(json.dumps(doc, default=str))),
                call_model=lambda p, to: "",
            )
        except _Crash:
            pass
        finally:
            monkeypatch.setattr(esc, "observe", originals["observe"])
            monkeypatch.setattr(alerts, "claim", originals["claim"])
            monkeypatch.setattr(alerts, "settle", originals["settle"])
            monkeypatch.setattr(esc, "record_send", originals["record"])
        prior = persisted.get("doc", prior)
    ep = esc.open_episode(esc.load(d / "ep.json"))
    return sent, ep, esc.stalled(now=t, policy=POLICY, path=d / "ep.json")


@pytest.mark.parametrize("crash_i", [1, 3])
@pytest.mark.parametrize(
    "crash_at", ["observe:before", "observe:after", "claim:after", "settle:after", "record:before", "record:after"]
)
def test_b5d_no_crash_point_loses_or_wedges_a_card(tmp_path, monkeypatch, crash_at, crash_i):
    base, ep0, _ = _crash_run(tmp_path, monkeypatch, "observe:before", 99)  # no crash
    sent, ep, stalled = _crash_run(tmp_path, monkeypatch, crash_at, crash_i)
    reds = [s for s in sent if "RED" in s[1]]
    assert reds, (crash_at, sent)  # the RED card is never lost
    assert ep["repeats"] == ep0["repeats"] and stalled is None, (crash_at, ep["repeats"], ep0["repeats"])
    assert len(sent) == len(base), (crash_at, len(sent), len(base))


def test_b5d_crash_between_send_and_settle_resends_at_most_once(tmp_path, monkeypatch):
    base, ep0, _ = _crash_run(tmp_path, monkeypatch, "observe:before", 99)
    sent, ep, stalled = _crash_run(tmp_path, monkeypatch, "settle:before", 3)
    assert len(sent) <= len(base) + 1 and ep["repeats"] == ep0["repeats"] and stalled is None


def test_b5d_record_send_is_idempotent_on_the_key(tmp_path):
    p = tmp_path / "ep.json"
    now = datetime(2026, 11, 3, 10, 0, tzinfo=ET)
    esc.observe({"tier": "RED", "observations": []}, now=now, policy=POLICY, path=p)
    ep_id = esc.open_episode(esc.load(p))["id"]
    for _ in range(3):
        esc.record_send(ep_id, now=now, kind="red", ok=True, path=p, key="market_risk:repeat:x:1")
    assert esc.open_episode(esc.load(p))["repeats"] == 1


def test_b5d_failed_send_does_not_count_as_a_send_for_stall(tmp_path):
    p = tmp_path / "ep.json"
    t = datetime(2026, 11, 3, 10, 0, tzinfo=ET)
    esc.observe({"tier": "RED", "observations": []}, now=t, policy=POLICY, path=p)
    ep_id = esc.open_episode(esc.load(p))["id"]
    esc.record_send(ep_id, now=t + timedelta(minutes=70), kind="red", ok=False, path=p)
    assert esc.stalled(now=t + timedelta(minutes=80), policy=POLICY, path=p) is not None


# ── N1: account breaches weighted by book share ──────────────────────────────────────────────────────────────────
def _assessment(tier="YELLOW"):
    a = scoring.compose(
        _mk(datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc), "YELLOW"),
        POLICY,
        now=datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc),
    )
    a.market_tier = a.tier = tier
    return a


def test_n1_small_single_name_account_never_lifts_the_tier():
    port = c.PortfolioContext(
        vulnerability=60.0,
        budget_breaches=(
            {"budget": "single_sector_pct", "ratio": 3.21, "scope": "acct-a", "book_share": 0.05},
            {"budget": "growth_style_pct", "ratio": 1.93, "scope": "acct-a", "book_share": 0.05},
            {"budget": "unprotected_pct", "ratio": 4.45, "scope": "acct-b", "book_share": 0.04},
        ),
    )
    a = scoring.apply_uplift(_assessment(), port, POLICY)
    assert a.tier == "YELLOW" and a.uplift is None


def test_n1_whole_book_breach_lifts_and_card_names_only():
    port = c.PortfolioContext(
        vulnerability=60.0, budget_breaches=({"budget": "growth_style_pct", "ratio": 1.5, "scope": "book"},)
    )
    a = scoring.apply_uplift(_assessment(), port, POLICY)
    assert a.tier == "ORANGE"
    assert "1.5" not in a.uplift["note"] and "growth_style_pct" in a.uplift["note"]  # M3: names only


def test_n1_budget_uplift_needs_minimum_vulnerability():
    port = c.PortfolioContext(
        vulnerability=20.0, budget_breaches=({"budget": "growth_style_pct", "ratio": 1.5, "scope": "book"},)
    )
    assert scoring.apply_uplift(_assessment(), port, POLICY).tier == "YELLOW"


# ── N2: GREEN guard and the de-escalation path ───────────────────────────────────────────────────────────────────
def _green_obs(now, unknown=0, stress_age_h=None):
    out = []
    for i, k in enumerate(c.CATEGORIES):
        if i < unknown:
            out.append(c.unknown(k, now, "x"))
        elif k in ("volatility", "macro_credit", "breadth"):
            out.append(
                c.CategoryObservation(category=k, state="IMPROVING", score=0, observed_at=now.isoformat(), headline=k)
            )
        else:
            out.append(
                c.CategoryObservation(category=k, state="CALM", score=0, observed_at=now.isoformat(), headline=k)
            )
    if stress_age_h is not None:
        out[0] = c.CategoryObservation(
            category=out[0].category,
            state="STRESS",
            score=85,
            observed_at=(now - timedelta(hours=stress_age_h)).isoformat(),
            headline="x",
        )
    return out


def test_n2_green_needs_coverage():
    now = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)
    assert scoring.compose(_green_obs(now), POLICY, now=now).hysteresis["raw_tier"] == "GREEN"
    assert scoring.compose(_green_obs(now, unknown=5), POLICY, now=now).hysteresis["raw_tier"] == "NONE"


def test_n2_green_needs_no_stress_in_24h():
    now = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)
    a = scoring.compose(_green_obs(now, stress_age_h=20), POLICY, now=now)
    assert a.hysteresis["raw_tier"] != "GREEN"


@pytest.mark.parametrize("start", ["RED", "ORANGE", "YELLOW", "BLUE"])
def test_n2_blue_or_above_reaches_green_only_after_closed_sessions(start):
    prior = {"tier": start, "market_tier": start, "hysteresis": {}}
    t = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)  # Tue 10:00 ET
    for i in range(4):  # one hour of GREEN readings inside one session
        a = scoring.compose(
            _green_obs(t + timedelta(minutes=15 * i)), POLICY, prior=prior, now=t + timedelta(minutes=15 * i)
        )
        prior = a.to_dict()
        assert a.tier == start, (start, i, a.tier)


# ── N3: reopen on re-entry ───────────────────────────────────────────────────────────────────────────────────────
def test_n3_acked_episode_reopens_when_the_tier_reenters_from_below(tmp_path):
    p = tmp_path / "ep.json"
    t = datetime(2026, 11, 2, 10, 0, tzinfo=ET)

    def a(tier, stress):
        return {"tier": tier, "score": 80, "observations": [{"category": k, "state": "STRESS"} for k in stress]}

    esc.observe(a("RED", ["options_flow", "breadth"]), now=t, policy=POLICY, path=p)
    esc.acknowledge(None, actor="tailnet:op", channel="cc", now=t + timedelta(minutes=5), path=p)
    for i in range(1, 10):
        esc.observe(
            a("YELLOW", ["options_flow"]),
            now=(t + timedelta(days=i)).replace(hour=16, minute=30),
            policy=POLICY,
            path=p,
        )
    r = esc.observe(a("RED", ["options_flow", "breadth"]), now=t + timedelta(days=15), policy=POLICY, path=p)
    assert r["event"] == "reopened" and r["episode"]["status"] == "OPEN"
    assert esc.due_repeats(now=t + timedelta(days=15, hours=2), policy=POLICY, path=p)


def test_n3_capped_orange_staying_orange_does_not_reopen(tmp_path):
    p = tmp_path / "ep.json"
    t = datetime(2026, 11, 2, 10, 0, tzinfo=ET)
    a = {"tier": "ORANGE", "score": 62, "observations": [{"category": "options_flow", "state": "STRESS"}]}
    esc.observe(a, now=t, policy=POLICY, path=p)
    ep = esc.open_episode(esc.load(p))
    for i in range(4):
        esc.record_send(
            ep["id"],
            now=t + timedelta(hours=i + 1),
            kind="orange",
            ok=True,
            path=p,
            policy_escalation=POLICY["escalation"],
            key=f"k{i}",
        )
    assert esc.observe(a, now=t + timedelta(days=1), policy=POLICY, path=p)["episode"]["status"] == "CAPPED"


# ── N4: ATR skips bars without OHLC (p_gapcrash.py) ──────────────────────────────────────────────────────────────
def test_n4_bars_without_high_low_never_blank_extended_hours():
    now = datetime(2026, 10, 29, 18, 15, tzinfo=ET)

    class R:
        def quotes(self, syms, start, end):
            return [
                {
                    "symbol": "QQQ",
                    "session": "afterhours",
                    "price": 600,
                    "prev_close": 615,
                    "as_of": (now - timedelta(minutes=5)).isoformat(),
                }
            ]

        def session_opens(self, syms, sessions, end):
            return [
                {
                    "symbol": "QQQ",
                    "date": "2026-10-29",
                    "open": 614,
                    "as_of": datetime(2026, 10, 29, 9, 30, tzinfo=ET).isoformat(),
                }
            ]

        def daily_bars(self, syms, sessions, end):
            out, d = [], date(2026, 10, 1)
            while d < date(2026, 10, 29):
                if d.weekday() < 5:
                    q = d >= date(2026, 10, 27)
                    out.append(
                        {
                            "symbol": "QQQ",
                            "date": d.isoformat(),
                            "open": None if q else 600,
                            "high": None if q else 610,
                            "low": None if q else 595,
                            "close": 615,
                        }
                    )
                d += timedelta(days=1)
            return out

    o = registry.evaluate_category(
        "extended_hours",
        c.EvalContext(now=now.astimezone(timezone.utc), reader=R(), policy=POLICY, session="afterhours"),
    )
    assert o.state == "STRESS", o.reason_unknown or o.headline


# ── M2: torn episode ledger never stops sends; API never echoes a path ───────────────────────────────────────────
def test_m2_torn_ledger_is_quarantined_and_the_writer_continues(tmp_path):
    p = tmp_path / "episodes.json"
    p.write_text('{"episodes": [', encoding="utf-8")
    r = esc.observe(
        {"tier": "RED", "observations": []},
        now=datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc),
        policy=POLICY,
        path=p,
    )
    assert r["event"] == "opened" and list(tmp_path.glob("episodes.json.corrupt-*"))


def test_m2_corrupt_message_names_the_file_not_its_path(tmp_path):
    p = tmp_path / "episodes.json"
    p.write_text("{", encoding="utf-8")
    with pytest.raises(esc.EpisodeStoreCorrupt) as ei:
        esc.load(p)
    assert str(tmp_path) not in str(ei.value)


# ── M3: projection budgets carry names only ──────────────────────────────────────────────────────────────────────
def test_m3_projection_budgets_have_no_book_percentages():
    snap = proj.snapshot_from_assessment(
        {
            "tier": "ORANGE",
            "score": 61,
            "as_of": "2026-11-03T15:00:00Z",
            "portfolio": {
                "vulnerability": 70,
                "budget_breaches": [
                    {"budget": "growth_style_pct", "actual": 62.4, "limit": 50, "ratio": 1.25, "scope": "book"}
                ],
            },
        }
    )
    b = snap["book"]["budgets"][0]
    assert set(b) == {"budget", "scope", "breached"}


# ── M4: versions keep the pre-gate stance ────────────────────────────────────────────────────────────────────────
def test_m4_curator_plans_versions_from_the_pre_gate_stance():
    src = (ROOT / "scripts" / "cio_opportunity_curator.py").read_text(encoding="utf-8")
    assert "store.plan(pre_gate" in src and "write_projection(assessments" in src


# ── session_of honours holidays and early closes ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "ts,want",
    [
        ("2026-11-26T11:00", "closed"),
        ("2026-11-27T12:00", "regular"),
        ("2026-11-27T14:00", "afterhours"),
        ("2026-10-31T10:00", "closed"),
    ],
)
def test_session_of_uses_the_nyse_calendar(ts, want):
    assert _evaluator().session_of(datetime.fromisoformat(ts).replace(tzinfo=ET)) == want


# ── N5: FRED freshness reads last_seen_at, fetched_at stays first-fetched ────────────────────────────────────────
def test_n5_freshness_consumers_read_last_seen_at():
    for f in ("scripts/health_agent.py", "scripts/api_v2.py"):
        assert "last_seen_at" in (ROOT / f).read_text(encoding="utf-8"), f
    mig = (ROOT / "migrations" / "2026_10_31_fred_last_seen_at.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS last_seen_at" in mig
    ing = (ROOT / "scripts" / "external_market_data_ingest.py").read_text(encoding="utf-8")
    assert (
        "last_seen_at=NOW()" in ing and "fetched_at=" not in ing.split("INSERT INTO fred_economic_series", 1)[1][:600]
    )


# ── N6: ACK principal; evaluated NONE projects as NONE ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("actor", ["service-token", "", "agent:x"])
def test_n6_ack_refuses_non_operator_principals(actor):
    code, body = proj.ack_outcome({"episode": {"id": "e1"}}, {}, actor=actor)
    assert code == 403 and not body["ok"]


def test_n6_evaluated_none_projects_as_none():
    now = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)
    snap = proj.snapshot_from_assessment(
        {"schema": c.SCHEMA_ASSESSMENT, "tier": "NONE", "score": 5, "as_of": now.isoformat()}
    )
    p = proj.build(snap, None, now=now)
    assert p["state"] == "evaluated" and p["tier"] == "NONE"
