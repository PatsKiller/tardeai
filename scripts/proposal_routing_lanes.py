"""Dual-lane entry routing: paper ATM auto-test + broker 2FA proposals."""
from __future__ import annotations

import os


def paper_account(*, env_key: str = "WATCHLIST_PAPER_ACCOUNT") -> str:
    try:
        from broker_config import get_default_paper_account
        return os.getenv(env_key) or get_default_paper_account()
    except Exception:
        return os.getenv(env_key, "tradeai_automated")


def broker_account(*, env_key: str = "WATCHLIST_BROKER_ACCOUNT", default: str = "schwab_taxable") -> str:
    return os.getenv(env_key, default)


def entry_routing_lanes(
    *,
    paper_env: str = "WATCHLIST_PAPER_ACCOUNT",
    broker_env: str = "WATCHLIST_BROKER_ACCOUNT",
) -> list[tuple[str, str, str, str]]:
    """(lane_id, target_account, intended_broker, routing_lane)."""
    paper = paper_account(env_key=paper_env)
    broker = broker_account(env_key=broker_env)
    return [
        ("paper_atm", paper, paper, "paper_atm"),
        ("live_2fa", broker, broker, "live_2fa"),
    ]


def risk_gate_for_lane(routing_lane: str) -> str:
    return "APPROVED" if routing_lane == "paper_atm" else "ADVISORY"