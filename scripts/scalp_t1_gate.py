#!/usr/bin/env python3
"""M3-S6 — T1 entitlement gate + gated runner.

The single choke point that makes it STRUCTURALLY IMPOSSIBLE to compute T1 microstructure metrics on
anything but real-time CONSOLIDATED (SIP) data. Per the M3-S5.5 finding, IEX-only trades/NBBO are a
~2-3% venue sample and would be weaker than the T0 BarPressure fallback — so a T1 metric computed on
IEX-only (or delayed / unentitled) data is not merely inaccurate, it is FORBIDDEN. Every path into the
T1 library goes through `require_consolidated_realtime` and the config `t1.enabled` flag (both must
pass). No feed is entitled today, so the runner refuses at runtime — T1 stays dormant until a
consolidated feed is procured and re-probed green.

No I/O in the gate logic (the entitlement is supplied by the caller/fabric); no order/proposal path.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "market_observations"))

from observation import EntitlementState                          # noqa: E402
import scalp_t1_metrics as t1                                     # noqa: E402

# The ONLY entitlement that authorizes T1 metrics: real-time consolidated (SIP).
# IEX_ONLY (venue-partial), *_DELAYED, HISTORICAL, SCAFFOLD_ONLY, UNAVAILABLE, UNRESOLVED all FORBIDDEN.
T1_REQUIRED_ENTITLEMENT = EntitlementState.SIP_REALTIME


class T1NotEntitled(Exception):
    """Raised whenever T1 metrics are requested without real-time consolidated entitlement (or with the
    t1.enabled flag off). Blocks silent computation on the wrong feed."""


def require_consolidated_realtime(entitlement: EntitlementState) -> None:
    if entitlement != T1_REQUIRED_ENTITLEMENT:
        raise T1NotEntitled(
            f"T1 microstructure requires {T1_REQUIRED_ENTITLEMENT.value} (real-time consolidated SIP); "
            f"got {getattr(entitlement, 'value', entitlement)} — FORBIDDEN (IEX-only/delayed = venue-partial)")


def t1_enabled(cfg: Mapping) -> bool:
    return bool((cfg or {}).get("t1", {}).get("enabled", False))


def t1_ready(cfg: Mapping, entitlement: EntitlementState) -> tuple[bool, str]:
    """(ready, reason). Ready only when BOTH the config flag is on AND the entitlement is SIP_REALTIME."""
    if not t1_enabled(cfg):
        return False, "t1.enabled=false"
    if entitlement != T1_REQUIRED_ENTITLEMENT:
        return False, f"entitlement={getattr(entitlement, 'value', entitlement)}≠SIP_REALTIME"
    return True, "ready"


def compute_t1_snapshot(*, trades: Sequence[Mapping], quotes: Sequence[Mapping],
                        bars: Sequence[Mapping], entitlement: EntitlementState, cfg: Mapping,
                        bucket_volume: Optional[float] = None) -> dict:
    """Gated T1 computation. Raises T1NotEntitled unless t1.enabled AND entitlement==SIP_REALTIME.
    Only then computes TFI / effective-spread / Kyle-λ / VPIN over CONSOLIDATED trades+NBBO."""
    if not t1_enabled(cfg):
        raise T1NotEntitled("t1.enabled=false — T1 disabled by config")
    require_consolidated_realtime(entitlement)                    # hard feed gate
    signed = t1.sign_trades(trades, quotes)
    tcfg = cfg.get("t1", {})
    bv = bucket_volume if bucket_volume is not None else float(tcfg.get("vpin_bucket_volume", 0) or 0)
    return {
        "entitlement": entitlement.value,
        "tfi": t1.trade_flow_imbalance(signed),
        "effective_spread_bps": t1.effective_spread_bps(signed, quotes),
        "kyle_lambda": t1.kyle_lambda(bars),
        "vpin": t1.vpin(signed, bv, int(tcfg.get("vpin_buckets", 50))) if bv > 0 else None,
        "n_trades": len(trades),
        "data_tier": "T1",
    }


def resolve_t1_entitlement_from_capability(provider: str) -> EntitlementState:
    """Read the consolidated-feed entitlement from the evidence-based capability matrix (M3-S5.5).
    Returns the provider's TRADE entitlement (SIP_REALTIME only when a consolidated feed is procured).
    Today every candidate is IEX_ONLY / UNAVAILABLE → the gate stays closed."""
    try:
        from providers import capability
        from observation import ObservationType
    except ModuleNotFoundError:
        from market_observations.providers import capability
        from market_observations.observation import ObservationType
    return capability(provider, ObservationType.TRADE).entitlement
