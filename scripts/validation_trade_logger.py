#!/usr/bin/env python3
"""validation_trade_logger.py — canonical wrapper over the legacy simulated trade logger/storage.

Operator-facing term: simulated VALIDATION trade. Legacy storage is the `paper_trades` table and
the `paper_trade_logger` module (kept for backward compatibility). This wrapper changes NO behavior
— it only exposes validation-named entry points over the existing sandbox/simulated logger.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paper_trade_logger as _legacy   # legacy storage adapter (paper_trades table)

# Canonical validation-named aliases (same functions, same storage).
open_validation_trade = _legacy.open_paper_trade
close_validation_trade = _legacy.close_paper_trade
get_open_validation_positions = _legacy.get_open_positions
get_validation_pnl_summary = _legacy.get_pnl_summary

LEGACY_TABLE = "paper_trades"
LEGACY_MODULE = "paper_trade_logger"

__all__ = ["open_validation_trade", "close_validation_trade", "get_open_validation_positions",
           "get_validation_pnl_summary", "LEGACY_TABLE", "LEGACY_MODULE"]
