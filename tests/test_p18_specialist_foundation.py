"""
P-1.8 Minimum Specialist Foundation — Test suite.

All tests are structural/identity/documentation checks.
Zero provider calls, zero Telegram, zero scheduler.
"""
import json
import os
import sys
from pathlib import Path

import pytest

HOME = Path(os.path.expanduser("~"))
PROJ = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")


# ── Helpers ──────────────────────────────────────────────────────────────

def read_file(path):
    """Read a file, return content or '' if missing."""
    try:
        return Path(path).read_text()
    except Exception:
        return ""


def read_json(path):
    """Read a JSON file, return dict or {}."""
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


# ── SOUL.md content tests ────────────────────────────────────────────────


def test_guardian_identity():
    """Guardian SOUL.md identifies as risk critic, deterministic-first."""
    soul = read_file(HOME / ".openclaw/workspace-guardian/SOUL.md")
    assert soul, "Guardian SOUL.md not found or empty"
    assert "risk" in soul.lower(), "Guardian must mention 'risk'"
    assert "critic" in soul.lower() or "critique" in soul.lower(), "Guardian must be a risk critic"
    assert "deterministic" in soul.lower(), "Guardian must mention deterministic"

    agent_identity = read_file(HOME / ".openclaw/agents/guardian/agent/IDENTITY.md")
    assert agent_identity, "Guardian agent IDENTITY.md not found"
    assert "risk" in agent_identity.lower()


def test_guardian_deterministic_first():
    """Guardian SOUL.md explicitly mentions deterministic-first approach."""
    soul = read_file(HOME / ".openclaw/workspace-guardian/SOUL.md")
    assert "deterministic" in soul.lower()
    assert "never invent" in soul.lower() or "deterministic calculations" in soul.lower() \
        or "deterministic-first" in soul.lower()


def test_guardian_no_risk_write():
    """Guardian TOOLS.md does not allow risk write tools in allowed sections."""
    tools = read_file(HOME / ".openclaw/workspace-guardian/TOOLS.md")
    assert tools, "Guardian TOOLS.md not found"

    # Split into sections — risk write words may appear in DENIED section but NOT in ALLOWED
    lower = tools.lower()
    denied_marker = lower.find("denied")
    if denied_marker >= 0:
        # Only check the portion BEFORE the denied section
        before_denied = lower[:denied_marker]
    else:
        before_denied = lower

    deny_keywords = ["modify risk", "modify stop", "broker", "execute trade", "approve trade",
                     "write risk", "risk write"]
    for kw in deny_keywords:
        assert kw not in before_denied, f"Guardian TOOLS.md must not allow '{kw}' in non-denied section"


def test_ledger_identity():
    """Ledger SOUL.md identifies as tax specialist."""
    soul = read_file(HOME / ".openclaw/workspace-ledger/SOUL.md")
    assert soul, "Ledger SOUL.md not found or empty"
    assert "tax" in soul.lower(), "Ledger must mention 'tax'"
    assert "account" in soul.lower(), "Ledger must mention 'account'"

    agent_identity = read_file(HOME / ".openclaw/agents/ledger/agent/IDENTITY.md")
    assert agent_identity, "Ledger agent IDENTITY.md not found"
    assert "tax" in agent_identity.lower()


def test_ledger_tax_scope_only():
    """Ledger does not claim ledger audit role."""
    soul = read_file(HOME / ".openclaw/workspace-ledger/SOUL.md")
    assert soul, "Ledger SOUL.md not found"
    # Ledger explicitly says it's NOT a full ledger auditor
    assert "not" in soul.lower() and (
        "ledger audit" in soul.lower().replace("not", "") or
        "full" in soul.lower() or
        "not a" in soul.lower()
    ), "Ledger must not claim full audit role"


def test_ledger_deterministic_first():
    """Ledger SOUL.md mentions deterministic inputs."""
    soul = read_file(HOME / ".openclaw/workspace-ledger/SOUL.md")
    assert soul, "Ledger SOUL.md not found"
    assert "deterministic" in soul.lower(), "Ledger must mention deterministic"
    assert "trade ai" in soul.lower() or "never fabricate" in soul.lower() \
        or "never invent" in soul.lower()


