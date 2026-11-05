"""Hourly Ask provider lifecycle: fake bridge, stores and search only."""

from datetime import datetime, timezone, timedelta
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.lib import cio_ask_contract as C
from scripts.lib import cio_ask_provider_routes as routes
from scripts.lib import cio_ask_research as research

NOW = datetime(2026, 10, 26, 17, tzinfo=timezone.utc)
GUID = "fixture-security"
OPUS = "claude-opus-5-5"


@pytest.fixture
def configured(tmp_path):
    (tmp_path / "config").mkdir()
    processes = [
        {
            "id": pid,
            "default_mode": "manual" if pid == routes.MANUAL_PROCESS else "automated",
            "daily_cost_cap_usd": 1,
            "daily_soft_cap": 10,
            "anthropic_first": pid in {routes.MANUAL_PROCESS, routes.SCHEDULED_PROCESS},
            "allowed_lanes": [provider],
        }
        for pid, provider in [
            (routes.MANUAL_PROCESS, "anthropic"),
            (routes.SCHEDULED_PROCESS, "anthropic"),
            *[(pid, provider) for provider, pid in routes.CRITIQUE_PROCESSES.items()],
        ]
    ]
    rows = {r["id"]: {"primary": {"provider": r["allowed_lanes"][0], "policy": "FAST"}} for r in processes}
    for name, value in {
        "llm_process_registry": {"processes": processes},
        "llm_routing_policy": {"policies": {"default": {"processes": rows}}},
        "anthropic_credit_policy": {"models": {"standard": OPUS}, "excluded_processes": {}},
        "llm_model_registry": {
            "logical_policies": {"FAST": {"provider": "deepseek", "model": "flash"}},
            "providers": {"deepseek": {"models": {"flash": {"model_id": "deepseek-flash"}}}},
        },
    }.items():
        (tmp_path / "config" / (name + ".json")).write_text(json.dumps(value))
    return tmp_path


def response(kwargs, provider="anthropic", *, cost=0.012, model=None):
    return {
        "model": model or (OPUS if provider == "anthropic" else provider + "-actual-model"),
        "choices": [
            {
                "message": {
                    "content": '{"subjects":[{"subject_key":"fixture-security","stance":"bullish","summary":"Sourced case","what_changes_view":["Evidence changes"]}]}'
                }
            }
        ],
        "_tradeai": {
            "governance_pass": True,
            "mock": False,
            "process_id": kwargs["process_id"],
            "request_id": kwargs["request_id"],
            "reservation_id": 42,
            "provider_request_id": "provider-id",
            "provider": provider,
            "cost_estimate": cost,
            "cost_basis": "free_oauth_unmetered"
            if provider in {"grok", "chatgpt"}
            else "provider_usage_x_registry_snapshot",
        },
    }


@pytest.mark.parametrize("manual,pid", [(True, routes.MANUAL_PROCESS), (False, routes.SCHEDULED_PROCESS)])
def test_primary_propagates_origin_and_narrows_budget(configured, manual, pid):
    calls = []

    def bridge(messages, **kwargs):
        calls.append((messages, kwargs))
        return response(kwargs)

    out = routes.call_role(
        "same facts",
        role="primary",
        process_id=pid,
        manual_trigger=manual,
        ceiling_usd=0.20,
        root=configured,
        bridge_call=bridge,
        request_id="fixture-request",
    )
    assert out.evidence["provider"] == "anthropic" and out.evidence["model"] == OPUS
    assert out.evidence["actual_cost_usd"] == 0.012 and out.evidence["cost_usage_known"]
    assert calls[0][1]["manual_trigger"] is manual
    assert calls[0][1]["process_id"] == pid
    assert calls[0][1]["budget"] == {"cost_ceiling_usd": 0.20}


