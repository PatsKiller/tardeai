"""Synthetic canonical JSON -> default operator API -> ledger -> Home readback.

No production state, SQL, providers, subprocesses, network or live HTTP is read.
The default API provider runs the real narrow file reader against a tmp root.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2032, 4, 12, 14, tzinfo=timezone.utc)
AS_OF = "2032-04-12T13:59:00Z"
SCOPE, BUDGET = "scope_synthetic_a", "single_sector_pct"
ACTOR = "tailnet:fixture-operator@example.test"


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def forbidden(*args, **kwargs):
    pytest.fail("Narrow budget source reached network, process, DB, ledger or Home hydration")


@pytest.fixture
def rig(tmp_path, monkeypatch):
    core = load("budget_source_core_under_test", "scripts/lib/operator_approvals.py")
    api = load("budget_source_api_under_test", "scripts/lib/operator_approvals_api.py")
    book = load("budget_source_join_under_test", "scripts/lib/market_risk_book_join.py")
    home = load("budget_source_home_under_test", "scripts/lib/market_risk_home_context.py")
    projection = load("budget_source_projection_under_test", "scripts/lib/market_risk_projection.py")
    api.core = core
    import scripts.lib as package

    monkeypatch.setattr(package, "operator_approvals", core)
    monkeypatch.setattr(package, "market_risk_book_join", book, raising=False)
    imports = {"market_risk_projection": projection, "market_risk_home_context": home}
    home_wrapper = book.home_context
    monkeypatch.setattr(book, "_import", lambda name: imports[name])
    for name in ("_ro_conn", "home_context", "join", "home_actions"):
        monkeypatch.setattr(book, name, forbidden)
    monkeypatch.setattr(home, "collect", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    state = tmp_path / "canonical-state"
    snapshot_path = state / projection.SNAPSHOT_REL
    assessment_path = state / "data/runtime/market_risk/latest.json"
    snapshot = {
        "schema": "MarketRiskSnapshot@v1",
        "as_of": AS_OF,
        "mode": "live",
        "tier": "YELLOW",
        "score": 50,
        "categories": [],
        "positions": {},
        "book": {"budget_breaches": [BUDGET]},
    }
    assessment = {
        "schema": "MarketRiskAssessment@v1",
        "as_of": AS_OF,
        "mode": "live",
        "tier": "YELLOW",
        "score": 50,
        "portfolio": {
            "budget_breaches": [
                {
                    "scope": SCOPE,
                    "budget": BUDGET,
                    "actual": 40,
                    "limit": 30,
                    "unit": "%",
                    "breached": True,
                    "account_label": "Synthetic display label",
                }
            ]
        },
    }

    def write():
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        assessment_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(snapshot))
        assessment_path.write_text(json.dumps(assessment))

    write()
    clock, approved = [NOW], [True]
    leaf = book.budget_presentation_snapshot
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setattr(core, "utc_now", lambda: clock[0])
    ledger = core.DecisionLedger(
        tmp_path / "operator-store/operator_decisions.jsonl", approved=lambda: approved[0], clock=lambda: clock[0]
    )
    ctx = api.Ctx(
        principal=lambda: ACTOR,
        listener=lambda: "serve_proxy",
        csrf=lambda *args: (True, ""),
        allowed_logins=frozenset({"fixture-operator@example.test"}),
        sources={},
        ledger=ledger,
        policy=lambda: {},
        clock=lambda: clock[0],
        can_read=lambda: True,
        budget_snapshot=api.default_budget_snapshot,
    )
    return SimpleNamespace(
        core=core,
        api=api,
        book=book,
        home=home,
        projection=projection,
        state=state,
        snapshot_path=snapshot_path,
        assessment_path=assessment_path,
        snapshot=snapshot,
        assessment=assessment,
        clock=clock,
        approved=approved,
        ledger=ledger,
        ctx=ctx,
        leaf=leaf,
        write=write,
        home_wrapper=home_wrapper,
    )


def get(rig, scope=SCOPE):
    return rig.api.handle(
        rig.api.PREFIX + "/budget-presentation", "GET", query={"scope_id": scope, "budget": BUDGET}, ctx=rig.ctx
    )


def acknowledge(rig, binding, *, scope=SCOPE, dry_run=False):
    return rig.api.handle(
        rig.api.PREFIX + "/budget-presentation/decide",
        "POST",
        {
            "subtype": "market_risk_budget_presentation",
            "action": "intentional_until",
            "scope_id": scope,
            "budget": BUDGET,
            "source_binding": binding,
            "intentional_until": "2032-04-12T14:05:00Z",
            "request_id": "synthetic_source_request_001",
            "dry_run": dry_run,
        },
        ctx=rig.ctx,
    )


def home_result(rig, scope=SCOPE, *, decision_rows="read", store_approved=True):
    raw = rig.leaf(scope_id=scope, budget=BUDGET, now=rig.clock[0], root=rig.state)
    projection = rig.projection.build(copy.deepcopy(rig.snapshot), None, now=rig.clock[0])
    context = rig.home.build(projection, {"budgets_detail": [raw]}, now=rig.clock[0])
    rows = rig.ledger.rows() if decision_rows == "read" else decision_rows
    enriched = rig.home.with_budget_presentation(
        context, projection, decision_rows=rows, store_approved=store_approved, now=rig.clock[0]
    )
    return raw, projection, context, enriched


def test_narrow_source_never_hydrates_home_or_reads_ledger(rig, monkeypatch):
    monkeypatch.setattr(rig.core.DecisionLedger, "rows", forbidden)
    before = (rig.snapshot_path.read_bytes(), rig.assessment_path.read_bytes())
    row = rig.leaf(scope_id=SCOPE, budget=BUDGET, now=NOW, root=rig.state)
    assert row["scope_id"] == SCOPE and row["budget"] == BUDGET
    assert row["actual"] == 40 and row["limit"] == 30 and row["breached"] is True
    assert row["source_mode"] == "live" and row["source_status"] == "evaluated" and row["stale"] is False
    assert row["source_binding"]["as_of"] == AS_OF and len(row["source_binding"]["sha256"]) == 64
    assert before == (rig.snapshot_path.read_bytes(), rig.assessment_path.read_bytes())
    assert not rig.ledger.path.parent.exists()


def test_default_api_ack_and_home_readback_share_binding_without_changing_budget(rig):
    before = (rig.snapshot_path.read_bytes(), rig.assessment_path.read_bytes())
    status, observed = get(rig)
    assert status == 200, observed
    binding = observed["data"]["current"]["source_binding"]
    status, preview = acknowledge(rig, binding, dry_run=True)
    assert status == 200 and preview["data"]["would_append"]["observed"] == {
        "actual": 40.0,
        "limit": 30.0,
        "unit": "%",
        "breached": True,
    }
    assert not rig.ledger.path.exists()
    status, written = acknowledge(rig, binding)
    assert status == 200, written
    raw, projection, context, enriched = home_result(rig)
    saved_context, saved_projection = copy.deepcopy(context), copy.deepcopy(projection)
    row = enriched["budgets"][0]
    assert row["source_binding"] == raw["source_binding"]
    assert row["presentation_binding"] == binding
    assert row["source_binding"] != row["presentation_binding"]
    assert row["actual"] == 40 and row["limit"] == 30 and row["breached"] is True
    assert row["plain_breach"] == "single sector pct is above its recorded limit"
    decision = row["budget_presentation_decision"]
    assert decision["active"] is True and decision["breached"] is True
    assert decision["receipt"] == written["data"]["hash_self"] and decision["actor"] == ACTOR
    assert enriched["budget_presentation_decisions"]["items"][0] == decision
    assert row["operator_decision"]["state"] == "available"
    assert before == (rig.snapshot_path.read_bytes(), rig.assessment_path.read_bytes())
    rig.home.with_budget_presentation(
        context, projection, decision_rows=rig.ledger.rows(), store_approved=True, now=NOW
    )
    assert context == saved_context and projection == saved_projection


def test_book_wrapper_reads_same_existing_ledger_and_never_appends(rig):
    status, observed = get(rig)
    assert status == 200, observed
    assert acknowledge(rig, observed["data"]["current"]["source_binding"])[0] == 200
    raw, projection, context, _ = home_result(rig)
    durable = rig.ledger.path.read_bytes()
    result = rig.book.budget_presentation_context(context, projection, now=NOW, ledger=rig.ledger)
    assert result["budget_presentation_decisions"]["items"][0]["active"] is True
    assert result["budgets"][0]["source_binding"] == raw["source_binding"]
    assert rig.ledger.path.read_bytes() == durable


@pytest.mark.parametrize("change", ["actual", "limit", "scope", "mode", "as_of"])
def test_current_source_fact_changes_invalidate_old_intent_and_keep_history(rig, change):
    status, observed = get(rig)
    assert status == 200, observed
    old_binding = observed["data"]["current"]["source_binding"]
    old_owner_binding = rig.leaf(scope_id=SCOPE, budget=BUDGET, now=NOW, root=rig.state)["source_binding"]
    assert acknowledge(rig, old_binding)[0] == 200
    durable = rig.ledger.path.read_bytes()
    budget = rig.assessment["portfolio"]["budget_breaches"][0]
    scope = SCOPE
    if change == "actual":
        budget["actual"] = 41
    elif change == "limit":
        budget["limit"] = 31
    elif change == "scope":
        scope = "scope_synthetic_b"
        budget["scope"] = scope
    elif change == "mode":
        rig.snapshot["mode"] = rig.assessment["mode"] = "shadow"
    else:
        rig.snapshot["as_of"] = rig.assessment["as_of"] = "2032-04-12T13:58:00Z"
    rig.write()
    if change == "mode":
        shadow = rig.state / rig.projection.SHADOW_REL
        shadow.write_text(json.dumps(rig.assessment))
    raw, _, _, enriched = home_result(rig, scope)
    assert raw["source_binding"] != old_owner_binding
    assert enriched["budgets"][0]["presentation_binding"] != old_binding
    assert enriched["budgets"][0]["budget_presentation_decision"]["active"] is False
    assert enriched["budgets"][0]["breached"] is True
    assert len(enriched["budget_presentation_decisions"]["history"]) == 1
    assert enriched["budget_presentation_decisions"]["history"][0]["active"] is False
    assert rig.ledger.path.read_bytes() == durable


def test_label_rename_does_not_change_identity_or_invalidate_intent(rig):
    status, observed = get(rig)
    assert status == 200, observed
    binding = observed["data"]["current"]["source_binding"]
    assert acknowledge(rig, binding)[0] == 200
    rig.assessment["portfolio"]["budget_breaches"][0]["account_label"] = "Another synthetic label"
    rig.write()
    _, _, _, enriched = home_result(rig)
    assert enriched["budgets"][0]["presentation_binding"] == binding
    assert enriched["budgets"][0]["budget_presentation_decision"]["active"] is True


def test_expired_intent_is_visible_as_history_while_breach_stays_true(rig):
    status, observed = get(rig)
    assert status == 200, observed
    assert acknowledge(rig, observed["data"]["current"]["source_binding"])[0] == 200
    rig.clock[0] = NOW + timedelta(minutes=6)
    _, _, _, enriched = home_result(rig)
    item = enriched["budget_presentation_decisions"]["items"][0]
    assert item["active"] is False and item["breached"] is True
    assert "expired" in item["history"][0]["inactive_reasons"]
    assert enriched["budgets"][0]["actual"] == 40 and enriched["budgets"][0]["limit"] == 30


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "unreadable",
        "stale",
        "future",
        "duplicate",
        "assessment_clock",
        "schema",
        "mode",
        "malformed_projection",
    ],
)
def test_unavailable_source_cannot_open_store_or_offer_an_ack(rig, monkeypatch, failure):
    if failure == "missing":
        rig.snapshot_path.rename(rig.snapshot_path.with_suffix(".archived.json"))
    elif failure == "unreadable":
        rig.snapshot_path.write_text("{unreadable")
    elif failure == "duplicate":
        rig.assessment["portfolio"]["budget_breaches"].append(
            copy.deepcopy(rig.assessment["portfolio"]["budget_breaches"][0])
        )
        rig.write()
    elif failure == "assessment_clock":
        rig.assessment["as_of"] = "2032-04-12T13:58:00Z"
        rig.write()
    elif failure == "schema":
        rig.assessment["schema"] = "UntrustedAssessment@v1"
        rig.write()
    elif failure == "mode":
        rig.assessment["mode"] = "shadow"
        rig.write()
    elif failure == "malformed_projection":
        rig.snapshot["history"] = 1
        rig.write()
    else:
        instant = "2032-04-12T11:00:00Z" if failure == "stale" else "2032-04-12T14:01:00Z"
        rig.snapshot["as_of"] = rig.assessment["as_of"] = instant
        rig.write()
    monkeypatch.setattr(rig.ledger, "rows", forbidden)
    status, result = acknowledge(rig, {"as_of": AS_OF, "sha256": "a" * 64}, dry_run=True)
    assert status == 503, result
    assert not rig.ledger.path.parent.exists()


def test_get_unavailable_source_keeps_inactive_history_without_fabricating_current(rig):
    status, observed = get(rig)
    assert status == 200, observed
    assert acknowledge(rig, observed["data"]["current"]["source_binding"])[0] == 200
    durable = rig.ledger.path.read_bytes()
    rig.snapshot_path.write_text("{unreadable")
    status, unavailable = get(rig)
    assert status == 503 and unavailable["data"]["current"] is None
    history = unavailable["data"]["budget_presentation_decisions"]["history"]
    assert len(history) == 1 and history[0]["active"] is False
    assert "source_unavailable" in history[0]["inactive_reasons"]
    assert rig.ledger.path.read_bytes() == durable


@pytest.mark.parametrize("decision_rows,approved", [(None, True), ([], False)])
def test_home_cannot_offer_write_when_store_is_unreadable_or_unapproved(rig, decision_rows, approved):
    _, _, _, enriched = home_result(rig, decision_rows=decision_rows, store_approved=approved)
    row = enriched["budgets"][0]
    assert row["operator_decision"]["state"] == "unavailable"
    assert row["operator_decision"]["route"] == "/ops/approvals"
    assert row["actual"] == 40 and row["limit"] == 30 and row["breached"] is True
    assert not rig.ledger.path.exists()


def test_stale_home_projection_keeps_breach_history_and_disables_intent_offer(rig):
    status, observed = get(rig)
    assert status == 200, observed
    assert acknowledge(rig, observed["data"]["current"]["source_binding"])[0] == 200
    _, projection, context, _ = home_result(rig)
    projection.update(state="stale", stale=True)
    durable = rig.ledger.path.read_bytes()
    enriched = rig.home.with_budget_presentation(
        context, projection, decision_rows=rig.ledger.rows(), store_approved=True, now=NOW
    )
    row = enriched["budgets"][0]
    assert row["operator_decision"]["state"] == "unavailable" and row["presentation_binding"] is None
    assert row["actual"] == 40 and row["limit"] == 30 and row["breached"] is True
    history = enriched["budget_presentation_decisions"]["history"]
    assert len(history) == 1 and history[0]["active"] is False
    assert rig.ledger.path.read_bytes() == durable


@pytest.mark.parametrize("path", ["success", "source_fallback"])
def test_existing_home_wrapper_attaches_ledger_readback_on_both_paths(rig, monkeypatch, path):
    status, observed = get(rig)
    assert status == 200, observed
    assert acknowledge(rig, observed["data"]["current"]["source_binding"])[0] == 200
    raw, projection, _, _ = home_result(rig)
    joined = {"budgets_detail": [raw]}
    readback = rig.book.budget_presentation_context
    monkeypatch.setattr(
        rig.book,
        "budget_presentation_context",
        lambda context, projection, **kwargs: readback(context, projection, ledger=rig.ledger, **kwargs),
    )
    if path == "success":
        monkeypatch.setattr(
            rig.home,
            "collect",
            lambda projection, joined, **kwargs: rig.home.build(projection, joined, now=kwargs["now"]),
        )
    else:

        def unavailable(*args, **kwargs):
            raise ValueError("Synthetic independent source failure")

        monkeypatch.setattr(rig.home, "collect", unavailable)
    durable = rig.ledger.path.read_bytes()
    result = rig.home_wrapper(projection, joined, policy={}, now=NOW, reader=SimpleNamespace(_rows=forbidden))
    assert result["budget_presentation_decisions"]["items"][0]["active"] is True
    assert result["budgets"][0]["presentation_binding"] == observed["data"]["current"]["source_binding"]
    assert result["budgets"][0]["breached"] is True
    if path == "source_fallback":
        assert result["read_errors"][0]["source"] == "canonical_home_context"
    assert rig.ledger.path.read_bytes() == durable


@pytest.mark.parametrize(
    "field,value",
    [
        ("actual", "40"),
        ("limit", "30"),
        ("actual", True),
        ("limit", False),
        ("actual", float("nan")),
        ("actual", float("inf")),
        ("limit", float("inf")),
        ("actual", None),
        ("actual", 10**400),
        ("limit", 10**400),
        ("mode", "untrusted"),
    ],
)
def test_home_never_offers_binding_that_the_narrow_leaf_refuses(rig, field, value):
    status, observed = get(rig)
    assert status == 200, observed
    assert acknowledge(rig, observed["data"]["current"]["source_binding"])[0] == 200
    durable = rig.ledger.path.read_bytes()
    if field == "mode":
        rig.snapshot["mode"] = rig.assessment["mode"] = value
    else:
        rig.assessment["portfolio"]["budget_breaches"][0][field] = value
    rig.write()
    source_bytes = (rig.snapshot_path.read_bytes(), rig.assessment_path.read_bytes())
    status, unavailable = get(rig)
    assert status == 503 and unavailable["data"]["current"] is None
    projection = rig.projection.build(copy.deepcopy(rig.snapshot), None, now=NOW)
    raw_rows = rig.book._assessment_budgets(projection, root=rig.state)
    assert len(raw_rows) == 1
    raw_before = json.dumps(raw_rows, sort_keys=True)
    context = rig.home.build(projection, {"budgets_detail": raw_rows}, now=NOW)
    enriched = rig.home.with_budget_presentation(
        context, projection, decision_rows=rig.ledger.rows(), store_approved=True, now=NOW
    )
    row = enriched["budgets"][0]
    assert row["operator_decision"]["state"] == "unavailable"
    assert row["presentation_binding"] is None and row["breached"] is True
    assert len(enriched["budget_presentation_decisions"]["history"]) == 1
    assert enriched["budget_presentation_decisions"]["history"][0]["active"] is False
    assert json.dumps(raw_rows, sort_keys=True) == raw_before
    assert source_bytes == (rig.snapshot_path.read_bytes(), rig.assessment_path.read_bytes())
    assert rig.ledger.path.read_bytes() == durable


def test_huge_current_value_keeps_prior_receipt_in_unavailable_get_history(rig):
    status, observed = get(rig)
    assert status == 200, observed
    assert acknowledge(rig, observed["data"]["current"]["source_binding"])[0] == 200
    receipt = rig.ledger.rows()[0]["hash_self"]
    durable = rig.ledger.path.read_bytes()
    rig.assessment["portfolio"]["budget_breaches"][0]["actual"] = 10**400
    rig.write()
    status, unavailable = get(rig)
    assert status == 503 and unavailable["data"]["current"] is None
    history = unavailable["data"]["budget_presentation_decisions"]["history"]
    assert len(history) == 1 and history[0]["receipt"] == receipt
    assert history[0]["active"] is False and "source_unavailable" in history[0]["inactive_reasons"]
    assert rig.ledger.path.read_bytes() == durable
