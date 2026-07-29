"""Versioned loader for the Moomoo L2 subscription-lifecycle config.

Pure config: no OpenD connection, no secrets, no order path. Falls back to the shipped
example so tests and cold hosts never crash. All knobs are read-only policy.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXAMPLE = _REPO_ROOT / "config" / "moomoo_l2_lifecycle.example.yaml"

SCHEMA_VERSION = "moomoo-l2-lifecycle-v1"


@dataclass(frozen=True)
class L2LifecycleConfig:
    schema_version: str
    min_subscription_dwell_seconds: float
    default_post_fire_retention_seconds: float
    default_arm_ttl_seconds: float
    max_concurrent_l2_symbols: int
    book_stale_after_ms: float
    tape_stale_after_ms: float
    subtypes: tuple[str, ...]                       # requested subtypes per L2 arm
    quota_reservations: Mapping[str, int]
    eligible_setup_states: tuple[str, ...]
    eligible_fsm_states: tuple[str, ...]
    eligible_lanes: tuple[str, ...]
    priority: Mapping[str, tuple[str, ...]]
    setup_l2_requirements: Mapping[str, Mapping[str, Any]]
    fresh_fire_seconds: float
    active_observation_minutes: float
    live_mark_source_priority: tuple[str, ...]
    live_mark_poll_interval_ms: int
    live_mark_stale_after_ms: float
    raw: Mapping[str, Any] = field(repr=False, default_factory=dict)

    @property
    def reserved_units_total(self) -> int:
        return int(sum(int(v) for v in self.quota_reservations.values()))

    def units_per_symbol(self) -> int:
        """Quota units one L2 arm consumes = number of requested subtypes."""
        return max(1, len(self.subtypes))


def _tuple(seq: Any, upper: bool = False) -> tuple[str, ...]:
    if not isinstance(seq, (list, tuple)):
        return ()
    out = [str(x) for x in seq]
    return tuple(s.upper() for s in out) if upper else tuple(out)


def resolve_config_path(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("MOOMOO_L2_LIFECYCLE_CONFIG", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    live = _REPO_ROOT / "config" / "moomoo_l2_lifecycle.yaml"
    return live.resolve() if live.is_file() else DEFAULT_EXAMPLE.resolve()


def load_l2_lifecycle_config(path: str | Path | None = None) -> L2LifecycleConfig:
    p = resolve_config_path(path)
    data: dict[str, Any] = {}
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    lc = data.get("lifecycle") if isinstance(data.get("lifecycle"), dict) else {}
    subs = data.get("subtypes") if isinstance(data.get("subtypes"), dict) else {}
    resv = data.get("quota_reservations") if isinstance(data.get("quota_reservations"), dict) else {}
    ap = data.get("arm_policy") if isinstance(data.get("arm_policy"), dict) else {}
    prio = ap.get("priority") if isinstance(ap.get("priority"), dict) else {}
    fl = data.get("fire_lifecycle") if isinstance(data.get("fire_lifecycle"), dict) else {}
    lm = data.get("live_mark") if isinstance(data.get("live_mark"), dict) else {}
    l2req = data.get("setup_l2_requirements") if isinstance(data.get("setup_l2_requirements"), dict) else {}

    # requested subtypes, canonical order QUOTE, ORDER_BOOK, TICKER, K_1M
    requested: list[str] = []
    for key, name in (("quote", "QUOTE"), ("order_book", "ORDER_BOOK"),
                      ("ticker", "TICKER"), ("k_1m", "K_1M")):
        if bool(subs.get(key, key in ("order_book", "ticker", "quote"))):
            requested.append(name)

    return L2LifecycleConfig(
        schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        min_subscription_dwell_seconds=float(lc.get("min_subscription_dwell_seconds", 60)),
        default_post_fire_retention_seconds=float(lc.get("default_post_fire_retention_seconds", 120)),
        default_arm_ttl_seconds=float(lc.get("default_arm_ttl_seconds", 180)),
        max_concurrent_l2_symbols=int(lc.get("max_concurrent_l2_symbols", 8)),
        book_stale_after_ms=float(lc.get("book_stale_after_ms", 2500)),
        tape_stale_after_ms=float(lc.get("tape_stale_after_ms", 3000)),
        subtypes=tuple(requested) or ("QUOTE", "ORDER_BOOK", "TICKER"),
        quota_reservations={str(k): int(v) for k, v in resv.items()} or {
            "held_positions": 4, "operator_selected": 4, "active_fires": 6,
            "reconnect_recovery": 4, "emergency": 2},
        eligible_setup_states=_tuple(ap.get("eligible_setup_states", ["ARMED"]), upper=True),
        eligible_fsm_states=_tuple(ap.get("eligible_fsm_states", ["PULLBACK", "ARMED"]), upper=True),
        eligible_lanes=_tuple(ap.get("eligible_lanes", ["IGN_45", "IGN_60", "IGN_75", "IGN_ACCEL"]), upper=True),
        priority={k: _tuple(v) for k, v in prio.items()},
        setup_l2_requirements={str(k): dict(v) for k, v in l2req.items() if isinstance(v, Mapping)},
        fresh_fire_seconds=float(fl.get("fresh_fire_seconds", 60)),
        active_observation_minutes=float(fl.get("active_observation_minutes", 30)),
        live_mark_source_priority=_tuple(lm.get("source_priority",
                                         ["moomoo_subscribed", "approved_current_quote_provider"])),
        live_mark_poll_interval_ms=int(lm.get("poll_interval_ms", 1500)),
        live_mark_stale_after_ms=float(lm.get("mark_stale_after_ms", 6000)),
        raw=data,
    )