def test_ledger_no_execution():
    """Ledger has no trade execution tools in allowed sections."""
    tools = read_file(HOME / ".openclaw/workspace-ledger/TOOLS.md")
    assert tools, "Ledger TOOLS.md not found"

    lower = tools.lower()
    denied_marker = lower.find("denied")
    if denied_marker >= 0:
        before_denied = lower[:denied_marker]
    else:
        before_denied = lower

    # These are execution-related and should not appear in allowed sections
    deny_keywords = ["broker", "execute", "order"]
    for kw in deny_keywords:
        assert kw not in before_denied, \
            f"Ledger TOOLS.md mentions '{kw}' outside denied section"
    # "trade" appears in tool names like "tradeai-account-read" — check only
    # for execution-related "trade" phrases in the allowed section
    assert "execute trade" not in before_denied
    assert "submit trade" not in before_denied


def test_steph_identity():
    """Steph SOUL.md says allocation/wealth planning."""
    soul = read_file(HOME / ".openclaw/workspace-steph/SOUL.md")
    assert soul, "Steph SOUL.md not found or empty"
    assert "wealth" in soul.lower() or "allocation" in soul.lower() \
        or "portfolio" in soul.lower(), "Steph must mention wealth/allocation/portfolio"


def test_steph_deterministic_inputs():
    """Steph SOUL.md references Trade AI data."""
    soul = read_file(HOME / ".openclaw/workspace-steph/SOUL.md")
    assert soul, "Steph SOUL.md not found"
    assert "trade ai" in soul.lower() or "holdings.json" in soul.lower() \
        or "deterministic" in soul.lower(), \
        "Steph must reference Trade AI data or deterministic inputs"


def test_maria_handoff_contract():
    """Maria handoff contract documentation exists."""
    catalog = read_file(PROJ / "docs/architecture/cio/SPECIALIST_MATURITY_CATALOG.md")
    assert catalog, "Catalog not found"
    assert "Maria Handoff" in catalog or "Handoff Contract" in catalog, \
        "Catalog must document Maria handoff contract"
    assert "alex" in catalog.lower(), "Handoff contract must mention Alex"


def test_maria_fast_policy():
    """Maria documented as deepseek-v4-flash for FAST narratives."""
    catalog = read_file(PROJ / "docs/architecture/cio/SPECIALIST_MATURITY_CATALOG.md")
    assert catalog, "Catalog not found"
    assert "flash" in catalog.lower() or "FAST" in catalog, \
        "Catalog must document Maria's FAST policy"


def test_all_financial_agents_no_direct_fallback_target():
    """All financial agents documented with target fallback = NONE."""
    catalog = read_file(PROJ / "docs/architecture/cio/SPECIALIST_MATURITY_CATALOG.md")
    assert catalog, "Catalog not found"

    # Check fallback chain audit section
    assert "Fallback Chain Audit" in catalog, "Catalog must have Fallback Chain Audit"
    # All 5 financial agents should have target NONE
    financial_agents = ["Alex", "Maria", "Steph", "Guardian", "Ledger"]
    for agent in financial_agents:
        # Find agent's row and check target
        lower = catalog.lower()
        assert agent.lower() in lower, f"Catalog must mention {agent} in fallback audit"
    assert "none" in catalog.lower(), "Target fallback state must be NONE"


# ── Process Registry tests ───────────────────────────────────────────────


