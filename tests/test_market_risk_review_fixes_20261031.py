"""Regression tests for the adversarial review of the integrated engine (#2362, round 1), one per finding.

B1 the CIO and the UI never saw the engine (path / schema / field-name mismatch) — end-to-end, no loader mocks.
B3 curation let behaviour advice and non-ASCII digits through; ORANGE/RED are never curated by default.
B4 weekends and holidays counted as sessions (hysteresis and episode resolution).
B5 RED repeats after the market fell; a finished cap read as stalled; dedupe keys were dead; a crash re-sent.
B6 the 16:05 regime VIX snapshot beat FRED VIXCLS.  M1 FRED/earnings look-ahead.  M2 guards.  M3 book lines.
M4 the gate's HOLD overlay wrote a CIO-memory version on every tier crossing.
Hermetic: no network, no DB, no Telegram (the transport is a stub), synthetic data only.
"""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.market_risk import alerts, cio_context, curation, escalation as esc, registry, sessions  # noqa: E402
from scripts.lib.market_risk import contract as c, scoring  # noqa: E402
from scripts.lib.market_risk.policy import load_policy  # noqa: E402
from scripts.lib import market_risk_projection as proj  # noqa: E402

COVERS = ["scripts/lib/market_risk/alerts.py", "scripts/market_risk_evaluate.py"]

POLICY = load_policy()
T_ORANGE = datetime(2026, 10, 28, 20, 30, tzinfo=timezone.utc)  # Wed 16:30 ET


def _obs(spec, now):
    out = []
    for k in c.CATEGORIES:
        if k in spec:
            st, sc = spec[k]
            out.append(
                c.CategoryObservation(
                    category=k, state=st, score=sc, observed_at=now.isoformat(), headline=f"{k}: {st.lower()} {sc}"
                )
            )
        else:
            out.append(c.unknown(k, now, "fixture"))
    return out


ORANGE_SPEC = {
    "options_flow": ("STRESS", 85),
    "technical": ("STRESS", 80),
    "event": ("STRESS", 88),
    "breadth": ("WARN", 58),
    "volatility": ("WARN", 60),
    "macro_credit": ("CALM", 20),
    "seasonal": ("CALM", 10),
    "cross_asset": ("CALM", 15),
    "extended_hours": ("CALM", 10),
}


def _evaluator():
    import importlib.util

    spec = importlib.util.spec_from_file_location("mre_eval_fix", ROOT / "scripts" / "market_risk_evaluate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _transport(monkeypatch, ok=True, on_send=None):
    calls = []
    mod = types.ModuleType("telegram_alert")

    def send_telegram(message, **kw):
        if on_send:
            on_send(message, kw)
        calls.append((message, kw))
        return ok

    mod.send_telegram = send_telegram
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    return calls


@pytest.fixture
def state(tmp_path, monkeypatch):
    root = tmp_path / "state"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(root))
    monkeypatch.setenv("MARKET_RISK_EPISODES_PATH", str(root / "data/runtime/market_risk/episodes.json"))
    monkeypatch.setenv("MARKET_RISK_SENT_LEDGER", str(root / "data/runtime/market_risk/sent_keys.json"))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    return root


def _run_apply(mod, now, monkeypatch, prior=None):
    monkeypatch.setattr(registry, "evaluate_all", lambda ctx: _obs(ORANGE_SPEC, ctx.now))
    written = {}

    def persist(d):
        written["latest"] = mod.persist(d, now)

    return mod.run_cycle(now, object(), POLICY, prior, apply=True, portfolio=None, on_assessed=persist), written


# ── B1: end to end — evaluator -> snapshot -> projection -> CIO / Ask-the-CIO / gate / API / Home banner ─────────


