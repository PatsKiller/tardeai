"""Maturity control plane — learning, Phase 11 promotion, notification, autonomy.

READ_ONLY_ADVISORY. Never grants broker / order / stop / 2FA / risk authority.
"""
from __future__ import annotations

AUTHORITY = "READ_ONLY_ADVISORY"
AUTO_PROMOTION_TO_TRADING = False
CONTRACT = "maturity-control-plane-v1"
