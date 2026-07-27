#!/usr/bin/env python3
"""M3-S5.5 — provider adapters + evidence-based capability matrix.

Each provider declares its capability PER observation type (entitlement state + tier), from the
M3-S5.5 entitlement probes / code inventory — NOT from optimism. Only Alpaca (IEX bars) is wired live
here; Yahoo/Schwab/Moomoo are capability-declared and their market-signal fetch is NOT wired in this
shadow stage (returns None / raises EntitlementError). No provider is granted a tier merely because
an adapter file exists.

SAFETY: no credentials or raw auth-bearing responses are logged. Schwab reads (when later wired) go
through the managed-token `scripts/schwab_transport.py` (NOT the racy `SchwabAdapter`). Moomoo goes
through the Stage-0 client boundary only — never a direct OpenD connection from here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

try:
    from observation import (Observation, ObservationType, EntitlementState, FreshnessState,
                             QualityState, DataTier, make_observation)
except ModuleNotFoundError:
    from .observation import (Observation, ObservationType, EntitlementState, FreshnessState,
                              QualityState, DataTier, make_observation)


@dataclass(frozen=True)
class Capability:
    entitlement: EntitlementState
    tier: DataTier
    note: str = ""


OT = ObservationType
ES = EntitlementState
DT = DataTier

# ── Evidence-based capability matrix (M3-S5.5 probes 2026-07-27 + code inventory) ──
# Alpaca: live probe — IEX bars/trades/quotes = 200 realtime; SIP = 403 recent (delayed only).
# Yahoo: yfinance daily/5m/15m historical; 1m capped ~7d (unsuitable); never broker truth.
# Schwab: schwab_transport managed-token reads — authoritative for Schwab account/position/order;
#         quotes = cross-check only. Electronic-entry eligibility UNRESOLVED (no adapter surfaces it).
# Moomoo: OpenD NOT configured on host (example config only, health registry empty) → SCAFFOLD_ONLY.
CAPABILITY_MATRIX: dict[str, dict[ObservationType, Capability]] = {
    "alpaca": {
        OT.BAR: Capability(ES.IEX_ONLY, DT.T0, "IEX realtime bars; SIP bars delayed-only (403 recent)"),
        OT.TRADE: Capability(ES.IEX_ONLY, DT.T1_VENUE, "IEX realtime trades (venue-partial ~2-3%); NOT consolidated SIP"),
        OT.QUOTE: Capability(ES.IEX_ONLY, DT.T1_VENUE, "IEX realtime NBBO (venue-partial); no consolidated SIP realtime"),
        OT.ORDER_BOOK: Capability(ES.UNAVAILABLE, DT.T2, "no depth on Alpaca"),
        OT.ACCOUNT_FACT: Capability(ES.AVAILABLE_REALTIME, DT.T0, "Alpaca authoritative for Alpaca (paper) accounts"),
        OT.POSITION_FACT: Capability(ES.AVAILABLE_REALTIME, DT.T0, "Alpaca positions (own resources)"),
        OT.ORDER_FACT: Capability(ES.AVAILABLE_REALTIME, DT.T0, "Alpaca orders (own resources)"),
    },
    "yahoo": {
        OT.BAR: Capability(ES.AVAILABLE_HISTORICAL, DT.T0, "daily/5m/15m historical; 1m capped ~7d → UNSUITABLE for 20-session profile"),
        OT.TRADE: Capability(ES.UNAVAILABLE, DT.T1_VENUE, "no tape"),
        OT.QUOTE: Capability(ES.AVAILABLE_DELAYED, DT.T0, "delayed quote/context; degraded fallback only"),
        OT.ORDER_BOOK: Capability(ES.UNAVAILABLE, DT.T2, ""),
        OT.ACCOUNT_FACT: Capability(ES.UNAVAILABLE, DT.T0, "never broker truth"),
        OT.POSITION_FACT: Capability(ES.UNAVAILABLE, DT.T0, "never broker truth"),
        OT.ORDER_FACT: Capability(ES.UNAVAILABLE, DT.T0, "never broker truth"),
    },
    "schwab": {
        OT.BAR: Capability(ES.AVAILABLE_HISTORICAL, DT.T0, "get_price_history — tier-2 chart fallback when Alpaca lacks bars"),
        OT.TRADE: Capability(ES.UNAVAILABLE, DT.T1_VENUE, ""),
        OT.QUOTE: Capability(ES.AVAILABLE_REALTIME, DT.T0, "schwab_transport get_quote — cross-check, not primary market data"),
        OT.ORDER_BOOK: Capability(ES.UNAVAILABLE, DT.T2, ""),
        OT.ACCOUNT_FACT: Capability(ES.AVAILABLE_REALTIME, DT.T0, "authoritative for Schwab accounts (managed tokens)"),
        OT.POSITION_FACT: Capability(ES.AVAILABLE_REALTIME, DT.T0, "authoritative for Schwab positions"),
        OT.ORDER_FACT: Capability(ES.AVAILABLE_REALTIME, DT.T0, "authoritative for Schwab orders; electronic-entry eligibility UNRESOLVED"),
    },
    "polygon": {
        # M3-S6 T1 candidate. Probed 2026-07-27: FREE plan → /v3/trades, /v3/quotes, last-trade,
        # last-NBBO all 403 NOT_AUTHORIZED; only EOD aggregate bars (delayed ~days). A paid upgrade
        # (Developer/Advanced) would make TRADE/QUOTE = SIP_REALTIME → unblocks T1.
        OT.BAR: Capability(ES.AVAILABLE_HISTORICAL, DT.T0, "free-plan EOD aggregate bars (delayed)"),
        OT.TRADE: Capability(ES.UNAVAILABLE, DT.T1, "403 NOT_AUTHORIZED — needs paid plan for consolidated tape"),
        OT.QUOTE: Capability(ES.UNAVAILABLE, DT.T1, "403 NOT_AUTHORIZED — needs paid plan for consolidated NBBO"),
        OT.ORDER_BOOK: Capability(ES.UNAVAILABLE, DT.T2, ""),
        OT.ACCOUNT_FACT: Capability(ES.UNAVAILABLE, DT.T0, "not a broker"),
        OT.POSITION_FACT: Capability(ES.UNAVAILABLE, DT.T0, "not a broker"),
        OT.ORDER_FACT: Capability(ES.UNAVAILABLE, DT.T0, "not a broker"),
    },
    "moomoo": {
        OT.BAR: Capability(ES.SCAFFOLD_ONLY, DT.T2, "OpenD not configured; Stage-0 scaffold only"),
        OT.TRADE: Capability(ES.SCAFFOLD_ONLY, DT.T2, "intended T2 tape — not proven"),
        OT.QUOTE: Capability(ES.SCAFFOLD_ONLY, DT.T2, "intended T2 quote — not proven"),
        OT.ORDER_BOOK: Capability(ES.SCAFFOLD_ONLY, DT.T2, "intended T2 depth — requires gateway+entitlement+sequence"),
        OT.ACCOUNT_FACT: Capability(ES.SCAFFOLD_ONLY, DT.T2, ""),
        OT.POSITION_FACT: Capability(ES.SCAFFOLD_ONLY, DT.T2, ""),
        OT.ORDER_FACT: Capability(ES.SCAFFOLD_ONLY, DT.T2, ""),
    },
}

ALPACA_T1_CLASSIFICATION = "T1_IEX_ONLY"   # real-time trades+NBBO exist but IEX-only (NOT consolidated SIP)


def capability(provider: str, t: ObservationType) -> Capability:
    return CAPABILITY_MATRIX.get(provider, {}).get(t, Capability(ES.UNRESOLVED, DT.T0, "unknown"))


class ProviderAdapter:
    """One protocol. `fetch_bar` returns an Observation or None; providers that aren't wired here
    return None (with their declared entitlement) rather than fabricate data."""
    name: str = "base"

    def capability(self, t: ObservationType) -> Capability:
        return capability(self.name, t)

    async def fetch_bar(self, symbol: str, now_iso: str) -> Optional[Observation]:
        return None


class AlpacaBarProvider(ProviderAdapter):
    """Wired: real-time IEX 1-minute latest bar (bounded, read-only; keys from env, never logged)."""
    name = "alpaca"

    def __init__(self, feed: str = "iex"):
        self.feed = feed

    def _keys(self):
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
        except Exception:
            pass
        k = os.environ.get("ALPACA_PAPER_API_KEY") or os.environ.get("ALPACA_API_KEY") or ""
        s = os.environ.get("ALPACA_PAPER_SECRET_KEY") or os.environ.get("ALPACA_SECRET_KEY") or ""
        return k, s

    def _blocking_fetch(self, symbol: str) -> Optional[dict]:
        import requests
        k, s = self._keys()
        if not k or not s:
            return None
        r = requests.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/bars/latest",
                         headers={"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s},
                         params={"feed": self.feed}, timeout=15)
        if r.status_code == 403:
            from .concurrency import EntitlementError  # type: ignore
            raise EntitlementError(f"alpaca {self.feed} bars: 403")
        if r.status_code != 200:
            return None
        return (r.json() or {}).get("bar")

    async def fetch_bar(self, symbol: str, now_iso: str) -> Optional[Observation]:
        import asyncio
        bar = await asyncio.to_thread(self._blocking_fetch, symbol)
        if not bar:
            return None
        cap = self.capability(OT.BAR)
        payload = {"o": bar.get("o"), "h": bar.get("h"), "l": bar.get("l"),
                   "c": bar.get("c"), "v": bar.get("v"), "close": bar.get("c")}
        return make_observation(
            source_system="alpaca", symbol=symbol, observation_type=OT.BAR, payload=payload,
            provider_at=bar.get("t"), observed_at=bar.get("t"), received_at=now_iso, normalized_at=now_iso,
            entitlement_state=cap.entitlement, feed=self.feed,
            freshness_state=FreshnessState.FRESH, quality_state=QualityState.DEGRADED,  # IEX = venue-partial
            data_tier=DT.T0)
