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
}

# Known, still-ungoverned, and NOT excused — recorded so the guard can block
# NEW ones while the debt stays visible. All three call Anthropic, for which
# llm_lane has no lane (deepseek-*, grok, chatgpt only), so they cannot be
# routed the way OpenAI and xAI were. All are reachable from scheduled work:
# portfolio_ai_analyst and monthly_advisory via portfolio_orchestrator (cron
# 07:15 weekdays), alert_missing_conditions directly. Mitigating observation,
# not a fix: the monthly run last failed with "credit balance is too low", so
# Anthropic spend appears to be zero.
#
# Closing these needs an `anthropic` lane plus registry pricing. Until then
# this list must SHRINK, never grow.
KNOWN_UNGOVERNED = {
    "scripts/portfolio_ai_analyst.py": "anthropic; no llm_lane anthropic lane",
    "scripts/monthly_advisory.py": "anthropic + openai; no anthropic lane",
    "scripts/alert_missing_conditions.py": "anthropic; no anthropic lane",
}


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