def test_b1_apply_cycle_reaches_every_consumer_without_loader_mocks(state, monkeypatch):
    mod = _evaluator()
    _transport(monkeypatch)
    cycle, _ = _run_apply(mod, T_ORANGE, monkeypatch)
    tier = cycle["assessment"]["tier"]
    assert tier in ("ORANGE", "RED"), cycle["assessment"]["score"]
    snap_file = state / proj.SNAPSHOT_REL
    assert snap_file.exists() and (state / "data/runtime/market_risk/latest.json").exists()
    snap = json.loads(snap_file.read_text())
    assert snap["schema"] == proj.SNAPSHOT_SCHEMA and snap["contributors"][0]["name"]
    # the real loader every consumer uses, on the real file
    from scripts.lib.cio_market_context_state import load_market_risk_projection

    mr = load_market_risk_projection(project_root=state)
    assert mr["tier"] == tier and mr["state"] in ("evaluated", "stale")
    line = cio_context.tier_line(mr)
    assert line.startswith(f"Market risk {tier}") and "Options flow" in line, line
    facts = cio_context.ask_facts(mr)
    assert facts["tier"] == tier and facts["contributors"][0]["name"] and facts["contributors"][0]["detail"]
    gate = {
        "enabled": True,
        "hold_tiers": ["ORANGE", "RED"],
        "demote_tiers": ["YELLOW"],
        "max_stale_hours": 10**6,
        "entry_types": ["new_position"],
        "hold_stances": {"ADD": "HOLD"},
    }
    items, rep = cio_context.apply_entry_gate([{"symbol": "AAA", "type": "new_position", "stance": "ADD"}], mr, gate)
    assert rep["action"] == "hold" and items[0]["stance"] == "HOLD"
    # API /market-risk/latest and Home banner: same build() on the same file, fresh clock
    fresh = proj.build(snap, None, now=T_ORANGE + timedelta(minutes=10))
    assert fresh["state"] == "evaluated" and fresh["tier"] == tier and proj.banner_visible(fresh)
    assert fresh["confirming"] == {"n": cycle["assessment"]["confirming"], "of": 9}


def test_b1_projection_accepts_the_raw_assessment_too():
    from scripts.lib.market_risk import explain

    a = explain.explain(scoring.compose(_obs(ORANGE_SPEC, T_ORANGE), POLICY, now=T_ORANGE), POLICY).to_dict()
    p = proj.build(a, None, now=T_ORANGE)
    assert p["state"] == "evaluated" and p["contributors"] and "name" in p["contributors"][0]


def test_b1_one_path_constant_everywhere():
    api = (ROOT / "scripts/api_v2.py").read_text()
    ctx = (ROOT / "scripts/lib/cio_market_context_state.py").read_text()
    assert '"market_risk_latest.json"' not in api and '"data/runtime/market_risk_latest.json"' not in ctx
    # since PR 2425 both read through market_risk_projection.load_snapshot, which owns SNAPSHOT_REL (live) and
    # SHADOW_REL (the labelled fallback)
    assert "load_snapshot" in api and "load_snapshot" in ctx
    projection = (ROOT / "scripts/lib/market_risk_projection.py").read_text()
    body = projection[projection.index("def load_snapshot") :][:2500]
    assert "load(SNAPSHOT_REL)" in body and "load(SHADOW_REL)" in body


# ── B3: curation ─────────────────────────────────────────────────────────────────────────────────────────────

CARD = (
    "🟡 MARKET RISK YELLOW 56/100 · 2 of 9 categories confirm\n"
    "options_flow +32 · Options flow: QQQ P/C OI 3.97 (3.85x median) · 10-30 17:35 ET\n"
    "Your book: NVDA stop 4.2% below\nEvaluated 10-31 10:36 ET. Advisory. No order, size or stop level is implied."
)
DOC = {
    "tier": "YELLOW",
    "score": 56,
    "confirming": 2,
    "as_of": "2026-10-31T14:36:00Z",
    "contributors": [
        {"category": "options_flow", "points": 32, "headline": "Options flow: QQQ P/C OI 3.97 (3.85x median)"}
    ],
    "observations": [{"evidence": [{"value": 712.5}, {"value": 500}, {"value": 100}]}],
}
REJECT = [
    "Trim 500 shares of NVDA.",
    "Lighten NVDA by half before the close.",
    "Take profits in NVDA and raise cash.",
    "Go to cash now.",
    "Unload one hundred shares of NVDA.",
    "Put a stop under 712.5 on QQQ.",
    "Move your NVDA stop level to 4.2% below.",
    "Rotate out of semis into bonds.",
    "De-risk: cut exposure to the AI basket.",
    "Sell ５００ shares.",
    "VIX could spike to ４５ tomorrow.",
    "Risk is 56 and QQQ may fall to ٧١٢ next.",
    "Spend €500 on puts.",
    "Buy puts on QQQ.",
    "Consider protective puts.",
    "Dump 100 sh of NVDA.",
    "Shrink the position by 25%.",
    "Reduce NVDA.",
    "Hold off on new entries; QQQ P/C OI is 3.97.",
    "Cut NVDA to a 2% slice of the book.",
    "Exit NVDA.",
    "Get out of NVDA before earnings.",
    "Sell half.",
    "NVDA exposure should be 10 percent lower.",
    "Use a 500 USD hedge.",
    "QQQ could drop to 690 next week.",  # a figure not on the allow-list
]


