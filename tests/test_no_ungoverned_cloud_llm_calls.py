"""No scheduled code may spend at a cloud LLM outside the ledger.

Audited 2026-08-30 after a live hop was blocked by COST_CAP_EXCEEDED on a day
whose ledgered spend was 1.4 cents. The cap was being eaten by test rows — but
the audit found the opposite hole too: real cloud spend paths the ledger could
not see at all.

  scripts/multi_tier_trade_reviewer.py  read OPENAI_API_KEY and POSTed to
      api.openai.com directly. Scheduled 3x (weekly, monthly, overnight).

  scripts/llm_router.py                 read XAI_API_KEY and urlopen'd
      api.x.ai directly, reachable from iterate_research_topics,
      agent_watchlist_engine, overnight_batch and api_v2. Its `cost_estimate`
      was arithmetic on max_tokens, not usage.

Both now route through llm_lane's existing governed `chatgpt` / `grok` lanes,
which reserve, settle and log like every DeepSeek call. A usage number that
cannot see a spend path is worse than no usage number, because it is trusted.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VENDOR_COMPLETION = re.compile(
    r"""(urlopen|requests\.post|requests\.get)\s*\(\s*f?["']https://api\."""
    r"""(openai\.com|x\.ai|anthropic\.com)""", re.I)

# Files whose job IS to probe a credential or report provider status. They may
# name a vendor host; they must not generate with it.
PROBE_ALLOWLIST = {
    "verify_llm_providers.py", "secret_validators.py", "rotation_probes.py",
    "secrets_admin.py", "cloud_oauth_usage_monitor.py", "defense_oversight.py",
    "validate_rotation_production_readiness.py",
    # max_tokens=1 "ping" that exists to read back a credit-status error.
    "alert_missing_conditions.py",
}

# CLOSED 2026-08-30. The list is empty, and the test below keeps it that way.
#
# portfolio_ai_analyst and monthly_advisory now route through llm_lane's
# `anthropic` lane (haiku / sonnet), added in this change together with real
# registry pricing from the vendor doc. That lane also resolves a CURRENT
# model: both callers named claude-sonnet-4-20250514 / claude-opus-4-20250514,
# which are RETIRED on the first-party API (Bedrock/Google Cloud only), so
# those calls could never have succeeded regardless of credit.
#
# alert_missing_conditions is NOT a generation call — it POSTs max_tokens=1
# with the body "ping" purely to read back a credit-status error. It is a
# probe, so it belongs in PROBE_ALLOWLIST rather than on a lane.
KNOWN_UNGOVERNED: dict[str, str] = {}


def _py_files():
    for p in (ROOT / "scripts").rglob("*.py"):
        if "/tests/" in str(p):
            continue
        yield p


@pytest.mark.parametrize("name", ["llm_router.py", "multi_tier_trade_reviewer.py"])
def test_the_audited_files_no_longer_call_a_vendor_directly(name):
    src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
    assert not VENDOR_COMPLETION.search(src), f"{name} still POSTs a vendor directly"


@pytest.mark.parametrize("name", ["llm_router.py", "multi_tier_trade_reviewer.py"])
def test_they_route_through_llm_lane(name):
    src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
    assert "llm_lane import generate" in src
    assert "process_id=" in src, "a governed call must attribute a process"


def test_the_grok_path_no_longer_invents_a_cost():
    """`cost_estimate` was max_tokens arithmetic — a guess recorded as a fact."""
    src = (ROOT / "scripts" / "llm_router.py").read_text(encoding="utf-8")
    assert "(max_tokens * 0.0005)" not in src
    assert '"cost_estimate": None' in src


def test_the_known_ungoverned_set_does_not_grow():
    offenders = []
    for p in _py_files():
        if p.name in PROBE_ALLOWLIST:
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if VENDOR_COMPLETION.search(src):
            offenders.append(str(p.relative_to(ROOT)))
    new = sorted(set(offenders) - set(KNOWN_UNGOVERNED))
    assert not new, (
        "NEW ungoverned cloud LLM call site(s). Route via llm_lane, or add to "
        f"PROBE_ALLOWLIST if it only checks a credential: {new}")


def test_the_known_list_is_accurate_and_shrinking():
    """A stale entry would hide a path that has since been fixed."""
    still = []
    for rel in KNOWN_UNGOVERNED:
        f = ROOT / rel
        if f.is_file() and VENDOR_COMPLETION.search(
                f.read_text(encoding="utf-8", errors="replace")):
            still.append(rel)
    assert sorted(still) == sorted(KNOWN_UNGOVERNED), (
        "an entry no longer calls a vendor directly — remove it from "
        f"KNOWN_UNGOVERNED: {sorted(set(KNOWN_UNGOVERNED) - set(still))}")


def test_the_known_ungoverned_list_is_closed():
    """It reached zero on 2026-08-30. It must not reopen.

    Re-adding an entry is allowed only alongside a deliberate decision — the
    point of the empty dict is that a new offender fails the test above rather
    than being quietly appended here.
    """
    assert KNOWN_UNGOVERNED == {}, (
        f"the list reopened: {sorted(KNOWN_UNGOVERNED)}")


@pytest.mark.parametrize("name", ["portfolio_ai_analyst.py", "monthly_advisory.py"])
def test_the_anthropic_callers_route_through_the_lane(name):
    src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
    assert not VENDOR_COMPLETION.search(src)
    assert "llm_lane import generate" in src
    assert "process_id=" in src


def test_the_anthropic_lane_exists_and_is_governed():
    src = (ROOT / "scripts" / "llm_lane.py").read_text(encoding="utf-8")
    assert "_ANTHROPIC_LANES" in src
    assert "log_call(lane=lane_l" in src, "anthropic calls must be ledgered"


def test_the_anthropic_lane_defaults_to_current_models():
    """The callers named RETIRED models; the lane must not repeat that."""
    from scripts.llm_lane import _ANTHROPIC_DEFAULT
    for m in _ANTHROPIC_DEFAULT.values():
        assert "sonnet-4-2025" not in m, m      # retired
        assert "opus-4-2025" not in m, m        # retired
    assert "haiku-4-5" in _ANTHROPIC_DEFAULT["haiku"]
    assert "sonnet-4-5" in _ANTHROPIC_DEFAULT["sonnet"]


def test_anthropic_registry_pricing_matches_the_vendor_doc():
    from scripts.lib.llm_model_registry import load_registry
    a = (load_registry().get("providers") or {}).get("anthropic") or {}
    got = {m["model_id"]: m["pricing_snapshot_usd_per_million_tokens"]
           for m in (a.get("models") or {}).values()}
    assert got["claude-haiku-4-5-20251001"] == {
        "cache_hit_input": 0.10, "cache_miss_input": 1.00, "output": 5.00}
    assert got["claude-sonnet-4-5-20250929"] == {
        "cache_hit_input": 0.30, "cache_miss_input": 3.00, "output": 15.00}
    assert "claude-opus-4-20250514" in (a.get("retired_models") or {})
