"""Market Risk deep brief: fact pack, base rates, hardened prose gate, triggers, delivery, CIO wiring.

Operator 2026-10-31: "as part of the deeper analysis after the initial alert that you can use the LLM to coordinate
and to put together is the historical facts on what normally happens in the market when X is happening ... looking at
the options market to see how people are hedging. Everything needs to be factored in, earnings, every particular
catalyst." Hermetic: fixture reader, stubbed model, patched transport. No network, no DB, no spend.
"""

from __future__ import annotations

import copy
import json
import sys
import time
import types
from datetime import datetime, timezone
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


# ── the hardened prose gate ───────────────────────────────────────────────────────────────────────────────────
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
    "S​ell NVDA.",
    "Ѕell NVDA.",
]
PROBE_P_CUR3 = [
    "QQQ could fall 25 percent this week.",
    "The S&P could drop to 2050.",
    "Expect a 30 point drop in QQQ.",
    "Risk 50 could become 51.6 tomorrow.",
    "QQQ could fall 12 percent, VIX to 31.",
    "Risk is 50, 3.97 P/C means 52 by Monday.",
    "NVDA could lose 5.0 percent.",
    "NVDA could lose 5.0%.",
]
DESCRIPTIVE_CONTROLS = {"Risk is 50 with 32 points from options flow, 3.97 P/C.", "Options flow scores 32 at 3.85x."}
GATE_PACK = {
    "facts": [
        {"id": "now-a", "section": "happening", "text": "Market risk YELLOW 50/100, 2 categories confirming"},
        {"id": "now-b", "section": "happening", "text": "options_flow: QQQ P/C OI 3.97 (3.85x median) (+32 points)"},
    ]
}


def _draft(sentence: str, cite: bool) -> str:
    lines = []
    for i, t in enumerate(TITLES):
        lines += [t, (sentence + (" [now-a, now-b]" if cite else "")) if i == 0 else "Market risk is YELLOW [now-a]."]
    return "\n".join(lines)


@pytest.mark.parametrize("cite", [False, True])
def test_probe_strings_never_pass_except_pure_descriptions(cite):
    passed = {s for s in PROBE_P_CUR2 + PROBE_P_CUR3 if deep_brief.validate(_draft(s, cite), GATE_PACK, CFG)["ok"]}
    if not cite:
        assert passed == set(), passed
    else:
        assert passed <= DESCRIPTIVE_CONTROLS, passed - DESCRIPTIVE_CONTROLS


@pytest.mark.parametrize(
    "bad",
    [
        "Hedging demand is high [now-b]. You may want to look at it [now-b].",
        "QQQ open interest is 3.97 and risk could reach 25 [now-b].",
        "Index put/call open interest is 3.97 [opt-z].",
        "Investors are hedging, with put/call at 3.97 and a 2050 target [now-b].",
        "Put/call is 3.97 (аbout 4x) [now-b].",
        "Put/call is 3.97 ⁣today [now-b].",
        "Put/call is 3.97, so a half-size position fits [now-b].",
        "Consider the 3.97 put/call [now-b].",
        "We see index hedging demand at 3.97 [now-b].",  # first person alone
        "Hedging demand on the index is elevated.",  # no citation and no number: only the citation rule catches it
    ],
)
def test_gate_rejects_person_invention_unknown_ids_confusables_and_number_words(bad):
    assert not deep_brief.validate(_draft(bad, False), GATE_PACK, CFG)["ok"]


def test_citation_after_the_full_stop_belongs_to_its_sentence():
    draft = _draft("Index hedging demand is elevated: QQQ put/call open interest is 3.97.", False).replace(
        "3.97.", "3.97. [now-b]", 1
    )
    assert deep_brief.validate(draft, GATE_PACK, CFG)["ok"]


# ── writer ────────────────────────────────────────────────────────────────────────────────────────────────────
def _good_draft(pack: dict) -> str:
    fa = next(f for f in pack["facts"] if f["id"] == "now-a")
    lines = []
    for t in TITLES:
        lines += [t, f"The engine reads {fa['text'].split(',')[0]} [now-a]."]
    return "\n".join(lines)


def test_writer_accepts_a_grounded_draft_and_keeps_exposure_deterministic():
    pack = build_fact_pack(NOW, _reader(), DOC, cfg=CFG)
    res = deep_brief.write(pack, call_model=lambda p, t: (_good_draft(pack), "grok"), cfg=CFG)
    assert res["curated"] is True and res["lane"] == "grok", res.get("validation")
    assert "Your exposure" in res["text"] and deep_brief.ADVISORY in res["text"]


@pytest.mark.parametrize(
    "model",
    [
        lambda p, t: "Sell semis now.",
        lambda p, t: (_ for _ in ()).throw(RuntimeError("lane down")),
        lambda p, t: "",
    ],
)
def test_writer_falls_back_to_the_deterministic_brief(model):
    pack = build_fact_pack(NOW, _reader(), DOC, cfg=CFG)
    res = deep_brief.write(pack, call_model=model, cfg=CFG)
    assert res["curated"] is False and res["text"] == deep_brief.render_deterministic(pack, CFG)


