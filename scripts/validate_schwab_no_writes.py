#!/usr/bin/env python3
"""validate_schwab_no_writes.py — SHIM (Stage 2b SB-1, 2026-06-12).

The "no writes exist" invariant was retired deliberately: SB-1 created ONE fenced write path
(operator-approved; see docs/brokers/stage2b-write-pilot-spec.md). The successor policy —
"writes exist ONLY behind the full committed stack" — is proven by validate_schwab_write_policy.py.

This shim keeps every existing runner (Stage 2a battery, cron, docs, muscle memory) working:
it executes the new validator and exits with its code.
"""
import runpy
import sys
from pathlib import Path

sys.argv[0] = str(Path(__file__).with_name("validate_schwab_write_policy.py"))
runpy.run_path(sys.argv[0], run_name="__main__")