@pytest.mark.parametrize(
    "manual,pid,reason",
    [
        (False, routes.MANUAL_PROCESS, "MANUAL_TRIGGER_REQUIRED"),
        (True, routes.SCHEDULED_PROCESS, "SCHEDULED_MANUAL_TRIGGER_FORBIDDEN"),
    ],
)
def test_manual_and_automated_authority_cannot_be_substituted(configured, manual, pid, reason):
    with pytest.raises(routes.ProviderRefused, match=reason):
        routes.call_role(
            "facts",
            role="primary",
            process_id=pid,
            manual_trigger=manual,
            ceiling_usd=0.1,
            root=configured,
            bridge_call=lambda *a, **k: pytest.fail("dispatch"),
        )


@pytest.mark.parametrize("provider", ["grok", "chatgpt"])
def test_independent_oauth_roles_keep_actual_model_and_known_zero_cost(configured, provider):
    def bridge(messages, **kwargs):
        assert kwargs["manual_trigger"] is False
        return response(kwargs, provider, cost=None)

    out = routes.call_role(
        "facts",
        role=provider,
        process_id=routes.CRITIQUE_PROCESSES[provider],
        manual_trigger=False,
        ceiling_usd=0,
        root=configured,
        bridge_call=bridge,
    )
    assert out.evidence["provider"] == provider
    assert out.evidence["model"] == provider + "-actual-model"
    assert out.evidence["actual_cost_usd"] == 0 and out.evidence["cost_usage_known"]


def test_wrong_provider_never_counts_as_independent_consensus(configured):
    def bridge(messages, **kwargs):
        return response(kwargs, "anthropic")

    with pytest.raises(routes.ProviderRefused, match="PROVIDER_IDENTITY_NOT_PROVEN") as caught:
        routes.call_role(
            "facts",
            role="grok",
            process_id=routes.CRITIQUE_PROCESSES["grok"],
            manual_trigger=False,
            ceiling_usd=0,
            root=configured,
            bridge_call=bridge,
        )
    assert caught.value.evidence["actual_cost_usd"] == 0.012  # paid mistake is still counted


@pytest.mark.parametrize("change", ["unregistered", "promoted", "walks", "wrong_provider", "manual"])
def test_invalid_critic_configuration_refuses_before_transport(configured, change):
    reg = configured / "config/llm_process_registry.json"
    pol = configured / "config/llm_routing_policy.json"
    registry, policy = json.loads(reg.read_text()), json.loads(pol.read_text())
    pid = routes.CRITIQUE_PROCESSES["grok"]
    cfg = next(r for r in registry["processes"] if r["id"] == pid)
    row = policy["policies"]["default"]["processes"][pid]
    if change == "unregistered":
        registry["processes"].remove(cfg)
    elif change == "promoted":
        cfg["anthropic_first"] = True
    elif change == "walks":
        row["transport_failover"] = True
    elif change == "wrong_provider":
        row["primary"]["provider"] = "anthropic"
    else:
        cfg["default_mode"] = "manual"
    reg.write_text(json.dumps(registry))
    pol.write_text(json.dumps(policy))
    with pytest.raises(routes.ProviderRefused):
        routes.call_role(
            "facts",
            role="grok",
            process_id=pid,
            manual_trigger=False,
            ceiling_usd=0,
            root=configured,
            bridge_call=lambda *a, **k: pytest.fail("dispatch"),
        )


def test_ambiguous_billable_response_preserves_unknown_cost(configured):
    def bridge(messages, **kwargs):
        data = response(kwargs)
        data["_tradeai"]["credit_usage_unknown"] = True
        return data

    out = routes.call_role(
        "facts",
        role="primary",
        process_id=routes.MANUAL_PROCESS,
        manual_trigger=True,
        ceiling_usd=0.2,
        root=configured,
        bridge_call=bridge,
    )
    assert out.evidence["cost_usage_known"] is False


def test_provider_failure_before_dispatch_has_known_zero(configured):
    def bridge(messages, **kwargs):
        return {"error": {"code": "COST_CAP_EXCEEDED"}}

    with pytest.raises(routes.ProviderRefused) as caught:
        routes.call_role(
            "facts",
            role="primary",
            process_id=routes.MANUAL_PROCESS,
            manual_trigger=True,
            ceiling_usd=0.2,
            root=configured,
            bridge_call=bridge,
        )
    assert caught.value.evidence["actual_cost_usd"] == 0
    assert caught.value.evidence["cost_usage_known"] is True