@pytest.mark.parametrize("answer", REJECT)
def test_b3_curation_rejects_behaviour_digits_and_ungrounded_numbers(answer):
    cfg = dict(curation.load_config(), skip_tiers=[])
    r = curation.curate(CARD, DOC, call_model=lambda p, t, a=answer: a, cfg=cfg)
    assert r["curated"] is False and r["text"] == CARD, (answer, r["reason"])


def test_b3_grounded_why_still_passes():
    cfg = dict(curation.load_config(), skip_tiers=[])
    ok = "QQQ P/C OI at 3.97 is 3.85x its median, so hedging demand is surging."
    r = curation.curate(CARD, DOC, call_model=lambda p, t: ok, cfg=cfg)
    assert r["curated"] is True and ok in r["text"]


def test_b3_orange_and_red_are_never_curated_by_default():
    cfg = curation.load_config()
    assert {"ORANGE", "RED"} <= {str(t).upper() for t in cfg["skip_tiers"]}
    for tier in ("ORANGE", "RED"):
        r = curation.curate(CARD, dict(DOC, tier=tier), call_model=lambda p, t: pytest.fail("model called"), cfg=cfg)
        assert r["curated"] is False and "never curated" in r["reason"]


# ── B4: sessions ────────────────────────────────────────────────────────────────────────────────────────────


def _et(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=sessions.ET)


def test_b4_completed_session_skips_weekends_holidays_and_open_hours():
    assert sessions.completed_session(_et(2026, 10, 30, 16, 30)) == "2026-10-30"
    assert sessions.completed_session(_et(2026, 10, 30, 15, 59)) is None
    assert sessions.completed_session(_et(2026, 10, 31, 17)) is None  # Saturday
    assert sessions.completed_session(_et(2026, 11, 1, 17)) is None  # Sunday (DST end)
    assert sessions.completed_session(_et(2026, 11, 26, 17)) is None  # Thanksgiving
    assert sessions.completed_session(_et(2026, 11, 27, 13, 5)) == "2026-11-27"  # early close 13:00


def test_b4_orange_survives_a_weekend_of_calm_prints():
    prior = None
    a = scoring.compose(_obs(ORANGE_SPEC, T_ORANGE), POLICY, prior=prior, now=T_ORANGE)
    assert a.tier in ("ORANGE", "RED")
    calm = {k: ("CALM", 5) for k in c.CATEGORIES}
    prior = a.to_dict()
    for t in (_et(2026, 10, 30, 16, 30), _et(2026, 10, 31, 10), _et(2026, 11, 1, 10), _et(2026, 11, 1, 18)):
        a = scoring.compose(_obs(calm, t), POLICY, prior=prior, now=t)
        prior = a.to_dict()
    assert a.tier == prior["tier"] and a.tier in ("ORANGE", "RED"), a.hysteresis  # one trading session counted
    assert a.hysteresis.get("below_sessions") == ["2026-10-30"]


def test_b4_episode_resolution_counts_trading_sessions_only(tmp_path):
    p = tmp_path / "ep.json"
    esc.observe({"tier": "ORANGE", "observations": []}, now=T_ORANGE, policy=POLICY, path=p)
    for t in (_et(2026, 10, 30, 16, 30), _et(2026, 10, 31, 12), _et(2026, 11, 1, 12)):
        ev = esc.observe({"tier": "BLUE", "observations": []}, now=t, policy=POLICY, path=p)
    assert ev["event"] != "resolved" and ev["episode"]["below_sessions"] == ["2026-10-30"]


# ── B5: repeats, cap, dedupe, crash ─────────────────────────────────────────────────────────────────────────


def _red_episode(p, now):
    esc.observe(
        {"tier": "RED", "observations": [{"category": "breadth", "state": "STRESS"}]}, now=now, policy=POLICY, path=p
    )


