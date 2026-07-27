#!/usr/bin/env python3
"""M3-S5.5 — multi-source observation fabric (orchestrator).

Gated by `multi_source.enabled` (default FALSE). With the flag OFF the fabric returns nothing and the
existing single-source T0 path is used unchanged — current behavior is exactly reproducible. With the
flag ON (tests / dry-run) it: (1) fans out per-provider fetches under bounded concurrency, (2)
normalizes them into immutable Observations, (3) deterministically arbitrates one canonical source per
symbol with full provenance. It does NOT change IGN or trigger formulas, does NOT enable T1/T2 merely
because adapters exist, and source availability can NEVER raise a score or pass a failing trigger.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

try:
    from observation import ObservationType
    from concurrency import Task, ConcurrencyLimits, run_bounded
    from arbitration import select_market_source, AuthorityPolicy
    from providers import AlpacaBarProvider, ProviderAdapter, CAPABILITY_MATRIX, ALPACA_T1_CLASSIFICATION
except ModuleNotFoundError:
    from .observation import ObservationType
    from .concurrency import Task, ConcurrencyLimits, run_bounded
    from .arbitration import select_market_source, AuthorityPolicy
    from .providers import AlpacaBarProvider, ProviderAdapter, CAPABILITY_MATRIX, ALPACA_T1_CLASSIFICATION


def is_enabled(cfg: dict) -> bool:
    return bool((cfg or {}).get("multi_source", {}).get("enabled", False))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MultiSourceFabric:
    """Acquires + arbitrates canonical bar snapshots. Only wired providers actually fetch; others are
    capability-declared (see providers.CAPABILITY_MATRIX) and contribute nothing until wired."""

    def __init__(self, cfg: dict, providers: Optional[list[ProviderAdapter]] = None,
                 policy: Optional[AuthorityPolicy] = None, limits: Optional[ConcurrencyLimits] = None):
        self.cfg = cfg or {}
        ms = self.cfg.get("multi_source", {})
        # limits from config with safe defaults
        lc = ms.get("concurrency", {})
        self.limits = limits or ConcurrencyLimits(
            global_max=int(lc.get("global_max", 8)),
            per_provider_max=dict(lc.get("per_provider_max", {"alpaca": 4, "yahoo": 2, "schwab": 2, "moomoo": 1})),
            task_timeout_s=float(lc.get("task_timeout_s", 10.0)),
            max_retries=int(lc.get("max_retries", 2)),
            breaker_threshold=int(lc.get("breaker_threshold", 3)),
        )
        self.policy = policy or AuthorityPolicy()
        # default wired provider = Alpaca bars at the configured T0 feed (iex — matches the profile feed)
        feed = self.cfg.get("data", {}).get("feed", "iex")
        self.providers = providers if providers is not None else [AlpacaBarProvider(feed=feed)]

    def acquire_bar_snapshot(self, symbols: list[str]) -> dict:
        """Return {symbol: {selected, provenance}} for the canonical bar per symbol. When the flag is
        off, returns {} (caller keeps the existing single-source path)."""
        if not is_enabled(self.cfg):
            return {}
        now = _now_iso()
        tasks, index = [], []
        for sym in symbols:
            for prov in self.providers:
                tasks.append(Task(provider=prov.name, key=f"{sym}:bar",
                                  fn=(lambda p=prov, s=sym: p.fetch_bar(s, now))))
                index.append((sym, prov.name))
        results, runner = run_bounded(tasks, self.limits)
        # group observations by symbol
        by_symbol: dict[str, list] = {s: [] for s in symbols}
        for (sym, _prov), obs in zip(index, results):
            if obs is not None:
                by_symbol[sym].append(obs)
        out = {}
        for sym in symbols:
            sel = select_market_source(ObservationType.BAR, by_symbol[sym], self.policy)
            out[sym] = {
                "selected": sel.selected.to_dict() if sel.selected else None,
                "provenance": {
                    "selected_source": sel.selected_source, "tier": sel.tier,
                    "tier_downgraded": sel.tier_downgraded, "rejected": sel.rejected,
                    "conflict": sel.conflict, "directive": sel.directive,
                    "policy_version": self.policy.version, "selection_reason": sel.selection_reason,
                },
            }
        self._last_counters = {p: vars(c) for p, c in runner.counters.items()}
        self._last_max_concurrency = runner.max_concurrency
        return out

    def capability_matrix(self) -> dict:
        return {p: {t.value: {"entitlement": c.entitlement.value, "tier": c.tier.value, "note": c.note}
                    for t, c in caps.items()} for p, caps in CAPABILITY_MATRIX.items()}

    @staticmethod
    def alpaca_t1_classification() -> str:
        return ALPACA_T1_CLASSIFICATION