def fact():
    return research.make_fact(
        source="fixture.web",
        family="web",
        kind="thesis",
        subject_key=GUID,
        claim="Sourced case",
        as_of=NOW,
        citation={"url": "https://fixture.invalid/source"},
    )


def context():
    req = C.AskRequest(
        "Research Fixture",
        channel="cc",
        source_ref="fixture-request",
        depth="deep",
        entities=[C.EntityRef(name="Fixture", symbol="FIX", security_guid=GUID)],
    )
    return C.AskResearchContext(req, "fixture-thread", 1, budget=C.ResearchBudget(0.25))


def governor(cap=0.25):
    return research.CostGovernor(
        per_question_usd=cap, registered_fn=lambda _: True, check_fn=lambda *a, **k: {"allow": True}
    )


def test_default_pipeline_propagates_manual_flag_and_actual_costs(monkeypatch):
    calls = []

    def role(prompt, **kwargs):
        calls.append(kwargs)
        provider = "anthropic" if kwargs["role"] == "primary" else kwargs["role"]
        return routes.ProviderResult(
            response({"process_id": kwargs["process_id"], "request_id": "fixture"})["choices"][0]["message"]["content"],
            {
                "provider": provider,
                "model": OPUS if provider == "anthropic" else provider + "-actual",
                "actual_cost_usd": 0.01 if provider == "anthropic" else 0.002 if provider == "deepseek" else 0,
                "cost_usage_known": True,
            },
        )

    monkeypatch.setattr(routes, "call_role", role)
    answer = research.run_deep_research(
        context(),
        manual_trigger=True,
        sources=[research.SourceSpec("fixture", "web", lambda *a: [fact()])],
        governor=governor(),
        memory=None,
    )
    assert len(calls) == 4
    assert next(c for c in calls if c["role"] == "primary")["manual_trigger"] is True
    assert all(c["manual_trigger"] is False for c in calls if c["role"] != "primary")
    assert answer.cost_usd == pytest.approx(0.012)
    assert answer.provenance["cost_usage_known"] is True
    assert {r["evidence"]["provider"] for r in answer.provenance["panel"]} == {
        "anthropic",
        "deepseek",
        "grok",
        "chatgpt",
    }
    assert {s.provider for s in answer.sources if s.kind == "model"} == {"anthropic", "deepseek", "grok", "chatgpt"}


def test_scheduled_pipeline_never_claims_manual_origin(monkeypatch):
    calls = []

    def role(prompt, **kwargs):
        calls.append(kwargs)
        raise routes.ProviderRefused("fixture-refused")

    monkeypatch.setattr(routes, "call_role", role)
    answer = research.run_deep_research(
        context(),
        manual_trigger=False,
        process_id=routes.SCHEDULED_PROCESS,
        sources=[research.SourceSpec("fixture", "web", lambda *a: [fact()])],
        governor=governor(),
        memory=None,
    )
    assert all(call["manual_trigger"] is False for call in calls)
    assert next(c for c in calls if c["role"] == "primary")["process_id"] == routes.SCHEDULED_PROCESS
    assert answer.provenance["partial"] and answer.provenance["refusals"]
    assert answer.cost_usd == 0 and answer.provenance["cost_usage_known"] is True


def test_question_cap_binds_cumulative_panel_before_dispatch():
    called = []
    members = [
        research.PanelMember("primary", lambda _: called.append("primary") or "{}", 0.2),
        research.PanelMember("reviewer", lambda _: called.append("reviewer") or "{}", 0.1),
    ]
    opinions = research.run_panel("facts", members, governor(0.25), mbi_log=[])
    assert called == ["primary"]
    assert next(o for o in opinions if o["member"] == "reviewer")["refusal"] == "PER_QUESTION_CAP_EXCEEDED"