def test_b5a_red_repeats_stop_when_the_market_falls_below_red(tmp_path):
    p = tmp_path / "ep.json"
    _red_episode(p, T_ORANGE)
    assert esc.due_repeats(now=T_ORANGE + timedelta(minutes=16), policy=POLICY, path=p)
    esc.observe({"tier": "YELLOW", "observations": []}, now=T_ORANGE + timedelta(minutes=45), policy=POLICY, path=p)
    for m in (61, 120, 300, 600):
        assert esc.due_repeats(now=T_ORANGE + timedelta(minutes=m), policy=POLICY, path=p) == []


def test_b5b_a_finished_cap_is_capped_not_stalled(tmp_path):
    p = tmp_path / "ep.json"
    _red_episode(p, T_ORANGE)
    ep_id = esc.open_episode(esc.load(p))["id"]
    t = T_ORANGE
    for _ in range(int(POLICY["escalation"]["red_repeat_cap"])):
        t += timedelta(minutes=61)
        esc.record_send(ep_id, now=t, kind="red", ok=True, path=p, policy_escalation=POLICY["escalation"])
    ep = esc.open_episode(esc.load(p))
    assert ep["status"] == "CAPPED"
    assert esc.stalled(now=t + timedelta(hours=5), policy=POLICY, path=p) is None
    assert esc.due_repeats(now=t + timedelta(hours=5), policy=POLICY, path=p) == []
    assert esc.acknowledge(ep_id, actor="operator", channel="test", now=t, path=p)[0] == 200


def test_b5_orange_boundary_repeats_skip_weekends(tmp_path):
    p = tmp_path / "ep.json"
    fri = _et(2026, 10, 30, 16, 31)
    esc.observe({"tier": "ORANGE", "observations": []}, now=fri, policy=POLICY, path=p)
    ep_id = esc.open_episode(esc.load(p))["id"]
    esc.record_send(ep_id, now=fri + timedelta(minutes=60), kind="orange", ok=True, path=p)
    for t in (_et(2026, 10, 31, 5, 1), _et(2026, 11, 1, 5, 1)):
        assert esc.due_repeats(now=t, policy=POLICY, path=p) == []
    assert esc.due_repeats(now=_et(2026, 11, 2, 5, 1), policy=POLICY, path=p)


def test_b5c_dedupe_key_is_enforced_by_the_sent_key_ledger(tmp_path, monkeypatch):
    calls = _transport(monkeypatch)
    led = tmp_path / "keys.json"
    it = {"priority": "P2", "dedupe_minutes": 60, "dedupe_key": "market_risk:YELLOW:2026-10-28:up_from_none"}
    a1 = alerts.deliver("Evaluated 16:30", it, POLICY, dry_run=False, now=T_ORANGE, ledger=led)
    a2 = alerts.deliver("Evaluated 16:45", it, POLICY, dry_run=False, now=T_ORANGE + timedelta(minutes=15), ledger=led)
    a3 = alerts.deliver("Evaluated 17:31", it, POLICY, dry_run=False, now=T_ORANGE + timedelta(minutes=61), ledger=led)
    assert a1["sent"] and a2.get("deduped") and a3["sent"] and len(calls) == 2


class _ProcessKilled(BaseException):
    """A process death mid-send (not an ordinary transport error, which ``deliver`` catches and retries)."""


def test_b5d_crash_mid_send_is_retried_once_and_prior_is_written_first(state, monkeypatch):
    # review of #2383, B5d: at-least-once. The prior and snapshot are written before the drain; a death mid-send leaves
    # the card claimed; the next cycle (after claim_ttl_min) sends it once and records it once — never lost, never
    # repeated every cycle.
    mod = _evaluator()
    seen = {}

    def boom(message, kw):
        seen["latest_existed"] = (state / "data/runtime/market_risk/latest.json").exists()
        seen["snapshot_existed"] = (state / proj.SNAPSHOT_REL).exists()
        raise _ProcessKilled("process killed mid-send")

    _transport(monkeypatch, on_send=boom)
    with pytest.raises(_ProcessKilled):
        _run_apply(mod, T_ORANGE, monkeypatch)
    assert seen == {"latest_existed": True, "snapshot_existed": True}
    calls = _transport(monkeypatch)
    prior = json.loads((state / "data/runtime/market_risk/latest.json").read_text())
    cycle, _ = _run_apply(mod, T_ORANGE + timedelta(minutes=15), monkeypatch, prior=prior)
    initial = [s for s in cycle["sends"] if s["kind"] == "initial" and s.get("sent")]
    assert len(initial) == 1
    calls2 = _transport(monkeypatch)
    cycle, _ = _run_apply(mod, T_ORANGE + timedelta(minutes=30), monkeypatch,
                          prior=json.loads((state / "data/runtime/market_risk/latest.json").read_text()))
    assert not [s for s in cycle["sends"] if s["kind"] == "initial" and s.get("sent")]
    assert not any("ALERT ACTIVE" not in m and "MARKET RISK" in m for m, _ in calls2)


