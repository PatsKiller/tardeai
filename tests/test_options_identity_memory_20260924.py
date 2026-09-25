#!/usr/bin/env python3
"""Slice A+B — options identity GUIDs + scoped memory envelope.

Hermetic only. No broker, no network, no DB.

    .venv/bin/python -m pytest tests/test_options_identity_memory_20260924.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib import options_identity as oid  # noqa: E402
from scripts.lib import options_memory_envelope as ome  # noqa: E402
from scripts.lib import cio_options_fluency as flu  # noqa: E402
from scripts.lib.security_identity import issuer_guid, security_guid  # noqa: E402
from scripts.lib.agent_feature_flags import (  # noqa: E402
    DEFAULT_FLAGS,
    load_feature_flags,
    behavior_influence_active,
)


# ── Slice A — identity ─────────────────────────────────────────────────────

# Hermetic issuer resolution: the identity registry is production state, so the
# tests inject a registry document shaped like RegisteredEntity@v1 rows. Only V
# has a registered issuer; ZZZZ does not — and must therefore mint nothing.
ISSUER_V = issuer_guid(company="Visa Inc")
V_SECURITY = security_guid(issuer=ISSUER_V)
FAKE_REGISTRY = {
    "by_symbol": {"V": V_SECURITY},
    "entities": {
        V_SECURITY: {
            "schema": "RegisteredEntity@v1",
            "ticker_alias": "V",
            "issuer_guid": ISSUER_V,
            "security_guid": V_SECURITY,
            "identity_status": "CONFIRMED",
        }
    },
}


@pytest.fixture(autouse=True)
def _hermetic_registry(monkeypatch):
    """Route every issuer lookup at the fixture registry, never production."""
    real = oid.resolve_issuer_guid

    def _resolve(underlying, *, registry=None):
        return real(underlying, registry=FAKE_REGISTRY if registry is None else registry)

    monkeypatch.setattr(oid, "resolve_issuer_guid", _resolve)
    yield


def test_contract_guid_is_a_security_of_the_underlying_issuer():
    """No fifth id prefix: the contract key lives in security_identity."""
    cg = oid.contract_guid("V", "call", 385, "2026-10-17")
    assert cg == security_guid(
        issuer=ISSUER_V, share_class="option", instrument="C:385.0000:2026-10-17",
    )
    # A venue, when it is a real listing venue, is part of the contract key.
    assert oid.contract_guid("V", "call", 385, "2026-10-17", venue="cboe") == security_guid(
        issuer=ISSUER_V, share_class="option", instrument="C:385.0000:2026-10-17:cboe",
    )


def test_contract_guid_never_minted_from_ticker_text():
    """An underlying with no registered issuer yields no GUID (§13.4)."""
    assert oid.contract_guid("ZZZZ", "call", 10, "2026-10-17") is None
    assert oid.option_strategy_guid("long_call", "ZZZZ", right="call", strike=10,
                                    expiration="2026-10-17") is None
    p = {"symbol": "ZZZZ", "strategy": "long_call", "option_type": "call",
         "strike": 10, "expiration": "2026-10-17"}
    oid.stamp_proposal_identity(p)
    assert "contract_guid" not in p and "option_strategy_guid" not in p


def test_same_listed_contract_one_guid_across_brokers_and_accounts():
    """Broker / account are routing, not venue: one contract, one GUID."""
    base = {"strategy": "covered_call", "symbol": "V", "underlying": "V",
            "option_type": "call", "strike": 385, "expiration": "2026-10-17"}
    a = oid.stamp_proposal_identity({**base, "broker": "alpaca", "account": "paper"})
    b = oid.stamp_proposal_identity({**base, "broker": "schwab", "account": "schwab_ira"})
    assert a["contract_guid"] == b["contract_guid"]
    # The strategy INSTANCE is account-scoped, so those differ.
    assert a["option_strategy_guid"] != b["option_strategy_guid"]


def test_equity_proposal_gets_no_option_guids():
    """No legs -> no strategy GUID. Equity scalp rows in proposal_outcome_chain
    stay NULL on the option columns instead of being minted through a 'noleg'
    path (the defect this repairs)."""
    keys = oid.outcome_attribution_keys({"symbol": "AAPL", "strategy_id": "momentum_scalp"})
    assert keys == {"symbol": "AAPL", "strategy_id": "momentum_scalp"}
    keys_v = oid.outcome_attribution_keys({"symbol": "V", "strategy_id": "momentum_scalp"})
    assert "option_strategy_guid" not in keys_v and "contract_guid" not in keys_v


def test_strategy_guid_is_a_graph_strategy_entity():
    from scripts.lib.ticker_knowledge_graph import entity_guid
    cg = oid.contract_guid("V", "call", 385, "2026-10-17")
    sg = oid.option_strategy_guid("covered_call", "V", right="call", strike=385,
                                  expiration="2026-10-17", account="schwab_ira")
    assert sg == entity_guid("strategy", f"covered_call|V|{cg}|schwab_ira")


def test_registry_resolve_guid_accepts_contract_guid():
    from scripts.lib.identity_registry import resolve_guid
    cg = oid.contract_guid("V", "put", 300, "2026-12-19")
    assert resolve_guid({"entities": {}}, cg) == cg


def test_no_expiration_or_strike_guids_are_minted():
    """Strike and expiration are attributes of the contract key, not entities."""
    p = oid.stamp_proposal_identity({"symbol": "V", "strategy": "long_call",
                                     "option_type": "call", "strike": 385,
                                     "expiration": "2026-10-17"})
    assert not any(k in p for k in ("expiration_guid", "strike_guid"))
    assert not any(k.endswith("_guid") and k not in ("contract_guid", "option_strategy_guid")
                   for k in p)



def test_contract_guid_stable_and_distinct():
    a = oid.contract_guid("V", "call", 385, "2026-10-17")
    b = oid.contract_guid("V", "C", 385.0, "20261017")
    c = oid.contract_guid("V", "put", 385, "2026-10-17")
    assert a and a == b
    assert c and c != a


def test_option_strategy_guid_includes_account_and_strategy():
    g1 = oid.option_strategy_guid(
        "covered_call", "V", right="call", strike=385,
        expiration="2026-10-17", account="schwab_ira",
    )
    g2 = oid.option_strategy_guid(
        "covered_call", "V", right="call", strike=385,
        expiration="2026-10-17", account="schwab_taxable",
    )
    g3 = oid.option_strategy_guid(
        "long_call", "V", right="call", strike=385,
        expiration="2026-10-17", account="schwab_ira",
    )
    assert g1 and g2 and g3
    assert g1 != g2  # account scopes strategy instance
    assert g1 != g3  # strategy type scopes


def test_stamp_proposal_identity_idempotent():
    p = {
        "strategy": "covered_call",
        "symbol": "V",
        "underlying": "V",
        "option_type": "call",
        "strike": 385,
        "expiration": "2026-10-17",
        "account": "schwab_ira",
        "broker": "schwab",
    }
    oid.stamp_proposal_identity(p)
    assert p.get("contract_guid")
    assert p.get("option_strategy_guid")
    first = (p["contract_guid"], p["option_strategy_guid"])
    oid.stamp_proposal_identity(p)
    assert (p["contract_guid"], p["option_strategy_guid"]) == first


def test_outcome_attribution_keys_never_invent_pnl():
    keys = oid.outcome_attribution_keys({
        "symbol": "V",
        "strategy": "long_call",
        "option_type": "call",
        "strike": 370,
        "expiration": "2026-11-21",
        "broker": "schwab",
        "account": "paper",
    })
    assert keys["symbol"] == "V"
    assert keys["strategy_id"] == "long_call"
    assert keys.get("option_strategy_guid")
    assert keys.get("contract_guid")
    assert "trade_pnl" not in keys
    assert "pnl" not in keys


def test_build_options_desk_summary_carries_guids():
    """Summary writer surfaces GUIDs when proposals are stamped."""
    # Avoid full generate_proposals — stamp a synthetic proposal through summary.
    from scripts import options_engine as oe

    props = {
        "generated_at": "2026-09-24T20:00:00Z",
        "proposals": [
            oid.stamp_proposal_identity({
                "id": "opt_test",
                "strategy": "long_call",
                "symbol": "V",
                "underlying": "V",
                "option_type": "call",
                "strike": 370,
                "expiration": "2026-11-21",
                "edge_score": 70,
                "pop_pct": 55,
                "account": "paper",
                "broker": "schwab",
                "recommended_action": "Buy Call",
            }),
        ],
        "strategy_overview": {"strategy_slots": {}},
    }
    summary = oe.build_options_desk_summary(props)
    top = summary["top_proposals"][0]
    assert top.get("option_strategy_guid")
    assert top.get("contract_guid")
    by = summary["by_symbol"]["V"][0]
    assert by.get("option_strategy_guid") == top["option_strategy_guid"]


# ── Slice B — scoped memory ────────────────────────────────────────────────


def test_global_memory_influence_default_stays_zero():
    flags = load_feature_flags({})
    assert flags["MEMORY_BEHAVIOR_INFLUENCE"] == 0
    assert flags["MEMORY_BEHAVIOR_INFLUENCE_OPTIONS"] == 0
    assert behavior_influence_active(flags) is False
    assert DEFAULT_FLAGS["MEMORY_BEHAVIOR_INFLUENCE"] == 0
    assert DEFAULT_FLAGS["MEMORY_BEHAVIOR_INFLUENCE_OPTIONS"] == 0


def test_scoped_flag_off_no_influence():
    env = ome.build_options_memory_envelope(
        "V",
        flags={"MEMORY_BEHAVIOR_INFLUENCE_OPTIONS": 0},
        outcomes=[{"symbol": "V", "strategy": "long_call", "outcome": "win", "pnl": 120}],
        learning_notes=[{"symbol": "V", "note": "prefer debit over CC for entry"}],
    )
    assert env["applied"] is False
    assert env["reason"] == "FLAG_OFF"
    assert env["prose"] == ""
    assert env["sources"] == []


def test_scoped_flag_on_empty_fail_closed():
    env = ome.build_options_memory_envelope(
        "V",
        flags={"MEMORY_BEHAVIOR_INFLUENCE_OPTIONS": 1},
        outcomes=[],
        learning_notes=[],
    )
    assert env["applied"] is False
    assert env["reason"] == "EMPTY"
    assert env["prose"] == ""


def test_scoped_flag_on_with_prior_cites_memory():
    outcomes = [
        {
            "symbol": "V",
            "strategy": "long_call",
            "outcome": "win",
            "pnl": 85.5,
            "option_strategy_guid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        },
    ]
    notes = [
        {"symbols": ["V"], "note": "Visa entry: prefer long_call over covered_call"},
    ]
    env = ome.build_options_memory_envelope(
        "V",
        flags={"MEMORY_BEHAVIOR_INFLUENCE_OPTIONS": 1},
        outcomes=outcomes,
        learning_notes=notes,
    )
    assert env["applied"] is True
    assert env["reason"] == "APPLIED"
    assert "options_prior_outcomes" in env["sources"]
    assert "cio_operator_learning" in env["sources"]
    assert "long_call" in env["prose"]
    assert "prefer long_call" in env["prose"]
    assert "Sources:" in env["prose"]
    # Global MBI never flipped by this module
    assert env["memory_behavior_influence_global"] == 0


def test_fluency_opinion_cites_memory_when_applied():
    desk = {
        "generated_at": "2026-09-24T20:00:00Z",
        "strategy_counts": {"long_call": 1},
        "by_symbol": {
            "V": [{
                "strategy": "long_call",
                "strike": 370,
                "option_strategy_guid": "11111111-2222-3333-4444-555555555555",
                "contract_guid": "66666666-7777-8888-9999-aaaaaaaaaaaa",
            }],
        },
    }
    facts = flu.gather_options_house_facts(
        ["V"],
        desk=desk,
        goals=[],
        memory_outcomes=[{
            "symbol": "V", "strategy": "long_call", "outcome": "win", "pnl": 40,
        }],
        memory_notes=[{"symbol": "V", "note": "debit preferred for BUY_READY"}],
        memory_flags={"MEMORY_BEHAVIOR_INFLUENCE_OPTIONS": 1},
    )
    assert facts["memory_envelope"]["applied"] is True
    card = flu.format_cio_options_opinion(
        facts, symbols=["V"], memory_envelope=facts["memory_envelope"],
    )
    assert "What we learned" in card
    assert "debit preferred" in card
    assert "strategy_guid=11111111" in card
    assert "Sources:" in card


def test_fluency_opinion_no_memory_when_flag_off():
    desk = {"by_symbol": {"V": [{"strategy": "long_call", "strike": 370}]},
            "strategy_counts": {}}
    facts = flu.gather_options_house_facts(
        ["V"],
        desk=desk,
        goals=[],
        memory_outcomes=[{"symbol": "V", "strategy": "long_call", "outcome": "win"}],
        memory_flags={"MEMORY_BEHAVIOR_INFLUENCE_OPTIONS": 0},
    )
    assert facts["memory_envelope"]["applied"] is False
    card = flu.format_cio_options_opinion(
        facts, symbols=["V"], memory_envelope=facts["memory_envelope"],
    )
    assert "What we learned" not in card


# ── Tranche 2, Slice 6 — options outcomes join the identity spine ─────────────

class _FakeExecutor:
    def __init__(self, rows=None, fail=False):
        self.rows = rows or []
        self.fail = fail
        self.calls = []

    def __call__(self, sql, params=None, fetch=None):
        self.calls.append({"sql": sql, "params": params, "fetch": fetch})
        if self.fail:
            return None
        if fetch == "all":
            return self.rows
        return True


def test_record_outcome_mints_contract_identity_from_an_unpadded_occ_symbol():
    """Both live callers pass only occ_symbol in meta (Alpaca: RTX260918C00160000)."""
    from scripts.lib.options_pipeline import validation as val

    ex = _FakeExecutor()
    res = val.record_outcome("opt_x1", outcome="win", strategy_id="deep_itm_call", symbol="V", pnl=85.5,
                             meta={"alpaca_order_id": "o1", "occ_symbol": "V     261017C00385000", "lane": "tradeai_automated"},
                             executor=ex)
    assert res["ok"] is True
    insert = next(c for c in ex.calls if "INSERT INTO options_paper_outcomes" in c["sql"])
    meta = __import__("json").loads(insert["params"][-1])
    assert meta["contract_guid"] == oid.contract_guid("V", "call", 385, "2026-10-17")
    assert meta["option_strategy_guid"]
    assert meta["strike"] == 385.0 and meta["expiration"] == "2026-10-17" and meta["option_type"] == "call"
    # unpadded root parses the same way
    assert val.contract_fields_from_occ("V261017C00385000") == {
        "underlying": "V", "expiration": "2026-10-17", "option_type": "call", "strike": 385.0}
    assert val.contract_fields_from_occ("not-an-occ") is None


def test_record_outcome_leaves_guids_absent_for_an_unregistered_underlying():
    from scripts.lib.options_pipeline import validation as val

    ex = _FakeExecutor()
    val.record_outcome("opt_x2", outcome="loss", strategy_id="deep_itm_call", symbol="ZZZZ", pnl=-10,
                       meta={"occ_symbol": "ZZZZ261017C00010000"}, executor=ex)
    meta = __import__("json").loads(next(c for c in ex.calls if "INSERT" in c["sql"])["params"][-1])
    assert "contract_guid" not in meta and "option_strategy_guid" not in meta


def test_multi_leg_occ_becomes_legs_and_a_strategy_guid():
    from scripts.lib.options_pipeline import validation as val

    fields = val.contract_fields_from_meta({"occ_symbol": "V261017C00385000,V261017C00400000"}, symbol="V")
    assert len(fields["legs"]) == 2 and fields["underlying"] == "V"
    ex = _FakeExecutor()
    val.record_outcome("opt_x3", outcome="win", strategy_id="deep_itm_call", symbol="V", pnl=1.0,
                       meta={"occ_symbol": "V261017C00385000,V261017C00400000"}, executor=ex)
    meta = __import__("json").loads(next(c for c in ex.calls if "INSERT" in c["sql"])["params"][-1])
    assert meta["option_strategy_guid"] and "contract_guid" not in meta  # two legs: strategy identity, no single contract


def test_fetch_symbol_outcomes_lifts_or_mints_guids_and_shapes_envelope_rows():
    from scripts.lib.options_pipeline import validation as val

    pj = {"strategy": "long_call", "symbol": "V", "option_type": "call", "strike": 370, "expiration": "2026-11-21", "account": "paper"}
    rows = [
        {"proposal_id": "p1", "strategy_id": "long_call", "symbol": "V", "outcome": "win", "pnl": "85.5",
         "closed_at": "2026-09-20", "meta": {"contract_guid": "cg-from-meta", "option_strategy_guid": "sg-from-meta"}, "proposal_json": None},
        {"proposal_id": "p2", "strategy_id": "long_call", "symbol": "V", "outcome": "loss", "pnl": -20.0,
         "closed_at": "2026-09-21", "meta": "{}", "proposal_json": __import__("json").dumps(pj)},
    ]
    ex = _FakeExecutor(rows=rows)
    out = val.fetch_symbol_outcomes("v", executor=ex)
    assert ex.calls[0]["params"] == ("V", 25) and "options_approval_queue" in ex.calls[0]["sql"]
    assert out[0]["contract_guid"] == "cg-from-meta" and out[0]["pnl"] == 85.5 and out[0]["source"] == "options_paper_outcomes"
    assert out[1]["contract_guid"] == oid.contract_guid("V", "call", 370, "2026-11-21")
    assert out[1]["option_strategy_guid"] and out[1]["outcome"] == "loss"
    assert val.fetch_symbol_outcomes("V", executor=_FakeExecutor(fail=True)) == []
    assert val.fetch_recent_outcomes(executor=_FakeExecutor(rows=rows))[1]["proposal_id"] == "p2"


def test_envelope_uses_the_settled_outcome_loader_when_no_rows_are_injected(monkeypatch):
    calls = []

    def loader(symbol, limit):
        calls.append((symbol, limit))
        return [{"symbol": "V", "strategy_id": "long_call", "outcome": "win", "pnl": 85.5,
                 "contract_guid": "11111111-aaaa", "source": "options_paper_outcomes"}]

    rows = ome.load_options_outcomes_for_symbol("V", rows=None, loader=loader)
    assert calls == [("V", ome.DEFAULT_MAX_OUTCOMES)] and len(rows) == 1
    # rows=[] is hermetic and never calls a loader
    assert ome.load_options_outcomes_for_symbol("V", rows=[], loader=loader) == [] and len(calls) == 1
    # env off -> the default loader answers [] without touching a DB
    monkeypatch.setenv(ome.OUTCOME_LOADER_ENV, "0")
    assert ome.default_outcome_loader("V", 5) == []
    # a loaded row is cited with its own source name when the flag is on
    env = ome.build_options_memory_envelope("V", flags={"MEMORY_BEHAVIOR_INFLUENCE_OPTIONS": 1},
                                            outcomes=loader("V", 5), learning_notes=[])
    assert env["applied"] is True and ome.SOURCE_PAPER_OUTCOMES in env["sources"]
    assert "contract_guid=11111111" in env["prose"]


def test_learning_candidate_paths_are_not_cwd_relative_only():
    paths = ome.learning_candidate_paths()
    assert any(p.is_absolute() for p in paths)
