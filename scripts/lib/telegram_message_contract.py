"""Stable import name for the canonical Telegram message contract."""
try:
    from .message_contract import *  # type: ignore # noqa: F401,F403
except ImportError:  # direct scripts/lib imports
    from message_contract import *  # noqa: F401,F403
