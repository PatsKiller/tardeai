"""Process-wide L2 read runtime for ActiveTrader — the single owner in the read plane.

Holds the ONE QuoteGateway + SubscriptionManager + L2FeatureService + FirePerfTracker the
read API reports from. Built lazily and fail-closed: when OpenD/the SDK is unavailable the
gateway honestly reports NOT connected (never fabricates connected/subscribed/fresh).

DESIRED subscriptions are restored from the arm-state file as INTENT ONLY (ARM_INTENT) —
file existence never implies connected/subscribed/fresh/T2/entitled. Read plane only.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ARM_STATE = _REPO_ROOT / "data" / "scalp" / "moomoo_armed_state.json"

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"built": False, "runtime": None}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_commit() -> str:
    """Best-effort build provenance for the read plane (build-meta → git → 'unknown')."""
    meta = _REPO_ROOT / "apps" / "command-center-v3" / "dist" / "build-meta.json"
    try:
        d = json.loads(meta.read_text(encoding="utf-8"))
        for k in ("source_commit", "source_commit_sha", "commit"):
            if d.get(k):
                return str(d[k])
    except Exception:
        pass
    try:
        import subprocess
        r = subprocess.run(["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "unknown"


class L2Runtime:
    def __init__(self, gateway, manager, features, fire_tracker, config):
        self.gateway = gateway
        self.manager = manager
        self.features = features
        self.fire_tracker = fire_tracker
        self.config = config

    def desired_from_state_file(self) -> list[str]:
        """Read DESIRED symbols from the arm-state file (intent only)."""
        try:
            if not _ARM_STATE.is_file():
                return []
            data = json.loads(_ARM_STATE.read_text(encoding="utf-8"))
            armed = data.get("armed") if isinstance(data, dict) else data
            if isinstance(armed, dict):
                return [str(s).upper() for s in armed.keys()]
            if isinstance(armed, list):
                return [str(x.get("symbol") if isinstance(x, dict) else x).upper() for x in armed]
        except Exception:
            return []
        return []


def _build() -> Optional[L2Runtime]:
    try:
        import sys
        sp = str(_REPO_ROOT / "scripts")
        if sp not in sys.path:
            sys.path.insert(0, sp)
        from moomoo.quote_gateway import get_gateway
        from moomoo.subscription_manager import SubscriptionManager
        from moomoo.l2_feature_service import L2FeatureService
        from moomoo.l2_lifecycle_config import load_l2_lifecycle_config
        from active_trader.fire_performance import FirePerfTracker, FirePerfConfig

        cfg = load_l2_lifecycle_config()
        gw = get_gateway()                      # real transport; honest 'down' when unavailable
        mgr = SubscriptionManager(gw, cfg)
        try:
            mgr.refresh_quota(_now_iso())
        except Exception:
            pass
        features = L2FeatureService(gw, mgr)
        ftracker = FirePerfTracker(FirePerfConfig(
            fresh_fire_seconds=cfg.fresh_fire_seconds,
            active_observation_minutes=cfg.active_observation_minutes,
            mark_stale_after_ms=cfg.live_mark_stale_after_ms))
        rt = L2Runtime(gw, mgr, features, ftracker, cfg)
        # restore DESIRED intent only (never connected)
        try:
            mgr.restore_desired_from_state(rt.desired_from_state_file())
        except Exception:
            pass
        return rt
    except Exception:
        return None


def get_runtime() -> Optional[L2Runtime]:
    if _STATE["built"]:
        return _STATE["runtime"]
    with _LOCK:
        if not _STATE["built"]:
            _STATE["runtime"] = _build()
            _STATE["built"] = True
    return _STATE["runtime"]


def reset_for_test() -> None:
    with _LOCK:
        _STATE["built"] = False
        _STATE["runtime"] = None


def set_runtime_for_test(rt: Optional[L2Runtime]) -> None:
    with _LOCK:
        _STATE["runtime"] = rt
        _STATE["built"] = True