def test_evidence_only_collection_and_prepared_reuse_never_search_twice():
    ctx = context()
    calls = []
    sources = [research.SourceSpec("fixture", "web", lambda *a: calls.append(1) or [fact()])]
    prepared = research.collect_current_evidence(ctx.request, sources=sources, now=NOW, thread_id=ctx.thread_id)
    assert calls == [1] and len(prepared["fingerprint"]) == 64
    answer = research.run_deep_research(
        ctx, prepared_evidence=prepared, sources=sources, panel=[], governor=governor(), memory=None
    )
    assert calls == [1] and answer.provenance["source_runs"][0]["facts"] == 1
    assert answer.provenance["evidence_fingerprint"] == prepared["fingerprint"]


@pytest.mark.parametrize(
    "ok,reason,status",
    [(True, "EMPTY_RESULTS", "no_data"), (False, "ENGINE_DISABLED", "disabled"), (False, "BUDGET_REFUSED", "refused")],
)
def test_web_router_outcome_survives_empty_and_refused_searches(monkeypatch, ok, reason, status):
    receipt = {"receipt_id": "fixture-search"}
    mod = SimpleNamespace(
        route_query=lambda *a, **k: SimpleNamespace(
            ok=ok,
            reason=reason,
            results=[],
            provider="fixture-search-provider",
            cache_hit=True,
            receipt=receipt,
            reservation_id="fixture-reservation",
        )
    )
    monkeypatch.setattr(research, "_imp", lambda *a: mod)
    entity = research.Entity("Fixture", "listed", symbol="FIX", security_guid=GUID)
    result = research.gather_facts(
        [entity],
        [research.SourceSpec("web.search", "web", research._src_web)],
        research.ResearchContext("fixture", now=NOW),
    )
    run = result["runs"][0]
    assert run["status"] == status and run["reason"] == reason and run["provider"] == "fixture-search-provider"
    assert run["receipt"] == receipt and run["cache_hit"] is True
    assert result["gaps"][0]["reason"] == ("NO_DATA" if ok else reason)


def test_material_fingerprint_ignores_receipt_cache_and_retrieval_clock_changes():
    first = research.make_fact(
        source="web.fixture",
        family="web",
        kind="web",
        subject_key=GUID,
        claim="Same evidence",
        as_of=NOW,
        citation={"url": "https://fixture.invalid", "as_of_basis": "retrieved_at", "receipt": "old"},
    )
    second = research.make_fact(
        source="web.fixture",
        family="web",
        kind="web",
        subject_key=GUID,
        claim="Same evidence",
        as_of=NOW + timedelta(hours=1),
        citation={"url": "https://fixture.invalid", "as_of_basis": "retrieved_at", "receipt": "new"},
    )
    assert research.evidence_fingerprint([first], []) == research.evidence_fingerprint([second], [])


@pytest.mark.parametrize("result", [None, {}, {"ok": False}, {"accepted": False}, {"ok": True, "dry_run": True}])
def test_memory_requires_positive_applied_acknowledgement(tmp_path, result):
    mem = research.MemoryAppender(ledger_path=tmp_path / "ledger", apply=True, sink=lambda _: result)
    receipt = mem.append([research.Entity("Fixture", "listed", security_guid=GUID)], [fact()], {}, include_answer=False)
    assert receipt["planned_count"] == 1 and receipt["applied_count"] == receipt["appended"] == 0
    assert receipt["refused"] and not (tmp_path / "ledger").exists()


def test_memory_dry_run_is_planned_and_can_later_apply(tmp_path):
    entity = research.Entity("Fixture", "listed", security_guid=GUID)
    ledger = tmp_path / "ledger"
    dry = research.MemoryAppender(ledger_path=ledger, apply=False, sink=lambda _: {"ok": True})
    receipt = dry.append([entity], [fact()], {}, include_answer=False)
    assert receipt["planned_count"] == 1 and receipt["applied_count"] == 0 and not ledger.exists()
    applied = research.MemoryAppender(ledger_path=ledger, apply=True, sink=lambda _: {"accepted": True})
    receipt = applied.append([entity], [fact()], {}, include_answer=False)
    assert receipt["applied_count"] == receipt["appended"] == 1 and ledger.exists()
    assert applied.append([entity], [fact()], {}, include_answer=False)["skipped_duplicate"] == 1


