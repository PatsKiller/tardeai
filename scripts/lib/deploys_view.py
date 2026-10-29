#!/usr/bin/env python3
"""Deploys status for Command Center: the latest DeployOnMainReceipt@v1 plus the deploy STOP latch (2026-10-27).

Read-only projection behind ``GET /api/v2/ops/deploys`` (Home "Deploys" line and drawer). It replaces the retired
release-train summary (operator directive 2026-10-27: "Remove everything about the old train ... from the Command
Center and from the code"). Mergify merges; the host ``deploy_on_main`` poller promotes and writes one receipt per
decision under ``<state_root>/data/runtime/deploy_on_main/`` (``latest.json`` is the newest; AGENTS.md §25.10).

Each source fails soft and honestly: a missing or unreadable receipt is ``null`` with an ``error`` string, never a
fabricated "ok". The STOP read-back is ``deploy_stop.status()`` (the same latch the poller and emergency promote
refuse on). Nothing here writes, touches git, GitHub, systemd, a broker or a credential.

AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = "DeploysStatus@v1"
RECEIPT_SCHEMA = "DeployOnMainReceipt@v1"
PATH = "/api/v2/ops/deploys"
RECENT_LIMIT = 5
DEFAULT_STATE_ROOT = Path.home() / "trade-ai-releases" / "persistent-state"
RECEIPTS_REL = Path("data") / "runtime" / "deploy_on_main"


def receipts_dir() -> Path:
    """Same resolution as ``deploy_on_main.receipts_dir`` (TRADEAI_STATE_ROOT, else the persistent-state default)."""
    root = Path(os.environ.get("TRADEAI_STATE_ROOT") or DEFAULT_STATE_ROOT)
    return root / RECEIPTS_REL


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_receipt(path: Path) -> Optional[dict]:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(body, dict) or body.get("schema") != RECEIPT_SCHEMA:
        return None
    return body


def latest_receipt(rdir: Optional[Path] = None) -> tuple[Optional[dict], Optional[str]]:
    rdir = rdir or receipts_dir()
    latest = rdir / "latest.json"
    if not latest.exists():
        return None, f"no receipt yet ({latest})"
    body = _read_receipt(latest)
    if body is None:
        return None, f"latest receipt unreadable or not {RECEIPT_SCHEMA}"
    return body, None


def recent_receipts(rdir: Optional[Path] = None, limit: int = RECENT_LIMIT) -> list[dict]:
    """Newest first, skipping ``latest.json`` and unreadable rows. Names start with a UTC stamp, so they sort."""
    rdir = rdir or receipts_dir()
    try:
        names = sorted((p for p in rdir.glob("*.json") if p.name != "latest.json"), key=lambda p: p.name, reverse=True)
    except OSError:
        return []
    out: list[dict] = []
    for p in names:
        body = _read_receipt(p)
        if body is not None:
            out.append(body)
        if len(out) >= limit:
            break
    return out


def _stop_status(stop_root: Optional[Path]) -> tuple[Optional[dict], Optional[str]]:
    try:
        try:
            from scripts.lib import deploy_stop as DS
        except ImportError:  # pragma: no cover - served layout: PYTHONPATH=<release>/scripts
            from lib import deploy_stop as DS  # type: ignore[no-redef]
        return DS.status(stop_root), None
    except Exception as exc:  # noqa: BLE001 - surfaced, never hidden
        return None, f"{type(exc).__name__}: {str(exc)[:160]}"


def build(*, rdir: Optional[Path] = None, stop_root: Optional[Path] = None, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    latest, latest_err = latest_receipt(rdir)
    stop, stop_err = _stop_status(stop_root)
    latch = ((stop or {}).get("latch") or {}).get("status")
    return {
        "schema": SCHEMA,
        "generated_at": _iso(now),
        "latest": latest,
        "latest_error": latest_err,
        "recent": recent_receipts(rdir),
        "stop": stop,
        "stop_error": stop_err,
        "stop_effective": latch in ("SET", "UNREADABLE") if latch else None,
        "how": "Mergify merges green PRs; the host deploy_on_main poller promotes main when STOP is clear.",
    }


def handle(base_path: str, method: str) -> Optional[tuple[int, dict]]:
    if base_path.rstrip("/") != PATH:
        return None
    if method != "GET":
        return 405, {"ok": False, "error": "method_not_allowed", "allowed": ["GET"]}
    return 200, {"ok": True, "data": build()}
