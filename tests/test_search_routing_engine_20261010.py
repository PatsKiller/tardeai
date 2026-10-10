"""Search source routing engine (2026-10-10). Hermetic: temp state roots, injected transports, fixed clocks.

Operator: "$20 maximum a month on Brave ... prioritize the search for scalps that are about to fire ... a
mature engine and rules about which source to use for what so we're conserving the spend."

Gates: policy validator, table-driven routing decisions, dollar budget math, the scalp-priority classifier,
the shared cache, the dry run (proved: zero Brave requests, nothing written), the free lane never naming a
Brave engine, the incident fan-in source, and the rerouted callers.
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import scalp_priority as sp  # noqa: E402
from scripts.lib import search_budget, search_quality, search_router, search_spend  # noqa: E402
from scripts.lib.search_routing_policy import POLICY_PATH, load_policy, validate_policy  # noqa: E402

COVERS = [
    "scripts/lib/search_router.py",
    "scripts/lib/search_routing_policy.py",
    "scripts/lib/search_spend.py",
    "scripts/lib/search_quality.py",
    "scripts/lib/scalp_priority.py",
    "scripts/search_spend_report.py",
]

RTH = datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc)        # Tue 10:00 ET
PRE = datetime(2026, 10, 13, 9, 30, tzinfo=timezone.utc)        # Tue 05:30 ET
SAT = datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc)        # Saturday


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    for k in ("SEARCH_ROUTING_ENGINE", "SEARCH_ROUTING_DRY_RUN", "BRAVE_ROUTER_LIVE", "BRAVE_ROUTER_ENABLED",
              "BRAVE_SEARCH_API_KEY", "SEARCH_BUDGET_BRAVE_DAILY", "SEARCH_BUDGET_BRAVE_MONTHLY"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def policy():
    return load_policy()


# ── fakes ─────────────────────────────────────────────────────────────────────


class Free:
    """SearXNG transport fake: returns ``rows`` and records every call (engines included)."""

    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    def __call__(self, q, *, categories, limit, timeout, engines=None):
        self.calls.append({"q": q, "categories": categories, "engines": engines})
        return list(self.rows)


class Paid:
    """Brave HTTP transport fake: counts requests — the proof a dry run spends nothing."""

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [
            {"title": "ACME jumps on FDA approval", "url": "https://www.reuters.com/a", "description": "ACME", "age": "1 hour ago"},
            {"title": "ACME FDA nod", "url": "https://www.cnbc.com/b", "description": "ACME shares", "age": "2 hours ago"},
        ]
        self.requests = 0

    def __call__(self, url, headers):
        self.requests += 1
        return ({"results": self.rows, "web": {"results": self.rows}}, {})


THIN = [{"title": "something else", "url": "https://blog.example.org/x", "snippet": "nothing"}]
GOOD_NEWS = [
    {"title": "ACME soars after FDA approval", "url": "https://www.reuters.com/n1", "snippet": "ACME", "published": "2026-10-13T12:00:00+00:00"},
    {"title": "ACME stock jumps", "url": "https://www.cnbc.com/n2", "snippet": "ACME", "published": "2026-10-13T11:00:00+00:00"},
]
GOOD_WEB = [
    {"title": "Dell earnings growth outlook", "url": "https://www.reuters.com/w1", "snippet": "Dell stock outlook growth drivers"},
    {"title": "Dell outlook growth", "url": "https://www.cnbc.com/w2", "snippet": "growth drivers outlook for Dell"},
    {"title": "Dell growth drivers", "url": "https://finance.yahoo.com/w3", "snippet": "outlook growth"},
]


def _route(tmp_path, policy, *, caller, query, symbol=None, free=None, paid=None, now=RTH, dry=False,
           candidates=None, scalp_rows=None, db=None, enabled=True, **kw):
    return search_router.route(
        search_router.SearchRequest(query=query, caller=caller, symbol=symbol, candidates=candidates or []),
        policy=policy, clock=lambda: now, root=tmp_path / "state", enabled=enabled, dry_run=dry,
        free_transport=free or Free(), paid_transport=paid, db_query=db or (lambda *a, **k: []),
        scalp_rows=scalp_rows if scalp_rows is not None else ([], None), **kw)


# ── 1. policy + validator ───────────────────────────────────────────────────


def test_the_committed_policy_validates_against_the_registry():
    pol = load_policy()
    assert pol["budget"]["working_target_usd"] == 15.0 and pol["budget"]["local_ceiling_usd"] == 18.0
    assert pol["budget"]["non_priority_stop_usd"] == 12.0 and pol["pricing"]["usd_per_request"] == 0.005
    reg = json.loads((ROOT / "config" / "data_source_authority.json").read_text())
    ws = next(d for d in reg["domains"] if d["domain"] == "web_search")
    assert ws["routing_policy"] == "config/search_routing_policy.json"


@pytest.mark.parametrize("mutate,needle", [
    (lambda p: p["free_lane"]["searxng"]["never_engines"].remove("braveapi"), "braveapi"),
    (lambda p: p["free_lane"]["searxng"]["engines"]["web"].append("braveapi"), "never-engine"),
    (lambda p: p["budget"]["pools"]["scalp"].__setitem__("share", 0.9), "sum to 1.0"),
    (lambda p: p["budget"].__setitem__("working_target_usd", 19.0), "non_priority_stop <= working_target"),
    (lambda p: p["classes"]["research"].__setitem__("pool", "nope"), "undeclared"),
    (lambda p: p["callers"].__setitem__("x", "no_such_class"), "caller x"),
    (lambda p: p["classes"]["gap_fill"].__setitem__("free_tiers", ["brave"]), "not a tier-1 source"),
    (lambda p: p["priority"]["scalp"]["eligible_decisions"].append("AVOID"), "AVOID"),
    (lambda p: p["budget"]["pools"]["other"].__setitem__("month_line", "local_ceiling_usd"), "background pool"),
    (lambda p: p["budget"]["pools"]["scalp"].__setitem__("may_borrow_unused_daily_from", ["operator"]), "reserve pool"),
])
def test_validator_refuses_a_broken_policy(policy, mutate, needle):
    bad = copy.deepcopy(policy)
    mutate(bad)
    errors = validate_policy(bad)
    assert any(needle in e for e in errors), errors


def test_authority_gate_reports_an_invalid_routing_policy(monkeypatch, tmp_path):
    import scripts.check_data_source_authority as gate
    auth = json.loads((ROOT / "config" / "data_source_authority.json").read_text())
    assert gate.check_routing_policy(auth) == []
    bad = json.loads(POLICY_PATH.read_text())
    bad["budget"]["local_ceiling_usd"] = 25.0
    (tmp_path / "p.json").write_text(json.dumps(bad))
    for d in auth["domains"]:
        if d["domain"] == "web_search":
            d["routing_policy"] = str(tmp_path / "p.json")
    monkeypatch.setattr(gate, "PROJECT_ROOT", Path("/"))
    f = gate.check_routing_policy(auth)
    assert f and f[0]["check"] == "ROUTING_POLICY_INVALID"


# ── 2. routing decisions, table-driven ──────────────────────────────────────


ROUTING_TABLE = [
    # caller, query, symbol, free rows, paid rows?, armed?, expected (ok, reason prefix, tier, class, brave requests)
    ("governed_research_producer", "Dell stock outlook growth drivers 2026", "DELL", GOOD_WEB, True,
     (True, "FREE_SUFFICIENT", 1, "research", 0)),
    ("governed_research_producer", "Dell stock outlook growth drivers 2026", "DELL", THIN, True,
     (True, "PAID_OK", 2, "research", 1)),
    ("gap_resolver", "Dell stock outlook growth drivers 2026", None, THIN, True,
     (True, "FREE_INSUFFICIENT:PAID_NOT_ALLOWED_FOR_CLASS", 1, "gap_fill", 0)),
    ("gap_resolver", "Dell stock outlook growth drivers 2026", None, [], True,
     (False, "NO_COVERAGE:declared_gap", 3, "gap_fill", 0)),
    ("research_quality_escalate", "q about dell growth", None, [], True,
     (False, "NO_COVERAGE:say_so", 3, "quality_escalation", 0)),
    ("aegis_social_sentiment", "ACME stock sentiment reddit", "ACME", THIN, True,
     (True, "FREE_INSUFFICIENT:PAID_NOT_ALLOWED_FOR_CLASS", 1, "social_discovery", 0)),
    ("web_research", "Dell stock outlook growth drivers 2026", None, THIN, True,
     (True, "PAID_OK", 2, "operator", 1)),
    ("web_research", "Dell stock outlook growth drivers 2026", None, THIN, False,
     (True, "FREE_INSUFFICIENT:PAID_NOT_ARMED", 1, "operator", 0)),
    ("hermes_momentum_catalyst", "ACME stock latest news", "ACME", GOOD_NEWS, True,
     (True, "FREE_SUFFICIENT", 1, "catalyst_confirmation", 0)),
    ("nobody_declared", "anything", None, GOOD_WEB, True,
     (False, "UNKNOWN_CALLER", 3, "", 0)),
]


@pytest.mark.parametrize("caller,query,symbol,free_rows,armed,expect", ROUTING_TABLE)
def test_routing_decisions(tmp_path, policy, monkeypatch, caller, query, symbol, free_rows, armed, expect):
    ok, reason, tier, cls, brave = expect
    paid = Paid() if armed else None
    resp = _route(tmp_path, policy, caller=caller, query=query, symbol=symbol, free=Free(free_rows), paid=paid,
                  api_key="fixture")
    assert (resp.ok, resp.tier) == (ok, tier), resp.reason
    assert resp.reason.startswith(reason), resp.reason
    assert resp.question_class == cls
    assert (paid.requests if paid else 0) == brave
    if brave:
        assert resp.cost_usd == pytest.approx(0.005)


def test_scalp_about_to_fire_is_promoted_and_gets_paid_first_claim(tmp_path, policy):
    paid = Paid()
    resp = _route(tmp_path, policy, caller="hermes_momentum_catalyst", query="ACME stock premarket catalyst",
                  symbol="ACME", free=Free(THIN), paid=paid, api_key="fixture",
                  candidates=[{"symbol": "ACME", "decision": "MANUAL_REVIEW", "score": 37}])
    assert resp.question_class == "scalp_priority" and resp.pool == "scalp"
    assert resp.priority["priority"] is True and resp.tier == 2 and paid.requests == 1
    led = search_budget.ledger_doc(root=tmp_path / "state")
    assert led["providers"]["brave"]["callers"]["2026-10"] == {"route.scalp": 1}
    # The same name again inside 30 minutes is not re-promoted, and is answered from the shared cache.
    later = _route(tmp_path, policy, caller="hermes_momentum_catalyst", query="ACME stock premarket catalyst",
                   symbol="ACME", free=Free(THIN), paid=paid, now=RTH + timedelta(minutes=10), api_key="fixture",
                   candidates=[{"symbol": "ACME", "decision": "MANUAL_REVIEW", "score": 37}])
    assert later.question_class == "catalyst_confirmation" and later.cache_hit and paid.requests == 1


def test_every_live_route_writes_one_receipt_with_class_tier_reason_cost_cache(tmp_path, policy):
    _route(tmp_path, policy, caller="governed_research_producer", query="Dell stock outlook growth drivers 2026",
           symbol="DELL", free=Free(THIN), paid=Paid(), api_key="fixture")
    rows = [json.loads(x) for x in search_budget.routing_receipts_path(tmp_path / "state").read_text().splitlines()]
    assert len(rows) == 1
    r = rows[0]
    for k in ("class", "tier", "reason", "cost_usd", "cache_hit", "pool", "latency_ms", "quality", "units_free"):
        assert k in r
    assert (r["class"], r["tier"], r["cost_usd"], r["cache_hit"]) == ("research", 2, 0.005, False)


# ── 3. dry run: proved zero Brave requests, nothing written ─────────────────


def test_dry_run_reaches_no_provider_and_writes_nothing(tmp_path, policy):
    free, paid = Free(THIN), Paid()
    resp = _route(tmp_path, policy, caller="web_research", query="Dell stock outlook growth drivers 2026",
                  free=free, paid=paid, dry=True, api_key="fixture")
    assert resp.dry_run and resp.reason == "DRY_RUN"
    assert paid.requests == 0 and free.calls == []
    assert [p["source"] for p in resp.plan] == ["cache", "searxng", "brave"]
    assert resp.plan[-1]["budget_preview"] == "OK"
    state = tmp_path / "state"
    assert not search_budget.budget_path(state).exists()
    assert not search_budget.routing_receipts_path(state).exists()
    assert not (state / "data/runtime/search_routing_cache.json").exists()


def test_dry_run_env_flag_forces_a_plan(tmp_path, policy, monkeypatch):
    monkeypatch.setenv("SEARCH_ROUTING_DRY_RUN", "1")
    paid = Paid()
    resp = search_router.route(search_router.SearchRequest(query="Dell stock outlook", caller="web_research"),
                               policy=policy, root=tmp_path / "state", enabled=True, paid_transport=paid,
                               free_transport=Free(THIN), clock=lambda: RTH)
    assert resp.dry_run and paid.requests == 0


def test_route_search_dry_run_needs_no_flag_and_spends_nothing(tmp_path, policy):
    paid = Paid()
    out = search_router.route_search("ACME stock premarket catalyst", request_class="scalp_priority",
                                     caller="hermes_scalp_catalyst", subject="ACME", intent="premarket catalyst",
                                     dry_run=True, policy=policy, root=tmp_path / "state", clock=lambda: RTH,
                                     paid_transport=paid, free_transport=Free(THIN), scalp_rows=([], None))
    assert out["ok"] is False and out["denied_reason"] == "DRY_RUN" and paid.requests == 0
    assert out["route"]["question_class"] == "scalp_priority" and out["route"]["dry_run"] is True
    assert out["decision"] == "DRY_RUN"
    assert set(out) == {"ok", "results", "provider", "cache_hit", "as_of", "decision", "route", "denied_reason"}


def test_route_search_shares_cache_on_subject_and_intent(tmp_path, policy, monkeypatch):
    monkeypatch.setenv("SEARCH_ROUTING_ENGINE", "1")
    free = Free(GOOD_NEWS)
    kw = dict(policy=policy, root=tmp_path / "state", clock=lambda: RTH, free_transport=free,
              db_query=lambda *a, **k: [], scalp_rows=([], None))
    a = search_router.route_search("ACME stock premarket catalyst", request_class="scalp_research",
                                   caller="hermes_scalp_catalyst", subject="ACME", intent="premarket catalyst", **kw)
    b = search_router.route_search("ACME premarket catalyst news today", request_class="scalp_research",
                                   caller="catalyst_momentum_engine", subject="ACME", intent="premarket catalyst", **kw)
    assert a["ok"] and not a["cache_hit"] and b["ok"] and b["cache_hit"]
    assert len(free.calls) == 1
    assert set(a["results"][0]) == {"title", "url", "content", "engine", "published"}


def test_route_search_live_needs_the_engine_flag_or_the_hot_tier(tmp_path, policy, monkeypatch):
    kw = dict(request_class="scalp_research", caller="hermes_scalp_catalyst", subject="ACME", intent="x",
              policy=policy, root=tmp_path / "state", free_transport=Free(GOOD_NEWS), db_query=lambda *a, **k: [],
              scalp_rows=([], None), clock=lambda: RTH)
    monkeypatch.delenv("SCALP_HOT_TIER", raising=False)
    assert search_router.route_search("ACME stock x", **kw)["denied_reason"] == "ENGINE_DISABLED"
    monkeypatch.setenv("SCALP_HOT_TIER", "1")
    out = search_router.route_search("ACME stock x", **kw)
    assert out["ok"] and out["decision"] == "FREE_SUFFICIENT"


def test_q_hot_tier_door_reaches_this_engine(tmp_path, monkeypatch):
    from lib import scalp_research_route as qroute
    qroute.set_engine_for_tests(None)
    assert qroute.engine_available()
    r = qroute.route("ACME", "premarket catalyst", caller="hermes_scalp_catalyst", priority=True, dry_run=True)
    assert r["decision"] == "DRY_RUN" and r["results"] == [] and r["request_class"] == "scalp_priority"


# ── 4. budget math ──────────────────────────────────────────────────────────


def test_trading_days_use_the_nyse_calendar():
    assert len(search_spend.trading_days(2026, 10)) == 22
    nov = search_spend.trading_days(2026, 11)
    assert date(2026, 11, 26) not in nov and len(nov) == 20


def _snap(policy, *, month=0, day=0, mpool=None, dpool=None):
    s = search_spend.SpendSnapshot(month_key="2026-10", day_key="2026-10-13", usd_per_request=0.005,
                                   month_requests=month, day_requests=day)
    s.month_by_pool, s.day_by_pool = dict(mpool or {}), dict(dpool or {})
    return s


BUDGET_TABLE = [
    # month requests, day requests, month by pool, day by pool, pool, expected reason
    (0, 0, {}, {}, "scalp", "OK"),
    (3599, 0, {}, {}, "operator", "OK"),                                    # $17.995 + 0.005 = $18.00
    (3600, 0, {}, {}, "operator", "LOCAL_CEILING"),
    (3000, 0, {}, {}, "scalp", "MONTH_LINE:working_target_usd"),            # $15 line
    (2399, 0, {"scalp": 2399}, {}, "scalp", "OK"),                          # scalp past $12 is fine
    (2400, 0, {"scalp": 2400}, {}, "catalyst", "MONTH_LINE:non_priority_stop_usd"),
    (700, 0, {"catalyst": 600}, {}, "catalyst", "POOL_MONTH_SHARE"),        # $3.00 share
    (0, 0, {}, {}, "nope", "UNKNOWN_POOL"),
]


@pytest.mark.parametrize("month,day,mpool,dpool,pool,reason", BUDGET_TABLE)
def test_budget_lines(policy, month, day, mpool, dpool, pool, reason):
    # Pacing generous enough not to bind: spent-before-today equals the expected pace.
    d = search_spend.decide(policy, _snap(policy, month=month, day=day, mpool=mpool, dpool=dpool), pool,
                            today=date(2026, 10, 31))
    assert d.reason == reason, d.detail


def test_daily_pace_base_carry_and_floor(policy):
    base = 15.0 / 22
    today = date(2026, 10, 13)            # 8 trading days elapsed before it (10-01 .. 10-12)
    on_pace = _snap(policy, month=int(round(base * 8 / 0.005)))
    assert search_spend.daily_allowance(policy, on_pace, today)["allowance"] == pytest.approx(base, rel=1e-3)
    unspent = _snap(policy, month=0)       # 8 days unspent: carry capped at one day
    assert search_spend.daily_allowance(policy, unspent, today)["allowance"] == pytest.approx(2 * base, rel=1e-3)
    overspent = _snap(policy, month=2000)  # $10 spent: pace repaid, never below the floor
    assert search_spend.daily_allowance(policy, overspent, today)["allowance"] == pytest.approx(0.25 * base, rel=1e-3)
    weekend = search_spend.daily_allowance(policy, unspent, date(2026, 10, 10))
    assert weekend["trading_day"] is False and weekend["allowance"] == pytest.approx(0.25 * base, rel=1e-3)


def test_background_pool_cannot_eat_the_scalp_share_of_the_day(policy):
    base = 15.0 / 22
    today = date(2026, 10, 13)
    month = int(round(base * 8 / 0.005))
    # catalyst share of the day = 20% of base; it has used exactly that
    used = int(0.2 * base / 0.005)
    s = _snap(policy, month=month + used, day=used, mpool={"catalyst": used}, dpool={"catalyst": used})
    assert search_spend.decide(policy, s, "catalyst", today=today).reason == "POOL_DAY_SHARE"
    # scalp may still spend — and may use the background's unspent part of the day
    assert search_spend.decide(policy, s, "scalp", today=today).allowed
    full = int(base / 0.005)
    s2 = _snap(policy, month=month + full, day=full, mpool={"scalp": full}, dpool={"scalp": full})
    assert search_spend.decide(policy, s2, "scalp", today=today).reason == "DAILY_PACE"
    # operator bypasses daily pacing (the reserve)
    assert search_spend.decide(policy, s2, "operator", today=today).allowed


def test_dollar_gate_runs_inside_the_ledger_lock(tmp_path, policy, monkeypatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "100000")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "100000")
    root = tmp_path / "state"
    path = search_budget.budget_path(root)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema": "SearchBudget@v1", "providers": {"brave": {
        "monthly": {"2026-10": 2400}, "callers": {"2026-10": {"legacy": 2400}}}}}))
    gate = search_spend.make_gate(policy, "catalyst")
    v = search_budget.try_consume("brave", caller="route.catalyst", now=RTH, root=root, gate=gate)
    assert not v["allowed"] and v["reason"] == "DOLLAR_BUDGET:MONTH_LINE:non_priority_stop_usd"
    led = json.loads(path.read_text())["providers"]["brave"]
    assert led["monthly"]["2026-10"] == 2400 and led["denied"]["2026-10-13"] == 1
    assert search_budget.try_consume("brave", caller="route.scalp", now=RTH, root=root,
                                     gate=search_spend.make_gate(policy, "scalp"))["allowed"]


def test_routed_callers_are_not_bound_by_hardcoded_per_caller_caps(monkeypatch):
    assert search_budget.caller_daily_cap("route.other", "brave") == search_budget.limits("brave")["daily"]
    assert search_budget.caller_daily_cap("governed_research_producer", "brave") == 25
    assert search_budget.effective_monthly_limit("brave", "route.operator", 1500) == 1500
    assert search_budget.effective_monthly_limit("brave", "route.scalp", 1500) == 1300


def test_spend_report_alert_levels(policy):
    def doc(n):
        return {"providers": {"brave": {"monthly": {"2026-10": n}, "daily": {"2026-10-13": 0}}}}
    assert search_spend.report(policy, doc(100), RTH)["alert"] == "ok"
    w = search_spend.report(policy, doc(2400), RTH)       # $12 = 80% of $15
    assert w["alert"] == "warning" and w["net_billed_usd"] == pytest.approx(7.0)
    assert search_spend.report(policy, doc(3600), RTH)["alert"] == "critical"


# ── 5. scalp-priority classifier ────────────────────────────────────────────


CFG = None


def _cfg(policy):
    return policy["priority"]["scalp"]


PRIORITY_TABLE = [
    # row, now, list age min, last researched min ago, expected priority, expected reason
    ({"symbol": "A", "decision": "MANUAL_REVIEW", "score": 36}, RTH, 5, None, True, "NEAR_GO"),
    ({"symbol": "A", "decision": "GO", "score": 45}, PRE, 5, None, True, "NEAR_GO"),
    ({"symbol": "A", "decision": "WAIT", "score": 20, "rvol": 4, "gap_pct": 8}, RTH, 5, None, True, "MOMENTUM"),
    ({"symbol": "A", "decision": "AVOID", "score": 45}, RTH, 5, None, False, "DECISION_AVOID"),
    ({"symbol": "A", "decision": "WAIT", "score": 30}, RTH, 5, None, False, "NOT_NEAR_TRIGGER"),
    ({"symbol": "A", "decision": "GO", "score": 45}, SAT, 5, None, False, "SESSION_CLOSED"),
    ({"symbol": "A", "decision": "GO", "score": 45}, RTH, 40, None, False, "LIST_STALE"),
    ({"symbol": "A", "decision": "GO", "score": 45}, RTH, 5, 10, False, "RESEARCHED_RECENTLY"),
    ({"symbol": "A", "decision": "GO", "score": 45}, RTH, 5, 31, True, "NEAR_GO"),
]


@pytest.mark.parametrize("row,now,age,last_min,pri,reason", PRIORITY_TABLE)
def test_priority_classifier(policy, row, now, age, last_min, pri, reason):
    last = {"A": now - timedelta(minutes=last_min)} if last_min is not None else {}
    out = sp.classify([row], now=now, cfg=_cfg(policy), go_min=40, last_researched=last,
                      list_as_of=now - timedelta(minutes=age))
    assert out[0].priority is pri and reason in out[0].reasons


def test_priority_cap_keeps_the_top_scores(policy):
    rows = [{"symbol": f"S{i}", "decision": "GO", "score": 40 + i} for i in range(8)]
    out = sp.classify(rows, now=RTH, cfg=_cfg(policy), go_min=40, handed_in=True)
    winners = sorted(d.symbol for d in out if d.priority)
    assert winners == ["S3", "S4", "S5", "S6", "S7"]
    assert all(d.reasons == ["OVER_CYCLE_CAP"] for d in out if not d.priority)


def test_scalp_list_loader_reads_the_projection(tmp_path):
    p = tmp_path / "data/trade_ai/scalp_universe_latest.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"as_of": "2026-10-13T10:00:00-04:00", "rows": [{"symbol": "X", "score": 1}]}))
    rows, as_of = sp.load_scalp_list(tmp_path, "data/trade_ai/scalp_universe_latest.json")
    assert rows == [{"symbol": "X", "score": 1}] and as_of == RTH
    assert sp.load_scalp_list(tmp_path, "missing.json") == ([], None)


# ── 6. cache ────────────────────────────────────────────────────────────────


def test_cache_ttl_shared_across_callers_and_fail_closed(tmp_path, policy):
    free = Free(GOOD_WEB)
    q = "Dell stock outlook growth drivers 2026"
    _route(tmp_path, policy, caller="governed_research_producer", query=q, symbol="DELL", free=free)
    hit = _route(tmp_path, policy, caller="hermes_cio_research", query=q, symbol="DELL", free=free,
                 now=RTH + timedelta(hours=5))
    assert hit.cache_hit and len(free.calls) == 1
    miss = _route(tmp_path, policy, caller="hermes_cio_research", query=q, symbol="DELL", free=free,
                  now=RTH + timedelta(hours=7))
    assert not miss.cache_hit and len(free.calls) == 2
    cpath = tmp_path / "state/data/runtime/search_routing_cache.json"
    cpath.write_text("{not json")
    assert search_router.cache_get(cpath, "k", ttl_s=60, now=RTH) is None
    assert search_router.cache_put(cpath, "k", {"results": [{"url": "https://x"}]}, now=RTH, max_entries=5, max_age_s=99)
    assert list(cpath.parent.glob("search_routing_cache.json.corrupt.*"))      # archived, never deleted


def test_an_insufficient_free_answer_in_cache_does_not_block_escalation(tmp_path, policy):
    paid = Paid()
    q = "Dell stock outlook growth drivers 2026"
    first = _route(tmp_path, policy, caller="web_research", query=q, free=Free(THIN), paid=None)
    assert first.reason.startswith("FREE_INSUFFICIENT:PAID_NOT_ARMED")
    second = _route(tmp_path, policy, caller="web_research", query=q, free=Free(THIN), paid=paid, api_key="fixture")
    assert second.tier == 2 and paid.requests == 1


# ── 7. the free lane never names a Brave engine ─────────────────────────────


def test_free_lane_engines_exclude_braveapi_and_match_the_policy(policy, monkeypatch):
    from scripts.lib import free_search
    sx = policy["free_lane"]["searxng"]
    assert free_search.DEFAULT_FREE_ENGINES["general"] == sx["engines"]["web"]
    assert free_search.DEFAULT_FREE_ENGINES["news"] == sx["engines"]["news"]
    for cat in ("general", "news"):
        eng = free_search.free_engines(cat)
        assert eng and not (set(eng) & {"braveapi", "brave", "brave.news"})
    seen = {}

    def fake_searx(q, **kw):
        seen.update(kw)
        return [{"title": "t", "url": "https://x", "snippet": "s"}]
    monkeypatch.setattr("scripts.lib.searxng_client.searx_search", fake_searx)
    free_search._default_transport("q", categories="general", limit=3, timeout=1.0)
    assert seen["engines"] == sx["engines"]["web"]


def test_searxng_client_sends_engines_instead_of_categories(monkeypatch):
    from scripts.lib import searxng_client
    urls = []

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"results": [{"title": "t", "url": "https://x", "content": "c",
                                            "engines": ["bing"], "publishedDate": "2026-10-13T10:00:00"}]}).encode()

    monkeypatch.setattr(searxng_client.urllib.request, "urlopen", lambda req, timeout: (urls.append(req.full_url), R())[1])
    out = searxng_client.searx_search("q", categories="general", engines=["bing", "seznam"])
    assert "engines=bing%2Cseznam" in urls[0] and "categories" not in urls[0]
    assert out[0]["published"] == "2026-10-13T10:00:00"
    searxng_client.searx_search("q", categories="news")
    assert "categories=news" in urls[1]


# ── 8. quality rule ─────────────────────────────────────────────────────────


def test_quality_rule_counts(policy):
    cfg = policy["classes"]["scalp_priority"]["quality"]
    td = policy["quality"]["trusted_domains"]
    a = search_quality.assess(GOOD_NEWS, query="ACME stock latest news", symbol="ACME", cfg=cfg, trusted_domains=td, now=RTH)
    assert a["sufficient"] and a["trusted"] == 2 and a["fresh"] == 2
    stale = [{**r, "published": "2026-10-01T00:00:00+00:00"} for r in GOOD_NEWS]
    b = search_quality.assess(stale, query="ACME stock latest news", symbol="ACME", cfg=cfg, trusted_domains=td, now=RTH)
    assert not b["sufficient"] and "min_fresh" in b["missing"]
    assert search_quality.trusted("https://investors.businesswire.com/x", ["businesswire.com"])
    assert not search_quality.trusted("https://notreuters.com/x", ["reuters.com"])
    assert search_quality.published_at({"age": "3 hours ago"}, RTH) == RTH - timedelta(hours=3)


def test_alpha_vantage_tier_is_skipped_until_granted(tmp_path, policy):
    resp = _route(tmp_path, policy, caller="hermes_momentum_catalyst", query="ACME stock latest news", symbol="ACME",
                  free=Free([]), paid=None)
    assert "alpha_vantage_news:NOT_GRANTED" in resp.receipt["attempts"]
    reg = {"providers": {"alpha_vantage": {"supplies": ["fundamentals", "news_sentiment"]}}}
    store = tmp_path / "state/data/runtime/alpha_vantage/news_sentiment_latest.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({"schema": "NewsSentimentIndex@v1", "by_ticker": {"ACME": [
        {"title": "ACME wins contract", "url": "https://www.benzinga.com/z", "summary": "s",
         "time_published": "20261013T120000", "source": "Benzinga"},
        {"title": "ACME guidance", "url": "https://www.reuters.com/z", "summary": "s",
         "time_published": "20261013T110000", "source": "Reuters"}]}}))
    resp2 = _route(tmp_path, policy, caller="hermes_momentum_catalyst", query="ACME stock earnings guidance",
                   symbol="ACME", free=Free([]), paid=None, registry=reg)
    assert resp2.ok and resp2.reason == "FREE_SUFFICIENT" and resp2.provider == "alpha_vantage_news"


# ── 9. incident fan-in source + report script ───────────────────────────────


def test_spend_report_write_feeds_the_fanin_as_p2(tmp_path, policy, monkeypatch):
    import scripts.search_spend_report as rep
    import scripts.n8n_incident_fanin as fanin
    root = tmp_path / "state"
    path = search_budget.budget_path(root)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"providers": {"brave": {"monthly": {"2026-10": 2500}, "daily": {"2099-01-01": 1}}}}))
    r = rep.build(root=root, now=RTH, policy=policy)
    assert r["alert"] == "warning" and r["status"] == "degraded"
    assert r["ledger_future_keys"] == {"brave": ["daily:2099-01-01"]}
    rep.write(r, root)
    monkeypatch.setenv("TRADEAI_FANIN_LANE_REGISTRY", "0")
    monkeypatch.setenv("TRADEAI_FANIN_RELAY", "0")
    monkeypatch.setattr(fanin, "_outbox_findings", lambda now: [])
    monkeypatch.setattr(fanin, "_runs_findings", lambda root, now: [])
    found = [f for f in fanin.collect(root, RTH, prev={}) if f["source"] == "search_spend"]
    assert found and found[0]["severity"] == "P2" and found[0]["item"] == "2026-10:warning"


def test_spend_report_default_is_a_dry_run(tmp_path, capsys):
    import scripts.search_spend_report as rep
    assert rep.main(["--root", str(tmp_path / "state")]) == 0
    assert '"dry_run": true' in capsys.readouterr().out
    assert not (tmp_path / "state" / rep.RECEIPT_REL).exists()


# ── 10. rerouted callers use the engine only behind the flag ────────────────


def test_catalyst_search_is_legacy_unless_flagged(monkeypatch):
    import hermes_momentum_catalyst_researcher as h
    assert h._routed_search("ACME", "ACME stock news") is None
    monkeypatch.setenv("SEARCH_ROUTING_ENGINE", "1")
    from lib import search_router as lsr
    monkeypatch.setattr(lsr, "route_search", lambda q, **kw: {
        "ok": True, "results": [{"title": "ACME", "url": "https://r/x", "content": "c", "engine": "searxng",
                                 "published": ""}], "denied_reason": None, "seen": kw})
    rows = h.search_catalyst("ACME", "premarket catalyst", candidate={"symbol": "ACME", "score": 39})
    assert rows and set(rows[0]) == {"title", "url", "content", "engine", "published"}


def test_hermes_web_research_routes_when_flagged():
    from scripts.lib import hermes_web_research as hw
    seen = []

    def fake_route(q, **kw):
        seen.append(kw)
        return search_router.RoutedResponse(ok=True, reason="FREE_SUFFICIENT", provider="searxng", tier=1, results=[
            {"title": "DELL stock earnings outlook", "url": f"https://www.reuters.com/{len(seen)}", "description": "stock"}])
    out = hw.gather({"reason": "x", "symbol": "DELL", "research_id": "r1",
                     "questions": [{"id": "q1", "intent": "thesis_check", "text": "growth"}]},
                    cfg={"enabled_reasons": ["*"]}, env={"SEARCH_ROUTING_ENGINE": "1"}, route_fn=fake_route,
                    free_fn=lambda *a, **k: pytest.fail("legacy free path used"),
                    brave_fn=lambda *a, **k: pytest.fail("legacy brave path used"))
    assert out["used"] and out["results"] and seen and seen[0]["caller"] == "hermes_cio_research"


def test_quality_escalate_routes_when_flagged(monkeypatch, tmp_path):
    from scripts.lib import research_quality_escalate as rqe
    calls = []
    monkeypatch.setattr(search_router, "route_query", lambda q, **kw: (calls.append(kw), search_router.RoutedResponse(
        ok=True, reason="FREE_SUFFICIENT", provider="searxng", tier=1, question_class="quality_escalation",
        results=[{"title": "t", "url": "https://x", "description": "d"}]))[1])
    env = {rqe.FLAG: "1", "SEARCH_ROUTING_ENGINE": "1"}
    r = rqe.maybe_escalate(question="what is dell backlog", symbol="DELL", search_hits=[], env=env, dry_run=False,
                           root=tmp_path)
    assert r["thin"] is True and r["escalated"] is True
    assert calls and calls[0]["caller"] == "research_quality_escalate"
    assert r["route_class"] == "quality_escalation" and r["provider"] == "searxng"


def test_governed_research_producer_routes_when_flagged(monkeypatch, tmp_path):
    from scripts.lib import governed_research_producer as grp
    seen = []

    def fake_route(req, **kw):
        seen.append((req, kw))
        return search_router.RoutedResponse(ok=True, reason="FREE_SUFFICIENT", provider="searxng", tier=1,
                                            results=[{"title": "t", "url": "https://www.reuters.com/z",
                                                      "description": "d", "provider": "searxng"}])
    monkeypatch.setattr(search_router, "route", fake_route)
    env = {"SEARCH_ROUTING_ENGINE": "1", grp.FEATURE_FLAG: "1"}
    res = grp.produce_research(targets=[{"symbol": "DELL", "subject_guid": "g-1", "query": "dell outlook"}],
                               env=env, root=tmp_path, feed=tmp_path / "feed.jsonl", health=tmp_path / "h.json",
                               clock=lambda: RTH,
                               transport=lambda *a: pytest.fail("legacy brave path used"))
    assert seen and seen[0][0].caller == "governed_research_producer" and seen[0][0].symbol == "DELL"
    assert res.produced == 1
    row = json.loads((tmp_path / "feed.jsonl").read_text().splitlines()[0])
    assert "governed_search_router" in json.dumps(row)


def test_gap_resolver_routes_when_flagged(monkeypatch):
    from scripts.lib import gap_resolver as gr
    seen = []
    monkeypatch.setattr(search_router, "route", lambda req, **kw: (seen.append(req), search_router.RoutedResponse(
        ok=True, reason="FREE_SUFFICIENT", provider="searxng", tier=1, question_class="gap_fill",
        results=[{"title": "t", "url": "https://x", "description": "d"}]))[1])
    gap = gr.DataGap(domain="catalyst_news", subject="DELL", question="why did DELL move")
    ctx = gr.Context(env={"SEARCH_ROUTING_ENGINE": "1"}, live=True, now=lambda: RTH)
    res = gr._v_governed_search(gap, {}, ctx)
    assert res.outcome == "partial" and seen[0].caller == "gap_resolver" and seen[0].symbol == "DELL"
    assert res.evidence["route_class"] == "gap_fill"