def test_shared_and_server_owned_role_maps_match_without_importing_runtime():
    from scripts.lib.governed_process_routes import CALLER_TASK_PROCESS_MAP

    source = Path(research.__file__).with_name("cio_governed_model_bridge.py").read_bytes()
    assert source.count(b"\r\n") == source.count(b"\n")
    tree = ast.parse(source.decode())
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "CALLER_TASK_PROCESS_MAP"
    )
    assert ast.literal_eval(assignment.value) == CALLER_TASK_PROCESS_MAP


def test_retry_payload_includes_local_facts_but_never_enters_model_context(monkeypatch):
    private = research.make_fact(
        source="internal.fixture",
        family="internal",
        kind="held",
        subject_key=GUID,
        claim="Local-only fixture",
        as_of=NOW,
        citation={"store": "fixture"},
        egress="local_only",
    )
    answer = research.run_deep_research(
        context(),
        panel=[],
        governor=governor(),
        memory=None,
        sources=[research.SourceSpec("fixture", "internal", lambda *a: [fact(), private])],
    )
    payload = answer.provenance["memory_retry_payload"]
    assert len(payload["facts"]) == 2 and any(f["egress"] == "local_only" for f in payload["facts"])
    assert "memory_retry_payload" not in C.research_context_for_model(answer.to_dict())["provenance"]
    assert all(f["egress"] == "model_ok" for f in answer.provenance["facts"])


def test_memory_retry_reuses_canonical_writer_without_sources_or_models(monkeypatch, tmp_path):
    payload = {
        "entities": [research.Entity("Fixture", "listed", security_guid=GUID).to_dict()],
        "facts": [fact().to_dict()],
        "request_id": "fixture-request",
    }
    calls = []

    def factory(*, memory_apply=False):
        return research.MemoryAppender(
            ledger_path=tmp_path / "ledger",
            apply=memory_apply,
            sink=lambda envelope: calls.append(envelope) or {"accepted": True},
        )

    monkeypatch.setattr(research, "_default_deep_memory", factory)
    monkeypatch.setattr(research, "gather_facts", lambda *a, **k: pytest.fail("retry gathered"))
    monkeypatch.setattr(routes, "call_role", lambda *a, **k: pytest.fail("retry called model"))
    first = research.retry_research_memory(payload, apply=True)
    second = research.retry_research_memory(payload, apply=True)
    assert first["ok"] and first["applied_count"] == 1
    assert second["ok"] and second["applied_count"] == 0 and second["skipped_duplicate"] == 1
    assert len(calls) == 1 and calls[0]["predicate"] == "ask.source"


@pytest.mark.parametrize("value", [{}, {"facts": []}, {"entities": [], "facts": [{"bad": True}], "request_id": "x"}])
def test_missing_or_corrupt_memory_retry_stays_pending(value):
    receipt = research.retry_research_memory(value, apply=True)
    assert not receipt["ok"] and receipt["not_measured"] and receipt["status"] == "pending"


def test_panel_workers_keep_the_existing_retrieval_context():
    from scripts.lib.intelligence_context import set_current_context, current_context_id

    set_current_context({"context_id": "fixture-context"})
    seen = []
    try:
        research.run_panel(
            "facts",
            [research.PanelMember("fixture", lambda _: seen.append(current_context_id()) or "{}", 0)],
            governor(),
            mbi_log=[],
        )
    finally:
        set_current_context(None)
    assert seen == ["fixture-context"]