def test_b5_repeat_priority_comes_from_policy(state, monkeypatch):
    mod = _evaluator()
    _transport(monkeypatch)
    import copy

    pol = copy.deepcopy(POLICY)
    pol["escalation"]["repeat_priority"] = "P2"
    monkeypatch.setattr(registry, "evaluate_all", lambda ctx: _obs(ORANGE_SPEC, ctx.now))
    first = mod.run_cycle(T_ORANGE, object(), pol, None, apply=True)  # bootstrap: no episode, no page (PR 2425 r4)
    second = mod.run_cycle(T_ORANGE + timedelta(minutes=1), object(), pol, first["assessment"], apply=True)
    later = mod.run_cycle(T_ORANGE + timedelta(minutes=62), object(), pol, second["assessment"], apply=True)
    reps = [s for s in later["sends"] if s["kind"] != "initial"]
    assert reps and all(s["intent"]["priority"] == "P2" for s in reps)


def test_dry_run_leaves_no_temp_directories(state, tmp_path, monkeypatch):
    mod = _evaluator()
    monkeypatch.setattr(registry, "evaluate_all", lambda ctx: _obs(ORANGE_SPEC, ctx.now))
    mod.run_cycle(T_ORANGE, object(), POLICY, None, apply=False)
    assert list((tmp_path / "tmp").glob("mre-dry-*")) == []
    assert not (state / proj.SNAPSHOT_REL).exists()


# ── B6 / M1: reader ─────────────────────────────────────────────────────────────────────────────────────────


class _Cur:
    def __init__(self, rows_by_sql, log):
        self.rows_by_sql, self.log, self._rows = rows_by_sql, log, []
        self.description = None

    def execute(self, sql, params=None):
        self.log.append((sql, params))
        for frag, rows in self.rows_by_sql.items():
            if frag in sql:
                self._rows = rows
                return
        self._rows = []

    def fetchall(self):
        return self._rows

    def close(self):
        pass


def test_m1_fred_and_earnings_queries_filter_on_knowability():
    from scripts.lib.market_risk import reader as rd

    log = []
    r = rd.PgReader(conn_factory=lambda: None)
    r._rows = lambda sql, params: log.append((sql, params)) or []
    end = datetime(2026, 10, 29, 14, 15, tzinfo=timezone.utc)
    r.fred(["DTWEXBGS"], observations=400, end=end)
    sql, params = log[-1]
    assert "fetched_at <= %s" in sql and end in params
    r.earnings_calendar(start=end, end=end + timedelta(days=10), now=end)
    sql, params = log[-1]
    # knowable at the evaluation instant, not at the end of the forward window
    assert "earnings_updated_at <= %s" in sql and params[-1] == end


def test_b6_fred_vixcls_beats_the_1605_snapshot_and_is_labelled():
    from datetime import date

    from scripts.lib.market_risk import reader as rd

    r = rd.PgReader(conn_factory=lambda: None)
    d = date(2026, 10, 29)
    snap_at = datetime(2026, 10, 29, 20, 5, tzinfo=timezone.utc)
    r._rows = lambda sql, params: [{"d": d, "value": 16.59, "created_at": snap_at}]
    r.fred = lambda series, observations, end: [{"observation_date": "2026-10-29", "value": 17.20}]
    out = r._vix_closes(start=snap_at - timedelta(days=3), end=snap_at + timedelta(days=3))
    assert out[-1]["close"] == 17.20 and out[-1]["source"] == "fred_economic_series:VIXCLS"
    r.fred = lambda series, observations, end: []
    out = r._vix_closes(start=snap_at - timedelta(days=3), end=snap_at + timedelta(days=3))
    assert out[-1]["close"] == 16.59 and out[-1]["provisional"] is True and "1605_snapshot" in out[-1]["source"]


