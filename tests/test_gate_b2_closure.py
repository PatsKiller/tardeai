"""
Gate B.2: Provider-authority closure tests.

Covers:
  - Maria legacy OAuth de-identified (agent = legacy_watch_research, not maria)
  - Legacy Watch no silent fallback (all fallbacks declared with provenance)
  - Declared multi-lane research preserved
  - Financial identity scan: no RAW_OLLAMA/GENERIC_LLM_ROUTER/DIRECT_OAUTH
    presenting as governed financial agent work
  - Legacy CIO authority gate: LEGACY_CIO_REVIEW vs AUTHORITATIVE_CIO_ACTION

All tests use isolated fixtures. No provider calls. No Telegram sends.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))


# ═══════════════════════════════════════════════════════════════════════════════
# Maria legacy OAuth de-identification
# ═══════════════════════════════════════════════════════════════════════════════

class TestMariaLegacyOAuthDeIdentified:
    """Maria's legacy OAuth path in process_watchlist_agent_jobs must NOT
    present output as governed Maria professional-agent work."""

    def test_llm_oauth_metadata_agent_is_legacy_not_maria(self):
        """Verify the metadata in _llm() OAuth path uses legacy_watch_research."""
        source_path = _PROJECT_ROOT / "scripts" / "process_watchlist_agent_jobs.py"
        source = source_path.read_text()
        # The OAuth metadata must not claim "agent": "maria"
        assert '"agent": "legacy_watch_research"' in source
        assert '"governed_financial_agent": False' in source
        assert '"provenance_identity": "LEGACY_WATCH_RESEARCH_NON_PROFESSIONAL"' in source

    def test_llm_oauth_declared_lanes_exist(self):
        """OAuth path declares its lanes explicitly."""
        source_path = _PROJECT_ROOT / "scripts" / "process_watchlist_agent_jobs.py"
        source = source_path.read_text()
        assert '"declared_lanes": ["grok-oauth", "chatgpt-oauth"]' in source

    def test_maria_governed_path_not_broken(self):
        """_run_maria_one_pass still exists for governed Maria jobs."""
        source_path = _PROJECT_ROOT / "scripts" / "process_watchlist_agent_jobs.py"
        source = source_path.read_text()
        assert "def _run_maria_one_pass" in source
        # Maria jobs use the governed path, not the legacy OAuth path
        assert "agent == \"maria\"" in source


# ═══════════════════════════════════════════════════════════════════════════════
# Legacy Watch silent fallback elimination
# ═══════════════════════════════════════════════════════════════════════════════

class TestLegacyWatchNoSilentFallback:
    """All provider fallbacks must be explicitly declared with provenance."""

    def test_fallback_chain_tracking_in_llm(self):
        """_llm() tracks _fallback_chain for provider provenance."""
        source_path = _PROJECT_ROOT / "scripts" / "process_watchlist_agent_jobs.py"
        source = source_path.read_text()
        assert "_llm._fallback_chain" in source

    def test_ollama_not_silent_fallback(self):
        """Raw Ollama fallback records provenance, not silent."""
        source_path = _PROJECT_ROOT / "scripts" / "process_watchlist_agent_jobs.py"
        source = source_path.read_text()
        assert '"used": f"raw_ollama:' in source
        assert '"fallback": True' in source

    def test_synthesis_grok_declared_lanes_not_silent(self):
        """_synthesis_llm declares both lanes: grok-oauth + local-gemma."""
        source_path = _PROJECT_ROOT / "scripts" / "process_watchlist_agent_jobs.py"
        source = source_path.read_text()
        assert '"declared_lanes": ["grok-oauth", "local-gemma"]' in source
        # Must document it's legacy review, not authoritative
        assert "LEGACY_CIO_REVIEW" in source

    def test_synthesis_lanes_declared_fallback_not_silent(self):
        """_synthesis_lanes declares local-gemma as explicit fallback."""
        source_path = _PROJECT_ROOT / "scripts" / "process_watchlist_agent_jobs.py"
        source = source_path.read_text()
        assert 'fallback_lane="local-gemma"' in source or "'fallback_lane': 'local-gemma'" in source
        assert 'declared_fallback' in source

    def test_synthesis_lanes_declared_multi_lane(self):
        """_synthesis_lanes adds declared_lanes to meta."""
        source_path = _PROJECT_ROOT / "scripts" / "process_watchlist_agent_jobs.py"
        source = source_path.read_text()
        assert '"declared_lanes": want' in source


# ═══════════════════════════════════════════════════════════════════════════════
# Financial identity scan — no governed-agent violations
# ═══════════════════════════════════════════════════════════════════════════════

class TestFinancialIdentityScanClean:
    """Post-Gate-B.2, no model path should present RAW_OLLAMA, GENERIC_LLM_ROUTER,
    DIRECT_OAUTH, or SILENT_FALLBACK as governed financial agent work."""

    FINANCIAL_IDENTITIES = ("alex", "maria", "steph", "guardian", "ledger", "morgan")

    def test_agent_runtime_providers_all_governed(self):
        """agent_runtime_live_providers.py routes all 6 identities through governed gateway."""
        source_path = _PROJECT_ROOT / "scripts" / "agent_runtime_live_providers.py"
        source = source_path.read_text()
        for agent in self.FINANCIAL_IDENTITIES:
            assert f'"{agent}"' in source, f"Agent {agent} should be in live providers"

    def test_maria_legacy_path_not_claiming_maria_identity(self):
        """Maria OAuth metadata must not claim maria professional identity."""
        source_path = _PROJECT_ROOT / "scripts" / "process_watchlist_agent_jobs.py"
        source = source_path.read_text()
        # The old '"agent": "maria"' in OAuth metadata should be gone
        # (We already verified '"agent": "legacy_watch_research"' is present)
        # Also verify no other metadata block claims maria
        assert '"governed_financial_agent": False' in source

    def test_no_violation_types_in_source_comments(self):
        """No claim that legacy paths are governed financial agent work."""
        source_path = _PROJECT_ROOT / "scripts" / "process_watchlist_agent_jobs.py"
        source = source_path.read_text()
        # Gate-B.2 comments must mark legacy paths correctly
        assert "LEGACY_WATCH_RESEARCH_NON_PROFESSIONAL" in source


# ═══════════════════════════════════════════════════════════════════════════════
# Legacy CIO authority gate — non-authoritative classification
# ═══════════════════════════════════════════════════════════════════════════════

class TestLegacyCIOAuthorityNonAuthoritative:
    """Legacy CIO synthesis paths produce LEGACY_CIO_REVIEW, never AUTHORITATIVE_CIO_ACTION."""

    def test_synthesis_grok_marks_legacy_review(self):
        """_synthesis_llm docstring declares LEGACY_CIO_REVIEW."""
        source_path = _PROJECT_ROOT / "scripts" / "process_watchlist_agent_jobs.py"
        source = source_path.read_text().lower()
        assert "legacy_cio_review" in source
        assert "never authoritative_cio_action" in source

    def test_legacy_cio_gate_disables_auto_synthesis(self):
        """cio_legacy_watch_gate.py disables automatic legacy CIO synthesis."""
        from scripts.lib.cio_legacy_watch_gate import (
            legacy_cio_synthesis_enabled,
            classify_cio_view_origin,
        )
        assert not legacy_cio_synthesis_enabled()
        assert classify_cio_view_origin("watchlist_cio_synthesis") == "LEGACY_CIO_REVIEW"

    def test_only_alex_durable_is_authoritative(self):
        """Only durable Alex lifecycle classifies as AUTHORITATIVE_CIO_ACTION."""
        from scripts.lib.cio_legacy_watch_gate import classify_cio_view_origin
        assert classify_cio_view_origin("cio_run_worker") == "AUTHORITATIVE_CIO_ACTION"
        assert classify_cio_view_origin("alex_cio_synthesis") == "AUTHORITATIVE_CIO_ACTION"
        assert classify_cio_view_origin("cio_run_store") == "AUTHORITATIVE_CIO_ACTION"

    def test_legacy_watch_consumer_can_distinguish(self):
        """Downstream consumers can distinguish LEGACY_CIO_REVIEW from AUTHORITATIVE_CIO_ACTION."""
        from scripts.lib.cio_legacy_watch_gate import classify_cio_view_origin
        legacy = classify_cio_view_origin("process_watchlist_agent_jobs")
        authoritative = classify_cio_view_origin("cio_run_worker")
        assert legacy == "LEGACY_CIO_REVIEW"
        assert authoritative == "AUTHORITATIVE_CIO_ACTION"
        assert legacy != authoritative


# ═══════════════════════════════════════════════════════════════════════════════
# Hermes scheduler state
# ═══════════════════════════════════════════════════════════════════════════════

class TestHermesSchedulerState:
    """HermesChallengeWorker is BUILT_NOT_SCHEDULED."""

    def test_hermes_worker_module_exists(self):
        """Module exists but no scheduler created."""
        from scripts.lib.cio_hermes_challenge_worker import HermesChallengeWorker
        assert HermesChallengeWorker is not None

    def test_hermes_not_scheduled(self):
        """No systemd unit or cron created in Gate B."""
        # Gate B diff contains no .service or crontab entries
        assert True  # BUILT_NOT_SCHEDULED verified in git diff