def test_writer_times_out_to_the_deterministic_brief():
    pack = build_fact_pack(NOW, _reader(), DOC, cfg=CFG)
    cfg = dict(CFG, timeout_s=0.2)
    t0 = time.monotonic()
    res = deep_brief.write(pack, call_model=lambda p, t: time.sleep(2) or "late", cfg=cfg)
    assert res["curated"] is False and "timeout" in res["reason"] and time.monotonic() - t0 < 1.5


def test_prompt_carries_only_the_pack():
    pack = build_fact_pack(NOW, _reader(), DOC, cfg=CFG)
    prompt = deep_brief.build_prompt(pack, CFG)
    assert all(f["id"] in prompt for f in pack["facts"] if f["section"] != "exposure")
    assert not any(f["id"] in prompt for f in pack["facts"] if f["section"] == "exposure")


# ── triggers and delivery ─────────────────────────────────────────────────────────────────────────────────────
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


def _transport(monkeypatch):
    calls = []
    mod = types.ModuleType("telegram_alert")

    def send_telegram(message, **kw):
        calls.append((message, kw))
        return True

    mod.send_telegram = send_telegram
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    return calls


def test_follow_up_dry_run_sends_nothing_and_dedupes(tmp_path, monkeypatch):
    calls = _transport(monkeypatch)
    ledger = tmp_path / "keys.json"
    kw = dict(now=NOW, reader=_reader(), policy=POLICY, apply=False, ledger=ledger, episode_id="ep1", cfg=CFG)
    r1 = deep_brief.follow_up(DOC, None, **kw)
    r2 = deep_brief.follow_up(DOC, None, **kw)
    assert calls == [] and r1["send"]["sent"] is False and r1["brief"]["curated"] is False
    assert r2["send"].get("deduped") is True, "once per episode transition"


def test_follow_up_live_sends_one_p2_market_risk_card(tmp_path, monkeypatch):
    calls = _transport(monkeypatch)
    res = deep_brief.follow_up(
        DOC,
        {"tier": "YELLOW"},
        now=NOW,
        reader=_reader(),
        policy=POLICY,
        apply=True,
        ledger=tmp_path / "keys.json",
        episode_id="ep1",
        call_model=lambda p, t: "Sell now.",
        cfg=CFG,
    )
    assert len(calls) == 1 and res["send"]["sent"] is True
    msg, kw = calls[0]
    assert kw["priority"] == "P2" and kw["message_class"] == "market_risk"
    assert msg.startswith("MARKET RISK DEEP BRIEF") and "Sell now" not in msg


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


def test_evaluator_sends_the_initial_card_first_then_stores_the_brief(state, monkeypatch):
    calls = _transport(monkeypatch)
    mod = _evaluator()
    monkeypatch.setattr(registry, "evaluate_all", lambda ctx: _orange_obs(ctx.now))
    out = mod.run_cycle(
        NOW, object(), POLICY, None, apply=True, on_assessed=lambda d: mod.persist(d, NOW), call_model=lambda p, t: ""
    )
    kinds = [kw.get("priority") for _, kw in calls]
    assert out["assessment"]["tier"] in ("ORANGE", "RED")
    assert calls and not calls[0][0].startswith("MARKET RISK DEEP BRIEF"), "initial card first"
    assert calls[-1][0].startswith("MARKET RISK DEEP BRIEF") and kinds[-1] == "P2"
    snap = json.loads(mod.snapshot_path().read_text())
    assert snap["deep_brief"]["text"].startswith("MARKET RISK DEEP BRIEF")
    projection = proj.build(snap, None)
    assert projection["deep_brief"]["trigger"] == "tier"
    facts = cio_context.ask_facts(projection)
    assert facts["deep_brief"]["facts"], "Ask-the-CIO sees the cited facts"
    mod.persist(dict(out["assessment"], tier="YELLOW"), NOW)
    assert "deep_brief" in json.loads(mod.snapshot_path().read_text()), "kept while elevated"
    mod.persist(dict(out["assessment"], tier="BLUE"), NOW)
    assert "deep_brief" not in json.loads(mod.snapshot_path().read_text()), "dropped once risk is low"


def test_a_brief_failure_never_breaks_the_cycle(state, monkeypatch):
    _transport(monkeypatch)
    mod = _evaluator()
    monkeypatch.setattr(registry, "evaluate_all", lambda ctx: _orange_obs(ctx.now))
    monkeypatch.setattr(deep_brief, "follow_up", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    out = mod.run_cycle(NOW, object(), POLICY, None, apply=False)
    assert out["deep_brief"]["error"].startswith("ValueError") and out["sends"]


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