def test_fred_ingest_never_rewrites_first_fetched_at():
    src = (ROOT / "scripts/external_market_data_ingest.py").read_text()
    upsert = src[src.index("INSERT INTO fred_economic_series") :][:300]
    assert "fetched_at" not in upsert.split("DO UPDATE SET", 1)[1].split('"""')[0]


# ── M2 guards ───────────────────────────────────────────────────────────────────────────────────────────────


def test_m2_collector_vol_proxy_failure_never_aborts(monkeypatch):
    import market_regime_collector as mrc

    monkeypatch.setattr(mrc, "_yahoo_last", lambda sym: (_ for _ in ()).throw(TimeoutError("no network")))

    class Conn:
        def cursor(self):
            class C:
                def execute(self, *a):
                    raise RuntimeError("relation market_quotes does not exist")

            return C()

        def rollback(self):
            pass

    out, missing = mrc.collect_vol_complex("snap", conn=Conn(), vix=None)
    assert out == [] and any(m.startswith("vol_proxy_unavailable") for m in missing)


def test_m2_torn_files_never_crash_readers(tmp_path):
    p = tmp_path / "episodes.json"
    p.write_text('{"episodes": [')
    with pytest.raises(esc.EpisodeStoreCorrupt):
        esc.load(p)
    api = (ROOT / "scripts/api_v2.py").read_text()
    block = api[api.index('"/api/v2/market-risk/latest"') :][:1400]
    assert "episode ledger unreadable" in block
    bad = tmp_path / "gate.yaml"
    bad.write_text("market_risk_gate: [unclosed\n")
    assert cio_context.load_gate_config(bad) == {}
    mod = _evaluator()
    lp = tmp_path / "latest.json"
    lp.write_text("{torn")
    assert mod._read_prior(lp) is None


def test_m2_brief_and_digest_tier_lines_fail_safe(monkeypatch):
    from scripts.lib import advice_digest

    monkeypatch.setattr(cio_context, "load_market_risk", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert advice_digest.market_risk_header().startswith("Market risk: not yet evaluated")


# ── M3 / M4 ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_m3_book_line_has_budget_names_only_and_safe_reasons():
    a = {
        "tier": "ORANGE",
        "score": 66,
        "contributors": [],
        "portfolio": {
            "budget_breaches": [{"scope": "acct", "budget": "max_ai_basket_pct", "actual": 52, "limit": 35}],
            "drivers": [
                {"symbol": "ETF-A", "stop_distance_pct": 4.1, "reason": "top holdings report"},
                {"symbol": "STOCK-B", "stop_distance_pct": 6.0, "reason": "trim 30% before earnings"},
            ],
        },
    }
    card = alerts.render(a)
    book = [ln for ln in card.splitlines() if ln.startswith("Your book")][0]
    assert "max_ai_basket_pct" in book and "52" not in book and "35" not in book
    assert "(top holdings report)" in book and "trim" not in book.lower()


def test_m4_gate_hold_is_not_a_material_change():
    from scripts.lib import cio_opportunity_store as st

    base = {"symbol": "AAA", "stance": "ADD", "type": "new_position", "conviction": 80, "rank": 3}
    held = dict(
        base,
        stance="HOLD",
        market_risk_gate={"action": "hold", "tier": "ORANGE"},
        stance_suppressed={"from": "ADD", "reason": "market_risk_gate: market risk ORANGE"},
    )
    assert st.material_changes(base, held, {}) == []
    assert st.material_changes(held, base, {}) == []
    assert st.material_changes(base, dict(base, stance="TRIM"), {})  # a real stance change still versions


def test_b3_non_ascii_digits_are_refused_by_their_own_rule():
    cfg = dict(curation.load_config(), skip_tiers=[])
    r = curation.curate(CARD, DOC, call_model=lambda p, t: "Pressure could build toward ٧١٢ on QQQ.", cfg=cfg)
    assert r["curated"] is False and r["reason"] == "non-ASCII digits rejected" and r["rejected"] == ["١", "٢", "٧"]
