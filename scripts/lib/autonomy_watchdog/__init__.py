"""Autonomous intelligence watchdog — observe, classify, record, alert.

READ_ONLY_ADVISORY. Never places trades or grants authority.
"""
from scripts.lib.autonomy_watchdog.engine import run_cycle

__all__ = ["run_cycle"]
