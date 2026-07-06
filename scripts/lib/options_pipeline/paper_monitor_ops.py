"""paper_monitor_ops.py — PR4 pipeline hook + runtime reporting for lifecycle monitor."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
RUNTIME_PATH = PROJECT_ROOT / "data" / "runtime" / "options_paper_monitor_last.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_market_hours() -> bool:
    """Equity session open (Schwab market hours API with ET weekday fallback)."""
    try:
        import schwab_transport
        eq = (schwab_transport.get_market_hours().get("markets") or {}).get("equity") or {}
        if eq.get("isOpen") is not None:
            return bool(eq.get("isOpen"))
        if eq.get("is_open") is not None:
            return bool(eq.get("is_open"))
    except Exception:
        pass
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= mins <= 16 * 60


def should_run_lifecycle(cfg: dict) -> tuple[bool, str]:
    if not cfg.get("enabled", True):
        return False, "disabled in config"
    if is_market_hours():
        return True, "market_hours"
    if cfg.get("after_hours_snapshot"):
        return True, "after_hours_snapshot"
    return False, "after_hours_skipped"


def write_runtime_report(report: dict) -> None:
    RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {**report, "written_at": _now_iso()}
    tmp = RUNTIME_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(RUNTIME_PATH)


def run_pipeline_hook(*, dry_run: bool = False, cfg: dict | None = None) -> dict:
    """Called from run_options_monitor.py — proposals refresh + lifecycle monitor."""
    from lib.options_pipeline.paper_position_monitor import load_config, run_monitor
    config = cfg or load_config()
    ok, reason = should_run_lifecycle(config)
    if not ok:
        out = {"ok": True, "skipped": True, "reason": reason}
        write_runtime_report(out)
        return out
    report = run_monitor(dry_run=dry_run, cfg=config)
    report["pipeline_reason"] = reason
    write_runtime_report(report)
    return report


def run_alpaca_reconcile(*, dry_run: bool = False) -> dict:
    """Read-only Alpaca paper options reconcile (fills/closes → monitored registry)."""
    from lib.options_pipeline.alpaca_paper import reconcile_fills
    return reconcile_fills(dry_run=dry_run)