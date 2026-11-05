"""Market Risk deep brief: fact pack, base rates, hardened prose gate, triggers, delivery, CIO wiring.

Operator 2026-10-31: "as part of the deeper analysis after the initial alert that you can use the LLM to coordinate
and to put together is the historical facts on what normally happens in the market when X is happening ... looking at
the options market to see how people are hedging. Everything needs to be factored in, earnings, every particular
catalyst." Hermetic: fixture reader, stubbed model, patched transport. No network, no DB, no spend.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib.market_risk import base_rates as br  # noqa: E402
from scripts.lib.market_risk import brief_guard, cio_context, deep_brief, registry  # noqa: E402
from scripts.lib.market_risk import contract as c  # noqa: E402
from scripts.lib.market_risk.deep_brief_facts import NullSources, PgSources, build_fact_pack, load_config  # noqa: E402
from scripts.lib.market_risk.fixture_reader import FixtureReader  # noqa: E402
from scripts.lib.market_risk.policy import load_policy  # noqa: E402
from scripts.lib import market_risk_projection as proj  # noqa: E402

COVERS = ["scripts/lib/market_risk/alerts.py"]  # the deep brief sends through alerts.deliver -> send_telegram

CFG = load_config()
POLICY = load_policy()
FIX = ROOT / "tests" / "fixtures" / "market_risk_scenarios"
NOW = datetime(2026, 10, 29, 22, 15, tzinfo=timezone.utc)
TITLES = list(CFG["sections"])

DOC = {
    "schema": c.SCHEMA_ASSESSMENT,
    "as_of": NOW.isoformat(),
    "tier": "ORANGE",
    "market_tier": "ORANGE",
    "score": 64.0,
    "confirming": 4,
    "contributors": [
        {
            "category": "options_flow",
            "points": 32.0,
            "headline": "QQQ P/C vol 3.31 (3.47x median)",
            "as_of": NOW.isoformat(),
        },
        {"category": "technical", "points": 18.0, "headline": "SOXX -21.5% off 52w high", "as_of": NOW.isoformat()},
    ],
    "observations": [
        {
            "category": "breadth",
            "state": "WARN",
            "score": 56,
            "headline": "RSP-SPY WEAKENING",
            "observed_at": NOW.isoformat(),
        },
        {
            "category": "macro_credit",
            "state": "CALM",
            "score": 10,
            "headline": "HY OAS steady",
            "observed_at": NOW.isoformat(),
        },
        {
            "category": "seasonal",
            "state": "CALM",
            "score": 22,
            "headline": "October midterm year",
            "observed_at": NOW.isoformat(),
        },
    ],
    "deescalates_if": "ORANGE -> YELLOW if score below 60 (now 64)",
}


def _reader():
    return FixtureReader(FIX, overlay=FIX / "oct2026")


# ── base rates ────────────────────────────────────────────────────────────────────────────────────────────────
def test_base_rate_table_holds_out_2026_and_is_regenerable():
    t = br.load_table()
    assert t["schema"] == br.TABLE_SCHEMA
    assert all(r["d"] < "2026-01-01" for r in t["rows"]), "no 2026 row may enter the table"
    last = t["rows"][-1]
    assert last["o"]["SPY"].get("1") is None, "a forward window reaching into 2026 must not be recorded"
    import importlib.util

    spec = importlib.util.spec_from_file_location("brb", ROOT / "scripts" / "market_risk_base_rates_build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rebuilt = mod.build(*mod.load_closes())
    assert json.dumps(rebuilt, sort_keys=True) == json.dumps(t, sort_keys=True), "table must equal a fresh build"


def test_harness_never_admits_2026_on_synthetic_data():
    import importlib.util
    from datetime import date as _d, timedelta as _td

    spec = importlib.util.spec_from_file_location("brb2", ROOT / "scripts" / "market_risk_base_rates_build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    days, x = [], _d(2025, 6, 2)
    while x < _d(2026, 3, 1):
        if x.weekday() < 5:
            days.append(x)
        x += _td(days=1)
    by = {s: {d: 100.0 + i * 0.1 for i, d in enumerate(days)} for s in mod.SYMBOLS}
    t = mod.build(days, by)
    assert t["rows"] and all(r["d"] < "2026-01-01" for r in t["rows"])
    last = t["rows"][-1]["o"]["SPY"]
    assert last.get("1") is None and last.get("20") is None, "no forward window may reach into 2026"


def test_conditional_backs_off_and_reports_sample_sizes():
    feats = {"pattern": "CONCENTRATED_TECH", "vix_b": "15-20", "sox_b": "20-30%", "breadth_b": "high", "vix_dir": "up"}
    res = br.conditional(feats, min_n=20)
    assert res["n_days"] >= 20 and res["SPY"]["20d"]["n"] >= 20
    assert set(res["conditions"]) | set(res["dropped"]) == set(feats)
    tiny = br.conditional(feats, min_n=10**6)
    assert tiny["insufficient_history"] is True and "SPY" not in tiny


def test_analogs_and_brief_never_feed_the_score():
    for mod in ("scoring.py", "registry.py", "explain.py", "contract.py"):
        src = (ROOT / "scripts/lib/market_risk" / mod).read_text(encoding="utf-8")
        assert "base_rates" not in src and "deep_brief" not in src, mod
    for f in (ROOT / "scripts/lib/market_risk/categories").glob("*.py"):
        src = f.read_text(encoding="utf-8")
        assert "base_rates" not in src and "deep_brief" not in src, f.name
    before = copy.deepcopy(DOC)
    build_fact_pack(NOW, _reader(), DOC, cfg=CFG)
    assert DOC == before, "building the pack must not change the assessment"


# ── fact pack ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_fact_pack_cites_every_fact_and_lists_unknowns():
    pack = build_fact_pack(NOW, _reader(), DOC, cfg=CFG)
    ids = [f["id"] for f in pack["facts"]]
    assert len(ids) == len(set(ids)) and all(not any(ch.isdigit() for ch in i) for i in ids)
    secs = {f["section"] for f in pack["facts"]}
    assert {"happening", "next", "hedging", "consensus", "change"} <= secs
    qqq = [f for f in pack["facts"] if f["label"] == "QQQ options"]
    assert qqq and "3.31" in qqq[0]["text"], "the 10-29 QQQ put/call surge must be in the hedging facts"
    hist = [f for f in pack["facts"] if f["section"] == "next"]
    assert any("(n=" in f["text"] for f in hist), "every base-rate fact carries its sample size"
    whats = {u["what"] for u in pack["unknown"]}
    assert {"dealer gamma", "shock type"} <= whats, "missing inputs are listed, never zero"
    assert pack["consensus"]["agreement_pct"] >= 0 and pack["consensus"]["majority"] in deep_brief_dirs()


def deep_brief_dirs():
    return ("risk_up", "risk_down", "neutral")


def test_fact_pack_uses_shock_type_sectors_and_stances_when_the_snapshot_has_them():
    snap = {
        "shock_type": {"class": "SECTOR", "confidence": 0.8},
        "sectors": {"stressed": [{"name": "Semiconductors", "etf": "SMH"}], "resilient": ["Consumer staples"]},
        "stances": [{"symbol": "ETF_A", "stance": "TRIM_REVIEW", "reasons": ["AI look-through 41%"]}],
    }
    pack = build_fact_pack(NOW, _reader(), DOC, snapshot=snap, cfg=CFG)
    texts = " ".join(f["text"] for f in pack["facts"])
    assert "Shock type SECTOR" in texts and "Semiconductors" in texts and "Consumer staples" in texts
    assert any(f["section"] == "exposure" and "ETF_A: CIO stance TRIM_REVIEW" in f["text"] for f in pack["facts"])


def test_pg_sources_filter_every_row_to_what_existed_at_the_instant():
    seen = []

    class FakeReader:
        def _rows(self, sql, params):
            seen.append((sql, params))
            return []

    src = PgSources(FakeReader())
    src.social(NOW, NOW)
    src.scalp_go(NOW, NOW)
    src.news(["AAPL"], NOW, NOW)
    src.catalysts(["AAPL"], NOW, NOW)
    src.material_changes(["AAPL"], NOW, NOW)
    src.analyst_revisions(["AAPL"], NOW)
    src.hermes_events(NOW, NOW)
    for sql, params in seen:
        assert "<= %s" in sql and NOW in params, sql
        assert sql.lstrip().upper().startswith("SELECT"), "read-only"


# ── deterministic brief ───────────────────────────────────────────────────────────────────────────────────────
def test_deterministic_brief_has_every_section_and_the_advisory_line():
    pack = build_fact_pack(NOW, _reader(), DOC, cfg=CFG)
    text = deep_brief.render_deterministic(pack, CFG)
    for t in TITLES + ["Your exposure"]:
        assert t in text
    assert deep_brief.ADVISORY in text
    assert "[hist-a]" in text and "Unknown:" in text


# ── the model only picks; the system renders ─────────────────────────────────────────────────────────────────
PROBE_P_CUR2 = [
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
    "Risk is 50 with 32 points from options flow, 3.97 P/C.",
    "Risk could reach 3.9 next week.",
    "Risk is 50; QQQ P/C 3.97 implies 397 basis points.",
    "Put/call 3.97 means about 4 times normal.",
    "QQQ may drop to 3,97.",
    "Options flow scores 32 at 3.85x.",
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
    "S\u200bell NVDA.",
    "Ѕell NVDA.",
    "QQQ could fall 25 percent this week.",
    "The S&P could drop to 2050.",
    "Expect a 30 point drop in QQQ.",
    "Support at 98.01 should hold.",
    "$ell NVDA.",
    "S e l l NVDA.",
    "S.e.l.l NVDA.",
    "Se-ll NVDA.",
    "De-risking now.",
]


def _pack():
    return build_fact_pack(NOW, _reader(), DOC, cfg=CFG)


ON = dict(CFG, enabled=True, timeout_s=2)


@pytest.mark.parametrize("answer", PROBE_P_CUR2)
def test_no_model_text_ever_reaches_the_brief(answer):
    pack = _pack()
    res = deep_brief.write(pack, call_model=lambda p, t, a=answer: (a, "grok"), cfg=ON)
    assert res["curated"] is False and res["text"] == deep_brief.render_deterministic(pack, CFG)


def test_valid_picks_render_only_bank_lead_ins_and_fact_text():
    pack = _pack()
    by = {f["id"]: f for f in pack["facts"]}
    nxt = [f["id"] for f in pack["facts"] if f["section"] == "next"]
    hap = [f["id"] for f in pack["facts"] if f["section"] == "happening"]
    # whole sections, reordered: the model leads with now-b and labels the history; it never drops a fact
    ans = json.dumps(
        {
            "happening": [{"t": "lead", "f": "now-b"}] + [{"t": "also", "f": f} for f in hap if f != "now-b"],
            "next": [{"t": "history", "f": nxt[1]}] + [{"t": "history", "f": f} for f in nxt if f != nxt[1]],
        }
    )
    res = deep_brief.write(pack, call_model=lambda p, t: (ans, "grok"), cfg=ON)
    assert res["curated"] is True, res.get("validation")
    assert f"- Main driver: {by['now-b']['text']} [now-b]" in res["text"]
    assert f"- Historically: {by[nxt[1]]['text']} [{nxt[1]}]" in res["text"]
    body = res["text"].split("Your exposure")[0]
    allowed = {ln for ln in deep_brief.render_deterministic(pack, CFG).splitlines()}
    for ln in body.splitlines():  # every line is a heading, a deterministic line, or a bank lead-in + a fact's text
        if ln and ln not in allowed:
            assert any(
                ln == f"- {tpl.format(text=f['text'])} [{f['id']}]"
                for tpl in deep_brief.TEMPLATES.values()
                for f in pack["facts"]
            ), ln


@pytest.mark.parametrize(
    "ans",
    [
        '{"happening": [{"t": "lead", "f": "hist-a"}]}',  # fact from another section
        '{"happening": [{"t": "Sell now: {text}", "f": "now-b"}]}',  # template not in the bank
        '{"happening": [{"t": "lead", "f": "now-zz"}]}',  # unknown fact
        '{"happening": [{"t": "lead", "f": "now-b", "x": "Sell"}]}',  # extra free-text field
        '{"exposure": [{"t": "plain", "f": "pos-a"}]}',  # the model never touches exposure
        '{"happening": [{"t": "lead", "f": "now-b"}, {"t": "also", "f": "now-b"}]}',  # duplicate
        '{"happening": ' + json.dumps([{"t": "plain", "f": "now-a"}] * 6) + "}",  # too many
        '["now-a"]',
        "Sell semis. {}",
        "{}",
    ],
)
def test_invalid_picks_send_the_deterministic_brief(ans):
    pack = _pack()
    res = deep_brief.write(pack, call_model=lambda p, t, a=ans: (a, "grok"), cfg=ON)
    assert res["curated"] is False and res["text"] == deep_brief.render_deterministic(pack, CFG)


def test_model_is_off_by_default_with_a_review_date():
    assert CFG["enabled"] is False
    assert str(CFG["disabled_until"]["review_by"]) == "2026-11-07"
    res = deep_brief.write(_pack(), call_model=lambda p, t: (_ for _ in ()).throw(AssertionError("called")), cfg=CFG)
    assert res["reason"] == "deep brief model disabled"


def test_writer_falls_back_on_lane_failure():
    pack = _pack()
    res = deep_brief.write(pack, call_model=lambda p, t: (_ for _ in ()).throw(RuntimeError("lane down")), cfg=ON)
    assert res["curated"] is False and "lane failure" in res["reason"]


def test_a_hung_model_never_holds_the_process(tmp_path):
    """Daemon thread + hard timeout: a process whose model sleeps 30 s still exits right after the timeout."""
    import subprocess

    script = tmp_path / "hang.py"
    script.write_text(
        "import sys, time\n"
        f"sys.path[:0] = [{str(ROOT)!r}, {str(ROOT / 'scripts')!r}]\n"
        "from scripts.lib.market_risk import deep_brief\n"
        "pack = {'facts': [{'id': 'now-a', 'section': 'happening', 'text': 'x'}], 'unknown': []}\n"
        "cfg = dict(deep_brief.load_config(), enabled=True, timeout_s=0.5)\n"
        "r = deep_brief.write(pack, call_model=lambda p, t: time.sleep(30), cfg=cfg)\n"
        "print(r['reason'])\n",
        encoding="utf-8",
    )
    t0 = time.monotonic()
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=25)
    assert "timeout" in out.stdout and time.monotonic() - t0 < 10, (out.stdout, out.stderr)


def test_prompt_carries_only_the_pack_and_never_exposure():
    pack = _pack()
    prompt = deep_brief.build_prompt(pack, CFG)
    assert all(f["id"] in prompt for f in pack["facts"] if f["section"] != "exposure")
    assert not any(f["id"] in prompt for f in pack["facts"] if f["section"] == "exposure")


# ── stance text and analyst source (review of #2393, items 4 and 5) ───────────────────────────────────────────
B1_PHRASES = [  # review of #2410, B1: all passed the old free-text filter unchanged
    "Half position until earnings clear",
    "Ten percent off the highs before adding",
    "One hundred ninety is the line",
    "Price back above one ninety-five",
    "Taking profits is warranted",
    "Smaller size into the print",
    "Fade strength into the print",
    "Under-weight vs index",
    "s e l l on strength",
    "trim 25% above $190",
    "AI look-through heavy",  # even a harmless phrase: free text is never rendered
]


@pytest.mark.parametrize("phrase", B1_PHRASES)
def test_stance_free_text_never_ships(phrase):
    snap = {
        "stances": [
            {"symbol": "ETF_A", "stance": "TRIM_REVIEW", "reasons": [phrase]},
            {"symbol": "ETF_B", "stance": "RE_ENTER_IF", "re_enter_if": phrase},
        ]
    }
    pack = build_fact_pack(NOW, _reader(), DOC, snapshot=snap, cfg=CFG)
    texts = {f["label"]: f["text"] for f in pack["facts"] if f["section"] == "exposure"}
    assert texts["stance ETF_A"] == "ETF_A: CIO stance TRIM_REVIEW (1 detail withheld)"
    assert texts["stance ETF_B"] == "ETF_B: CIO stance RE_ENTER_IF (1 detail withheld)"
    brief = deep_brief.render_deterministic(pack, CFG)
    assert phrase not in brief and phrase.lower() not in brief.lower()


def test_unknown_stance_names_and_bad_symbols_are_withheld():
    snap = {"stances": [{"symbol": "ETF_C", "stance": "sell 500 now"}, {"symbol": "bad symbol $", "stance": "HOLD"}]}
    pack = build_fact_pack(NOW, _reader(), DOC, snapshot=snap, cfg=CFG)
    texts = {f["label"]: f["text"] for f in pack["facts"] if f["section"] == "exposure"}
    assert texts["stance ETF_C"] == "ETF_C: CIO stance unrecognised (1 detail withheld)"
    assert "stance bad symbol $" not in texts


class _CatalystSources(NullSources):
    def catalysts(self, symbols, start, end):
        return [
            {
                "symbol": "NVDA",
                "catalyst_type": "analyst_upgrade",
                "headline": "Buy NVDA now, target $250 (+12%)",
                "impact_score": 9,
                "created_at": "2026-10-29T12:00:00+00:00",
            },
            {
                "symbol": "AAPL",
                "catalyst_type": "hedge_fund_buying",
                "headline": "Funds load up; trim at 240",
                "impact_score": 5,
                "created_at": "2026-10-29T13:00:00+00:00",
            },
        ]

    def material_changes(self, symbols, start, end):
        return [{"symbol": "NVDA", "kind": "sell_signal", "authority": "x", "created_at": "2026-10-29T13:00:00+00:00"}]


def test_catalyst_headlines_and_unknown_types_never_ship():
    pack = build_fact_pack(NOW, _reader(), DOC, sources=_CatalystSources(), cfg=CFG)
    t = {f["label"]: f["text"] for f in pack["facts"]}
    assert t["company catalysts"] == (
        "Company catalysts in 72h: NVDA analyst upgrade; AAPL other event (2 headlines withheld)"
    )
    assert t["material changes"] == "Material changes in 72h: NVDA other change"
    brief = deep_brief.render_deterministic(pack, CFG)
    for bad in ("Buy NVDA", "$250", "12%", "load up", "trim at", "sell_signal", "hedge_fund_buying"):
        assert bad not in brief


def test_analyst_targets_come_from_pg_sources_and_null_sources_is_empty():
    assert NullSources().analyst_revisions(["AAPL"], NOW) == []
    seen = []

    class FakeReader:
        def _rows(self, sql, params):
            seen.append(sql)
            if "tgt_now" in sql:
                return [{"symbol": "AAPL", "tgt_now": 210.0, "as_of": "2026-10-28"}]
            return [{"symbol": "AAPL", "tgt_then": 200.0}]

    rows = PgSources(FakeReader()).analyst_revisions(["AAPL"], NOW)
    assert rows and rows[0]["tgt_now"] == 210.0 and rows[0]["tgt_then"] == 200.0
    assert all("target_price" in q for q in seen)


def test_triggers():
    assert deep_brief.should_brief({"tier": "ORANGE"}, None, CFG) == "tier"
    assert deep_brief.should_brief({"tier": "ORANGE"}, {"tier": "YELLOW"}, CFG) == "tier"
    assert deep_brief.should_brief({"tier": "ORANGE"}, {"tier": "ORANGE"}, CFG) is None
    assert deep_brief.should_brief({"tier": "YELLOW"}, {"tier": "BLUE"}, CFG) is None
    s1, s2 = {"class": "SECTOR"}, {"class": "SYSTEMIC"}
    assert (
        deep_brief.should_brief({"tier": "YELLOW", "shock_type": s2}, {"tier": "YELLOW", "shock_type": s1}, CFG)
        == "shock_type"
    )
    assert deep_brief.should_brief({"tier": "BLUE", "shock_type": s2}, {"tier": "BLUE", "shock_type": s1}, CFG) is None


def _transport(monkeypatch, ok=True):
    calls = []
    mod = types.ModuleType("telegram_alert")

    def send_telegram(message, **kw):
        calls.append((message, kw))
        return ok(message) if callable(ok) else ok

    mod.send_telegram = send_telegram
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    return calls


# ── evaluator: after the initial cards, stored in the snapshot, kept while elevated ────────────────────────────
def _evaluator():
    import importlib.util

    spec = importlib.util.spec_from_file_location("mre_eval_db", ROOT / "scripts" / "market_risk_evaluate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def state(tmp_path, monkeypatch):
    root = tmp_path / "state"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(root))
    monkeypatch.setenv("MARKET_RISK_EPISODES_PATH", str(root / "data/runtime/market_risk/episodes.json"))
    monkeypatch.setenv("MARKET_RISK_SENT_LEDGER", str(root / "data/runtime/market_risk/sent_keys.json"))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    return root


def _orange_obs(now):
    spec = {
        "options_flow": ("STRESS", 85),
        "technical": ("STRESS", 80),
        "breadth": ("WARN", 55),
        "event": ("STRESS", 75),
        "volatility": ("WARN", 50),
        "macro_credit": ("CALM", 10),
        "seasonal": ("CALM", 20),
        "cross_asset": ("CALM", 15),
        "extended_hours": ("CALM", 10),
    }
    return [
        c.CategoryObservation(category=k, state=s, score=float(v), observed_at=now.isoformat(), headline=f"{k} {s}")
        for k, (s, v) in spec.items()
    ]


def _run(mod, now, prior=None, apply=True):
    return mod.run_cycle(
        now,
        object(),
        POLICY,
        prior,
        apply=apply,
        on_assessed=(lambda d: mod.persist(d, now)) if apply else None,
        call_model=lambda p, t: "",
    )


def test_evaluator_sends_the_initial_card_first_then_the_brief_and_stores_it(state, monkeypatch):
    calls = _transport(monkeypatch)
    mod = _evaluator()
    monkeypatch.setattr(registry, "evaluate_all", lambda ctx: _orange_obs(ctx.now))
    out = _run(mod, NOW)
    assert out["assessment"]["tier"] in ("ORANGE", "RED")
    assert calls and not calls[0][0].startswith("MARKET RISK DEEP BRIEF"), "initial card first"
    assert calls[-1][0].startswith("MARKET RISK DEEP BRIEF") and calls[-1][1]["priority"] == "P2"
    assert calls[-1][1]["message_class"] == "market_risk"
    snap = json.loads(mod.snapshot_path().read_text())
    assert snap["deep_brief"]["text"].startswith("MARKET RISK DEEP BRIEF")
    projection = proj.build(snap, None)
    assert projection["deep_brief"]["text"] and cio_context.ask_facts(projection)["deep_brief"]["facts"]
    _run(mod, NOW + timedelta(minutes=15), prior=out["assessment"])
    assert sum(m.startswith("MARKET RISK DEEP BRIEF") for m, _ in calls) == 1, "once per episode transition"
    mod.persist(dict(out["assessment"], tier="YELLOW"), NOW)
    assert "deep_brief" in json.loads(mod.snapshot_path().read_text()), "kept while elevated"
    mod.persist(dict(out["assessment"], tier="BLUE"), NOW)
    assert "deep_brief" not in json.loads(mod.snapshot_path().read_text()), "dropped once risk is low"


def test_brief_waits_for_a_sent_initial_card_and_is_retried(state, monkeypatch):
    fail_initial = {"on": True}
    calls = _transport(
        monkeypatch, ok=lambda m: not (fail_initial["on"] and not m.startswith("MARKET RISK DEEP BRIEF"))
    )
    mod = _evaluator()
    monkeypatch.setattr(registry, "evaluate_all", lambda ctx: _orange_obs(ctx.now))
    out = _run(mod, NOW)
    assert calls and not any(m.startswith("MARKET RISK DEEP BRIEF") for m, _ in calls), "no brief before a sent initial"
    fail_initial["on"] = False
    for k in range(1, 12):  # the initial card's retry backoff, then the brief right after it
        _run(mod, NOW + timedelta(minutes=15 * k), prior=out["assessment"])
        if any(m.startswith("MARKET RISK DEEP BRIEF") for m, _ in calls):
            break
    briefs = [i for i, (m, _) in enumerate(calls) if m.startswith("MARKET RISK DEEP BRIEF")]
    sent_initial = [i for i, (m, _) in enumerate(calls) if not m.startswith("MARKET RISK DEEP BRIEF")]
    assert len(briefs) == 1 and briefs[0] > max(sent_initial[:-1] or [0]), (len(calls), briefs)


def test_a_brief_failure_never_breaks_the_cycle(state, monkeypatch):
    _transport(monkeypatch)
    mod = _evaluator()
    monkeypatch.setattr(registry, "evaluate_all", lambda ctx: _orange_obs(ctx.now))
    monkeypatch.setattr(deep_brief, "build", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    out = _run(mod, NOW, apply=False)
    kinds = {s.get("kind"): s for s in out["sends"]}
    assert "initial" in kinds and kinds.get("deep_brief", {}).get("error", "").startswith("drain raised ValueError")


def test_ask_the_cio_on_demand(monkeypatch):
    assert cio_context.wants_deep_brief("Give me the deep brief on this selloff")
    assert not cio_context.wants_deep_brief("how is NVDA doing")
    stored = {"deep_brief": {"text": "MARKET RISK DEEP BRIEF — X", "facts": []}}
    monkeypatch.setattr(cio_context, "load_market_risk", lambda: stored)
    assert cio_context.deep_brief_on_demand()["source"] == "stored"
    monkeypatch.setattr(cio_context, "load_market_risk", lambda: (_ for _ in ()).throw(OSError("x")))
    assert cio_context.deep_brief_on_demand()["source"] == "unavailable"


def test_null_sources_report_unknown_not_zero():
    pack = build_fact_pack(NOW, _reader(), DOC, sources=NullSources(), cfg=CFG)
    whats = {u["what"] for u in pack["unknown"]}
    assert {"social sentiment", "news tone", "company catalysts"} <= whats


# ── review of #2410: N4 pick rules, the drain gate (B2, N1, N2) end to end ─────────────────────────────────────
def test_deeply_nested_json_falls_back_instead_of_raising():
    pack = _pack()
    for ans in ("[" * 100000, '{"happening": ' + "[" * 50000 + "]" * 50000 + "}"):
        res = deep_brief.write(pack, call_model=lambda p, t, a=ans: (a, "grok"), cfg=ON)
        assert res["curated"] is False and res["text"] == deep_brief.render_deterministic(pack, CFG)


def test_lead_ins_are_tied_to_their_sections():
    pack = _pack()
    hap = [f["id"] for f in pack["facts"] if f["section"] == "happening"]
    ans = json.dumps({"happening": [{"t": "history", "f": f} for f in hap]})  # "Historically:" on today's facts
    v = deep_brief.parse_picks(ans, pack)
    assert not v["ok"] and any("not allowed in happening" in r for r in v["reasons"])
    for t, secs in deep_brief.TEMPLATE_SECTIONS.items():
        assert t in deep_brief.TEMPLATES and secs <= set(deep_brief.SECTION_KEYS)


def test_a_section_the_model_includes_must_be_complete():
    pack = _pack()
    nxt = [f["id"] for f in pack["facts"] if f["section"] == "next"]
    assert len(nxt) > 2
    # cherry-picking the rosiest base rate and dropping the rest is refused
    v = deep_brief.parse_picks(json.dumps({"next": [{"t": "history", "f": nxt[0]}]}), pack)
    assert not v["ok"] and any("omits" in r for r in v["reasons"])
    res = deep_brief.write(
        pack, call_model=lambda p, t: (json.dumps({"next": [{"t": "history", "f": nxt[0]}]}), "g"), cfg=ON
    )
    assert res["curated"] is False


def _brief_ent(transition="deep_brief:tier", after="init-k", episode="ep1"):
    return {
        "key": "market_risk:deep_brief:ep1:ORANGE:na",
        "kind": "deep_brief",
        "intent": {"transition": transition, "after_key": after, "episode": episode},
    }


def test_drain_gate_retires_a_brief_whose_tier_has_fallen_away():
    sent = {"init-k": {"status": "sent", "kind": "initial", "episode_id": "ep1"}}
    assert deep_brief.drain_gate(_brief_ent(), {"tier": "BLUE"}, sent, CFG)[0] == "retire"
    assert deep_brief.drain_gate(_brief_ent(), {"tier": "YELLOW"}, sent, CFG)[0] == "retire"
    assert deep_brief.drain_gate(_brief_ent(), {"tier": "ORANGE"}, sent, CFG)[0] == "send"
    shock = _brief_ent("deep_brief:shock_type", after=None)
    assert deep_brief.drain_gate(shock, {"tier": "BLUE"}, sent, CFG)[0] == "retire"
    assert deep_brief.drain_gate(shock, {"tier": "YELLOW"}, sent, CFG)[0] == "send"


def test_drain_gate_a_sent_then_superseded_initial_does_not_retire_its_brief():
    torn = {"init-k": {"status": "superseded", "sent_at": "2026-10-29T22:15:00+00:00", "episode_id": "ep1"}}
    assert deep_brief.drain_gate(_brief_ent(), {"tier": "ORANGE"}, torn, CFG) == ("send", "ok")
    unsent = {"init-k": {"status": "superseded", "episode_id": "ep1"}}
    assert deep_brief.drain_gate(_brief_ent(), {"tier": "ORANGE"}, unsent, CFG)[0] == "retire"


def test_drain_gate_waits_for_every_unsent_card_of_its_episode():
    shock = _brief_ent("deep_brief:shock_type", after=None)  # a same-tier shock change has no initial card
    keys = {"init-k": {"status": "pending", "kind": "initial", "episode_id": "ep1"}}
    assert deep_brief.drain_gate(shock, {"tier": "ORANGE"}, keys, CFG)[0] == "wait"
    keys["init-k"]["status"] = "sent"
    keys["other-ep"] = {"status": "pending", "kind": "initial", "episode_id": "ep2"}
    assert deep_brief.drain_gate(shock, {"tier": "ORANGE"}, keys, CFG)[0] == "send"


class _WithShock:
    """Delegating wrapper: the evaluator's assessment plus a shock type, as the precision builder will add one."""

    def __init__(self, a, shock):
        self._a, self._shock = a, shock

    def __getattr__(self, name):
        return getattr(self._a, name)

    def to_dict(self):
        return {**self._a.to_dict(), "shock_type": {"class": self._shock}}


