"""Unmatched conflicts -> AI-proposed rule -> operator approval (docs/ops/CONFLICT_RULE_PROPOSALS.md).

Hermetic: tmp state roots, the governed bridge is a stub (no model call), the comms intent queue is a stub (no send),
no network, no database, MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from scripts.lib.cio_ask_api import Ctx
from scripts.lib.conflicts import proposals as P
from scripts.lib.conflicts import proposals_api as API
from scripts.lib.conflicts.adapters import evaluate_inputs, security_inputs
from scripts.lib.conflicts.engine import Input, Subject
from scripts.lib.conflicts.adapters import EvaluationInputs

NOW = datetime(2026, 10, 23, 19, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def bundle(label="FOO_BAR", *, guid="guid-a", symbol="AAA", held=False, role="claim", source="desk", canonical="WATCH"):
    return security_inputs(security_guid=guid, symbol=symbol, held=held,
                           canonical={"stance": canonical, "as_of": NOW.isoformat()},
                           extras=[Input(source, label, NOW, role=role)])


def unmatched_for(b, findings=None):
    findings = evaluate_inputs(b, now=NOW) if findings is None else findings
    return P.detect_unmatched(b, findings)


def ctx(principal="tailnet:operator@example.com", listener="serve_proxy", csrf=True):
    return Ctx(principal=lambda: principal, listener=lambda: listener,
               csrf=lambda *_: (csrf, "fixture"), allowed_logins=frozenset({"operator@example.com"}))


def config(**caps):
    doc = P.load_config()
    doc["caps"] = {**doc["caps"], **caps}
    return doc


def answer(row, **over):
    keys = [e["key"] for e in row["examples"]]
    body = {"plain_rule": "Treat FOO BAR from the desk as the same stance as WATCH.", "tier": "T4",
            "proposed_resolution": [{"finding_key": k, "resolution": "Map the label and re-evaluate."} for k in keys],
            "machine_form": {"op": "vocabulary_alias", "label": row["pattern"].get("label", "X"), "maps_to": "WATCH"},
            "never_auto_implications": "None; this is a judgment-tier vocabulary label.",
            "test_cases": [{"inputs": {"desk": "FOO_BAR", "canonical": "WATCH", "held": False},
                            "expected": {"kind": "AGREEMENT"}}],
            "risks": ["The desk may mean something stronger than WATCH."], "citations": ["F1", "F4"], "confidence": 0.8}
    body.update(over)
    return body


def stub_call(answers, calls=None, cost=0.0):
    """Governed bridge stand-in: returns the next canned answer in the live `_tradeai` envelope shape."""
    def call(messages, **kw):
        if calls is not None:
            calls.append({"messages": messages, **kw})
        content = answers.pop(0)
        return {"choices": [{"message": {"content": json.dumps(content) if not isinstance(content, str) else content}}],
                "_tradeai": {"governance_pass": True, "process_id": "conflict_rule_proposal", "reservation_id": "r1",
                             "model_id": "grok-oauth", "provider": "grok", "cost_estimate": cost, "request_id": "q1",
                             "routing_decision": {"lane_chosen": "grok"}}}
    return call


def seed(root, *bundles_):
    rows = [u for b in bundles_ for u in unmatched_for(b)]
    P.record_unmatched(root, rows, at=NOW, run_id="seed")
    return rows


def created(root, label="FOO_BAR", **kw):
    seed(root, bundle(label))
    row = next(iter(P.ProposalStore(root).state()["patterns"].values()))
    report = P.propose(root, now=NOW, apply=True, governed_call=stub_call([answer(row, **kw)]), run_id="job")
    assert report["created"], report
    return report["created"][0]


# ── 1. unmatched detection ───────────────────────────────────────────────────────────────────────────────────────


def test_unmapped_label_becomes_unmatched_never_auto_and_engine_finding_is_kept():
    b = bundle("FOO_BAR")
    findings = evaluate_inputs(b, now=NOW)
    rows = P.detect_unmatched(b, findings)
    assert [f.kind for f in findings] == ["DATA_ERROR"]          # the engine's own flag still shows on the card
    assert len(rows) == 1 and rows[0]["kind"] == "UNMATCHED" and rows[0]["never_auto"] is True
    assert rows[0]["proposal_status"] == "AI proposal pending" and rows[0]["pattern"]["gap"] == "vocabulary_unmapped"
    assert rows[0]["policy"]["tier"] == "T4" and rows[0]["policy"]["never_auto"] is False
    r8 = unmatched_for(bundle("ADD_ON_PULLBACK"))[0]
    assert r8["pattern"]["r8_listed"] is True


def test_known_labels_and_agreement_are_not_unmatched():
    assert unmatched_for(bundle("ADD")) == []
    assert unmatched_for(bundle("AVOID")) == []


def test_unknown_gate_role_vocabulary_is_unmatched_at_its_tier():
    row = unmatched_for(bundle("SOMETHING_NEW", role="gate", source="trade_ai"))[0]
    assert row["pattern"] == {"domain": "security_stance", "subject_kind": "security", "gap": "vocabulary_unknown",
                              "role": "gate", "label": "SOMETHING_NEW"}
    assert row["policy"]["tier"] == "T3"
    protection = unmatched_for(bundle("WOBBLY", role="protection", source="stop", held=True, canonical="HOLD"))[0]
    assert protection["policy"]["never_auto"] is True and "protection" in protection["policy"]["categories"]


def test_dropped_fact_input_unknown_role_and_unknown_domain_are_unmatched():
    fact = unmatched_for(bundle("ADD", role="fact", source="broker_positions", held=True, canonical="HOLD"))
    assert [r["pattern"]["gap"] for r in fact] == ["uncovered_input"] and fact[0]["policy"]["tier"] == "T1"
    weird = bundle("ADD", role="vibes", source="hermes")
    assert any(r["pattern"]["gap"] == "unknown_role" for r in P.detect_unmatched(weird, []))

    class SectorProfile:
        name = "sector_posture"
    other = EvaluationInputs(Subject("sector", "tech", "Tech"), None, [], SectorProfile())
    rows = P.detect_unmatched(other, [])
    assert rows[0]["pattern"]["gap"] == "unknown_domain" and rows[0]["never_auto"] is True


def test_nway_split_without_an_r11_finding_is_unmatched_and_r11_covers_it():
    b = security_inputs(security_guid="g", symbol="S", held=True, canonical={"stance": "HOLD", "as_of": NOW.isoformat()},
                        extras=[Input("desk", "ADD", NOW), Input("advisory_desk", "TRIM", NOW), Input("hermes", "EXIT", NOW)])
    rows = P.detect_unmatched(b, [])
    nway = [r for r in rows if r["pattern"]["gap"] == "nway_uncovered"]
    assert len(nway) == 1 and nway[0]["pattern"]["owner_side"] is True
    assert "nway_recorded_split" in nway[0]["policy"]["categories"] and nway[0]["never_auto"]
    covered = [{"kind": "CONFLICT", "rule": "R11", "key": "security:g:R11", "sides": [
        {"source": s} for s in ("desk", "advisory_desk", "hermes")]}]
    assert not [r for r in P.detect_unmatched(b, covered) if r["pattern"]["gap"] == "nway_uncovered"]


# ── 2. dedupe, rate limits, LLM stub, schema ─────────────────────────────────────────────────────────────────────


def test_dedupe_by_pattern_not_row(tmp_path):
    rows = seed(tmp_path, bundle("FOO_BAR", guid="g1", symbol="A"), bundle("FOO_BAR", guid="g2", symbol="B"))
    assert len({r["signature"] for r in rows}) == 1
    state = P.ProposalStore(tmp_path).state()
    assert len(state["patterns"]) == 1 and len(next(iter(state["patterns"].values()))["examples"]) == 2
    before = len(state["events"])
    P.record_unmatched(tmp_path, rows, at=NOW + timedelta(minutes=15), run_id="again")
    assert len(P.ProposalStore(tmp_path).state()["events"]) == before   # same keys inside the refresh window: no row


def test_dry_run_is_write_free_and_never_calls_a_model(tmp_path):
    seed(tmp_path, bundle("FOO_BAR"))
    before = (tmp_path / "data/conflicts/rule_proposals.jsonl").read_bytes()

    def boom(*a, **k):
        raise AssertionError("model called in dry run")
    report = P.propose(tmp_path, now=NOW, apply=False, governed_call=boom)
    assert report["model_calls"] == 0 and report["skipped"][0]["reason"] == "dry_run"
    assert (tmp_path / "data/conflicts/rule_proposals.jsonl").read_bytes() == before


def test_stubbed_llm_produces_schema_complete_pending_proposal(tmp_path):
    calls = []
    seed(tmp_path, bundle("FOO_BAR"))
    row = next(iter(P.ProposalStore(tmp_path).state()["patterns"].values()))
    report = P.propose(tmp_path, now=NOW, apply=True, governed_call=stub_call([answer(row)], calls), run_id="job")
    proposal = P.ProposalStore(tmp_path).state()["proposals"][report["created"][0]]
    required = {"proposal_id", "signature", "example_findings", "plain_rule", "tier", "proposed_resolution",
                "machine_form", "patch", "never_auto_implications", "test_cases", "risks", "model", "route",
                "created_at", "status"}
    assert required <= set(proposal) and proposal["status"] == "PENDING" and proposal["schema"] == "RuleProposal@v1"
    assert proposal["patch"] == [{"op": "add", "path": "/amendments/vocabulary_aliases/FOO_BAR", "value": "WATCH"}]
    assert proposal["auto_resolvable"] is True and proposal["model"]["model_id"] == "grok-oauth"
    assert calls[0]["process_id"] == "conflict_rule_proposal" and calls[0]["task_type"] == "conflict_rule_proposal"
    facts = json.loads(calls[0]["messages"][1]["content"].split("\n", 1)[1])
    assert set(facts) >= {"F1", "F2", "F3", "F4", "F5"}       # matrix F6 only when its bytes match matrix_sha256
    assert report["matrix_gap"]


def test_matrix_supplied_only_when_hash_matches(tmp_path):
    cfg = P.load_config()
    path = tmp_path / cfg["matrix_rel"]
    path.parent.mkdir(parents=True)
    path.write_text("not the matrix")
    assert P.matrix_text(tmp_path, cfg, P._rulebook())[0] is None
    real = Path.home() / "trade-ai-releases/persistent-state" / cfg["matrix_rel"]
    if real.exists() and hashlib.sha256(real.read_bytes()).hexdigest() == P._rulebook()["matrix_sha256"]:
        path.write_bytes(real.read_bytes())
        assert P.matrix_text(tmp_path, cfg, P._rulebook())[0]


@pytest.mark.parametrize("override, reason", [
    ({"citations": ["F9"]}, "ungrounded"),
    ({"plain_rule": "Treat FOO BAR as WATCH for 37 days at least."}, "ungrounded_number"),
    ({"machine_form": {"op": "replace", "path": "/never_auto", "value": []}}, "machine_form_refused"),
    ({"machine_form": {"op": "vocabulary_alias", "label": "FOO_BAR", "maps_to": "ADD_ON_PULLBACK"}}, "machine_form_refused"),
    ({"tier": "T9"}, "schema_invalid"),
])
def test_invalid_model_answers_fail_closed(tmp_path, override, reason):
    seed(tmp_path, bundle("FOO_BAR"))
    row = next(iter(P.ProposalStore(tmp_path).state()["patterns"].values()))
    report = P.propose(tmp_path, now=NOW, apply=True, governed_call=stub_call([answer(row, **override)]))
    assert not report["created"] and report["failed"][0]["reason"] == reason
    assert not P.ProposalStore(tmp_path).state()["proposals"]


def test_rate_limits_per_run_daily_and_attempts(tmp_path):
    for n in range(4):
        seed(tmp_path, bundle(f"NEW_LABEL_{chr(65 + n)}", guid=f"g{n}", symbol=f"S{n}"))
    rows = list(P.ProposalStore(tmp_path).state()["patterns"].values())
    report = P.propose(tmp_path, now=NOW, apply=True, config=config(max_proposals_per_run=2),
                       governed_call=stub_call([answer(r) for r in rows]))
    assert len(report["created"]) == 2 and {s["reason"] for s in report["skipped"]} == {"max_proposals_per_run"}
    capped = P.propose(tmp_path, now=NOW, apply=True, config=config(daily_proposal_cap=2),
                       governed_call=stub_call([]))
    assert not capped["created"] and {s["reason"] for s in capped["skipped"]} == {"daily_proposal_cap"}
    # a failing signature is retried at most max_attempts_per_signature_per_day times
    bad = [answer(rows[2], citations=["F99"]) for _ in range(5)]
    first = P.propose(tmp_path, now=NOW, apply=True, config=config(max_proposals_per_run=1), governed_call=stub_call(bad))
    P.propose(tmp_path, now=NOW, apply=True, config=config(max_proposals_per_run=1), governed_call=stub_call(bad))
    third = P.propose(tmp_path, now=NOW, apply=True, config=config(max_proposals_per_run=1), governed_call=stub_call(bad))
    assert first["failed"] and any(s["reason"] == "max_attempts_per_signature_per_day" for s in third["skipped"])


def test_daily_cost_cap_and_offpeak_deferral_stop_calls(tmp_path):
    seed(tmp_path, bundle("FOO_BAR"), bundle("BAR_BAZ", guid="g2", symbol="B"))
    rows = list(P.ProposalStore(tmp_path).state()["patterns"].values())
    report = P.propose(tmp_path, now=NOW, apply=True, config=config(daily_cost_cap_usd=0.01),
                       governed_call=stub_call([answer(r) for r in rows], cost=0.02))
    assert len(report["created"]) == 1 and report["skipped"][0]["reason"] == "daily_cost_cap_usd"

    class Defer:
        defer, run_after = True, "2026-10-24T03:00:00+00:00"
    seed(tmp_path, bundle("QUUX", guid="g3", symbol="C"))
    deferred = P.propose(tmp_path, now=NOW + timedelta(days=1), apply=True, deferral=lambda pid: Defer(),
                         governed_call=stub_call([]))
    assert deferred["model_calls"] == 0 and deferred["skipped"][0]["reason"] == "offpeak_deferred"


def test_per_call_cost_ceiling_refuses(tmp_path):
    seed(tmp_path, bundle("FOO_BAR"))
    row = next(iter(P.ProposalStore(tmp_path).state()["patterns"].values()))
    report = P.propose(tmp_path, now=NOW, apply=True, governed_call=stub_call([answer(row)], cost=0.5))
    assert report["failed"][0]["reason"] == "over_cap"


# ── 3. operator-only decision, amendment, never-auto, reject ─────────────────────────────────────────────────────


def url(pid):
    return f"/api/v3/conflicts/proposals/{pid}/decision"


def revision(root, pid):
    return P.ProposalStore(root).state()["proposals"][pid]["revision"]


@pytest.mark.parametrize("identity", ["service-token", "n8n", "agent", "tailnet:unknown@example.com", ""])
def test_agents_refused_before_any_write(tmp_path, identity):
    pid = created(tmp_path)
    before = (tmp_path / "data/conflicts/rule_proposals.jsonl").read_bytes()
    status, out = API.handle(url(pid), "POST", {"decision": "approve", "reason": "x", "expected_revision": 1},
                             ctx=ctx(identity), root=tmp_path, write_enabled=True, now=NOW)
    assert status == 403 and out["error"] == "AGENT_CALLER_REFUSED"
    assert (tmp_path / "data/conflicts/rule_proposals.jsonl").read_bytes() == before
    assert not (tmp_path / "data/conflicts/rulebook_amendments.jsonl").exists()


def test_csrf_activation_and_revision_guards(tmp_path):
    pid = created(tmp_path)
    good = {"decision": "approve", "reason": "matches desk usage", "expected_revision": revision(tmp_path, pid)}
    assert API.handle(url(pid), "POST", good, ctx=ctx(csrf=False), root=tmp_path, write_enabled=True)[0] == 403
    status, out = API.handle(url(pid), "POST", good, ctx=ctx(), root=tmp_path)   # config default: not activated
    assert status == 503 and out["error"] == "PROPOSAL_DECISIONS_NOT_ACTIVATED"
    stale = {**good, "expected_revision": 999}
    assert API.handle(url(pid), "POST", stale, ctx=ctx(), root=tmp_path, write_enabled=True)[1]["error"] == "PROPOSAL_CHANGED"
    assert API.handle(url(pid), "POST", {**good, "actor": "me"}, ctx=ctx(), root=tmp_path,
                      write_enabled=True)[1]["error"] == "UNKNOWN_OR_ACTOR_FIELD"


def test_approval_appends_amendment_bumps_version_and_preserves_matrix_hash(tmp_path):
    base = json.loads((ROOT / "config/conflict_rulebook.json").read_text())
    pid = created(tmp_path)
    status, out = API.handle(url(pid), "POST", {"decision": "approve", "reason": "desk FOO BAR means watch",
                                                "expected_revision": revision(tmp_path, pid), "apply_current_case": True},
                             ctx=ctx(), root=tmp_path, write_enabled=True, now=NOW + timedelta(hours=1))
    assert status == 200, out
    amendment = out["amendment"]
    assert amendment["amendment_id"] == "A1" and amendment["proposal_id"] == pid
    assert amendment["provenance"]["approved_by"] == "tailnet:operator@example.com"
    assert amendment["provenance"]["reason"] == "desk FOO BAR means watch"
    assert amendment["base"]["matrix_sha256"] == base["matrix_sha256"]
    body = {k: v for k, v in amendment.items() if k != "sha256"}
    assert hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest() == amendment["sha256"]
    rulebook = out["rulebook"]
    assert rulebook["version"] == f"{base['version']}.1" and rulebook["matrix_sha256"] == base["matrix_sha256"]
    assert rulebook["amendments"][0]["sha256"] == amendment["sha256"]
    assert out["proposal"]["status"] == "APPROVED" and out["current_case"]["applied"] is True
    # the base rulebook file is never written
    assert json.loads((ROOT / "config/conflict_rulebook.json").read_text()) == base
    # re-evaluation on the next run: the label now maps, so no UNMATCHED and no vocabulary DATA_ERROR
    effective = P.effective_rulebook(tmp_path)
    findings, unmatched = P.evaluate(bundle("FOO_BAR"), now=NOW, effective=effective)
    assert unmatched == [] and [f.kind for f in findings] == ["AGREEMENT"]
    # a second decision is refused; the store is append-only
    again = API.handle(url(pid), "POST", {"decision": "reject", "reason": "no", "expected_revision": revision(tmp_path, pid)},
                       ctx=ctx(), root=tmp_path, write_enabled=True)
    assert again[1]["error"] == "PROPOSAL_NOT_PENDING"


def test_tampered_amendment_chain_fails_closed(tmp_path):
    pid = created(tmp_path)
    P.decide(tmp_path, pid, decision="approve", reason="ok", actor="tailnet:operator@example.com", at=NOW)
    path = tmp_path / "data/conflicts/rulebook_amendments.jsonl"
    path.write_text(path.read_text().replace("WATCH", "ADD"))
    with pytest.raises(ValueError):
        P.effective_rulebook(tmp_path)


def test_never_auto_pattern_can_be_proposed_but_never_approved_auto(tmp_path):
    seed(tmp_path, bundle("ADD", role="fact", source="broker_positions", held=True, canonical="HOLD"))
    row = next(iter(P.ProposalStore(tmp_path).state()["patterns"].values()))
    assert row["policy"]["never_auto"] is True
    report = P.propose(tmp_path, now=NOW, apply=True, governed_call=stub_call([answer(
        row, plain_rule="Broker position facts older than the desk are superseded.",
        machine_form={"op": "source_supersede_days", "source": "broker_positions", "days": 2})]))
    pid = report["created"][0]
    proposal = P.ProposalStore(tmp_path).state()["proposals"][pid]
    assert proposal["auto_resolvable"] is False and proposal["tier"] == "T1"
    assert proposal["never_auto_implications"].startswith("Computed: T1 never-auto")
    status, out = API.handle(url(pid), "POST", {"decision": "approve", "reason": "fine",
                                                "expected_revision": revision(tmp_path, pid)},
                             ctx=ctx(), root=tmp_path, write_enabled=True)
    assert status == 409 and out["error"] == "NEVER_AUTO_REFUSED" and "never resolves it automatically" in out["reason"]
    assert not (tmp_path / "data/conflicts/rulebook_amendments.jsonl").exists()
    # edit-and-approve as route-to-owner is allowed and routes the pattern to the operator on the next run
    status, out = API.handle(url(pid), "POST", {"decision": "edit-and-approve", "reason": "I decide these",
                                                "expected_revision": revision(tmp_path, pid),
                                                "edited": {"machine_form": {"op": "route_to_owner", "owner": "operator",
                                                                            "kind": "NEEDS_OPERATOR"}, "tier": "T4"}},
                             ctx=ctx(), root=tmp_path, write_enabled=True)
    assert status == 200 and out["amendment"]["rule"]["auto_resolvable"] is False
    assert out["amendment"]["rule"]["tier"] == "T1"             # never looser than the computed tier
    findings, unmatched = P.evaluate(bundle("ADD", role="fact", source="broker_positions", held=True, canonical="HOLD"),
                                     now=NOW, effective=P.effective_rulebook(tmp_path))
    assert unmatched == [] and findings[-1].kind == "NEEDS_OPERATOR" and findings[-1].rule == "A1"
    assert findings[-1].never_auto is True


def test_reject_path_records_reason_and_cools_down(tmp_path):
    pid = created(tmp_path)
    status, out = API.handle(url(pid), "POST", {"decision": "reject", "reason": "the desk label is noise",
                                                "expected_revision": revision(tmp_path, pid)},
                             ctx=ctx(), root=tmp_path, write_enabled=True, now=NOW)
    assert status == 200 and out["amendment"] is None and out["proposal"]["status"] == "REJECTED"
    assert out["proposal"]["decision"]["reason"] == "the desk label is noise"
    assert not (tmp_path / "data/conflicts/rulebook_amendments.jsonl").exists()
    state = P.ProposalStore(tmp_path).state()
    assert P.due_patterns(state, now=NOW + timedelta(days=1), config=P.load_config()) == []
    assert P.due_patterns(state, now=NOW + timedelta(days=15), config=P.load_config())


# ── 4. grouped notification ──────────────────────────────────────────────────────────────────────────────────────


def test_one_grouped_notification_for_new_pending_proposals(tmp_path):
    seed(tmp_path, bundle("FOO_BAR"), bundle("BAR_BAZ", guid="g2", symbol="B"))
    rows = list(P.ProposalStore(tmp_path).state()["patterns"].values())
    P.propose(tmp_path, now=NOW, apply=True, governed_call=stub_call([answer(r) for r in rows]))
    sent = []
    result = P.notify_pending(tmp_path, now=NOW, run_id="r1", queue=lambda **kw: sent.append(kw) or {"intent_id": "i1"})
    assert result["queued"] and len(sent) == 1 and len(result["proposal_ids"]) == 2
    assert sent[0]["kind"] == "rule_proposals_pending" and sent[0]["producer"] == "conflict_rule_proposals"
    assert "2 proposed conflict rules awaiting your approval" in sent[0]["summary"]
    assert P.load_config()["notify"]["page_url"] in sent[0]["summary"]
    assert P.notify_pending(tmp_path, now=NOW, run_id="r2", queue=lambda **kw: sent.append(kw))["reason"] == "nothing_new"
    assert len(sent) == 1


def test_unrouted_notification_is_recorded_and_retried(tmp_path):
    created(tmp_path)

    class Unrouted(Exception):
        reason = "intent_unrouted"

    def refuse(**kw):
        raise Unrouted()
    assert P.notify_pending(tmp_path, now=NOW, run_id="r1", queue=refuse) == {"queued": False, "reason": "intent_unrouted"}
    assert any(e["event"] == "notify_failed" for e in P.ProposalStore(tmp_path).events())
    sent = []
    assert P.notify_pending(tmp_path, now=NOW, run_id="r2", queue=lambda **kw: sent.append(kw) or {})["queued"]


# ── 5. resolver hook + read API ──────────────────────────────────────────────────────────────────────────────────


def test_resolver_shadow_records_unmatched_and_dry_run_writes_nothing(tmp_path, monkeypatch):
    from scripts.conflict_resolver import run
    dry = run(tmp_path / "absent", [bundle("FOO_BAR")], now=NOW, run_id="dry")
    assert dry["unmatched_count"] == 1 and dry["unmatched"][0]["kind"] == "UNMATCHED"
    assert not (tmp_path / "absent").exists()
    monkeypatch.setenv("TRADEAI_RUN_ID", "shadow-1")
    report = run(tmp_path, [bundle("FOO_BAR")], now=NOW, shadow=True, run_id="shadow-1", memory_writer=lambda e: True)
    assert report["unmatched_count"] == 1 and report["notifications"] == 0
    state = P.ProposalStore(tmp_path).state()
    assert len(state["patterns"]) == 1


def test_list_shape_for_the_page(tmp_path):
    pid = created(tmp_path)
    seed(tmp_path, bundle("NOT_YET_PROPOSED", guid="g9", symbol="Z"))
    status, data = API.handle("/api/v3/conflicts/proposals", "GET", query={"status": ["PENDING"]}, root=tmp_path)
    assert status == 200 and data["schema"] == "RuleProposalCollection@v1"
    assert [p["proposal_id"] for p in data["proposals"]] == [pid] and data["counts"]["pending"] == 1
    assert data["counts"]["unmatched_awaiting_ai"] == 1 and data["decisions_enabled"] is False
    assert {u["proposal_status"] for u in data["unmatched"]} == {"AI proposal pending", "Proposed rule awaiting your approval"}
    assert data["rulebook"]["version"].endswith(".0") and "overlay" not in data["rulebook"]
    assert API.handle(f"/api/v3/conflicts/proposals/{pid}", "GET", root=tmp_path)[1]["proposal_id"] == pid
    assert API.handle("/api/v3/conflicts/proposals", "GET", query={"status": "BOGUS"}, root=tmp_path)[0] == 400
    assert API.handle("/api/v3/conflicts/other", "GET", root=tmp_path) is None


def test_api_v2_routes_proposals_before_the_conflict_key_catch_all():
    text = (ROOT / "scripts/api_v2.py").read_text()
    assert text.index('"/api/v3/conflicts/proposals"') < text.index('base_path.rstrip("/") == "/api/v3/conflicts" or')