def test_executor_bound_process_set_cannot_be_escaped(configured, monkeypatch):
    monkeypatch.setenv("TRADEAI_LLM_PROCESS_ID", routes.SCHEDULED_PROCESS)
    with pytest.raises(routes.ProviderRefused, match="PROCESS_ROUTE_NOT_BOUND"):
        routes.call_role(
            "facts",
            role="grok",
            process_id=routes.CRITIQUE_PROCESSES["grok"],
            manual_trigger=False,
            ceiling_usd=0,
            root=configured,
            bridge_call=lambda *a, **k: pytest.fail("dispatch"),
        )


def test_fixed_loopback_client_forwards_manual_context_and_narrowing_budget(monkeypatch):
    from scripts.lib.intelligence_context import set_current_context

    seen = []

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, *args):
            return b'{"fixture": true}'

    def request(req, **kwargs):
        seen.append((req, kwargs))
        return Reply()

    monkeypatch.setattr(routes, "build_opener", lambda *a: SimpleNamespace(open=request))
    set_current_context({"context_id": "fixture-context"})
    try:
        out = routes._native_bridge_call(
            [{"role": "user", "content": "facts"}],
            process_id=routes.MANUAL_PROCESS,
            caller="advisory_desk",
            task_type=routes.MANUAL_PROCESS,
            request_id="fixture-request",
            timeout_s=5,
            max_tokens=32,
            manual_trigger=True,
            budget={"cost_ceiling_usd": 0.1},
        )
    finally:
        set_current_context(None)
    req, kwargs = seen[0]
    assert out == {"fixture": True} and req.full_url == "http://127.0.0.1:8766/v1/chat/completions"
    assert req.get_header("X-tradeai-context-id") == "fixture-context"
    assert req.get_header("X-tradeai-manual-trigger") == "1"
    assert json.loads(req.data)["budget"] == {"cost_ceiling_usd": 0.1}
    assert kwargs["timeout"] == 5


def test_successful_search_routing_cache_reason_is_not_a_material_change():
    old = [{"source": "web.search", "subject": "Fixture", "status": "ok", "reason": "CACHE_HIT"}]
    new = [{"source": "web.search", "subject": "Fixture", "status": "ok", "reason": "FREE_SUFFICIENT"}]
    assert research.evidence_fingerprint([fact()], old) == research.evidence_fingerprint([fact()], new)


def test_deepseek_critic_has_its_own_route_and_actual_model(configured):
    def bridge(messages, **kwargs):
        assert kwargs["process_id"] == routes.CRITIQUE_PROCESSES["deepseek"]
        assert kwargs["manual_trigger"] is False
        return response(kwargs, "deepseek", model="deepseek-flash", cost=0.002)

    result = routes.call_role(
        "facts",
        role="deepseek",
        process_id=routes.CRITIQUE_PROCESSES["deepseek"],
        manual_trigger=False,
        ceiling_usd=0.05,
        root=configured,
        bridge_call=bridge,
    )
    assert result.evidence["provider"] == "deepseek" and result.evidence["model"] == "deepseek-flash"


def test_prepared_evidence_accepts_child_request_id_but_binds_question_thread_and_entities():
    ctx = context()
    parent = ctx.request.to_dict()
    parent.update(request_id="old-parent-request", thread_id=ctx.thread_id)
    prepared = research.collect_current_evidence(
        parent, sources=[research.SourceSpec("fixture", "web", lambda *a: [fact()])]
    )
    # The actual scheduled child has a new source_ref/ask_id but the same research scope.
    ctx.request.source_ref = "auto:new-child"
    answer = research.run_deep_research(ctx, prepared_evidence=prepared, panel=[], governor=governor(), memory=None)
    assert answer.provenance["evidence_fingerprint"] == prepared["fingerprint"]
    for change in ("question", "thread", "entities"):
        altered = context()
        if change == "question":
            altered.request.question = "A different question"
        elif change == "thread":
            altered.thread_id = "different-thread"
        else:
            altered.request.entities[0].security_guid = "different-security"
        with pytest.raises(ValueError, match="PREPARED_EVIDENCE_REQUEST_MISMATCH"):
            research.run_deep_research(altered, prepared_evidence=prepared, panel=[], governor=governor(), memory=None)


