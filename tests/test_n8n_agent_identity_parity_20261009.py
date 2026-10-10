"""AGENTS.md 3.0.0 §23.10 P20 — n8n has an identity, and the two denylists stay in step (audit A high).

n8n is declared in config/agent_clients.yaml (ADVISORY, so never mutating) and config/agent_registry.json
(a scheduler/requester actor: no broker, no send, gateway scopes coordination_run + coordination_read).
The gateway's FORBIDDEN_ROUTE_TOKENS and agent_runtime_mvl.json global_denied_tools are separate lists;
DENIED_TOOL_MAP below says, for every denied tool, which gateway token refuses it or that the gateway's
route allowlist does. A new denied tool, a removed gateway token or a new gateway route fails this test
until the map is re-reviewed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import agent_clients_registry as ACR  # noqa: E402
from scripts.lib import agent_registry as AR  # noqa: E402
from scripts.lib import n8n_coordination_gateway as G  # noqa: E402

ALLOWLIST = "route_allowlist"

#: global_denied_tools entry -> the gateway token that refuses it, or ALLOWLIST when no token exists and the
#: refusal comes from ALLOWED_ROUTES (only coordination/event|status|run are served).
DENIED_TOOL_MAP: dict[str, str] = {
    "broker.*": "broker",
    "order.*": "order",
    "trade.*": ALLOWLIST,
    "execution.*": ALLOWLIST,
    "account.write": ALLOWLIST,
    "position.write": ALLOWLIST,
    "approval.*": "approve",
    "2fa.*": "2fa",
    "secrets.*": ALLOWLIST,
    "credential.*": ALLOWLIST,
    "production.*": ALLOWLIST,
    "prod_db.write": "sql",
    "config.promote": "promote",
    "config.activate": ALLOWLIST,
    "shell.*": ALLOWLIST,
    "systemd.*": ALLOWLIST,
}
#: The routes the ALLOWLIST mapping relies on. Adding a route means re-reviewing every ALLOWLIST row.
#: 2026-10-09 re-review (n8n maturity B5.3): coordination/due is a READ route (scope coordination_read, operation
#: `due` only, writes nothing, returns lane_id/mode/key items); it serves none of the ALLOWLIST rows above.
EXPECTED_ROUTES = frozenset({"coordination/event", "coordination/status", "coordination/run", "coordination/due"})


def _mvl() -> dict:
    return json.loads((ROOT / "config" / "agent_runtime_mvl.json").read_text(encoding="utf-8"))


def _stem(tool: str) -> str:
    return tool.split(".", 1)[0]


def test_every_denied_tool_is_mapped_and_nothing_else_is():
    denied = _mvl()["global_denied_tools"]
    assert set(DENIED_TOOL_MAP) == set(denied), (
        "global_denied_tools changed: map each new entry to a gateway token or route_allowlist"
    )


def test_mapped_gateway_tokens_exist_and_refuse_the_route():
    for tool, token in DENIED_TOOL_MAP.items():
        if token == ALLOWLIST:
            continue
        assert token in G.FORBIDDEN_ROUTE_TOKENS, (tool, token)
        assert G.route_forbidden(f"coordination/{token}") == token, (tool, token)


def test_a_denied_tool_whose_stem_is_a_gateway_token_maps_to_that_token():
    for tool, token in DENIED_TOOL_MAP.items():
        if _stem(tool) in G.FORBIDDEN_ROUTE_TOKENS:
            assert token == _stem(tool), (tool, token)


def test_every_denied_stem_is_refused_as_a_route():
    for tool in DENIED_TOOL_MAP:
        for route in (_stem(tool), f"coordination/{_stem(tool)}", tool.replace(".", "/").replace("*", "x")):
            assert G.route_forbidden(route) is not None, (tool, route)


def test_allowlist_mapping_rests_on_exactly_three_routes_none_of_which_is_denied():
    assert G.ALLOWED_ROUTES == EXPECTED_ROUTES
    for route in G.ALLOWED_ROUTES:
        assert G.route_forbidden(route) is None, route


def test_n8n_is_a_registered_advisory_client_that_cannot_mutate():
    reg = ACR.load_registry(ROOT / "config" / "agent_clients.yaml")
    assert ACR.validate_registry(reg, schema_path=ROOT / "config" / "agent_clients.schema.json") == []
    c = ACR.get_client("n8n", reg)
    assert not c.get("unknown")
    assert c["enforcement_level"] == "ADVISORY"
    assert ACR.mutating_allowed("n8n", reg) is False
    assert c["validation_test"] == "tests/test_n8n_agent_identity_parity_20261009.py"
    assert (ROOT / c["validation_test"]).is_file()


def test_n8n_registry_row_is_a_scheduler_with_run_and_read_scopes_only():
    env = {"TRADEAI_AGENT_REGISTRY": str(ROOT / "config" / "agent_registry.json")}
    row = AR.get("n8n", env)
    assert row is not None and AR.canonical(G.RELAY_CALLER, env) == "n8n"
    assert set(row["gateway_scopes"]) == {G.SCOPE_RUN, G.SCOPE_READ} == set(G.SCOPES)
    assert row["broker"] is False and row["send"] is False
    assert row["authority"] == "READ_ONLY_ADVISORY" and row["status"] == "SCHEDULER"
    assert row["wake_eligible"] is False and row["model_caller"] is None and row["bus_events"] == []
    assert "n8n" not in AR.wake_eligible(env)
    assert "n8n" not in AR.subscribers("operator.message", env)


def test_the_relay_caller_key_grants_exactly_the_registry_scopes():
    keys = G.build_caller_keys(b"k" * 32, n8n_key=b"n" * 32)
    assert set(keys[G.RELAY_CALLER].scopes) == {G.SCOPE_RUN, G.SCOPE_READ}
    assert set(keys[G.DISPATCH_CALLER].scopes) == {G.SCOPE_READ}
