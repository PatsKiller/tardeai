"""Round-3 review of the Market Risk Engine (#2383): outbox and episode-store hardening, GREEN must-measure, ACK CSRF.

Every probe in ~/agent_scratch/r3probes (p_failwedge, p_quar, p_ack2 A/B/C, p_outbox runs 1-2, p_conc, p_green2) is a
regression test here. Hermetic: temp paths only, telegram stubbed, no DB, no network.
"""

from __future__ import annotations

import itertools
import json
import sys
import threading
import types
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.lib.market_risk import alerts, contract as c, escalation as E, explain, scoring  # noqa: E402
from scripts.lib.market_risk.policy import load_policy  # noqa: E402

ET = ZoneInfo("America/New_York")
P = load_policy()
T0 = datetime(2026, 11, 3, 10, 0, tzinfo=ET)


class _Crash(BaseException):
    pass


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A stubbed transport, the evaluator module, and a ``cyc(now, tier, prior)`` driver (the probes' harness)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("mre_eval_r3", ROOT / "scripts" / "market_risk_evaluate.py")
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    sent: list[str] = []
    mode = {"ok": True, "crash_after_send": False}

    def send_telegram(msg, **kw):
        if not mode["ok"]:
            return False
        sent.append(msg.splitlines()[0][:60])
        if mode["crash_after_send"]:
            mode["crash_after_send"] = False
            raise _Crash("killed after transport accepted")
        return True

    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = send_telegram
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    d = tmp_path / "s"
    d.mkdir()

    def mk(now, tier):
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

    def cyc(now, tier, prior):
        obs = mk(now, tier)
        monkeypatch.setattr(
            ev,
            "evaluate",
            lambda n, r, p, pr, portfolio=None, obs=obs: explain.explain(
                scoring.apply_uplift(scoring.compose(obs, p, prior=pr, now=n), None, p), p
            ),
        )
        got = {}
        try:
            ev.run_cycle(
                now,
                None,
                P,
                prior,
                apply=True,
                episodes_path=d / "ep.json",
                ledger_path=d / "keys.json",
                on_assessed=lambda doc: got.setdefault("d", json.loads(json.dumps(doc, default=str))),
                call_model=lambda p, t: "",
            )
        except _Crash:
            pass
        return got.get("d", prior)

    return types.SimpleNamespace(ev=ev, sent=sent, mode=mode, d=d, cyc=cyc, mk=mk)


# ── H1: a Telegram outage never wedges a card (p_failwedge.py) ───────────────────────────────────────────────────
def test_h1_three_hour_outage_then_recovery(rig):
    prior = rig.cyc(T0, "YELLOW", None)
    prior = rig.cyc(T0 + timedelta(minutes=15), "RED", prior)
    for i in range(2, 30):
        rig.mode["ok"] = not (2 <= i <= 11)
        prior = rig.cyc(T0 + timedelta(minutes=15 * i), "RED", prior)
    ep = E.open_episode(E.load(rig.d / "ep.json"))
    keys = json.loads((rig.d / "keys.json").read_text())["keys"]
    assert ep["repeats"] >= 6, ep["repeats"]
    assert "failed" not in {v["status"] for v in keys.values()}
    assert E.stalled(now=T0 + timedelta(hours=7, minutes=15), policy=P, path=rig.d / "ep.json") is None


def test_h1_retry_backoff_is_never_terminal(tmp_path):
    led = tmp_path / "k.json"
    now = T0
    alerts.outbox_put({"key": "k", "text": "x", "intent": {"dedupe_minutes": 0}, "kind": "initial"}, now=now, path=led)
    for i in range(12):
        assert alerts.claim("k", 0, now=now, path=led)
        alerts.settle("k", False, path=led, now=now)
        rec = json.loads(led.read_text())["keys"]["k"]
        assert rec["status"] == "pending"
        now = datetime.fromisoformat(rec.get("next_attempt_at") or now.isoformat()) + timedelta(seconds=1)
    assert alerts.claim("k", 0, now=now, path=led)


def test_h1_legacy_failed_entry_is_retried(tmp_path):
    led = tmp_path / "k.json"
    led.write_text(
        json.dumps(
            {
                "schema": "MarketRiskSentKeys@v1",
                "keys": {
                    "k": {
                        "at": T0.isoformat(),
                        "status": "failed",
                        "text": "x",
                        "intent": {"dedupe_minutes": 0},
                        "attempts": 8,
                    }
                },
            }
        )
    )
    assert [e["key"] for e in alerts.outbox_due(now=T0, path=led)] == ["k"]
    assert alerts.claim("k", 0, now=T0, path=led)


# ── H2: a torn ledger with a pending entry never crash-loops (p_quar.py) ─────────────────────────────────────────
def test_h2_orphaned_outbox_entry_after_quarantine(rig):
    prior = rig.cyc(T0, "YELLOW", None)
    rig.mode["ok"] = False
    prior = rig.cyc(T0 + timedelta(minutes=15), "RED", prior)
    (rig.d / "ep.json").write_text('{"episodes": [ {"id": ')
    rig.mode["ok"] = True
    for i in range(2, 7):
        n = len(rig.sent)
        prior = rig.cyc(T0 + timedelta(minutes=15 * i), "RED", prior)  # raises on a crash
        if i == 2:
            assert any("MARKET RISK RED" in m for m in rig.sent[n:])
    assert sum("MARKET RISK RED" in m for m in rig.sent) == 1
    assert E.record_send("no-such-episode", now=T0, kind="red", ok=True, path=rig.d / "ep.json") is None


# ── H3: a stale below_open never reopens an ACK (p_ack2.py A, B) ─────────────────────────────────────────────────
def _a(tier, stress=("breadth",)):
    return {"tier": tier, "score": 80, "observations": [{"category": k, "state": "STRESS"} for k in stress]}


def test_h3_case_a_dip_and_return_while_open(tmp_path):
    d, t = tmp_path / "a.json", datetime(2026, 11, 2, 10, 0, tzinfo=ET)
    E.observe(_a("RED"), now=t, policy=P, path=d)
    E.observe(_a("YELLOW"), now=t + timedelta(minutes=15), policy=P, path=d)
    E.observe(_a("RED"), now=t + timedelta(minutes=30), policy=P, path=d)
    assert E.acknowledge(None, actor="tailnet:op", channel="cc", now=t + timedelta(minutes=35), path=d)[0] == 200
    r = E.observe(_a("RED"), now=t + timedelta(minutes=45), policy=P, path=d)
    assert r["event"] == "unchanged" and r["episode"]["status"] == "ACKED"
    assert E.due_repeats(now=t + timedelta(hours=2), policy=P, path=d) == []


def test_h3_case_b_upgrade_then_ack(tmp_path):
    d, t = tmp_path / "b.json", datetime(2026, 11, 2, 10, 0, tzinfo=ET)
    E.observe(_a("ORANGE"), now=t, policy=P, path=d)
    E.observe(_a("YELLOW"), now=t + timedelta(minutes=15), policy=P, path=d)
    assert E.observe(_a("RED"), now=t + timedelta(minutes=30), policy=P, path=d)["event"] == "upgraded"
    E.acknowledge(None, actor="tailnet:op", channel="cc", now=t + timedelta(minutes=35), path=d)
    r = E.observe(_a("RED"), now=t + timedelta(minutes=45), policy=P, path=d)
    assert r["event"] == "unchanged" and r["episode"]["status"] == "ACKED"


def test_h3_return_while_open_clears_below_open_before_a_cap(tmp_path):
    # dip and return while OPEN, then the RED repeats run out (CAPPED): the next RED evaluation must not "reopen"
    # on the stale dip
    d, t = tmp_path / "cap.json", datetime(2026, 11, 2, 10, 0, tzinfo=ET)
    E.observe(_a("RED"), now=t, policy=P, path=d)
    E.observe(_a("YELLOW"), now=t + timedelta(minutes=15), policy=P, path=d)
    E.observe(_a("RED"), now=t + timedelta(minutes=30), policy=P, path=d)
    ep = E.open_episode(E.load(d))
    for i in range(12):
        E.record_send(
            ep["id"],
            now=t + timedelta(minutes=45 + i),
            kind="red",
            ok=True,
            path=d,
            policy_escalation=P["escalation"],
            key=f"r{i}",
        )
    assert E.open_episode(E.load(d))["status"] == "CAPPED"
    r = E.observe(_a("RED"), now=t + timedelta(hours=2), policy=P, path=d)
    assert r["event"] == "unchanged" and r["episode"]["status"] == "CAPPED"


# ── H5: an ACK racing an evaluator write is never lost (p_ack2.py C) ─────────────────────────────────────────────
def test_h5_case_c_ack_between_read_and_write(tmp_path, monkeypatch):
    d, t = tmp_path / "c.json", datetime(2026, 11, 2, 10, 0, tzinfo=ET)
    E.observe(_a("RED"), now=t, policy=P, path=d)
    orig, state = E.load_for_write, {}

    def slow_load(path=None):
        data = orig(path)
        if not state.get("done"):
            state["done"] = True
            assert (
                E.acknowledge(None, actor="tailnet:op", channel="cc", now=t + timedelta(minutes=14), path=d)[0] == 200
            )
        return data

    monkeypatch.setattr(E, "load_for_write", slow_load)
    E.observe(_a("RED"), now=t + timedelta(minutes=15), policy=P, path=d)
    monkeypatch.setattr(E, "load_for_write", orig)
    ep = E.open_episode(E.load(d))
    assert ep["status"] == "ACKED" and len(ep["acks"]) == 1
    assert not E.due_repeats(now=t + timedelta(minutes=16), policy=P, path=d)


# ── H4: no "acknowledgment required" repeat after an ACK (p_outbox.py runs 1, 2) ──────────────────────────────────
@pytest.mark.parametrize("fail_window,crash_at", [((3, 5), None), (None, 3)])
def test_h4_no_repeat_after_ack(rig, fail_window, crash_at):
    prior = rig.cyc(T0, "YELLOW", None)
    acked_at = None
    for i in range(1, 14):
        t = T0 + timedelta(minutes=15 * i)
        rig.mode["ok"] = not (fail_window and fail_window[0] <= i <= fail_window[1])
        if crash_at == i:
            rig.mode["crash_after_send"] = True
        if i == 4:
            assert E.acknowledge(None, actor="tailnet:op", channel="cc", now=t, path=rig.d / "ep.json")[0] == 200
            acked_at = len(rig.sent)
        prior = rig.cyc(t, "RED", prior)
    assert not [m for m in rig.sent[acked_at:] if "acknowledgment required" in m], rig.sent


# ── H5: two concurrent evaluators send one RED initial (p_conc.py) ───────────────────────────────────────────────
def test_h5_concurrent_evaluators_send_one_initial(rig, monkeypatch):
    prior = rig.cyc(T0, "YELLOW", None)
    t = T0 + timedelta(minutes=15)
    obs = rig.mk(t, "RED")
    monkeypatch.setattr(
        rig.ev,
        "evaluate",
        lambda n, r, p, pr, portfolio=None: explain.explain(
            scoring.apply_uplift(scoring.compose(obs, p, prior=pr, now=n), None, p), p
        ),
    )
    errs = []

    def one():
        try:
            rig.ev.run_cycle(
                t,
                None,
                P,
                prior,
                apply=True,
                episodes_path=rig.d / "ep.json",
                ledger_path=rig.d / "keys.json",
                on_assessed=lambda doc: None,
                call_model=lambda p, t: "",
            )
        except Exception as x:  # noqa: BLE001
            errs.append(repr(x))

    th = [threading.Thread(target=one) for _ in range(2)]
    [x.start() for x in th]
    [x.join() for x in th]
    assert not errs
    assert sum("MARKET RISK RED" in m for m in rig.sent) == 1
    assert len(E.load(rig.d / "ep.json")["episodes"]) == 1


def test_h5_stale_claim_retries_back_off(tmp_path):
    # a claim that never settles (the send keeps killing the process) is retried after 10, then 20, then 40 minutes
    led = tmp_path / "k.json"
    alerts.outbox_put({"key": "k", "text": "x", "intent": {"dedupe_minutes": 0}}, now=T0, path=led)
    assert alerts.claim("k", 0, now=T0, path=led, claim_ttl_min=10)
    last, gaps = T0, []
    for _ in range(3):
        step = timedelta(minutes=1)
        while not alerts.claim("k", 0, now=last + step, path=led, claim_ttl_min=10):
            step += timedelta(minutes=1)
        gaps.append(int(step.total_seconds() // 60))
        last = last + step
    assert gaps == [10, 20, 40], gaps


def test_h5_evaluator_apply_takes_a_process_lock(tmp_path, monkeypatch):
    import fcntl
    import importlib.util
    import os

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    spec = importlib.util.spec_from_file_location("mre_eval_r3l", ROOT / "scripts" / "market_risk_evaluate.py")
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    lp = ev.state_dir() / "evaluate.lock"
    lp.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lp), os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        monkeypatch.setattr(ev, "production_reader", lambda: (_ for _ in ()).throw(AssertionError("must not run")))
        assert ev.main(["--apply", "--no-portfolio"]) == 0
    finally:
        os.close(fd)


# ── M-B: GREEN needs the must-measure categories and never fires on bootstrap (p_green2.py) ───────────────────────
def _gobs(spec, now):
    return [
        c.CategoryObservation(
            category=k,
            state=spec.get(k, ("UNKNOWN", None))[0],
            score=spec.get(k, ("UNKNOWN", None))[1],
            observed_at=now.isoformat(),
            headline=k,
            reason_unknown=("x" if k not in spec else None),
        )
        for k in c.CATEGORIES
    ]


def test_mb_green_requires_must_measure_or_high_coverage():
    must = set(P["tiers"]["green"]["must_measure"])
    cats = list(c.CATEGORIES)
    for r in range(0, 5):
        for unk in itertools.combinations(cats, r):
            known = [k for k in cats if k not in unk]
            spec = {k: (("IMPROVING", 0) if i < 3 else ("CALM", 0)) for i, k in enumerate(known)}
            pr = {"tier": "NONE", "market_tier": "NONE", "hysteresis": {"last_stress_at": None}}
            for j in range(3):
                a = scoring.compose(
                    _gobs(spec, T0 + timedelta(minutes=15 * j)), P, prior=pr, now=T0 + timedelta(minutes=15 * j)
                )
                pr = a.to_dict()
            if a.tier == "GREEN" and must & set(unk):
                assert a.hysteresis["coverage"] >= 0.85, (unk, a.hysteresis["coverage"])


def test_mb_no_green_on_bootstrap():
    spec = {k: ("IMPROVING", 0) for k in ("volatility", "macro_credit", "breadth")}
    spec.update(
        {k: ("CALM", 0) for k in ("technical", "cross_asset", "event", "seasonal", "options_flow", "extended_hours")}
    )
    assert scoring.compose(_gobs(spec, T0), P, prior=None, now=T0).tier != "GREEN"


# ── M-C: the ACK route enforces same-origin CSRF ─────────────────────────────────────────────────────────────────
def test_mc_ack_route_refuses_cross_site(monkeypatch, tmp_path):
    import api_v2
    from lib import cc_auth

    monkeypatch.setattr(api_v2, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("MARKET_RISK_EPISODES_PATH", str(tmp_path / "ep.json"))
    monkeypatch.setattr(cc_auth, "command_csrf_check", lambda cfg, m, p: (False, "cross-site"))
    monkeypatch.setattr(cc_auth, "current_principal", lambda: "tailnet:op")
    code, resp = api_v2.handle("/api/v2/market-risk/ack", "POST", {}, {})
    assert code == 403 and "cross-site" in json.dumps(resp)


# ── L1 / L3: account breaches ────────────────────────────────────────────────────────────────────────────────────
def _yellow():
    a = scoring.compose(_gobs({"options_flow": ("STRESS", 85), "technical": ("STRESS", 70)}, T0), P, now=T0)
    a.market_tier = a.tier = "YELLOW"
    return a


def test_l1_account_breach_without_book_breach_never_lifts():
    port = c.PortfolioContext(
        vulnerability=60.0,
        budget_breaches=({"budget": "growth_style_pct", "ratio": 2.0, "scope": "acct-a", "book_share": 0.9},),
    )
    assert scoring.apply_uplift(_yellow(), port, P).tier == "YELLOW"
    port = c.PortfolioContext(
        vulnerability=60.0,
        budget_breaches=(
            {"budget": "growth_style_pct", "ratio": 1.1, "scope": "book"},
            {"budget": "growth_style_pct", "ratio": 2.0, "scope": "acct-a", "book_share": 0.9},
        ),
    )
    assert scoring.apply_uplift(_yellow(), port, P).tier == "ORANGE"


def test_l3_card_labels_account_breaches():
    doc = {
        "tier": "YELLOW",
        "score": 50,
        "as_of": T0.isoformat(),
        "contributors": [],
        "observations": [],
        "portfolio": {"budget_breaches": [{"budget": "unprotected_pct", "scope": "acct-b", "ratio": 4.4}]},
    }
    card = alerts.render(doc)
    assert "over budget in one account: unprotected_pct" in card and "4.4" not in card


# ── data-feed review: the reader is read-only from its FIRST query ───────────────────────────────────────────────
class _FakeConn:
    """Mimics Postgres session semantics: ``set_session(readonly=True)`` before the first statement makes the first
    transaction read-only; ``SET default_transaction_read_only`` only affects LATER transactions."""

    def __init__(self, has_set_session=True):
        self.readonly_session = False
        self.default_ro = False
        self.in_tx = False
        self.tx_ro = None
        self.log = []
        if not has_set_session:
            self.set_session = None

    def set_session(self, readonly=False):  # noqa: D401 — psycopg2 API
        assert not self.in_tx, "set_session inside a transaction"
        self.readonly_session = readonly

    def cursor(self):
        conn = self

        class Cur:
            description = [("transaction_read_only",)]

            def execute(self, sql, params=None):
                if not conn.in_tx:
                    conn.in_tx, conn.tx_ro = True, conn.readonly_session or conn.default_ro
                if sql.startswith("SET default_transaction_read_only"):
                    conn.default_ro = True
                conn.log.append(sql)
                self._row = ("on" if conn.tx_ro else "off",)

            def fetchall(self):
                return [self._row]

            def fetchone(self):
                return self._row

            def close(self):
                pass

        return Cur()

    def close(self):
        pass


def test_reader_is_read_only_from_the_first_query():
    from scripts.lib.market_risk.reader import PgReader

    conn = _FakeConn()
    r = PgReader(conn_factory=lambda: conn)
    assert r._rows("SHOW transaction_read_only", []) == [{"transaction_read_only": "on"}]


def test_reader_refuses_a_connection_it_cannot_make_read_only():
    from scripts.lib.market_risk.reader import PgReader

    class Bare:  # neither psycopg2 set_session nor psycopg 3 read_only
        closed = False

        def cursor(self):
            raise AssertionError("must not be queried")

        def close(self):
            Bare.closed = True

    r = PgReader(conn_factory=Bare)
    with pytest.raises(RuntimeError):
        r._rows("SHOW transaction_read_only", [])
    assert Bare.closed