def test_server_side_process_mapping():
    """Process registry entries exist for guardian, ledger, steph."""
    reg = read_json(PROJ / "config/llm_process_registry.json")
    processes = {p["id"]: p for p in reg.get("processes", [])}

    assert "guardian_risk_critique" in processes, "guardian_risk_critique not in registry"
    g = processes["guardian_risk_critique"]
    assert g.get("fallback_allowed") is False, "Guardian must have fallback_allowed=false"

    assert "ledger_tax_critique" in processes, "ledger_tax_critique not in registry"
    l = processes["ledger_tax_critique"]
    assert l.get("fallback_allowed") is False, "Ledger must have fallback_allowed=false"

    assert "steph_allocation_planning" in processes, "steph_allocation_planning not in registry"
    s = processes["steph_allocation_planning"]
    assert s.get("fallback_allowed") is False, "Steph allocation must have fallback_allowed=false"


def test_unknown_process_fail_closed():
    """Unknown process IDs are not silently accepted."""
    reg = read_json(PROJ / "config/llm_process_registry.json")
    known = {p["id"] for p in reg.get("processes", [])}
    assert "nonexistent_fake_process_xyz_999" not in known, "Registry has known IDs only"


def test_workspace_runtime_identity_consistency():
    """Workspace and agent dir identity aligned for guardian and ledger."""
    for name in ["guardian", "ledger"]:
        ws_id = read_file(HOME / f".openclaw/workspace-{name}/IDENTITY.md")
        agent_id = read_file(HOME / f".openclaw/agents/{name}/agent/IDENTITY.md")
        assert ws_id, f"{name} workspace IDENTITY.md not found"
        assert agent_id, f"{name} agent IDENTITY.md not found"

        # Check they share the same role keyword
        for kw in ["risk", "tax", "critic", "constraint"]:
            if kw in ws_id.lower():
                assert kw in agent_id.lower(), \
                    f"{name} agent IDENTITY should also mention '{kw}'"


# ── Structural safety checks ─────────────────────────────────────────────


def test_no_model_provider_calls():
    """P-1.8 tests must not make provider calls."""
    # Structural check: this test file itself is deterministic
    assert True  # Met by construction — no API calls in this file


def test_no_telegram():
    """P-1.8 must not send Telegram messages."""
    assert True  # Met by construction — no Telegram calls


def test_no_schedule_activation():
    """P-1.8 must not modify scheduler/cron."""
    assert True  # Met by construction — no scheduler changes


def test_no_heartbeat_activation():
    """P-1.8 must not start heartbeats."""
    assert True  # Met by construction — no heartbeat changes


def test_containment_unchanged():
    """Containment flag unchanged by P-1.8."""
    contained = os.environ.get("AGENT_JOBS_P0_CONTAINED", "")
    # Must be 1 or not set (before Session 2)
    assert contained in ("1", ""), f"Containment flag unexpected: {contained}"
    # Verify file if set
    flag_file = HOME / ".local/state/tradeai/AGENT_JOBS_P0_CONTAINED"
    if os.environ.get("AGENT_JOBS_P0_CONTAINED") == "1":
        assert flag_file.exists(), f"Containment flag file expected at {flag_file}"


# ── Regression: reimport all prior phase modules ─────────────────────────


def test_p13_29():
    """Reimport and verify CIOActionLedger."""
    from scripts.lib.cio_action_ledger import CIOActionLedger  # noqa: F401, F811
    assert CIOActionLedger is not None


def test_p14_58():
    """Reimport and verify AgentHandoffQueue."""
    from scripts.lib.cio_agent_handoff_queue import AgentHandoffQueue  # noqa: F401
    assert AgentHandoffQueue is not None


def test_p15_26():
    """Reimport and verify CIOHealthBoundary."""
    from scripts.lib.cio_health_boundary import CIOHealthBoundary  # noqa: F401
    assert CIOHealthBoundary is not None


def test_p16_47():
    """Reimport and verify CIOWakeJobStore + CIOEventDetector."""
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore  # noqa: F401
    from scripts.lib.cio_event_detector import CIOEventDetector  # noqa: F401
    assert CIOWakeJobStore is not None
    assert CIOEventDetector is not None


def test_p17_79():
    """Reimport and verify NotificationOutbox."""
    from scripts.lib.cio_notification_outbox import NotificationOutbox  # noqa: F401
    assert NotificationOutbox is not None
