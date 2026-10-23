"""Ask the CIO Phase 9 research pipeline: hermetic tests (fake search, LLM and stores; no network, no DB).

ANCHOR: CIO_ASK_RESEARCH_PHASE9_20261023
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import cio_ask_research as car  # noqa: E402

TSLA_GUID = "sec-tsla-0001"
ISSUER_TSLA = "iss-tsla-0001"
NOW = "2026-10-22T20:00:00Z"


# ------------------------------------------------------------------------------------------------ fakes
def fake_identity(sym: str) -> dict:
    if sym == "TSLA":
        return {
            "subject_guid": TSLA_GUID,
            "security_guid": TSLA_GUID,
            "issuer_guid": ISSUER_TSLA,
            "identity_lookup": "RESOLVED",
            "entity_type": "security",
        }
    return {"subject_guid": None, "identity_lookup": "UNRESOLVED"}


def fake_name(name: str):
    return {"symbol": "TSLA"} if name.lower().startswith("tesla") else None


def fake_issuer(name: str) -> str:
    return "iss-private-" + name.lower().replace(" ", "-")


def _src(name, family, facts_fn, timeout=2.0, needs_symbol=True, delay=0.0):
    def fn(ent, ctx):
        if delay:
            time.sleep(delay)
        return facts_fn(ent, ctx)

    return car.SourceSpec(name, family, fn, timeout_s=timeout, needs_symbol=needs_symbol)


def street_facts(ent, ctx):
    out = []
    for fld, v in (("target_low", 150.0), ("target_mean", 260.0), ("target_high", 400.0), ("analyst_count", 42)):
        out.append(
            car.make_fact(
                source="street.yahoo_targets",
                family="street",
                kind="target",
                subject_key=ent.subject_key,
                symbol=ent.symbol,
                claim=f"Street {fld}: {v}",
                as_of=NOW,
                citation={"store": "yahoo_analyst_targets_history"},
                field=fld,
                value=v,
                unit="usd",
            )
        )
    return out


def price_facts(ent, ctx):
    return [
        car.make_fact(
            source="market.quote",
            family="market",
            kind="price",
            subject_key=ent.subject_key,
            symbol=ent.symbol,
            claim="last 220",
            as_of=NOW,
            citation={"projection": "latest_quote"},
            field="last_price",
            value=220.0,
            unit="usd",
        )
    ]


def catalyst_facts(ent, ctx):
    return [
        car.make_fact(
            source="internal.catalysts",
            family="internal",
            kind="catalyst",
            subject_key=ent.subject_key,
            symbol=ent.symbol,
            claim="[earnings] Q3 results",
            as_of="2026-10-21T21:00:00Z",
            citation={"store": "catalyst_events", "url": "https://example.test/q3"},
        )
    ]


def held_facts(ent, ctx):
    return [
        car.make_fact(
            source="internal.holdings",
            family="internal",
            kind="held",
            subject_key=ent.subject_key,
            symbol=ent.symbol,
            claim="TSLA is held (held flag) SECRET-LOCAL-MARKER",
            as_of=NOW,
            citation={"reader": "held_positions"},
            field="held",
            value=1,
            egress="local_only",
        )
    ]


def web_facts(ent, ctx):
    return [
        car.make_fact(
            source="web.brave",
            family="web",
            kind="web",
            subject_key=ent.subject_key,
            symbol=ent.symbol,
            claim=f"Report about {ent.label}",
            as_of=NOW,
            citation={"url": "https://example.test/web", "as_of_basis": "published_at"},
        )
    ]


def base_sources():
    return [
        _src("street", "street", street_facts),
        _src("price", "market", price_facts),
        _src("catalysts", "internal", catalyst_facts),
        _src("holdings", "internal", held_facts),
        _src("web", "web", web_facts, needs_symbol=False),
    ]


def model_reply(stance: str, *, base_anchor_id=None, extra_text="", behavior_key=False) -> str:
    cell = lambda fid, txt: {"anchor_fact_id": fid, "assumption": txt}  # noqa: E731
    subj = {
        "subject_key": TSLA_GUID,
        "stance": stance,
        "summary": f"Deliveries drive the view. {extra_text}".strip(),
        "horizons": {
            h: {
                "bear": cell(None, "demand slows"),
                "base": cell(base_anchor_id, "steady"),
                "bull": cell(None, "robotaxi scale"),
            }
            for h in ("3m", "6m", "12m")
        },
        "risks": [{"text": "Margin pressure", "fact_ids": []}],
        "what_changes_view": ["A guidance cut"],
    }
    if behavior_key:
        subj["shares"] = 500
    return json.dumps({"subjects": [subj]})


class Gov(car.CostGovernor):
    def __init__(self, *, cap=1.0, allow=True, registered=True, raise_exc=False):
        def check(pid, projected_usd=0.0, global_cap=None):
            if raise_exc:
                raise RuntimeError("ledger down")
            return {"allow": allow, "reason": None if allow else "COST_CAP_EXCEEDED"}

        super().__init__(per_question_usd=cap, check_fn=check, registered_fn=lambda pid: registered)


def run(
    question="Should I own 100 or 1,000 TSLA given the merger talk?",
    *,
    panel=None,
    sources=None,
    gov=None,
    memory=None,
    origin="in_process",
    subjects=None,
):
    req = {"question": question, "request_id": "ask_test_1", "asked_at": NOW}
    if subjects is not None:
        req["subjects"] = subjects
    return car.run_research(
        req,
        sources=sources or base_sources(),
        panel=panel if panel is not None else [],
        governor=gov or Gov(),
        memory=memory,
        origin=origin,
        identity_fn=fake_identity,
        name_fn=fake_name,
        issuer_guid_fn=fake_issuer,
    )


# ------------------------------------------------------------------------------------------------ gather
def test_parallel_gather_with_per_source_timeout():
    ctx = car.ResearchContext(question="q")
    ent = car.resolve_entity(
        {"symbol": "TSLA"}, identity_fn=fake_identity, name_fn=fake_name, issuer_guid_fn=fake_issuer
    )
    srcs = [_src(f"slow{i}", "internal", catalyst_facts, delay=0.4) for i in range(4)]
    srcs.append(_src("hung", "web", web_facts, timeout=0.3, delay=5.0))
    t0 = time.monotonic()
    g = car.gather_facts([ent], srcs, ctx)
    elapsed = time.monotonic() - t0
    assert elapsed < 1.5, f"gather is not parallel or waited on the hung source ({elapsed:.2f}s)"
    assert {"reason": "TIMEOUT", "source": "hung"}.items() <= next(
        x for x in g["gaps"] if x["source"] == "hung"
    ).items()
    assert sum(r["status"] == "ok" for r in g["runs"]) == 4
    assert len(g["facts"]) == 1  # four sources produced the same fact: de-duplicated by fact_id


def test_source_error_and_uncited_fact_become_named_gaps():
    def boom(ent, ctx):
        raise ConnectionError("store offline")

    def no_asof(ent, ctx):
        return [
            car.make_fact(
                source="x",
                family="news",
                kind="news",
                subject_key=ent.subject_key,
                claim="c",
                as_of=None,
                citation={"url": "u"},
            )
        ]

    def no_cite(ent, ctx):
        return [
            car.make_fact(
                source="y", family="news", kind="news", subject_key=ent.subject_key, claim="c", as_of=NOW, citation={}
            )
        ]

    ent = car.resolve_entity("TSLA", identity_fn=fake_identity, name_fn=fake_name, issuer_guid_fn=fake_issuer)
    g = car.gather_facts(
        [ent],
        [_src("boom", "sec", boom), _src("noasof", "news", no_asof), _src("nocite", "news", no_cite)],
        car.ResearchContext(question="q"),
    )
    reasons = {x["source"]: x["reason"] for x in g["gaps"]}
    assert reasons == {"boom": "SOURCE_ERROR", "noasof": "FACT_REJECTED", "nocite": "FACT_REJECTED"}
    assert g["facts"] == []


# ------------------------------------------------------------------------------------------------ citations
def test_every_number_carries_as_of_and_citation_and_horizon_gaps_are_named():
    ans = run()
    assert car.assert_numbers_cited(ans) == []
    for f in ans["facts"]:
        assert f["as_of"] and f["citation"]
    p = ans["prospectus"][0]
    assert p["street"]["range"] == [150.0, 400.0]
    assert p["horizons"]["12m"]["bull"]["price"] == 400.0  # street high, cited
    assert p["horizons"]["12m"]["bull"]["anchor"]["citation"]["store"] == "yahoo_analyst_targets_history"
    for h in ("3m", "6m"):
        for c in ("bear", "base", "bull"):
            cell = p["horizons"][h][c]
            assert cell["price"] is None and cell["gap"].startswith("NO_SOURCED_ANCHOR")
    assert p["catalysts"][0]["date"] == "2026-10-21T21:00:00Z"
    assert all(s["as_of"] for s in ans["sources"])


def test_model_numbers_without_a_fact_are_dropped():
    panel = [
        car.PanelMember(
            "grok",
            lambda p: model_reply("bullish", base_anchor_id="f_bogus", extra_text="Shares reach 999 by spring."),
            est_usd=0.0,
        )
    ]
    ans = run(panel=panel)
    blob = json.dumps(ans["prospectus"])
    assert "999" not in blob
    reasons = {x["reason"] for x in ans["ungrounded_log"]}
    assert {"ungrounded_number", "anchor_not_a_sourced_number"} <= reasons


def test_model_may_quote_sourced_numbers():
    vals = [260.0]
    assert (
        car.ground_text("Base case holds near the 260 mean.", vals, where="t", log=[])
        == "Base case holds near the 260 mean."
    )
    assert car.ungrounded_numbers("Over 12 months in 2027", vals) == []


# ------------------------------------------------------------------------------------------------ panel / dissent
def test_dissent_captured_and_every_member_sees_the_same_facts():
    seen: dict[str, str] = {}

    def member(name, stance, anchor_field=None):
        def call(prompt):
            seen[name] = prompt
            fid = None
            if anchor_field:
                fid = next(
                    f["fact_id"]
                    for f in json.loads(prompt.split("INPUT:\n", 1)[1])["facts"]
                    if f.get("kind") == "target" and f["claim"].startswith(f"Street {anchor_field}")
                )
            return model_reply(stance, base_anchor_id=fid)

        return car.PanelMember(name, call, est_usd=0.0)

    ans = run(
        panel=[
            member("deepseek", "bullish", "target_mean"),
            member("grok", "bearish", "target_low"),
            member("chatgpt", "bullish", "target_mean"),
        ]
    )
    assert len(set(seen.values())) == 1, "panel members were given different facts"
    assert len({o["prompt_sha"] for o in ans["panel"]}) == 1
    stance = next(d for d in ans["dissent"] if d["kind"] == "stance")
    assert stance["positions"] == {"chatgpt": "bullish", "deepseek": "bullish", "grok": "bearish"}
    anchor = [
        d for d in ans["dissent"] if d["kind"] == "scenario_anchor" and d["horizon"] == "3m" and d["case"] == "base"
    ]
    assert anchor and anchor[0]["positions"]["grok"] == 150.0
    assert ans["prospectus"][0]["horizons"]["3m"]["base"]["price"] == 260.0  # majority anchor, sourced


def test_local_only_facts_never_reach_the_panel_prompt():
    prompts = []
    ans = run(panel=[car.PanelMember("grok", lambda p: prompts.append(p) or model_reply("neutral"), est_usd=0.0)])
    assert prompts and "SECRET-LOCAL-MARKER" not in prompts[0]
    assert "SECRET-LOCAL-MARKER" in json.dumps(ans["facts"])  # kept locally


# ------------------------------------------------------------------------------------------------ MBI guard
def test_mbi_guard_strips_and_logs_model_sizing():
    text = (
        "Buy 500 shares at the open. Put a stop-loss at 180. Allocate 5% of the portfolio. Deliveries drive the view."
    )
    panel = [
        car.PanelMember("chatgpt", lambda p: model_reply("bullish", extra_text=text, behavior_key=True), est_usd=0.0)
    ]
    ans = run(panel=panel)
    views = json.dumps(ans["prospectus"][0]["panel_views"])
    assert "500 shares" not in views and "stop-loss" not in views and "5% of the portfolio" not in views
    assert "Deliveries drive the view." in views
    log = ans["mbi_strip_log"]
    assert any(x["reason"] == "behavior_key" and x["where"].endswith(".shares") for x in log)
    assert sum(x["reason"].startswith(("sizing_pattern", "execution_imperative")) for x in log) >= 3
    rb = ans["prospectus"][0]["risk_budget_inputs"]
    assert rb["size_suggestion"] is None and "21.0.0" in rb["size_suggestion_policy"]
    assert "size_suggestion" not in json.dumps({k: v for k, v in ans.items() if k != "prospectus"})


def test_sizing_context_is_arithmetic_on_operator_named_quantities_only():
    ans = run()
    rows = ans["prospectus"][0]["sizing_context"]
    assert [r["quantity"] for r in rows] == [100.0, 1000.0]
    assert rows[0]["notional_usd"] == 22000.0 and rows[1]["notional_usd"] == 220000.0
    assert rows[1]["scenario_pnl_usd"]["12m"]["bull"] == 1000 * (400.0 - 220.0)
    assert rows[1]["scenario_pnl_usd"]["3m"]["base"] is None  # no sourced anchor, no number
    assert all(r["named_by"] == "operator" and r["egress"] == "local_only" for r in rows)
    none = run(question="What is the street view on TSLA?")
    assert none["prospectus"][0]["sizing_context"] == []


def test_named_quantity_parser():
    assert [q["quantity"] for q in car.parse_named_quantities("100 or 1,000 TSLA?")] == [100.0, 1000.0]
    assert car.parse_named_quantities("buy 2k shares of NVDA")[0] == {
        "symbol": "NVDA",
        "quantity": 2000.0,
        "source": "operator_question",
    }
    assert car.parse_named_quantities("invest in Skydance after Musk's $1B?") == []


# ------------------------------------------------------------------------------------------------ cost caps
def test_per_question_cap_refuses_cleanly_with_partial_answer():
    calls = []
    mk = lambda n: car.PanelMember(n, lambda p: calls.append(n) or model_reply("neutral"), est_usd=0.2)  # noqa: E731
    ans = run(panel=[mk("chatgpt"), mk("deepseek"), mk("grok")], gov=Gov(cap=0.3))
    assert calls == ["chatgpt"]
    assert ans["partial"] is True
    refused = {r["member"]: r["reason"] for r in ans["refusals"]}
    assert refused == {"deepseek": "PER_QUESTION_CAP_EXCEEDED", "grok": "PER_QUESTION_CAP_EXCEEDED"}
    assert ans["prospectus"][0]["street"]["range"] == [150.0, 400.0]  # sourced part still answered


@pytest.mark.parametrize(
    "gov,reason",
    [
        (Gov(allow=False), "COST_CAP_EXCEEDED"),
        (Gov(registered=False), "PROCESS_NOT_REGISTERED"),
        (Gov(raise_exc=True), "BUDGET_UNAVAILABLE:RuntimeError"),
    ],
)
def test_daily_cap_and_fail_closed(gov, reason):
    called = []
    ans = run(panel=[car.PanelMember("deepseek", lambda p: called.append(1) or "{}", est_usd=0.01)], gov=gov)
    assert called == []
    assert ans["partial"] and ans["refusals"] == [{"member": "deepseek", "reason": reason}]


def test_unregistered_process_is_refused_by_default_registry():
    gov = car.CostGovernor(check_fn=lambda *a, **k: {"allow": True})
    assert gov.admit("deepseek", 0.01) == (False, "PROCESS_NOT_REGISTERED")


# ------------------------------------------------------------------------------------------------ entities
def test_private_company_is_a_tracked_entity_without_a_ticker():
    ans = run(question="Should I invest in Skydance after Musk's $1B?", subjects=[{"name": "Skydance"}])
    ent = ans["entities"][0]
    assert ent["kind"] == "private" and ent["symbol"] is None
    assert ent["subject_key"] == "iss-private-skydance"
    assert ent["identity_status"] == "TRACKED_PRIVATE_UNREGISTERED"
    gap_sources = {g["source"] for g in ans["gaps"] if g["reason"] == "NOT_APPLICABLE_PRIVATE_ENTITY"}
    assert {"street", "price", "catalysts", "holdings"} <= gap_sources
    assert [f["source"] for f in ans["facts"]] == ["web.brave"]
    p = ans["prospectus"][0]
    assert p["reference_price"] is None and p["street"]["range"] is None
    assert all(f["symbol"] is None for f in ans["facts"])


def test_name_resolving_to_a_listed_symbol_and_unresolved_symbol():
    e = car.resolve_entity(
        {"name": "Tesla Inc"}, identity_fn=fake_identity, name_fn=fake_name, issuer_guid_fn=fake_issuer
    )
    assert (e.kind, e.symbol, e.subject_key) == ("listed", "TSLA", TSLA_GUID)
    u = car.resolve_entity({"symbol": "ZZZZ"}, identity_fn=fake_identity, name_fn=fake_name, issuer_guid_fn=fake_issuer)
    assert u.kind == "unresolved" and u.subject_key is None
    ans = run(subjects=[{"symbol": "ZZZZ"}])
    assert ans["prospectus"][0]["status"] == "identity unresolved" and ans["facts"] == []


def test_bare_tokens_need_identity_confirmation():
    subs = car.extract_subjects("Is TSLA or I or ZZZZ a buy? $abc", known_symbol=lambda t: t == "TSLA")
    assert subs == [{"symbol": "TSLA"}, {"symbol": "ABC"}]


# ------------------------------------------------------------------------------------------------ memory
def test_memory_append_is_idempotent_and_keyed_by_guid(tmp_path):
    sink = []
    mem = car.MemoryAppender(ledger_path=tmp_path / "ledger.jsonl", sink=sink.append)
    panel = [car.PanelMember("grok", lambda p: model_reply("bullish"), est_usd=0.0)]
    a1 = run(panel=panel, memory=mem)
    n = len(sink)
    assert a1["memory_receipt"]["appended"] == n == len(a1["facts"]) + 1
    assert {e["subject_guid"] for e in sink} == {TSLA_GUID}
    assert {e["predicate"] for e in sink} == {"ask_research_fact", "ask_answer"}
    # same request again, fresh appender over the same ledger: nothing new
    mem2 = car.MemoryAppender(ledger_path=tmp_path / "ledger.jsonl", sink=sink.append)
    a2 = run(panel=panel, memory=mem2)
    assert len(sink) == n and a2["memory_receipt"]["skipped_duplicate"] == n
    # no sizing in memory (FORBIDDEN_OBJECT_KEYS / §2A)
    assert "quantity" not in json.dumps(sink) and "notional" not in json.dumps(sink)


def test_n8n_origin_keeps_model_text_out_of_memory(tmp_path):
    sink = []
    mem = car.MemoryAppender(ledger_path=tmp_path / "l.jsonl", sink=sink.append)
    run(panel=[car.PanelMember("grok", lambda p: model_reply("bullish"), est_usd=0.0)], memory=mem, origin="n8n")
    ans_ev = next(e for e in sink if e["predicate"] == "ask_answer")
    assert "panel_views" not in ans_ev["object"] and ans_ev["object"]["model_text"].startswith("OMITTED_ON_N8N_PATH")


def test_private_entity_memory_keyed_by_issuer(tmp_path):
    sink = []
    run(subjects=[{"name": "Skydance"}], memory=car.MemoryAppender(sink=sink.append))
    assert sink and {e["subject_guid"] for e in sink} == {"iss-private-skydance"}
    assert all(e["symbol"] is None and e["entity_kind"] == "private" for e in sink)


def test_refused_memory_envelope_is_reported_not_raised():
    def sink(env):
        raise RuntimeError("FINANCIAL_TRUTH_REFUSED: key=qty")

    ans = run(memory=car.MemoryAppender(sink=sink))
    assert ans["memory_receipt"]["appended"] == 0 and ans["memory_receipt"]["refused"]


# ------------------------------------------------------------------------------------------------ modes / executor
def test_dry_run_plans_without_gathering():
    def never(ent, ctx):
        raise AssertionError("dry run gathered")

    plan = car.run_research(
        {"question": "TSLA?", "subjects": [{"symbol": "TSLA"}]},
        sources=[_src("x", "web", never)],
        panel=[],
        governor=Gov(),
        dry_run=True,
        identity_fn=fake_identity,
        name_fn=fake_name,
        issuer_guid_fn=fake_issuer,
    )
    assert plan["dry_run"] is True and plan["entities"][0]["subject_key"] == TSLA_GUID


def test_fast_mode_skips_panel_and_web():
    ans = car.run_research(
        {"question": "TSLA?", "subjects": [{"symbol": "TSLA"}], "mode": "fast"},
        sources=base_sources(),
        panel=None,
        governor=Gov(),
        identity_fn=fake_identity,
        name_fn=fake_name,
        issuer_guid_fn=fake_issuer,
    )
    assert ans["panel"] == [] and "web.brave" not in {f["source"] for f in ans["facts"]}


def test_executor_dry_run_writes_nothing(tmp_path):
    q, out = tmp_path / "q", tmp_path / "out"
    q.mkdir()
    (q / "r1.json").write_text(json.dumps({"request_id": "r1", "question": "$ZZZZ outlook?"}))
    env = {"PATH": "/usr/bin:/bin", "TRADEAI_PERSISTENT_STATE_ROOT": str(tmp_path / "state"), "HOME": str(tmp_path)}
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "cio_ask_research.py"),
            "--dry-run",
            "--queue-dir",
            str(q),
            "--out-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert "DRY-RUN" in r.stdout and '"lane_id": "cio-ask-research"' in r.stdout
    assert not out.exists() and not (tmp_path / "state").exists()


def test_ci_gate_registered():
    gate = json.loads((ROOT / "config" / "ci_gates" / "cio_ask_research_phase9_20261023.json").read_text())
    assert "tests/test_cio_ask_research.py" in gate["files"]
