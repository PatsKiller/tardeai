#!/usr/bin/env python3
"""validation_submitter.py — canonical wrapper over the existing safe sandbox/simulated submitter.

Operator-facing term: VALIDATION submit (sandbox/simulated). Legacy storage/adapter is
`proposal_paper_submitter` (kept for backward compatibility). This wrapper changes NO behavior and
weakens NO gate — it only exposes validation-named entry points. Sandbox/simulated only; never the
live broker path. Live trading is unchanged (operator confirmation + 2FA).
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proposal_paper_submitter as _legacy   # legacy adapter (alpaca_paper sandbox)

# Canonical validation-named aliases (same functions, same safety gates).
validation_check_gates = _legacy.check_gates
submit_validation = _legacy.submit_paper          # sandbox/simulated submit via the existing path
dry_run_validation_bracket = _legacy.dry_run_bracket

LEGACY_MODULE = "proposal_paper_submitter"
SANDBOX_ACCOUNT = "tradeai_automated"   # account identifier only

__all__ = ["validation_check_gates", "submit_validation", "dry_run_validation_bracket",
           "LEGACY_MODULE", "SANDBOX_ACCOUNT"]