def test_shock_brief_never_overtakes_an_unsent_initial_card(state, monkeypatch):
    """Review of #2410, B2: ORANGE initial queued, Telegram down 10 cycles, the shock type changes at the same tier,
    Telegram returns. No brief may be sent while the initial card is unsent."""
    up = {"on": False}
    calls = _transport(monkeypatch, ok=lambda m: up["on"])
    mod = _evaluator()
    monkeypatch.setattr(registry, "evaluate_all", lambda ctx: _orange_obs(ctx.now))
    shock = {"v": "TECH_CONCENTRATED"}
    orig = mod.evaluate
    monkeypatch.setattr(mod, "evaluate", lambda *a, **k: _WithShock(orig(*a, **k), shock["v"]))
    prior, delivered = None, []
    for k in range(40):
        if k == 10:
            shock["v"] = "BROAD_DELEVERAGING"
        if k == 11:
            up["on"] = True
        before = len(calls)
        out = _run(mod, NOW + timedelta(minutes=15 * k), prior=prior)
        prior = out["assessment"]
        if up["on"]:
            delivered += [m for m, _ in calls[before:]]
    first_brief = next(i for i, m in enumerate(delivered) if m.startswith("MARKET RISK DEEP BRIEF"))
    initials = [i for i, m in enumerate(delivered) if m.startswith("🟠 MARKET RISK")]
    assert initials and initials[0] < first_brief, "the initial card is delivered before any brief"
    ledger = json.loads(Path(os.environ["MARKET_RISK_SENT_LEDGER"]).read_text())["keys"]
    pending_cards = [
        k for k, r in ledger.items() if r.get("kind") != "deep_brief" and r.get("status") in ("pending", "claimed")
    ]
    assert pending_cards == []
    assert sum(m.startswith("MARKET RISK DEEP BRIEF") for m in delivered) == 2, "tier brief + shock-type brief"


@pytest.mark.parametrize(
    "posture",
    B1_PHRASES + ["Trim half above one ninety, cut to underweight", "DEFENSIVE then sell at 190"],
)
def test_cio_posture_free_text_never_ships(posture):
    """Review of #2410 round 3, B3: the CIO posture is free text from another store; only a fixed name renders."""
    pack = build_fact_pack(NOW, _reader(), DOC, snapshot={"cio": {"posture": posture}}, cfg=CFG)
    cons = [f["text"] for f in pack["facts"] if f["section"] == "consensus"]
    brief = deep_brief.render_deterministic(pack, CFG)
    assert any("CIO posture unrecognised (1 detail withheld)" in t for t in cons)
    assert posture.upper() not in brief.upper()


@pytest.mark.parametrize(
    "posture,shown", [("defensive", "DEFENSIVE"), ("risk-off", "RISK OFF"), ("Neutral", "NEUTRAL")]
)
def test_cio_posture_known_names_still_render(posture, shown):
    pack = build_fact_pack(NOW, _reader(), DOC, snapshot={"cio": {"posture": posture}}, cfg=CFG)
    cons = [f["text"] for f in pack["facts"] if f["section"] == "consensus"]
    assert any(f"CIO posture {shown}" in t for t in cons)