def test_preprovider_budget_refusal_has_known_zero_native_requests():
    answer = research.run_deep_research(
        context(),
        panel=[research.PanelMember("fixture", lambda _: pytest.fail("dispatch"), est_usd=0.3)],
        sources=[research.SourceSpec("fixture", "web", lambda *a: [fact()])],
        governor=governor(),
        memory=None,
    )
    assert answer.provenance["native_request_count"] == 0
    assert answer.provenance["native_request_count_known"] is True


@pytest.mark.parametrize("review", [{}, {"status": "MISSING", "missing_reason": "cio_record_missing"}])
def test_missing_stored_review_clock_does_not_create_hourly_material_change(monkeypatch, review):
    from datetime import datetime, timedelta, timezone
    from scripts.lib.data_broker import cio_company_facts as projection

    review = dict(review)
    monkeypatch.setattr(projection, "load_snapshot", lambda root: {})
    monkeypatch.setattr(projection, "for_security", lambda *a, **k: {"company_facts": {}, "review_lifecycle": review})
    entity = research.Entity(label="Synthetic Example", kind="listed", symbol="DEMO", security_guid="fixture-guid")
    now = datetime(2031, 3, 10, 15, tzinfo=timezone.utc)
    first = research._src_cio_record_research(entity, research.ResearchContext(question="Synthetic review?", now=now))
    later = research._src_cio_record_research(
        entity, research.ResearchContext(question="Synthetic review?", now=now + timedelta(hours=1))
    )
    assert research.evidence_fingerprint(first, []) == research.evidence_fingerprint(later, [])
    review["completed_at"] = "2031-03-10T16:00:00Z"
    changed = research._src_cio_record_research(
        entity, research.ResearchContext(question="Synthetic review?", now=now + timedelta(hours=1))
    )
    assert research.evidence_fingerprint(first, []) != research.evidence_fingerprint(changed, [])


@pytest.mark.parametrize(
    "field",
    [
        None,
        "section.position_and_plan",
        "section.business_and_moat",
        "scenario_bear_price",
        "cio_conviction_at_writing",
    ],
)
def test_inherited_prospectus_prose_stays_local_in_real_panel_prompt(monkeypatch, field):
    from types import SimpleNamespace
    from scripts.lib import cio_ask_research as research

    ent = research.Entity(label="Example Robotics", kind="listed", symbol="EXMP", security_guid="fixture-guid")
    claim = "We own 317 shares bought at $42; private fixture position"
    original = research.make_fact(
        source="internal.prospectus",
        family="internal",
        kind="prospectus",
        subject_key=ent.subject_key,
        symbol=ent.symbol,
        claim=claim,
        as_of="2026-10-26T14:00:00Z",
        citation={"store": "security_research_spine", "version": "fixture"},
        field=field,
    )
    real_import = research._imp

    def source_import(*names):
        if "lib.prospectus.cio_memory" in names:
            return SimpleNamespace(ask_facts=lambda *_: [original])
        return real_import(*names)

    monkeypatch.setattr(research, "_imp", source_import)
    facts = research._src_prospectus(ent, research.ResearchContext(question="What changed?"))
    assert original.egress == "model_ok", "shared producer objects must not be mutated"
    assert len(facts) == 1 and facts[0].egress == "local_only"
    assert facts[0].fact_id == original.fact_id and facts[0].claim == claim
    assert facts[0].citation == original.citation and facts[0].as_of == original.as_of
    public = research.make_fact(
        source="market.fixture",
        family="market",
        kind="price",
        subject_key=ent.subject_key,
        claim="Public fixture quote",
        as_of="2026-10-26T14:00:00Z",
        citation={"ref": "fixture"},
        value=21.5,
        unit="usd",
    )
    prompt = research.build_panel_prompt("What changed?", [ent], facts + [public])
    assert "317" not in prompt and "private fixture position" not in prompt
    assert "Public fixture quote" in prompt
